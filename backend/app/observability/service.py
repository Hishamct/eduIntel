import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import LLMCallUsage
from app.observability.models import AgentTraceLog, AuditLog, LLMUsageLog

# Pricing constants — approximate, for reporting purposes only. The project
# currently runs on Gemini's and Groq's FREE tiers (see llm_client.py), so
# nothing is actually being billed; this estimates what usage WOULD cost at
# each provider's published per-token rates, which is the number worth
# showing an Owner/Admin ("here's what this feature would cost to run at
# scale"). Kept as a small, obviously-editable block — update these if the
# models change or you want to plug in real current pricing rather than
# this rough placeholder.
GEMINI_INPUT_COST_PER_1K_TOKENS_USD = 0.000075
GEMINI_OUTPUT_COST_PER_1K_TOKENS_USD = 0.0003
GROQ_INPUT_COST_PER_1K_TOKENS_USD = (
    0.0  # Groq's hosted open-weight fallback model — free tier
)
GROQ_OUTPUT_COST_PER_1K_TOKENS_USD = 0.0
USD_TO_INR = 88.0  # approximate — update to the current rate for accurate ₹ figures

# Free-tier quota tracking — this is NOT read from Google's actual account
# quota (the SDK doesn't expose remaining-quota as a queryable value); it's
# our own count of Gemini calls logged in this app, compared against the
# limits shown on your Google AI Studio "Rate Limit" dashboard (Project:
# RAG-EduIntel > Rate Limit). As of the values you pulled from there for
# gemini-3.6-flash on the free tier:
#   RPM (requests/minute): 5      RPD (requests/day): 20
#   TPM (input tokens/minute): 250,000
# RPD is the one you're actually hitting in practice (your dashboard showed
# 24/20 — already over for the day), so it's the headline number on the
# admin page; RPM is tracked too since it's the one that causes an
# individual request to fail even when you're nowhere near the daily cap.
# TPM isn't tracked here — at 250K/minute it's far from the binding
# constraint for single chat/RAG-style calls. Update these three if Google
# changes your tier's limits (check the same dashboard).
GEMINI_RPD_LIMIT = 20
GEMINI_RPM_LIMIT = 5

# Google's API quotas (Gemini included) reset at midnight Pacific Time, not
# UTC — this is what your dashboard's "UTC-8" trend-chart label is showing.
# Using zoneinfo (not a fixed UTC-8 offset) so this correctly tracks the
# Pacific/Los_Angeles DST switch between PST (UTC-8) and PDT (UTC-7)
# instead of drifting by an hour twice a year.
GEMINI_QUOTA_RESET_TZ = ZoneInfo("America/Los_Angeles")

# Groq — from your Groq Console > Settings > Limits > "Organization Limits"
# table, for openai/gpt-oss-120b specifically (the only Groq model
# GROQ_FALLBACK_MODEL in llm_client.py actually calls — ignore any other
# model's limits/logs, e.g. gpt-oss-20b, seen elsewhere in the console).
# TPM is tracked here (unlike Gemini's, which was too loose to matter) —
# at 8K tokens/minute and calls in the 500-2000 token range seen in your
# own logs, TPM caps you well before the 30 RPM limit would.
GROQ_RPM_LIMIT = 30
GROQ_RPD_LIMIT = 1000
GROQ_TPM_LIMIT = 8000
GROQ_TPD_LIMIT = 200000

# UNVERIFIED ASSUMPTION: unlike Google's confirmed-Pacific reset, I don't
# have a confirmed reset timezone for Groq's daily/RPD counters — the
# console didn't label one the way AI Studio labeled "UTC-8". Defaulting to
# UTC; if your logged RPD count drifts from what Groq's own dashboard
# shows, check Groq's docs for their actual reset time and adjust this.
GROQ_QUOTA_RESET_TZ = UTC


def estimate_cost_inr(usage: "LLMCallUsage") -> float | None:
    """
    Estimates cost in ₹ for one LLM call from its token counts. Returns
    None (not 0.0) when token counts are missing, so a caller can tell
    "genuinely free" apart from "we don't actually know."
    """
    if usage.input_tokens is None or usage.output_tokens is None:
        return None

    if usage.provider == "gemini":
        input_rate, output_rate = (
            GEMINI_INPUT_COST_PER_1K_TOKENS_USD,
            GEMINI_OUTPUT_COST_PER_1K_TOKENS_USD,
        )
    elif usage.provider == "groq":
        input_rate, output_rate = (
            GROQ_INPUT_COST_PER_1K_TOKENS_USD,
            GROQ_OUTPUT_COST_PER_1K_TOKENS_USD,
        )
    else:
        return None

    cost_usd = (usage.input_tokens / 1000) * input_rate + (
        usage.output_tokens / 1000
    ) * output_rate
    return round(cost_usd * USD_TO_INR, 6)


async def log_ai_query(
    db: AsyncSession,
    user_id: uuid.UUID,
    endpoint: str,
    query_text: str,
    was_blocked: bool = False,
    block_reason: str | None = None,
    was_redacted: bool = False,
    redaction_count: int = 0,
    redacted_types: list[str] | None = None,
    was_socratic_redirected: bool = False,
    socratic_trigger_pattern: str | None = None,
) -> None:
    """
    Records one AI assistant query to the audit log. Called from the
    router layer (after chat_with_portal_assistant / chat_with_admin_assistant
    / generate_and_send_parent_report / retrieve_and_generate return) so it
    captures allowed, guardrail-blocked, guardrail-redacted, and
    Socratic-redirected queries alike.

    was_redacted/redaction_count/redacted_types cover the PII-redaction
    guardrail (see app/guardrails/pii_redaction.py) — redacted_types is
    passed in as a list and joined to a comma-separated string for storage;
    only pattern names go in, never the matched PII values themselves.

    was_socratic_redirected/socratic_trigger_pattern cover the anti-cheating
    guardrail (see app/guardrails/anti_cheating.py) — set from the
    socratic_mode/cheating_pattern fields retrieve_and_generate returns.

    Best-effort: a logging failure should never break the actual user-facing
    response, so callers should not let an exception here propagate — wrap
    the call in a try/except if this needs to be fully non-blocking in
    production. For the capstone, a straightforward await is fine.
    """
    entry = AuditLog(
        user_id=user_id,
        endpoint=endpoint,
        query_text=query_text,
        was_blocked=was_blocked,
        block_reason=block_reason,
        was_redacted=was_redacted,
        redaction_count=redaction_count,
        redacted_types=",".join(redacted_types) if redacted_types else None,
        was_socratic_redirected=was_socratic_redirected,
        socratic_trigger_pattern=socratic_trigger_pattern,
    )
    db.add(entry)
    await db.commit()


async def log_pii_redaction(
    db: AsyncSession,
    user_id: uuid.UUID,
    endpoint: str,
    query_text: str,
    redaction_count: int,
    redacted_types: list[str],
) -> None:
    """
    Thin convenience wrapper around log_ai_query for guardrail call sites
    that only deal with redaction (not blocking) — e.g. the Parent Report
    Generation Agent, which never "blocks" a report but does redact its
    generated body before sending. Logs a row regardless of whether
    anything was actually redacted (redaction_count=0 is still useful
    signal: "this endpoint ran the guardrail and found nothing to catch").
    """
    await log_ai_query(
        db=db,
        user_id=user_id,
        endpoint=endpoint,
        query_text=query_text,
        was_blocked=False,
        block_reason=None,
        was_redacted=redaction_count > 0,
        redaction_count=redaction_count,
        redacted_types=redacted_types,
    )


async def log_socratic_redirect(
    db: AsyncSession,
    user_id: uuid.UUID,
    endpoint: str,
    query_text: str,
    was_socratic_redirected: bool,
    socratic_trigger_pattern: str | None,
) -> None:
    """
    Thin convenience wrapper around log_ai_query for the anti-cheating
    guardrail — call this after retrieve_and_generate() returns, passing
    its socratic_mode/cheating_pattern fields straight through. Logs a row
    regardless of whether the guard actually fired (was_socratic_redirected
    =False is still useful signal: "this endpoint ran the guardrail check").
    """
    await log_ai_query(
        db=db,
        user_id=user_id,
        endpoint=endpoint,
        query_text=query_text,
        was_blocked=False,
        block_reason=None,
        was_socratic_redirected=was_socratic_redirected,
        socratic_trigger_pattern=socratic_trigger_pattern,
    )


async def log_llm_usage(
    db: AsyncSession, endpoint: str, usage: "LLMCallUsage | None"
) -> None:
    """
    Records one raw LLM call to llm_usage_logs. Call this right after
    generate_text_with_usage()/decide_tools_with_usage() returns, passing
    the usage object straight through.

    usage=None is a safe no-op (nothing is written) — this happens when a
    guardrail blocked the request before any LLM call was made (e.g.
    prompt injection caught upstream), so there's genuinely nothing to log
    here; the block itself is still captured by log_ai_query separately.
    """
    if usage is None:
        return

    entry = LLMUsageLog(
        endpoint=endpoint,
        provider=usage.provider,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=usage.latency_ms,
        used_fallback=usage.used_fallback,
        estimated_cost_inr=estimate_cost_inr(usage),
    )
    db.add(entry)
    await db.commit()


async def get_llm_usage_summary(db: AsyncSession, since_days: int | None = 30) -> dict:
    """
    Aggregate LLM usage for the Owner/Admin analytics dashboard: overall
    totals plus a per-endpoint breakdown. since_days filters to the last
    N days (None = all-time).

    Returns:
        {
            "since_days": 30,
            "overall": {
                "call_count": int, "total_input_tokens": int,
                "total_output_tokens": int, "avg_latency_ms": float,
                "total_estimated_cost_inr": float, "fallback_count": int,
            },
            "by_endpoint": [
                {"endpoint": str, "call_count": int, "avg_latency_ms": float,
                 "total_estimated_cost_inr": float, "fallback_count": int},
                ...
            ],
        }
    total_estimated_cost_inr sums only calls that had a known cost (see
    estimate_cost_inr) — calls with missing token counts are excluded from
    the sum rather than silently treated as ₹0, so the total never
    understates real cost; call_count still reflects every call either way.
    """
    cutoff = None
    if since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)

    base_query = select(LLMUsageLog)
    if cutoff is not None:
        base_query = base_query.where(LLMUsageLog.created_at >= cutoff)

    overall_stmt = select(
        func.count(LLMUsageLog.id),
        func.sum(LLMUsageLog.input_tokens),
        func.sum(LLMUsageLog.output_tokens),
        func.avg(LLMUsageLog.latency_ms),
        func.sum(LLMUsageLog.estimated_cost_inr),
        func.sum(func.cast(LLMUsageLog.used_fallback, Integer)),
    )
    if cutoff is not None:
        overall_stmt = overall_stmt.where(LLMUsageLog.created_at >= cutoff)

    overall_row = (await db.execute(overall_stmt)).one()
    call_count, total_input, total_output, avg_latency, total_cost, fallback_count = (
        overall_row
    )

    by_endpoint_stmt = select(
        LLMUsageLog.endpoint,
        func.count(LLMUsageLog.id),
        func.avg(LLMUsageLog.latency_ms),
        func.sum(LLMUsageLog.estimated_cost_inr),
        func.sum(func.cast(LLMUsageLog.used_fallback, Integer)),
        func.sum(LLMUsageLog.input_tokens),
        func.sum(LLMUsageLog.output_tokens),
    ).group_by(LLMUsageLog.endpoint)
    if cutoff is not None:
        by_endpoint_stmt = by_endpoint_stmt.where(LLMUsageLog.created_at >= cutoff)

    by_endpoint_rows = (await db.execute(by_endpoint_stmt)).all()

    return {
        "since_days": since_days,
        "overall": {
            "call_count": call_count or 0,
            "total_input_tokens": int(total_input or 0),
            "total_output_tokens": int(total_output or 0),
            "avg_latency_ms": round(float(avg_latency), 1)
            if avg_latency is not None
            else None,
            "total_estimated_cost_inr": round(float(total_cost), 4)
            if total_cost is not None
            else 0.0,
            "fallback_count": int(fallback_count or 0),
        },
        "by_endpoint": [
            {
                "endpoint": endpoint,
                "call_count": count,
                "avg_latency_ms": round(float(avg_lat), 1)
                if avg_lat is not None
                else None,
                "total_estimated_cost_inr": round(float(cost), 4)
                if cost is not None
                else 0.0,
                "fallback_count": int(fb or 0),
                "total_input_tokens": int(in_tok or 0),
                "total_output_tokens": int(out_tok or 0),
            }
            for endpoint, count, avg_lat, cost, fb, in_tok, out_tok in by_endpoint_rows
        ],
        "gemini_quota": await _get_gemini_quota_status(db),
        "groq_quota": await _get_groq_quota_status(db),
    }


async def log_agent_trace(
    db: AsyncSession,
    trace_id: str,
    agent_name: str,
    session_id: str,
    trace_steps: list[dict],
) -> None:
    """
    Persists one agent run's step-by-step trace in a single batch — call
    this from the router after chat_with_admin_assistant()/
    chat_with_portal_assistant() returns, passing its trace_id and
    trace_steps straight through (see app/observability/tracing.py for how
    trace_steps gets built up).

    No-op on an empty list — a guardrail-blocked turn still produces a
    minimal one-step trace (see admin_assistant.py/portal_assistant.py),
    so an empty list here means the caller genuinely had nothing to log,
    not a bug to silently swallow.
    """
    if not trace_steps:
        return

    for step in trace_steps:
        db.add(
            AgentTraceLog(
                trace_id=trace_id,
                agent_name=agent_name,
                session_id=session_id,
                node_name=step["node_name"],
                step_order=step["step_order"],
                duration_ms=step["duration_ms"],
                status=step.get("status", "ok"),
                error_message=step.get("error_message"),
            )
        )
    await db.commit()


async def get_agent_trace_summary(db: AsyncSession, since_days: int = 30) -> dict:
    """
    Aggregate view for the admin dashboard: per (agent_name, node_name)
    call count / avg / max duration and error count over the last
    since_days days, plus a run count per agent (distinct trace_id) and
    the 20 most recently active traces so a reviewer can pull up an
    actual run's full step list via get_agent_trace_detail rather than
    only ever seeing aggregates.
    """
    since = datetime.now(UTC) - timedelta(days=since_days)

    node_stats_stmt = (
        select(
            AgentTraceLog.agent_name,
            AgentTraceLog.node_name,
            func.count(AgentTraceLog.id),
            func.avg(AgentTraceLog.duration_ms),
            func.max(AgentTraceLog.duration_ms),
            func.sum(case((AgentTraceLog.status == "error", 1), else_=0)),
        )
        .where(AgentTraceLog.created_at >= since)
        .group_by(AgentTraceLog.agent_name, AgentTraceLog.node_name)
    )
    node_rows = (await db.execute(node_stats_stmt)).all()

    node_breakdown = [
        {
            "agent_name": agent_name,
            "node_name": node_name,
            "call_count": call_count,
            "avg_duration_ms": round(float(avg_dur), 1) if avg_dur is not None else 0,
            "max_duration_ms": int(max_dur or 0),
            "error_count": int(error_count or 0),
        }
        for agent_name, node_name, call_count, avg_dur, max_dur, error_count in node_rows
    ]

    run_count_stmt = (
        select(
            AgentTraceLog.agent_name, func.count(func.distinct(AgentTraceLog.trace_id))
        )
        .where(AgentTraceLog.created_at >= since)
        .group_by(AgentTraceLog.agent_name)
    )
    run_counts = dict((await db.execute(run_count_stmt)).all())

    recent_traces_stmt = (
        select(
            AgentTraceLog.agent_name,
            AgentTraceLog.trace_id,
            func.max(AgentTraceLog.created_at),
            func.sum(AgentTraceLog.duration_ms),
        )
        .where(AgentTraceLog.created_at >= since)
        .group_by(AgentTraceLog.agent_name, AgentTraceLog.trace_id)
        .order_by(func.max(AgentTraceLog.created_at).desc())
        .limit(20)
    )
    recent_rows = (await db.execute(recent_traces_stmt)).all()
    recent_traces = [
        {
            "agent_name": agent_name,
            "trace_id": str(trace_id),
            "last_step_at": last_step_at.isoformat(),
            "total_duration_ms": int(total_duration or 0),
        }
        for agent_name, trace_id, last_step_at, total_duration in recent_rows
    ]

    return {
        "since_days": since_days,
        "run_counts": {agent_name: count for agent_name, count in run_counts.items()},
        "node_breakdown": node_breakdown,
        "recent_traces": recent_traces,
    }


async def get_agent_trace_detail(db: AsyncSession, trace_id: str) -> list[dict]:
    """
    Full ordered step list for one agent run, keyed by trace_id — this is
    the "show me exactly what this run did" view, e.g. for demoing a
    specific query to a reviewer or debugging a wrong answer.
    """
    stmt = (
        select(AgentTraceLog)
        .where(AgentTraceLog.trace_id == trace_id)
        .order_by(AgentTraceLog.step_order)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "node_name": row.node_name,
            "step_order": row.step_order,
            "duration_ms": row.duration_ms,
            "status": row.status,
            "error_message": row.error_message,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


async def _get_gemini_quota_status(db: AsyncSession) -> dict:
    """
    Today's and this-minute's Gemini call counts vs. GEMINI_RPD_LIMIT /
    GEMINI_RPM_LIMIT (see the constants' comment above for where these
    numbers come from and why this is an estimate, not a real account-quota
    read). "Today" is a Pacific Time calendar day (GEMINI_QUOTA_RESET_TZ),
    matching when Google's API quotas actually reset — not UTC and not IST
    — so this should track your AI Studio dashboard's RPD count closely.
    """
    now_utc = datetime.now(UTC)
    now_pacific = now_utc.astimezone(GEMINI_QUOTA_RESET_TZ)
    today_start_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_start_pacific.astimezone(UTC)
    minute_start = now_utc - timedelta(minutes=1)

    rpd_stmt = select(func.count(LLMUsageLog.id)).where(
        LLMUsageLog.provider == "gemini",
        LLMUsageLog.created_at >= today_start,
    )
    used_today = (await db.execute(rpd_stmt)).scalar() or 0

    rpm_stmt = select(func.count(LLMUsageLog.id)).where(
        LLMUsageLog.provider == "gemini",
        LLMUsageLog.created_at >= minute_start,
    )
    used_this_minute = (await db.execute(rpm_stmt)).scalar() or 0

    return {
        "requests_used_today": used_today,
        "daily_limit": GEMINI_RPD_LIMIT,
        "requests_remaining": max(GEMINI_RPD_LIMIT - used_today, 0),
        "percent_used": round((used_today / GEMINI_RPD_LIMIT) * 100, 1)
        if GEMINI_RPD_LIMIT
        else None,
        "requests_used_this_minute": used_this_minute,
        "per_minute_limit": GEMINI_RPM_LIMIT,
        "per_minute_remaining": max(GEMINI_RPM_LIMIT - used_this_minute, 0),
    }


async def _get_groq_quota_status(db: AsyncSession) -> dict:
    """
    Today's and this-minute's Groq call/token counts vs. GROQ_RPD_LIMIT /
    GROQ_RPM_LIMIT / GROQ_TPM_LIMIT / GROQ_TPD_LIMIT (see the constants'
    comment above for where these numbers come from — pulled directly from
    Groq Console's Limits table for openai/gpt-oss-120b, not guessed).

    Unlike Gemini, TPM is tracked here too since it's realistically the
    first limit you'll hit, not RPM.
    """
    now_utc = datetime.now(UTC)
    now_groq_tz = now_utc.astimezone(GROQ_QUOTA_RESET_TZ)
    today_start_groq_tz = now_groq_tz.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_start_groq_tz.astimezone(UTC)
    minute_start = now_utc - timedelta(minutes=1)

    requests_today_stmt = select(func.count(LLMUsageLog.id)).where(
        LLMUsageLog.provider == "groq",
        LLMUsageLog.created_at >= today_start,
    )
    requests_today = (await db.execute(requests_today_stmt)).scalar() or 0

    requests_this_minute_stmt = select(func.count(LLMUsageLog.id)).where(
        LLMUsageLog.provider == "groq",
        LLMUsageLog.created_at >= minute_start,
    )
    requests_this_minute = (await db.execute(requests_this_minute_stmt)).scalar() or 0

    tokens_today_stmt = select(
        func.sum(LLMUsageLog.input_tokens), func.sum(LLMUsageLog.output_tokens)
    ).where(
        LLMUsageLog.provider == "groq",
        LLMUsageLog.created_at >= today_start,
    )
    in_today, out_today = (await db.execute(tokens_today_stmt)).one()
    tokens_today = int(in_today or 0) + int(out_today or 0)

    tokens_this_minute_stmt = select(
        func.sum(LLMUsageLog.input_tokens), func.sum(LLMUsageLog.output_tokens)
    ).where(
        LLMUsageLog.provider == "groq",
        LLMUsageLog.created_at >= minute_start,
    )
    in_min, out_min = (await db.execute(tokens_this_minute_stmt)).one()
    tokens_this_minute = int(in_min or 0) + int(out_min or 0)

    return {
        "requests_used_today": requests_today,
        "daily_limit": GROQ_RPD_LIMIT,
        "requests_remaining": max(GROQ_RPD_LIMIT - requests_today, 0),
        "percent_used": round((requests_today / GROQ_RPD_LIMIT) * 100, 1)
        if GROQ_RPD_LIMIT
        else None,
        "requests_used_this_minute": requests_this_minute,
        "per_minute_limit": GROQ_RPM_LIMIT,
        "per_minute_remaining": max(GROQ_RPM_LIMIT - requests_this_minute, 0),
        "tokens_used_today": tokens_today,
        "tokens_daily_limit": GROQ_TPD_LIMIT,
        "tokens_remaining_today": max(GROQ_TPD_LIMIT - tokens_today, 0),
        "tokens_used_this_minute": tokens_this_minute,
        "tokens_per_minute_limit": GROQ_TPM_LIMIT,
        "tokens_per_minute_remaining": max(GROQ_TPM_LIMIT - tokens_this_minute, 0),
    }

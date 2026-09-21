import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """
    Records every AI assistant query — who asked, which endpoint, what they
    asked, whether the guardrail layer blocked it (e.g. a detected
    prompt-injection attempt), whether it redacted PII from the response
    before it went out (e.g. a Parent Report body), and whether it switched
    the doubt-answering tutor into Socratic mode (e.g. a detected
    "just give me the answer" request). This is the audit trail a reviewer
    would expect for "how would you know if this was misused?" — it's
    append-only from the application's side; nothing reads or mutates these
    rows except for reporting.

    was_blocked/block_reason, was_redacted/redaction_count/redacted_types,
    and was_socratic_redirected/socratic_trigger_pattern are independent
    guardrail outcomes — a query can hit any combination of them (though in
    practice a blocked query never reaches generation, so it won't also be
    redacted or Socratic-redirected).

    redacted_types is a comma-joined list of PII pattern names (see
    app/guardrails/pii_redaction.py's PII_TYPE_LABELS) — never the raw
    matched values. The whole point of this table is to prove redaction
    happened without itself becoming a place PII leaks into.

    socratic_trigger_pattern is the matched regex pattern from
    app/guardrails/anti_cheating.py — useful for a reviewer-facing "which
    phrasing is triggering this most often" breakdown, not sensitive data.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    was_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    was_redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redacted_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    was_socratic_redirected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    socratic_trigger_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class LLMUsageLog(Base):
    """
    Records one raw LLM call (one generate_text_with_usage()/
    decide_tools_with_usage() invocation from app/core/llm_client.py) —
    latency, token counts, which provider actually served it (Gemini vs.
    the Groq rate-limit fallback), and an estimated ₹ cost. Feeds the
    "LLM cost/latency tracking surfaced in owner analytics" deliverable.

    Deliberately separate from AuditLog: one user-facing query can trigger
    more than one LLM call (the Admin Assistant makes two — decide_tools
    then generate — per turn), so this is call-level, not query-level.
    endpoint tags which call site it came from (e.g.
    "admin-assistant/decide_tools", "admin-assistant/generate",
    "portal-assistant/generate", "rag/query", "reports/parent-report").

    estimated_cost_inr is nullable: it's None whenever token counts weren't
    available on the response (e.g. the decide_tools rate-limit degrade
    path in llm_client.py returns no usage metadata) rather than being
    silently reported as ₹0, which would understate real cost.
    """

    __tablename__ = "llm_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "gemini" | "groq"
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    used_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estimated_cost_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class AgentTraceLog(Base):
    """
    One row per LangGraph node execution within a single agent "turn" —
    the step-by-step execution path for one chat_with_admin_assistant()/
    chat_with_portal_assistant() call, tied together by trace_id so all of
    one turn's steps can be pulled back in order.

    Deliberately separate from LLMUsageLog (call-level) and AuditLog
    (guardrail-decision-level, flat across a turn): this is the piece that
    actually answers "what did the agent do, in what order, and how long
    did each step take" — the thing a LangGraph-based "agentic AI" demo
    needs in order to not be a black box.

    Rows are written once per turn, after the whole graph run finishes —
    see app/observability/tracing.py's traced_node decorator, which
    accumulates steps on the LangGraph state as nodes run (node functions
    have no db session of their own — same pattern already used for
    LLMCallUsage), and app/observability/service.py: log_agent_trace,
    which persists the accumulated steps in one batch once a db session is
    available in the router.

    Known limitation: a node that raises aborts the whole graph run before
    any state is returned, so a crashed turn currently leaves no trace at
    all rather than a partial one — worth knowing if a trace "goes
    missing" for a request you know errored; not a bug, see tracing.py.
    """

    __tablename__ = "agent_trace_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "admin-assistant" | "portal-assistant"
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ok"
    )  # "ok" | "blocked"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

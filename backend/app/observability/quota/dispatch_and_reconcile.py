"""
Stage 7.2 Tx 2A (Durable Dispatch), Tx 2B (Attempt Outcome), Tx 3 (Finalization / UNKNOWN_USAGE),
Tx 4 (Manual Operator Settlement), and Tx 5 (Late Provider Arrival & Differential Adjustments).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.quota.errors import (
    AttemptNotFoundError,
    IdempotencyConflictError,
    InvalidStateTransitionError,
    ReservationExpiredError,
)
from app.observability.quota.locking import (
    compute_attempt_totals,
    load_reservation_routing,
    lock_daily_usage_row,
    lock_reservation_and_attempts,
    to_adjustment_snapshot,
    to_attempt_snapshot,
    to_reservation_snapshot,
    upsert_and_lock_level2,
)
from app.observability.quota.policy import MissingUsageContext, MissingUsagePolicyResolver
from app.observability.quota.pricing import (
    TOKENS_PER_RATE_UNIT,
    calculate_cost_breakdown,
    extract_model_rate_spec,
    quantize_inr,
    resolve_active_pricing_version,
    resolve_pricing_version_by_id,
)
from app.observability.quota.types import (
    MAX_TOTAL_OP_TOKENS,
    AttemptDispatchRequest,
    AttemptSnapshot,
    ReconciliationResult,
    ReservationSnapshot,
    validate_non_empty_text,
    validate_token_count,
)
from app.observability.quota_models import (
    AIFinancialAdjustment,
    AIProviderAttempt,
    AITokenReservation,
    TenantAIQuota,
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
)

logger = logging.getLogger(__name__)


def _utc_now(as_of: datetime | None) -> datetime:
    """Return validated timezone-aware UTC timestamp."""
    if as_of is None:
        return datetime.now(UTC)
    if as_of.tzinfo is None:
        raise ValueError("as_of timestamp must be timezone-aware")
    return as_of.astimezone(UTC)


def _require_dispatched_at(res: AITokenReservation) -> datetime:
    """Validate and return non-null dispatched_at timestamp without assert."""
    if res.dispatched_at is None:
        raise InvalidStateTransitionError(
            f"Reservation {res.id} is missing required dispatched_at timestamp",
            current_state=res.status,
            target_state=res.status,
            entity_type="reservation",
        )
    return res.dispatched_at


def _find_attempt(attempts: list[AIProviderAttempt], attempt_id: uuid.UUID, res_id: uuid.UUID) -> AIProviderAttempt:
    """Locate target attempt inside a locked reservation's attempt list."""
    for att in attempts:
        if att.id == attempt_id:
            return att
    raise AttemptNotFoundError(attempt_id, res_id)


async def _check_provider_request_id_conflict(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    provider: str,
    provider_request_id: str,
) -> AIProviderAttempt | None:
    """Return any existing attempt in this tenant matching `(provider, provider_request_id)`."""
    stmt = select(AIProviderAttempt).where(
        AIProviderAttempt.institution_id == institution_id,
        AIProviderAttempt.provider == provider,
        AIProviderAttempt.provider_request_id == provider_request_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_policy_name(db: AsyncSession, institution_id: uuid.UUID) -> str:
    """Read `missing_usage_policy` string for an institution without locking Level 1."""
    stmt = select(TenantAIQuota.missing_usage_policy).where(
        TenantAIQuota.institution_id == institution_id
    )
    return str((await db.execute(stmt)).scalar_one())


def _apply_attempt_delta_to_ledgers(
    *,
    res: AITokenReservation,
    daily: TenantDailyAIUsage,
    cat: TenantDailyCategoryUsage,
    attempts: list[AIProviderAttempt],
) -> None:
    """
    Synchronize confirmed (`actual_*` / `committed_*`) and uncertain hold buckets
    across reservation, daily total, and daily category rollups using exact deltas.
    """
    totals = compute_attempt_totals(attempts)

    delta_in = totals.confirmed_input_tokens - res.actual_input_tokens
    delta_out = totals.confirmed_output_tokens - res.actual_output_tokens
    delta_tot = totals.confirmed_total_tokens - res.actual_total_tokens
    delta_cost = totals.confirmed_cost_inr - res.actual_cost_inr

    res.actual_input_tokens = totals.confirmed_input_tokens
    res.actual_output_tokens = totals.confirmed_output_tokens
    res.actual_total_tokens = totals.confirmed_total_tokens
    res.actual_cost_inr = totals.confirmed_cost_inr

    daily.committed_total_tokens += delta_tot
    daily.committed_cost_inr += delta_cost
    cat.committed_input_tokens += delta_in
    cat.committed_output_tokens += delta_out
    cat.committed_total_tokens += delta_tot
    cat.committed_cost_inr += delta_cost


def _set_uncertain_hold(
    *,
    res: AITokenReservation,
    daily: TenantDailyAIUsage,
    cat: TenantDailyCategoryUsage,
    new_uncertain_tokens: int,
    new_uncertain_cost: Decimal,
) -> None:
    """Adjust `uncertain_*` hold buckets cleanly by exact delta against reservation."""
    delta_tok = new_uncertain_tokens - res.uncertain_tokens_held
    delta_cost = new_uncertain_cost - res.uncertain_cost_held_inr

    res.uncertain_tokens_held = new_uncertain_tokens
    res.uncertain_cost_held_inr = new_uncertain_cost

    daily.uncertain_reserved_tokens += delta_tok
    daily.uncertain_exposure_cost_inr += delta_cost
    cat.uncertain_reserved_tokens += delta_tok


async def begin_provider_dispatch_tx(
    db: AsyncSession,
    request: AttemptDispatchRequest,
    *,
    as_of: datetime | None = None,
) -> tuple[ReservationSnapshot, AttemptSnapshot]:
    """
    Execute Tx 2A: Persist durable DISPATCHED boundary & attempt before provider network I/O.
    """
    now = _utc_now(as_of)
    routing = await load_reservation_routing(
        db, institution_id=request.institution_id, reservation_id=request.reservation_id
    )
    daily = await lock_daily_usage_row(
        db, institution_id=request.institution_id, usage_date=routing.usage_date
    )
    res, attempts = await lock_reservation_and_attempts(
        db, institution_id=request.institution_id, reservation_id=request.reservation_id
    )

    if request.provider_request_id is not None:
        existing_req = await _check_provider_request_id_conflict(
            db,
            institution_id=request.institution_id,
            provider=request.provider,
            provider_request_id=request.provider_request_id,
        )
        if existing_req is not None:
            if existing_req.reservation_id != res.id:
                raise IdempotencyConflictError(
                    "provider_request_id already belongs to a different reservation",
                    institution_id=request.institution_id,
                    idempotency_key=request.provider_request_id,
                    mismatched_fields=("reservation_id",),
                )
            if (
                existing_req.model != request.model
                or existing_req.is_fallback != request.is_fallback
                or existing_req.is_retry != request.is_retry
                or existing_req.estimated_tokens != request.estimated_tokens
            ):
                raise IdempotencyConflictError(
                    "provider_request_id reused on same reservation with conflicting attempt parameters",
                    institution_id=request.institution_id,
                    idempotency_key=request.provider_request_id,
                    mismatched_fields=("model", "estimated_tokens", "flags"),
                )
            return to_reservation_snapshot(res), to_attempt_snapshot(existing_req)

    if res.status == "RESERVED":
        if now >= res.expires_at:
            raise ReservationExpiredError(res.id)
        res.status = "DISPATCHED"
        res.dispatched_at = max(now, res.created_at)
    elif res.status != "DISPATCHED":
        raise InvalidStateTransitionError(
            f"Cannot dispatch attempt while reservation is in status {res.status!r}",
            current_state=res.status,
            target_state="DISPATCHED",
            entity_type="reservation",
        )

    pv = (
        await resolve_pricing_version_by_id(db, request.pricing_version)
        if request.pricing_version is not None
        else await resolve_active_pricing_version(db, as_of=now)
    )
    if request.estimated_input_tokens is not None and request.estimated_output_tokens is not None:
        if request.estimated_input_tokens + request.estimated_output_tokens != request.estimated_tokens:
            raise ValueError(
                "estimated_input_tokens + estimated_output_tokens must equal estimated_tokens"
            )
        est_cost = calculate_cost_breakdown(
            pv,
            provider=request.provider,
            model=request.model,
            input_tokens=request.estimated_input_tokens,
            output_tokens=request.estimated_output_tokens,
        ).total_cost_inr
    else:
        spec = extract_model_rate_spec(pv, provider=request.provider, model=request.model)
        max_rate = max(spec.input_inr_per_1k, spec.output_inr_per_1k)
        est_cost = quantize_inr((Decimal(request.estimated_tokens) / TOKENS_PER_RATE_UNIT) * max_rate)

    next_seq = (attempts[-1].attempt_sequence + 1) if attempts else 1
    att_dispatched_at = max(now, _require_dispatched_at(res))

    attempt = AIProviderAttempt(
        id=uuid.uuid4(),
        institution_id=request.institution_id,
        reservation_id=res.id,
        logical_operation_id=res.logical_operation_id,
        attempt_sequence=next_seq,
        provider=request.provider,
        model=request.model,
        is_fallback=request.is_fallback,
        is_retry=request.is_retry,
        status="DISPATCHED",
        provider_request_id=request.provider_request_id,
        pricing_version=pv.version_id,
        estimated_tokens=request.estimated_tokens,
        estimated_cost_inr=est_cost,
        dispatched_at=att_dispatched_at,
    )
    db.add(attempt)

    if request.is_fallback:
        daily.fallback_count += 1
    daily.version += 1
    await db.flush()

    logger.info(
        "quota_provider_attempt_dispatched",
        extra={
            "institution_id": str(request.institution_id),
            "reservation_id": str(res.id),
            "attempt_id": str(attempt.id),
            "attempt_sequence": next_seq,
            "provider": request.provider,
            "model": request.model,
            "is_fallback": request.is_fallback,
            "is_retry": request.is_retry,
            "pricing_version": pv.version_id,
        },
    )
    return to_reservation_snapshot(res), to_attempt_snapshot(attempt)


async def record_attempt_outcome_tx(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    reservation_id: uuid.UUID,
    attempt_id: uuid.UUID,
    status: str,
    policy_resolver: MissingUsagePolicyResolver,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    provider_request_id: str | None = None,
    error_classification: str | None = None,
    latency_ms: int | None = None,
    as_of: datetime | None = None,
) -> tuple[ReservationSnapshot, AttemptSnapshot]:
    """
    Execute Tx 2B: Record terminal or uncertain outcome for a single `DISPATCHED` attempt.
    """
    if status not in ("SUCCEEDED", "FAILED_CONFIRMED", "TIMEOUT_UNCERTAIN"):
        raise ValueError(f"Unsupported Tx 2B attempt outcome status={status!r}")
    if latency_ms is not None and (isinstance(latency_ms, bool) or latency_ms < 0):
        raise ValueError("latency_ms must be a non-negative integer")
    if provider_request_id is not None:
        provider_request_id = validate_non_empty_text(
            provider_request_id, field_name="provider_request_id", max_length=255
        )
    if error_classification is not None:
        error_classification = validate_non_empty_text(
            error_classification, field_name="error_classification", max_length=60
        )

    now = _utc_now(as_of)
    routing = await load_reservation_routing(
        db, institution_id=institution_id, reservation_id=reservation_id
    )
    daily, _ = await upsert_and_lock_level2(
        db,
        institution_id=institution_id,
        usage_date=routing.usage_date,
        usage_category=routing.usage_category,
    )
    res, attempts = await lock_reservation_and_attempts(
        db, institution_id=institution_id, reservation_id=reservation_id
    )
    attempt = _find_attempt(attempts, attempt_id, res.id)

    if attempt.status != "DISPATCHED":
        same_outcome = (
            attempt.status == status
            and attempt.input_tokens == (0 if status == "FAILED_CONFIRMED" and input_tokens is None else input_tokens)
            and attempt.output_tokens == (0 if status == "FAILED_CONFIRMED" and output_tokens is None else output_tokens)
            and (provider_request_id is None or attempt.provider_request_id == provider_request_id)
        )
        if same_outcome:
            return to_reservation_snapshot(res), to_attempt_snapshot(attempt)
        raise InvalidStateTransitionError(
            f"Attempt {attempt.id} already in status {attempt.status!r}; cannot transition to {status!r}",
            current_state=attempt.status,
            target_state=status,
            entity_type="attempt",
        )

    if res.status != "DISPATCHED":
        raise InvalidStateTransitionError(
            f"Cannot update attempt while reservation is in status {res.status!r}",
            current_state=res.status,
            target_state="DISPATCHED",
            entity_type="reservation",
        )

    if provider_request_id is not None and provider_request_id != attempt.provider_request_id:
        conflict = await _check_provider_request_id_conflict(
            db,
            institution_id=institution_id,
            provider=attempt.provider,
            provider_request_id=provider_request_id,
        )
        if conflict is not None and conflict.id != attempt.id:
            raise IdempotencyConflictError(
                "provider_request_id already belongs to another attempt",
                institution_id=institution_id,
                idempotency_key=provider_request_id,
                mismatched_fields=("attempt_id",),
            )
        attempt.provider_request_id = provider_request_id

    completed_at = max(now, attempt.dispatched_at)

    if status == "SUCCEEDED":
        if input_tokens is None or output_tokens is None:
            policy_name = await _load_policy_name(db, institution_id)
            decision = policy_resolver.resolve_missing_usage(
                MissingUsageContext(
                    institution_id=institution_id,
                    reservation_id=res.id,
                    attempt_id=attempt.id,
                    policy_name=policy_name,
                    attempt_status=status,
                    estimated_input_tokens=res.estimated_input_tokens,
                    reserved_output_tokens=res.reserved_output_tokens,
                    total_reserved_tokens=res.total_reserved_tokens,
                )
            )
            if decision.action == "UNKNOWN_USAGE":
                attempt.status = "TIMEOUT_UNCERTAIN"
                attempt.error_classification = decision.reason or "MISSING_USAGE_METADATA"
                attempt.latency_ms = latency_ms
                attempt.completed_at = completed_at
                daily.version += 1
                await db.flush()
                return to_reservation_snapshot(res), to_attempt_snapshot(attempt)
            in_tok = validate_token_count(decision.settled_input_tokens or 0, field_name="settled_input_tokens")
            out_tok = validate_token_count(decision.settled_output_tokens or 0, field_name="settled_output_tokens")
        else:
            in_tok = validate_token_count(input_tokens, field_name="input_tokens")
            out_tok = validate_token_count(output_tokens, field_name="output_tokens")

        pv = await resolve_pricing_version_by_id(db, attempt.pricing_version)
        cost = calculate_cost_breakdown(
            pv,
            provider=attempt.provider,
            model=attempt.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
        attempt.status = "SUCCEEDED"
        attempt.input_tokens = in_tok
        attempt.output_tokens = out_tok
        attempt.actual_cost_inr = cost.total_cost_inr
    elif status == "FAILED_CONFIRMED":
        in_tok = validate_token_count(input_tokens or 0, field_name="input_tokens")
        out_tok = validate_token_count(output_tokens or 0, field_name="output_tokens")
        if in_tok == 0 and out_tok == 0:
            actual_cost = Decimal("0.0000")
        else:
            pv = await resolve_pricing_version_by_id(db, attempt.pricing_version)
            actual_cost = calculate_cost_breakdown(
                pv,
                provider=attempt.provider,
                model=attempt.model,
                input_tokens=in_tok,
                output_tokens=out_tok,
            ).total_cost_inr
        attempt.status = "FAILED_CONFIRMED"
        attempt.input_tokens = in_tok
        attempt.output_tokens = out_tok
        attempt.actual_cost_inr = actual_cost
        attempt.error_classification = error_classification
    else:  # TIMEOUT_UNCERTAIN
        attempt.status = "TIMEOUT_UNCERTAIN"
        attempt.error_classification = error_classification or "TIMEOUT_UNCERTAIN"

    attempt.latency_ms = latency_ms
    attempt.completed_at = completed_at
    daily.version += 1
    await db.flush()

    logger.info(
        "quota_attempt_outcome_recorded",
        extra={
            "institution_id": str(institution_id),
            "reservation_id": str(res.id),
            "attempt_id": str(attempt.id),
            "attempt_status": attempt.status,
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
            "actual_cost_inr": str(attempt.actual_cost_inr) if attempt.actual_cost_inr is not None else None,
        },
    )
    return to_reservation_snapshot(res), to_attempt_snapshot(attempt)


async def finalize_reservation_tx(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    reservation_id: uuid.UUID,
    escalate_dispatched_to_unknown: bool = False,
    recovery_reason: str | None = None,
    as_of: datetime | None = None,
) -> ReconciliationResult:
    """
    Execute Tx 3: Finalize `DISPATCHED` reservation into `COMMITTED` or `UNKNOWN_USAGE`.

    Never moves a `DISPATCHED` reservation to `RELEASED`.
    """
    now = _utc_now(as_of)
    if recovery_reason is not None:
        recovery_reason = validate_non_empty_text(
            recovery_reason, field_name="recovery_reason", max_length=100
        )

    routing = await load_reservation_routing(
        db, institution_id=institution_id, reservation_id=reservation_id
    )
    daily, cat = await upsert_and_lock_level2(
        db,
        institution_id=institution_id,
        usage_date=routing.usage_date,
        usage_category=routing.usage_category,
    )
    res, attempts = await lock_reservation_and_attempts(
        db, institution_id=institution_id, reservation_id=reservation_id
    )

    if res.status == "COMMITTED":
        return ReconciliationResult(
            reservation=to_reservation_snapshot(res),
            attempts=tuple(to_attempt_snapshot(a) for a in attempts),
            was_idempotent_noop=True,
        )

    if res.status == "UNKNOWN_USAGE":
        if not escalate_dispatched_to_unknown:
            return ReconciliationResult(
                reservation=to_reservation_snapshot(res),
                attempts=tuple(to_attempt_snapshot(a) for a in attempts),
                was_idempotent_noop=True,
            )
        return ReconciliationResult(
            reservation=to_reservation_snapshot(res),
            attempts=tuple(to_attempt_snapshot(a) for a in attempts),
            was_idempotent_noop=True,
        )

    if res.status != "DISPATCHED":
        raise InvalidStateTransitionError(
            f"Cannot finalize reservation from status {res.status!r}",
            current_state=res.status,
            target_state="COMMITTED",
            entity_type="reservation",
        )

    totals = compute_attempt_totals(attempts)
    if totals.has_dispatched_attempts:
        if not escalate_dispatched_to_unknown:
            raise InvalidStateTransitionError(
                "Reservation still has in-flight DISPATCHED attempt(s); record outcome or escalate to UNKNOWN_USAGE",
                current_state="DISPATCHED",
                target_state="COMMITTED",
                entity_type="reservation",
            )
        for att in attempts:
            if att.status == "DISPATCHED":
                att.status = "TIMEOUT_UNCERTAIN"
                att.error_classification = att.error_classification or (
                    recovery_reason or "DISPATCH_OUTCOME_UNKNOWN"
                )
                att.completed_at = max(now, att.dispatched_at)
        totals = compute_attempt_totals(attempts)

    # Release pending reserve back from Level 2
    daily.pending_reserved_tokens -= res.total_reserved_tokens
    daily.pending_reserved_cost_inr -= res.reserved_cost_inr
    cat.pending_reserved_tokens -= res.total_reserved_tokens

    # Commit any confirmed usage (in DISPATCHED -> COMMITTED, all attempts;
    # in DISPATCHED -> UNKNOWN_USAGE, any already succeeded earlier attempts).
    _apply_attempt_delta_to_ledgers(res=res, daily=daily, cat=cat, attempts=attempts)

    if totals.has_uncertain_attempts or not attempts:
        hold_tokens = totals.uncertain_tokens_held if attempts else res.total_reserved_tokens
        hold_cost = totals.uncertain_cost_held_inr if attempts else res.reserved_cost_inr
        _set_uncertain_hold(
            res=res,
            daily=daily,
            cat=cat,
            new_uncertain_tokens=hold_tokens,
            new_uncertain_cost=hold_cost,
        )
        res.status = "UNKNOWN_USAGE"
        res.review_status = "NEEDS_MANUAL_REVIEW"
        res.reconciled_at = None
        if recovery_reason is not None:
            res.recovery_reason = recovery_reason
        res.reconciliation_version += 1
        daily.unknown_usage_count += 1
    else:
        _set_uncertain_hold(
            res=res,
            daily=daily,
            cat=cat,
            new_uncertain_tokens=0,
            new_uncertain_cost=Decimal("0.0000"),
        )
        res.status = "COMMITTED"
        res.reconciled_at = max(now, _require_dispatched_at(res))
        res.reconciliation_version += 1

    daily.version += 1
    await db.flush()

    logger.info(
        "quota_reservation_finalized",
        extra={
            "institution_id": str(institution_id),
            "reservation_id": str(res.id),
            "final_status": res.status,
            "actual_total_tokens": res.actual_total_tokens,
            "actual_cost_inr": str(res.actual_cost_inr),
            "uncertain_tokens_held": res.uncertain_tokens_held,
            "reconciliation_version": res.reconciliation_version,
        },
    )
    return ReconciliationResult(
        reservation=to_reservation_snapshot(res),
        attempts=tuple(to_attempt_snapshot(a) for a in attempts),
    )


async def manual_settle_unknown_usage_tx(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    reservation_id: uuid.UUID,
    settled_tokens: int,
    actor: str,
    reason: str,
    notes: str,
    attempt_id: uuid.UUID | None = None,
    settled_cost_inr: Decimal | None = None,
    settled_input_tokens: int | None = None,
    settled_output_tokens: int | None = None,
    zero_charge_release: bool = False,
    as_of: datetime | None = None,
) -> ReconciliationResult:
    """
    Execute Tx 4: Operator manual settlement of an `UNKNOWN_USAGE` reservation/attempt.
    """
    now = _utc_now(as_of)
    validate_token_count(settled_tokens, field_name="settled_tokens", upper_bound=MAX_TOTAL_OP_TOKENS)
    norm_actor = validate_non_empty_text(actor, field_name="actor", max_length=100)
    norm_reason = validate_non_empty_text(reason, field_name="reason", max_length=100)
    norm_notes = validate_non_empty_text(notes, field_name="notes")

    routing = await load_reservation_routing(
        db, institution_id=institution_id, reservation_id=reservation_id
    )
    daily, cat = await upsert_and_lock_level2(
        db,
        institution_id=institution_id,
        usage_date=routing.usage_date,
        usage_category=routing.usage_category,
    )
    res, attempts = await lock_reservation_and_attempts(
        db, institution_id=institution_id, reservation_id=reservation_id
    )

    if res.status != "UNKNOWN_USAGE":
        raise InvalidStateTransitionError(
            f"Manual settlement requires reservation status 'UNKNOWN_USAGE', got {res.status!r}",
            current_state=res.status,
            target_state="COMMITTED",
            entity_type="reservation",
        )

    uncertain_attempts = [a for a in attempts if a.status in ("TIMEOUT_UNCERTAIN", "DISPATCHED")]
    if not uncertain_attempts:
        raise InvalidStateTransitionError(
            "No unsettled TIMEOUT_UNCERTAIN attempt found on reservation",
            current_state=res.status,
            target_state="COMMITTED",
            entity_type="attempt",
        )
    if attempt_id is not None:
        target_attempt = _find_attempt(attempts, attempt_id, res.id)
        if target_attempt.status not in ("TIMEOUT_UNCERTAIN", "DISPATCHED"):
            raise InvalidStateTransitionError(
                f"Attempt {target_attempt.id} is already settled in status {target_attempt.status!r}",
                current_state=target_attempt.status,
                target_state="MANUALLY_SETTLED",
                entity_type="attempt",
            )
    else:
        if len(uncertain_attempts) > 1:
            raise ValueError(
                "attempt_id is required when a reservation has multiple uncertain attempts"
            )
        target_attempt = uncertain_attempts[0]

    if settled_cost_inr is not None:
        final_cost = quantize_inr(settled_cost_inr)
    else:
        pv = await resolve_pricing_version_by_id(db, target_attempt.pricing_version)
        if settled_input_tokens is not None and settled_output_tokens is not None:
            in_tok = validate_token_count(settled_input_tokens, field_name="settled_input_tokens")
            out_tok = validate_token_count(settled_output_tokens, field_name="settled_output_tokens")
            if in_tok + out_tok != settled_tokens:
                raise ValueError("settled_input_tokens + settled_output_tokens must equal settled_tokens")
            final_cost = calculate_cost_breakdown(
                pv,
                provider=target_attempt.provider,
                model=target_attempt.model,
                input_tokens=in_tok,
                output_tokens=out_tok,
            ).total_cost_inr
        else:
            final_cost = calculate_cost_breakdown(
                pv,
                provider=target_attempt.provider,
                model=target_attempt.model,
                input_tokens=0,
                output_tokens=settled_tokens,
            ).total_cost_inr

    target_attempt.status = "MANUALLY_SETTLED"
    target_attempt.manual_settled_tokens = settled_tokens
    target_attempt.manual_settled_cost_inr = final_cost
    target_attempt.manual_settled_at = now
    if target_attempt.completed_at is None:
        target_attempt.completed_at = max(now, target_attempt.dispatched_at)

    _apply_attempt_delta_to_ledgers(res=res, daily=daily, cat=cat, attempts=attempts)
    new_totals = compute_attempt_totals(attempts)

    _set_uncertain_hold(
        res=res,
        daily=daily,
        cat=cat,
        new_uncertain_tokens=new_totals.uncertain_tokens_held,
        new_uncertain_cost=new_totals.uncertain_cost_held_inr,
    )

    adjustment = AIFinancialAdjustment(
        id=uuid.uuid4(),
        institution_id=institution_id,
        reservation_id=res.id,
        attempt_id=target_attempt.id,
        adjusted_by_actor=norm_actor,
        adjustment_type="MANUAL_SETTLE",
        token_delta=settled_tokens,
        cost_inr_delta=final_cost,
        adjustment_reason=norm_reason,
        notes=norm_notes,
        created_at=now,
    )
    db.add(adjustment)

    if not new_totals.has_uncertain_attempts and not new_totals.has_dispatched_attempts:
        dispatched_at = _require_dispatched_at(res)
        is_zero_release = (
            zero_charge_release
            and res.actual_total_tokens == 0
            and res.actual_cost_inr == Decimal("0.0000")
            and not new_totals.has_succeeded_attempts
        )
        res.status = "RELEASED" if is_zero_release else "COMMITTED"
        res.review_status = "MANUALLY_SETTLED"
        res.reconciled_at = max(now, dispatched_at)
    else:
        res.review_status = "NEEDS_MANUAL_REVIEW"

    res.reconciliation_version += 1
    daily.version += 1
    await db.flush()

    logger.info(
        "quota_reservation_manually_settled",
        extra={
            "institution_id": str(institution_id),
            "reservation_id": str(res.id),
            "attempt_id": str(target_attempt.id),
            "settled_tokens": settled_tokens,
            "settled_cost_inr": str(final_cost),
            "final_status": res.status,
            "actor": norm_actor,
        },
    )
    return ReconciliationResult(
        reservation=to_reservation_snapshot(res),
        attempts=tuple(to_attempt_snapshot(a) for a in attempts),
        adjustment=to_adjustment_snapshot(adjustment),
    )


async def record_late_provider_usage_tx(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    reservation_id: uuid.UUID,
    attempt_id: uuid.UUID,
    input_tokens: int,
    output_tokens: int,
    actor: str,
    reason: str,
    notes: str,
    provider_request_id: str | None = None,
    failed_confirmed: bool = False,
    as_of: datetime | None = None,
) -> ReconciliationResult:
    """
    Execute Tx 5: Reconcile late provider usage on `UNKNOWN_USAGE` or `MANUALLY_SETTLED` attempts.

    Preserves `manual_settled_*` snapshots intact and appends differential variance entries
    (`VARIANCE_DEBIT` / `VARIANCE_CREDIT`) when late provider evidence differs from manual estimate.
    """
    now = _utc_now(as_of)
    in_tok = validate_token_count(input_tokens, field_name="input_tokens")
    out_tok = validate_token_count(output_tokens, field_name="output_tokens")
    norm_actor = validate_non_empty_text(actor, field_name="actor", max_length=100)
    norm_reason = validate_non_empty_text(reason, field_name="reason", max_length=100)
    norm_notes = validate_non_empty_text(notes, field_name="notes")
    if provider_request_id is not None:
        provider_request_id = validate_non_empty_text(
            provider_request_id, field_name="provider_request_id", max_length=255
        )

    routing = await load_reservation_routing(
        db, institution_id=institution_id, reservation_id=reservation_id
    )
    daily, cat = await upsert_and_lock_level2(
        db,
        institution_id=institution_id,
        usage_date=routing.usage_date,
        usage_category=routing.usage_category,
    )
    res, attempts = await lock_reservation_and_attempts(
        db, institution_id=institution_id, reservation_id=reservation_id
    )
    target_attempt = _find_attempt(attempts, attempt_id, res.id)

    pv = await resolve_pricing_version_by_id(db, target_attempt.pricing_version)
    late_cost = calculate_cost_breakdown(
        pv,
        provider=target_attempt.provider,
        model=target_attempt.model,
        input_tokens=in_tok,
        output_tokens=out_tok,
    ).total_cost_inr

    if provider_request_id is not None and provider_request_id != target_attempt.provider_request_id:
        conflict = await _check_provider_request_id_conflict(
            db,
            institution_id=institution_id,
            provider=target_attempt.provider,
            provider_request_id=provider_request_id,
        )
        if conflict is not None and conflict.id != target_attempt.id:
            raise IdempotencyConflictError(
                "provider_request_id already belongs to another attempt",
                institution_id=institution_id,
                idempotency_key=provider_request_id,
                mismatched_fields=("attempt_id",),
            )
        target_attempt.provider_request_id = provider_request_id

    if target_attempt.status == "TIMEOUT_UNCERTAIN":
        if res.status != "UNKNOWN_USAGE":
            raise InvalidStateTransitionError(
                f"Expected reservation in 'UNKNOWN_USAGE', got {res.status!r}",
                current_state=res.status,
                target_state="COMMITTED",
                entity_type="reservation",
            )
        target_attempt.status = (
            "FAILED_CONFIRMED" if (failed_confirmed and in_tok == 0 and out_tok == 0) else "SUCCEEDED"
        )
        target_attempt.input_tokens = in_tok
        target_attempt.output_tokens = out_tok
        target_attempt.actual_cost_inr = late_cost
        target_attempt.late_reported_input_tokens = in_tok
        target_attempt.late_reported_output_tokens = out_tok
        target_attempt.late_reported_cost_inr = late_cost
        target_attempt.late_reported_at = now
        target_attempt.completed_at = target_attempt.completed_at or max(
            now, target_attempt.dispatched_at
        )

        _apply_attempt_delta_to_ledgers(res=res, daily=daily, cat=cat, attempts=attempts)
        new_totals = compute_attempt_totals(attempts)
        _set_uncertain_hold(
            res=res,
            daily=daily,
            cat=cat,
            new_uncertain_tokens=new_totals.uncertain_tokens_held,
            new_uncertain_cost=new_totals.uncertain_cost_held_inr,
        )
        token_delta = in_tok + out_tok
        cost_delta = late_cost
        adj_type = "LATE_SETTLEMENT"

        if not new_totals.has_uncertain_attempts and not new_totals.has_dispatched_attempts:
            dispatched_at = _require_dispatched_at(res)
            all_zero_failure = (
                res.actual_total_tokens == 0
                and res.actual_cost_inr == Decimal("0.0000")
                and not new_totals.has_succeeded_attempts
                and not new_totals.has_manual_settlements
            )
            res.status = "RELEASED" if all_zero_failure else "COMMITTED"
            res.review_status = "MANUALLY_SETTLED" if new_totals.has_manual_settlements else "NONE"
            res.reconciled_at = max(now, dispatched_at)
            if all_zero_failure:
                res.recovery_reason = res.recovery_reason or "LATE_CONFIRMED_FAILURE"

    elif target_attempt.status == "MANUALLY_SETTLED":
        if target_attempt.late_reported_at is not None:
            same_late = (
                target_attempt.late_reported_input_tokens == in_tok
                and target_attempt.late_reported_output_tokens == out_tok
                and target_attempt.late_reported_cost_inr == late_cost
            )
            if same_late:
                return ReconciliationResult(
                    reservation=to_reservation_snapshot(res),
                    attempts=tuple(to_attempt_snapshot(a) for a in attempts),
                    was_idempotent_noop=True,
                )
            raise InvalidStateTransitionError(
                "Conflicting late provider report received after late evidence was already recorded",
                current_state=target_attempt.status,
                target_state="MANUALLY_SETTLED",
                entity_type="attempt",
            )

        # Preserve manual_settled_* columns intact; store late evidence alongside them.
        target_attempt.late_reported_input_tokens = in_tok
        target_attempt.late_reported_output_tokens = out_tok
        target_attempt.late_reported_cost_inr = late_cost
        target_attempt.late_reported_at = now

        token_delta = (in_tok + out_tok) - (target_attempt.manual_settled_tokens or 0)
        cost_delta = late_cost - (target_attempt.manual_settled_cost_inr or Decimal("0.0000"))
        adj_type = (
            "VARIANCE_DEBIT"
            if (cost_delta > Decimal("0") or (cost_delta == Decimal("0") and token_delta >= 0))
            else "VARIANCE_CREDIT"
        )

        _apply_attempt_delta_to_ledgers(res=res, daily=daily, cat=cat, attempts=attempts)
        if res.status == "RELEASED" and (
            res.actual_total_tokens > 0 or res.actual_cost_inr > Decimal("0")
        ):
            res.status = "COMMITTED"
        res.review_status = "LATE_EVIDENCE_REVIEW_REQUIRED"

    elif target_attempt.status in ("SUCCEEDED", "FAILED_CONFIRMED"):
        same_terminal = (
            target_attempt.input_tokens == in_tok
            and target_attempt.output_tokens == out_tok
            and target_attempt.actual_cost_inr == late_cost
        )
        if same_terminal:
            return ReconciliationResult(
                reservation=to_reservation_snapshot(res),
                attempts=tuple(to_attempt_snapshot(a) for a in attempts),
                was_idempotent_noop=True,
            )
        raise InvalidStateTransitionError(
            f"Attempt {target_attempt.id} already resolved in status {target_attempt.status!r} with differing usage",
            current_state=target_attempt.status,
            target_state=target_attempt.status,
            entity_type="attempt",
        )
    else:
        raise InvalidStateTransitionError(
            f"Cannot record late provider usage while attempt is in status {target_attempt.status!r}",
            current_state=target_attempt.status,
            target_state="SUCCEEDED",
            entity_type="attempt",
        )

    adjustment = AIFinancialAdjustment(
        id=uuid.uuid4(),
        institution_id=institution_id,
        reservation_id=res.id,
        attempt_id=target_attempt.id,
        adjusted_by_actor=norm_actor,
        adjustment_type=adj_type,
        token_delta=token_delta,
        cost_inr_delta=cost_delta,
        adjustment_reason=norm_reason,
        notes=norm_notes,
        created_at=now,
    )
    db.add(adjustment)
    res.reconciliation_version += 1
    daily.version += 1
    await db.flush()

    logger.info(
        "quota_late_provider_usage_reconciled",
        extra={
            "institution_id": str(institution_id),
            "reservation_id": str(res.id),
            "attempt_id": str(target_attempt.id),
            "adjustment_type": adj_type,
            "token_delta": token_delta,
            "cost_inr_delta": str(cost_delta),
            "review_status": res.review_status,
            "final_status": res.status,
        },
    )
    return ReconciliationResult(
        reservation=to_reservation_snapshot(res),
        attempts=tuple(to_attempt_snapshot(a) for a in attempts),
        adjustment=to_adjustment_snapshot(adjustment),
    )

"""
Canonical lock acquisition helpers and immutable row-to-snapshot mappers.

Enforces the Stage 7 lock hierarchy strictly in ascending order:
  Level 1:  tenant_ai_quotas
  Level 2a: tenant_daily_ai_usage
  Level 2b: tenant_daily_category_usage
  Level 3:  ai_token_reservations
  Level 4:  ai_provider_attempts
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.quota.errors import (
    ReservationNotFoundError,
    TenantQuotaNotConfiguredError,
)
from app.observability.quota.types import (
    AdjustmentSnapshot,
    AttemptSnapshot,
    ReservationSnapshot,
)
from app.observability.quota_models import (
    AIFinancialAdjustment,
    AIProviderAttempt,
    AITokenReservation,
    TenantAIQuota,
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
)


@dataclass(frozen=True, slots=True)
class ReservationRoutingKey:
    """Immutable routing coordinates needed to acquire Level 2 locks before Level 3."""

    institution_id: uuid.UUID
    usage_date: date
    usage_category: str


@dataclass(frozen=True, slots=True)
class AttemptTotals:
    """Aggregated confirmed and uncertain totals across a reservation's provider attempts."""

    confirmed_input_tokens: int
    confirmed_output_tokens: int
    confirmed_total_tokens: int
    confirmed_cost_inr: Decimal
    uncertain_tokens_held: int
    uncertain_cost_held_inr: Decimal
    has_dispatched_attempts: bool
    has_uncertain_attempts: bool
    has_succeeded_attempts: bool
    has_manual_settlements: bool


async def lock_tenant_quota(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
) -> TenantAIQuota:
    """Acquire Level 1 `FOR UPDATE` lock on TenantAIQuota for `institution_id`."""
    stmt = (
        select(TenantAIQuota)
        .where(TenantAIQuota.institution_id == institution_id)
        .with_for_update()
    )
    quota = (await db.execute(stmt)).scalar_one_or_none()
    if quota is None:
        raise TenantQuotaNotConfiguredError(institution_id)
    return quota


async def upsert_and_lock_level2(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    usage_date: date,
    usage_category: str,
) -> tuple[TenantDailyAIUsage, TenantDailyCategoryUsage]:
    """
    Atomically get-or-create and `FOR UPDATE` lock Level 2a then Level 2b rollup rows.
    """
    daily_insert = (
        pg_insert(TenantDailyAIUsage)
        .values(
            id=uuid.uuid4(),
            institution_id=institution_id,
            usage_date=usage_date,
        )
        .on_conflict_do_nothing(constraint="uq_tenant_daily_usage_date")
    )
    await db.execute(daily_insert)

    daily_stmt = (
        select(TenantDailyAIUsage)
        .where(
            TenantDailyAIUsage.institution_id == institution_id,
            TenantDailyAIUsage.usage_date == usage_date,
        )
        .with_for_update()
    )
    daily = (await db.execute(daily_stmt)).scalar_one()

    cat_insert = (
        pg_insert(TenantDailyCategoryUsage)
        .values(
            id=uuid.uuid4(),
            institution_id=institution_id,
            usage_date=usage_date,
            usage_category=usage_category,
        )
        .on_conflict_do_nothing(constraint="uq_tenant_daily_category_date")
    )
    await db.execute(cat_insert)

    cat_stmt = (
        select(TenantDailyCategoryUsage)
        .where(
            TenantDailyCategoryUsage.institution_id == institution_id,
            TenantDailyCategoryUsage.usage_date == usage_date,
            TenantDailyCategoryUsage.usage_category == usage_category,
        )
        .with_for_update()
    )
    category_row = (await db.execute(cat_stmt)).scalar_one()
    return daily, category_row


async def lock_daily_usage_row(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    usage_date: date,
) -> TenantDailyAIUsage:
    """Acquire Level 2a `FOR UPDATE` lock on an existing daily usage row."""
    stmt = (
        select(TenantDailyAIUsage)
        .where(
            TenantDailyAIUsage.institution_id == institution_id,
            TenantDailyAIUsage.usage_date == usage_date,
        )
        .with_for_update()
    )
    return (await db.execute(stmt)).scalar_one()


async def load_reservation_routing(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    reservation_id: uuid.UUID,
) -> ReservationRoutingKey:
    """
    Read immutable routing coordinates for a reservation WITHOUT acquiring row locks.

    Allows lifecycle transactions to acquire Level 2 locks before Level 3/4 locks,
    eliminating Level 3 -> Level 2 lock inversion deadlocks.
    """
    stmt = select(
        AITokenReservation.institution_id,
        AITokenReservation.usage_date,
        AITokenReservation.usage_category,
    ).where(
        AITokenReservation.institution_id == institution_id,
        AITokenReservation.id == reservation_id,
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        raise ReservationNotFoundError(reservation_id, institution_id)
    return ReservationRoutingKey(
        institution_id=row.institution_id,
        usage_date=row.usage_date,
        usage_category=row.usage_category,
    )


async def lock_reservation_and_attempts(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    reservation_id: uuid.UUID,
) -> tuple[AITokenReservation, list[AIProviderAttempt]]:
    """Acquire Level 3 (`ai_token_reservations`) then Level 4 (`ai_provider_attempts`) locks."""
    res_stmt = (
        select(AITokenReservation)
        .where(
            AITokenReservation.institution_id == institution_id,
            AITokenReservation.id == reservation_id,
        )
        .with_for_update()
    )
    reservation = (await db.execute(res_stmt)).scalar_one_or_none()
    if reservation is None:
        raise ReservationNotFoundError(reservation_id, institution_id)

    att_stmt = (
        select(AIProviderAttempt)
        .where(
            AIProviderAttempt.institution_id == institution_id,
            AIProviderAttempt.reservation_id == reservation_id,
        )
        .order_by(AIProviderAttempt.attempt_sequence.asc())
        .with_for_update()
    )
    attempts = list((await db.execute(att_stmt)).scalars().all())
    return reservation, attempts


def daily_limit_for_category(quota: TenantAIQuota, category: str) -> int:
    """Return configured daily token ceiling for `category` cleanly via mapping."""
    mapping = {
        "interactive_ai": quota.daily_interactive_token_limit,
        "ingestion_embeddings": quota.daily_ingestion_token_limit,
        "other_metered": quota.daily_other_token_limit,
    }
    if category not in mapping:
        raise ValueError(f"Unsupported usage_category={category!r}")
    return int(mapping[category])


def attempt_confirmed_contribution(attempt: AIProviderAttempt) -> tuple[int, int, Decimal]:
    """
    Return canonical `(input_tokens, output_tokens, cost_inr)` for one attempt.

    Precedence preserves immutable audit snapshots:
      1. Late provider evidence (`late_reported_at IS NOT NULL`) overrides manual estimate.
      2. Operator manual settlement (`status == 'MANUALLY_SETTLED'`).
      3. Terminal provider response (`status in ('SUCCEEDED', 'FAILED_CONFIRMED')`).
      4. Active/uncertain (`DISPATCHED`, `TIMEOUT_UNCERTAIN`) contribute 0 confirmed usage.
    """
    if attempt.late_reported_at is not None:
        return (
            attempt.late_reported_input_tokens or 0,
            attempt.late_reported_output_tokens or 0,
            attempt.late_reported_cost_inr or Decimal("0.0000"),
        )
    if attempt.status == "MANUALLY_SETTLED":
        return (
            0,
            attempt.manual_settled_tokens or 0,
            attempt.manual_settled_cost_inr or Decimal("0.0000"),
        )
    if attempt.status in ("SUCCEEDED", "FAILED_CONFIRMED"):
        return (
            attempt.input_tokens or 0,
            attempt.output_tokens or 0,
            attempt.actual_cost_inr or Decimal("0.0000"),
        )
    return 0, 0, Decimal("0.0000")


def compute_attempt_totals(attempts: list[AIProviderAttempt]) -> AttemptTotals:
    """Compute exact confirmed and uncertain totals across all attempts of a reservation."""
    conf_in = 0
    conf_out = 0
    conf_cost = Decimal("0.0000")
    unc_tok = 0
    unc_cost = Decimal("0.0000")
    has_dispatched = False
    has_uncertain = False
    has_succeeded = False
    has_manual = False

    for att in attempts:
        a_in, a_out, a_cost = attempt_confirmed_contribution(att)
        conf_in += a_in
        conf_out += a_out
        conf_cost += a_cost

        if att.status == "DISPATCHED":
            has_dispatched = True
            unc_tok += att.estimated_tokens
            unc_cost += att.estimated_cost_inr
        elif att.status == "TIMEOUT_UNCERTAIN":
            has_uncertain = True
            unc_tok += att.estimated_tokens
            unc_cost += att.estimated_cost_inr
        elif att.status == "SUCCEEDED":
            has_succeeded = True
        elif att.status == "MANUALLY_SETTLED":
            has_manual = True

    return AttemptTotals(
        confirmed_input_tokens=conf_in,
        confirmed_output_tokens=conf_out,
        confirmed_total_tokens=conf_in + conf_out,
        confirmed_cost_inr=conf_cost,
        uncertain_tokens_held=unc_tok,
        uncertain_cost_held_inr=unc_cost,
        has_dispatched_attempts=has_dispatched,
        has_uncertain_attempts=has_uncertain,
        has_succeeded_attempts=has_succeeded,
        has_manual_settlements=has_manual,
    )


def to_reservation_snapshot(row: AITokenReservation) -> ReservationSnapshot:
    """Convert ORM AITokenReservation into an immutable snapshot."""
    return ReservationSnapshot(
        id=row.id,
        institution_id=row.institution_id,
        user_id=row.user_id,
        logical_operation_id=row.logical_operation_id,
        usage_date=row.usage_date,
        usage_category=row.usage_category,
        endpoint=row.endpoint,
        status=row.status,
        pricing_version=row.pricing_version,
        estimated_input_tokens=row.estimated_input_tokens,
        reserved_output_tokens=row.reserved_output_tokens,
        total_reserved_tokens=row.total_reserved_tokens,
        reserved_cost_inr=row.reserved_cost_inr,
        actual_input_tokens=row.actual_input_tokens,
        actual_output_tokens=row.actual_output_tokens,
        actual_total_tokens=row.actual_total_tokens,
        actual_cost_inr=row.actual_cost_inr,
        uncertain_tokens_held=row.uncertain_tokens_held,
        uncertain_cost_held_inr=row.uncertain_cost_held_inr,
        idempotency_key=row.idempotency_key,
        reconciliation_version=row.reconciliation_version,
        recovery_state=row.recovery_state,
        recovery_reason=row.recovery_reason,
        review_status=row.review_status,
        dispatched_at=row.dispatched_at,
        created_at=row.created_at,
        expires_at=row.expires_at,
        reconciled_at=row.reconciled_at,
    )


def to_attempt_snapshot(row: AIProviderAttempt) -> AttemptSnapshot:
    """Convert ORM AIProviderAttempt into an immutable snapshot."""
    return AttemptSnapshot(
        id=row.id,
        institution_id=row.institution_id,
        reservation_id=row.reservation_id,
        attempt_sequence=row.attempt_sequence,
        provider=row.provider,
        model=row.model,
        is_fallback=row.is_fallback,
        is_retry=row.is_retry,
        status=row.status,
        provider_request_id=row.provider_request_id,
        pricing_version=row.pricing_version,
        estimated_tokens=row.estimated_tokens,
        estimated_cost_inr=row.estimated_cost_inr,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        actual_cost_inr=row.actual_cost_inr,
        manual_settled_tokens=row.manual_settled_tokens,
        manual_settled_cost_inr=row.manual_settled_cost_inr,
        manual_settled_at=row.manual_settled_at,
        late_reported_input_tokens=row.late_reported_input_tokens,
        late_reported_output_tokens=row.late_reported_output_tokens,
        late_reported_cost_inr=row.late_reported_cost_inr,
        late_reported_at=row.late_reported_at,
        error_classification=row.error_classification,
        latency_ms=row.latency_ms,
        dispatched_at=row.dispatched_at,
        completed_at=row.completed_at,
    )


def to_adjustment_snapshot(row: AIFinancialAdjustment) -> AdjustmentSnapshot:
    """Convert ORM AIFinancialAdjustment into an immutable snapshot."""
    return AdjustmentSnapshot(
        id=row.id,
        institution_id=row.institution_id,
        reservation_id=row.reservation_id,
        attempt_id=row.attempt_id,
        adjusted_by_actor=row.adjusted_by_actor,
        adjustment_type=row.adjustment_type,
        token_delta=row.token_delta,
        cost_inr_delta=row.cost_inr_delta,
        adjustment_reason=row.adjustment_reason,
        notes=row.notes,
        created_at=row.created_at,
    )


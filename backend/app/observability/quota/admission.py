"""
Stage 7.2 Tx 1 (Admission & Reservation), Tx 1B (Pre-dispatch Release/Expiry),
and Uncertain Commit Recovery operations.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.quota.errors import (
    IdempotencyConflictError,
    InvalidStateTransitionError,
    QuotaExceededError,
    TenantQuotaSuspendedError,
)
from app.observability.quota.locking import (
    daily_limit_for_category,
    load_reservation_routing,
    lock_reservation_and_attempts,
    lock_tenant_quota,
    to_reservation_snapshot,
    upsert_and_lock_level2,
)
from app.observability.quota.pricing import (
    calculate_cost_breakdown,
    resolve_active_pricing_version,
    resolve_pricing_version_by_id,
)
from app.observability.quota.timezone import month_date_bounds, resolve_tenant_usage_date
from app.observability.quota.types import (
    AdmissionResult,
    ReservationCreateRequest,
    ReservationSnapshot,
    validate_non_empty_text,
)
from app.observability.quota_models import (
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


def _find_mismatched_idempotency_fields(
    existing: AITokenReservation,
    request: ReservationCreateRequest,
) -> tuple[str, ...]:
    """Compare admission request parameters against an existing reservation."""
    checks: list[tuple[str, object, object]] = [
        ("user_id", existing.user_id, request.user_id),
        ("usage_category", existing.usage_category, request.usage_category),
        ("endpoint", existing.endpoint, request.endpoint),
        ("estimated_input_tokens", existing.estimated_input_tokens, request.estimated_input_tokens),
        ("reserved_output_tokens", existing.reserved_output_tokens, request.reserved_output_tokens),
    ]
    if request.logical_operation_id is not None:
        checks.append(
            ("logical_operation_id", existing.logical_operation_id, request.logical_operation_id)
        )
    if request.pricing_version is not None:
        checks.append(("pricing_version", existing.pricing_version, request.pricing_version))
    return tuple(name for name, old_val, new_val in checks if old_val != new_val)


async def _find_reservation_by_idempotency_key(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    idempotency_key: str,
    for_update: bool,
) -> AITokenReservation | None:
    """Look up a reservation by `(institution_id, idempotency_key)`."""
    stmt = select(AITokenReservation).where(
        AITokenReservation.institution_id == institution_id,
        AITokenReservation.idempotency_key == idempotency_key,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _enforce_quota_ceilings(
    db: AsyncSession,
    *,
    quota: TenantAIQuota,
    daily: TenantDailyAIUsage,
    cat: TenantDailyCategoryUsage,
    usage_date,
    request: ReservationCreateRequest,
    cost_inr: Decimal,
) -> None:
    """Enforce daily category limit, reserve risk cap, monthly cap, and financial exposure."""
    requested_tokens = request.estimated_input_tokens + request.reserved_output_tokens
    category_limit = daily_limit_for_category(quota, request.usage_category)

    cat_effective = (
        cat.committed_total_tokens + cat.pending_reserved_tokens + cat.uncertain_reserved_tokens
    )
    if cat_effective + requested_tokens > category_limit:
        raise QuotaExceededError(
            f"Daily {request.usage_category} token quota exceeded",
            limit_type="DAILY_CATEGORY_LIMIT",
            institution_id=request.institution_id,
            usage_category=request.usage_category,
            current_value=cat_effective,
            requested_value=requested_tokens,
            limit_value=category_limit,
        )

    reserve_cap = int(
        (Decimal(category_limit) * quota.pending_reserve_cap_percent).to_integral_value(
            rounding=ROUND_DOWN
        )
    )
    active_held = cat.pending_reserved_tokens + cat.uncertain_reserved_tokens
    if active_held + requested_tokens > reserve_cap:
        raise QuotaExceededError(
            f"Pending reserve risk cap exceeded for {request.usage_category}",
            limit_type="PENDING_RESERVE_CAP_LIMIT",
            institution_id=request.institution_id,
            usage_category=request.usage_category,
            current_value=active_held,
            requested_value=requested_tokens,
            limit_value=reserve_cap,
        )

    if quota.monthly_total_token_limit is not None:
        month_start, next_month_start = month_date_bounds(usage_date)
        monthly_stmt = select(
            func.coalesce(
                func.sum(
                    TenantDailyAIUsage.committed_total_tokens
                    + TenantDailyAIUsage.pending_reserved_tokens
                    + TenantDailyAIUsage.uncertain_reserved_tokens
                ),
                0,
            )
        ).where(
            TenantDailyAIUsage.institution_id == request.institution_id,
            TenantDailyAIUsage.usage_date >= month_start,
            TenantDailyAIUsage.usage_date < next_month_start,
        )
        monthly_used = int((await db.execute(monthly_stmt)).scalar_one())
        if monthly_used + requested_tokens > quota.monthly_total_token_limit:
            raise QuotaExceededError(
                "Monthly total token quota exceeded",
                limit_type="MONTHLY_TOTAL_LIMIT",
                institution_id=request.institution_id,
                usage_category=request.usage_category,
                current_value=monthly_used,
                requested_value=requested_tokens,
                limit_value=int(quota.monthly_total_token_limit),
            )

    daily_exposure = (
        daily.committed_cost_inr + daily.pending_reserved_cost_inr + daily.uncertain_exposure_cost_inr
    )
    # Stage 7.4 Approved Business Decisions 1 & 2:
    # Protect the configured risk reserve percentage buffer of the daily financial ceiling
    risk_reserve_pct = getattr(quota, "risk_reserve_percent", Decimal("0.0000"))
    risk_reserve_inr = (quota.daily_exposure_limit_inr * risk_reserve_pct).quantize(Decimal("0.0001"))
    available_exposure = max(Decimal("0.0000"), quota.daily_exposure_limit_inr - risk_reserve_inr)

    if daily_exposure + cost_inr > available_exposure:
        raise QuotaExceededError(
            "Daily financial INR exposure limit exceeded (protecting risk reserve buffer)",
            limit_type="DAILY_FINANCIAL_EXPOSURE_LIMIT",
            institution_id=request.institution_id,
            usage_category=request.usage_category,
            current_value=daily_exposure + risk_reserve_inr,
            requested_value=cost_inr,
            limit_value=quota.daily_exposure_limit_inr,
        )


async def admit_and_reserve_tx(
    db: AsyncSession,
    request: ReservationCreateRequest,
    *,
    as_of: datetime | None = None,
) -> AdmissionResult:
    """
    Execute Tx 1: Atomic quota admission & pre-dispatch reservation creation.

    Acquires Level 1 -> Level 2a -> Level 2b -> Level 3 strictly in canonical order.
    """
    now = _utc_now(as_of)
    quota = await lock_tenant_quota(db, institution_id=request.institution_id)

    if request.idempotency_key is not None:
        existing = await _find_reservation_by_idempotency_key(
            db,
            institution_id=request.institution_id,
            idempotency_key=request.idempotency_key,
            for_update=True,
        )
        if existing is not None:
            mismatched = _find_mismatched_idempotency_fields(existing, request)
            if mismatched:
                raise IdempotencyConflictError(
                    f"Idempotency key {request.idempotency_key!r} reused with conflicting parameters: "
                    f"{', '.join(mismatched)}",
                    institution_id=request.institution_id,
                    idempotency_key=request.idempotency_key,
                    mismatched_fields=mismatched,
                )
            logger.info(
                "quota_admission_idempotent_replay",
                extra={
                    "institution_id": str(request.institution_id),
                    "reservation_id": str(existing.id),
                    "usage_date": existing.usage_date.isoformat(),
                    "category": existing.usage_category,
                },
            )
            return AdmissionResult(
                reservation=to_reservation_snapshot(existing),
                is_idempotent_replay=True,
            )

    if quota.is_suspended:
        raise TenantQuotaSuspendedError(request.institution_id, quota.suspension_reason)

    requested_tokens = request.estimated_input_tokens + request.reserved_output_tokens
    if requested_tokens > quota.max_tokens_per_request:
        raise QuotaExceededError(
            "Requested tokens exceed max_tokens_per_request ceiling",
            limit_type="PER_REQUEST_LIMIT",
            institution_id=request.institution_id,
            usage_category=request.usage_category,
            current_value=0,
            requested_value=requested_tokens,
            limit_value=quota.max_tokens_per_request,
        )

    usage_date = resolve_tenant_usage_date(quota_timezone=quota.quota_timezone, as_of=now)
    pricing_version = (
        await resolve_pricing_version_by_id(db, request.pricing_version)
        if request.pricing_version is not None
        else await resolve_active_pricing_version(db, as_of=now)
    )
    cost = calculate_cost_breakdown(
        pricing_version,
        provider=request.provider,
        model=request.model,
        input_tokens=request.estimated_input_tokens,
        output_tokens=request.reserved_output_tokens,
    )

    daily, cat = await upsert_and_lock_level2(
        db,
        institution_id=request.institution_id,
        usage_date=usage_date,
        usage_category=request.usage_category,
    )

    if not quota.is_unlimited:
        await _enforce_quota_ceilings(
            db,
            quota=quota,
            daily=daily,
            cat=cat,
            usage_date=usage_date,
            request=request,
            cost_inr=cost.total_cost_inr,
        )

    reservation = AITokenReservation(
        id=uuid.uuid4(),
        institution_id=request.institution_id,
        user_id=request.user_id,
        logical_operation_id=request.logical_operation_id or uuid.uuid4(),
        usage_date=usage_date,
        usage_category=request.usage_category,
        endpoint=request.endpoint,
        status="RESERVED",
        pricing_version=pricing_version.version_id,
        estimated_input_tokens=request.estimated_input_tokens,
        reserved_output_tokens=request.reserved_output_tokens,
        total_reserved_tokens=requested_tokens,
        reserved_cost_inr=cost.total_cost_inr,
        idempotency_key=request.idempotency_key,
        created_at=now,
        expires_at=now + timedelta(seconds=request.ttl_seconds),
    )
    db.add(reservation)

    daily.pending_reserved_tokens += requested_tokens
    daily.pending_reserved_cost_inr += cost.total_cost_inr
    daily.request_count += 1
    daily.version += 1
    cat.pending_reserved_tokens += requested_tokens
    await db.flush()

    logger.info(
        "quota_admission_reserved",
        extra={
            "institution_id": str(request.institution_id),
            "reservation_id": str(reservation.id),
            "usage_date": usage_date.isoformat(),
            "category": request.usage_category,
            "endpoint": request.endpoint,
            "tokens_reserved": requested_tokens,
            "reserved_cost_inr": str(cost.total_cost_inr),
            "pricing_version": pricing_version.version_id,
        },
    )
    return AdmissionResult(
        reservation=to_reservation_snapshot(reservation),
        is_idempotent_replay=False,
        cost_breakdown=cost,
    )


async def recover_reservation_by_idempotency_key_tx(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    idempotency_key: str,
    expected_request: ReservationCreateRequest | None = None,
) -> ReservationSnapshot | None:
    """
    Verify commit outcome for an uncertain Tx 1 failure using `(institution_id, idempotency_key)`.
    """
    normalized_key = validate_non_empty_text(
        idempotency_key, field_name="idempotency_key", max_length=255
    )
    existing = await _find_reservation_by_idempotency_key(
        db,
        institution_id=institution_id,
        idempotency_key=normalized_key,
        for_update=False,
    )
    if existing is None:
        return None
    if expected_request is not None:
        if expected_request.institution_id != institution_id:
            raise ValueError("expected_request.institution_id does not match institution_id")
        mismatched = _find_mismatched_idempotency_fields(existing, expected_request)
        if mismatched:
            raise IdempotencyConflictError(
                f"Recovered reservation for idempotency_key {normalized_key!r} conflicts on: "
                f"{', '.join(mismatched)}",
                institution_id=institution_id,
                idempotency_key=normalized_key,
                mismatched_fields=mismatched,
            )
    return to_reservation_snapshot(existing)


async def release_pre_dispatch_tx(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    reservation_id: uuid.UUID,
    reason: str = "PRE_DISPATCH_CANCELLED",
    require_expired: bool = False,
    as_of: datetime | None = None,
) -> ReservationSnapshot:
    """
    Execute Tx 1B: Release or expire an un-dispatched `RESERVED` reservation (`RESERVED -> RELEASED`).

    Credits full reserved tokens and INR cost back to the reservation's originating `usage_date`.
    """
    now = _utc_now(as_of)
    norm_reason = validate_non_empty_text(reason, field_name="reason", max_length=100)
    routing = await load_reservation_routing(
        db, institution_id=institution_id, reservation_id=reservation_id
    )
    daily, cat = await upsert_and_lock_level2(
        db,
        institution_id=institution_id,
        usage_date=routing.usage_date,
        usage_category=routing.usage_category,
    )
    res, _ = await lock_reservation_and_attempts(
        db, institution_id=institution_id, reservation_id=reservation_id
    )

    if res.status == "RELEASED" and res.dispatched_at is None:
        return to_reservation_snapshot(res)

    if res.status != "RESERVED":
        raise InvalidStateTransitionError(
            f"Cannot pre-dispatch release reservation in status {res.status!r}",
            current_state=res.status,
            target_state="RELEASED",
            entity_type="reservation",
        )

    if require_expired and now < res.expires_at:
        raise InvalidStateTransitionError(
            "Pre-dispatch reservation TTL has not expired yet",
            current_state=res.status,
            target_state="RELEASED",
            entity_type="reservation",
        )

    effective_reconciled_at = max(now, res.created_at)
    res.status = "RELEASED"
    res.reconciled_at = effective_reconciled_at
    res.reconciliation_version += 1
    res.recovery_reason = norm_reason

    daily.pending_reserved_tokens -= res.total_reserved_tokens
    daily.pending_reserved_cost_inr -= res.reserved_cost_inr
    daily.version += 1
    cat.pending_reserved_tokens -= res.total_reserved_tokens
    await db.flush()

    logger.info(
        "quota_reservation_released_pre_dispatch",
        extra={
            "institution_id": str(institution_id),
            "reservation_id": str(res.id),
            "usage_date": res.usage_date.isoformat(),
            "reason": norm_reason,
            "tokens_released": res.total_reserved_tokens,
        },
    )
    return to_reservation_snapshot(res)

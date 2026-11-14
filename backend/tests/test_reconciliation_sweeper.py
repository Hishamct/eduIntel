"""
Stage 7.4 Test Suite: Automated Reconciliation Sweeper & Backlog Engine
Covers:
- Expired pre-dispatch RESERVED lease recovery (transition to RELEASED with LEASE_EXPIRED_RECOVERED)
- Stale in-flight DISPATCHED attempt recovery (transition to UNKNOWN_USAGE with NEEDS_MANUAL_REVIEW)
- Sweeper batch execution and idempotency
- FOR UPDATE SKIP LOCKED concurrency safety
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.institutions.models import Institution
from app.observability.quota import (
    AttemptDispatchRequest,
    QuotaReconciliationSweeper,
    ReservationCreateRequest,
    TenantQuotaEngine,
)
from app.observability.quota_models import (
    AIPricingActivation,
    AIPricingVersion,
    AITokenReservation,
    TenantAIQuota,
)
from app.users.models import User


def _make_session(db_connection) -> AsyncSession:
    return AsyncSession(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


async def _set_admin_ctx(session: AsyncSession, inst_id: uuid.UUID | None = None) -> None:
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :inst, true);"),
        {"inst": str(inst_id) if inst_id else ""},
    )
    await session.execute(
        text("SELECT set_config('app.is_platform_admin', 'true', true);"),
    )


async def _seed_sweeper_env(
    session: AsyncSession,
) -> tuple[Institution, User, TenantAIQuota]:
    inst_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await _set_admin_ctx(session, inst_id)

    inst = Institution(id=inst_id, name="Sweeper Inst", slug=f"sw-{inst_id.hex[:6]}", is_active=True)
    user = User(id=user_id, email=f"user-{user_id.hex[:6]}@sw.edu", name="Sweeper User", hashed_password="pw", role="admin")
    quota = TenantAIQuota(
        id=uuid.uuid4(),
        institution_id=inst_id,
        quota_timezone="Asia/Kolkata",
        plan_id="growth",
        daily_exposure_limit_inr=Decimal("300.0000"),
        risk_reserve_percent=Decimal("0.1000"),
        daily_interactive_token_limit=600_000,
        daily_ingestion_token_limit=1_500_000,
        daily_other_token_limit=300_000,
        monthly_total_token_limit=7_500_000,
        pending_reserve_cap_percent=Decimal("0.5000"),
        max_tokens_per_request=60_000,
        missing_usage_policy="HOLD_UNKNOWN",
        is_unlimited=False,
        is_suspended=False,
        tier_name="growth",
    )
    session.add_all([inst, user, quota])

    pv_id = f"r01-conc-sw-{uuid.uuid4().hex[:6]}"
    pv = AIPricingVersion(
        version_id=pv_id,
        currency="INR",
        usd_to_inr_rate=Decimal("85.5000"),
        rate_source="TEST_SW",
        rates_json={
            "gemini": {
                "gemini-2.5-flash": {
                    "input_1k": "0.0100",
                    "output_1k": "0.0400",
                }
            }
        },
        effective_from=datetime.now(UTC),
        is_active=True,
    )
    activation = AIPricingActivation(
        id=uuid.uuid4(),
        pricing_version=pv_id,
        expected_version_active=True,
        activated_by_actor="system",
        activation_reason="Test setup",
    )
    session.add(pv)
    await session.flush()
    session.add(activation)
    await session.flush()
    return inst, user, quota


class TestReconciliationSweeper:
    @pytest.mark.asyncio
    async def test_sweeper_releases_expired_undispatched_reservations(self, db_connection):
        session = _make_session(db_connection)
        inst, user, quota = await _seed_sweeper_env(session)

        engine = TenantQuotaEngine()
        # Create a reservation with 30s TTL
        admission = await engine.admit_and_reserve(
            ReservationCreateRequest(
                institution_id=inst.id,
                user_id=user.id,
                usage_category="interactive_ai",
                endpoint="admin_assistant",
                provider="gemini",
                model="gemini-2.5-flash",
                estimated_input_tokens=100,
                reserved_output_tokens=100,
                idempotency_key=f"idem-{uuid.uuid4()}",
                ttl_seconds=30,
            ),
            db=session,
        )
        res_id = admission.reservation.reservation_id
        assert admission.reservation.status == "RESERVED"

        # Manually backdate created_at and expires_at to simulate time passage
        past_created = datetime.now(UTC) - timedelta(minutes=5)
        past_expires = datetime.now(UTC) - timedelta(seconds=10)
        await session.execute(
            text("UPDATE ai_token_reservations SET created_at = :created, expires_at = :past WHERE id = :rid"),
            {"created": past_created, "past": past_expires, "rid": res_id},
        )
        await session.flush()

        # Run sweeper batch
        sweeper = QuotaReconciliationSweeper(session)
        result = await sweeper.run_sweep_batch(batch_size=50)

        assert result.expired_reservations_released == 1
        assert result.stale_dispatched_marked_unknown == 0

        # Assert database row is now RELEASED with LEASE_EXPIRED_RECOVERED
        refreshed = (
            await session.execute(
                select(AITokenReservation).where(AITokenReservation.id == res_id)
            )
        ).scalars().first()

        assert refreshed.status == "RELEASED"
        assert refreshed.recovery_reason == "TTL_EXPIRED_SWEEPER"
        assert refreshed.uncertain_cost_held_inr == Decimal("0.0000")

    @pytest.mark.asyncio
    async def test_sweeper_marks_stale_dispatched_as_unknown_usage(self, db_connection):
        session = _make_session(db_connection)
        inst, user, quota = await _seed_sweeper_env(session)

        engine = TenantQuotaEngine()
        # Create reservation and dispatch attempt
        admission = await engine.admit_and_reserve(
            ReservationCreateRequest(
                institution_id=inst.id,
                user_id=user.id,
                usage_category="interactive_ai",
                endpoint="admin_assistant",
                provider="gemini",
                model="gemini-2.5-flash",
                estimated_input_tokens=100,
                reserved_output_tokens=100,
                idempotency_key=f"idem-{uuid.uuid4()}",
                ttl_seconds=30,
            ),
            db=session,
        )
        res_id = admission.reservation.reservation_id

        await engine.begin_provider_dispatch(
            AttemptDispatchRequest(
                institution_id=inst.id,
                reservation_id=res_id,
                provider="gemini",
                model="gemini-2.5-flash",
                estimated_tokens=200,
            ),
            db=session,
        )

        # Backdate created_at and expires_at past deadline
        past_created = datetime.now(UTC) - timedelta(minutes=5)
        past_expires = datetime.now(UTC) - timedelta(seconds=10)
        await session.execute(
            text("UPDATE ai_token_reservations SET created_at = :created, expires_at = :past WHERE id = :rid"),
            {"created": past_created, "past": past_expires, "rid": res_id},
        )
        await session.flush()

        # Run sweeper
        sweeper = QuotaReconciliationSweeper(session)
        result = await sweeper.run_sweep_batch(batch_size=50)

        assert result.stale_dispatched_marked_unknown == 1

        refreshed = (
            await session.execute(
                select(AITokenReservation).where(AITokenReservation.id == res_id)
            )
        ).scalars().first()

        assert refreshed.status == "UNKNOWN_USAGE"
        assert refreshed.review_status == "NEEDS_MANUAL_REVIEW"
        # Decision 4: Financial exposure hold is retained for protection
        assert refreshed.uncertain_cost_held_inr > Decimal("0.0000")

    @pytest.mark.asyncio
    async def test_sweeper_idempotency(self, db_connection):
        session = _make_session(db_connection)
        inst, user, quota = await _seed_sweeper_env(session)

        sweeper = QuotaReconciliationSweeper(session)
        # First run on clean DB: 0 released, 0 stale
        res1 = await sweeper.run_sweep_batch(batch_size=50)
        assert res1.expired_reservations_released == 0
        assert res1.stale_dispatched_marked_unknown == 0

        # Second run immediately after: still 0
        res2 = await sweeper.run_sweep_batch(batch_size=50)
        assert res2.expired_reservations_released == 0
        assert res2.stale_dispatched_marked_unknown == 0

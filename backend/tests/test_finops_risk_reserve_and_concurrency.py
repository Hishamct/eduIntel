"""
Stage 7.4 Test Suite: FinOps Risk Reserve Calculation & Quota Concurrency
Covers:
- Decision 1 & 2: 10% protected risk reserve buffer on daily financial ceiling
- Available exposure calculation: max(0, daily_exposure_limit_inr - risk_reserve_inr)
- Rejection at available exposure boundary (below nominal ceiling)
- Decision 3: Independent quota enforcement across interactive_ai, ingestion_embeddings, and other_metered
- Cross-category isolation (exhausted interactive quota does not block ingestion embeddings)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.institutions.models import Institution
from app.observability.quota import (
    QuotaExceededError,
    ReservationCreateRequest,
    TenantQuotaEngine,
)
from app.observability.quota_models import (
    AIPricingActivation,
    AIPricingVersion,
    TenantAIQuota,
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
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


async def _seed_test_env(
    session: AsyncSession,
    *,
    daily_exposure_inr: Decimal = Decimal("100.0000"),
    risk_reserve_pct: Decimal = Decimal("0.1000"),
    interactive_tokens: int = 10_000,
    ingestion_tokens: int = 50_000,
    other_tokens: int = 5_000,
) -> tuple[Institution, User, TenantAIQuota]:
    inst_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await _set_admin_ctx(session, inst_id)

    inst = Institution(id=inst_id, name="Risk Reserve Inst", slug=f"rr-{inst_id.hex[:6]}", is_active=True)
    user = User(id=user_id, email=f"user-{user_id.hex[:6]}@rr.edu", name="RR User", hashed_password="pw", role="admin")
    quota = TenantAIQuota(
        id=uuid.uuid4(),
        institution_id=inst_id,
        quota_timezone="Asia/Kolkata",
        plan_id="starter",
        daily_exposure_limit_inr=daily_exposure_inr,
        risk_reserve_percent=risk_reserve_pct,
        daily_interactive_token_limit=interactive_tokens,
        daily_ingestion_token_limit=ingestion_tokens,
        daily_other_token_limit=other_tokens,
        monthly_total_token_limit=500_000,
        pending_reserve_cap_percent=Decimal("0.5000"),
        max_tokens_per_request=25_000,
        missing_usage_policy="HOLD_UNKNOWN",
        is_unlimited=False,
        is_suspended=False,
        tier_name="starter",
    )
    session.add_all([inst, user, quota])

    # Seed pricing version if not present
    pv_id = f"r01-conc-rr-{uuid.uuid4().hex[:6]}"
    pv = AIPricingVersion(
        version_id=pv_id,
        currency="INR",
        usd_to_inr_rate=Decimal("85.5000"),
        rate_source="TEST_RR",
        rates_json={
            "gemini": {
                "gemini-2.5-flash": {
                    "input_1k": "0.0100",
                    "output_1k": "0.0400",
                },
                "text-embedding-004": {
                    "input_1k": "0.0050",
                    "output_1k": "0.0000",
                },
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


class TestFinOpsRiskReserveAndConcurrency:
    @pytest.mark.asyncio
    async def test_risk_reserve_math_blocks_at_available_exposure(self, db_connection):
        """
        Nominal daily exposure limit: ₹100.00.
        Risk reserve: 10% = ₹10.00.
        Available exposure: ₹90.00.
        When committed spend reaches ₹89.50, an estimated ₹1.00 reservation must be rejected!
        """
        session = _make_session(db_connection)
        inst, user, quota = await _seed_test_env(
            session,
            daily_exposure_inr=Decimal("100.0000"),
            risk_reserve_pct=Decimal("0.1000"),
            interactive_tokens=100_000,
        )

        # Commit ₹89.60 of spend today
        today = datetime.now(UTC).date()
        usage = TenantDailyAIUsage(
            id=uuid.uuid4(),
            institution_id=inst.id,
            usage_date=today,
            committed_cost_inr=Decimal("89.6000"),
            committed_total_tokens=1500,
            pending_reserved_cost_inr=Decimal("0.0000"),
            pending_reserved_tokens=0,
            uncertain_exposure_cost_inr=Decimal("0.0000"),
            uncertain_reserved_tokens=0,
            request_count=5,
        )
        session.add(usage)
        await session.flush()

        engine = TenantQuotaEngine()

        # An operation estimated at ₹0.50 brings total exposure to ₹90.10,
        # exceeding available exposure ₹90.00 (protecting 10% risk reserve of ₹10.00)
        with pytest.raises(QuotaExceededError) as exc_info:
            await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="admin_assistant",
                    provider="gemini",
                    model="gemini-2.5-flash",
                    estimated_input_tokens=10_000,
                    reserved_output_tokens=10_000,
                    idempotency_key=f"idem-{uuid.uuid4()}",
                ),
                db=session,
            )
        assert "exposure limit exceeded" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_admission_succeeds_within_available_exposure(self, db_connection):
        """
        Nominal daily exposure limit: ₹100.00.
        Risk reserve: 10% = ₹10.00.
        Available exposure: ₹90.00.
        Committed spend: ₹50.00.
        Small operation fits comfortably within available exposure.
        """
        session = _make_session(db_connection)
        inst, user, quota = await _seed_test_env(
            session,
            daily_exposure_inr=Decimal("100.0000"),
            risk_reserve_pct=Decimal("0.1000"),
        )

        today = datetime.now(UTC).date()
        usage = TenantDailyAIUsage(
            id=uuid.uuid4(),
            institution_id=inst.id,
            usage_date=today,
            committed_cost_inr=Decimal("50.0000"),
            committed_total_tokens=1500,
            pending_reserved_cost_inr=Decimal("0.0000"),
            pending_reserved_tokens=0,
            uncertain_exposure_cost_inr=Decimal("0.0000"),
            uncertain_reserved_tokens=0,
            request_count=5,
        )
        session.add(usage)
        await session.flush()

        engine = TenantQuotaEngine()
        res = await engine.admit_and_reserve(
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
            ),
            db=session,
        )
        assert res is not None
        assert res.reservation.institution_id == inst.id
        assert res.reservation.status == "RESERVED"

    @pytest.mark.asyncio
    async def test_independent_category_quota_enforcement(self, db_connection):
        """
        Decision 3:
        Exhausting daily_interactive_token_limit (e.g. 10,000) does NOT block
        ingestion_embeddings requests if ingestion limit (e.g. 50,000) has headroom.
        """
        session = _make_session(db_connection)
        inst, user, quota = await _seed_test_env(
            session,
            daily_exposure_inr=Decimal("500.0000"),
            interactive_tokens=10_000,
            ingestion_tokens=50_000,
        )

        today = datetime.now(UTC).date()
        # Commit 10,000 tokens to interactive_ai
        daily_usage = TenantDailyAIUsage(
            id=uuid.uuid4(),
            institution_id=inst.id,
            usage_date=today,
            committed_cost_inr=Decimal("0.0000"),
            committed_total_tokens=10_000,
            pending_reserved_cost_inr=Decimal("0.0000"),
            pending_reserved_tokens=0,
            uncertain_exposure_cost_inr=Decimal("0.0000"),
            uncertain_reserved_tokens=0,
            request_count=1,
        )
        cat_usage = TenantDailyCategoryUsage(
            id=uuid.uuid4(),
            institution_id=inst.id,
            usage_date=today,
            usage_category="interactive_ai",
            committed_input_tokens=8_000,
            committed_output_tokens=2_000,
            committed_total_tokens=10_000,
            pending_reserved_tokens=0,
            uncertain_reserved_tokens=0,
        )
        session.add_all([daily_usage, cat_usage])
        await session.flush()

        engine = TenantQuotaEngine()

        # Interactive AI reservation should now be rejected due to category limit exhaustion
        with pytest.raises(QuotaExceededError) as exc_info:
            await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="admin_assistant",
                    provider="gemini",
                    model="gemini-2.5-flash",
                    estimated_input_tokens=500,
                    reserved_output_tokens=500,
                    idempotency_key=f"idem-{uuid.uuid4()}",
                ),
                db=session,
            )
        assert "quota exceeded" in str(exc_info.value).lower()

        # Ingestion embeddings reservation MUST SUCCEED because it has 50,000 headroom
        ingest_res = await engine.admit_and_reserve(
            ReservationCreateRequest(
                institution_id=inst.id,
                user_id=user.id,
                usage_category="ingestion_embeddings",
                endpoint="rag_ingestion",
                provider="gemini",
                model="text-embedding-004",
                estimated_input_tokens=1000,
                reserved_output_tokens=0,
                idempotency_key=f"idem-{uuid.uuid4()}",
            ),
            db=session,
        )
        assert ingest_res is not None
        assert ingest_res.reservation.usage_category == "ingestion_embeddings"
        assert ingest_res.reservation.status == "RESERVED"

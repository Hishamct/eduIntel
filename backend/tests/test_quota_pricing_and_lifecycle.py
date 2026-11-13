"""
Stage 7.2 Comprehensive Unit & Single-Session PostgreSQL Tests:
- Active pricing version resolution (activation ledger) & strict Decimal math
- Quota configuration & limits (daily/monthly/exposure/reserve-cap/per-request/unlimited/suspended)
- Reservation & multi-attempt lifecycle state machine (no EXPIRED state)
- Operator manual settlement & late provider variance adjustments
- Tenant timezone pinning & midnight rollover conservation
- Policy-neutral missing-usage fail-closed behavior
- Cross-tenant RLS isolation & non-sensitive structured logging
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.institutions.models import Institution
from app.observability.quota import (
    AttemptDispatchRequest,
    FailClosedMissingUsagePolicyResolver,
    IdempotencyConflictError,
    InvalidPricingSchemaError,
    InvalidStateTransitionError,
    MissingUsageContext,
    MissingUsagePolicyPendingError,
    MissingUsageResolution,
    PricingModelRateNotFoundError,
    PricingVersionNotFoundError,
    QuotaConfigurationError,
    QuotaExceededError,
    ReservationCreateRequest,
    ReservationExpiredError,
    ReservationNotFoundError,
    TenantQuotaEngine,
    TenantQuotaNotConfiguredError,
    TenantQuotaSuspendedError,
    calculate_cost_breakdown,
    resolve_active_pricing_version,
    resolve_tenant_usage_date,
)
from app.observability.quota_models import (
    AIFinancialAdjustment,
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


async def _seed_tenant(
    session: AsyncSession,
    *,
    prefix: str,
    quota_timezone: str = "Asia/Kolkata",
    daily_interactive_limit: int = 10_000,
    daily_ingestion_limit: int = 20_000,
    daily_other_limit: int = 5_000,
    monthly_total_limit: int | None = 100_000,
    daily_exposure_limit_inr: Decimal = Decimal("50.0000"),
    pending_reserve_cap_percent: Decimal = Decimal("0.5000"),
    max_tokens_per_request: int = 4_000,
    missing_usage_policy: str = "HOLD_UNKNOWN",
    is_unlimited: bool = False,
    is_suspended: bool = False,
) -> tuple[Institution, User, TenantAIQuota]:
    inst_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await _set_admin_ctx(session, inst_id)

    inst = Institution(
        id=inst_id,
        name=f"Stage72 Inst {prefix}",
        slug=f"s72-{prefix}-{inst_id.hex[:8]}",
        is_active=True,
    )
    user = User(
        id=user_id,
        email=f"s72-{user_id.hex[:8]}@{prefix}.edu",
        name=f"Stage72 User {prefix}",
        hashed_password=hash_password("StrongTestPass123!"),
        role="admin",
        is_active=True,
    )
    quota = TenantAIQuota(
        id=uuid.uuid4(),
        institution_id=inst_id,
        quota_timezone=quota_timezone,
        daily_interactive_token_limit=daily_interactive_limit,
        daily_ingestion_token_limit=daily_ingestion_limit,
        daily_other_token_limit=daily_other_limit,
        monthly_total_token_limit=monthly_total_limit,
        daily_exposure_limit_inr=daily_exposure_limit_inr,
        pending_reserve_cap_percent=pending_reserve_cap_percent,
        max_tokens_per_request=max_tokens_per_request,
        missing_usage_policy=missing_usage_policy,
        is_unlimited=is_unlimited,
        is_suspended=is_suspended,
        suspension_reason="Suspended for test" if is_suspended else None,
        tier_name="test-tier",
    )
    session.add_all([inst, user, quota])
    await session.flush()
    return inst, user, quota


async def _seed_pricing(
    session: AsyncSession,
    *,
    version_id: str,
    currency: str = "INR",
    usd_to_inr_rate: Decimal = Decimal("85.5000"),
    rates_json: dict | None = None,
    effective_from: datetime | None = None,
    is_active: bool = True,
    activate: bool = True,
) -> AIPricingVersion:
    await _set_admin_ctx(session, None)
    pv = AIPricingVersion(
        version_id=version_id,
        currency=currency,
        usd_to_inr_rate=usd_to_inr_rate,
        rate_source="STAGE72_UNIT_TEST",
        rates_json=rates_json
        if rates_json is not None
        else {
            "gemini": {
                "gemini-3.6-flash": {"input_1k": "0.0100", "output_1k": "0.0400"},
            },
            "groq": {
                "openai/gpt-oss-120b": {"input_1k": "0.0050", "output_1k": "0.0200"},
            },
        },
        effective_from=effective_from or datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        is_active=is_active,
    )
    session.add(pv)
    await session.flush()
    if activate and is_active:
        act = AIPricingActivation(
            id=uuid.uuid4(),
            pricing_version=version_id,
            expected_version_active=True,
            activated_by_actor="test-admin",
            activation_reason="TEST_ACTIVATION",
        )
        session.add(act)
        await session.flush()
    return pv


class TestStage72PricingResolutionAndMath:
    """Verify authoritative activation resolution and strict Decimal cost calculation."""

    def test_pure_decimal_pricing_math_and_schema_validation(self):
        pv_inr = AIPricingVersion(
            version_id="v-inr-1",
            currency="INR",
            usd_to_inr_rate=Decimal("86.0000"),
            rate_source="TEST",
            rates_json={
                "gemini": {"g1": {"input_1k": "0.0125", "output_1k": "0.0505"}},
                "groq": {"free-m": {"input_1k": "0.0000", "output_1k": "0.0000"}},
                "openai": {"m-usd": {"input_usd_per_1k": "0.0010", "output_usd_per_1k": "0.0020"}},
            },
            effective_from=datetime.now(UTC) - timedelta(days=1),
            is_active=True,
        )
        # 500 in @ 0.0125/1k = 0.00625; 100 out @ 0.0505/1k = 0.00505 -> raw 0.01130 -> 0.0113
        bd = calculate_cost_breakdown(pv_inr, provider="gemini", model="g1", input_tokens=500, output_tokens=100)
        assert bd.total_cost_inr == Decimal("0.0113")

        # ROUND_HALF_UP check: 4 tokens @ 0.0125/1k = 0.00005 -> rounds half up to 0.0001
        bd_half = calculate_cost_breakdown(pv_inr, provider="gemini", model="g1", input_tokens=4, output_tokens=0)
        assert bd_half.total_cost_inr == Decimal("0.0001")

        # Explicit USD keys multiply by usd_to_inr_rate (1k in + 1k out = 0.003 * 86 = 0.2580 INR)
        bd_usd = calculate_cost_breakdown(
            pv_inr, provider="openai", model="m-usd", input_tokens=1000, output_tokens=1000
        )
        assert bd_usd.total_cost_inr == Decimal("0.2580")

        # Explicit zero rate allowed when declared cleanly
        bd_zero = calculate_cost_breakdown(pv_inr, provider="groq", model="free-m", input_tokens=500, output_tokens=500)
        assert bd_zero.total_cost_inr == Decimal("0.0000")

        # Unknown provider or model fails closed
        with pytest.raises(PricingModelRateNotFoundError):
            calculate_cost_breakdown(pv_inr, provider="anthropic", model="claude", input_tokens=10, output_tokens=10)
        with pytest.raises(PricingModelRateNotFoundError):
            calculate_cost_breakdown(pv_inr, provider="gemini", model="missing-model", input_tokens=10, output_tokens=10)

        # Reject floats, booleans, negative numbers, NaN strings
        for bad_rates in (
            {"gemini": {"g1": {"input_1k": 0.01, "output_1k": "0.02"}}},
            {"gemini": {"g1": {"input_1k": True, "output_1k": "0.02"}}},
            {"gemini": {"g1": {"input_1k": "-0.01", "output_1k": "0.02"}}},
            {"gemini": {"g1": {"input_1k": "NaN", "output_1k": "0.02"}}},
            {"gemini": {"g1": {"only_in": "0.01"}}},
        ):
            bad_pv = AIPricingVersion(
                version_id="v-bad",
                currency="INR",
                usd_to_inr_rate=Decimal("85.0000"),
                rate_source="TEST",
                rates_json=bad_rates,
                effective_from=datetime.now(UTC) - timedelta(days=1),
                is_active=True,
            )
            with pytest.raises(InvalidPricingSchemaError):
                calculate_cost_breakdown(bad_pv, provider="gemini", model="g1", input_tokens=100, output_tokens=100)

    @pytest.mark.asyncio
    async def test_activation_sequence_precedence_and_fail_closed_when_absent(self, db_connection):
        class _EmptyResult:
            def scalar_one_or_none(self):
                return None

        class _EmptySession:
            async def execute(self, _stmt):
                return _EmptyResult()

        with pytest.raises(PricingVersionNotFoundError):
            await resolve_active_pricing_version(_EmptySession())  # type: ignore[arg-type]

        session = _make_session(db_connection)
        try:
            inst, user, _ = await _seed_tenant(session, prefix="prc")
            engine = TenantQuotaEngine()

            req = ReservationCreateRequest(
                institution_id=inst.id,
                user_id=user.id,
                usage_category="interactive_ai",
                endpoint="admin-assistant/generate",
                provider="gemini",
                model="gemini-3.6-flash",
                estimated_input_tokens=1000,
                reserved_output_tokens=1000,
                idempotency_key="fail-no-pricing",
            )

            # Future effective_from becomes highest activation_seq in savepoint -> fails closed
            await _seed_pricing(
                session,
                version_id=f"v-future-{uuid.uuid4().hex[:6]}",
                effective_from=datetime.now(UTC) + timedelta(days=2),
            )
            with pytest.raises(PricingVersionNotFoundError):
                await engine.admit_and_reserve(req, db=session)

            # Activation sequence switches cleanly: v1 -> v2 -> v1 rollback wins by max activation_seq
            v1_id = f"v1-{uuid.uuid4().hex[:6]}"
            v2_id = f"v2-{uuid.uuid4().hex[:6]}"
            await _seed_pricing(session, version_id=v1_id, activate=True)
            await _seed_pricing(
                session,
                version_id=v2_id,
                rates_json={"gemini": {"gemini-3.6-flash": {"input_1k": "0.1000", "output_1k": "0.2000"}}},
                activate=True,
            )
            res_v2 = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="admin-assistant/generate",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=1000,
                    idempotency_key="admit-v2",
                ),
                db=session,
            )
            assert res_v2.reservation.pricing_version == v2_id
            assert res_v2.reservation.reserved_cost_inr == Decimal("0.3000")

            # Re-activate v1 -> new reservations pin v1, existing v2 dispatch still settles at v2!
            await _set_admin_ctx(session, None)
            session.add(
                AIPricingActivation(
                    id=uuid.uuid4(),
                    pricing_version=v1_id,
                    expected_version_active=True,
                    activated_by_actor="test-admin",
                    activation_reason="ROLLBACK_TO_V1",
                )
            )
            await session.flush()

            _, att_v2 = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=res_v2.reservation.id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=2000,
                    pricing_version=res_v2.reservation.pricing_version,
                ),
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=res_v2.reservation.id,
                attempt_id=att_v2.id,
                status="SUCCEEDED",
                input_tokens=1000,
                output_tokens=1000,
                db=session,
            )
            fin_v2 = await engine.finalize_reservation(
                institution_id=inst.id, reservation_id=res_v2.reservation.id, db=session
            )
            assert fin_v2.reservation.actual_cost_inr == Decimal("0.3000")

            res_v1 = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="admin-assistant/generate",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=1000,
                    idempotency_key="admit-v1",
                ),
                db=session,
            )
            assert res_v1.reservation.pricing_version == v1_id
            assert res_v1.reservation.reserved_cost_inr == Decimal("0.0500")
        finally:
            await session.close()


class TestStage72AdmissionCapsAndTimezonePinning:
    """Verify every admission cap, timezone rollover pinning, and suspend/unlimited switches."""

    @pytest.mark.asyncio
    async def test_all_admission_limits_and_switches(self, db_connection):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            engine = TenantQuotaEngine()

            # 1. Missing TenantAIQuota -> fail closed
            unconfigured_inst = uuid.uuid4()
            with pytest.raises(TenantQuotaNotConfiguredError):
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=unconfigured_inst,
                        user_id=uuid.uuid4(),
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=100,
                        reserved_output_tokens=100,
                    ),
                    db=session,
                )

            # 2. Suspended tenant (even with is_unlimited=True) -> TenantQuotaSuspendedError
            susp_inst, susp_user, _ = await _seed_tenant(
                session, prefix="susp", is_unlimited=True, is_suspended=True
            )
            with pytest.raises(TenantQuotaSuspendedError):
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=susp_inst.id,
                        user_id=susp_user.id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=100,
                        reserved_output_tokens=100,
                    ),
                    db=session,
                )

            # 3. Invalid quota_timezone -> QuotaConfigurationError
            tz_inst, tz_user, _ = await _seed_tenant(session, prefix="badtz", quota_timezone="Mars/Olympus")
            with pytest.raises(QuotaConfigurationError):
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=tz_inst.id,
                        user_id=tz_user.id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=100,
                        reserved_output_tokens=100,
                    ),
                    db=session,
                )

            # 4. Per-request, Reserve Cap, Daily Category, Financial Exposure, Monthly limits
            inst, user, _ = await _seed_tenant(
                session,
                prefix="caps",
                daily_interactive_limit=5_000,
                daily_other_limit=10_000,
                monthly_total_limit=6_000,
                daily_exposure_limit_inr=Decimal("0.1800"),
                pending_reserve_cap_percent=Decimal("0.4000"),  # cap = 2,000 interactive concurrent
                max_tokens_per_request=2_500,
            )

            # Exceeds max_tokens_per_request (2600 > 2500)
            with pytest.raises(QuotaExceededError) as exc_req:
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst.id,
                        user_id=user.id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=1600,
                        reserved_output_tokens=1000,
                    ),
                    db=session,
                )
            assert exc_req.value.limit_type == "PER_REQUEST_LIMIT"

            # Exceeds pending_reserve_cap_percent (2100 > 2000)
            with pytest.raises(QuotaExceededError) as exc_cap:
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst.id,
                        user_id=user.id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=1100,
                        reserved_output_tokens=1000,
                    ),
                    db=session,
                )
            assert exc_cap.value.limit_type == "PENDING_RESERVE_CAP_LIMIT"

            # Reserve 2000 interactive (cost = 0.01 + 0.04 = 0.05), dispatch & finalize so reserve cap clears!
            t0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
            adm1 = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=1000,
                    idempotency_key="cap-1",
                ),
                as_of=t0,
                db=session,
            )
            _, att1 = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=adm1.reservation.id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=2000,
                ),
                as_of=t0,
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=adm1.reservation.id,
                attempt_id=att1.id,
                status="SUCCEEDED",
                input_tokens=1000,
                output_tokens=2500,  # committed 3500 tokens, cost = 0.01 + 0.10 = 0.11 INR
                as_of=t0,
                db=session,
            )
            await engine.finalize_reservation(
                institution_id=inst.id, reservation_id=adm1.reservation.id, as_of=t0, db=session
            )

            # Now interactive committed = 3500 / 5000 (1500 left), daily INR = 0.11 / 0.18 (0.07 left)
            # Request 1600 interactive -> rejected by DAILY_CATEGORY_LIMIT (3500 + 1600 > 5000)
            with pytest.raises(QuotaExceededError) as exc_daily:
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst.id,
                        user_id=user.id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=800,
                        reserved_output_tokens=800,
                    ),
                    as_of=t0,
                    db=session,
                )
            assert exc_daily.value.limit_type == "DAILY_CATEGORY_LIMIT"

            # Request 2000 other_metered (cost = 0.01 + 0.04 = 0.05) succeeds on other category
            # WAIT: committed (0.11) + 0.05 = 0.16 <= 0.18 INR, monthly 3500 + 2000 = 5500 <= 6000!
            await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="other_metered",
                    endpoint="reports/summary",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=1000,
                    idempotency_key="cap-2-other",
                ),
                as_of=t0,
                db=session,
            )

            # Next day in same month (5500 monthly used / 6000 limit) -> 600 tokens blocked by MONTHLY_TOTAL_LIMIT
            t_next_day = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
            with pytest.raises(QuotaExceededError) as exc_mon:
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst.id,
                        user_id=user.id,
                        usage_category="other_metered",
                        endpoint="reports/summary",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=300,
                        reserved_output_tokens=300,
                    ),
                    as_of=t_next_day,
                    db=session,
                )
            assert exc_mon.value.limit_type == "MONTHLY_TOTAL_LIMIT"

            # Financial INR ceiling: 500 interactive tokens on day 1 where only 0.02 INR left (< 0.0200? 500 out = 0.0200, 500 in+1000 out = 0.045 > 0.02)
            # 100 in + 500 out = 600 tokens: check on day 1 hits MONTHLY first if >500; let 200 in + 300 out = 500 tokens:
            # 5500+500=6000 monthly ok, 3500+500=4000 daily ok, INR = 0.002+0.012 = 0.014 ok -> use 0 in + 500 out? Wait let's use 0 in + 501 out -> wait monthly 5500+500 <= 6000:
            # Make ingestion request 100 in + 400 out (=0.001 + 0.016 = 0.017 ok), OR test dedicated INR ceiling cleanly:
            inr_inst, inr_user, _ = await _seed_tenant(
                session,
                prefix="inr",
                daily_interactive_limit=100_000,
                monthly_total_limit=None,
                daily_exposure_limit_inr=Decimal("0.0300"),
                pending_reserve_cap_percent=Decimal("1.0000"),
                max_tokens_per_request=5_000,
            )
            with pytest.raises(QuotaExceededError) as exc_inr:
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inr_inst.id,
                        user_id=inr_user.id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=1000,
                        reserved_output_tokens=1000,  # 0.0500 > 0.0300
                    ),
                    db=session,
                )
            assert exc_inr.value.limit_type == "DAILY_FINANCIAL_EXPOSURE_LIMIT"

            # is_unlimited=True bypasses daily/monthly/financial caps while still tracking ledger & per-request cap
            unl_inst, unl_user, _ = await _seed_tenant(
                session,
                prefix="unl",
                daily_interactive_limit=100,
                monthly_total_limit=100,
                daily_exposure_limit_inr=Decimal("0.0001"),
                pending_reserve_cap_percent=Decimal("0.1000"),
                max_tokens_per_request=3_000,
                is_unlimited=True,
            )
            adm_unl = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=unl_inst.id,
                    user_id=unl_user.id,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=1000,
                ),
                db=session,
            )
            assert adm_unl.reservation.total_reserved_tokens == 2000
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_ist_midnight_rollover_pins_usage_date_across_lifecycle(self, db_connection):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            inst, user, _ = await _seed_tenant(session, prefix="ist", quota_timezone="Asia/Kolkata")
            engine = TenantQuotaEngine()

            before_midnight_utc = datetime(2026, 11, 12, 18, 29, 59, tzinfo=UTC)  # 23:59:59 IST Nov 12
            after_midnight_utc = datetime(2026, 11, 12, 18, 30, 5, tzinfo=UTC)    # 00:00:05 IST Nov 13

            assert resolve_tenant_usage_date(quota_timezone="Asia/Kolkata", as_of=before_midnight_utc) == date(2026, 11, 12)
            assert resolve_tenant_usage_date(quota_timezone="Asia/Kolkata", as_of=after_midnight_utc) == date(2026, 11, 13)

            # Reserve before midnight (Nov 12 IST), settle AFTER midnight (Nov 13 IST)
            adm = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="agents/admin",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=1000,
                ),
                as_of=before_midnight_utc,
                db=session,
            )
            assert adm.reservation.usage_date == date(2026, 11, 12)

            _, att = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=adm.reservation.id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=2000,
                ),
                as_of=after_midnight_utc,
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=adm.reservation.id,
                attempt_id=att.id,
                status="SUCCEEDED",
                input_tokens=700,
                output_tokens=300,
                as_of=after_midnight_utc,
                db=session,
            )
            fin = await engine.finalize_reservation(
                institution_id=inst.id,
                reservation_id=adm.reservation.id,
                as_of=after_midnight_utc,
                db=session,
            )
            assert fin.reservation.usage_date == date(2026, 11, 12)

            nov12 = (
                await session.execute(
                    select(TenantDailyAIUsage).where(
                        TenantDailyAIUsage.institution_id == inst.id,
                        TenantDailyAIUsage.usage_date == date(2026, 11, 12),
                    )
                )
            ).scalar_one()
            nov13 = (
                await session.execute(
                    select(TenantDailyAIUsage).where(
                        TenantDailyAIUsage.institution_id == inst.id,
                        TenantDailyAIUsage.usage_date == date(2026, 11, 13),
                    )
                )
            ).scalar_one_or_none()
            assert nov12.pending_reserved_tokens == 0
            assert nov12.pending_reserved_cost_inr == Decimal("0.0000")
            assert nov12.committed_total_tokens == 1000
            assert nov12.committed_cost_inr == Decimal("0.0190")
            assert nov13 is None
        finally:
            await session.close()


class TestStage72StateMachineMultiAttemptAndVariance:
    """Verify full lifecycle transitions, multi-attempt sums, manual settle, and late variance."""

    @pytest.mark.asyncio
    async def test_pre_dispatch_release_and_ttl_expiry_guards(self, db_connection):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            inst, user, _ = await _seed_tenant(session, prefix="exp")
            engine = TenantQuotaEngine()
            t0 = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

            adm = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="ingestion_embeddings",
                    endpoint="rag/ingest",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=0,
                    ttl_seconds=60,
                ),
                as_of=t0,
                db=session,
            )

            # Cannot expire before TTL
            with pytest.raises(InvalidStateTransitionError):
                await engine.expire_pre_dispatch(
                    institution_id=inst.id,
                    reservation_id=adm.reservation.id,
                    as_of=t0 + timedelta(seconds=30),
                    db=session,
                )

            # Cannot dispatch after TTL
            with pytest.raises(ReservationExpiredError):
                await engine.begin_provider_dispatch(
                    AttemptDispatchRequest(
                        institution_id=inst.id,
                        reservation_id=adm.reservation.id,
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_tokens=1000,
                    ),
                    as_of=t0 + timedelta(seconds=61),
                    db=session,
                )

            # Valid TTL expiration releases pending reserve cleanly
            rel = await engine.expire_pre_dispatch(
                institution_id=inst.id,
                reservation_id=adm.reservation.id,
                as_of=t0 + timedelta(seconds=61),
                db=session,
            )
            assert rel.status == "RELEASED"
            assert rel.recovery_reason == "PRE_DISPATCH_TTL_EXPIRED"
            assert rel.dispatched_at is None
            assert rel.reconciled_at is not None

            # Idempotent replay returns RELEASED cleanly
            rel_again = await engine.release_pre_dispatch(
                institution_id=inst.id, reservation_id=adm.reservation.id, as_of=t0 + timedelta(seconds=62), db=session
            )
            assert rel_again.status == "RELEASED"
            assert rel_again.reconciliation_version == rel.reconciliation_version

            # Daily and category pending reserves returned to zero
            daily = (
                await session.execute(select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst.id))
            ).scalar_one()
            assert daily.pending_reserved_tokens == 0
            assert daily.pending_reserved_cost_inr == Decimal("0.0000")
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_multi_attempt_cumulative_and_dispatched_ttl_unknown_usage_and_late_arrival(self, db_connection):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            inst, user, _ = await _seed_tenant(
                session, prefix="multi", daily_interactive_limit=50_000, monthly_total_limit=100_000
            )
            engine = TenantQuotaEngine()
            t0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)

            adm = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="agents/admin",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1500,
                    reserved_output_tokens=1000,
                    ttl_seconds=60,
                ),
                as_of=t0,
                db=session,
            )
            # Dispatch Attempt 1 (partial generation 2000 tokens: 1200 in + 800 out = 0.012 + 0.032 = 0.044)
            _, att1 = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=adm.reservation.id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=2000,
                    provider_request_id="gem-req-1",
                ),
                as_of=t0 + timedelta(seconds=1),
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=adm.reservation.id,
                attempt_id=att1.id,
                status="SUCCEEDED",
                input_tokens=1200,
                output_tokens=800,
                as_of=t0 + timedelta(seconds=2),
                db=session,
            )

            # Dispatch fallback Attempt 2 (Groq) even past reservation expires_at — DISPATCHED never expires into RELEASED!
            _, att2 = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=adm.reservation.id,
                    provider="groq",
                    model="openai/gpt-oss-120b",
                    estimated_tokens=1500,
                    is_fallback=True,
                    provider_request_id="groq-req-2",
                ),
                as_of=t0 + timedelta(seconds=120),
                db=session,
            )
            # Mark Attempt 2 / DISPATCHED reservation expired into UNKNOWN_USAGE
            unk = await engine.mark_dispatched_reservation_unknown(
                institution_id=inst.id,
                reservation_id=adm.reservation.id,
                recovery_reason="DISPATCHED_TTL_EXPIRED",
                as_of=t0 + timedelta(seconds=125),
                db=session,
            )
            assert unk.reservation.status == "UNKNOWN_USAGE"
            assert unk.reservation.actual_total_tokens == 2000
            assert unk.reservation.actual_cost_inr == Decimal("0.0440")
            assert unk.reservation.uncertain_tokens_held == 1500
            assert unk.reservation.review_status == "NEEDS_MANUAL_REVIEW"

            daily = (
                await session.execute(select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst.id))
            ).scalar_one()
            assert daily.pending_reserved_tokens == 0
            assert daily.committed_total_tokens == 2000
            assert daily.uncertain_reserved_tokens == 1500
            assert daily.fallback_count == 1
            assert daily.unknown_usage_count == 1

            # Late provider report arrives for Attempt 2: 1000 in + 500 out @ groq (0.005 + 0.010 = 0.0150)
            late = await engine.record_late_provider_usage(
                institution_id=inst.id,
                reservation_id=adm.reservation.id,
                attempt_id=att2.id,
                input_tokens=1000,
                output_tokens=500,
                actor="late-webhook",
                reason="PROVIDER_USAGE_WEBHOOK",
                notes="Late Groq webhook confirmed exact tokens",
                as_of=t0 + timedelta(seconds=300),
                db=session,
            )
            assert late.reservation.status == "COMMITTED"
            assert late.reservation.actual_total_tokens == 3500
            assert late.reservation.actual_cost_inr == Decimal("0.0590")
            assert late.reservation.uncertain_tokens_held == 0
            assert late.reservation.uncertain_cost_held_inr == Decimal("0.0000")
            assert late.adjustment is not None
            assert late.adjustment.adjustment_type == "LATE_SETTLEMENT"
            assert late.adjustment.token_delta == 1500

            cat = (
                await session.execute(
                    select(TenantDailyCategoryUsage).where(
                        TenantDailyCategoryUsage.institution_id == inst.id,
                        TenantDailyCategoryUsage.usage_category == "interactive_ai",
                    )
                )
            ).scalar_one()
            assert cat.committed_total_tokens == 3500
            assert cat.committed_cost_inr == Decimal("0.0590")
            assert cat.uncertain_reserved_tokens == 0
            assert cat.pending_reserved_tokens == 0
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_manual_settlement_then_late_variance_debit_and_credit_preserve_audit(self, db_connection):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            inst, user, _ = await _seed_tenant(session, prefix="var")
            engine = TenantQuotaEngine()
            t0 = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)

            async def _setup_unknown_attempt(key: str):
                adm = await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst.id,
                        user_id=user.id,
                        usage_category="interactive_ai",
                        endpoint="reports/parent",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=1000,
                        reserved_output_tokens=1000,
                        idempotency_key=key,
                    ),
                    as_of=t0,
                    db=session,
                )
                _, att = await engine.begin_provider_dispatch(
                    AttemptDispatchRequest(
                        institution_id=inst.id,
                        reservation_id=adm.reservation.id,
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_tokens=2000,
                    ),
                    as_of=t0,
                    db=session,
                )
                await engine.record_attempt_outcome(
                    institution_id=inst.id,
                    reservation_id=adm.reservation.id,
                    attempt_id=att.id,
                    status="TIMEOUT_UNCERTAIN",
                    as_of=t0,
                    db=session,
                )
                await engine.finalize_reservation(
                    institution_id=inst.id, reservation_id=adm.reservation.id, as_of=t0, db=session
                )
                return adm.reservation.id, att.id

            # Case 1: Manual settle 1000 tokens (₹0.0400 output rate), then late report HIGHER (1000 in + 1500 out = ₹0.0700) -> VARIANCE_DEBIT +1500, +0.0300
            r1_id, a1_id = await _setup_unknown_attempt("var-debit")
            man1 = await engine.manual_settle_unknown_usage(
                institution_id=inst.id,
                reservation_id=r1_id,
                settled_tokens=1000,
                actor="finops-op-1",
                reason="MANUAL_ESTIMATE",
                notes="Provider console unavailable",
                as_of=t0 + timedelta(minutes=5),
                db=session,
            )
            assert man1.reservation.status == "COMMITTED"
            assert man1.reservation.actual_cost_inr == Decimal("0.0400")
            assert man1.adjustment is not None and man1.adjustment.adjustment_type == "MANUAL_SETTLE"

            late1 = await engine.record_late_provider_usage(
                institution_id=inst.id,
                reservation_id=r1_id,
                attempt_id=a1_id,
                input_tokens=1000,
                output_tokens=1500,
                actor="reconciler",
                reason="LATE_USAGE_CSV",
                notes="Actual billing export exceeded manual estimate",
                as_of=t0 + timedelta(hours=2),
                db=session,
            )
            assert late1.reservation.review_status == "LATE_EVIDENCE_REVIEW_REQUIRED"
            assert late1.reservation.actual_total_tokens == 2500
            assert late1.reservation.actual_cost_inr == Decimal("0.0700")
            assert late1.adjustment is not None
            assert late1.adjustment.adjustment_type == "VARIANCE_DEBIT"
            assert late1.adjustment.token_delta == 1500
            assert late1.adjustment.cost_inr_delta == Decimal("0.0300")
            # Manual snapshot strictly preserved
            att1_after = late1.attempts[0]
            assert att1_after.manual_settled_tokens == 1000
            assert att1_after.manual_settled_cost_inr == Decimal("0.0400")
            assert att1_after.manual_settled_at is not None
            assert att1_after.late_reported_cost_inr == Decimal("0.0700")

            # Identical repeat late evidence is idempotent no-op
            late1_dup = await engine.record_late_provider_usage(
                institution_id=inst.id,
                reservation_id=r1_id,
                attempt_id=a1_id,
                input_tokens=1000,
                output_tokens=1500,
                actor="reconciler",
                reason="LATE_USAGE_CSV",
                notes="Retry webhook",
                as_of=t0 + timedelta(hours=2, minutes=1),
                db=session,
            )
            assert late1_dup.was_idempotent_noop is True

            # Case 2: Manual settle 1000 tokens (₹0.0400), then late report LOWER (500 in + 100 out = 600, ₹0.0090) -> VARIANCE_CREDIT -400, -0.0310
            r2_id, a2_id = await _setup_unknown_attempt("var-credit")
            await engine.manual_settle_unknown_usage(
                institution_id=inst.id,
                reservation_id=r2_id,
                settled_tokens=1000,
                actor="finops-op-1",
                reason="MANUAL_ESTIMATE",
                notes="Provisional hold",
                as_of=t0 + timedelta(minutes=6),
                db=session,
            )
            late2 = await engine.record_late_provider_usage(
                institution_id=inst.id,
                reservation_id=r2_id,
                attempt_id=a2_id,
                input_tokens=500,
                output_tokens=100,
                actor="reconciler",
                reason="LATE_USAGE_CSV",
                notes="Actual lower than estimate",
                as_of=t0 + timedelta(hours=3),
                db=session,
            )
            assert late2.adjustment is not None
            assert late2.adjustment.adjustment_type == "VARIANCE_CREDIT"
            assert late2.adjustment.token_delta == -400
            assert late2.adjustment.cost_inr_delta == Decimal("-0.0310")

            daily = (
                await session.execute(select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst.id))
            ).scalar_one()
            assert daily.committed_total_tokens == 2500 + 600
            assert daily.committed_cost_inr == Decimal("0.0700") + Decimal("0.0090")
            assert daily.uncertain_reserved_tokens == 0

            adj_rows = (
                await session.execute(
                    select(AIFinancialAdjustment).where(AIFinancialAdjustment.institution_id == inst.id)
                )
            ).scalars().all()
            assert len(adj_rows) == 4
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_mixed_attempts_success_and_zero_usage_settlement_conserves_committed_usage(
        self, db_connection
    ):
        """
        Close F-7.2-T01: Multi-attempt reservation with one SUCCEEDED attempt and one zero-usage
        attempt (settled with zero_charge_release=True or late confirmed failure) MUST NEVER
        release or zero out the successful attempt's committed tokens and INR cost.
        Rollup buckets (pending, committed, uncertain) must conserve exact balances across both
        the reservation and tenant daily/category tables.
        """
        session = _make_session(db_connection)
        try:
            pv_id = f"pv-{uuid.uuid4().hex[:6]}"
            await _seed_pricing(session, version_id=pv_id)
            inst, user, _ = await _seed_tenant(
                session,
                prefix="mixzero",
                daily_interactive_limit=50_000,
                monthly_total_limit=100_000,
                daily_exposure_limit_inr=Decimal("50.0000"),
            )
            engine = TenantQuotaEngine()
            t0 = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)

            # 1. Create logical reservation for 1500 tokens (1000 in @ 0.01/1k + 500 out @ 0.04/1k = 0.0300 INR)
            adm = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="agents/admin",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=500,
                    idempotency_key="mixed-zero-key-1",
                    pricing_version=pv_id,
                ),
                as_of=t0,
                db=session,
            )
            res_id = adm.reservation.id
            assert adm.reservation.total_reserved_tokens == 1500
            assert adm.reservation.reserved_cost_inr == Decimal("0.0300")

            daily_init = (
                await session.execute(
                    select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst.id)
                )
            ).scalar_one()
            assert daily_init.pending_reserved_tokens == 1500
            assert daily_init.pending_reserved_cost_inr == Decimal("0.0300")
            assert daily_init.committed_total_tokens == 0
            assert daily_init.committed_cost_inr == Decimal("0.0000")

            # 2. Attempt 1: Dispatched and SUCCEEDED with non-zero usage (800 in + 400 out = 1200 tokens, 0.0240 INR)
            _, att1 = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=res_id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=1500,
                    provider_request_id="mixed-att1-req",
                    pricing_version=pv_id,
                ),
                as_of=t0 + timedelta(seconds=1),
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=res_id,
                attempt_id=att1.id,
                status="SUCCEEDED",
                input_tokens=800,
                output_tokens=400,
                as_of=t0 + timedelta(seconds=2),
                db=session,
            )

            # 3. Attempt 2: Dispatched (retry/fallback) and produces zero-usage outcome (TIMEOUT_UNCERTAIN)
            _, att2 = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=res_id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=1000,
                    is_retry=True,
                    provider_request_id="mixed-att2-req",
                    pricing_version=pv_id,
                ),
                as_of=t0 + timedelta(seconds=10),
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=res_id,
                attempt_id=att2.id,
                status="TIMEOUT_UNCERTAIN",
                as_of=t0 + timedelta(seconds=20),
                db=session,
            )

            # 4. Finalize reservation: transitions to UNKNOWN_USAGE holding Attempt 2's uncertain tokens (1000)
            # while committing Attempt 1's confirmed tokens (1200) and cost (0.0240 INR)
            fin = await engine.finalize_reservation(
                institution_id=inst.id,
                reservation_id=res_id,
                as_of=t0 + timedelta(seconds=25),
                db=session,
            )
            assert fin.reservation.status == "UNKNOWN_USAGE"
            assert fin.reservation.actual_input_tokens == 800
            assert fin.reservation.actual_output_tokens == 400
            assert fin.reservation.actual_total_tokens == 1200
            assert fin.reservation.actual_cost_inr == Decimal("0.0240")
            assert fin.reservation.uncertain_tokens_held == 1000
            assert fin.reservation.review_status == "NEEDS_MANUAL_REVIEW"

            daily_mid = (
                await session.execute(
                    select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst.id)
                )
            ).scalar_one()
            assert daily_mid.pending_reserved_tokens == 0
            assert daily_mid.pending_reserved_cost_inr == Decimal("0.0000")
            assert daily_mid.committed_total_tokens == 1200
            assert daily_mid.committed_cost_inr == Decimal("0.0240")
            assert daily_mid.uncertain_reserved_tokens == 1000

            # 5. Operator manual settlement with settled_tokens=0 and zero_charge_release=True on Attempt 2
            # Verification: The zero-usage settlement on Attempt 2 MUST NOT release Attempt 1!
            # The reservation status must be COMMITTED (not RELEASED) because Attempt 1 succeeded!
            man = await engine.manual_settle_unknown_usage(
                institution_id=inst.id,
                reservation_id=res_id,
                attempt_id=att2.id,
                settled_tokens=0,
                settled_cost_inr=Decimal("0.0000"),
                zero_charge_release=True,
                actor="finops-auditor",
                reason="TIMEOUT_ATTEMPT_ZERO_CHARGE",
                notes="Attempt 2 network timeout; operator granted zero charge",
                as_of=t0 + timedelta(minutes=5),
                db=session,
            )
            assert man.reservation.status == "COMMITTED"
            assert man.reservation.actual_input_tokens == 800
            assert man.reservation.actual_output_tokens == 400
            assert man.reservation.actual_total_tokens == 1200
            assert man.reservation.actual_cost_inr == Decimal("0.0240")
            assert man.reservation.uncertain_tokens_held == 0
            assert man.reservation.uncertain_cost_held_inr == Decimal("0.0000")
            assert man.reservation.review_status == "MANUALLY_SETTLED"
            assert man.reservation.reconciled_at is not None

            # 6. Verify aggregate bucket conservation on both daily and category tables
            daily_fin = (
                await session.execute(
                    select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst.id)
                )
            ).scalar_one()
            cat_fin = (
                await session.execute(
                    select(TenantDailyCategoryUsage).where(
                        TenantDailyCategoryUsage.institution_id == inst.id,
                        TenantDailyCategoryUsage.usage_category == "interactive_ai",
                    )
                )
            ).scalar_one()
            assert daily_fin.pending_reserved_tokens == 0
            assert daily_fin.pending_reserved_cost_inr == Decimal("0.0000")
            assert daily_fin.committed_total_tokens == 1200
            assert daily_fin.committed_cost_inr == Decimal("0.0240")
            assert daily_fin.uncertain_reserved_tokens == 0
            assert daily_fin.uncertain_exposure_cost_inr == Decimal("0.0000")

            assert cat_fin.pending_reserved_tokens == 0
            assert cat_fin.committed_total_tokens == 1200
            assert cat_fin.committed_cost_inr == Decimal("0.0240")
            assert cat_fin.uncertain_reserved_tokens == 0

            # 7. Late provider report arrives for Attempt 2 confirming 0 tokens (failed_confirmed=True)
            late = await engine.record_late_provider_usage(
                institution_id=inst.id,
                reservation_id=res_id,
                attempt_id=att2.id,
                input_tokens=0,
                output_tokens=0,
                failed_confirmed=True,
                actor="late-provider-audit",
                reason="LATE_CONFIRMED_ZERO",
                notes="Provider logs confirm 0 tokens consumed on attempt 2",
                as_of=t0 + timedelta(hours=1),
                db=session,
            )
            assert late.reservation.status == "COMMITTED"
            assert late.reservation.actual_total_tokens == 1200
            assert late.reservation.actual_cost_inr == Decimal("0.0240")
            assert late.adjustment is not None
            assert late.adjustment.token_delta == 0
            assert late.adjustment.cost_inr_delta == Decimal("0.0000")

            # 8. Idempotent replays
            dup_late = await engine.record_late_provider_usage(
                institution_id=inst.id,
                reservation_id=res_id,
                attempt_id=att2.id,
                input_tokens=0,
                output_tokens=0,
                failed_confirmed=True,
                actor="late-provider-audit",
                reason="LATE_CONFIRMED_ZERO",
                notes="Duplicate replay",
                as_of=t0 + timedelta(hours=1, minutes=1),
                db=session,
            )
            assert dup_late.was_idempotent_noop is True

            dup_fin = await engine.finalize_reservation(
                institution_id=inst.id,
                reservation_id=res_id,
                as_of=t0 + timedelta(hours=1, minutes=2),
                db=session,
            )
            assert dup_fin.was_idempotent_noop is True
            assert dup_fin.reservation.status == "COMMITTED"
            assert dup_fin.reservation.actual_total_tokens == 1200

            # 9. Contrast verification: A reservation where ALL attempts are zero-usage DOES release to RELEASED
            adm_all_zero = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="agents/admin",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=500,
                    reserved_output_tokens=500,
                    idempotency_key="all-zero-contrast",
                    pricing_version=pv_id,
                ),
                as_of=t0,
                db=session,
            )
            _, att_az = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=adm_all_zero.reservation.id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=1000,
                    provider_request_id="az-att-req",
                    pricing_version=pv_id,
                ),
                as_of=t0 + timedelta(seconds=1),
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=adm_all_zero.reservation.id,
                attempt_id=att_az.id,
                status="TIMEOUT_UNCERTAIN",
                as_of=t0 + timedelta(seconds=2),
                db=session,
            )
            await engine.finalize_reservation(
                institution_id=inst.id,
                reservation_id=adm_all_zero.reservation.id,
                as_of=t0 + timedelta(seconds=3),
                db=session,
            )
            man_az = await engine.manual_settle_unknown_usage(
                institution_id=inst.id,
                reservation_id=adm_all_zero.reservation.id,
                attempt_id=att_az.id,
                settled_tokens=0,
                settled_cost_inr=Decimal("0.0000"),
                zero_charge_release=True,
                actor="finops-auditor",
                reason="ALL_ATTEMPTS_FAILED",
                notes="Pure zero failure release",
                as_of=t0 + timedelta(minutes=10),
                db=session,
            )
            # When ALL attempts are zero-usage and no attempt succeeded, it transitions to RELEASED
            assert man_az.reservation.status == "RELEASED"
            assert man_az.reservation.actual_total_tokens == 0
            assert man_az.reservation.actual_cost_inr == Decimal("0.0000")
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_invalid_state_transitions_and_provider_request_id_conflicts(self, db_connection):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            inst, user, _ = await _seed_tenant(session, prefix="inv")
            engine = TenantQuotaEngine()

            # 1. RESERVED cannot finalize directly to COMMITTED or manually settle
            adm1 = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=200,
                    reserved_output_tokens=200,
                    idempotency_key="inv-1",
                ),
                db=session,
            )
            with pytest.raises(InvalidStateTransitionError):
                await engine.finalize_reservation(
                    institution_id=inst.id, reservation_id=adm1.reservation.id, db=session
                )
            with pytest.raises(InvalidStateTransitionError):
                await engine.manual_settle_unknown_usage(
                    institution_id=inst.id,
                    reservation_id=adm1.reservation.id,
                    settled_tokens=100,
                    actor="admin",
                    reason="TEST",
                    notes="Invalid state check",
                    db=session,
                )

            # Released reservation cannot dispatch
            await engine.release_pre_dispatch(
                institution_id=inst.id, reservation_id=adm1.reservation.id, db=session
            )
            with pytest.raises(InvalidStateTransitionError):
                await engine.begin_provider_dispatch(
                    AttemptDispatchRequest(
                        institution_id=inst.id,
                        reservation_id=adm1.reservation.id,
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_tokens=400,
                    ),
                    db=session,
                )

            # 2. Committed reservation cannot dispatch or pre-dispatch release; provider_request_id cannot span reservations
            adm2 = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=200,
                    reserved_output_tokens=200,
                    idempotency_key="inv-2",
                ),
                db=session,
            )
            _, att2 = await engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=adm2.reservation.id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=400,
                    provider_request_id="unique-prov-req-1",
                ),
                db=session,
            )
            await engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=adm2.reservation.id,
                attempt_id=att2.id,
                status="SUCCEEDED",
                input_tokens=100,
                output_tokens=100,
                db=session,
            )
            await engine.finalize_reservation(
                institution_id=inst.id, reservation_id=adm2.reservation.id, db=session
            )
            with pytest.raises(InvalidStateTransitionError):
                await engine.release_pre_dispatch(
                    institution_id=inst.id, reservation_id=adm2.reservation.id, db=session
                )

            adm3 = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=200,
                    reserved_output_tokens=200,
                    idempotency_key="inv-3",
                ),
                db=session,
            )
            with pytest.raises(IdempotencyConflictError):
                await engine.begin_provider_dispatch(
                    AttemptDispatchRequest(
                        institution_id=inst.id,
                        reservation_id=adm3.reservation.id,
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_tokens=400,
                        provider_request_id="unique-prov-req-1",
                    ),
                    db=session,
                )
        finally:
            await session.close()


class TestStage72PolicyIsolationSecurityAndLogging:
    """Verify Business Decision #4 fail-closed interface, RLS isolation, and non-sensitive logs."""

    @pytest.mark.asyncio
    async def test_missing_usage_fails_closed_by_default_and_honors_injected_resolver(self, db_connection):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            inst, user, _ = await _seed_tenant(session, prefix="pol", missing_usage_policy="HOLD_UNKNOWN")

            default_engine = TenantQuotaEngine()
            assert isinstance(default_engine.policy_resolver, FailClosedMissingUsagePolicyResolver)

            adm = await default_engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst.id,
                    user_id=user.id,
                    usage_category="interactive_ai",
                    endpoint="agents/admin",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=1000,
                    reserved_output_tokens=500,
                ),
                db=session,
            )
            _, att = await default_engine.begin_provider_dispatch(
                AttemptDispatchRequest(
                    institution_id=inst.id,
                    reservation_id=adm.reservation.id,
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_tokens=1500,
                ),
                db=session,
            )

            # Default resolver refuses to fabricate unapproved Business Decision #4 behavior
            with pytest.raises(MissingUsagePolicyPendingError):
                await default_engine.record_attempt_outcome(
                    institution_id=inst.id,
                    reservation_id=adm.reservation.id,
                    attempt_id=att.id,
                    status="SUCCEEDED",
                    input_tokens=None,
                    output_tokens=None,
                    db=session,
                )

            # Injecting explicit approved resolver succeeds without touching core engine
            class _HoldUnknownResolver:
                def resolve_missing_usage(self, context: MissingUsageContext) -> MissingUsageResolution:
                    assert context.policy_name == "HOLD_UNKNOWN"
                    return MissingUsageResolution(action="UNKNOWN_USAGE", reason="APPROVED_HOLD")

            policy_engine = TenantQuotaEngine(policy_resolver=_HoldUnknownResolver())
            _, att_after = await policy_engine.record_attempt_outcome(
                institution_id=inst.id,
                reservation_id=adm.reservation.id,
                attempt_id=att.id,
                status="SUCCEEDED",
                input_tokens=None,
                output_tokens=None,
                db=session,
            )
            assert att_after.status == "TIMEOUT_UNCERTAIN"
            fin = await policy_engine.finalize_reservation(
                institution_id=inst.id, reservation_id=adm.reservation.id, db=session
            )
            assert fin.reservation.status == "UNKNOWN_USAGE"
            assert fin.reservation.uncertain_tokens_held == 1500
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation_and_non_sensitive_structured_logs(self, db_connection, caplog):
        session = _make_session(db_connection)
        try:
            await _seed_pricing(session, version_id=f"pv-{uuid.uuid4().hex[:6]}")
            inst_a, user_a, _ = await _seed_tenant(session, prefix="iso-a")
            inst_b, _, _ = await _seed_tenant(session, prefix="iso-b")
            engine = TenantQuotaEngine()

            with caplog.at_level(logging.INFO, logger="app.observability.quota"):
                adm_a = await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst_a.id,
                        user_id=user_a.id,
                        usage_category="interactive_ai",
                        endpoint="agents/admin",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=400,
                        reserved_output_tokens=400,
                        idempotency_key="iso-key-1",
                    ),
                    db=session,
                )

            # Tenant B cannot inspect, recover, dispatch, or release Tenant A's reservation
            assert (
                await engine.recover_reservation_by_idempotency_key(
                    institution_id=inst_b.id, idempotency_key="iso-key-1", db=session
                )
                is None
            )
            with pytest.raises(ReservationNotFoundError):
                await engine.release_pre_dispatch(
                    institution_id=inst_b.id, reservation_id=adm_a.reservation.id, db=session
                )
            with pytest.raises(ReservationNotFoundError):
                await engine.begin_provider_dispatch(
                    AttemptDispatchRequest(
                        institution_id=inst_b.id,
                        reservation_id=adm_a.reservation.id,
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_tokens=800,
                    ),
                    db=session,
                )

            # Verify structured logs contain zero PII/prompt-like leakage
            log_text = " ".join(
                f"{rec.getMessage()} {getattr(rec, '__dict__', {})}" for rec in caplog.records
            )
            assert "quota_admission_reserved" in log_text
            assert user_a.email not in log_text
            assert "prompt" not in log_text.lower()
        finally:
            await session.close()

"""
Stage 7.2 Real PostgreSQL Concurrency, Contention Retry & Failure-Injection Tests.

Uses independent database connections (NullPool AsyncEngine) executing as runtime role
`eduintel_app` with real PostgreSQL row locks, transactions, and savepoints.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.security import hash_password
from app.institutions.models import Institution
from app.observability.quota import (
    AttemptDispatchRequest,
    DatabaseContentionError,
    IdempotencyConflictError,
    QuotaExceededError,
    ReservationCreateRequest,
    RetryPolicy,
    TenantQuotaEngine,
    execute_with_retry,
)
from app.observability.quota_models import (
    AIPricingActivation,
    AIPricingVersion,
    AITokenReservation,
    TenantAIQuota,
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
)
from app.users.models import User


@pytest_asyncio.fixture
async def conc_session_factory():
    """Provide an independent NullPool async_sessionmaker for true parallel connections."""
    db_url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(db_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _bind_admin(session: AsyncSession, inst_id: uuid.UUID | None = None) -> None:
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :inst, true);"),
        {"inst": str(inst_id) if inst_id else ""},
    )
    await session.execute(text("SELECT set_config('app.is_platform_admin', 'true', true);"))


async def _bind_tenant(session: AsyncSession, inst_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :inst, true);"),
        {"inst": str(inst_id)},
    )
    await session.execute(text("SELECT set_config('app.is_platform_admin', 'false', true);"))


async def _provision_committed_fixture(
    factory: async_sessionmaker[AsyncSession],
    *,
    prefix: str,
    daily_interactive_limit: int = 10_000,
    monthly_total_limit: int | None = 50_000,
    daily_exposure_limit_inr: Decimal = Decimal("50.0000"),
    pending_reserve_cap_percent: Decimal = Decimal("1.0000"),
    max_tokens_per_request: int = 5_000,
    quota_timezone: str = "Asia/Kolkata",
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Commit isolated tenant, user, quota, and r01-conc-prefixed pricing activation."""
    inst_id = uuid.uuid4()
    user_id = uuid.uuid4()
    version_id = f"r01-conc-s72-{prefix}-{uuid.uuid4().hex[:8]}"

    async with factory() as session:
        async with session.begin():
            await _bind_admin(session, inst_id)
            session.add(
                Institution(
                    id=inst_id,
                    name=f"Conc Inst {prefix}",
                    slug=f"conc-{prefix}-{inst_id.hex[:8]}",
                    is_active=True,
                )
            )
            session.add(
                User(
                    id=user_id,
                    email=f"conc-{user_id.hex[:8]}@{prefix}.edu",
                    name=f"Conc User {prefix}",
                    hashed_password=hash_password("ConcPassword123!"),
                    role="admin",
                    is_active=True,
                )
            )
            session.add(
                AIPricingVersion(
                    version_id=version_id,
                    currency="INR",
                    usd_to_inr_rate=Decimal("85.0000"),
                    rate_source="CONC_TEST",
                    rates_json={
                        "gemini": {
                            "gemini-3.6-flash": {"input_1k": "0.0100", "output_1k": "0.0400"}
                        }
                    },
                    effective_from=datetime.now(UTC) - timedelta(hours=1),
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                AIPricingActivation(
                    id=uuid.uuid4(),
                    pricing_version=version_id,
                    expected_version_active=True,
                    activated_by_actor="conc-admin",
                    activation_reason="CONC_TEST_SETUP",
                )
            )
            session.add(
                TenantAIQuota(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    quota_timezone=quota_timezone,
                    daily_interactive_token_limit=daily_interactive_limit,
                    daily_ingestion_token_limit=50_000,
                    daily_other_token_limit=50_000,
                    monthly_total_token_limit=monthly_total_limit,
                    daily_exposure_limit_inr=daily_exposure_limit_inr,
                    pending_reserve_cap_percent=pending_reserve_cap_percent,
                    max_tokens_per_request=max_tokens_per_request,
                    missing_usage_policy="HOLD_UNKNOWN",
                    is_unlimited=False,
                    is_suspended=False,
                    tier_name="conc-tier",
                )
            )
    return inst_id, user_id, version_id


class TestStage72ParallelAdmissionsAndCaps:
    """Real multi-connection concurrency proofs (2, 10, 25 parallel workers)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("worker_count", "daily_limit", "expected_successes"),
        [
            (2, 1_000, 1),
            (10, 4_000, 4),
            (25, 10_000, 10),
        ],
    )
    async def test_parallel_admission_bursts_never_overshoot_daily_quota(
        self,
        conc_session_factory,
        worker_count: int,
        daily_limit: int,
        expected_successes: int,
    ):
        inst_id, user_id, pv_id = await _provision_committed_fixture(
            conc_session_factory,
            prefix=f"burst-{worker_count}",
            daily_interactive_limit=daily_limit,
            monthly_total_limit=None,
            daily_exposure_limit_inr=Decimal("100.0000"),
            pending_reserve_cap_percent=Decimal("1.0000"),
            max_tokens_per_request=2_000,
        )
        engine = TenantQuotaEngine(conc_session_factory)
        barrier = asyncio.Barrier(worker_count)

        async def _worker(idx: int) -> str:
            await barrier.wait()
            try:
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst_id,
                        user_id=user_id,
                        usage_category="interactive_ai",
                        endpoint="agents/admin",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=500,
                        reserved_output_tokens=500,
                        idempotency_key=f"burst-{worker_count}-{idx}",
                        pricing_version=pv_id,
                    )
                )
                return "ADMITTED"
            except QuotaExceededError as exc:
                assert exc.limit_type == "DAILY_CATEGORY_LIMIT"
                return "REJECTED"

        outcomes = await asyncio.gather(*(_worker(i) for i in range(worker_count)))
        assert outcomes.count("ADMITTED") == expected_successes
        assert outcomes.count("REJECTED") == worker_count - expected_successes

        async with conc_session_factory() as verify_db:
            async with verify_db.begin():
                await _bind_tenant(verify_db, inst_id)
                daily = (
                    await verify_db.execute(
                        select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst_id)
                    )
                ).scalar_one()
                cat = (
                    await verify_db.execute(
                        select(TenantDailyCategoryUsage).where(
                            TenantDailyCategoryUsage.institution_id == inst_id
                        )
                    )
                ).scalar_one()
                reservations = (
                    await verify_db.execute(
                        select(AITokenReservation).where(AITokenReservation.institution_id == inst_id)
                    )
                ).scalars().all()
                assert len(reservations) == expected_successes
                assert daily.pending_reserved_tokens == expected_successes * 1000
                assert cat.pending_reserved_tokens == expected_successes * 1000
                assert daily.request_count == expected_successes

    @pytest.mark.asyncio
    async def test_parallel_exposure_and_monthly_limit_under_10_workers(self, conc_session_factory):
        # 500 in + 500 out = 0.005 + 0.020 = 0.0250 INR per call -> ceiling 0.0800 admits max 3 calls (0.0750)
        inst_id, user_id, pv_id = await _provision_committed_fixture(
            conc_session_factory,
            prefix="exp10",
            daily_interactive_limit=50_000,
            monthly_total_limit=50_000,
            daily_exposure_limit_inr=Decimal("0.0800"),
            pending_reserve_cap_percent=Decimal("1.0000"),
        )
        engine = TenantQuotaEngine(conc_session_factory)
        barrier = asyncio.Barrier(10)

        async def _worker(idx: int) -> str:
            await barrier.wait()
            try:
                await engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=inst_id,
                        user_id=user_id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=500,
                        reserved_output_tokens=500,
                        idempotency_key=f"exp10-{idx}",
                        pricing_version=pv_id,
                    )
                )
                return "ADMITTED"
            except QuotaExceededError as exc:
                assert exc.limit_type == "DAILY_FINANCIAL_EXPOSURE_LIMIT"
                return "REJECTED"

        outcomes = await asyncio.gather(*(_worker(i) for i in range(10)))
        assert outcomes.count("ADMITTED") == 3
        assert outcomes.count("REJECTED") == 7

        # Cross-day parallel monthly ceiling test (5 days in same month, monthly_total_limit=3000)
        m_inst_id, m_user_id, m_pv_id = await _provision_committed_fixture(
            conc_session_factory,
            prefix="mon10",
            daily_interactive_limit=50_000,
            monthly_total_limit=3_000,
            daily_exposure_limit_inr=Decimal("100.0000"),
            pending_reserve_cap_percent=Decimal("1.0000"),
        )
        m_engine = TenantQuotaEngine(conc_session_factory)
        m_barrier = asyncio.Barrier(10)

        async def _month_worker(idx: int) -> str:
            await m_barrier.wait()
            day = 10 + (idx % 3)  # Spread concurrently across 3 different calendar days in Nov 2026
            as_of = datetime(2026, 11, day, 12, 0, tzinfo=UTC)
            try:
                await m_engine.admit_and_reserve(
                    ReservationCreateRequest(
                        institution_id=m_inst_id,
                        user_id=m_user_id,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_input_tokens=500,
                        reserved_output_tokens=500,
                        idempotency_key=f"mon10-{idx}",
                        pricing_version=m_pv_id,
                    ),
                    as_of=as_of,
                )
                return "ADMITTED"
            except QuotaExceededError as exc:
                assert exc.limit_type == "MONTHLY_TOTAL_LIMIT"
                return "REJECTED"

        m_outcomes = await asyncio.gather(*(_month_worker(i) for i in range(10)))
        assert m_outcomes.count("ADMITTED") == 3
        assert m_outcomes.count("REJECTED") == 7

    @pytest.mark.asyncio
    async def test_interleaved_reserve_dispatch_finalize_and_release_conserves_totals(
        self, conc_session_factory
    ):
        inst_id, user_id, pv_id = await _provision_committed_fixture(
            conc_session_factory,
            prefix="mix12",
            daily_interactive_limit=100_000,
            monthly_total_limit=None,
            daily_exposure_limit_inr=Decimal("100.0000"),
            pending_reserve_cap_percent=Decimal("1.0000"),
        )
        engine = TenantQuotaEngine(conc_session_factory)
        barrier = asyncio.Barrier(12)

        async def _lifecycle_worker(idx: int) -> None:
            await barrier.wait()
            adm = await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst_id,
                    user_id=user_id,
                    usage_category="interactive_ai",
                    endpoint="agents/admin",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=600,
                    reserved_output_tokens=400,
                    idempotency_key=f"mix-{idx}",
                    pricing_version=pv_id,
                )
            )
            if idx % 3 == 0:
                await engine.release_pre_dispatch(
                    institution_id=inst_id,
                    reservation_id=adm.reservation.id,
                    reason="CLIENT_ABORTED",
                )
            else:
                _, att = await engine.begin_provider_dispatch(
                    AttemptDispatchRequest(
                        institution_id=inst_id,
                        reservation_id=adm.reservation.id,
                        provider="gemini",
                        model="gemini-3.6-flash",
                        estimated_tokens=1000,
                    )
                )
                await engine.record_attempt_outcome(
                    institution_id=inst_id,
                    reservation_id=adm.reservation.id,
                    attempt_id=att.id,
                    status="SUCCEEDED",
                    input_tokens=400,
                    output_tokens=200,
                )
                await engine.finalize_reservation(
                    institution_id=inst_id, reservation_id=adm.reservation.id
                )

        await asyncio.gather(*(_lifecycle_worker(i) for i in range(12)))

        async with conc_session_factory() as verify_db:
            async with verify_db.begin():
                await _bind_tenant(verify_db, inst_id)
                daily = (
                    await verify_db.execute(
                        select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst_id)
                    )
                ).scalar_one()
                cat = (
                    await verify_db.execute(
                        select(TenantDailyCategoryUsage).where(
                            TenantDailyCategoryUsage.institution_id == inst_id
                        )
                    )
                ).scalar_one()
                # 4 released (0 committed), 8 committed (600 tokens each -> 4800)
                # Each 400 in @ 0.01/1k + 200 out @ 0.04/1k = 0.004 + 0.008 = 0.0120 INR * 8 = 0.0960 INR
                assert daily.pending_reserved_tokens == 0
                assert daily.pending_reserved_cost_inr == Decimal("0.0000")
                assert daily.committed_total_tokens == 8 * 600
                assert daily.committed_cost_inr == Decimal("0.0960")
                assert cat.pending_reserved_tokens == 0
                assert cat.committed_total_tokens == 8 * 600
                assert cat.committed_cost_inr == Decimal("0.0960")


class TestStage72IdempotencyCrashRecoveryAndRetry:
    """Idempotency conflict detection, uncertain commit recovery, and transient SQLSTATE retry."""

    @pytest.mark.asyncio
    async def test_concurrent_idempotency_race_and_payload_conflict(self, conc_session_factory):
        inst_id, user_id, pv_id = await _provision_committed_fixture(
            conc_session_factory, prefix="idem10"
        )
        engine = TenantQuotaEngine(conc_session_factory)
        barrier = asyncio.Barrier(10)

        shared_req = ReservationCreateRequest(
            institution_id=inst_id,
            user_id=user_id,
            usage_category="interactive_ai",
            endpoint="agents/admin",
            provider="gemini",
            model="gemini-3.6-flash",
            estimated_input_tokens=500,
            reserved_output_tokens=500,
            idempotency_key="shared-idem-key",
            pricing_version=pv_id,
        )

        async def _worker():
            await barrier.wait()
            return await engine.admit_and_reserve(shared_req)

        results = await asyncio.gather(*(_worker() for _ in range(10)))
        ids = {r.reservation.id for r in results}
        assert len(ids) == 1
        assert sum(1 for r in results if not r.is_idempotent_replay) == 1
        assert sum(1 for r in results if r.is_idempotent_replay) == 9

        # Conflicting reuse fails explicitly without mutating ledger
        with pytest.raises(IdempotencyConflictError):
            await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst_id,
                    user_id=user_id,
                    usage_category="interactive_ai",
                    endpoint="agents/admin",
                    provider="gemini",
                    model="gemini-3.6-flash",
                    estimated_input_tokens=501,  # Diverges!
                    reserved_output_tokens=500,
                    idempotency_key="shared-idem-key",
                    pricing_version=pv_id,
                )
            )

    @pytest.mark.asyncio
    async def test_uncertain_commit_and_pre_commit_crash_recovery(self, conc_session_factory):
        inst_id, user_id, pv_id = await _provision_committed_fixture(
            conc_session_factory, prefix="crash"
        )

        # Simulate socket drop AFTER PostgreSQL COMMIT completes via SQLAlchemy after_commit hook
        class _PostCommitDropFactory:
            def __init__(self, inner):
                self._inner = inner

            def __call__(self):
                session = self._inner()

                def _raise_after_commit(_sync_session):
                    raise ConnectionResetError("Simulated socket drop after DB COMMIT")

                event.listen(session.sync_session, "after_commit", _raise_after_commit)
                return session

        faulty_engine = TenantQuotaEngine(_PostCommitDropFactory(conc_session_factory))  # type: ignore[arg-type]
        req = ReservationCreateRequest(
            institution_id=inst_id,
            user_id=user_id,
            usage_category="interactive_ai",
            endpoint="rag/query",
            provider="gemini",
            model="gemini-3.6-flash",
            estimated_input_tokens=400,
            reserved_output_tokens=600,
            idempotency_key="uncertain-commit-1",
            pricing_version=pv_id,
        )

        with pytest.raises(ConnectionResetError):
            await faulty_engine.admit_and_reserve(req)

        # Clean engine recovers committed reservation without creating a second debit
        clean_engine = TenantQuotaEngine(conc_session_factory)
        recovered = await clean_engine.recover_reservation_by_idempotency_key(
            institution_id=inst_id,
            idempotency_key="uncertain-commit-1",
            expected_request=req,
        )
        assert recovered is not None
        assert recovered.total_reserved_tokens == 1000

        replayed = await clean_engine.admit_and_reserve(req)
        assert replayed.is_idempotent_replay is True
        assert replayed.reservation.id == recovered.id

        # Non-existent key after pre-commit abort recovers as None
        assert (
            await clean_engine.recover_reservation_by_idempotency_key(
                institution_id=inst_id,
                idempotency_key="never-committed-key",
            )
            is None
        )

        async with conc_session_factory() as verify_db:
            async with verify_db.begin():
                await _bind_tenant(verify_db, inst_id)
                daily = (
                    await verify_db.execute(
                        select(TenantDailyAIUsage).where(TenantDailyAIUsage.institution_id == inst_id)
                    )
                ).scalar_one()
                assert daily.pending_reserved_tokens == 1000
                assert daily.request_count == 1

    @pytest.mark.asyncio
    async def test_live_lock_timeout_retry_and_transient_sqlstate_handling(self, conc_session_factory):
        inst_id, user_id, pv_id = await _provision_committed_fixture(
            conc_session_factory, prefix="retry"
        )
        fast_retry = RetryPolicy(max_attempts=3, delays_ms=(25, 50, 75), jitter_ratio=0.0, lock_timeout_ms=120)
        engine = TenantQuotaEngine(conc_session_factory, retry_policy=fast_retry)

        # 1. Real PostgreSQL 55P03 lock_not_available contention that succeeds after blocker commits
        holder_locked = asyncio.Event()

        async def _blocking_locker():
            async with conc_session_factory() as lock_db:
                async with lock_db.begin():
                    await _bind_tenant(lock_db, inst_id)
                    await lock_db.execute(
                        select(TenantAIQuota).where(TenantAIQuota.institution_id == inst_id).with_for_update()
                    )
                    holder_locked.set()
                    await asyncio.sleep(0.18)  # Outlasts 1st lock_timeout=120ms, commits before 2nd attempt finishes!

        blocker_task = asyncio.create_task(_blocking_locker())
        await holder_locked.wait()

        admission = await engine.admit_and_reserve(
            ReservationCreateRequest(
                institution_id=inst_id,
                user_id=user_id,
                usage_category="interactive_ai",
                endpoint="agents/admin",
                provider="gemini",
                model="gemini-3.6-flash",
                estimated_input_tokens=300,
                reserved_output_tokens=200,
                idempotency_key="retry-55p03-success",
                pricing_version=pv_id,
            )
        )
        await blocker_task
        assert admission.reservation.status == "RESERVED"

        # 2. Retryable SQLSTATEs (40P01, 40001) retry up to max_attempts then raise DatabaseContentionError
        class _FakePgError(Exception):
            def __init__(self, sqlstate: str):
                self.sqlstate = sqlstate

        for transient_state in ("40P01", "40001"):
            attempts_seen = 0

            async def _always_transient(_db: AsyncSession, _state: str = transient_state):
                nonlocal attempts_seen
                attempts_seen += 1
                raise DBAPIError("SELECT 1", {}, _FakePgError(_state))

            with pytest.raises(DatabaseContentionError) as exc_dl:
                await execute_with_retry(
                    session_factory=conc_session_factory,
                    institution_id=inst_id,
                    fn=_always_transient,
                    operation_name=f"test_{transient_state}",
                    policy=fast_retry,
                )
            assert attempts_seen == 3
            assert exc_dl.value.sqlstate == transient_state

        # Non-transient SQLSTATE (e.g., 23505 unique_violation) MUST NOT retry
        non_retry_attempts = 0

        async def _non_transient(db: AsyncSession):
            nonlocal non_retry_attempts
            non_retry_attempts += 1
            raise DBAPIError("INSERT", {}, _FakePgError("23505"))

        with pytest.raises(DBAPIError):
            await execute_with_retry(
                session_factory=conc_session_factory,
                institution_id=inst_id,
                fn=_non_transient,
                operation_name="test_unique",
                policy=fast_retry,
            )
        assert non_retry_attempts == 1


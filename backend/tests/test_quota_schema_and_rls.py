"""
backend/tests/test_quota_schema_and_rls.py

Stage 7.1 & 7.1R Database Schema, Role Separation, Security & Concurrency Tests:
1. SQLAlchemy Metadata, Model Registration, Precision & Unapproved Defaults Check:
   - Verifies all 8 Stage 7.1/7.1R tables exist on Base.metadata and live PostgreSQL.
   - Verifies NUMERIC fixed-point precision for INR columns and BIGINT for token fields.
   - Verifies zero unapproved default pricing or limit rows seeded by migration.
   - Verifies linear Alembic single-head chain ending at b2c3d4e5f6a7 (Stage 7.1R2).
2. Relational Integrity & Static Invariants (F-02, F-03, F-04):
   - Reservation status CHECK constraints (rejects 'EXPIRED').
   - Dispatched & reconciled timestamp invariants (including RELEASED from RESERVED vs UNKNOWN_USAGE).
   - Token summation arithmetic & BIGINT overflow protection.
   - Attempt sequence uniqueness, provider_request_id deduplication, and empty-string rejections.
   - Composite FK (institution_id, reservation_id, attempt_id) rejecting cross-reservation mismatches.
   - Separate append-only AIPricingActivation ledger preventing UPDATEs on immutable AIPricingVersion.
3. PostgreSQL Role Separation, RLS, Least-Privilege ACLs & Adversarial Bypass Proofs (F-01, F-02, F-04, F-05):
   - Verifies runtime role `eduintel_app` is unprivileged and has zero inherited/SET ROLE
     memberships in privileged or schema/table/function-owning roles.
   - Proves `SET ROLE`, `DISABLE TRIGGER`, `CREATE OR REPLACE FUNCTION`, `ALTER POLICY`,
     `UPDATE`/`DELETE`/`TRUNCATE` on immutable tables all fail closed under `eduintel_app`.
   - Verifies pricing FK insertion works without `UPDATE` ACL on `ai_pricing_versions`.
   - Verifies cross-tenant read/write/delete isolation and platform-admin read-only separation.
   - Executes single-connection tests inside rollback-isolated `db_connection` savepoints.
4. Real-PostgreSQL Concurrency Foundations (Independent Connections):
   - Concurrent daily rollup initialization (INSERT ... ON CONFLICT DO NOTHING) across 6 sessions.
   - Concurrent duplicate idempotency_key & attempt_sequence contention.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import BigInteger, Numeric, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentSession, AgentSessionMessage, ToolExecutionRecord
from app.auth.security import hash_password
from app.core.database import Base
from app.institutions.models import Institution
from app.observability.quota_models import (
    VALID_RESERVATION_STATUSES,
    AIFinancialAdjustment,
    AIPricingActivation,
    AIPricingVersion,
    AIProviderAttempt,
    AITokenReservation,
    TenantAIQuota,
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
)
from app.users.models import User


async def _set_context(
    session: AsyncSession,
    inst_id: uuid.UUID | None,
    is_platform_admin: bool = False,
) -> None:
    inst_str = str(inst_id) if inst_id else ""
    admin_str = "true" if is_platform_admin else "false"
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :inst, true);"),
        {"inst": inst_str},
    )
    await session.execute(
        text("SELECT set_config('app.is_platform_admin', :adm, true);"),
        {"adm": admin_str},
    )


async def _provision_inst_and_user(
    session: AsyncSession,
    inst_id: uuid.UUID,
    user_id: uuid.UUID,
    slug_prefix: str,
) -> tuple[Institution, User]:
    inst = Institution(
        id=inst_id,
        name=f"Quota Inst {slug_prefix}",
        slug=f"{slug_prefix}-{inst_id.hex[:8]}",
        is_active=True,
    )
    user = User(
        id=user_id,
        email=f"quota-{user_id.hex[:8]}@{slug_prefix}.edu",
        name=f"Quota User {slug_prefix}",
        hashed_password=hash_password("TestPassword123!"),
        role="teacher",
        is_active=True,
    )
    session.add_all([inst, user])
    await session.flush()
    return inst, user


async def _create_pricing_version(
    session: AsyncSession,
    version_id: str,
    *,
    is_active: bool = True,
) -> AIPricingVersion:
    pv = AIPricingVersion(
        version_id=version_id,
        currency="INR",
        usd_to_inr_rate=Decimal("85.5000"),
        rate_source="TEST_FIXTURE_RATE",
        rates_json={"gemini": {"gemini-1.5-flash": {"input_1k": "0.0050", "output_1k": "0.0200"}}},
        effective_from=datetime.now(UTC) - timedelta(days=1),
        is_active=is_active,
    )
    session.add(pv)
    await session.flush()
    return pv


async def _setup_rollup_chain(
    session: AsyncSession,
    inst_id: uuid.UUID,
    usage_date: date,
    category: str = "interactive_ai",
) -> tuple[TenantDailyAIUsage, TenantDailyCategoryUsage]:
    daily = TenantDailyAIUsage(institution_id=inst_id, usage_date=usage_date)
    session.add(daily)
    await session.flush()

    cat = TenantDailyCategoryUsage(
        institution_id=inst_id,
        usage_date=usage_date,
        usage_category=category,
    )
    session.add(cat)
    await session.flush()
    return daily, cat


def _make_session(db_connection) -> AsyncSession:
    return AsyncSession(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


# ==============================================================================
# Suite 1: Schema Registration, Alembic Chain & Financial/Token Precision
# ==============================================================================


class TestStage71SchemaRegistrationAndPrecision:
    """Validates SQLAlchemy model registration, column types, and migration chain."""

    def test_all_eight_finops_tables_registered_on_base_metadata(self):
        expected_tables = {
            "ai_pricing_versions",
            "ai_pricing_activations",
            "tenant_ai_quotas",
            "tenant_daily_ai_usage",
            "tenant_daily_category_usage",
            "ai_token_reservations",
            "ai_provider_attempts",
            "ai_financial_adjustments",
        }
        registered = set(Base.metadata.tables.keys())
        missing = expected_tables - registered
        assert not missing, f"Missing expected Stage 7.1/7.1R tables in Base.metadata: {missing}"

    def test_reserved_statuses_exclude_expired_state(self):
        assert set(VALID_RESERVATION_STATUSES) == {
            "RESERVED",
            "DISPATCHED",
            "COMMITTED",
            "RELEASED",
            "UNKNOWN_USAGE",
        }
        assert "EXPIRED" not in VALID_RESERVATION_STATUSES

    def test_financial_columns_use_fixed_point_numeric_never_float(self):
        monetary_columns = [
            (AIPricingVersion, "usd_to_inr_rate", 10, 4),
            (TenantAIQuota, "daily_exposure_limit_inr", 12, 4),
            (TenantAIQuota, "pending_reserve_cap_percent", 5, 4),
            (TenantDailyAIUsage, "committed_cost_inr", 14, 4),
            (TenantDailyAIUsage, "pending_reserved_cost_inr", 14, 4),
            (TenantDailyAIUsage, "uncertain_exposure_cost_inr", 14, 4),
            (TenantDailyCategoryUsage, "committed_cost_inr", 14, 4),
            (AITokenReservation, "reserved_cost_inr", 12, 4),
            (AITokenReservation, "actual_cost_inr", 12, 4),
            (AITokenReservation, "uncertain_cost_held_inr", 12, 4),
            (AIProviderAttempt, "estimated_cost_inr", 12, 4),
            (AIProviderAttempt, "actual_cost_inr", 12, 4),
            (AIProviderAttempt, "manual_settled_cost_inr", 12, 4),
            (AIProviderAttempt, "late_reported_cost_inr", 12, 4),
            (AIFinancialAdjustment, "cost_inr_delta", 12, 4),
        ]
        for model_cls, col_name, precision, scale in monetary_columns:
            col = model_cls.__table__.c[col_name]
            assert isinstance(col.type, Numeric), f"{model_cls.__name__}.{col_name} must be Numeric, got {col.type}"
            assert col.type.precision == precision
            assert col.type.scale == scale

    def test_token_columns_use_64bit_bigint_preventing_overflow(self):
        bigint_columns = [
            (AIPricingActivation, "activation_seq"),
            (AITokenReservation, "estimated_input_tokens"),
            (AITokenReservation, "reserved_output_tokens"),
            (AITokenReservation, "total_reserved_tokens"),
            (AITokenReservation, "actual_input_tokens"),
            (AITokenReservation, "actual_output_tokens"),
            (AITokenReservation, "actual_total_tokens"),
            (AITokenReservation, "uncertain_tokens_held"),
            (AIProviderAttempt, "estimated_tokens"),
            (AIProviderAttempt, "input_tokens"),
            (AIProviderAttempt, "output_tokens"),
            (AIProviderAttempt, "manual_settled_tokens"),
            (AIProviderAttempt, "late_reported_input_tokens"),
            (AIProviderAttempt, "late_reported_output_tokens"),
        ]
        for model_cls, col_name in bigint_columns:
            col = model_cls.__table__.c[col_name]
            assert isinstance(col.type, BigInteger), f"{model_cls.__name__}.{col_name} must be BigInteger, got {col.type}"

    def test_alembic_revision_chain_single_head_c3d4e5f6a7b8(self):
        cfg = AlembicConfig("alembic.ini")
        script_dir = ScriptDirectory.from_config(cfg)
        heads = script_dir.get_heads()
        assert heads == ["c3d4e5f6a7b8"], f"Expected single head c3d4e5f6a7b8, got {heads}"
        rev = script_dir.get_revision("c3d4e5f6a7b8")
        assert rev is not None
        assert rev.down_revision == "b2c3d4e5f6a7"
        rev_31 = script_dir.get_revision("b2c3d4e5f6a7")
        assert rev_31 is not None
        assert rev_31.down_revision == "a1b2c3d4e5f6"
        rev_30 = script_dir.get_revision("a1b2c3d4e5f6")
        assert rev_30 is not None
        assert rev_30.down_revision == "f2a3b4c5d6e7"

    async def test_all_stage7_tables_exist_in_postgresql_with_no_unapproved_seeds(self, db_connection):
        session = _make_session(db_connection)
        try:
            def _inspect_tables(sync_conn):
                inspector = inspect(sync_conn)
                return set(inspector.get_table_names(schema="public"))

            conn = await session.connection()
            pg_tables = await conn.run_sync(_inspect_tables)
            for tbl in (
                "ai_pricing_versions",
                "ai_pricing_activations",
                "tenant_ai_quotas",
                "tenant_daily_ai_usage",
                "tenant_daily_category_usage",
                "ai_token_reservations",
                "ai_provider_attempts",
                "ai_financial_adjustments",
            ):
                assert tbl in pg_tables, f"Table {tbl} not present in live PostgreSQL"

            await _set_context(session, None, is_platform_admin=True)
            unapproved_pv = (
                await session.execute(select(AIPricingVersion).where(AIPricingVersion.version_id == "2026-11-v1"))
            ).scalar_one_or_none()
            assert unapproved_pv is None, "Unapproved pricing version '2026-11-v1' must NOT be seeded"
            activation_count = (
                await session.execute(
                    select(AIPricingActivation).where(~AIPricingActivation.pricing_version.like("r01-conc-%"))
                )
            ).scalars().all()
            assert len(activation_count) == 0, "Unapproved pricing activations must NOT be seeded"
        finally:
            await session.close()


# ==============================================================================
# Suite 2: Constraints, FKs, Activation Design & State Invariant Enforcement
# ==============================================================================


class TestStage71SchemaConstraintsAndIntegrity:
    """Verifies constraints, composite FKs, token arithmetic, and pricing activations."""

    async def test_reservation_status_and_timestamp_consistency_checks(self, db_connection):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        pv_id = f"test-pv-{uuid.uuid4().hex[:8]}"
        today = date.today()
        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_id, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_id, user_id, "chk-res")
            await _create_pricing_version(session, pv_id)
            await _setup_rollup_chain(session, inst_id, today)

            # 1. 'EXPIRED' status rejected
            sp = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="portal-assistant/generate",
                    status="EXPIRED",
                    pricing_version=pv_id,
                    estimated_input_tokens=100,
                    reserved_output_tokens=200,
                    total_reserved_tokens=300,
                    reserved_cost_inr=Decimal("0.0100"),
                    expires_at=datetime.now(UTC) + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_token_reservations_status"):
                await session.flush()
            await sp.rollback()

            # 2. DISPATCHED, COMMITTED, and UNKNOWN_USAGE without dispatched_at rejected
            now_ts = datetime.now(UTC)
            for bad_status in ("DISPATCHED", "COMMITTED", "UNKNOWN_USAGE"):
                sp = await session.begin_nested()
                session.add(
                    AITokenReservation(
                        id=uuid.uuid4(),
                        institution_id=inst_id,
                        user_id=user_id,
                        logical_operation_id=uuid.uuid4(),
                        usage_date=today,
                        usage_category="interactive_ai",
                        endpoint="portal-assistant/generate",
                        status=bad_status,
                        dispatched_at=None,
                        reconciled_at=now_ts if bad_status == "COMMITTED" else None,
                        pricing_version=pv_id,
                        estimated_input_tokens=100,
                        reserved_output_tokens=200,
                        total_reserved_tokens=300,
                        reserved_cost_inr=Decimal("0.0100"),
                        expires_at=now_ts + timedelta(minutes=2),
                    )
                )
                with pytest.raises(IntegrityError, match="ck_ai_token_reservations_dispatched_ts"):
                    await session.flush()
                await sp.rollback()

            # 3. RESERVED with dispatched_at rejected
            sp = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="portal-assistant/generate",
                    status="RESERVED",
                    dispatched_at=now_ts,
                    pricing_version=pv_id,
                    estimated_input_tokens=100,
                    reserved_output_tokens=200,
                    total_reserved_tokens=300,
                    reserved_cost_inr=Decimal("0.0100"),
                    expires_at=now_ts + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_token_reservations_reserved_no_dispatch"):
                await session.flush()
            await sp.rollback()

            # 4. COMMITTED or RELEASED without reconciled_at rejected; RESERVED/DISPATCHED with reconciled_at rejected
            for bad_rec_status, disp_v, rec_v in (
                ("COMMITTED", now_ts, None),
                ("RELEASED", None, None),
                ("RESERVED", None, now_ts),
                ("DISPATCHED", now_ts, now_ts),
            ):
                sp = await session.begin_nested()
                session.add(
                    AITokenReservation(
                        id=uuid.uuid4(),
                        institution_id=inst_id,
                        user_id=user_id,
                        logical_operation_id=uuid.uuid4(),
                        usage_date=today,
                        usage_category="interactive_ai",
                        endpoint="portal-assistant/generate",
                        status=bad_rec_status,
                        dispatched_at=disp_v,
                        reconciled_at=rec_v,
                        pricing_version=pv_id,
                        estimated_input_tokens=100,
                        reserved_output_tokens=200,
                        total_reserved_tokens=300,
                        reserved_cost_inr=Decimal("0.0100"),
                        expires_at=now_ts + timedelta(minutes=2),
                    )
                )
                with pytest.raises(IntegrityError, match="ck_ai_token_reservations_reconciled_ts"):
                    await session.flush()
                await sp.rollback()

            # 5. Documented architectural exception: RELEASED permitted both pre-dispatch (dispatched_at=None)
            # and post-dispatch via UNKNOWN_USAGE manual zero-charge release (dispatched_at IS NOT NULL).
            sp = await session.begin_nested()
            r_pre_rel = AITokenReservation(
                id=uuid.uuid4(),
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=uuid.uuid4(),
                usage_date=today,
                usage_category="interactive_ai",
                endpoint="portal-assistant/generate",
                status="RELEASED",
                dispatched_at=None,
                reconciled_at=now_ts,
                pricing_version=pv_id,
                estimated_input_tokens=100,
                reserved_output_tokens=200,
                total_reserved_tokens=300,
                reserved_cost_inr=Decimal("0.0100"),
                expires_at=now_ts + timedelta(minutes=2),
            )
            r_post_rel = AITokenReservation(
                id=uuid.uuid4(),
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=uuid.uuid4(),
                usage_date=today,
                usage_category="interactive_ai",
                endpoint="portal-assistant/generate",
                status="RELEASED",
                dispatched_at=now_ts - timedelta(seconds=5),
                reconciled_at=now_ts,
                pricing_version=pv_id,
                estimated_input_tokens=100,
                reserved_output_tokens=200,
                total_reserved_tokens=300,
                reserved_cost_inr=Decimal("0.0100"),
                expires_at=now_ts + timedelta(minutes=2),
            )
            session.add_all([r_pre_rel, r_post_rel])
            await session.flush()
            await sp.rollback()
        finally:
            await session.close()

    async def test_token_arithmetic_consistency_and_bigint_overflow_protection(self, db_connection):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        pv_id = f"test-arith-{uuid.uuid4().hex[:8]}"
        today = date.today()
        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_id, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_id, user_id, "arith")
            await _create_pricing_version(session, pv_id)
            await _setup_rollup_chain(session, inst_id, today, category="ingestion_embeddings")

            # 1. Reserved token sum mismatch rejected
            sp1 = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="ingestion_embeddings",
                    endpoint="rag/ingest",
                    status="RESERVED",
                    pricing_version=pv_id,
                    estimated_input_tokens=100,
                    reserved_output_tokens=200,
                    total_reserved_tokens=999,
                    reserved_cost_inr=Decimal("0.0100"),
                    expires_at=datetime.now(UTC) + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_res_tot_res_sum"):
                await session.flush()
            await sp1.rollback()

            # 2. Actual token sum mismatch rejected
            sp2 = await session.begin_nested()
            now_ts = datetime.now(UTC)
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="ingestion_embeddings",
                    endpoint="rag/ingest",
                    status="COMMITTED",
                    dispatched_at=now_ts,
                    reconciled_at=now_ts,
                    pricing_version=pv_id,
                    estimated_input_tokens=100,
                    reserved_output_tokens=200,
                    total_reserved_tokens=300,
                    reserved_cost_inr=Decimal("0.0100"),
                    actual_input_tokens=40,
                    actual_output_tokens=60,
                    actual_total_tokens=9999,
                    expires_at=now_ts + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_res_act_tot_sum"):
                await session.flush()
            await sp2.rollback()

            # 3. Large > INT4_MAX (32-bit) batch sums succeed cleanly via BIGINT without overflow
            sp3 = await session.begin_nested()
            large_res = AITokenReservation(
                id=uuid.uuid4(),
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=uuid.uuid4(),
                usage_date=today,
                usage_category="ingestion_embeddings",
                endpoint="rag/ingest-batch",
                status="COMMITTED",
                dispatched_at=now_ts,
                reconciled_at=now_ts,
                pricing_version=pv_id,
                estimated_input_tokens=2_500_000_000,
                reserved_output_tokens=500_000_000,
                total_reserved_tokens=3_000_000_000,
                reserved_cost_inr=Decimal("100.0000"),
                actual_input_tokens=2_400_000_000,
                actual_output_tokens=100_000_000,
                actual_total_tokens=2_500_000_000,
                actual_cost_inr=Decimal("90.0000"),
                expires_at=now_ts + timedelta(minutes=2),
            )
            session.add(large_res)
            await session.flush()
            assert large_res.total_reserved_tokens == 3_000_000_000
            await sp3.rollback()

            # 4. Unrealistic INT8 overflow-probing value (> 10^15) rejected by bounds check
            sp4 = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="ingestion_embeddings",
                    endpoint="rag/ingest",
                    status="RESERVED",
                    pricing_version=pv_id,
                    estimated_input_tokens=10**16,
                    reserved_output_tokens=10**16,
                    total_reserved_tokens=2 * (10**16),
                    reserved_cost_inr=Decimal("0.0100"),
                    expires_at=now_ts + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_res_reserved_bounds"):
                await session.flush()
            await sp4.rollback()
        finally:
            await session.close()

    async def test_attempt_sequence_provider_id_uniqueness_and_empty_metadata_rejected(self, db_connection):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        pv_id = f"test-pv-{uuid.uuid4().hex[:8]}"
        today = date.today()
        res_id = uuid.uuid4()
        op_id = uuid.uuid4()
        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_id, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_id, user_id, "att-uniq")
            await _create_pricing_version(session, pv_id)
            await _setup_rollup_chain(session, inst_id, today)

            # Empty endpoint / idempotency_key rejected
            sp_ep = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=op_id,
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="   ",
                    status="RESERVED",
                    pricing_version=pv_id,
                    estimated_input_tokens=100,
                    reserved_output_tokens=200,
                    total_reserved_tokens=300,
                    reserved_cost_inr=Decimal("0.0100"),
                    expires_at=datetime.now(UTC) + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_res_endpoint_nonempty"):
                await session.flush()
            await sp_ep.rollback()

            sp_ik = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=op_id,
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    idempotency_key="  ",
                    status="RESERVED",
                    pricing_version=pv_id,
                    estimated_input_tokens=100,
                    reserved_output_tokens=200,
                    total_reserved_tokens=300,
                    reserved_cost_inr=Decimal("0.0100"),
                    expires_at=datetime.now(UTC) + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_res_idem_key_nonempty"):
                await session.flush()
            await sp_ik.rollback()

            res = AITokenReservation(
                id=res_id,
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=op_id,
                usage_date=today,
                usage_category="interactive_ai",
                endpoint="admin-assistant/generate",
                status="DISPATCHED",
                dispatched_at=datetime.now(UTC),
                pricing_version=pv_id,
                estimated_input_tokens=100,
                reserved_output_tokens=200,
                total_reserved_tokens=300,
                reserved_cost_inr=Decimal("0.0100"),
                expires_at=datetime.now(UTC) + timedelta(minutes=2),
            )
            session.add(res)
            await session.flush()

            a1 = AIProviderAttempt(
                reservation_id=res_id,
                institution_id=inst_id,
                logical_operation_id=op_id,
                attempt_sequence=1,
                provider="gemini",
                model="gemini-test",
                status="TIMEOUT_UNCERTAIN",
                provider_request_id="req_vendor_123",
                pricing_version=pv_id,
                estimated_tokens=300,
                estimated_cost_inr=Decimal("0.0100"),
                manual_settled_tokens=250,
                manual_settled_cost_inr=Decimal("0.0080"),
                manual_settled_at=datetime.now(UTC),
                late_reported_input_tokens=150,
                late_reported_output_tokens=250,
                late_reported_cost_inr=Decimal("0.0125"),
                late_reported_at=datetime.now(UTC),
            )
            session.add(a1)
            await session.flush()

            # Duplicate attempt_sequence within same reservation rejected
            sp1 = await session.begin_nested()
            session.add(
                AIProviderAttempt(
                    reservation_id=res_id,
                    institution_id=inst_id,
                    logical_operation_id=op_id,
                    attempt_sequence=1,
                    provider="groq",
                    model="groq-test",
                    status="DISPATCHED",
                    provider_request_id="req_vendor_other",
                    pricing_version=pv_id,
                    estimated_tokens=300,
                    estimated_cost_inr=Decimal("0.0050"),
                )
            )
            with pytest.raises(IntegrityError, match="uq_ai_attempt_seq"):
                await session.flush()
            await sp1.rollback()

            # Duplicate provider_request_id rejected
            sp2 = await session.begin_nested()
            session.add(
                AIProviderAttempt(
                    reservation_id=res_id,
                    institution_id=inst_id,
                    logical_operation_id=op_id,
                    attempt_sequence=2,
                    provider="gemini",
                    model="gemini-test",
                    status="SUCCEEDED",
                    provider_request_id="req_vendor_123",
                    pricing_version=pv_id,
                    estimated_tokens=300,
                    estimated_cost_inr=Decimal("0.0100"),
                )
            )
            with pytest.raises(IntegrityError, match="uq_ai_attempt_provider_req_id"):
                await session.flush()
            await sp2.rollback()

            # Empty / whitespace provider_request_id, provider, and model rejected
            for field_overrides, err_name in (
                ({"provider_request_id": ""}, "ck_ai_att_provider_req_id_nonempty"),
                ({"provider_request_id": "   "}, "ck_ai_att_provider_req_id_nonempty"),
                ({"provider": "  "}, "ck_ai_att_provider_nonempty"),
                ({"model": ""}, "ck_ai_att_model_nonempty"),
            ):
                sp_empty = await session.begin_nested()
                kwargs = {
                    "reservation_id": res_id,
                    "institution_id": inst_id,
                    "logical_operation_id": op_id,
                    "attempt_sequence": 3,
                    "provider": "gemini",
                    "model": "gemini-test",
                    "status": "DISPATCHED",
                    "provider_request_id": "req_ok",
                    "pricing_version": pv_id,
                    "estimated_tokens": 100,
                    "estimated_cost_inr": Decimal("0.0010"),
                }
                kwargs.update(field_overrides)
                session.add(AIProviderAttempt(**kwargs))
                with pytest.raises(IntegrityError, match=err_name):
                    await session.flush()
                await sp_empty.rollback()
        finally:
            await session.close()

    async def test_negative_financial_and_token_values_rejected(self, db_connection):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        today = date.today()
        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_id, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_id, user_id, "neg-chk")

            sp1 = await session.begin_nested()
            session.add(
                TenantAIQuota(
                    institution_id=inst_id,
                    quota_timezone="UTC",
                    daily_interactive_token_limit=1000,
                    daily_ingestion_token_limit=1000,
                    daily_other_token_limit=1000,
                    daily_exposure_limit_inr=Decimal("-1.0000"),
                    pending_reserve_cap_percent=Decimal("0.1500"),
                    max_tokens_per_request=2048,
                    missing_usage_policy="HOLD_UNKNOWN",
                    tier_name="custom",
                )
            )
            with pytest.raises(IntegrityError, match="ck_tenant_ai_quotas_exposure_nonneg"):
                await session.flush()
            await sp1.rollback()

            sp2 = await session.begin_nested()
            session.add(
                TenantAIQuota(
                    institution_id=inst_id,
                    quota_timezone="UTC",
                    daily_interactive_token_limit=1000,
                    daily_ingestion_token_limit=1000,
                    daily_other_token_limit=1000,
                    daily_exposure_limit_inr=Decimal("100.0000"),
                    pending_reserve_cap_percent=Decimal("1.5000"),
                    max_tokens_per_request=2048,
                    missing_usage_policy="HOLD_UNKNOWN",
                    tier_name="custom",
                )
            )
            with pytest.raises(IntegrityError, match="ck_tenant_ai_quotas_reserve_pct_range"):
                await session.flush()
            await sp2.rollback()

            sp3 = await session.begin_nested()
            session.add(
                TenantDailyAIUsage(
                    institution_id=inst_id,
                    usage_date=today,
                    committed_cost_inr=Decimal("-0.0001"),
                )
            )
            with pytest.raises(IntegrityError, match="ck_tenant_daily_ai_usage_committed_cost_nonneg"):
                await session.flush()
            await sp3.rollback()
        finally:
            await session.close()

    async def test_financial_adjustment_composite_fk_blocks_cross_reservation_pairing(self, db_connection):
        inst_a = uuid.uuid4()
        inst_b = uuid.uuid4()
        user_a = uuid.uuid4()
        pv_id = f"test-comp-{uuid.uuid4().hex[:8]}"
        today = date.today()
        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_a, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_a, user_a, "comp-a")
            session.add(Institution(id=inst_b, name="Comp B", slug=f"comp-b-{inst_b.hex[:8]}", is_active=True))
            await _create_pricing_version(session, pv_id)
            await _setup_rollup_chain(session, inst_a, today)

            r1_id = uuid.uuid4()
            r2_id = uuid.uuid4()
            now_ts = datetime.now(UTC)
            for rid in (r1_id, r2_id):
                session.add(
                    AITokenReservation(
                        id=rid,
                        institution_id=inst_a,
                        user_id=user_a,
                        logical_operation_id=uuid.uuid4(),
                        usage_date=today,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        status="DISPATCHED",
                        dispatched_at=now_ts,
                        pricing_version=pv_id,
                        estimated_input_tokens=50,
                        reserved_output_tokens=100,
                        total_reserved_tokens=150,
                        reserved_cost_inr=Decimal("0.0050"),
                        expires_at=now_ts + timedelta(minutes=2),
                    )
                )
            await session.flush()

            a1_id = uuid.uuid4()
            a2_id = uuid.uuid4()
            session.add_all([
                AIProviderAttempt(
                    id=a1_id,
                    reservation_id=r1_id,
                    institution_id=inst_a,
                    logical_operation_id=uuid.uuid4(),
                    attempt_sequence=1,
                    provider="gemini",
                    model="gemini-test",
                    status="TIMEOUT_UNCERTAIN",
                    pricing_version=pv_id,
                    estimated_tokens=150,
                    estimated_cost_inr=Decimal("0.0050"),
                ),
                AIProviderAttempt(
                    id=a2_id,
                    reservation_id=r2_id,
                    institution_id=inst_a,
                    logical_operation_id=uuid.uuid4(),
                    attempt_sequence=1,
                    provider="groq",
                    model="groq-test",
                    status="TIMEOUT_UNCERTAIN",
                    pricing_version=pv_id,
                    estimated_tokens=150,
                    estimated_cost_inr=Decimal("0.0030"),
                ),
            ])
            await session.flush()

            # 1. Valid (inst_a, r1_id, a1_id) pair succeeds
            valid_adj = AIFinancialAdjustment(
                institution_id=inst_a,
                reservation_id=r1_id,
                attempt_id=a1_id,
                adjusted_by_actor="SYSTEM_TEST",
                adjustment_type="LATE_SETTLEMENT",
                token_delta=10,
                cost_inr_delta=Decimal("0.0010"),
                adjustment_reason="VALID_PAIR",
                notes="Matches parent reservation R1 and attempt A1",
            )
            session.add(valid_adj)
            await session.flush()

            # 2. Cross-reservation pairing inside SAME tenant (R1 + A2 from R2) REJECTED!
            sp_cross_res = await session.begin_nested()
            session.add(
                AIFinancialAdjustment(
                    institution_id=inst_a,
                    reservation_id=r1_id,
                    attempt_id=a2_id,
                    adjusted_by_actor="SYSTEM_TEST",
                    adjustment_type="LATE_SETTLEMENT",
                    token_delta=10,
                    cost_inr_delta=Decimal("0.0010"),
                    adjustment_reason="MISMATCH_RES_ATTEMPT",
                    notes="Illegal cross-reservation pairing",
                )
            )
            with pytest.raises(IntegrityError, match="fk_adjustment_res_attempt_tenant"):
                await session.flush()
            await sp_cross_res.rollback()

            # 3. Orphaned attempt_id without reservation_id REJECTED (prevents MATCH SIMPLE bypass)
            sp_null_res = await session.begin_nested()
            session.add(
                AIFinancialAdjustment(
                    institution_id=inst_a,
                    reservation_id=None,
                    attempt_id=a1_id,
                    adjusted_by_actor="SYSTEM_TEST",
                    adjustment_type="MANUAL_SETTLE",
                    token_delta=10,
                    cost_inr_delta=Decimal("0.0010"),
                    adjustment_reason="MISSING_RES",
                    notes="Must specify reservation_id whenever attempt_id is set",
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_financial_adjustments_attempt_requires_res"):
                await session.flush()
            await sp_null_res.rollback()

            # 4. Cross-tenant pairing REJECTED (attempt + FK under inst_b context)
            await _set_context(session, inst_b, is_platform_admin=False)
            sp_cross_tenant = await session.begin_nested()
            session.add(
                AIProviderAttempt(
                    reservation_id=r1_id,
                    institution_id=inst_b,
                    logical_operation_id=uuid.uuid4(),
                    attempt_sequence=2,
                    provider="gemini",
                    model="gemini-test",
                    status="DISPATCHED",
                    pricing_version=pv_id,
                    estimated_tokens=100,
                    estimated_cost_inr=Decimal("0.0020"),
                )
            )
            with pytest.raises(IntegrityError, match="fk_attempt_reservation_tenant"):
                await session.flush()
            await sp_cross_tenant.rollback()

            sp_cross_adj = await session.begin_nested()
            session.add(
                AIFinancialAdjustment(
                    institution_id=inst_b,
                    reservation_id=r1_id,
                    attempt_id=a1_id,
                    adjusted_by_actor="SYSTEM_TEST",
                    adjustment_type="LATE_SETTLEMENT",
                    token_delta=1,
                    cost_inr_delta=Decimal("0.0001"),
                    adjustment_reason="CROSS_TENANT",
                    notes="Cross-tenant spoof",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await sp_cross_adj.rollback()
        finally:
            await session.close()

    async def test_pricing_activation_design_preserves_immutability_and_selects_latest(self, db_connection):
        pv1 = f"v1-{uuid.uuid4().hex[:6]}"
        pv2 = f"v2-{uuid.uuid4().hex[:6]}"
        pv_draft = f"draft-{uuid.uuid4().hex[:6]}"
        session = _make_session(db_connection)
        try:
            await _set_context(session, None, is_platform_admin=True)
            await _create_pricing_version(session, pv1, is_active=True)
            await _create_pricing_version(session, pv2, is_active=True)
            await _create_pricing_version(session, pv_draft, is_active=False)

            # Activate v1 -> switch to v2 -> rollback to v1 purely via append-only INSERTs
            for ver, reason in ((pv1, "INITIAL"), (pv2, "RATE_UPDATE"), (pv1, "ROLLBACK")):
                session.add(
                    AIPricingActivation(
                        pricing_version=ver,
                        activated_by_actor="FINOPS_ADMIN",
                        activation_reason=reason,
                    )
                )
                await session.flush()

            latest = (
                await session.execute(
                    select(AIPricingActivation)
                    .where(AIPricingActivation.pricing_version.in_([pv1, pv2]))
                    .order_by(AIPricingActivation.activation_seq.desc())
                    .limit(1)
                )
            ).scalar_one()
            assert latest.pricing_version == pv1
            assert latest.activation_reason == "ROLLBACK"

            # Inactive/draft version (is_active=False) CANNOT be activated (enforced by composite FK)
            sp_inact = await session.begin_nested()
            session.add(
                AIPricingActivation(
                    pricing_version=pv_draft,
                    activated_by_actor="FINOPS_ADMIN",
                    activation_reason="SHOULD_FAIL",
                )
            )
            with pytest.raises(IntegrityError, match="fk_pricing_activation_eligible_version"):
                await session.flush()
            await sp_inact.rollback()

            # Ordinary tenant user CANNOT insert activation events (RLS admin check)
            await _set_context(session, uuid.uuid4(), is_platform_admin=False)
            sp_nonadmin = await session.begin_nested()
            session.add(
                AIPricingActivation(
                    pricing_version=pv2,
                    activated_by_actor="TENANT_SPOOF",
                    activation_reason="UNAUTHORIZED",
                )
            )
            with pytest.raises((ProgrammingError, DBAPIError)):
                await session.flush()
            await sp_nonadmin.rollback()
        finally:
            await session.close()

    async def test_r01_pricing_activation_sequence_blocks_manual_and_override_values(self, db_connection):
        pv1 = f"r01-v1-{uuid.uuid4().hex[:6]}"
        pv2 = f"r01-v2-{uuid.uuid4().hex[:6]}"
        session = _make_session(db_connection)
        try:
            await _set_context(session, None, is_platform_admin=True)
            await _create_pricing_version(session, pv1, is_active=True)
            await _create_pricing_version(session, pv2, is_active=True)

            # 1. Normal ORM single-row & multi-row inserts generate strictly positive monotonic IDs
            a1 = AIPricingActivation(pricing_version=pv1, activated_by_actor="ADM", activation_reason="INIT")
            a2 = AIPricingActivation(pricing_version=pv2, activated_by_actor="ADM", activation_reason="UP")
            a3 = AIPricingActivation(pricing_version=pv1, activated_by_actor="ADM", activation_reason="BACK")
            session.add_all([a1, a2, a3])
            await session.flush()
            assert a1.activation_seq >= 1
            assert a3.activation_seq > a2.activation_seq > a1.activation_seq

            # 2. Multi-row INSERT ... SELECT succeeds via row-level identity generation
            sel_rows = (
                await session.execute(
                    text(
                        """
                        INSERT INTO ai_pricing_activations
                            (id, pricing_version, activated_by_actor, activation_reason)
                        SELECT CAST(v.id AS uuid), v.pv, 'ADM', 'MULTI_SEL'
                        FROM (VALUES (:id1, :pv1), (:id2, :pv2)) AS v(id, pv)
                        RETURNING activation_seq
                        """
                    ),
                    {"id1": str(uuid.uuid4()), "id2": str(uuid.uuid4()), "pv1": pv1, "pv2": pv2},
                )
            ).scalars().all()
            assert len(sel_rows) == 2 and sel_rows[1] > sel_rows[0] > a3.activation_seq

            # 3. Attempting to supply explicit negative or arbitrary positive seq MUST fail (GENERATED ALWAYS -> 428C9)
            for bad_seq in (-1, -50, 0, 999999999):
                sp_exp = await session.begin_nested()
                with pytest.raises((ProgrammingError, DBAPIError)):
                    await session.execute(
                        text(
                            """
                            INSERT INTO ai_pricing_activations
                                (id, activation_seq, pricing_version, activated_by_actor, activation_reason)
                            VALUES (:id, :seq, :pv, 'ADM', 'EXPLICIT_ATTEMPT')
                            """
                        ),
                        {"id": str(uuid.uuid4()), "seq": bad_seq, "pv": pv2},
                    )
                await sp_exp.rollback()

            # 4. Even WITH `OVERRIDING SYSTEM VALUE`, arbitrary/negative sequences MUST fail closed
            for bad_seq in (-50, 0, sel_rows[-1] + 500, sel_rows[-1]):
                sp_ov = await session.begin_nested()
                with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
                    await session.execute(
                        text(
                            """
                            INSERT INTO ai_pricing_activations
                                (id, activation_seq, pricing_version, activated_by_actor, activation_reason)
                            OVERRIDING SYSTEM VALUE
                            VALUES (:id, :seq, :pv, 'ADM', 'OVERRIDE_ATTEMPT')
                            """
                        ),
                        {"id": str(uuid.uuid4()), "seq": bad_seq, "pv": pv2},
                    )
                await sp_ov.rollback()

            # 5. Latest query still resolves pv2 -> wait INSERT..SELECT ended on pv2, test normal rollback back to pv1
            a_final = AIPricingActivation(pricing_version=pv1, activated_by_actor="ADM", activation_reason="FINAL")
            session.add(a_final)
            await session.flush()
            latest_pv = (
                await session.execute(
                    select(AIPricingActivation.pricing_version)
                    .order_by(AIPricingActivation.activation_seq.desc())
                    .limit(1)
                )
            ).scalar_one()
            assert latest_pv == pv1
        finally:
            await session.close()

    async def test_r03_timestamp_reconciliation_unknown_usage_and_index_hardening(self, db_connection):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        pv_id = f"r03-ts-{uuid.uuid4().hex[:6]}"
        today = date.today()
        now_ts = datetime.now(UTC)
        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_id, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_id, user_id, "r03-ts")
            await _create_pricing_version(session, pv_id)
            await _setup_rollup_chain(session, inst_id, today)

            # 1. Index metadata: ix_ai_pricing_activations_version_seq replaced ix_ai_pricing_activations_active_lookup
            idx_names = {
                r[0]
                for r in (
                    await session.execute(
                        text("SELECT indexname FROM pg_indexes WHERE tablename = 'ai_pricing_activations'")
                    )
                ).fetchall()
            }
            assert "ix_ai_pricing_activations_version_seq" in idx_names
            assert "uq_ai_pricing_activations_seq" in idx_names
            assert "ix_ai_pricing_activations_active_lookup" not in idx_names

            # 2. Boundary valid timestamps: expires_at == created_at; COMMITTED reconciled_at == dispatched_at
            r_eq = AITokenReservation(
                id=uuid.uuid4(),
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=uuid.uuid4(),
                usage_date=today,
                usage_category="interactive_ai",
                endpoint="rag/query",
                status="COMMITTED",
                pricing_version=pv_id,
                estimated_input_tokens=10,
                reserved_output_tokens=20,
                total_reserved_tokens=30,
                reserved_cost_inr=Decimal("0.0010"),
                created_at=now_ts,
                expires_at=now_ts,
                dispatched_at=now_ts,
                reconciled_at=now_ts,
            )
            r_unk = AITokenReservation(
                id=uuid.uuid4(),
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=uuid.uuid4(),
                usage_date=today,
                usage_category="interactive_ai",
                endpoint="rag/query",
                status="UNKNOWN_USAGE",
                pricing_version=pv_id,
                estimated_input_tokens=10,
                reserved_output_tokens=20,
                total_reserved_tokens=30,
                reserved_cost_inr=Decimal("0.0010"),
                uncertain_tokens_held=30,
                uncertain_cost_held_inr=Decimal("0.0010"),
                created_at=now_ts,
                expires_at=now_ts + timedelta(minutes=1),
                dispatched_at=now_ts,
                reconciled_at=None,
            )
            session.add_all([r_eq, r_unk])
            await session.flush()

            # 3. expires_at < created_at REJECTED
            sp_exp = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    status="RESERVED",
                    pricing_version=pv_id,
                    estimated_input_tokens=10,
                    reserved_output_tokens=20,
                    total_reserved_tokens=30,
                    reserved_cost_inr=Decimal("0.0010"),
                    created_at=now_ts,
                    expires_at=now_ts - timedelta(seconds=1),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_token_reservations_expires_after_created"):
                await session.flush()
            await sp_exp.rollback()

            # 4. reconciled_at < dispatched_at REJECTED on COMMITTED and post-dispatch RELEASED
            for bad_st in ("COMMITTED", "RELEASED"):
                sp_rec_order = await session.begin_nested()
                session.add(
                    AITokenReservation(
                        id=uuid.uuid4(),
                        institution_id=inst_id,
                        user_id=user_id,
                        logical_operation_id=uuid.uuid4(),
                        usage_date=today,
                        usage_category="interactive_ai",
                        endpoint="rag/query",
                        status=bad_st,
                        pricing_version=pv_id,
                        estimated_input_tokens=10,
                        reserved_output_tokens=20,
                        total_reserved_tokens=30,
                        reserved_cost_inr=Decimal("0.0010"),
                        created_at=now_ts - timedelta(minutes=1),
                        expires_at=now_ts + timedelta(minutes=2),
                        dispatched_at=now_ts,
                        reconciled_at=now_ts - timedelta(seconds=1),
                    )
                )
                with pytest.raises(IntegrityError, match="ck_ai_token_reservations_reconciled_after_dispatch"):
                    await session.flush()
                await sp_rec_order.rollback()

            # 5. UNKNOWN_USAGE with reconciled_at IS NOT NULL REJECTED
            sp_unk = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    status="UNKNOWN_USAGE",
                    pricing_version=pv_id,
                    estimated_input_tokens=10,
                    reserved_output_tokens=20,
                    total_reserved_tokens=30,
                    reserved_cost_inr=Decimal("0.0010"),
                    created_at=now_ts,
                    expires_at=now_ts + timedelta(minutes=2),
                    dispatched_at=now_ts,
                    reconciled_at=now_ts,
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_token_reservations_reconciled_ts"):
                await session.flush()
            await sp_unk.rollback()
        finally:
            await session.close()

    async def test_r03_attempt_rollup_and_adjustment_token_boundary_invariants(self, db_connection):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        pv_id = f"r03-bnd-{uuid.uuid4().hex[:6]}"
        today = date.today()
        now_ts = datetime.now(UTC)
        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_id, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_id, user_id, "r03-bnd")
            await _create_pricing_version(session, pv_id)

            max_term = 10**15
            max_op_sum = 2 * (10**15)
            max_agg = 10**17

            # Valid exact upper boundary on aggregate rollup + sum never overflows INT8
            daily = TenantDailyAIUsage(
                institution_id=inst_id,
                usage_date=today,
                committed_total_tokens=max_agg,
                pending_reserved_tokens=max_agg,
                uncertain_reserved_tokens=max_agg,
            )
            cat = TenantDailyCategoryUsage(
                institution_id=inst_id,
                usage_date=today,
                usage_category="interactive_ai",
                committed_input_tokens=max_agg,
                committed_output_tokens=max_agg,
                committed_total_tokens=max_agg,
                pending_reserved_tokens=max_agg,
                uncertain_reserved_tokens=max_agg,
            )
            session.add_all([daily, cat])
            await session.flush()

            agg_sum = (
                await session.execute(
                    text(
                        "SELECT committed_total_tokens + pending_reserved_tokens + uncertain_reserved_tokens "
                        "FROM tenant_daily_ai_usage WHERE id = :id"
                    ),
                    {"id": str(daily.id)},
                )
            ).scalar_one()
            assert agg_sum == 3 * max_agg

            res = AITokenReservation(
                id=uuid.uuid4(),
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=uuid.uuid4(),
                usage_date=today,
                usage_category="interactive_ai",
                endpoint="rag/query",
                status="DISPATCHED",
                pricing_version=pv_id,
                estimated_input_tokens=max_term,
                reserved_output_tokens=max_term,
                total_reserved_tokens=max_op_sum,
                reserved_cost_inr=Decimal("10.0000"),
                uncertain_tokens_held=max_op_sum,
                created_at=now_ts,
                dispatched_at=now_ts,
                expires_at=now_ts + timedelta(minutes=2),
            )
            session.add(res)
            await session.flush()

            att = AIProviderAttempt(
                id=uuid.uuid4(),
                reservation_id=res.id,
                institution_id=inst_id,
                logical_operation_id=res.logical_operation_id,
                attempt_sequence=1,
                provider="gemini",
                model="gemini-test",
                status="SUCCEEDED",
                pricing_version=pv_id,
                estimated_tokens=max_op_sum,
                estimated_cost_inr=Decimal("10.0000"),
                input_tokens=max_term,
                output_tokens=max_term,
                manual_settled_tokens=max_op_sum,
                late_reported_input_tokens=max_term,
                late_reported_output_tokens=max_term,
            )
            adj = AIFinancialAdjustment(
                institution_id=inst_id,
                reservation_id=res.id,
                attempt_id=att.id,
                adjusted_by_actor="ADM",
                adjustment_type="VARIANCE_CREDIT",
                token_delta=-max_op_sum,
                cost_inr_delta=Decimal("-1.0000"),
                adjustment_reason="BOUNDARY_MIN_NEG",
                notes="Boundary check",
            )
            session.add(att)
            await session.flush()
            session.add(adj)
            await session.flush()

            # Out-of-bounds values (> 10^15 / > 2*10^15 / > 10^17 / < -2*10^15 / -1) REJECTED
            for bad_kw, err_name in (
                ({"estimated_tokens": max_op_sum + 1}, "ck_ai_att_est_tok_bounds"),
                ({"estimated_tokens": -1}, "ck_ai_att_est_tok_nonneg"),
                ({"input_tokens": max_term + 1}, "ck_ai_att_in_tok_bounds"),
                ({"output_tokens": max_term + 1}, "ck_ai_att_out_tok_bounds"),
                ({"manual_settled_tokens": max_op_sum + 1}, "ck_ai_att_man_tok_bounds"),
                ({"late_reported_input_tokens": max_term + 1}, "ck_ai_att_late_in_bounds"),
                ({"late_reported_output_tokens": max_term + 1}, "ck_ai_att_late_out_bounds"),
            ):
                sp_att = await session.begin_nested()
                kwargs = {
                    "reservation_id": res.id,
                    "institution_id": inst_id,
                    "logical_operation_id": res.logical_operation_id,
                    "attempt_sequence": 2,
                    "provider": "gemini",
                    "model": "gemini-test",
                    "status": "DISPATCHED",
                    "pricing_version": pv_id,
                    "estimated_tokens": 100,
                    "estimated_cost_inr": Decimal("0.0100"),
                }
                kwargs.update(bad_kw)
                session.add(AIProviderAttempt(**kwargs))
                with pytest.raises(IntegrityError, match=err_name):
                    await session.flush()
                await sp_att.rollback()

            for delta_val in (max_op_sum + 1, -max_op_sum - 1):
                sp_adj = await session.begin_nested()
                session.add(
                    AIFinancialAdjustment(
                        institution_id=inst_id,
                        reservation_id=res.id,
                        attempt_id=att.id,
                        adjusted_by_actor="ADM",
                        adjustment_type="VARIANCE_DEBIT",
                        token_delta=delta_val,
                        cost_inr_delta=Decimal("0.0000"),
                        adjustment_reason="OVERFLOW_PROBE",
                        notes="Exceeds token_delta bound",
                    )
                )
                with pytest.raises(IntegrityError, match="ck_ai_financial_adjustments_token_delta_bounds"):
                    await session.flush()
                await sp_adj.rollback()

            sp_unc = await session.begin_nested()
            session.add(
                AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    status="UNKNOWN_USAGE",
                    pricing_version=pv_id,
                    estimated_input_tokens=10,
                    reserved_output_tokens=10,
                    total_reserved_tokens=20,
                    reserved_cost_inr=Decimal("0.0010"),
                    uncertain_tokens_held=max_op_sum + 1,
                    dispatched_at=now_ts,
                    expires_at=now_ts + timedelta(minutes=2),
                )
            )
            with pytest.raises(IntegrityError, match="ck_ai_res_unc_tok_bounds"):
                await session.flush()
            await sp_unc.rollback()

            inst2 = uuid.uuid4()
            await _provision_inst_and_user(session, inst2, uuid.uuid4(), "r03-ov2")
            await _set_context(session, inst2, is_platform_admin=True)
            sp_d = await session.begin_nested()
            session.add(
                TenantDailyAIUsage(
                    institution_id=inst2,
                    usage_date=today,
                    committed_total_tokens=max_agg + 1,
                )
            )
            with pytest.raises(IntegrityError, match="ck_tenant_daily_ai_usage_tok_bounds"):
                await session.flush()
            await sp_d.rollback()

            await _setup_rollup_chain(session, inst2, today, category="other_metered")
            sp_c = await session.begin_nested()
            session.add(
                TenantDailyCategoryUsage(
                    institution_id=inst2,
                    usage_date=today,
                    usage_category="ingestion_embeddings",
                    pending_reserved_tokens=max_agg + 1,
                )
            )
            with pytest.raises(IntegrityError, match="ck_tenant_daily_cat_tok_bounds"):
                await session.flush()
            await sp_c.rollback()
        finally:
            await session.close()


# ==============================================================================
# Suite 3: PostgreSQL Role Separation, RLS, Least-Privilege ACL & Bypass Proofs
# ==============================================================================


class TestStage71SecurityRLSAndLeastPrivilege:
    """Tests live PostgreSQL role separation, RLS, ACLs, and anti-escalation under eduintel_app."""

    async def test_runtime_role_separation_acls_and_no_privileged_inheritance(self, db_connection):
        stage7_tables = (
            "ai_pricing_versions",
            "ai_pricing_activations",
            "tenant_ai_quotas",
            "tenant_daily_ai_usage",
            "tenant_daily_category_usage",
            "ai_token_reservations",
            "ai_provider_attempts",
            "ai_financial_adjustments",
        )
        session = _make_session(db_connection)
        try:
            cur_user = (await session.execute(text("SELECT current_user"))).scalar_one()
            assert cur_user == "eduintel_app", f"Tests must run as unprivileged 'eduintel_app', got {cur_user}"

            role_flags = (
                await session.execute(
                    text("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = 'eduintel_app'")
                )
            ).one()
            assert not any(role_flags), f"eduintel_app must be unprivileged, got {role_flags}"

            # Zero inherited or SET ROLE reachable membership in privileged/owner roles
            violations = (
                await session.execute(
                    text(
                        """
                        WITH RECURSIVE role_tree AS (
                            SELECT r.oid, r.rolname, r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
                                   true AS can_inherit, true AS can_set, 0 AS depth
                            FROM pg_roles r WHERE r.rolname = 'eduintel_app'
                            UNION ALL
                            SELECT parent.oid, parent.rolname, parent.rolsuper, parent.rolbypassrls,
                                   parent.rolcreaterole, parent.rolcreatedb,
                                   (rt.can_inherit AND m.inherit_option),
                                   (rt.can_set AND m.set_option),
                                   rt.depth + 1
                            FROM pg_auth_members m
                            JOIN role_tree rt ON m.member = rt.oid
                            JOIN pg_roles parent ON m.roleid = parent.oid
                            WHERE rt.depth < 16
                        )
                        SELECT DISTINCT rt.rolname
                        FROM role_tree rt
                        WHERE rt.depth > 0 AND (rt.can_inherit OR rt.can_set)
                          AND (
                              rt.rolsuper OR rt.rolbypassrls OR rt.rolcreaterole OR rt.rolcreatedb
                              OR rt.rolname IN ('eduintel', 'eduintel_migrator', 'pg_database_owner')
                              OR EXISTS (
                                  SELECT 1 FROM pg_class c
                                  JOIN pg_namespace n ON n.oid = c.relnamespace
                                  WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) = rt.rolname
                              )
                          )
                        """
                    )
                )
            ).fetchall()
            assert not violations, f"eduintel_app must NOT inherit/assume privileged or owner roles: {violations}"

            # Zero Stage 7.1/7.1R tables or security functions owned by eduintel_app
            owned_tables = (
                await session.execute(
                    text(
                        """
                        SELECT c.relname FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public' AND c.relname = ANY(:tbls)
                          AND pg_get_userbyid(c.relowner) = 'eduintel_app'
                        """
                    ),
                    {"tbls": list(stage7_tables)},
                )
            ).fetchall()
            assert not owned_tables, f"Stage 7.1 tables must NOT be owned by eduintel_app: {owned_tables}"

            func_owner = (
                await session.execute(
                    text("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname = 'prevent_finops_immutable_mutation'")
                )
            ).scalar_one()
            assert func_owner != "eduintel_app"

            # PUBLIC has ZERO privileges; eduintel_app strictly least-privileged
            for tbl in stage7_tables:
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    has_pub = (
                        await session.execute(text(f"SELECT has_table_privilege('public', '{tbl}', '{priv}')"))
                    ).scalar_one()
                    assert has_pub is False, f"PUBLIC unexpectedly has {priv} on {tbl}"

            for immutable_tbl in ("ai_pricing_versions", "ai_pricing_activations", "ai_financial_adjustments"):
                for forbidden in ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER"):
                    assert (
                        await session.execute(
                            text(f"SELECT has_table_privilege('eduintel_app', '{immutable_tbl}', '{forbidden}')")
                        )
                    ).scalar_one() is False, f"eduintel_app must NOT hold {forbidden} on {immutable_tbl}"

            for rw_tbl in (
                "tenant_daily_ai_usage",
                "tenant_daily_category_usage",
                "ai_token_reservations",
                "ai_provider_attempts",
            ):
                for forbidden in ("DELETE", "TRUNCATE", "TRIGGER"):
                    assert (
                        await session.execute(text(f"SELECT has_table_privilege('eduintel_app', '{rw_tbl}', '{forbidden}')"))
                    ).scalar_one() is False
        finally:
            await session.close()

    async def test_runtime_cannot_assume_owner_disable_triggers_or_tamper_security_objects(self, db_connection):
        session = _make_session(db_connection)
        try:
            owner_role = (
                await session.execute(
                    text(
                        """
                        SELECT pg_get_userbyid(relowner)
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public' AND c.relname = 'ai_financial_adjustments'
                        """
                    )
                )
            ).scalar_one()

            adversarial_ddl = (
                f"SET LOCAL ROLE {owner_role};",
                "SET LOCAL ROLE eduintel;",
                "ALTER TABLE ai_financial_adjustments DISABLE TRIGGER trg_ai_financial_adjustments_append_only;",
                "ALTER TABLE ai_pricing_versions DISABLE TRIGGER trg_ai_pricing_versions_immutable;",
                "DROP TRIGGER trg_ai_financial_adjustments_append_only ON ai_financial_adjustments;",
                "CREATE OR REPLACE FUNCTION prevent_finops_immutable_mutation() RETURNS TRIGGER AS $$ BEGIN RETURN NEW; END; $$ LANGUAGE plpgsql;",
                "ALTER POLICY tenant_isolation_read_policy ON ai_token_reservations USING (true);",
            )
            for stmt in adversarial_ddl:
                sp = await session.begin_nested()
                with pytest.raises((ProgrammingError, DBAPIError)):
                    await session.execute(text(stmt))
                await sp.rollback()
        finally:
            await session.close()

    async def test_r02_legacy_agent_tables_sequences_and_default_acls_hardened(self, db_connection):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        session = _make_session(db_connection)
        try:
            legacy_agent_tables = (
                "agent_sessions",
                "agent_session_messages",
                "tool_execution_records",
            )
            # 1. Exact least-privilege ACLs on legacy agent tables: ONLY SELECT, INSERT, UPDATE, DELETE; ZERO PUBLIC grants
            for tbl in legacy_agent_tables:
                for allowed in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert (
                        await session.execute(
                            text(f"SELECT has_table_privilege('eduintel_app', '{tbl}', '{allowed}')")
                        )
                    ).scalar_one() is True
                for forbidden in ("TRUNCATE", "TRIGGER", "REFERENCES"):
                    assert (
                        await session.execute(
                            text(f"SELECT has_table_privilege('eduintel_app', '{tbl}', '{forbidden}')")
                        )
                    ).scalar_one() is False, f"eduintel_app must NOT hold {forbidden} on {tbl}"
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES"):
                    assert (
                        await session.execute(text(f"SELECT has_table_privilege('public', '{tbl}', '{priv}')"))
                    ).scalar_one() is False, f"PUBLIC must hold ZERO grants on {tbl}"

                rls_flags = (
                    await session.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity, pg_get_userbyid(relowner) "
                            "FROM pg_class WHERE relname = :tbl"
                        ),
                        {"tbl": tbl},
                    )
                ).one()
                assert rls_flags[0] is True and rls_flags[1] is True and rls_flags[2] != "eduintel_app"

            # 2. Zero sequence privileges for PUBLIC or eduintel_app across all user sequences
            seqs = (
                await session.execute(
                    text(
                        """
                        SELECT n.nspname, c.relname, pg_get_userbyid(c.relowner)
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind = 'S' AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
                        """
                    )
                )
            ).fetchall()
            assert any(r[1] == "ai_pricing_activations_activation_seq_seq" for r in seqs)
            for schema_n, seq_n, owner_n in seqs:
                assert owner_n != "eduintel_app"
                for role_n in ("public", "eduintel_app"):
                    for s_priv in ("USAGE", "SELECT", "UPDATE"):
                        assert (
                            await session.execute(
                                text(f"SELECT has_sequence_privilege('{role_n}', '{schema_n}.{seq_n}', '{s_priv}')")
                            )
                        ).scalar_one() is False, f"{role_n} must NOT hold {s_priv} on {schema_n}.{seq_n}"

            # 3. Zero unsafe pg_default_acl grants to eduintel_app or PUBLIC; enforce function protected
            bad_defs = (
                await session.execute(
                    text(
                        """
                        SELECT d.defaclacl::text
                        FROM pg_catalog.pg_default_acl d
                        WHERE d.defaclacl::text ~ '(eduintel_app=|(^|[{,])=)'
                        """
                    )
                )
            ).fetchall()
            assert not bad_defs, f"Unexpected pg_default_acl grants remained: {bad_defs}"

            fn_owner = (
                await session.execute(
                    text("SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname = 'enforce_ai_pricing_activation_seq'")
                )
            ).scalar_one()
            assert fn_owner != "eduintel_app"
            assert (
                await session.execute(
                    text(
                        "SELECT has_function_privilege('eduintel_app', 'enforce_ai_pricing_activation_seq()', 'EXECUTE')"
                    )
                )
            ).scalar_one() is False

            # 4. Adversarial runtime attacks fail closed under eduintel_app
            for bad_sql in (
                "TRUNCATE TABLE agent_sessions;",
                "TRUNCATE TABLE agent_sessions CASCADE;",
                "TRUNCATE TABLE agent_session_messages;",
                "TRUNCATE TABLE tool_execution_records;",
                "CREATE TRIGGER rogue_trig AFTER INSERT ON agent_sessions FOR EACH ROW EXECUTE FUNCTION prevent_finops_immutable_mutation();",
                "CREATE TEMP TABLE rogue_fk_probe(sid uuid REFERENCES agent_sessions(id));",
                "SELECT setval('ai_pricing_activations_activation_seq_seq', 888);",
                "SELECT nextval('ai_pricing_activations_activation_seq_seq');",
                "SELECT currval('ai_pricing_activations_activation_seq_seq');",
            ):
                sp_bad = await session.begin_nested()
                with pytest.raises((ProgrammingError, DBAPIError)):
                    await session.execute(text(bad_sql))
                await sp_bad.rollback()

            # 5. Legitimate session/message/tool DML operations still succeed under eduintel_app
            await _set_context(session, inst_id, is_platform_admin=False)
            await _provision_inst_and_user(session, inst_id, user_id, "r02-ops")
            sess_id = uuid.uuid4()
            sess = AgentSession(
                id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                agent_name="portal_assistant",
                title="R-02 Live Check",
            )
            msg = AgentSessionMessage(
                institution_id=inst_id,
                session_id=sess_id,
                turn_id=1,
                role="user",
                content="Hello",
                status="COMPLETED",
            )
            tool_rec = ToolExecutionRecord(
                institution_id=inst_id,
                session_id=str(sess_id),
                turn_id=1,
                tool_call_id="tc-1",
                tool_name="lookup_attendance",
                arguments_hash="a" * 64,
                status="COMPLETED",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            session.add_all([sess, msg, tool_rec])
            await session.flush()

            sess.title = "Updated Title"
            await session.flush()
            await session.delete(tool_rec)
            await session.delete(sess)
            await session.flush()
        finally:
            await session.close()

    async def test_append_only_immutable_and_truncate_protections(self, db_connection):
        inst_a = uuid.uuid4()
        user_a = uuid.uuid4()
        pv_id = f"test-immut-{uuid.uuid4().hex[:8]}"
        today = date.today()
        res_a_id = uuid.uuid4()
        adj_a_id = uuid.uuid4()
        act_id = uuid.uuid4()
        now_ts = datetime.now(UTC)

        session = _make_session(db_connection)
        try:
            await _set_context(session, inst_a, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_a, user_a, "immut")
            await _create_pricing_version(session, pv_id)
            session.add(
                AIPricingActivation(
                    id=act_id,
                    pricing_version=pv_id,
                    activated_by_actor="ADMIN",
                    activation_reason="IMMUT_TEST",
                )
            )
            await _setup_rollup_chain(session, inst_a, today)
            session.add(
                AITokenReservation(
                    id=res_a_id,
                    institution_id=inst_a,
                    user_id=user_a,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="rag/query",
                    status="COMMITTED",
                    dispatched_at=now_ts,
                    reconciled_at=now_ts,
                    pricing_version=pv_id,
                    estimated_input_tokens=10,
                    reserved_output_tokens=20,
                    total_reserved_tokens=30,
                    reserved_cost_inr=Decimal("0.0010"),
                    expires_at=now_ts + timedelta(minutes=2),
                )
            )
            await session.flush()
            session.add(
                AIFinancialAdjustment(
                    id=adj_a_id,
                    institution_id=inst_a,
                    reservation_id=res_a_id,
                    adjusted_by_actor="SYSTEM_TEST",
                    adjustment_type="VARIANCE_DEBIT",
                    token_delta=10,
                    cost_inr_delta=Decimal("0.0010"),
                    adjustment_reason="TEST_IMMUT",
                    notes="Immutable entry",
                )
            )
            await session.flush()

            blocked_dml = (
                ("UPDATE ai_financial_adjustments SET notes = 'TAMPERED' WHERE id = :id", {"id": str(adj_a_id)}),
                ("DELETE FROM ai_financial_adjustments WHERE id = :id", {"id": str(adj_a_id)}),
                ("TRUNCATE TABLE ai_financial_adjustments", {}),
                ("UPDATE ai_pricing_versions SET usd_to_inr_rate = 1.0 WHERE version_id = :id", {"id": pv_id}),
                ("DELETE FROM ai_pricing_versions WHERE version_id = :id", {"id": pv_id}),
                ("TRUNCATE TABLE ai_pricing_versions CASCADE", {}),
                ("UPDATE ai_pricing_activations SET activation_reason = 'HACK' WHERE id = :id", {"id": str(act_id)}),
                ("DELETE FROM ai_pricing_activations WHERE id = :id", {"id": str(act_id)}),
                ("TRUNCATE TABLE ai_pricing_activations", {}),
                ("DELETE FROM tenant_daily_ai_usage WHERE institution_id = :id", {"id": str(inst_a)}),
                ("DELETE FROM tenant_daily_category_usage WHERE institution_id = :id", {"id": str(inst_a)}),
                ("DELETE FROM ai_token_reservations WHERE id = :id", {"id": str(res_a_id)}),
                ("DELETE FROM ai_provider_attempts WHERE reservation_id = :id", {"id": str(res_a_id)}),
            )
            for sql, params in blocked_dml:
                sp = await session.begin_nested()
                with pytest.raises((ProgrammingError, DBAPIError)):
                    await session.execute(text(sql), params)
                await sp.rollback()
        finally:
            await session.close()

    async def test_cross_tenant_rls_isolation_platform_admin_and_missing_context(self, db_connection):
        inst_a = uuid.uuid4()
        inst_b = uuid.uuid4()
        user_a = uuid.uuid4()
        pv_id = f"test-pv-{uuid.uuid4().hex[:8]}"
        today = date.today()
        now_ts = datetime.now(UTC)

        session = _make_session(db_connection)
        try:
            # Provision fixtures & pricing version
            await _set_context(session, None, is_platform_admin=True)
            await _provision_inst_and_user(session, inst_a, user_a, "rls-a")
            session.add(Institution(id=inst_b, name="RLS B", slug=f"rls-b-{inst_b.hex[:8]}", is_active=True))
            await _create_pricing_version(session, pv_id)
            await session.flush()

            # Tenant A creates complete graph (proving FK insert into ai_pricing_versions works without UPDATE ACL)
            await _set_context(session, inst_a, is_platform_admin=False)
            quota_a_id = uuid.uuid4()
            res_a_id = uuid.uuid4()
            att_a_id = uuid.uuid4()
            adj_a_id = uuid.uuid4()

            session.add(
                TenantAIQuota(
                    id=quota_a_id,
                    institution_id=inst_a,
                    quota_timezone="Asia/Kolkata",
                    daily_interactive_token_limit=100000,
                    daily_ingestion_token_limit=50000,
                    daily_other_token_limit=10000,
                    daily_exposure_limit_inr=Decimal("100.0000"),
                    pending_reserve_cap_percent=Decimal("0.2000"),
                    max_tokens_per_request=4096,
                    missing_usage_policy="HEURISTIC_HOLD_UNKNOWN",
                    tier_name="pilot",
                )
            )
            daily_a, cat_a = await _setup_rollup_chain(session, inst_a, today)
            res_a = AITokenReservation(
                id=res_a_id,
                institution_id=inst_a,
                user_id=user_a,
                logical_operation_id=uuid.uuid4(),
                usage_date=today,
                usage_category="interactive_ai",
                endpoint="portal-assistant/generate",
                status="DISPATCHED",
                dispatched_at=now_ts,
                pricing_version=pv_id,
                estimated_input_tokens=100,
                reserved_output_tokens=200,
                total_reserved_tokens=300,
                reserved_cost_inr=Decimal("0.0150"),
                expires_at=now_ts + timedelta(minutes=2),
            )
            session.add(res_a)
            await session.flush()

            att_a = AIProviderAttempt(
                id=att_a_id,
                reservation_id=res_a_id,
                institution_id=inst_a,
                logical_operation_id=res_a.logical_operation_id,
                attempt_sequence=1,
                provider="gemini",
                model="gemini-test",
                status="DISPATCHED",
                pricing_version=pv_id,
                estimated_tokens=300,
                estimated_cost_inr=Decimal("0.0150"),
            )
            session.add(att_a)
            await session.flush()

            session.add(
                AIFinancialAdjustment(
                    id=adj_a_id,
                    institution_id=inst_a,
                    reservation_id=res_a_id,
                    attempt_id=att_a_id,
                    adjusted_by_actor="SYSTEM_TEST",
                    adjustment_type="LATE_SETTLEMENT",
                    token_delta=50,
                    cost_inr_delta=Decimal("0.0020"),
                    adjustment_reason="LATE_WEBHOOK",
                    notes="Test adjustment entry",
                )
            )
            await session.flush()

            # Tenant B context: zero visibility & zero cross-tenant writes across all 6 tables
            await _set_context(session, inst_b, is_platform_admin=False)
            assert (await session.execute(select(TenantAIQuota).where(TenantAIQuota.id == quota_a_id))).scalar_one_or_none() is None
            assert (await session.execute(select(TenantDailyAIUsage).where(TenantDailyAIUsage.id == daily_a.id))).scalar_one_or_none() is None
            assert (await session.execute(select(TenantDailyCategoryUsage).where(TenantDailyCategoryUsage.id == cat_a.id))).scalar_one_or_none() is None
            assert (await session.execute(select(AITokenReservation).where(AITokenReservation.id == res_a_id))).scalar_one_or_none() is None
            assert (await session.execute(select(AIProviderAttempt).where(AIProviderAttempt.id == att_a_id))).scalar_one_or_none() is None
            assert (await session.execute(select(AIFinancialAdjustment).where(AIFinancialAdjustment.id == adj_a_id))).scalar_one_or_none() is None

            assert (await session.execute(update(AITokenReservation).where(AITokenReservation.id == res_a_id).values(endpoint="hijack"))).rowcount == 0
            assert (await session.execute(update(TenantAIQuota).where(TenantAIQuota.id == quota_a_id).values(is_unlimited=True))).rowcount == 0
            assert (await session.execute(update(TenantDailyAIUsage).where(TenantDailyAIUsage.id == daily_a.id).values(version=99))).rowcount == 0
            assert (await session.execute(update(TenantDailyCategoryUsage).where(TenantDailyCategoryUsage.id == cat_a.id).values(committed_total_tokens=99))).rowcount == 0
            assert (await session.execute(update(AIProviderAttempt).where(AIProviderAttempt.id == att_a_id).values(input_tokens=99))).rowcount == 0
            assert (await session.execute(text("DELETE FROM tenant_ai_quotas WHERE id = :id"), {"id": str(quota_a_id)})).rowcount == 0

            sp_spoof = await session.begin_nested()
            session.add(
                TenantAIQuota(
                    institution_id=inst_a,
                    quota_timezone="UTC",
                    daily_interactive_token_limit=1,
                    daily_ingestion_token_limit=1,
                    daily_other_token_limit=1,
                    daily_exposure_limit_inr=Decimal("1.0000"),
                    pending_reserve_cap_percent=Decimal("0.1000"),
                    max_tokens_per_request=100,
                    missing_usage_policy="HOLD_UNKNOWN",
                    tier_name="spoof",
                )
            )
            with pytest.raises((ProgrammingError, DBAPIError)):
                await session.flush()
            await sp_spoof.rollback()

            # Tenant B CAN read global pricing version, CANNOT insert new pricing version
            pv_read = (await session.execute(select(AIPricingVersion).where(AIPricingVersion.version_id == pv_id))).scalar_one_or_none()
            assert pv_read is not None and pv_read.usd_to_inr_rate == Decimal("85.5000")

            sp_pv = await session.begin_nested()
            session.add(
                AIPricingVersion(
                    version_id=f"spoof-pv-{uuid.uuid4().hex[:8]}",
                    currency="INR",
                    usd_to_inr_rate=Decimal("1.0000"),
                    rate_source="SPOOF",
                    rates_json={},
                    effective_from=now_ts,
                )
            )
            with pytest.raises((ProgrammingError, DBAPIError)):
                await session.flush()
            await sp_pv.rollback()

            # Platform Admin read/write split (app.is_platform_admin='true', bound to inst_b):
            # cross-tenant SELECT works across all 6 tenant tables, cross-tenant WRITE/DELETE blocked!
            await _set_context(session, inst_b, is_platform_admin=True)
            assert (await session.execute(select(TenantAIQuota).where(TenantAIQuota.id == quota_a_id))).scalar_one_or_none() is not None
            assert (await session.execute(select(TenantDailyAIUsage).where(TenantDailyAIUsage.id == daily_a.id))).scalar_one_or_none() is not None
            assert (await session.execute(select(TenantDailyCategoryUsage).where(TenantDailyCategoryUsage.id == cat_a.id))).scalar_one_or_none() is not None
            assert (await session.execute(select(AITokenReservation).where(AITokenReservation.id == res_a_id))).scalar_one_or_none() is not None
            assert (await session.execute(select(AIProviderAttempt).where(AIProviderAttempt.id == att_a_id))).scalar_one_or_none() is not None
            assert (await session.execute(select(AIFinancialAdjustment).where(AIFinancialAdjustment.id == adj_a_id))).scalar_one_or_none() is not None

            assert (await session.execute(update(TenantAIQuota).where(TenantAIQuota.id == quota_a_id).values(is_unlimited=True))).rowcount == 0
            assert (await session.execute(update(TenantDailyAIUsage).where(TenantDailyAIUsage.id == daily_a.id).values(version=88))).rowcount == 0
            assert (await session.execute(update(AITokenReservation).where(AITokenReservation.id == res_a_id).values(endpoint="admin-spoof"))).rowcount == 0
            assert (await session.execute(text("DELETE FROM tenant_ai_quotas WHERE id = :id"), {"id": str(quota_a_id)})).rowcount == 0

            sp_pa_ins = await session.begin_nested()
            session.add(
                AIFinancialAdjustment(
                    institution_id=inst_a,
                    reservation_id=res_a_id,
                    adjusted_by_actor="ADMIN_SPOOF",
                    adjustment_type="REFUND",
                    token_delta=0,
                    cost_inr_delta=Decimal("0.0000"),
                    adjustment_reason="SPOOF",
                    notes="Platform admin must not write cross-tenant",
                )
            )
            with pytest.raises((ProgrammingError, DBAPIError)):
                await session.flush()
            await sp_pa_ins.rollback()

            # Missing tenant context fails closed on reads and writes
            await _set_context(session, None, is_platform_admin=False)
            assert (await session.execute(select(TenantAIQuota).where(TenantAIQuota.id == quota_a_id))).scalar_one_or_none() is None
            assert (await session.execute(select(AITokenReservation).where(AITokenReservation.id == res_a_id))).scalar_one_or_none() is None
            sp_anon = await session.begin_nested()
            session.add(
                TenantAIQuota(
                    institution_id=inst_a,
                    quota_timezone="UTC",
                    daily_interactive_token_limit=100,
                    daily_ingestion_token_limit=100,
                    daily_other_token_limit=100,
                    daily_exposure_limit_inr=Decimal("10.0000"),
                    pending_reserve_cap_percent=Decimal("0.1000"),
                    max_tokens_per_request=500,
                    missing_usage_policy="HOLD_UNKNOWN",
                    tier_name="anon",
                )
            )
            with pytest.raises((ProgrammingError, DBAPIError)):
                await session.flush()
            await sp_anon.rollback()
        finally:
            await session.close()


# ==============================================================================
# Suite 4: Database Uniqueness & Concurrency Foundation Tests (Real PostgreSQL)
# ==============================================================================


class TestStage71ConcurrencyFoundations:
    """Tests PostgreSQL conflict handling across genuinely independent connections."""

    async def test_concurrent_daily_rollup_on_conflict_initialization(self, test_engine):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        today = date.today()

        async with AsyncSession(test_engine, expire_on_commit=False) as setup_sess:
            await _set_context(setup_sess, None, is_platform_admin=True)
            await _provision_inst_and_user(setup_sess, inst_id, user_id, "conc-init")
            await setup_sess.commit()

        async def _init_worker():
            async with AsyncSession(test_engine, expire_on_commit=False) as s:
                await _set_context(s, inst_id)
                await s.execute(
                    text(
                        """
                        INSERT INTO tenant_daily_ai_usage (id, institution_id, usage_date)
                        VALUES (:id, :inst, :dt)
                        ON CONFLICT (institution_id, usage_date) DO NOTHING
                        """
                    ),
                    {"id": str(uuid.uuid4()), "inst": str(inst_id), "dt": today},
                )
                await s.commit()

        await asyncio.gather(*[_init_worker() for _ in range(6)])

        async with AsyncSession(test_engine, expire_on_commit=False) as verify_sess:
            await _set_context(verify_sess, inst_id)
            rows = (
                await verify_sess.execute(
                    select(TenantDailyAIUsage).where(
                        TenantDailyAIUsage.institution_id == inst_id,
                        TenantDailyAIUsage.usage_date == today,
                    )
                )
            ).scalars().all()
            assert len(rows) == 1

    async def test_concurrent_duplicate_idempotency_key_and_attempt_seq_contention(self, test_engine):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        pv_id = f"test-conc-{uuid.uuid4().hex[:8]}"
        today = date.today()
        idem_key = f"turn-{uuid.uuid4().hex[:12]}"

        async with AsyncSession(test_engine, expire_on_commit=False) as setup_sess:
            await _set_context(setup_sess, inst_id, is_platform_admin=True)
            await _provision_inst_and_user(setup_sess, inst_id, user_id, "conc-res")
            await _create_pricing_version(setup_sess, pv_id)
            await _setup_rollup_chain(setup_sess, inst_id, today)
            await setup_sess.commit()

        async def _race_insert_reservation():
            async with AsyncSession(test_engine, expire_on_commit=False) as s:
                await _set_context(s, inst_id)
                res = AITokenReservation(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=user_id,
                    logical_operation_id=uuid.uuid4(),
                    usage_date=today,
                    usage_category="interactive_ai",
                    endpoint="portal-assistant/generate",
                    status="RESERVED",
                    pricing_version=pv_id,
                    estimated_input_tokens=50,
                    reserved_output_tokens=50,
                    total_reserved_tokens=100,
                    reserved_cost_inr=Decimal("0.0050"),
                    idempotency_key=idem_key,
                    expires_at=datetime.now(UTC) + timedelta(minutes=2),
                )
                s.add(res)
                await s.commit()
                return res.id

        results = await asyncio.gather(_race_insert_reservation(), _race_insert_reservation(), return_exceptions=True)
        successes = [r for r in results if isinstance(r, uuid.UUID)]
        errors = [r for r in results if isinstance(r, IntegrityError)]
        assert len(successes) == 1 and len(errors) == 1

        winner_res_id = successes[0]
        async with AsyncSession(test_engine, expire_on_commit=False) as disp_sess:
            await _set_context(disp_sess, inst_id)
            await disp_sess.execute(
                update(AITokenReservation)
                .where(AITokenReservation.id == winner_res_id)
                .values(status="DISPATCHED", dispatched_at=datetime.now(UTC))
            )
            await disp_sess.commit()

        async def _race_insert_attempt():
            async with AsyncSession(test_engine, expire_on_commit=False) as s:
                await _set_context(s, inst_id)
                att = AIProviderAttempt(
                    reservation_id=winner_res_id,
                    institution_id=inst_id,
                    logical_operation_id=uuid.uuid4(),
                    attempt_sequence=1,
                    provider="gemini",
                    model="gemini-test",
                    status="DISPATCHED",
                    pricing_version=pv_id,
                    estimated_tokens=100,
                    estimated_cost_inr=Decimal("0.0050"),
                )
                s.add(att)
                await s.commit()
                return att.id

        att_results = await asyncio.gather(_race_insert_attempt(), _race_insert_attempt(), return_exceptions=True)
        att_ok = [r for r in att_results if isinstance(r, uuid.UUID)]
        att_err = [r for r in att_results if isinstance(r, IntegrityError)]
        assert len(att_ok) == 1 and len(att_err) == 1

    async def test_r01_concurrent_pricing_activations_unique_monotonic_and_reversible(self, test_engine):
        pv_a = f"r01-conc-a-{uuid.uuid4().hex[:6]}"
        pv_b = f"r01-conc-b-{uuid.uuid4().hex[:6]}"

        async with AsyncSession(test_engine, expire_on_commit=False) as setup_sess:
            await _set_context(setup_sess, None, is_platform_admin=True)
            await _create_pricing_version(setup_sess, pv_a, is_active=True)
            await _create_pricing_version(setup_sess, pv_b, is_active=True)
            await setup_sess.commit()

        async def _activate_worker(idx: int) -> int:
            async with AsyncSession(test_engine, expire_on_commit=False) as s:
                await _set_context(s, None, is_platform_admin=True)
                act = AIPricingActivation(
                    pricing_version=pv_a if idx % 2 == 0 else pv_b,
                    activated_by_actor="CONC_TEST",
                    activation_reason=f"SWITCH_{idx}",
                )
                s.add(act)
                await s.commit()
                return act.activation_seq

        seqs = await asyncio.gather(*[_activate_worker(i) for i in range(12)])
        assert len(seqs) == 12
        assert len(set(seqs)) == 12
        assert all(s >= 1 for s in seqs)

        # Deterministic final switch back to pv_a -> latest query selects pv_a
        async with AsyncSession(test_engine, expire_on_commit=False) as tail_sess:
            await _set_context(tail_sess, None, is_platform_admin=True)
            tail = AIPricingActivation(
                pricing_version=pv_a,
                activated_by_actor="CONC_TEST",
                activation_reason="REVERT_A",
            )
            tail_sess.add(tail)
            await tail_sess.commit()
            assert tail.activation_seq > max(seqs)

            latest = (
                await tail_sess.execute(
                    select(AIPricingActivation)
                    .where(AIPricingActivation.pricing_version.in_([pv_a, pv_b]))
                    .order_by(AIPricingActivation.activation_seq.desc())
                    .limit(1)
                )
            ).scalar_one()
            assert latest.pricing_version == pv_a
            assert latest.activation_seq == tail.activation_seq

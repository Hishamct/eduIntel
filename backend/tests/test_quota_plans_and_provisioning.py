"""
Stage 7.4 Test Suite: Subscription AI Quota Plans & Tenant Provisioning Engine
Covers:
- Seeded subscription plans (Starter, Growth, Enterprise, Custom) in database
- Explicit platform-admin tenant provisioning (QuotaProvisioningService)
- Append-only audit trail in tenant_quota_provisioning_logs (immutability trigger)
- Active day plan upgrades (usage conservation without erasing history)
- Tenant AI quota suspension & resumption lifecycle
- Fail-closed behavior for unprovisioned tenants
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.institutions.models import Institution
from app.observability.quota import (
    QuotaProvisioningService,
    ReservationCreateRequest,
    TenantQuotaEngine,
    TenantQuotaNotConfiguredError,
    TenantQuotaSuspendedError,
)
from app.observability.quota_models import (
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
    TenantQuotaProvisioningLog,
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


class TestQuotaPlansAndProvisioning:
    @pytest.mark.asyncio
    async def test_seeded_plans_exist_with_accurate_specifications(self, db_connection):
        session = _make_session(db_connection)
        await _set_admin_ctx(session, None)

        plans = await QuotaProvisioningService.list_plans(session)
        plan_map = {p.plan_id: p for p in plans}

        assert "starter" in plan_map
        assert "growth" in plan_map
        assert "enterprise" in plan_map
        assert "custom" in plan_map

        starter = plan_map["starter"]
        assert starter.daily_financial_ceiling_inr == Decimal("100.0000")
        assert starter.monthly_total_token_limit == 3_000_000
        assert starter.daily_interactive_token_limit == 100_000
        assert starter.daily_ingestion_token_limit == 50_000
        assert starter.daily_other_token_limit == 50_000
        assert starter.risk_reserve_percent == Decimal("0.1000")
        assert starter.max_tokens_per_request == 4096

        growth = plan_map["growth"]
        assert growth.daily_financial_ceiling_inr == Decimal("300.0000")
        assert growth.monthly_total_token_limit == 10_000_000
        assert growth.daily_interactive_token_limit == 300_000
        assert growth.daily_ingestion_token_limit == 200_000
        assert growth.daily_other_token_limit == 100_000
        assert growth.risk_reserve_percent == Decimal("0.1000")
        assert growth.max_tokens_per_request == 8192

        enterprise = plan_map["enterprise"]
        assert enterprise.daily_financial_ceiling_inr == Decimal("750.0000")
        assert enterprise.monthly_total_token_limit == 30_000_000
        assert enterprise.daily_interactive_token_limit == 750_000
        assert enterprise.daily_ingestion_token_limit == 500_000
        assert enterprise.daily_other_token_limit == 250_000
        assert enterprise.risk_reserve_percent == Decimal("0.1000")
        assert enterprise.max_tokens_per_request == 16384

    @pytest.mark.asyncio
    async def test_explicit_tenant_provisioning_and_audit_log(self, db_connection):
        session = _make_session(db_connection)
        inst_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        await _set_admin_ctx(session, inst_id)

        inst = Institution(id=inst_id, name="Provision Test Inst", slug=f"prov-{inst_id.hex[:6]}", is_active=True)
        admin = User(id=admin_id, email=f"admin-{admin_id.hex[:6]}@prov.edu", name="Platform Admin", hashed_password="pw", role="admin", is_platform_admin=True)
        session.add_all([inst, admin])
        await session.flush()

        # Provision Starter Plan
        quota = await QuotaProvisioningService.provision_tenant_quota(
            session,
            institution_id=inst_id,
            plan_id="starter",
            actor_user_id=admin_id,
            change_reason="Initial customer subscription onboarding",
        )

        assert quota.institution_id == inst_id
        assert quota.plan_id == "starter"
        assert quota.daily_exposure_limit_inr == Decimal("100.0000")
        assert quota.risk_reserve_percent == Decimal("0.1000")
        assert quota.is_suspended is False

        # Verify audit log in tenant_quota_provisioning_logs
        stmt = select(TenantQuotaProvisioningLog).where(TenantQuotaProvisioningLog.institution_id == inst_id)
        logs = (await session.execute(stmt)).scalars().all()
        assert len(logs) == 1
        log = logs[0]
        assert log.changed_by_actor == str(admin_id)
        assert log.action == "PROVISION"
        assert log.new_plan_id == "starter"
        assert log.change_reason == "Initial customer subscription onboarding"
        assert log.snapshot_json["daily_financial_ceiling_inr"] == "100.0000"

    @pytest.mark.asyncio
    async def test_provisioning_logs_are_strictly_append_only(self, db_connection):
        session = _make_session(db_connection)
        inst_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        await _set_admin_ctx(session, inst_id)

        inst = Institution(id=inst_id, name="Log Test Inst", slug=f"log-{inst_id.hex[:6]}", is_active=True)
        admin = User(id=admin_id, email=f"admin-{admin_id.hex[:6]}@log.edu", name="Platform Admin", hashed_password="pw", role="admin", is_platform_admin=True)
        session.add_all([inst, admin])
        await session.flush()

        await QuotaProvisioningService.provision_tenant_quota(
            session,
            institution_id=inst_id,
            plan_id="starter",
            actor_user_id=admin_id,
            change_reason="Audit test onboarding",
        )

        stmt = select(TenantQuotaProvisioningLog).where(TenantQuotaProvisioningLog.institution_id == inst_id)
        log = (await session.execute(stmt)).scalars().first()
        assert log is not None

        # Attempting UPDATE must fail due to permission denial or append-only trigger
        log.change_reason = "Tampered reason"
        with pytest.raises(DBAPIError) as exc_info:
            await session.flush()
        err_msg = str(exc_info.value).lower()
        assert "permission denied" in err_msg or "append-only" in err_msg

    @pytest.mark.asyncio
    async def test_plan_upgrade_during_active_day_preserves_usage(self, db_connection):
        session = _make_session(db_connection)
        inst_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        await _set_admin_ctx(session, inst_id)

        inst = Institution(id=inst_id, name="Upgrade Inst", slug=f"up-{inst_id.hex[:6]}", is_active=True)
        admin = User(id=admin_id, email=f"admin-{admin_id.hex[:6]}@up.edu", name="Platform Admin", hashed_password="pw", role="admin", is_platform_admin=True)
        session.add_all([inst, admin])
        await session.flush()

        # 1. Provision Starter Plan
        await QuotaProvisioningService.provision_tenant_quota(
            session,
            institution_id=inst_id,
            plan_id="starter",
            actor_user_id=admin_id,
            change_reason="Starting with Starter",
        )

        # 2. Simulate committed usage on active day
        today = date(2026, 11, 13)
        daily_usage = TenantDailyAIUsage(
            id=uuid.uuid4(),
            institution_id=inst_id,
            usage_date=today,
            committed_cost_inr=Decimal("35.0000"),
            committed_total_tokens=7000,
            pending_reserved_cost_inr=Decimal("0.0000"),
            pending_reserved_tokens=0,
            uncertain_exposure_cost_inr=Decimal("0.0000"),
            uncertain_reserved_tokens=0,
            request_count=10,
        )
        cat_usage = TenantDailyCategoryUsage(
            id=uuid.uuid4(),
            institution_id=inst_id,
            usage_date=today,
            usage_category="interactive_ai",
            committed_input_tokens=5000,
            committed_output_tokens=2000,
            committed_total_tokens=7000,
            pending_reserved_tokens=0,
            uncertain_reserved_tokens=0,
        )
        session.add_all([daily_usage, cat_usage])
        await session.flush()

        # 3. Upgrade to Enterprise Plan
        upgraded_quota = await QuotaProvisioningService.provision_tenant_quota(
            session,
            institution_id=inst_id,
            plan_id="enterprise",
            actor_user_id=admin_id,
            change_reason="Mid-day upgrade to enterprise",
        )

        assert upgraded_quota.plan_id == "enterprise"
        assert upgraded_quota.daily_exposure_limit_inr == Decimal("750.0000")

        # 4. Assert prior usage is completely preserved
        refreshed_daily = (
            await session.execute(
                select(TenantDailyAIUsage).where(
                    TenantDailyAIUsage.institution_id == inst_id,
                    TenantDailyAIUsage.usage_date == today,
                )
            )
        ).scalars().first()
        assert refreshed_daily is not None
        assert refreshed_daily.committed_cost_inr == Decimal("35.0000")
        assert refreshed_daily.committed_total_tokens == 7000

    @pytest.mark.asyncio
    async def test_tenant_suspension_and_resumption_lifecycle(self, db_connection):
        session = _make_session(db_connection)
        inst_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        await _set_admin_ctx(session, inst_id)

        inst = Institution(id=inst_id, name="Suspend Inst", slug=f"susp-{inst_id.hex[:6]}", is_active=True)
        admin = User(id=admin_id, email=f"admin-{admin_id.hex[:6]}@susp.edu", name="Platform Admin", hashed_password="pw", role="admin", is_platform_admin=True)
        session.add_all([inst, admin])
        await session.flush()

        await QuotaProvisioningService.provision_tenant_quota(
            session,
            institution_id=inst_id,
            plan_id="starter",
            actor_user_id=admin_id,
            change_reason="Initial setup",
        )

        # Suspend
        suspended = await QuotaProvisioningService.suspend_tenant_quota(
            session,
            institution_id=inst_id,
            reason="Billing payment default",
            actor_user_id=admin_id,
        )
        assert suspended.is_suspended is True
        assert suspended.suspension_reason == "Billing payment default"

        # Reservation attempts fail closed
        engine = TenantQuotaEngine()
        with pytest.raises(TenantQuotaSuspendedError):
            await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst_id,
                    user_id=admin_id,
                    usage_category="interactive_ai",
                    endpoint="admin_assistant",
                    provider="gemini",
                    model="gemini-2.5-flash",
                    estimated_input_tokens=50,
                    reserved_output_tokens=50,
                    idempotency_key=f"idem-{uuid.uuid4()}",
                ),
                db=session,
            )

        # Resume
        resumed = await QuotaProvisioningService.resume_tenant_quota(
            session,
            institution_id=inst_id,
            reason="Payment received, account restored",
            actor_user_id=admin_id,
        )
        assert resumed.is_suspended is False
        assert resumed.suspension_reason is None

    @pytest.mark.asyncio
    async def test_unprovisioned_tenant_fails_closed(self, db_connection):
        session = _make_session(db_connection)
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        await _set_admin_ctx(session, inst_id)

        inst = Institution(id=inst_id, name="Unprovisioned Inst", slug=f"unprov-{inst_id.hex[:6]}", is_active=True)
        user = User(id=user_id, email=f"user-{user_id.hex[:6]}@unprov.edu", name="Regular User", hashed_password="pw", role="admin")
        session.add_all([inst, user])
        await session.flush()

        engine = TenantQuotaEngine()
        with pytest.raises(TenantQuotaNotConfiguredError):
            await engine.admit_and_reserve(
                ReservationCreateRequest(
                    institution_id=inst_id,
                    user_id=user_id,
                    usage_category="interactive_ai",
                    endpoint="admin_assistant",
                    provider="gemini",
                    model="gemini-2.5-flash",
                    estimated_input_tokens=50,
                    reserved_output_tokens=50,
                    idempotency_key=f"idem-{uuid.uuid4()}",
                ),
                db=session,
            )

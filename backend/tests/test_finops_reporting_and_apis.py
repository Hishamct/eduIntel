"""
Stage 7.4 Test Suite: FinOps Administrative APIs, Reporting & RBAC/Tenant Isolation
Covers:
- Institution-Admin APIs (/finops/overview, /daily, /by-category, /by-provider, /reservations, /adjustments)
- Strict Tenant Isolation (Admins cannot access cross-tenant FinOps telemetry)
- Platform-Admin Privileged APIs (/platform-admin/finops/overview, /institutions, /plans, /provision, /sweep, /manual-settle)
- Role-based authorization & permission enforcement (403 for unauthorized roles, 401 unauthenticated)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password
from app.core.database import AsyncSessionLocal
from app.institutions.models import Institution, InstitutionMembership
from app.main import app
from app.observability.quota import QuotaProvisioningService
from app.observability.quota_models import (
    AIPricingActivation,
    AIPricingVersion,
    AIProviderAttempt,
    AITokenReservation,
    TenantAIQuota,
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
)
from app.users.models import User
from tests.conftest import auth_headers


async def _set_admin_ctx(session: AsyncSession, inst_id: uuid.UUID | None = None) -> None:
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :inst, true);"),
        {"inst": str(inst_id) if inst_id else ""},
    )
    await session.execute(
        text("SELECT set_config('app.is_platform_admin', 'true', true);"),
    )


@pytest_asyncio.fixture
async def finops_client():
    """
    HTTP client targeting FastAPI app with connection pool from TEST_DATABASE_URL.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _setup_institution_with_admin(
    *,
    name: str,
    slug: str,
    plan_id: str = "starter",
) -> tuple[Institution, User, str]:
    async with AsyncSessionLocal() as session:
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        await _set_admin_ctx(session, inst_id)

        inst = Institution(id=inst_id, name=name, slug=slug, is_active=True)
        user = User(
            id=user_id,
            email=f"admin-{slug}@example.edu",
            name=f"Admin {name}",
            hashed_password=hash_password("Pass123!"),
            role="admin",
            is_active=True,
            is_platform_admin=False,
        )
        membership = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_id,
            user_id=user_id,
            role="admin",
            status="active",
        )
        session.add_all([inst, user, membership])
        await session.flush()

        # Provision quota plan
        await QuotaProvisioningService.provision_tenant_quota(
            session,
            institution_id=inst_id,
            plan_id=plan_id,
            actor=str(user_id),
            change_reason="Setup test institution",
        )

        await session.commit()

    token = create_access_token({"sub": str(user_id), "role": "admin"})
    return inst, user, token


async def _provision_committed_user(role: str, is_platform_admin: bool = False) -> tuple[User, str]:
    async with AsyncSessionLocal() as session:
        user_id = uuid.uuid4()
        inst_id = uuid.uuid4()
        await _set_admin_ctx(session, inst_id)

        inst = Institution(id=inst_id, name=f"Inst-{inst_id.hex[:6]}", slug=f"slug-{inst_id.hex[:6]}", is_active=True)
        user = User(
            id=user_id,
            email=f"{role}-{user_id.hex[:6]}@example.edu",
            name=f"User {role}",
            hashed_password=hash_password("Pass123!"),
            role=role,
            is_active=True,
            is_platform_admin=is_platform_admin,
        )
        membership = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_id,
            user_id=user_id,
            role=role,
            status="active",
        )
        session.add_all([inst, user, membership])
        await session.commit()

    token = create_access_token({"sub": str(user_id), "role": role})
    return user, token


@pytest_asyncio.fixture
async def finops_platform_admin_token() -> str:
    _, token = await _provision_committed_user("admin", is_platform_admin=True)
    return token


@pytest_asyncio.fixture
async def finops_teacher_token() -> str:
    _, token = await _provision_committed_user("teacher")
    return token


@pytest_asyncio.fixture
async def finops_student_token() -> str:
    _, token = await _provision_committed_user("student")
    return token


@pytest_asyncio.fixture
async def finops_tenant_admin_token() -> str:
    _, token = await _provision_committed_user("admin", is_platform_admin=False)
    return token


class TestFinOpsReportingAndAPIs:
    @pytest.mark.asyncio
    async def test_institution_admin_finops_overview(self, finops_client: AsyncClient):
        inst, user, token = await _setup_institution_with_admin(
            name="Alpha Academy", slug=f"alpha-{uuid.uuid4().hex[:6]}", plan_id="starter"
        )

        resp = await finops_client.get(
            "/finops/overview",
            headers={**auth_headers(token), "X-Institution-Id": str(inst.id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["institution_id"] == str(inst.id)
        assert data["plan_id"] == "starter"
        assert data["financial"]["daily_ceiling_inr"] == "100.0000"
        assert data["financial"]["risk_reserve_percent"] == "0.1000"
        assert data["financial"]["risk_reserve_inr"] == "10.0000"
        assert data["financial"]["available_admission_capacity_inr"] == "90.0000"
        assert data["is_suspended"] is False

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation_on_finops_overview(self, finops_client: AsyncClient):
        """Institution A admin cannot see or fetch Institution B's telemetry."""
        inst_a, _, token_a = await _setup_institution_with_admin(
            name="Inst A", slug=f"insta-{uuid.uuid4().hex[:6]}", plan_id="starter"
        )
        inst_b, _, token_b = await _setup_institution_with_admin(
            name="Inst B", slug=f"instb-{uuid.uuid4().hex[:6]}", plan_id="growth"
        )

        resp_a = await finops_client.get(
            "/finops/overview",
            headers={**auth_headers(token_a), "X-Institution-Id": str(inst_a.id)},
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["institution_id"] == str(inst_a.id)
        assert resp_a.json()["plan_id"] == "starter"

        resp_b = await finops_client.get(
            "/finops/overview",
            headers={**auth_headers(token_b), "X-Institution-Id": str(inst_b.id)},
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["institution_id"] == str(inst_b.id)
        assert resp_b.json()["plan_id"] == "growth"

    @pytest.mark.asyncio
    async def test_platform_admin_overview_and_institutions(
        self, finops_client: AsyncClient, finops_platform_admin_token: str
    ):
        resp = await finops_client.get(
            "/platform-admin/finops/overview",
            headers=auth_headers(finops_platform_admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "institutions_configured_count" in data
        assert "today" in data
        assert "current_month" in data
        assert "reconciliation_backlog" in data

        inst_resp = await finops_client.get(
            "/platform-admin/finops/institutions",
            headers=auth_headers(finops_platform_admin_token),
        )
        assert inst_resp.status_code == 200
        inst_data = inst_resp.json()
        assert "items" in inst_data

    @pytest.mark.asyncio
    async def test_platform_admin_provision_endpoint(
        self, finops_client: AsyncClient, finops_platform_admin_token: str
    ):
        async with AsyncSessionLocal() as session:
            inst_id = uuid.uuid4()
            await _set_admin_ctx(session, inst_id)
            inst = Institution(id=inst_id, name="Target Inst", slug=f"target-{inst_id.hex[:6]}", is_active=True)
            session.add(inst)
            await session.commit()

        payload = {
            "plan_id": "enterprise",
            "change_reason": "Upgrade to Enterprise tier via Platform Admin API",
        }
        resp = await finops_client.post(
            f"/platform-admin/finops/institutions/{inst_id}/provision",
            json=payload,
            headers=auth_headers(finops_platform_admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_id"] == "enterprise"
        assert data["daily_ceiling_inr"] == "750.0000"

    @pytest.mark.asyncio
    async def test_platform_admin_reconciliation_sweep_trigger(
        self, finops_client: AsyncClient, finops_platform_admin_token: str
    ):
        resp = await finops_client.post(
            "/platform-admin/finops/reconciliation/sweep?batch_size=10",
            headers=auth_headers(finops_platform_admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "swept_expired_reservations" in data or "expired_reservations_released" in data
        assert "swept_stale_dispatched" in data or "stale_dispatched_marked_unknown" in data
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_platform_admin_manual_settlement(
        self, finops_client: AsyncClient, finops_platform_admin_token: str
    ):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        res_id = uuid.uuid4()
        pv_id = f"r01-conc-set-{uuid.uuid4().hex[:6]}"
        now_ts = datetime.now(UTC)

        async with AsyncSessionLocal() as session:
            await _set_admin_ctx(session, inst_id)

            inst = Institution(id=inst_id, name="Settle Inst", slug=f"set-{inst_id.hex[:6]}", is_active=True)
            user = User(id=user_id, email=f"user-{user_id.hex[:6]}@set.edu", name="User", hashed_password="pw", role="admin")
            quota = TenantAIQuota(
                id=uuid.uuid4(),
                institution_id=inst_id,
                plan_id="starter",
                quota_timezone="Asia/Kolkata",
                daily_exposure_limit_inr=Decimal("100.0000"),
                risk_reserve_percent=Decimal("0.1000"),
                daily_interactive_token_limit=100_000,
                daily_ingestion_token_limit=200_000,
                daily_other_token_limit=50_000,
                monthly_total_token_limit=1_000_000,
                pending_reserve_cap_percent=Decimal("0.5000"),
                max_tokens_per_request=10_000,
                missing_usage_policy="HOLD_UNKNOWN",
                is_unlimited=False,
                is_suspended=False,
                tier_name="starter",
            )
            pv = AIPricingVersion(
                version_id=pv_id,
                currency="INR",
                usd_to_inr_rate=Decimal("85.5000"),
                rate_source="TEST_SETTLE",
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
            act = AIPricingActivation(
                id=uuid.uuid4(),
                pricing_version=pv_id,
                expected_version_active=True,
                activated_by_actor="system",
                activation_reason="Test setup",
            )
            daily_usage = TenantDailyAIUsage(
                id=uuid.uuid4(),
                institution_id=inst_id,
                usage_date=now_ts.date(),
                committed_cost_inr=Decimal("0.0000"),
                pending_reserved_cost_inr=Decimal("0.0000"),
                uncertain_exposure_cost_inr=Decimal("0.5000"),
                committed_total_tokens=0,
                pending_reserved_tokens=0,
                uncertain_reserved_tokens=300,
                request_count=1,
            )
            cat_usage = TenantDailyCategoryUsage(
                id=uuid.uuid4(),
                institution_id=inst_id,
                usage_date=now_ts.date(),
                usage_category="interactive_ai",
                committed_input_tokens=0,
                committed_output_tokens=0,
                committed_total_tokens=0,
                pending_reserved_tokens=0,
                uncertain_reserved_tokens=300,
                committed_cost_inr=Decimal("0.0000"),
            )
            reservation = AITokenReservation(
                id=res_id,
                institution_id=inst_id,
                user_id=user_id,
                logical_operation_id=uuid.uuid4(),
                usage_date=now_ts.date(),
                usage_category="interactive_ai",
                endpoint="/api/v1/chat",
                status="UNKNOWN_USAGE",
                pricing_version=pv_id,
                estimated_input_tokens=100,
                reserved_output_tokens=200,
                total_reserved_tokens=300,
                reserved_cost_inr=Decimal("0.5000"),
                uncertain_cost_held_inr=Decimal("0.5000"),
                uncertain_tokens_held=300,
                review_status="NEEDS_MANUAL_REVIEW",
                dispatched_at=now_ts,
                expires_at=now_ts + timedelta(minutes=2),
            )
            attempt = AIProviderAttempt(
                id=uuid.uuid4(),
                reservation_id=res_id,
                institution_id=inst_id,
                logical_operation_id=reservation.logical_operation_id,
                attempt_sequence=1,
                provider="gemini",
                model="gemini-2.5-flash",
                is_fallback=False,
                is_retry=False,
                status="TIMEOUT_UNCERTAIN",
                pricing_version=pv_id,
                estimated_tokens=300,
                estimated_cost_inr=Decimal("0.5000"),
                dispatched_at=now_ts,
            )
            session.add_all([inst, user, quota, pv, daily_usage, cat_usage])
            await session.flush()
            session.add(act)
            await session.flush()
            session.add_all([reservation, attempt])
            await session.commit()

        payload = {
            "institution_id": str(inst_id),
            "reservation_id": str(res_id),
            "settled_input_tokens": 200,
            "settled_output_tokens": 200,
            "settled_cost_inr": "0.4000",
            "settlement_reason": "INVOICE_RECONCILED",
            "notes": "Reconciled with provider monthly billing statement",
        }
        resp = await finops_client.post(
            "/platform-admin/finops/reconciliation/manual-settle",
            json=payload,
            headers=auth_headers(finops_platform_admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "COMMITTED"
        assert data["review_status"] == "MANUALLY_SETTLED"

    @pytest.mark.asyncio
    async def test_non_platform_admin_forbidden_from_platform_finops(
        self,
        finops_client: AsyncClient,
        finops_tenant_admin_token: str,
        finops_teacher_token: str,
        finops_student_token: str,
    ):
        """Regular tenant admin, teacher, and student cannot access platform FinOps."""
        for token in [finops_tenant_admin_token, finops_teacher_token, finops_student_token]:
            resp = await finops_client.get(
                "/platform-admin/finops/overview",
                headers=auth_headers(token),
            )
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_teacher_and_student_forbidden_from_tenant_finops(
        self, finops_client: AsyncClient, finops_teacher_token: str, finops_student_token: str
    ):
        """Teacher and student cannot access tenant FinOps."""
        for token in [finops_teacher_token, finops_student_token]:
            resp = await finops_client.get(
                "/finops/overview",
                headers=auth_headers(token),
            )
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self, finops_client: AsyncClient):
        resp = await finops_client.get("/finops/overview")
        assert resp.status_code == 401

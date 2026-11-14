"""
backend/tests/test_authorization_matrix.py

Grounded Authorization & RBAC Test Matrix:
Covers positive and negative role authorization, cross-tenant isolation boundaries,
platform admin governance, and high-risk API mutations grounded against actual
FastAPI route specifications and dependency graphs.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.institutions.models import Institution, InstitutionMembership
from app.users.models import User
from tests.conftest import auth_headers


@pytest_asyncio.fixture
async def auth_tokens(admin_token: str, teacher_token: str, student_token: str, platform_admin_token: str):
    """Aggregates all role tokens in an async-safe dictionary fixture."""
    return {
        "admin": admin_token,
        "teacher": teacher_token,
        "student": student_token,
        "platform_admin": platform_admin_token,
    }


# -----------------------------------------------------------------------------
# 1. Platform Admin Governance Matrix
# -----------------------------------------------------------------------------
class TestPlatformAdminGovernanceMatrix:
    """Verifies that platform administrative endpoints strictly require is_platform_admin=True."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role_key,expected_status",
        [
            (None, 401),
            ("student", 403),
            ("teacher", 403),
            ("admin", 403),
            ("platform_admin", 200),
        ],
    )
    async def test_list_institutions_governance(
        self, client: AsyncClient, auth_tokens: dict, role_key, expected_status
    ):
        headers = {}
        if role_key:
            headers = auth_headers(auth_tokens[role_key])

        resp = await client.get("/institutions", headers=headers)
        assert resp.status_code == expected_status, (
            f"GET /institutions with {role_key} returned {resp.status_code}, expected {expected_status}. "
            f"Response: {resp.text}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role_key,expected_status",
        [
            (None, 401),
            ("student", 403),
            ("teacher", 403),
            ("admin", 403),
            ("platform_admin", 201),
        ],
    )
    async def test_onboard_institution_governance(
        self, client: AsyncClient, auth_tokens: dict, role_key, expected_status
    ):
        headers = {}
        if role_key:
            headers = auth_headers(auth_tokens[role_key])

        unique_slug = f"matrix-inst-{uuid.uuid4().hex[:6]}"
        payload = {
            "name": f"Matrix Academy {unique_slug}",
            "slug": unique_slug,
            "admin_email": f"admin-{unique_slug}@example.com",
            "admin_name": "Matrix Admin",
            "contact_email": f"contact-{unique_slug}@example.com",
        }

        resp = await client.post("/institutions", json=payload, headers=headers)
        assert resp.status_code == expected_status, (
            f"POST /institutions with {role_key} returned {resp.status_code}, expected {expected_status}. "
            f"Response: {resp.text}"
        )
        if expected_status == 201:
            data = resp.json()
            assert data["slug"] == unique_slug
            assert "activation_token" in data

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role_key,expected_status",
        [
            (None, 401),
            ("student", 403),
            ("teacher", 403),
            ("admin", 403),
            ("platform_admin", 200),
        ],
    )
    async def test_patch_institution_status_governance(
        self, client: AsyncClient, auth_tokens: dict, role_key, expected_status
    ):
        target_id = "00000000-0000-0000-0000-000000000001"
        headers = {}
        if role_key:
            headers = auth_headers(auth_tokens[role_key])

        payload = {"is_active": True}
        resp = await client.patch(f"/institutions/{target_id}/status", json=payload, headers=headers)
        assert resp.status_code == expected_status, (
            f"PATCH /institutions/{target_id}/status with {role_key} returned {resp.status_code}, "
            f"expected {expected_status}."
        )


# -----------------------------------------------------------------------------
# 2. Academic Domain Role & Route Boundaries
# -----------------------------------------------------------------------------
class TestAcademicDomainRoleBoundaries:
    """Verifies positive role acceptance and negative role rejection across student, teacher, and admin routers."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path,role_key,expected_status",
        [
            # Student Portal Endpoints
            ("/student/dashboard", None, 401),
            ("/student/dashboard", "student", 200),
            ("/student/dashboard", "teacher", 403),
            ("/student/dashboard", "admin", 403),
            ("/student/homework", None, 401),
            ("/student/homework", "student", 200),
            ("/student/homework", "teacher", 403),
            ("/student/homework", "admin", 403),
            # Teacher Portal Endpoints
            ("/teacher/dashboard", None, 401),
            ("/teacher/dashboard", "teacher", 200),
            ("/teacher/dashboard", "student", 403),
            ("/teacher/dashboard", "admin", 403),
            ("/teacher/homework", None, 401),
            ("/teacher/homework", "teacher", 200),
            ("/teacher/homework", "student", 403),
            ("/teacher/homework", "admin", 403),
            # Admin Portal Endpoints
            ("/admin/dashboard", None, 401),
            ("/admin/dashboard", "admin", 200),
            ("/admin/dashboard", "student", 403),
            ("/admin/dashboard", "teacher", 403),
            ("/admin/timetable", None, 401),
            ("/admin/timetable", "admin", 200),
            ("/admin/timetable", "student", 403),
            ("/admin/timetable", "teacher", 403),
            ("/admin/teachers", None, 401),
            ("/admin/teachers", "admin", 200),
            ("/admin/teachers", "student", 403),
            ("/admin/teachers", "teacher", 403),
            ("/admin/students", None, 401),
            ("/admin/students", "admin", 200),
            ("/admin/students", "student", 403),
            ("/admin/students", "teacher", 403),
        ],
    )
    async def test_role_gated_get_endpoints(
        self, client: AsyncClient, auth_tokens: dict, path, role_key, expected_status
    ):
        headers = {}
        if role_key:
            headers = auth_headers(auth_tokens[role_key])

        resp = await client.get(path, headers=headers)
        assert resp.status_code == expected_status, (
            f"GET {path} with {role_key} returned {resp.status_code}, expected {expected_status}."
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role_key,expected_status",
        [
            (None, 401),
            ("student", 403),
            ("teacher", 403),
            ("admin", 200),
        ],
    )
    async def test_admin_timetable_post_mutation(
        self, client: AsyncClient, auth_tokens: dict, role_key, expected_status
    ):
        headers = {}
        if role_key:
            headers = auth_headers(auth_tokens[role_key])

        payload = {
            "class_section": "10-A",
            "day_of_week": "Monday",
            "period": 1,
            "subject": "Mathematics",
            "teacher_id": None,
        }
        resp = await client.post("/admin/timetable", json=payload, headers=headers)
        assert resp.status_code == expected_status, (
            f"POST /admin/timetable with {role_key} returned {resp.status_code}, expected {expected_status}."
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role_key,expected_status",
        [
            (None, 401),
            ("student", 403),
        ],
    )
    async def test_parent_report_trigger_rejects_student(
        self, client: AsyncClient, auth_tokens: dict, role_key, expected_status
    ):
        dummy_student_id = str(uuid.uuid4())
        headers = {}
        if role_key:
            headers = auth_headers(auth_tokens[role_key])

        resp = await client.post(f"/reports/parent-report/{dummy_student_id}", headers=headers)
        assert resp.status_code == expected_status, (
            f"POST /reports/parent-report with {role_key} returned {resp.status_code}, expected {expected_status}."
        )


# -----------------------------------------------------------------------------
# 3. Cross-Tenant IDOR & Header Isolation Matrix
# -----------------------------------------------------------------------------
class TestCrossTenantIDORBoundaries:
    """Verifies that tenant context resolution fails closed on header spoofing and non-membership."""

    @pytest.mark.asyncio
    async def test_foreign_institution_header_returns_403(
        self, client: AsyncClient, student_token: str
    ):
        """A user belonging strictly to Institution A attempting to claim Institution B via header must get 403."""
        foreign_inst_id = str(uuid.uuid4())
        headers = {
            **auth_headers(student_token),
            "X-Institution-Id": foreign_inst_id,
        }
        resp = await client.get("/student/dashboard", headers=headers)
        assert resp.status_code == 403
        assert "not an active member" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_suspended_institution_blocks_access(
        self, client: AsyncClient, db_connection
    ):
        """Accessing a suspended institution returns 403 explicitly indicating suspension."""
        session = AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        suspended_id = uuid.uuid4()

        # Insert suspended institution
        inst = Institution(
            id=suspended_id,
            name="Suspended Prep School",
            slug=f"suspended-{suspended_id.hex[:6]}",
            is_active=False,
        )
        session.add(inst)
        await session.flush()

        from app.auth.security import create_access_token, hash_password

        # Create user with membership in suspended institution
        user = User(
            email=f"suspended-student-{suspended_id.hex[:6]}@example.com",
            name="Suspended Student",
            hashed_password=hash_password("Pass123!"),
            role="student",
            is_active=True,
            is_platform_admin=False,
        )
        session.add(user)
        await session.flush()

        session.add(
            InstitutionMembership(
                id=uuid.uuid4(),
                institution_id=suspended_id,
                user_id=user.id,
                role="student",
                status="active",
            )
        )
        await session.commit()
        await session.close()

        suspended_token = create_access_token({"sub": str(user.id), "role": "student"})
        headers = {
            **auth_headers(suspended_token),
            "X-Institution-Id": str(suspended_id),
        }
        resp = await client.get("/student/dashboard", headers=headers)
        assert resp.status_code == 403
        assert "suspended" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_invalid_institution_header_format_returns_400(
        self, client: AsyncClient, student_token: str
    ):
        """Malformed UUID in X-Institution-Id fails closed with 400 Bad Request."""
        headers = {
            **auth_headers(student_token),
            "X-Institution-Id": "not-a-valid-uuid-1234",
        }
        resp = await client.get("/student/dashboard", headers=headers)
        assert resp.status_code == 400
        assert "Invalid institution identifier format" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# 4. Public Security & Core Invariant Boundaries
# -----------------------------------------------------------------------------
class TestPublicSecurityBoundaries:
    """Verifies baseline non-authenticated attack surface constraints."""

    @pytest.mark.asyncio
    async def test_health_check_public_accessible(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_public_signup_disabled_sec02(self, client: AsyncClient):
        """SEC-02: Public self-registration must be disabled and return 403 Forbidden."""
        payload = {
            "email": "attacker@evil.com",
            "password": "EvilPassword123!",
            "name": "Attacker",
            "role": "admin",
        }
        resp = await client.post("/auth/signup", json=payload)
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

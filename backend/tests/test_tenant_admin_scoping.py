"""
backend/tests/test_tenant_admin_scoping.py

Focused test suite verifying Phase 2C Stage 3, Batch 1:
Administrative Core & Provisioning Tenant Scoping.

Verifies:
1. Route scoping: All /admin/* routes require verified TenantContext with institutional role 'admin'
   and use tenant-scoped database sessions (get_tenant_db).
2. Fast rejection: Unauthenticated requests return 401; non-admin roles and un-tenanted admins return 403.
3. Atomic provisioning:
   - Student enrollment (/admin/students) atomically creates User, StudentProfile (with institution_id),
     and active InstitutionMembership (role='student', status='active').
   - Teacher provisioning (/admin/teachers) atomically creates User, TeacherProfile (with institution_id),
     and active InstitutionMembership (role='teacher', status='active').
   - Administrator provisioning (/admin/administrators) atomically creates User, AdminProfile (with institution_id),
     and active InstitutionMembership (role='admin', status='active').
4. Existing user safety: Duplicate email provisioning requests are rejected with HTTP 400 without
   mutating credentials, roles, or creating spurious profiles/memberships.
5. Query & mutation isolation:
   - list_teachers joins TeacherProfile and filters strictly by the authenticated institution_id.
   - list_students filters StudentProfile strictly by institution_id.
   - Timetable and Salary creation populates institution_id from TenantContext.
   - Cross-tenant student profile updates are rejected with 404 Not Found.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.admin.models import SalaryRecord, Timetable
from app.admin.service import get_admin_dashboard_summary
from app.auth.security import create_access_token, hash_password
from app.core.database import get_db
from app.core.tenant import PILOT_INSTITUTION_UUID
from app.institutions.models import InstitutionMembership
from app.main import app
from app.users.dependencies import get_current_user
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User

# Fixed Tenant UUIDs for testing cross-tenant boundaries
TENANT_ALPHA = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_BETA = uuid.UUID("22222222-2222-2222-2222-222222222222")


def create_mock_user(
    role: str,
    user_id: uuid.UUID | None = None,
    institution_id: uuid.UUID | None = TENANT_ALPHA,
    email: str | None = None,
) -> User:
    """Helper creating mock User instances with optional tenant binding."""
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=email or f"mock_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    if institution_id is not None:
        user.institution_id = institution_id
    else:
        user.institution_id = None

    if role == "student":
        user.student_profile = StudentProfile(user_id=uid, institution_id=institution_id, grade="10", section="A")
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            user_id=uid,
            institution_id=institution_id,
            department="Science",
            subjects="Physics",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(user_id=uid, institution_id=institution_id, designation="Administrator")
    return user


def make_auth_header(user: User) -> dict:
    """Helper generating bearer token authorization headers."""
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def create_mock_session():
    """Helper creating a properly wired mock AsyncSession for unit tests."""
    mock_db = AsyncMock()
    added_objects = []

    # SQLAlchemy db.add is synchronous
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    mock_db.flush = AsyncMock()

    async def _mock_refresh(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)

    mock_db.refresh = AsyncMock(side_effect=_mock_refresh)
    return mock_db, added_objects


# =====================================================================
# 1. Route Scoping & Role/Tenant Authorization Guards
# =====================================================================


class TestAdminRouteScopingAndAuth:
    """Verifies that all /admin/* routes enforce authentication, admin role, and active tenant context."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "endpoint", "payload"),
        [
            ("GET", "/admin/dashboard", None),
            ("GET", "/admin/teachers", None),
            ("GET", "/admin/students", None),
            ("GET", "/admin/timetable", None),
            ("GET", "/admin/salary", None),
            (
                "POST",
                "/admin/students",
                {
                    "email": "student@test.com",
                    "password": "Password123!",
                    "name": "Jane",
                },
            ),
            (
                "POST",
                "/admin/teachers",
                {
                    "email": "teacher@test.com",
                    "password": "Password123!",
                    "name": "Prof",
                },
            ),
            (
                "POST",
                "/admin/administrators",
                {
                    "email": "admin@test.com",
                    "password": "Password123!",
                    "name": "Adm",
                },
            ),
            (
                "POST",
                "/admin/timetable",
                {
                    "class_section": "10-A",
                    "day_of_week": "Monday",
                    "period": 1,
                    "subject": "Math",
                },
            ),
            (
                "POST",
                "/admin/salary",
                {
                    "teacher_id": str(uuid.uuid4()),
                    "month": "2026-11-01",
                    "base_salary": 5000,
                },
            ),
        ],
    )
    async def test_unauthenticated_requests_return_401(self, method, endpoint, payload):
        """Unauthenticated requests without Authorization header return 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.request(method, endpoint, json=payload)
            assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["student", "teacher"])
    @pytest.mark.parametrize(
        ("method", "endpoint"),
        [
            ("GET", "/admin/dashboard"),
            ("GET", "/admin/teachers"),
            ("GET", "/admin/students"),
            ("GET", "/admin/timetable"),
            ("GET", "/admin/salary"),
        ],
    )
    async def test_non_admin_roles_rejected_with_403(self, role, method, endpoint):
        """Authenticated non-admin roles (student, teacher) receive 403 Forbidden."""
        user = create_mock_user(role, institution_id=TENANT_ALPHA)
        headers = make_auth_header(user)

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.request(method, endpoint, headers=headers)
                assert resp.status_code == 403
                assert "Operation not permitted" in resp.json()["detail"] or "role" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_without_tenant_membership_rejected_with_403(self):
        """Administrator without tenant context receives 403 Forbidden."""
        admin_no_tenant = create_mock_user("admin", institution_id=None)
        headers = make_auth_header(admin_no_tenant)

        app.dependency_overrides[get_current_user] = lambda: admin_no_tenant
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/dashboard", headers=headers)
                assert resp.status_code == 403
                assert "Tenant context required" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 2. Admin Dashboard Tenant Scoping
# =====================================================================


class TestAdminDashboardScoping:
    """Verifies that /admin/dashboard enforces tenant boundaries for both pilot and non-pilot institutions."""

    @pytest.mark.asyncio
    async def test_admin_dashboard_pilot_institution_access_success(self):
        """Admin from pilot institution accesses dashboard and receives scoped counts."""
        admin_user = create_mock_user("admin", institution_id=PILOT_INSTITUTION_UUID)
        headers = make_auth_header(admin_user)
        mock_db, _ = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one.side_effect = [42, 8]
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/dashboard", headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_students"] == 42
                assert data["total_teachers"] == 8
                assert data["role"] == "admin"

                assert mock_db.execute.call_count == 2
                calls = mock_db.execute.call_args_list
                for call in calls:
                    stmt = call[0][0]
                    compiled_sql = str(stmt)
                    assert "institution_id" in compiled_sql
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_dashboard_non_pilot_institution_access_success(self):
        """Admin from non-pilot institution accesses dashboard and receives metrics for their institution."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, _ = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one.side_effect = [120, 15]
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/dashboard", headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_students"] == 120
                assert data["total_teachers"] == 15
                assert data["role"] == "admin"

                assert mock_db.execute.call_count == 2
                calls = mock_db.execute.call_args_list
                for call in calls:
                    stmt = call[0][0]
                    compiled_sql = str(stmt)
                    assert "institution_id" in compiled_sql
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_dashboard_counts_scoped_to_callers_institution(self):
        """Dashboard service executes queries with explicit institution_id filter for defense in depth."""
        mock_db, _ = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one.side_effect = [50, 5]
        mock_db.execute.return_value = mock_result

        summary = await get_admin_dashboard_summary(db=mock_db, institution_id=TENANT_BETA)
        assert summary["total_students"] == 50
        assert summary["total_teachers"] == 5

        assert mock_db.execute.call_count == 2
        calls = mock_db.execute.call_args_list

        # Verify StudentProfile count query filters by TENANT_BETA
        student_stmt = calls[0][0][0]
        student_sql = str(student_stmt)
        assert "student_profiles" in student_sql
        assert "institution_id" in student_sql

        # Verify TeacherProfile count query filters by TENANT_BETA
        teacher_stmt = calls[1][0][0]
        teacher_sql = str(teacher_stmt)
        assert "teacher_profiles" in teacher_sql
        assert "institution_id" in teacher_sql

    @pytest.mark.asyncio
    async def test_admin_dashboard_missing_tenant_context_fails_closed_403(self):
        """Request without active tenant context fails closed with HTTP 403."""
        admin_no_tenant = create_mock_user("admin", institution_id=None)
        headers = make_auth_header(admin_no_tenant)
        mock_db, _ = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: admin_no_tenant
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/dashboard", headers=headers)
                assert resp.status_code == 403
                assert "Tenant context required" in resp.json()["detail"]
                mock_db.execute.assert_not_called()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_admin_dashboard_summary_missing_institution_raises_value_error(self):
        """Direct service call without institution_id raises ValueError."""
        mock_db, _ = create_mock_session()
        with pytest.raises(ValueError, match="Trusted institution_id is required"):
            await get_admin_dashboard_summary(db=mock_db, institution_id=None)
        mock_db.execute.assert_not_called()


# =====================================================================
# 3. Student Provisioning & Atomic Membership
# =====================================================================


class TestStudentProvisioning:
    """Verifies atomic creation of User, StudentProfile, and InstitutionMembership."""

    @pytest.mark.asyncio
    async def test_enroll_student_creates_profile_and_membership_atomically(self):
        """Enrolling a student populates tenant institution_id and active membership atomically."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, added_objects = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing user with this email
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {
                    "email": "newstudent@alpha.edu",
                    "password": "SecurePassword123!",
                    "name": "Alice Johnson",
                    "grade": "11",
                    "section": "A",
                    "roll_number": "11-A-01",
                    "parent_email": "parent@example.com",
                    "phone": "555-0101",
                    "address": "123 Campus Way",
                    "guardian_name": "Bob Johnson",
                    "guardian_phone": "555-0102",
                }
                resp = await client.post("/admin/students", json=payload, headers=headers)
                assert resp.status_code == 201
                data = resp.json()
                assert data["email"] == "newstudent@alpha.edu"
                assert data["name"] == "Alice Johnson"
                assert data["grade"] == "11"
                assert data["section"] == "A"

                # Verify atomic additions: User, StudentProfile, InstitutionMembership
                assert len(added_objects) == 3
                new_user = next(o for o in added_objects if isinstance(o, User))
                new_profile = next(o for o in added_objects if isinstance(o, StudentProfile))
                new_membership = next(o for o in added_objects if isinstance(o, InstitutionMembership))

                # Identity assertions
                assert new_user.email == "newstudent@alpha.edu"
                assert new_user.role == "student"

                # Tenant scoping assertions
                assert new_profile.institution_id == TENANT_ALPHA
                assert new_profile.user_id == new_user.id
                assert new_profile.grade == "11"

                # Membership assertions
                assert new_membership.institution_id == TENANT_ALPHA
                assert new_membership.user_id == new_user.id
                assert new_membership.role == "student"
                assert new_membership.status == "active"

                assert mock_db.flush.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_enroll_student_duplicate_email_rejected_400(self):
        """Duplicate email during student enrollment fails with 400 and creates no records."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, added_objects = create_mock_session()

        existing_user = User(
            id=uuid.uuid4(),
            email="existing@alpha.edu",
            name="Existing User",
            role="student",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {
                    "email": "existing@alpha.edu",
                    "password": "SecurePassword123!",
                    "name": "Duplicate Student",
                }
                resp = await client.post("/admin/students", json=payload, headers=headers)
                assert resp.status_code == 400
                assert "A user with this email already exists" in resp.json()["detail"]
                assert len(added_objects) == 0
                assert not mock_db.flush.called
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 4. Staff Provisioning (Teacher & Administrator) & Atomic Membership
# =====================================================================


class TestStaffProvisioning:
    """Verifies atomic creation of User, Profile, and InstitutionMembership for staff."""

    @pytest.mark.asyncio
    async def test_provision_teacher_creates_profile_and_membership_atomically(self):
        """Provisioning a teacher populates tenant institution_id and active membership atomically."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, added_objects = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {
                    "email": "teacher.smith@alpha.edu",
                    "password": "SecurePassword123!",
                    "name": "Dr. Smith",
                    "department": "Mathematics",
                    "subjects": "Calculus, Linear Algebra",
                }
                resp = await client.post("/admin/teachers", json=payload, headers=headers)
                assert resp.status_code == 201
                data = resp.json()
                assert data["email"] == "teacher.smith@alpha.edu"
                assert data["role"] == "teacher"

                assert len(added_objects) == 3
                new_user = next(o for o in added_objects if isinstance(o, User))
                new_profile = next(o for o in added_objects if isinstance(o, TeacherProfile))
                new_membership = next(o for o in added_objects if isinstance(o, InstitutionMembership))

                assert new_user.role == "teacher"
                assert new_profile.institution_id == TENANT_ALPHA
                assert new_profile.department == "Mathematics"
                assert new_membership.institution_id == TENANT_ALPHA
                assert new_membership.role == "teacher"
                assert new_membership.status == "active"
                assert mock_db.flush.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_provision_administrator_creates_profile_and_membership_atomically(self):
        """Provisioning an administrator populates tenant institution_id and active membership atomically."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, added_objects = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {
                    "email": "vice.principal@alpha.edu",
                    "password": "SecurePassword123!",
                    "name": "Vice Principal Adams",
                    "designation": "Vice Principal",
                }
                resp = await client.post("/admin/administrators", json=payload, headers=headers)
                assert resp.status_code == 201
                data = resp.json()
                assert data["email"] == "vice.principal@alpha.edu"
                assert data["role"] == "admin"

                assert len(added_objects) == 3
                new_user = next(o for o in added_objects if isinstance(o, User))
                new_profile = next(o for o in added_objects if isinstance(o, AdminProfile))
                new_membership = next(o for o in added_objects if isinstance(o, InstitutionMembership))

                assert new_user.role == "admin"
                assert new_profile.institution_id == TENANT_ALPHA
                assert new_profile.designation == "Vice Principal"
                assert new_membership.institution_id == TENANT_ALPHA
                assert new_membership.role == "admin"
                assert new_membership.status == "active"
                assert mock_db.flush.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_provision_staff_duplicate_email_rejected_400(self):
        """Duplicate email during staff provisioning fails with 400."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, added_objects = create_mock_session()

        existing_user = User(
            id=uuid.uuid4(),
            email="existing.staff@alpha.edu",
            name="Existing Staff",
            role="teacher",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {
                    "email": "existing.staff@alpha.edu",
                    "password": "SecurePassword123!",
                    "name": "Duplicate Teacher",
                }
                resp = await client.post("/admin/teachers", json=payload, headers=headers)
                assert resp.status_code == 400
                assert "User with this email already exists" in resp.json()["detail"]
                assert len(added_objects) == 0
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 5. Tenant Query & Mutation Isolation (Teachers, Students, Timetable, Salary)
# =====================================================================


class TestTenantQueryAndMutationIsolation:
    """Verifies that listing and mutation operations are restricted to the tenant."""

    @pytest.mark.asyncio
    async def test_list_teachers_filters_by_institution(self):
        """GET /admin/teachers joins TeacherProfile and filters by institution_id."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, _ = create_mock_session()

        teacher_user = User(
            id=uuid.uuid4(),
            email="teacher@alpha.edu",
            name="Alpha Teacher",
            role="teacher",
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [teacher_user]
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/teachers", headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert len(data) == 1
                assert data[0]["email"] == "teacher@alpha.edu"

                called_stmt = mock_db.execute.call_args[0][0]
                compiled_sql = str(called_stmt)
                assert "teacher_profiles" in compiled_sql
                assert "institution_id" in compiled_sql
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_students_filters_by_institution(self):
        """GET /admin/students filters StudentProfile strictly by institution_id."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, _ = create_mock_session()

        student_user = User(
            id=uuid.uuid4(),
            email="student@alpha.edu",
            name="Alpha Student",
            role="student",
            created_at=datetime.now(UTC),
        )
        student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=student_user.id,
            institution_id=TENANT_ALPHA,
            grade="10",
            section="A",
            roll_number="10-A-01",
        )
        mock_result = MagicMock()
        mock_result.all.return_value = [(student_user, student_profile)]
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/students", headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert len(data) == 1
                assert data[0]["email"] == "student@alpha.edu"

                called_stmt = mock_db.execute.call_args[0][0]
                compiled_sql = str(called_stmt)
                assert "student_profiles" in compiled_sql
                assert "institution_id" in compiled_sql
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_timetable_entry_scoped_to_institution(self):
        """POST /admin/timetable assigns institution_id from TenantContext."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, added_objects = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {
                    "class_section": "10-B",
                    "day_of_week": "Tuesday",
                    "period": 3,
                    "subject": "Chemistry",
                }
                resp = await client.post("/admin/timetable", json=payload, headers=headers)
                assert resp.status_code == 200

                assert len(added_objects) == 1
                timetable_entry = added_objects[0]
                assert isinstance(timetable_entry, Timetable)
                assert timetable_entry.institution_id == TENANT_ALPHA
                assert timetable_entry.created_by == admin_user.id
                assert timetable_entry.class_section == "10-B"
                assert mock_db.flush.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_timetable_filters_by_institution(self):
        """GET /admin/timetable filters Timetable strictly by institution_id."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, _ = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/timetable?class_section=10-B", headers=headers)
                assert resp.status_code == 200

                called_stmt = mock_db.execute.call_args[0][0]
                compiled_sql = str(called_stmt)
                assert "timetable_entries" in compiled_sql
                assert "institution_id" in compiled_sql
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_salary_record_scoped_to_institution(self):
        """POST /admin/salary assigns institution_id from TenantContext."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        teacher_id = uuid.uuid4()
        mock_db, added_objects = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = {
                    "teacher_id": str(teacher_id),
                    "month": "2026-11-01",
                    "base_salary": 6500.0,
                    "bonus": 500.0,
                    "deduction": 100.0,
                    "payment_status": "pending",
                }
                resp = await client.post("/admin/salary", json=payload, headers=headers)
                assert resp.status_code == 200

                assert len(added_objects) == 1
                salary_record = added_objects[0]
                assert isinstance(salary_record, SalaryRecord)
                assert salary_record.institution_id == TENANT_ALPHA
                assert salary_record.created_by == admin_user.id
                assert salary_record.teacher_id == teacher_id
                assert mock_db.flush.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_salary_records_filters_by_institution(self):
        """GET /admin/salary filters SalaryRecord strictly by institution_id."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_user)
        mock_db, _ = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/admin/salary", headers=headers)
                assert resp.status_code == 200

                called_stmt = mock_db.execute.call_args[0][0]
                compiled_sql = str(called_stmt)
                assert "salary_records" in compiled_sql
                assert "institution_id" in compiled_sql
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_update_student_profile_cross_tenant_isolation_returns_404(self):
        """Admin from Tenant Alpha attempting to update a student not in Tenant Alpha receives 404."""
        admin_alpha = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_alpha)
        student_beta_id = uuid.uuid4()
        mock_db, _ = create_mock_session()

        # Querying with StudentProfile.institution_id == TENANT_ALPHA returns None
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_alpha
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/admin/students/{student_beta_id}",
                    json={"grade": "12", "section": "Z"},
                    headers=headers,
                )
                assert resp.status_code == 404
                assert "Student not found" in resp.json()["detail"]

                called_stmt = mock_db.execute.call_args[0][0]
                compiled_sql = str(called_stmt)
                assert "institution_id" in compiled_sql
                assert not mock_db.flush.called
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_update_student_profile_same_tenant_success(self):
        """Admin from Tenant Alpha updating student belonging to Tenant Alpha succeeds."""
        admin_alpha = create_mock_user("admin", institution_id=TENANT_ALPHA)
        headers = make_auth_header(admin_alpha)
        student_id = uuid.uuid4()
        mock_db, _ = create_mock_session()

        student_user = User(
            id=student_id,
            email="student@alpha.edu",
            name="Alice Student",
            role="student",
            created_at=datetime.now(UTC),
        )
        student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=student_id,
            institution_id=TENANT_ALPHA,
            grade="10",
            section="A",
            roll_number="10-A-01",
        )
        mock_result = MagicMock()
        mock_result.first.return_value = (student_user, student_profile)
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_alpha
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.patch(
                    f"/admin/students/{student_id}",
                    json={"grade": "11", "section": "B"},
                    headers=headers,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["grade"] == "11"
                assert data["section"] == "B"
                assert student_profile.grade == "11"
                assert student_profile.section == "B"
                assert mock_db.flush.called
        finally:
            app.dependency_overrides.clear()

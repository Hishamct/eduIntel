"""
tests/test_registration_privilege_escalation.py

Comprehensive test suite verifying SEC-02 remediation:
- Public self-registration lockdown (HTTP 403 Forbidden).
- Authenticated administrator provisioning for students, teachers, and admins (HTTP 201 Created).
- Role-based authorization gates on provisioning endpoints (HTTP 401 / 403).
- Role immutability and mass-assignment protection (extra='forbid' on schemas and PUT /users/me).
- Structured audit logging without credential disclosure.
- Out-of-band administrator bootstrap CLI functionality.

TEST EXECUTION ENVIRONMENT NOTE:
These automated unit and route-contract tests utilize FastAPI ASGITransport with
dependency injection overrides (`app.dependency_overrides`) and AsyncMock session
fixtures. They verify route authorization guards, schema validation (extra='forbid',
password lengths), HTTP status codes, structured audit logging, and service layer logic
without mutating or requiring a live development database. Live PostgreSQL integration
testing with a disposable test database and Alembic migrations is formally scheduled
for Phase 4 (Dedicated Testing Phase).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.database import get_db
from app.main import app
from app.users.dependencies import get_current_user
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User


def create_mock_user(role: str, user_id: uuid.UUID | None = None, email: str | None = None) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=email or f"user_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    if role == "student":
        user.student_profile = StudentProfile(user_id=uid, grade="10", section="A")
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(user_id=uid, department="Science", subjects="Physics")
    elif role == "admin":
        user.admin_profile = AdminProfile(user_id=uid, designation="Administrator")
    return user


def make_auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


class TestPublicSignupLockdown:
    @pytest.mark.asyncio
    async def test_public_signup_disabled_returns_403(self):
        """Verifies that public self-registration is closed and returns 403 Forbidden."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/auth/signup",
                json={
                    "email": "attacker@example.com",
                    "password": "Password123!",
                    "role": "admin",
                },
            )
            assert resp.status_code == 403
            data = resp.json()
            assert "Public registration is disabled" in data["detail"]
            assert "institution administrator" in data["detail"]

    @pytest.mark.asyncio
    async def test_public_signup_empty_payload_returns_403(self):
        """Verifies that any request to /auth/signup is immediately rejected with 403."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/signup", json={})
            assert resp.status_code == 403


class TestAdminProvisioningEndpoints:
    @pytest.mark.asyncio
    async def test_admin_provisions_student_success(self):
        """Verifies authenticated administrator can provision a student account (201 Created)."""
        admin_user = create_mock_user("admin")
        mock_db = AsyncMock()

        # Mock select query returning no existing user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                payload = {
                    "email": "newstudent@example.com",
                    "password": "ValidPassword123!",
                    "name": "Alex Mercer",
                    "grade": "11",
                    "section": "B",
                    "roll_number": "11B-42",
                    "parent_email": "parent@example.com",
                }
                with patch("app.admin.router.logger.info") as mock_logger:
                    resp = await client.post("/admin/students", json=payload, headers=headers)
                    assert resp.status_code == 201
                    data = resp.json()
                    assert data["email"] == "newstudent@example.com"
                    assert data["name"] == "Alex Mercer"
                    assert data["grade"] == "11"
                    assert data["section"] == "B"

                    # Verify structured audit logging
                    mock_logger.assert_called_once()
                    log_format, *log_args = mock_logger.call_args[0]
                    assert "AUDIT: User provisioned" in log_format
                    assert admin_user.id in log_args
                    assert "newstudent@example.com" in log_args
                    assert "student" in log_args
                    # Ensure passwords/secrets are NEVER logged
                    assert "ValidPassword123!" not in str(log_args)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_provisions_teacher_success(self):
        """Verifies authenticated administrator can provision a teacher account (201 Created)."""
        admin_user = create_mock_user("admin")
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                payload = {
                    "email": "newteacher@example.com",
                    "password": "SecurePass123!",
                    "name": "Dr. Sarah Adams",
                    "department": "Mathematics",
                    "subjects": "Calculus, Linear Algebra",
                }
                with patch("app.admin.router.logger.info") as mock_logger:
                    resp = await client.post("/admin/teachers", json=payload, headers=headers)
                    assert resp.status_code == 201
                    data = resp.json()
                    assert data["email"] == "newteacher@example.com"
                    assert data["role"] == "teacher"
                    assert data["is_active"] is True

                    # Verify structured audit logging
                    mock_logger.assert_called_once()
                    log_format, *log_args = mock_logger.call_args[0]
                    assert "AUDIT: User provisioned" in log_format
                    assert "newteacher@example.com" in log_args
                    assert "teacher" in log_args
                    assert "SecurePass123!" not in str(log_args)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_provisions_administrator_success(self):
        """Verifies authenticated administrator can provision an additional administrator (201 Created)."""
        admin_user = create_mock_user("admin")
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                payload = {
                    "email": "newadmin@example.com",
                    "password": "AdminSecurePass123!",
                    "name": "Vice Principal Davis",
                    "designation": "Vice Principal",
                }
                with patch("app.admin.router.logger.info") as mock_logger:
                    resp = await client.post("/admin/administrators", json=payload, headers=headers)
                    assert resp.status_code == 201
                    data = resp.json()
                    assert data["email"] == "newadmin@example.com"
                    assert data["role"] == "admin"
                    assert data["is_active"] is True

                    # Verify structured audit logging
                    mock_logger.assert_called_once()
                    log_format, *log_args = mock_logger.call_args[0]
                    assert "AUDIT: User provisioned" in log_format
                    assert "newadmin@example.com" in log_args
                    assert "admin" in log_args
                    assert "AdminSecurePass123!" not in str(log_args)
        finally:
            app.dependency_overrides.clear()


class TestProvisioningAuthorizationGuards:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ["/admin/students", "/admin/teachers", "/admin/administrators"])
    async def test_unauthenticated_requests_rejected_with_401(self, endpoint):
        """Verifies that unauthenticated callers are rejected with 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                endpoint,
                json={"email": "test@example.com", "password": "Password123!", "name": "Test"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ["/admin/students", "/admin/teachers", "/admin/administrators"])
    async def test_student_rejected_with_403(self, endpoint):
        """Verifies students cannot access provisioning endpoints."""
        student_user = create_mock_user("student")
        app.dependency_overrides[get_current_user] = lambda: student_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.post(
                    endpoint,
                    json={"email": "test@example.com", "password": "Password123!", "name": "Test"},
                    headers=headers,
                )
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ["/admin/students", "/admin/teachers", "/admin/administrators"])
    async def test_teacher_rejected_with_403(self, endpoint):
        """Verifies teachers cannot access provisioning endpoints."""
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post(
                    endpoint,
                    json={"email": "test@example.com", "password": "Password123!", "name": "Test"},
                    headers=headers,
                )
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()


class TestValidationAndMassAssignmentDefenses:
    @pytest.mark.asyncio
    async def test_duplicate_email_rejected_with_400(self):
        """Verifies duplicate email accounts are rejected with 400 Bad Request."""
        admin_user = create_mock_user("admin")
        mock_db = AsyncMock()

        # Mock select query returning an existing user
        existing_user = create_mock_user("student", email="existing@example.com")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_db.execute.return_value = mock_result

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                payload = {
                    "email": "existing@example.com",
                    "password": "ValidPassword123!",
                    "name": "Duplicate Student",
                }
                resp = await client.post("/admin/students", json=payload, headers=headers)
                assert resp.status_code == 400
                assert "already exists" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ["/admin/students", "/admin/teachers", "/admin/administrators"])
    async def test_short_password_rejected_with_422(self, endpoint):
        """Verifies password minimum length (>= 8 characters) is enforced on all provisioning endpoints."""
        admin_user = create_mock_user("admin")
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                payload = {
                    "email": "shortpass@example.com",
                    "password": "short",  # Only 5 chars
                    "name": "Short Pass User",
                }
                resp = await client.post(endpoint, json=payload, headers=headers)
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint", ["/admin/students", "/admin/teachers", "/admin/administrators"])
    async def test_extra_fields_rejected_on_provisioning_with_422(self, endpoint):
        """Verifies mass-assignment protection (extra='forbid') on provisioning schemas."""
        admin_user = create_mock_user("admin")
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                payload = {
                    "email": "injected@example.com",
                    "password": "ValidPassword123!",
                    "name": "Injected Field User",
                    "is_superuser": True,  # Unauthorized extra field
                    "role": "admin",        # Unauthorized extra field
                }
                resp = await client.post(endpoint, json=payload, headers=headers)
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_provisioning_policy_cannot_create_superadmin(self):
        """
        Verifies admin provisioning policy:
        1. An institutional admin can provision a peer institutional admin (role='admin').
        2. Attempting to inject elevated privilege fields (is_platform_admin, role='superadmin')
           is rejected with 422 Unprocessable Entity.
        """
        admin_user = create_mock_user("admin")
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                payload = {
                    "email": "elevated@example.com",
                    "password": "ValidPassword123!",
                    "name": "Elevated User",
                    "is_platform_admin": True,
                }
                resp = await client.post("/admin/administrators", json=payload, headers=headers)
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_put_users_me_rejects_role_escalation_with_422(self):
        """
        Verifies that PUT /users/me forbids extra keys like 'role' or 'is_active',
        preventing privilege escalation via profile update mass assignment.
        """
        student_user = create_mock_user("student")
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: student_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                # Attempt to escalate privileges from student to admin
                escalation_payload = {
                    "grade": "12",
                    "role": "admin",  # Attacker attempt to self-promote
                }
                resp = await client.put("/users/me", json=escalation_payload, headers=headers)
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestBootstrapAdminCLI:
    @pytest.mark.asyncio
    async def test_bootstrap_admin_creates_root_user(self):
        """Verifies out-of-band CLI bootstrap creates active admin user and admin profile."""
        from app.core import bootstrap_admin

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Context manager mock for AsyncSessionLocal
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session

        with patch("app.core.bootstrap_admin.AsyncSessionLocal", return_value=mock_session_cm):
            success = await bootstrap_admin.bootstrap(
                email="rootadmin@eduintel.ai",
                name="Root Administrator",
                password="SuperSecretPassword123!",
            )
            assert success is True
            mock_session.add.assert_called()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_bootstrap_admin_rejects_short_password(self):
        """Verifies CLI bootstrap rejects passwords shorter than 8 characters."""
        from app.core import bootstrap_admin

        success = await bootstrap_admin.bootstrap(
            email="rootadmin@eduintel.ai",
            name="Root Administrator",
            password="short",
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_bootstrap_admin_rejects_duplicate_email(self):
        """Verifies CLI bootstrap rejects already registered email address."""
        from app.core import bootstrap_admin

        existing_user = create_mock_user("admin", email="rootadmin@eduintel.ai")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_session.execute.return_value = mock_result

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session

        with patch("app.core.bootstrap_admin.AsyncSessionLocal", return_value=mock_session_cm):
            success = await bootstrap_admin.bootstrap(
                email="rootadmin@eduintel.ai",
                name="Root Administrator",
                password="SuperSecretPassword123!",
            )
            assert success is False
            mock_session.commit.assert_not_called()

    def test_bootstrap_cli_main_prompts_getpass_and_confirms_success(self):
        """Verifies CLI main uses getpass for non-echoing password prompt and confirmation."""
        from app.core import bootstrap_admin

        test_args = ["bootstrap_admin.py", "--email", "cliadmin@eduintel.ai", "--name", "CLI Administrator"]
        with patch("sys.argv", test_args):
            with patch("getpass.getpass", side_effect=["SecureCliPass123!", "SecureCliPass123!"]) as mock_getpass:
                with patch("app.core.bootstrap_admin.bootstrap", new_callable=AsyncMock) as mock_bootstrap:
                    mock_bootstrap.return_value = True
                    bootstrap_admin.main()
                    assert mock_getpass.call_count == 2
                    mock_bootstrap.assert_called_once_with(
                        "cliadmin@eduintel.ai", "CLI Administrator", "SecureCliPass123!"
                    )

    def test_bootstrap_cli_main_rejects_password_mismatch(self):
        """Verifies CLI main exits with code 1 if password confirmation does not match."""
        from app.core import bootstrap_admin

        test_args = ["bootstrap_admin.py", "--email", "cliadmin@eduintel.ai", "--name", "CLI Administrator"]
        with patch("sys.argv", test_args):
            with patch("getpass.getpass", side_effect=["SecureCliPass123!", "MismatchPass123!"]):
                with pytest.raises(SystemExit) as exc_info:
                    bootstrap_admin.main()
                assert exc_info.value.code == 1

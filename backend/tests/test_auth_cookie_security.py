"""
backend/tests/test_auth_cookie_security.py

Comprehensive test suite verifying SEC-10 remediation:
- Token Storage in LocalStorage (XSS Vulnerability) remediation.
- Backend cookie issuance on POST /auth/login with HttpOnly, SameSite, Path, Max-Age.
- Environment-aware Secure attribute (True in production, local HTTP support in development).
- Cookie clearing on POST /auth/logout with matching security attributes.
- Cookie-based authentication on protected endpoints without Authorization header.
- Dual-mode Bearer token fallback for CLI clients, scripts, and legacy tests.
- Fail-closed behavior on missing, invalid, expired, and tampered credentials.
- Role-based authorization enforcement using cookie authentication.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User


def create_mock_user(
    role: str = "student",
    user_id: uuid.UUID | None = None,
    is_active: bool = True,
    institution_id: str | None = "eduintel-pilot",
) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"test_{role}_{uid.hex[:6]}@example.com",
        name=f"Test {role.capitalize()}",
        hashed_password=hash_password("ValidPassword123!"),
        role=role,
        is_active=is_active,
    )
    if institution_id:
        user.institution_id = institution_id
    if role == "student":
        user.student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=uid,
            grade="10",
            section="A",
            parent_email="parent@example.com",
        )
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            id=uuid.uuid4(),
            user_id=uid,
            subjects="Mathematics",
            department="Science",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(
            id=uuid.uuid4(),
            user_id=uid,
            designation="Principal",
        )
    return user


# =====================================================================
# 1. Cookie Issuance on Login & Security Attributes
# =====================================================================

class TestCookieIssuanceOnLogin:
    """Verifies that POST /auth/login issues HttpOnly, SameSite cookies with proper lifetime."""

    @pytest.mark.asyncio
    async def test_login_sets_httponly_samesite_cookie(self):
        user = create_mock_user("student")
        mock_db = AsyncMock()

        # Mock authenticate_user to return a valid JWT
        test_jwt = create_access_token({"sub": str(user.id), "role": user.role})

        with patch("app.auth.service.authenticate_user", AsyncMock(return_value=test_jwt)):
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.post(
                        "/auth/login",
                        json={"email": user.email, "password": "ValidPassword123!"},
                    )

                    assert res.status_code == 200
                    # Assert cookie exists in response headers
                    cookie_header = res.headers.get("set-cookie", "")
                    assert settings.AUTH_COOKIE_NAME in cookie_header
                    assert "HttpOnly" in cookie_header
                    assert "Path=/" in cookie_header
                    assert f"samesite={settings.AUTH_COOKIE_SAMESITE.lower()}" in cookie_header.lower()
                    assert "Max-Age=" in cookie_header
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_login_cookie_enforces_secure_in_production(self):
        user = create_mock_user("admin")
        test_jwt = create_access_token({"sub": str(user.id), "role": user.role})

        with patch.object(settings, "ENVIRONMENT", "production"), \
             patch.object(settings, "AUTH_COOKIE_SECURE", None):
            with patch("app.auth.service.authenticate_user", AsyncMock(return_value=test_jwt)):
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                try:
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        res = await client.post(
                            "/auth/login",
                            json={"email": user.email, "password": "ValidPassword123!"},
                        )
                        assert res.status_code == 200
                        cookie_header = res.headers.get("set-cookie", "")
                        assert "secure" in cookie_header.lower()
                finally:
                    app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_login_cookie_omits_secure_in_development(self):
        user = create_mock_user("teacher")
        test_jwt = create_access_token({"sub": str(user.id), "role": user.role})

        with patch.object(settings, "ENVIRONMENT", "development"), \
             patch.object(settings, "AUTH_COOKIE_SECURE", None):
            with patch("app.auth.service.authenticate_user", AsyncMock(return_value=test_jwt)):
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                try:
                    transport = ASGITransport(app=app)
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        res = await client.post(
                            "/auth/login",
                            json={"email": user.email, "password": "ValidPassword123!"},
                        )
                        assert res.status_code == 200
                        cookie_header = res.headers.get("set-cookie", "")
                        # In dev, secure is omitted so localhost HTTP functions smoothly
                        assert "secure" not in cookie_header.lower()
                finally:
                    app.dependency_overrides.clear()


# =====================================================================
# 2. Cookie Clearing on Logout
# =====================================================================

class TestCookieClearingOnLogout:
    """Verifies that POST /auth/logout clears the authentication cookie with matching attributes."""

    @pytest.mark.asyncio
    async def test_logout_deletes_cookie(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/auth/logout")

            assert res.status_code == 200
            assert res.json() == {"message": "Successfully logged out"}

            cookie_header = res.headers.get("set-cookie", "")
            assert settings.AUTH_COOKIE_NAME in cookie_header
            assert "HttpOnly" in cookie_header
            # Deletion sets max-age=0 or expires in past
            assert 'max-age=0' in cookie_header.lower() or 'expires=' in cookie_header.lower()


# =====================================================================
# 3. Authenticated Route Access via Cookie vs Bearer Fallback
# =====================================================================

class TestAuthenticationDependencies:
    """Verifies cookie extraction and Bearer fallback in get_current_user."""

    @pytest.mark.asyncio
    async def test_access_protected_route_with_cookie_success(self):
        user = create_mock_user("student")
        token = create_access_token({"sub": str(user.id), "role": user.role})

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_scalar

        with patch("app.users.service.get_user_with_profile", AsyncMock(return_value={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": True,
            "created_at": datetime.now(UTC),
            "profile": {},
        })):
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # Provide token ONLY via cookie, NO Authorization header
                    client.cookies.set(settings.AUTH_COOKIE_NAME, token)
                    res = await client.get("/users/me")

                    assert res.status_code == 200
                    assert res.json()["email"] == user.email
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_access_protected_route_with_bearer_fallback_success(self):
        user = create_mock_user("teacher")
        token = create_access_token({"sub": str(user.id), "role": user.role})

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_scalar

        with patch("app.users.service.get_user_with_profile", AsyncMock(return_value={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": True,
            "created_at": datetime.now(UTC),
            "profile": {},
        })):
            app.dependency_overrides[get_db] = lambda: mock_db
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # Provide token via Authorization: Bearer, NO cookie
                    res = await client.get(
                        "/users/me",
                        headers={"Authorization": f"Bearer {token}"},
                    )

                    assert res.status_code == 200
                    assert res.json()["email"] == user.email
            finally:
                app.dependency_overrides.clear()


# =====================================================================
# 4. Fail-Closed Authentication & Abuse Cases
# =====================================================================

class TestFailClosedAuthentication:
    """Verifies that missing, invalid, expired, or tampered credentials fail closed with 401."""

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_401(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/users/me")
            assert res.status_code == 401
            assert "Could not validate credentials" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_malformed_cookie_returns_401(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(settings.AUTH_COOKIE_NAME, "malformed.token.value")
            res = await client.get("/users/me")
            assert res.status_code == 401
            assert "Could not validate credentials" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_expired_cookie_returns_401(self):
        user = create_mock_user("student")
        # Token expired 1 hour ago
        expired_token = create_access_token(
            {"sub": str(user.id), "role": user.role},
            expires_delta=timedelta(hours=-1),
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(settings.AUTH_COOKIE_NAME, expired_token)
            res = await client.get("/users/me")
            assert res.status_code == 401
            assert "Could not validate credentials" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_tampered_signature_cookie_returns_401(self):
        user = create_mock_user("student")
        valid_token = create_access_token({"sub": str(user.id), "role": user.role})
        # Tamper with signature
        tampered_token = valid_token[:-6] + "xxxxxx"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(settings.AUTH_COOKIE_NAME, tampered_token)
            res = await client.get("/users/me")
            assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_deactivated_user_cookie_returns_401(self):
        inactive_user = create_mock_user("student", is_active=False)
        token = create_access_token({"sub": str(inactive_user.id), "role": inactive_user.role})

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = inactive_user
        mock_db.execute.return_value = mock_scalar

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                client.cookies.set(settings.AUTH_COOKIE_NAME, token)
                res = await client.get("/users/me")
                assert res.status_code == 401
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 5. Role-Based Authorization Enforcement via Cookie
# =====================================================================

class TestRoleBasedAuthorizationWithCookie:
    """Verifies that role checkers (require_role) correctly enforce RBAC with cookies."""

    @pytest.mark.asyncio
    async def test_student_cookie_rejected_from_teacher_route(self):
        student_user = create_mock_user("student")
        token = create_access_token({"sub": str(student_user.id), "role": student_user.role})

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = student_user
        mock_db.execute.return_value = mock_scalar

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                client.cookies.set(settings.AUTH_COOKIE_NAME, token)
                # Attempt to access teacher dashboard route
                res = await client.get("/teacher/dashboard")
                assert res.status_code == 403
                assert "requires one of these roles: teacher" in res.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

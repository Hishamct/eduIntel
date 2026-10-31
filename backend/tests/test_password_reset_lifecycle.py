"""
tests/test_password_reset_lifecycle.py

Comprehensive security and regression tests for SEC-01:
Password Reset Token Disclosure & Lifecycle Security.

Covers:
1. Zero token disclosure in HTTP response bodies (dev_reset_token removed).
2. User enumeration defense (identical 200 responses for registered vs unregistered emails).
3. SHA-256 token hashing at rest in database (never raw tokens).
4. Password reset confirmation with raw token and single-use invalidation.
5. Single-use enforcement rejection on reuse.
6. 30-minute expiration enforcement rejection on expired tokens.
7. Invalid token rejection.
8. Execution of comparable processing paths on missing/inactive accounts.
9. Email background dispatch with frontend reset link format.
10. Configurable FRONTEND_BASE_URL HTTPS validation in production.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.auth.models import PasswordResetToken
from app.auth.security import hash_password, verify_password
from app.auth.service import (
    _hash_token,
    confirm_password_reset,
    request_password_reset,
    send_password_reset_email_background,
)
from app.core.config import Settings, settings
from app.core.database import get_db
from app.core.rate_limiter import password_reset_limiter
from app.main import app
from app.users.models import User

# =====================================================================
# 1. Unit Tests for Service Layer (Cryptographic Token Lifecycle)
# =====================================================================

class TestPasswordResetCryptoLifecycle:
    """Tests SHA-256 hashing at rest, expiration, and single-use enforcement."""

    @pytest.mark.asyncio
    async def test_token_hashed_at_rest_with_sha256(self):
        """Verify that the database stores strictly the 64-char SHA-256 hex digest, never raw token."""
        mock_db = AsyncMock()
        mock_user = User(
            id=uuid.uuid4(),
            email="student@eduintel.ai",
            hashed_password=hash_password("OldPassword123!"),
            role="student",
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        raw_token, recipient_email = await request_password_reset(mock_db, "student@eduintel.ai")

        assert raw_token is not None
        assert recipient_email == "student@eduintel.ai"
        # URL-safe base64 of 32 bytes produces a 43-character string
        assert len(raw_token) == 43

        # Assert record added to database
        assert mock_db.add.called
        added_record = mock_db.add.call_args[0][0]
        assert isinstance(added_record, PasswordResetToken)

        # Stored token must be 64-char SHA-256 hex digest
        assert len(added_record.token) == 64
        expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert added_record.token == expected_hash
        assert added_record.token != raw_token
        assert added_record.used is False
        assert added_record.expires_at > datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_nonexistent_or_inactive_user_returns_none_with_comparable_path(self):
        """Verify that unknown or inactive accounts return (None, None) and execute comparable work."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.auth.service._dummy_hash_computation") as mock_dummy:
            raw_token, email = await request_password_reset(mock_db, "nonexistent@eduintel.ai")
            assert raw_token is None
            assert email is None
            assert mock_dummy.called
            assert not mock_db.add.called

    @pytest.mark.asyncio
    async def test_confirm_reset_success_updates_password_and_marks_used(self):
        """Verify valid raw token confirms reset, marks record as used, and updates password hash."""
        mock_db = AsyncMock()
        raw_token = "valid-test-raw-token-123456789012345"
        token_hash = _hash_token(raw_token)

        mock_user = User(
            id=uuid.uuid4(),
            email="user@eduintel.ai",
            hashed_password=hash_password("OldPassword123!"),
            role="student",
            is_active=True,
        )
        reset_token_record = PasswordResetToken(
            user_id=mock_user.id,
            token=token_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=25),
            used=False,
        )

        # Mock query return for PasswordResetToken, then User
        token_query_result = MagicMock()
        token_query_result.scalar_one_or_none.return_value = reset_token_record

        user_query_result = MagicMock()
        user_query_result.scalar_one_or_none.return_value = mock_user

        mock_db.execute.side_effect = [token_query_result, user_query_result]

        await confirm_password_reset(mock_db, raw_token, "BrandNewPassword123!")

        assert reset_token_record.used is True
        assert verify_password("BrandNewPassword123!", mock_user.hashed_password)
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_confirm_reset_rejection_on_already_used_token(self):
        """Single-use enforcement: re-using a confirmed token must raise ValueError."""
        mock_db = AsyncMock()
        raw_token = "already-used-raw-token"
        token_hash = _hash_token(raw_token)

        reset_token_record = PasswordResetToken(
            user_id=uuid.uuid4(),
            token=token_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=20),
            used=True,  # Already used
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = reset_token_record
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already been used"):
            await confirm_password_reset(mock_db, raw_token, "AnyPassword123!")

    @pytest.mark.asyncio
    async def test_confirm_reset_rejection_on_expired_token(self):
        """Expiration enforcement: token with expires_at in the past must raise ValueError."""
        mock_db = AsyncMock()
        raw_token = "expired-raw-token"
        token_hash = _hash_token(raw_token)

        reset_token_record = PasswordResetToken(
            user_id=uuid.uuid4(),
            token=token_hash,
            expires_at=datetime.now(UTC) - timedelta(minutes=5),  # Expired
            used=False,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = reset_token_record
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="expired"):
            await confirm_password_reset(mock_db, raw_token, "AnyPassword123!")

    @pytest.mark.asyncio
    async def test_confirm_reset_rejection_on_invalid_token(self):
        """Invalid token that does not exist in the database must raise ValueError."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invalid reset token"):
            await confirm_password_reset(mock_db, "nonexistent-token", "AnyPassword123!")


# =====================================================================
# 2. Integration Tests for HTTP Endpoints (Router & Zero Disclosure)
# =====================================================================

class TestPasswordResetHttpRouter:
    """Tests HTTP status codes, payload structure, and absence of dev_reset_token."""

    @pytest.fixture(autouse=True)
    def reset_limiter_fixture(self):
        password_reset_limiter.reset()
        yield
        password_reset_limiter.reset()

    @pytest.mark.asyncio
    async def test_request_reset_zero_token_disclosure_for_existing_user(self):
        """Verify that dev_reset_token is NEVER included in response JSON for an existing user."""
        mock_db = AsyncMock()
        mock_user = User(
            id=uuid.uuid4(),
            email="registered@example.com",
            hashed_password=hash_password("Pass12345!"),
            role="student",
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/auth/password-reset/request",
                json={"email": "registered@example.com"},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "dev_reset_token" not in data
        assert "token" not in data
        assert data["message"] == "If that email is registered, a password reset link has been sent to your email."

    @pytest.mark.asyncio
    async def test_user_enumeration_uniformity(self):
        """Verify that responses are completely identical for registered and unregistered emails."""
        mock_db = AsyncMock()
        mock_user = User(
            id=uuid.uuid4(),
            email="registered@example.com",
            hashed_password=hash_password("Pass12345!"),
            role="student",
            is_active=True,
        )

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Registered email
            res_reg = MagicMock()
            res_reg.scalar_one_or_none.return_value = mock_user
            mock_db.execute.return_value = res_reg

            resp_registered = await client.post(
                "/auth/password-reset/request",
                json={"email": "registered@example.com"},
            )

            # 2. Unregistered email
            res_unreg = MagicMock()
            res_unreg.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = res_unreg

            resp_unregistered = await client.post(
                "/auth/password-reset/request",
                json={"email": "unregistered@example.com"},
            )

        app.dependency_overrides.clear()

        assert resp_registered.status_code == 200
        assert resp_unregistered.status_code == 200
        assert resp_registered.json() == resp_unregistered.json()
        assert "dev_reset_token" not in resp_registered.json()
        assert "dev_reset_token" not in resp_unregistered.json()

    @pytest.mark.asyncio
    async def test_confirm_reset_http_success_and_failure_mappings(self):
        """Verify confirm endpoint maps success to 200 and ValueErrors to HTTP 400 Bad Request."""
        mock_db = AsyncMock()

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Successful confirmation
            with patch("app.auth.service.confirm_password_reset", new_callable=AsyncMock) as mock_confirm:
                mock_confirm.return_value = None
                resp = await client.post(
                    "/auth/password-reset/confirm",
                    json={"token": "valid_token", "new_password": "NewSecurePassword123!"},
                )
                assert resp.status_code == 200
                assert resp.json()["message"] == "Password has been reset successfully."

            # 2. Failed confirmation (e.g. expired token)
            with patch("app.auth.service.confirm_password_reset", new_callable=AsyncMock) as mock_confirm:
                mock_confirm.side_effect = ValueError("This reset token has expired")
                resp = await client.post(
                    "/auth/password-reset/confirm",
                    json={"token": "expired_token", "new_password": "NewSecurePassword123!"},
                )
                assert resp.status_code == 400
                assert resp.json()["detail"] == "This reset token has expired"

        app.dependency_overrides.clear()


# =====================================================================
# 3. Email Dispatch & Base URL Configuration Tests
# =====================================================================

class TestPasswordResetEmailAndConfig:
    """Tests background email dispatch payload and production HTTPS enforcement."""

    def test_background_email_dispatch_includes_configured_url(self):
        """Verify background task constructs valid reset link and dispatches via send_email_direct."""
        captured_emails = []

        def mock_send_email_direct(to_email: str, subject: str, body: str):
            captured_emails.append({"to": to_email, "subject": subject, "body": body})
            return {"status": "sent"}

        raw_token = "raw-sample-token-abc123xyz"
        with patch("app.auth.service.send_email_direct", side_effect=mock_send_email_direct):
            send_password_reset_email_background(raw_token, "parent@eduintel.ai")

        assert len(captured_emails) == 1
        sent = captured_emails[0]
        assert sent["to"] == "parent@eduintel.ai"
        assert "Password Reset Request" in sent["subject"]
        assert f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}" in sent["body"]
        assert "expires in 30 minutes" in sent["body"]

    def test_production_https_validation_on_frontend_base_url(self):
        """Verify that in production mode, non-HTTPS FRONTEND_BASE_URL raises a validation error."""
        # Development mode allows http://
        dev_settings = Settings(
            DATABASE_URL="postgresql+asyncpg://eduintel:eduintel@localhost:5432/eduintel",
            JWT_SECRET_KEY="test_secret_key",
            GEMINI_API_KEY="test_key",
            GROQ_API_KEY="test_key",
            SMTP_HOST="localhost",
            SMTP_USER="test",
            SMTP_PASSWORD="pwd",
            EMAIL_FROM="noreply@eduintel.ai",
            ENVIRONMENT="development",
            FRONTEND_BASE_URL="http://localhost:5173",
        )
        assert dev_settings.FRONTEND_BASE_URL == "http://localhost:5173"

        # Production mode rejects http://
        with pytest.raises(ValidationError, match="FRONTEND_BASE_URL must use HTTPS"):
            Settings(
                DATABASE_URL="postgresql+asyncpg://eduintel:eduintel@localhost:5432/eduintel",
                JWT_SECRET_KEY="test_secret_key",
                GEMINI_API_KEY="test_key",
                GROQ_API_KEY="test_key",
                SMTP_HOST="localhost",
                SMTP_USER="test",
                SMTP_PASSWORD="pwd",
                EMAIL_FROM="noreply@eduintel.ai",
                ENVIRONMENT="production",
                FRONTEND_BASE_URL="http://insecure.eduintel.ai",
            )

        # Production mode accepts https://
        prod_settings = Settings(
            DATABASE_URL="postgresql+asyncpg://eduintel:eduintel@localhost:5432/eduintel",
            JWT_SECRET_KEY="test_secret_key",
            GEMINI_API_KEY="test_key",
            GROQ_API_KEY="test_key",
            SMTP_HOST="localhost",
            SMTP_USER="test",
            SMTP_PASSWORD="pwd",
            EMAIL_FROM="noreply@eduintel.ai",
            ENVIRONMENT="production",
            FRONTEND_BASE_URL="https://app.eduintel.ai",
        )
        assert prod_settings.FRONTEND_BASE_URL == "https://app.eduintel.ai"


# =====================================================================
# 4. Rate Limiting Tests (5 Requests / Minute per IP with Proxy Trust)
# =====================================================================

class TestPasswordResetRateLimiting:
    """
    Tests process-local in-memory sliding window rate limiter with:
    - Normal requests without forwarded headers
    - Trusted proxy forwarded client IP resolution
    - Untrusted source spoofed X-Forwarded-For rejection
    - Malformed forwarded IP handling and fallback
    - Rate limit enforcement (HTTP 429 + Retry-After)
    - Independent rate limit buckets for distinct client IPs
    """

    @pytest.fixture(autouse=True)
    def reset_limiter_fixture(self):
        password_reset_limiter.reset()
        yield
        password_reset_limiter.reset()

    @pytest.mark.asyncio
    async def test_normal_request_without_forwarded_headers(self):
        """Verify normal requests without forwarded headers are rate-limited by client host."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app, client=("198.51.100.10", 45000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 5 allowed requests without forwarded headers
            for i in range(5):
                resp = await client.post(
                    "/auth/password-reset/request",
                    json={"email": "student@eduintel.ai"},
                )
                assert resp.status_code == 200, f"Request {i+1} failed with {resp.status_code}"

            # 6th request from same client host must receive 429
            resp_blocked = await client.post(
                "/auth/password-reset/request",
                json={"email": "student@eduintel.ai"},
            )
            assert resp_blocked.status_code == 429
            assert "Too many password reset requests" in resp_blocked.json()["detail"]
            assert "Retry-After" in resp_blocked.headers

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_requests_from_trusted_proxy_uses_forwarded_client_ip(self):
        """Verify that when the request originates from a trusted proxy (127.0.0.1), forwarded IP is used."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        # Peer is 127.0.0.1 (trusted proxy)
        transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"x-forwarded-for": "203.0.113.88"}
            for _ in range(5):
                resp = await client.post(
                    "/auth/password-reset/request",
                    json={"email": "student@eduintel.ai"},
                    headers=headers,
                )
                assert resp.status_code == 200

            # 6th request with same forwarded IP receives 429
            resp_blocked = await client.post(
                "/auth/password-reset/request",
                json={"email": "student@eduintel.ai"},
                headers=headers,
            )
            assert resp_blocked.status_code == 429
            assert "Retry-After" in resp_blocked.headers

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_untrusted_source_spoofed_forwarded_header_ignored(self):
        """
        Anti-Spoofing: An untrusted client attempting to bypass rate limits by rotating
        X-Forwarded-For headers is tracked by their actual peer IP and blocked.
        """
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        # Peer is an external, untrusted client IP (NOT in TRUSTED_PROXIES)
        transport = ASGITransport(app=app, client=("198.51.100.42", 50000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Attacker rotates X-Forwarded-For header on every request
            for i in range(5):
                resp = await client.post(
                    "/auth/password-reset/request",
                    json={"email": "student@eduintel.ai"},
                    headers={"x-forwarded-for": f"10.0.0.{i+1}"},
                )
                assert resp.status_code == 200

            # 6th request with yet another spoofed IP must be BLOCKED (429)
            # because the limiter tracks the peer IP 198.51.100.42, ignoring the spoofed header!
            resp_blocked = await client.post(
                "/auth/password-reset/request",
                json={"email": "student@eduintel.ai"},
                headers={"x-forwarded-for": "10.0.0.99"},
            )
            assert resp_blocked.status_code == 429
            assert "Too many password reset requests" in resp_blocked.json()["detail"]

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_malformed_forwarded_ip_handled_safely(self):
        """Malformed forwarded IP headers do not create arbitrary buckets and fall back to peer IP."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send malformed non-IP string in X-Forwarded-For
            malformed_headers = {"x-forwarded-for": "not_an_ip; DROP TABLE users; --"}
            resp = await client.post(
                "/auth/password-reset/request",
                json={"email": "student@eduintel.ai"},
                headers=malformed_headers,
            )
            # Request must not crash (returns 200) and bucket must not use arbitrary string
            assert resp.status_code == 200
            assert "not_an_ip; DROP TABLE users; --" not in password_reset_limiter.history
            # Falls back to peer IP (127.0.0.1)
            assert "127.0.0.1" in password_reset_limiter.history

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_independent_rate_limit_buckets_for_legitimate_ips(self):
        """Distinct legitimate client IPs have independent buckets and do not interfere."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        transport_ip1 = ASGITransport(app=app, client=("203.0.113.1", 50000))
        transport_ip2 = ASGITransport(app=app, client=("203.0.113.2", 50000))

        async with AsyncClient(transport=transport_ip1, base_url="http://test") as client1:
            async with AsyncClient(transport=transport_ip2, base_url="http://test") as client2:
                # Exhaust quota for IP 1
                for _ in range(5):
                    resp1 = await client1.post(
                        "/auth/password-reset/request",
                        json={"email": "student@eduintel.ai"},
                    )
                    assert resp1.status_code == 200

                # IP 1 is now rate-limited
                resp1_blocked = await client1.post(
                    "/auth/password-reset/request",
                    json={"email": "student@eduintel.ai"},
                )
                assert resp1_blocked.status_code == 429

                # IP 2 must still be allowed to make requests!
                resp2 = await client2.post(
                    "/auth/password-reset/request",
                    json={"email": "student@eduintel.ai"},
                )
                assert resp2.status_code == 200

        app.dependency_overrides.clear()

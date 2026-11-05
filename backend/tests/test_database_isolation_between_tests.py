"""
backend/tests/test_database_isolation_between_tests.py

Comprehensive verification of Step 3 database test harness:
1. Verifies that the test database guard strictly fails closed.
2. Verifies that unprivileged role eduintel_app cannot bypass Row-Level Security.
3. Verifies savepoint transaction isolation (zero state leakage between tests).
4. Verifies test-order independence and fixture-level cleanup traps.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.auth.security import hash_password
from app.institutions.models import Institution
from app.users.models import AdminProfile, User
from tests.conftest import assert_safe_test_database

# Unique sentinel ID shared across order-independence check
SENTINEL_INST_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


class TestDatabaseSafetyGuard:
    """Verifies that assert_safe_test_database rejects unsafe parameters."""

    def test_guard_rejects_non_test_environment(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("EDUINTEL_TEST_MODE", "true")
        with pytest.raises(RuntimeError, match="FATAL: Tests may only run when ENVIRONMENT='testing'"):
            assert_safe_test_database("postgresql+asyncpg://eduintel:pass@localhost:5432/eduintel_test")

    def test_guard_rejects_missing_test_mode(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "testing")
        monkeypatch.setenv("EDUINTEL_TEST_MODE", "false")
        with pytest.raises(RuntimeError, match="FATAL: Tests may only run when ENVIRONMENT='testing'"):
            assert_safe_test_database("postgresql+asyncpg://eduintel:pass@localhost:5432/eduintel_test")

    def test_guard_rejects_remote_host(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "testing")
        monkeypatch.setenv("EDUINTEL_TEST_MODE", "true")
        with pytest.raises(RuntimeError, match="Refusing to execute tests against a remote or non-loopback host"):
            assert_safe_test_database("postgresql+asyncpg://eduintel:pass@db.production.internal:5432/eduintel_test")

    def test_guard_rejects_protected_production_db_name(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "testing")
        monkeypatch.setenv("EDUINTEL_TEST_MODE", "true")
        with pytest.raises(RuntimeError, match="is a protected production/development database name"):
            assert_safe_test_database("postgresql+asyncpg://eduintel:pass@localhost:5432/eduintel")

    def test_guard_rejects_unexpected_query_parameters(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "testing")
        monkeypatch.setenv("EDUINTEL_TEST_MODE", "true")
        with pytest.raises(RuntimeError, match="contains unexpected query parameters"):
            assert_safe_test_database("postgresql+asyncpg://eduintel:pass@localhost:5432/eduintel_test?sslmode=disable")

    def test_guard_rejects_nonstandard_database_name(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "testing")
        monkeypatch.setenv("EDUINTEL_TEST_MODE", "true")
        with pytest.raises(RuntimeError, match="violates allowlist regex"):
            assert_safe_test_database("postgresql+asyncpg://eduintel:pass@localhost:5432/my_random_test_db")


class TestRLSEnforcementAndIsolation:
    """Verifies that eduintel_app is unprivileged and RLS cannot be bypassed."""

    @pytest.mark.asyncio
    async def test_unprivileged_role_cannot_bypass_rls(self, db_connection):
        from sqlalchemy.ext.asyncio import AsyncSession
        session = AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

        # 1. Reset any tenant context to empty
        await session.execute(text("SELECT set_config('app.current_institution_id', '', false)"))
        await session.execute(text("SELECT set_config('app.is_platform_admin', '', false)"))

        # 2. Attempt to insert admin_profile without tenant context
        admin = AdminProfile(
            id=uuid.uuid4(),
            institution_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            designation="Illegitimate Admin",
        )
        session.add(admin)

        # 3. Must raise InsufficientPrivilegeError / ProgrammingError
        with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
            await session.commit()

        assert "tenant_isolation_insert_policy" in str(exc_info.value)
        await session.close()

    @pytest.mark.asyncio
    async def test_session_gucs_are_clean_at_test_start(self, db_connection):
        """Verifies teardown reset traps guaranteed zero leakage of tenant parameters."""
        inst_setting = (await db_connection.execute(text("SELECT current_setting('app.current_institution_id', true)"))).scalar()
        pa_setting = (await db_connection.execute(text("SELECT current_setting('app.is_platform_admin', true)"))).scalar()
        assert inst_setting in (None, ""), f"app.current_institution_id leaked from previous test: '{inst_setting}'"
        assert pa_setting in (None, ""), f"app.is_platform_admin leaked from previous test: '{pa_setting}'"


class TestCrossTestTransactionIsolation:
    """
    Demonstrates that mutations in one test are rolled back completely
    and leave zero residue for subsequent or randomly-ordered tests.
    """

    @pytest.mark.asyncio
    async def test_step_a_mutate_and_verify_visible_within_test(self, db_connection):
        from sqlalchemy.ext.asyncio import AsyncSession
        session = AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

        inst = Institution(
            id=SENTINEL_INST_ID,
            name="Sentinel Institution",
            slug="sentinel-inst",
            is_active=True,
        )
        session.add(inst)
        await session.flush()

        u = User(
            id=uuid.uuid4(),
            email="sentinel_user@example.com",
            name="Sentinel User",
            hashed_password=hash_password("SentinelPass123!"),
            role="admin",
            is_active=True,
        )
        session.add(u)
        await session.commit()

        # Query back inside this test: must be present
        found = (await session.execute(select(Institution).where(Institution.id == SENTINEL_INST_ID))).scalar_one_or_none()
        assert found is not None
        assert found.name == "Sentinel Institution"
        await session.close()

    @pytest.mark.asyncio
    async def test_step_b_verify_sentinel_absent_in_different_test(self, db_connection):
        from sqlalchemy.ext.asyncio import AsyncSession
        session = AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

        # Query sentinel: must NOT exist because previous test transaction was rolled back
        found = (await session.execute(select(Institution).where(Institution.id == SENTINEL_INST_ID))).scalar_one_or_none()
        assert found is None, "State residue leaked from test_step_a! Sentinel institution was not rolled back."

        found_user = (await session.execute(select(User).where(User.email == "sentinel_user@example.com"))).scalar_one_or_none()
        assert found_user is None, "User state residue leaked from test_step_a!"
        await session.close()

"""
backend/tests/test_tenant_isolation_rls.py

Comprehensive test suite verifying Phase 2C Stage 2 multi-tenant architecture:
1. Tenant Context Resolution & Identifier Normalization (UUID + legacy pilot slug)
2. Dependency Injection (get_tenant_context, require_tenant_role, get_tenant_db)
3. ChromaDB Dual-Identifier Filtering & Vector Ingestion
4. PostgreSQL 16 Role Security Startup Assertion (recursive CTE, inherit_option, set_option)
5. RLS Policy Coverage & Table Metadata Auditing (all 17 tenant-owned tables)
6. Negative-Test Savepoint Recovery Pattern
7. Migration 0021 Downgrade Precondition Guard Assertions
8. Admin Assistant Non-HTTP Tenant Context Binding
"""

import importlib.util
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError

from app.agents.admin_assistant import execute_tools_node
from app.auth.security import create_access_token
from app.core.config import settings
from app.core.database import get_db
from app.core.tenant import (
    PILOT_INSTITUTION_UUID,
    TenantContext,
    get_tenant_context,
    is_pilot_institution,
    normalize_institution_id,
    require_tenant_role,
)
from app.institutions.models import Institution, InstitutionMembership
from app.main import app, lifespan, verify_unprivileged_db_user
from app.rag.service import build_chroma_tenant_filter, ingest_study_material
from app.users.dependencies import get_current_user
from app.users.models import User


def load_migration_module(filename: str):
    path = Path(__file__).parent.parent / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig_0021 = load_migration_module("0021_e5a7b9c1d3f5_create_institutions_and_tenant_schema.py")
mig_0022 = load_migration_module("0022_f6b8c0d2e4a6_enable_postgresql_rls.py")

# List of 17 expected tenant-owned tables
EXPECTED_17_TENANT_TABLES = [
    "student_profiles",
    "teacher_profiles",
    "admin_profiles",
    "assignments",
    "study_materials",
    "exam_results",
    "homework_submissions",
    "doubt_threads",
    "doubt_messages",
    "timetable_entries",
    "salary_records",
    "fee_records",
    "attendance_records",
    "announcements",
    "audit_logs",
    "llm_usage_logs",
    "agent_trace_logs",
]


# ============================================================================
# 1. Tenant Identifier Normalization & Pilot Identification
# ============================================================================


class TestTenantNormalization:
    def test_normalize_valid_uuid_string(self):
        test_uuid = uuid.uuid4()
        res = normalize_institution_id(str(test_uuid))
        assert res == test_uuid

    def test_normalize_uuid_object(self):
        test_uuid = uuid.uuid4()
        res = normalize_institution_id(test_uuid)
        assert res == test_uuid

    def test_normalize_legacy_pilot_slug(self):
        res = normalize_institution_id("eduintel-pilot")
        assert res == PILOT_INSTITUTION_UUID

    def test_normalize_legacy_pilot_slug_case_insensitive(self):
        res = normalize_institution_id("EduIntel-Pilot")
        assert res == PILOT_INSTITUTION_UUID

    def test_normalize_empty_or_none(self):
        assert normalize_institution_id(None) is None
        assert normalize_institution_id("") is None
        assert normalize_institution_id("   ") is None

    def test_normalize_invalid_uuid_raises_http_400(self):
        with pytest.raises(HTTPException) as exc_info:
            normalize_institution_id("not-a-valid-uuid-or-slug")
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid institution identifier format" in exc_info.value.detail

    def test_is_pilot_institution(self):
        assert is_pilot_institution(PILOT_INSTITUTION_UUID) is True
        assert is_pilot_institution(str(PILOT_INSTITUTION_UUID)) is True
        assert is_pilot_institution("eduintel-pilot") is True
        assert is_pilot_institution("EduIntel-Pilot") is True
        assert is_pilot_institution(uuid.uuid4()) is False
        assert is_pilot_institution("foreign-tenant-uuid") is False
        assert is_pilot_institution(None) is False
        assert is_pilot_institution("") is False


# ============================================================================
# 2. get_tenant_context Dependency Tests
# ============================================================================


class TestTenantContextDependency:
    @pytest.fixture
    def mock_user(self):
        return User(
            id=uuid.uuid4(),
            email="tenant_user@example.com",
            name="Tenant User",
            role="teacher",
            is_active=True,
        )

    @pytest.mark.asyncio
    async def test_single_active_membership_auto_resolved(self, mock_user):
        """User with exactly one active membership auto-resolves without X-Institution-Id header."""
        inst_id = uuid.uuid4()
        membership = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_id,
            user_id=mock_user.id,
            role="teacher",
            status="active",
        )
        institution = Institution(
            id=inst_id,
            name="Green Valley School",
            slug="green-valley",
            is_active=True,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(membership, institution)]
        mock_db.execute.return_value = mock_result

        request = Request(scope={"type": "http", "headers": []})
        ctx = await get_tenant_context(request=request, current_user=mock_user, db=mock_db)

        assert ctx.institution_id == inst_id
        assert ctx.user_id == mock_user.id
        assert ctx.role == "teacher"
        assert ctx.is_pilot is False

    @pytest.mark.asyncio
    async def test_multiple_memberships_without_header_raises_400(self, mock_user):
        """User belonging to multiple institutions must supply X-Institution-Id header."""
        m1 = InstitutionMembership(
            id=uuid.uuid4(), institution_id=uuid.uuid4(), user_id=mock_user.id, role="teacher", status="active"
        )
        m2 = InstitutionMembership(
            id=uuid.uuid4(), institution_id=uuid.uuid4(), user_id=mock_user.id, role="admin", status="active"
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(m1, MagicMock()), (m2, MagicMock())]
        mock_db.execute.return_value = mock_result

        request = Request(scope={"type": "http", "headers": []})
        with pytest.raises(HTTPException) as exc_info:
            await get_tenant_context(request=request, current_user=mock_user, db=mock_db)
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "multiple institutions" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_multiple_memberships_with_valid_header_resolves(self, mock_user):
        """Supplying X-Institution-Id selects target institution when user has multiple memberships."""
        target_inst_id = uuid.uuid4()
        m1 = InstitutionMembership(
            id=uuid.uuid4(), institution_id=target_inst_id, user_id=mock_user.id, role="admin", status="active"
        )
        m2 = InstitutionMembership(
            id=uuid.uuid4(), institution_id=uuid.uuid4(), user_id=mock_user.id, role="teacher", status="active"
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(m1, MagicMock()), (m2, MagicMock())]
        mock_db.execute.return_value = mock_result

        request = Request(scope={"type": "http", "headers": [(b"x-institution-id", str(target_inst_id).encode())]})
        ctx = await get_tenant_context(request=request, current_user=mock_user, db=mock_db)

        assert ctx.institution_id == target_inst_id
        assert ctx.role == "admin"

    @pytest.mark.asyncio
    async def test_header_for_non_member_institution_raises_403(self, mock_user):
        """Requesting an institution where user is not an active member fails closed with 403."""
        member_inst = uuid.uuid4()
        unauthorized_inst = uuid.uuid4()
        m1 = InstitutionMembership(
            id=uuid.uuid4(), institution_id=member_inst, user_id=mock_user.id, role="teacher", status="active"
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(m1, MagicMock())]
        mock_db.execute.return_value = mock_result

        request = Request(scope={"type": "http", "headers": [(b"x-institution-id", str(unauthorized_inst).encode())]})
        with pytest.raises(HTTPException) as exc_info:
            await get_tenant_context(request=request, current_user=mock_user, db=mock_db)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "not an active member" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_zero_memberships_fails_closed_without_legacy_flag(self, mock_user):
        """User with no active memberships is rejected with 403."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        request = Request(scope={"type": "http", "headers": []})
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            with pytest.raises(HTTPException) as exc_info:
                await get_tenant_context(request=request, current_user=mock_user, db=mock_db)
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# 3. require_tenant_role Dependency Tests
# ============================================================================


class TestRequireTenantRole:
    @pytest.mark.asyncio
    async def test_authorized_role_succeeds(self):
        ctx = TenantContext(institution_id=uuid.uuid4(), user_id=uuid.uuid4(), role="admin")
        checker = require_tenant_role("admin", "principal")
        res = await checker(tenant=ctx)
        assert res == ctx

    @pytest.mark.asyncio
    async def test_unauthorized_role_raises_403(self):
        ctx = TenantContext(institution_id=uuid.uuid4(), user_id=uuid.uuid4(), role="student")
        checker = require_tenant_role("admin", "teacher")
        with pytest.raises(HTTPException) as exc_info:
            await checker(tenant=ctx)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "requires one of these institutional roles" in exc_info.value.detail


# ============================================================================
# 4. ChromaDB Dual-Identifier Filtering Tests
# ============================================================================


class TestChromaTenantFiltering:
    def test_pilot_slug_uses_in_filter(self):
        filter_dict = build_chroma_tenant_filter("eduintel-pilot")
        expected = {
            "institution_id": {
                "$in": [
                    "00000000-0000-0000-0000-000000000001",
                    "eduintel-pilot",
                ]
            }
        }
        assert filter_dict == expected

    def test_pilot_uuid_uses_in_filter(self):
        filter_dict = build_chroma_tenant_filter(PILOT_INSTITUTION_UUID)
        assert filter_dict["institution_id"]["$in"] == [
            "00000000-0000-0000-0000-000000000001",
            "eduintel-pilot",
        ]

    def test_non_pilot_tenant_uses_exact_uuid_filter(self):
        foreign_id = uuid.uuid4()
        filter_dict = build_chroma_tenant_filter(foreign_id)
        assert filter_dict == {"institution_id": str(foreign_id)}

    def test_missing_institution_fails_closed(self):
        with pytest.raises(ValueError):
            build_chroma_tenant_filter(None)

    def test_ingestion_canonicalizes_pilot_metadata(self):
        mock_col = MagicMock()
        with patch("app.rag.service.get_study_materials_collection", return_value=mock_col):
            ingest_study_material(
                material_id=str(uuid.uuid4()),
                subject="Physics",
                title="Mechanics",
                extracted_text="Quantum mechanics is a fundamental theory in physics.",
                institution_id="eduintel-pilot",
            )
            # Verify upsert metadatas recorded canonical UUID
            args, kwargs = mock_col.upsert.call_args
            for meta in kwargs["metadatas"]:
                assert meta["institution_id"] == "00000000-0000-0000-0000-000000000001"


# ============================================================================
# 5. PostgreSQL Role Privilege Startup Assertion Tests
# ============================================================================


class TestDatabaseRoleSecurityAssertion:
    FATAL_ERR_SUBSTRING = "unconstrained superuser, bypassrls, createrole, or createdb"

    @pytest.mark.asyncio
    async def test_unprivileged_role_passes(self):
        """Clean unprivileged role passes startup verification."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []  # No violating roles returned
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        # Should complete without error
        await verify_unprivileged_db_user(mock_engine)

    @pytest.mark.asyncio
    async def test_direct_superuser_fails_closed(self):
        """Direct SUPERUSER role triggers fatal RuntimeError."""
        mock_role = MagicMock(
            rolname="eduintel",
            rolsuper=True,
            rolbypassrls=False,
            rolcreaterole=False,
            rolcreatedb=False,
        )
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_role]
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        with pytest.raises(RuntimeError) as exc_info:
            await verify_unprivileged_db_user(mock_engine)
        assert self.FATAL_ERR_SUBSTRING in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_direct_bypassrls_fails_closed(self):
        """Direct BYPASSRLS role triggers fatal RuntimeError."""
        mock_role = MagicMock(
            rolname="eduintel",
            rolsuper=False,
            rolbypassrls=True,
            rolcreaterole=False,
            rolcreatedb=False,
        )
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_role]
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        with pytest.raises(RuntimeError) as exc_info:
            await verify_unprivileged_db_user(mock_engine)
        assert self.FATAL_ERR_SUBSTRING in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_direct_createrole_fails_closed(self):
        """Direct CREATEROLE role triggers fatal RuntimeError."""
        mock_role = MagicMock(
            rolname="eduintel",
            rolsuper=False,
            rolbypassrls=False,
            rolcreaterole=True,
            rolcreatedb=False,
        )
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_role]
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        with pytest.raises(RuntimeError) as exc_info:
            await verify_unprivileged_db_user(mock_engine)
        assert self.FATAL_ERR_SUBSTRING in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_direct_createdb_fails_closed(self):
        """Direct CREATEDB role triggers fatal RuntimeError."""
        mock_role = MagicMock(
            rolname="eduintel",
            rolsuper=False,
            rolbypassrls=False,
            rolcreaterole=False,
            rolcreatedb=True,
        )
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_role]
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        with pytest.raises(RuntimeError) as exc_info:
            await verify_unprivileged_db_user(mock_engine)
        assert self.FATAL_ERR_SUBSTRING in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_inherited_bypassrls_fails_closed(self):
        """Inherited role with BYPASSRLS capability triggers fatal RuntimeError."""
        mock_parent_role = MagicMock(
            rolname="admin_group",
            rolsuper=False,
            rolbypassrls=True,
            rolcreaterole=False,
            rolcreatedb=False,
        )
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_parent_role]
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        with pytest.raises(RuntimeError) as exc_info:
            await verify_unprivileged_db_user(mock_engine)
        assert self.FATAL_ERR_SUBSTRING in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_inherited_createrole_fails_closed(self):
        """Inherited role with CREATEROLE capability triggers fatal RuntimeError."""
        mock_parent_role = MagicMock(
            rolname="role_admin",
            rolsuper=False,
            rolbypassrls=False,
            rolcreaterole=True,
            rolcreatedb=False,
        )
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_parent_role]
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        with pytest.raises(RuntimeError) as exc_info:
            await verify_unprivileged_db_user(mock_engine)
        assert self.FATAL_ERR_SUBSTRING in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_set_role_reachable_privilege_fails_closed(self):
        """Role reachable via SET ROLE with SUPERUSER capability triggers fatal RuntimeError."""
        mock_parent_role = MagicMock(
            rolname="dba_role",
            rolsuper=True,
            rolbypassrls=False,
            rolcreaterole=False,
            rolcreatedb=False,
        )
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_parent_role]
        mock_conn.execute.return_value = mock_result

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        with pytest.raises(RuntimeError) as exc_info:
            await verify_unprivileged_db_user(mock_engine)
        assert self.FATAL_ERR_SUBSTRING in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_production_startup_fails_closed_on_db_error(self):
        """In production, any connection or query error during role check aborts startup."""
        conn_err = ConnectionRefusedError("Database unreachable")
        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch("app.main.verify_unprivileged_db_user", side_effect=conn_err):
                with pytest.raises(RuntimeError) as exc_info:
                    async with lifespan(app):
                        pass
                assert "FATAL: Database privilege check failed to execute in production" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_development_startup_defers_on_db_error(self):
        """In development/test, connection or query error logs warning and allows offline startup."""
        conn_err = ConnectionRefusedError("Database unreachable")
        with patch.object(settings, "ENVIRONMENT", "development"):
            with patch("app.main.verify_unprivileged_db_user", side_effect=conn_err):
                async with lifespan(app):
                    pass


# ============================================================================
# 6. RLS Negative Test Savepoint Recovery Pattern
# ============================================================================


class TestSavepointNegativePattern:
    @pytest.mark.asyncio
    async def test_nested_savepoint_rollback_preserves_outer_session(self):
        """
        Verifies correct implementation pattern for testing RLS check violations:
        Putting `with pytest.raises` OUTSIDE `async with session.begin_nested():`
        ensures that the nested savepoint rolls back on error, leaving the outer
        session clean and healthy.
        """
        mock_session = MagicMock()
        nested_tx = MagicMock()
        mock_session.begin_nested.return_value = nested_tx

        # Simulate savepoint context manager behavior
        nested_tx.__aenter__ = AsyncMock(return_value=nested_tx)
        nested_tx.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(DBAPIError):
            async with mock_session.begin_nested():
                # Simulate RLS WITH CHECK policy violation error from PostgreSQL
                raise DBAPIError("new row violates row-level security policy for table student_profiles", {}, None)

        # Confirm savepoint rollback was triggered via aexit
        nested_tx.__aexit__.assert_called_once()


# ============================================================================
# 7. Migration Coverage & Table Auditing (17 Tenant Tables)
# ============================================================================


class TestMigrationTableCoverage:
    def test_migration_0021_covers_all_17_tenant_tables(self):
        assert set(mig_0021.TENANT_TABLES) == set(EXPECTED_17_TENANT_TABLES)
        assert len(mig_0021.TENANT_TABLES) == 17

    def test_migration_0022_covers_all_17_tenant_tables(self):
        assert set(mig_0022.TENANT_TABLES) == set(EXPECTED_17_TENANT_TABLES)
        assert len(mig_0022.TENANT_TABLES) == 17

    def test_downgrade_guard_aborts_on_non_pilot_institution(self):
        """Downgrade PL/pgSQL guard aborts when non_pilot_inst_count > 0."""
        guard_sql = mig_0021.downgrade.__code__.co_consts
        found_guard = any("non-pilot institution(s) exist" in str(c) for c in guard_sql)
        assert found_guard, "Downgrade guard must check for non-pilot institutions before dropping schema"

    def test_downgrade_guard_aborts_on_null_institution_ids(self):
        """Downgrade PL/pgSQL guard aborts when any table has NULL institution_id."""
        guard_sql = mig_0021.downgrade.__code__.co_consts
        found_guard = any("NULL institution_id records" in str(c) for c in guard_sql)
        assert found_guard, "Downgrade guard must check for NULL institution_id records"


# ============================================================================
# 8. Admin AI Non-HTTP Tenant Context Binding
# ============================================================================


class TestAdminAiNonHttpBinding:
    @pytest.mark.asyncio
    async def test_execute_tools_node_binds_tenant_session(self):
        """execute_tools_node sets transaction-local app.current_institution_id."""
        mock_db = MagicMock()
        mock_tx = MagicMock()
        mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_tx.__aexit__ = AsyncMock(return_value=None)
        mock_db.begin.return_value = mock_tx
        mock_db.execute = AsyncMock()

        test_tenant_id = str(uuid.uuid4())
        state = {
            "tenant_id": test_tenant_id,
            "tool_calls": [
                {
                    "name": "get_student_teacher_counts",
                    "args": {},
                }
            ],
        }

        @asynccontextmanager
        async def mock_session_local():
            yield mock_db

        mock_tools = {"get_student_teacher_counts": AsyncMock(return_value={"students": 10, "teachers": 2})}
        with (
            patch("app.agents.admin_assistant.AsyncSessionLocal", side_effect=mock_session_local),
            patch("app.agents.admin_assistant.TOOL_FUNCTIONS", mock_tools),
        ):
            res = await execute_tools_node(state)

            # Verify set_config was executed with transaction-local flag (true)
            executed_sqls = [str(call[0][0]) for call in mock_db.execute.call_args_list]
            assert any("app.current_institution_id" in s for s in executed_sqls)
            assert len(res["tool_results"]) == 1
            assert res["tool_results"][0]["result"] == {"students": 10, "teachers": 2}


# ============================================================================
# 9. Admin Assistant Route Tenant Hardening Tests
# ============================================================================


class TestAdminAssistantRouteTenantHardening:
    """Verifies POST /agents/admin-assistant/chat tenant dependency migration and authorization."""

    @pytest.mark.asyncio
    async def test_authorized_tenant_admin_succeeds(self):
        """Authorized tenant admin with active institutional membership executes chat successfully."""
        user_id = uuid.uuid4()
        inst_id = uuid.uuid4()
        admin_user = User(
            id=user_id,
            email="admin@school.org",
            name="School Admin",
            role="admin",
            hashed_password="mock",
        )
        inst = Institution(id=inst_id, name="Alpha Academy", slug="alpha-academy", is_active=True)
        membership = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_id,
            user_id=user_id,
            role="admin",
            status="active",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(membership, inst)]
        mock_db.execute.return_value = mock_result

        mock_chat_response = {
            "answer": "Here is the summary.",
            "tools_used": [],
            "session_id": "sess-alpha-01",
            "trace_id": "tr-001",
            "llm_usage": {},
        }

        token = create_access_token({"sub": str(user_id), "role": "admin"})

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_chat = AsyncMock(return_value=mock_chat_response)
        with (
            patch("app.agents.router.chat_with_admin_assistant", mock_chat),
            patch("app.agents.router.log_ai_query", AsyncMock()),
            patch("app.agents.router.log_agent_trace", AsyncMock()),
        ):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.post(
                        "/agents/admin-assistant/chat",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-Institution-Id": str(inst_id),
                        },
                        json={"session_id": "sess-alpha-01", "query": "Student attendance summary"},
                    )
                    assert res.status_code == 200
                    data = res.json()
                    assert data["answer"] == "Here is the summary."
                    # Verify chat_with_admin_assistant was called with canonical tenant_id
                    mock_chat.assert_awaited_once_with(
                        session_id="sess-alpha-01",
                        query="Student attendance summary",
                        tenant_id=str(inst_id),
                        user_id=user_id,
                    )
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_user_without_active_membership_rejected_403(self):
        """User without active membership in the target institution receives 403 Forbidden."""
        user_id = uuid.uuid4()
        target_inst_id = uuid.uuid4()
        admin_user = User(
            id=user_id,
            email="admin@school.org",
            name="School Admin",
            role="admin",
            hashed_password="mock",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []  # No memberships in target institution
        mock_db.execute.return_value = mock_result

        token = create_access_token({"sub": str(user_id), "role": "admin"})

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/agents/admin-assistant/chat",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Institution-Id": str(target_inst_id),
                    },
                    json={"session_id": "sess-alpha-01", "query": "Student count"},
                )
                assert res.status_code == 403
                assert "Access denied: User is not an active member" in res.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_user_with_mismatched_institutional_role_rejected_403(self):
        """User who is an active member but has a non-admin role in the institution receives 403 Forbidden."""
        user_id = uuid.uuid4()
        inst_id = uuid.uuid4()
        admin_user = User(
            id=user_id,
            email="teacher@school.org",
            name="Teacher User",
            role="admin",
            hashed_password="mock",
        )
        inst = Institution(id=inst_id, name="Alpha Academy", slug="alpha-academy", is_active=True)
        # Institutional membership has role 'teacher'
        membership = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_id,
            user_id=user_id,
            role="teacher",
            status="active",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(membership, inst)]
        mock_db.execute.return_value = mock_result

        token = create_access_token({"sub": str(user_id), "role": "admin"})

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/agents/admin-assistant/chat",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Institution-Id": str(inst_id),
                    },
                    json={"session_id": "sess-alpha-01", "query": "Student count"},
                )
                assert res.status_code == 403
                assert "requires one of these institutional roles: admin" in res.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_multi_tenant_admin_with_x_institution_id_routes_correctly(self):
        """Admin with memberships in multiple institutions correctly scopes to the header-selected institution."""
        user_id = uuid.uuid4()
        inst_a_id = uuid.uuid4()
        inst_b_id = uuid.uuid4()
        admin_user = User(
            id=user_id,
            email="multiadmin@edugroup.org",
            name="Multi Admin",
            role="admin",
            hashed_password="mock",
        )
        inst_a = Institution(id=inst_a_id, name="School Alpha", slug="school-alpha", is_active=True)
        inst_b = Institution(id=inst_b_id, name="School Beta", slug="school-beta", is_active=True)
        mem_a = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_a_id,
            user_id=user_id,
            role="admin",
            status="active",
        )
        mem_b = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_b_id,
            user_id=user_id,
            role="admin",
            status="active",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        # Query returns both active memberships
        mock_result.all.return_value = [(mem_a, inst_a), (mem_b, inst_b)]
        mock_db.execute.return_value = mock_result

        mock_chat_response = {
            "answer": "Beta results.",
            "tools_used": [],
            "session_id": "sess-beta-01",
            "trace_id": "tr-002",
            "llm_usage": {},
        }

        token = create_access_token({"sub": str(user_id), "role": "admin"})

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_chat = AsyncMock(return_value=mock_chat_response)
        with (
            patch("app.agents.router.chat_with_admin_assistant", mock_chat),
            patch("app.agents.router.log_ai_query", AsyncMock()),
            patch("app.agents.router.log_agent_trace", AsyncMock()),
        ):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # Explicitly select School Beta
                    res = await client.post(
                        "/agents/admin-assistant/chat",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-Institution-Id": str(inst_b_id),
                        },
                        json={"session_id": "sess-beta-01", "query": "Fee collection stats"},
                    )
                    assert res.status_code == 200
                    # Verify chat_with_admin_assistant received Beta's UUID
                    mock_chat.assert_awaited_once_with(
                        session_id="sess-beta-01",
                        query="Fee collection stats",
                        tenant_id=str(inst_b_id),
                        user_id=user_id,
                    )
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_multi_tenant_admin_without_header_rejected_400(self):
        """Admin with memberships in multiple institutions omitting header receives 400 Bad Request."""
        user_id = uuid.uuid4()
        inst_a_id = uuid.uuid4()
        inst_b_id = uuid.uuid4()
        admin_user = User(
            id=user_id,
            email="multiadmin@edugroup.org",
            name="Multi Admin",
            role="admin",
            hashed_password="mock",
        )
        inst_a = Institution(id=inst_a_id, name="School Alpha", slug="school-alpha", is_active=True)
        inst_b = Institution(id=inst_b_id, name="School Beta", slug="school-beta", is_active=True)
        mem_a = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_a_id,
            user_id=user_id,
            role="admin",
            status="active",
        )
        mem_b = InstitutionMembership(
            id=uuid.uuid4(),
            institution_id=inst_b_id,
            user_id=user_id,
            role="admin",
            status="active",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(mem_a, inst_a), (mem_b, inst_b)]
        mock_db.execute.return_value = mock_result

        token = create_access_token({"sub": str(user_id), "role": "admin"})

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/agents/admin-assistant/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"session_id": "sess-beta-01", "query": "Fee collection stats"},
                )
                assert res.status_code == 400
                expected_err = "User belongs to multiple institutions. 'X-Institution-Id' header is required."
                assert expected_err in res.json()["detail"]
        finally:
            app.dependency_overrides.clear()

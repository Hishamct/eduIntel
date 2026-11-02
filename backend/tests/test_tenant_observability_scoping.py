"""
backend/tests/test_tenant_observability_scoping.py

Focused test suite verifying Phase 2C Stage 3, Sub-Batch 2C:
Observability Domain Tenant Scoping.

Verifies:
1. Route scoping: All /observability/* endpoints require authenticated TenantContext with
   institutional role 'admin' and use tenant-scoped database sessions (get_tenant_db).
2. Fast rejection: Unauthenticated callers return 401; non-admin roles (student, teacher)
   and untenanted admins return 403.
3. Summary isolation: get_llm_usage_summary and get_agent_trace_summary strictly filter
   all metric queries and quota calculations by institution_id.
4. Trace detail isolation: get_agent_trace_detail filters strictly by institution_id and
   trace_id, returning an empty step list for cross-tenant trace lookups.
5. Logging isolation & flushing: log_ai_query, log_pii_redaction, log_socratic_redirect,
   log_llm_usage, and log_agent_trace persist institution_id, fall back safely to
   PILOT_INSTITUTION_UUID when unprovided, and use db.flush() rather than committing.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.tenant import PILOT_INSTITUTION_UUID, get_tenant_db
from app.main import app
from app.observability.models import AgentTraceLog, AuditLog, LLMUsageLog
from app.observability.service import (
    get_agent_trace_detail,
    get_agent_trace_summary,
    get_llm_usage_summary,
    log_agent_trace,
    log_ai_query,
    log_llm_usage,
    log_pii_redaction,
    log_socratic_redirect,
)
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
    name: str | None = None,
) -> User:
    """Helper creating mock User instances with optional tenant binding."""
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=email or f"mock_{role}_{uid.hex[:6]}@example.com",
        name=name or f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    user.institution_id = institution_id

    if role == "student":
        user.student_profile = StudentProfile(
            user_id=uid,
            institution_id=institution_id,
            grade="10",
            section="A",
        )
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            user_id=uid,
            institution_id=institution_id,
            department="Science",
            subjects="Physics",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(
            user_id=uid,
            institution_id=institution_id,
            designation="Administrator",
        )
    return user


def make_auth_header(user: User) -> dict:
    """Helper generating bearer token authorization headers."""
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def create_mock_session():
    """Helper creating a properly wired mock AsyncSession for unit tests."""
    mock_db = AsyncMock()
    added_objects = []

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


class TestObservabilityRouteScopingAndAuth:
    """Tests route-level authorization, authentication, and admin tenant enforcement."""

    OBSERVABILITY_ENDPOINTS = [
        ("GET", "/observability/llm-usage-summary"),
        ("GET", "/observability/agent-traces/summary"),
        ("GET", f"/observability/agent-traces/{uuid.uuid4()}"),
    ]

    @pytest.mark.asyncio
    async def test_unauthenticated_requests_rejected(self):
        """Unauthenticated requests to all observability endpoints must return 401."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for method, url in self.OBSERVABILITY_ENDPOINTS:
                res = await client.request(method, url)
                assert res.status_code == 401, f"{method} {url} allowed unauthenticated access"

    @pytest.mark.asyncio
    async def test_non_admin_roles_rejected_with_403(self):
        """Students and teachers must be rejected with 403 on all observability endpoints."""
        student_user = create_mock_user("student", institution_id=TENANT_ALPHA)
        teacher_user = create_mock_user("teacher", institution_id=TENANT_ALPHA)

        mock_db, _ = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                for user in [student_user, teacher_user]:
                    app.dependency_overrides[get_current_user] = lambda u=user: u
                    headers = make_auth_header(user)
                    for method, url in self.OBSERVABILITY_ENDPOINTS:
                        res = await client.request(method, url, headers=headers)
                        assert res.status_code == 403, f"{method} {url} allowed role {user.role}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_untenanted_admin_rejected_with_403(self):
        """Admin users without an active tenant context must receive 403 on all endpoints."""
        untenanted_admin = create_mock_user("admin", institution_id=None)

        mock_db, _ = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: untenanted_admin

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(untenanted_admin)
                for method, url in self.OBSERVABILITY_ENDPOINTS:
                    res = await client.request(method, url, headers=headers)
                    assert res.status_code == 403, f"{method} {url} allowed untenanted admin"
                    assert "Tenant context required" in res.json().get("detail", "")
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_tenanted_admin_can_access_observability_routes(self):
        """Admin with valid tenant context can successfully access all observability endpoints."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        trace_id = uuid.uuid4()

        mock_db, _ = create_mock_session()

        # Mock database queries for summaries
        async def mock_execute(stmt):
            res = MagicMock()
            cols = list(stmt.selected_columns)
            if len(cols) == 2:
                res.one.return_value = (0, 0)
            elif len(cols) == 6:
                res.one.return_value = (0, 0, 0, 0.0, 0.0, 0)
            else:
                res.one.return_value = (0,)
            res.all.return_value = []
            res.scalar.return_value = 0
            res.scalars.return_value.all.return_value = []
            return res

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)

                res_usage = await client.get("/observability/llm-usage-summary", headers=headers)
                assert res_usage.status_code == 200
                assert "overall" in res_usage.json()

                res_traces = await client.get("/observability/agent-traces/summary", headers=headers)
                assert res_traces.status_code == 200
                assert "node_breakdown" in res_traces.json()

                res_detail = await client.get(f"/observability/agent-traces/{trace_id}", headers=headers)
                assert res_detail.status_code == 200
                data = res_detail.json()
                assert data["trace_id"] == str(trace_id)
                assert "steps" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_since_days_zero_accepted(self):
        """SEC-S3-06: Query parameter since_days=0 is accepted with 200 OK."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        mock_db, _ = create_mock_session()

        async def mock_execute(stmt):
            res = MagicMock()
            cols = list(stmt.selected_columns)
            if len(cols) == 2:
                res.one.return_value = (0, 0)
            elif len(cols) == 6:
                res.one.return_value = (0, 0, 0, 0.0, 0.0, 0)
            else:
                res.one.return_value = (0,)
            res.all.return_value = []
            res.scalar.return_value = 0
            res.scalars.return_value.all.return_value = []
            return res

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)

                res_usage = await client.get("/observability/llm-usage-summary?since_days=0", headers=headers)
                assert res_usage.status_code == 200

                res_traces = await client.get("/observability/agent-traces/summary?since_days=0", headers=headers)
                assert res_traces.status_code == 200
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_since_days_negative_rejected_422(self):
        """SEC-S3-06: Negative since_days parameter is rejected with 422 Unprocessable Entity."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        mock_db, _ = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)

                res_usage = await client.get("/observability/llm-usage-summary?since_days=-1", headers=headers)
                assert res_usage.status_code == 422
                errors = res_usage.json().get("detail", [])
                assert any("since_days" in str(err.get("loc", [])) for err in errors)

                res_traces = await client.get("/observability/agent-traces/summary?since_days=-5", headers=headers)
                assert res_traces.status_code == 422
                errors_traces = res_traces.json().get("detail", [])
                assert any("since_days" in str(err.get("loc", [])) for err in errors_traces)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_since_days_omitted_defaults_properly(self):
        """SEC-S3-06: Omitted since_days parameter defaults to 30 and returns 200 OK."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        mock_db, _ = create_mock_session()

        async def mock_execute(stmt):
            res = MagicMock()
            cols = list(stmt.selected_columns)
            if len(cols) == 2:
                res.one.return_value = (0, 0)
            elif len(cols) == 6:
                res.one.return_value = (0, 0, 0, 0.0, 0.0, 0)
            else:
                res.one.return_value = (0,)
            res.all.return_value = []
            res.scalar.return_value = 0
            res.scalars.return_value.all.return_value = []
            return res

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)

                res_usage = await client.get("/observability/llm-usage-summary", headers=headers)
                assert res_usage.status_code == 200
                assert res_usage.json()["since_days"] == 30

                res_traces = await client.get("/observability/agent-traces/summary", headers=headers)
                assert res_traces.status_code == 200
                assert res_traces.json()["since_days"] == 30
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 2. Service Scoping & Cross-Tenant Isolation
# =====================================================================


class TestObservabilityServiceScopingAndIsolation:
    """Verifies observability services enforce institution_id boundaries and isolate tenants."""

    @pytest.mark.asyncio
    async def test_get_llm_usage_summary_filters_all_queries_by_institution_id(self):
        """get_llm_usage_summary must scope overall, endpoint, and quota queries by institution_id."""
        executed_stmts = []

        async def mock_execute(stmt):
            executed_stmts.append(stmt)
            res = MagicMock()
            cols = list(stmt.selected_columns)
            if len(cols) == 6:
                # overall_stmt returns one row
                res.one.return_value = (10, 500, 250, 120.0, 1.25, 1)
            elif len(cols) == 2:
                # tokens_today and tokens_this_minute return 2 values
                res.one.return_value = (200, 100)
            else:
                res.one.return_value = (0,)
            # by_endpoint_stmt returns list of rows
            res.all.return_value = [("chat", 10, 120.0, 1.25, 1, 500, 250)]
            # quota scalar returns count
            res.scalar.return_value = 5
            return res

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        summary = await get_llm_usage_summary(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            since_days=30,
        )

        assert summary["overall"]["call_count"] == 10
        assert summary["overall"]["total_input_tokens"] == 500
        assert len(summary["by_endpoint"]) == 1
        assert "gemini_quota" in summary
        assert "groq_quota" in summary

        # Check every executed statement has an institution_id filter bound to TENANT_ALPHA
        assert len(executed_stmts) >= 4  # overall, by_endpoint, gemini rpd, gemini rpm, groq queries
        for stmt in executed_stmts:
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
            assert "llm_usage_logs.institution_id =" in compiled
            params = stmt.compile().params
            assert any(val == TENANT_ALPHA for val in params.values())

    @pytest.mark.asyncio
    async def test_get_agent_trace_summary_filters_all_queries_by_institution_id(self):
        """get_agent_trace_summary must scope node stats, run counts, and recent traces by institution_id."""
        executed_stmts = []

        async def mock_execute(stmt):
            executed_stmts.append(stmt)
            res = MagicMock()
            res.all.return_value = []
            return res

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        summary = await get_agent_trace_summary(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            since_days=7,
        )

        assert "run_counts" in summary
        assert "node_breakdown" in summary
        assert "recent_traces" in summary

        # Check all 3 queries have institution_id filter bound to TENANT_ALPHA
        assert len(executed_stmts) == 3
        for stmt in executed_stmts:
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
            assert "agent_trace_logs.institution_id =" in compiled
            params = stmt.compile().params
            assert any(val == TENANT_ALPHA for val in params.values())

    @pytest.mark.asyncio
    async def test_get_agent_trace_detail_scoping_and_cross_tenant_isolation(self):
        """get_agent_trace_detail must filter by both institution_id and trace_id."""
        trace_alpha_id = uuid.uuid4()
        step_alpha = AgentTraceLog(
            id=uuid.uuid4(),
            institution_id=TENANT_ALPHA,
            trace_id=trace_alpha_id,
            agent_name="admin_assistant",
            session_id="session-1",
            node_name="reasoning",
            step_order=1,
            duration_ms=250,
            status="ok",
            error_message=None,
            created_at=datetime.now(UTC),
        )

        async def mock_execute(stmt):
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
            assert "agent_trace_logs.institution_id =" in compiled
            assert "agent_trace_logs.trace_id =" in compiled
            params = stmt.compile().params
            res = MagicMock()
            if any(val == TENANT_ALPHA for val in params.values()) and any(
                val == trace_alpha_id for val in params.values()
            ):
                res.scalars.return_value.all.return_value = [step_alpha]
            else:
                res.scalars.return_value.all.return_value = []
            return res

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        # Alpha admin querying Alpha trace -> returns step
        steps_alpha = await get_agent_trace_detail(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            trace_id=str(trace_alpha_id),
        )
        assert len(steps_alpha) == 1
        assert steps_alpha[0]["node_name"] == "reasoning"
        assert steps_alpha[0]["duration_ms"] == 250

        # Beta admin querying Alpha trace -> returns empty list (cross-tenant isolation)
        steps_beta = await get_agent_trace_detail(
            db=mock_db,
            institution_id=TENANT_BETA,
            trace_id=str(trace_alpha_id),
        )
        assert steps_beta == []

        # Invalid trace ID string -> returns empty list gracefully
        steps_invalid = await get_agent_trace_detail(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            trace_id="not-a-valid-uuid",
        )
        assert steps_invalid == []

    @pytest.mark.asyncio
    async def test_log_ai_query_persists_institution_id_and_flushes(self):
        """log_ai_query persists institution_id, flushes to db, and does not commit."""
        mock_db, added = create_mock_session()
        user_id = uuid.uuid4()

        # Explicit institution_id
        await log_ai_query(
            db=mock_db,
            user_id=user_id,
            endpoint="chat_portal",
            query_text="What is Newton's third law?",
            institution_id=TENANT_ALPHA,
        )

        assert len(added) == 1
        entry = added[0]
        assert isinstance(entry, AuditLog)
        assert entry.institution_id == TENANT_ALPHA
        assert entry.user_id == user_id
        assert entry.endpoint == "chat_portal"
        assert entry.query_text == "What is Newton's third law?"
        mock_db.flush.assert_awaited_once()
        assert not hasattr(mock_db, "commit") or not mock_db.commit.called

        # Fallback to PILOT_INSTITUTION_UUID when institution_id is None
        await log_ai_query(
            db=mock_db,
            user_id=user_id,
            endpoint="chat_legacy",
            query_text="Legacy question",
            institution_id=None,
        )
        assert len(added) == 2
        entry_fallback = added[1]
        assert entry_fallback.institution_id == PILOT_INSTITUTION_UUID

    @pytest.mark.asyncio
    async def test_log_pii_redaction_and_socratic_redirect_forward_institution_id(self):
        """log_pii_redaction and log_socratic_redirect correctly forward institution_id."""
        mock_db, added = create_mock_session()
        user_id = uuid.uuid4()

        await log_pii_redaction(
            db=mock_db,
            user_id=user_id,
            endpoint="parent_report",
            query_text="Report for Rahul (phone 9876543210)",
            redaction_count=1,
            redacted_types=["PHONE_NUMBER"],
            institution_id=TENANT_ALPHA,
        )

        assert len(added) == 1
        pii_entry = added[0]
        assert pii_entry.institution_id == TENANT_ALPHA
        assert pii_entry.was_redacted is True
        assert pii_entry.redacted_types == "PHONE_NUMBER"

        await log_socratic_redirect(
            db=mock_db,
            user_id=user_id,
            endpoint="rag_query",
            query_text="Write my entire essay",
            was_socratic_redirected=True,
            socratic_trigger_pattern="essay_request",
            institution_id=TENANT_BETA,
        )

        assert len(added) == 2
        socratic_entry = added[1]
        assert socratic_entry.institution_id == TENANT_BETA
        assert socratic_entry.was_socratic_redirected is True
        assert socratic_entry.socratic_trigger_pattern == "essay_request"

    @pytest.mark.asyncio
    async def test_log_llm_usage_persists_institution_id_and_flushes(self):
        """log_llm_usage persists institution_id, flushes, and handles None usage safely."""
        from app.core.llm_client import LLMCallUsage

        mock_db, added = create_mock_session()

        usage = LLMCallUsage(
            provider="gemini",
            model="gemini-2.0-flash",
            input_tokens=150,
            output_tokens=50,
            latency_ms=320,
            used_fallback=False,
        )

        # Explicit institution_id
        await log_llm_usage(
            db=mock_db,
            endpoint="chat_admin",
            usage=usage,
            institution_id=TENANT_ALPHA,
        )

        assert len(added) == 1
        entry = added[0]
        assert isinstance(entry, LLMUsageLog)
        assert entry.institution_id == TENANT_ALPHA
        assert entry.provider == "gemini"
        assert entry.input_tokens == 150
        assert entry.output_tokens == 50
        assert entry.latency_ms == 320
        mock_db.flush.assert_awaited_once()

        # Fallback to PILOT_INSTITUTION_UUID
        await log_llm_usage(
            db=mock_db,
            endpoint="chat_admin",
            usage=usage,
            institution_id=None,
        )
        assert len(added) == 2
        assert added[1].institution_id == PILOT_INSTITUTION_UUID

        # usage=None is a safe no-op
        await log_llm_usage(
            db=mock_db,
            endpoint="blocked_endpoint",
            usage=None,
            institution_id=TENANT_ALPHA,
        )
        assert len(added) == 2  # No new entry added

    @pytest.mark.asyncio
    async def test_log_agent_trace_persists_institution_id_and_flushes(self):
        """log_agent_trace persists institution_id, normalizes trace_id, and flushes."""
        mock_db, added = create_mock_session()
        trace_uuid = uuid.uuid4()
        steps = [
            {
                "node_name": "retrieval",
                "step_order": 1,
                "duration_ms": 110,
                "status": "ok",
            },
            {
                "node_name": "synthesis",
                "step_order": 2,
                "duration_ms": 340,
                "status": "ok",
            },
        ]

        # Explicit institution_id and string trace_id
        await log_agent_trace(
            db=mock_db,
            trace_id=str(trace_uuid),
            agent_name="admin_assistant",
            session_id="session-42",
            trace_steps=steps,
            institution_id=TENANT_ALPHA,
        )

        assert len(added) == 2
        for i, entry in enumerate(added):
            assert isinstance(entry, AgentTraceLog)
            assert entry.institution_id == TENANT_ALPHA
            assert entry.trace_id == trace_uuid
            assert entry.agent_name == "admin_assistant"
            assert entry.session_id == "session-42"
            assert entry.node_name == steps[i]["node_name"]
            assert entry.step_order == steps[i]["step_order"]
        mock_db.flush.assert_awaited_once()

        # Fallback to PILOT_INSTITUTION_UUID
        await log_agent_trace(
            db=mock_db,
            trace_id=trace_uuid,
            agent_name="portal_assistant",
            session_id="session-99",
            trace_steps=[steps[0]],
            institution_id=None,
        )
        assert len(added) == 3
        assert added[2].institution_id == PILOT_INSTITUTION_UUID

        # Empty trace_steps is a safe no-op
        await log_agent_trace(
            db=mock_db,
            trace_id=trace_uuid,
            agent_name="empty_agent",
            session_id="session-0",
            trace_steps=[],
            institution_id=TENANT_ALPHA,
        )
        assert len(added) == 3  # No new entry added

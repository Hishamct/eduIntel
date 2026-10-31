"""
backend/tests/test_admin_ai_tenant_isolation.py

Comprehensive security regression test suite for SEC-09:
- LangGraph Admin AI Cross-Tenant Aggregation Leakage remediation.
- Strict fail-closed guard for all six reporting functions + admin dashboard summary.
- Proof that blocked reporting executes ZERO SQL queries.
- Tenant data isolation: rejection of client-supplied tenant fields.
- Admin Assistant conversation memory isolation across tenants and users.
- Bounded session memory management (max turns, LRU capacity limit, TTL pruning).
- Consistent 403 responses from /admin/debug/* endpoints for tenant administrators.
- Approved legacy single-tenant pilot mode authorization.
"""

import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.admin.service import (
    TenantAggregationBlockedError,
    get_admin_dashboard_summary,
    get_attendance_stats,
    get_revenue_summary,
    get_salary_summary,
    get_student_teacher_counts,
    get_teacher_grading_performance,
    get_timetable_coverage,
    verify_tenant_reporting_authorized,
)
from app.agents.admin_assistant import (
    MAX_ADMIN_SESSIONS,
    MAX_TURNS_PER_SESSION,
    SESSION_TTL_SECONDS,
    _admin_conversation_sessions,
    _get_namespaced_session,
    _reset_admin_conversation_sessions,
    _save_namespaced_session,
    execute_tools_node,
)
from app.auth.security import create_access_token, hash_password
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.users.dependencies import get_current_user
from app.users.models import User


def create_mock_user(
    role: str,
    user_id: uuid.UUID | None = None,
    institution_id: str | None = None,
) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"user_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    if institution_id:
        user.institution_id = institution_id
    return user


# =====================================================================
# 1. Zero SQL Execution & Fail-Closed Guard Tests
# =====================================================================

class TestReportingFunctionsFailClosed:
    """Verifies that all reporting functions fail closed before executing any SQL queries."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "func, kwargs",
        [
            (get_revenue_summary, {"month": None}),
            (get_attendance_stats, {"class_section": "10-A"}),
            (get_student_teacher_counts, {}),
            (get_salary_summary, {"month": None}),
            (get_timetable_coverage, {"class_section": "10-A"}),
            (get_teacher_grading_performance, {}),
            (get_admin_dashboard_summary, {}),
        ],
    )
    async def test_all_reporting_functions_raise_tenant_blocked_in_multi_tenant_mode(self, func, kwargs):
        """In multi-tenant mode, all reporting functions must raise TenantAggregationBlockedError with ZERO SQL."""
        mock_db = AsyncMock()
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            with pytest.raises(TenantAggregationBlockedError) as exc_info:
                await func(db=mock_db, tenant_id="tenant-alpha", **kwargs)

            assert "Tenant-scoped aggregation is currently unavailable" in str(exc_info.value)
            # Proof: Zero SQL queries executed
            mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "func, kwargs",
        [
            (get_revenue_summary, {"month": None}),
            (get_attendance_stats, {"class_section": "10-A"}),
            (get_student_teacher_counts, {}),
            (get_salary_summary, {"month": None}),
            (get_timetable_coverage, {"class_section": "10-A"}),
            (get_teacher_grading_performance, {}),
            (get_admin_dashboard_summary, {}),
        ],
    )
    async def test_reporting_functions_raise_value_error_when_tenant_id_is_none(self, func, kwargs):
        """Missing tenant_id must raise ValueError immediately and execute zero SQL queries."""
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="Trusted tenant_id is required"):
            await func(db=mock_db, tenant_id=None, **kwargs)

        mock_db.execute.assert_not_called()

    def test_verify_guard_pilot_mode_authorizes_default_institution_only(self):
        """Approved pilot exception succeeds only when tenant matches DEFAULT_INSTITUTION_ID."""
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", True):
            # Pilot tenant passes
            verify_tenant_reporting_authorized(settings.DEFAULT_INSTITUTION_ID)

            # Any other tenant fails closed even in pilot mode
            with pytest.raises(TenantAggregationBlockedError) as exc_info:
                verify_tenant_reporting_authorized("competing-tenant-beta")
            assert "Tenant-scoped aggregation is currently unavailable" in str(exc_info.value)

    def test_verify_guard_multi_tenant_mode_blocks_all_tenants(self):
        """Outside pilot mode, even DEFAULT_INSTITUTION_ID fails closed without schema partitioning."""
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            with pytest.raises(TenantAggregationBlockedError):
                verify_tenant_reporting_authorized(settings.DEFAULT_INSTITUTION_ID)


# =====================================================================
# 2. LangGraph Admin Assistant Tool Execution Security
# =====================================================================

class TestAdminAssistantLangGraphExecution:
    """Verifies that the LangGraph tool execution node enforces tenant boundaries and safe responses."""

    @pytest.mark.asyncio
    async def test_execute_tools_node_returns_unavailable_in_multi_tenant_mode(self):
        """When multi-tenant aggregation is blocked, tools return safe unavailable responses."""
        state = {
            "query": "What is our revenue and attendance?",
            "tenant_id": "tenant-school-1",
            "history": [],
            "tool_calls": [
                {"name": "get_revenue_summary", "args": {}},
                {"name": "get_attendance_stats", "args": {"class_section": "10-A"}},
                {"name": "get_student_teacher_counts", "args": {}},
            ],
            "tool_results": [],
            "answer": "",
            "decide_tools_usage": None,
            "generate_usage": None,
            "trace_steps": [],
        }

        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            new_state = await execute_tools_node(state)
            results = new_state["tool_results"]

            assert len(results) == 3
            for r in results:
                assert r["result"]["status"] == "unavailable"
                assert "currently unavailable for your institution" in r["result"]["error"]
                assert "Tenant-scoped aggregation is currently unavailable" in r["result"]["error"]

    @pytest.mark.asyncio
    async def test_execute_tools_node_fails_closed_without_tenant_id(self):
        """Missing tenant_id in agent state returns unavailable status."""
        state = {
            "query": "Salary stats",
            "tenant_id": "",
            "history": [],
            "tool_calls": [{"name": "get_salary_summary", "args": {}}],
            "tool_results": [],
            "answer": "",
            "decide_tools_usage": None,
            "generate_usage": None,
            "trace_steps": [],
        }

        new_state = await execute_tools_node(state)
        result = new_state["tool_results"][0]["result"]
        assert result["status"] == "unavailable"
        assert "Trusted tenant context is required" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_tools_node_in_pilot_mode_executes_queries(self):
        """In approved pilot mode with pilot tenant, tools execute and return reporting data."""
        mock_revenue = {
            "total_collected": 50000.0,
            "total_pending": 10000.0,
            "total_overdue": 0.0,
            "record_count": 5,
            "overdue_count": 0,
        }

        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", True):
            with patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {
                "get_revenue_summary": AsyncMock(return_value=mock_revenue)
            }):
                state = {
                    "query": "revenue",
                    "tenant_id": settings.DEFAULT_INSTITUTION_ID,
                    "history": [],
                    "tool_calls": [{"name": "get_revenue_summary", "args": {}}],
                    "tool_results": [],
                    "answer": "",
                    "decide_tools_usage": None,
                    "generate_usage": None,
                    "trace_steps": [],
                }

                new_state = await execute_tools_node(state)
                result = new_state["tool_results"][0]["result"]
                assert result == mock_revenue


# =====================================================================
# 3. Route-Level Endpoint Security & Tenant Injection Rejection
# =====================================================================

class TestAdminAssistantRouteSecurity:
    """Verifies POST /agents/admin-assistant/chat authentication, validation, and isolation."""

    @pytest.fixture(autouse=True)
    def clean_sessions(self):
        _reset_admin_conversation_sessions()
        yield
        _reset_admin_conversation_sessions()

    @pytest.mark.asyncio
    async def test_chat_rejects_client_supplied_tenant_fields(self):
        """Clients attempting to inject institution_id or tenant_id receive 422 Unprocessable Entity."""
        admin_user = create_mock_user("admin", institution_id="inst-alpha")
        token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role})

        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/agents/admin-assistant/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "session_id": "valid-session-1",
                        "query": "Show financial summary",
                        "institution_id": "malicious-competing-school",
                    },
                )
                assert res.status_code == 422
                assert "extra_forbidden" in str(res.json())
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_chat_rejects_malformed_session_id(self):
        """Session ID must adhere to strict alphanumeric/dash/underscore/dot/colon pattern."""
        admin_user = create_mock_user("admin", institution_id="inst-alpha")
        token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role})

        invalid_sessions = [
            "session with spaces",
            "session/slash",
            "session$dollar",
            "session;drop",
            "a" * 65,  # Exceeds max_length 64
        ]

        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                for bad_sid in invalid_sessions:
                    res = await client.post(
                        "/agents/admin-assistant/chat",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"session_id": bad_sid, "query": "Hello"},
                    )
                    assert res.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_chat_fails_closed_when_admin_lacks_tenant_context(self):
        """Admin user without trusted institution_id in multi-tenant mode receives 403 Forbidden."""
        admin_no_tenant = create_mock_user("admin", institution_id=None)
        token = create_access_token({"sub": str(admin_no_tenant.id), "role": admin_no_tenant.role})

        app.dependency_overrides[get_current_user] = lambda: admin_no_tenant
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.post(
                        "/agents/admin-assistant/chat",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"session_id": "sess-001", "query": "Summary"},
                    )
                    assert res.status_code == 403
                    assert "Tenant context required" in res.json()["detail"]
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_chat_rejects_non_admin_roles(self):
        """Students and teachers are rejected with 403 Forbidden."""
        student_user = create_mock_user("student", institution_id="inst-alpha")
        token = create_access_token({"sub": str(student_user.id), "role": student_user.role})

        app.dependency_overrides[get_current_user] = lambda: student_user
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/agents/admin-assistant/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"session_id": "sess-001", "query": "Summary"},
                )
                assert res.status_code == 403
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 4. Debug Endpoints Authorization & Isolation
# =====================================================================

class TestAdminDebugEndpointsIsolation:
    """Verifies that all /admin/debug/* reporting endpoints fail closed for tenant administrators."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/admin/debug/student-teacher-counts",
            "/admin/debug/salary-summary",
            "/admin/debug/timetable-coverage",
            "/admin/debug/teacher-grading-performance",
            "/admin/debug/revenue-summary",
            "/admin/debug/attendance-stats",
            "/admin/dashboard",
        ],
    )
    async def test_debug_endpoints_return_403_in_multi_tenant_mode(self, endpoint):
        """In multi-tenant mode, tenant admins receive 403 Forbidden preventing cross-tenant leakage."""
        admin_user = create_mock_user("admin", institution_id="inst-tenant-alpha")
        token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role})

        mock_db = AsyncMock()
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
                    assert res.status_code == 403
                    assert "Tenant-scoped aggregation is currently unavailable" in res.json()["detail"]
                    # Zero SQL queries executed
                    mock_db.execute.assert_not_called()
            finally:
                app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_debug_endpoints_require_tenant_context(self):
        """Admin without tenant context receives 403 Forbidden."""
        admin_no_tenant = create_mock_user("admin", institution_id=None)
        token = create_access_token({"sub": str(admin_no_tenant.id), "role": admin_no_tenant.role})

        app.dependency_overrides[get_current_user] = lambda: admin_no_tenant
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.get(
                        "/admin/debug/revenue-summary",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    assert res.status_code == 403
                    assert "Tenant context required" in res.json()["detail"]
            finally:
                app.dependency_overrides.clear()


# =====================================================================
# 5. Session Memory Isolation, Bounded Retention & Eviction
# =====================================================================

class TestSessionMemoryIsolationAndBounding:
    """Verifies namespaced conversation memory, capacity eviction (LRU), and TTL pruning."""

    def setup_method(self):
        _reset_admin_conversation_sessions()

    def teardown_method(self):
        _reset_admin_conversation_sessions()

    def test_cross_tenant_session_memory_isolation(self):
        """Two admins from different tenants using the identical session_id do not share memory."""
        tenant_a = "school-alpha"
        tenant_b = "school-beta"
        user_1 = uuid.uuid4()
        user_2 = uuid.uuid4()
        session_id = "shared-session-001"

        key_a = f"{tenant_a}:{user_1}:{session_id}"
        key_b = f"{tenant_b}:{user_2}:{session_id}"

        # Tenant A records a conversation
        _save_namespaced_session(key_a, [
            {"role": "user", "content": "Confidential School Alpha question"},
            {"role": "assistant", "content": "School Alpha answer"},
        ])

        # Tenant B queries the exact same session_id
        history_b = _get_namespaced_session(key_b)
        assert history_b == []  # Completely empty, zero leakage

        history_a = _get_namespaced_session(key_a)
        assert len(history_a) == 2
        assert "School Alpha" in history_a[0]["content"]

    def test_cross_user_session_memory_isolation_within_same_tenant(self):
        """Two different admins within the same tenant using the same session_id do not collide."""
        tenant = "school-gamma"
        admin_1 = uuid.uuid4()
        admin_2 = uuid.uuid4()
        session_id = "thread-1"

        key_1 = f"{tenant}:{admin_1}:{session_id}"
        key_2 = f"{tenant}:{admin_2}:{session_id}"

        _save_namespaced_session(key_1, [{"role": "user", "content": "Admin 1 turn"}])

        assert _get_namespaced_session(key_2) == []
        assert len(_get_namespaced_session(key_1)) == 1

    def test_session_history_turn_limit_bounding(self):
        """Session history is bounded to MAX_TURNS_PER_SESSION (20 messages)."""
        key = "tenant:user:sess"
        oversized_history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(35)
        ]

        _save_namespaced_session(key, oversized_history)
        retrieved = _get_namespaced_session(key)

        assert len(retrieved) == MAX_TURNS_PER_SESSION  # Exactly 20
        # Confirms it kept the latest messages
        assert retrieved[-1]["content"] == "msg 34"
        assert retrieved[0]["content"] == "msg 15"

    def test_session_lru_capacity_eviction(self):
        """When active sessions exceed MAX_ADMIN_SESSIONS (1000), oldest session is evicted."""
        assert MAX_ADMIN_SESSIONS == 1000

        # Fill exactly 1000 sessions
        for i in range(1000):
            _save_namespaced_session(f"tenant:user:sess_{i}", [{"role": "user", "content": f"query {i}"}])

        assert len(_admin_conversation_sessions) == 1000
        # sess_0 is the oldest
        assert "tenant:user:sess_0" in _admin_conversation_sessions

        # Add 1001st session
        _save_namespaced_session("tenant:user:sess_1000", [{"role": "user", "content": "query 1000"}])

        assert len(_admin_conversation_sessions) == 1000
        # sess_0 must have been evicted
        assert "tenant:user:sess_0" not in _admin_conversation_sessions
        # sess_1 and sess_1000 are present
        assert "tenant:user:sess_1" in _admin_conversation_sessions
        assert "tenant:user:sess_1000" in _admin_conversation_sessions

    def test_session_lru_touch_prevents_eviction(self):
        """Accessing an existing session touches its LRU order, preventing premature eviction."""
        # Add 5 sessions with a smaller test capacity simulation
        for i in range(1000):
            _save_namespaced_session(f"tenant:user:sess_{i}", [{"role": "user", "content": f"msg {i}"}])

        # Access sess_0 so it becomes most recently used
        _get_namespaced_session("tenant:user:sess_0")

        # Add new session to trigger eviction
        _save_namespaced_session("tenant:user:new_sess", [{"role": "user", "content": "new msg"}])

        # sess_0 was touched, so sess_1 should have been evicted instead of sess_0
        assert "tenant:user:sess_0" in _admin_conversation_sessions
        assert "tenant:user:sess_1" not in _admin_conversation_sessions

    def test_session_ttl_expiration_pruning(self):
        """Sessions inactive for longer than SESSION_TTL_SECONDS (24h) are pruned on access."""
        key = "tenant:user:expired_session"
        now = time.time()

        # Simulate session created 25 hours ago
        _admin_conversation_sessions[key] = {
            "history": [{"role": "user", "content": "Old message"}],
            "last_accessed": now - (SESSION_TTL_SECONDS + 3600),
        }

        # Access should prune it and return empty
        result = _get_namespaced_session(key)
        assert result == []
        assert key not in _admin_conversation_sessions

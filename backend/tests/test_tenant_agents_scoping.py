"""
backend/tests/test_tenant_agents_scoping.py

Comprehensive test suite verifying Stage 3 Agents/AI Domain Scoping:
1. Portal Assistant route tenant scoping:
   - Mandatory authentication and student role requirement.
   - Rejection of unauthenticated (401) and non-student/untenanted callers (403).
   - Telemetry attribution (log_ai_query, log_llm_usage, log_agent_trace) scoped to caller's institution_id.
2. Portal Assistant in-memory session isolation:
   - Namespaced session storage: f"{tenant_id}:{user_id}:{session_id}".
   - Zero cross-tenant and zero cross-user conversation history collision.
   - Bounded capacity eviction (LRU at MAX_PORTAL_SESSIONS = 1000).
   - Turn bounding (MAX_TURNS_PER_SESSION = 20) and TTL expiry (SESSION_TTL_SECONDS = 86400).
3. MCP Server get_student_data tenant scoping:
   - Mandatory institution_id when ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE is False.
   - Transaction-local tenant_session_scope with RLS session parameter binding.
   - Dual-layer query scoping: ExamResult and Attendance filtered by student_id AND institution_id.
   - Rejection of malformed institution_id and student_id UUIDs.
   - Explicit isolated legacy path with PILOT_INSTITUTION_UUID when legacy single-tenant mode is enabled.
"""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.portal_assistant import (
    MAX_PORTAL_SESSIONS,
    MAX_TURNS_PER_SESSION,
    SESSION_TTL_SECONDS,
    _get_portal_namespaced_session,
    _portal_conversation_sessions,
    _reset_portal_conversation_sessions,
    _save_portal_namespaced_session,
    chat_with_portal_assistant,
)
from app.auth.security import create_access_token, hash_password
from app.core.config import settings
from app.core.database import get_db
from app.core.tenant import PILOT_INSTITUTION_UUID
from app.main import app
from app.mcp.server import get_student_data
from app.users.dependencies import get_current_user
from app.users.models import StudentProfile, User

TENANT_ALPHA = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_BETA = uuid.UUID("22222222-2222-2222-2222-222222222222")


def create_mock_user(
    role: str,
    user_id: uuid.UUID | None = None,
    institution_id: uuid.UUID | None = TENANT_ALPHA,
) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"mock_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    user.institution_id = institution_id

    if role == "student":
        user.student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=uid,
            institution_id=institution_id or PILOT_INSTITUTION_UUID,
            grade="10",
            section="A",
            parent_email="parent@example.com",
        )
    return user


def make_auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


class TestPortalAssistantRouteTenantScoping:
    """Verifies authentication, authorization, and telemetry on /agents/portal-assistant/chat."""

    @pytest.mark.asyncio
    async def test_portal_assistant_anonymous_rejected_401(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/agents/portal-assistant/chat",
                json={"session_id": "test-session", "query": "How to submit homework?"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_portal_assistant_teacher_role_rejected_403(self):
        teacher = create_mock_user("teacher", institution_id=TENANT_ALPHA)
        app.dependency_overrides[get_current_user] = lambda: teacher
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/agents/portal-assistant/chat",
                    json={"session_id": "test-session", "query": "Help"},
                    headers=make_auth_header(teacher),
                )
                assert resp.status_code == 403
                assert "requires one of these roles: student" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_portal_assistant_untenanted_student_rejected_403(self):
        student_no_tenant = create_mock_user("student", institution_id=None)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: student_no_tenant
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/agents/portal-assistant/chat",
                    json={"session_id": "test-session", "query": "Help"},
                    headers=make_auth_header(student_no_tenant),
                )
                assert resp.status_code == 403
                assert "Tenant context required" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_portal_assistant_authenticated_student_success_200(self):
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_db] = lambda: mock_db

        with (
            patch("app.agents.router.chat_with_portal_assistant") as mock_chat,
            patch("app.agents.router.log_ai_query", new_callable=AsyncMock) as mock_ai_query,
            patch("app.agents.router.log_llm_usage", new_callable=AsyncMock) as mock_usage,
            patch("app.agents.router.log_agent_trace", new_callable=AsyncMock) as mock_trace,
        ):
            mock_chat.return_value = {
                "answer": "Go to the Homework tab.",
                "grounded": True,
                "blocked": False,
                "block_reason": None,
                "llm_usage": MagicMock(),
                "trace_id": str(uuid.uuid4()),
                "trace_steps": [],
            }

            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/agents/portal-assistant/chat",
                        json={"session_id": "student-sess-1", "query": "How do I submit homework?"},
                        headers=make_auth_header(student),
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["answer"] == "Go to the Homework tab."

                    # Verify namespaced chat execution
                    mock_chat.assert_called_once_with(
                        session_id="student-sess-1",
                        query="How do I submit homework?",
                        tenant_id=str(TENANT_ALPHA),
                        user_id=student.id,
                    )

                    # Verify telemetry attribution strictly to caller's institution_id
                    mock_ai_query.assert_called_once()
                    mock_usage.assert_called_once()
                    mock_trace.assert_called_once()

                    assert mock_ai_query.call_args[1]["institution_id"] == TENANT_ALPHA
                    assert mock_usage.call_args[1]["institution_id"] == TENANT_ALPHA
                    assert mock_trace.call_args[1]["institution_id"] == TENANT_ALPHA
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)


class TestPortalAssistantMemoryIsolationAndStorage:
    """Verifies tenant/user memory namespacing, LRU capacity eviction, and TTL expiration."""

    def setup_method(self):
        _reset_portal_conversation_sessions()

    def teardown_method(self):
        _reset_portal_conversation_sessions()

    def test_cross_tenant_session_memory_isolation(self):
        """
        Two students in different institutions using the same session_id must NOT
        share conversation history.
        """
        user_alpha = uuid.uuid4()
        user_beta = uuid.uuid4()
        shared_session_id = "common-client-session-id"

        # Student Alpha asks question in Tenant Alpha
        with patch("app.agents.portal_assistant.portal_assistant_graph.invoke") as mock_invoke:
            mock_invoke.return_value = {
                "answer": "Alpha answer regarding homework",
                "grounded": True,
                "llm_usage": None,
                "trace_steps": [],
            }
            chat_with_portal_assistant(
                session_id=shared_session_id,
                query="How do I submit homework?",
                tenant_id=str(TENANT_ALPHA),
                user_id=user_alpha,
            )

        # Student Beta in Tenant Beta invokes with same session_id
        with patch("app.agents.portal_assistant.portal_assistant_graph.invoke") as mock_invoke:
            mock_invoke.return_value = {
                "answer": "Beta answer",
                "grounded": True,
                "llm_usage": None,
                "trace_steps": [],
            }
            chat_with_portal_assistant(
                session_id=shared_session_id,
                query="What was my last question?",
                tenant_id=str(TENANT_BETA),
                user_id=user_beta,
            )

            # In mock_invoke call for Student Beta, history must be completely EMPTY
            beta_call_args = mock_invoke.call_args[0][0]
            assert beta_call_args["history"] == []

        # Confirm both distinct namespaced keys exist independently in session cache
        key_alpha = f"{TENANT_ALPHA}:{user_alpha}:{shared_session_id}"
        key_beta = f"{TENANT_BETA}:{user_beta}:{shared_session_id}"
        assert key_alpha in _portal_conversation_sessions
        assert key_beta in _portal_conversation_sessions

    def test_cross_user_same_tenant_session_memory_isolation(self):
        """
        Two students in the same institution using the same session_id must NOT
        share conversation history.
        """
        user_1 = uuid.uuid4()
        user_2 = uuid.uuid4()
        shared_session_id = "same-tenant-sess"

        with patch("app.agents.portal_assistant.portal_assistant_graph.invoke") as mock_invoke:
            mock_invoke.return_value = {
                "answer": "Answer 1",
                "grounded": True,
                "llm_usage": None,
                "trace_steps": [],
            }
            chat_with_portal_assistant(
                session_id=shared_session_id,
                query="User 1 query",
                tenant_id=str(TENANT_ALPHA),
                user_id=user_1,
            )

        with patch("app.agents.portal_assistant.portal_assistant_graph.invoke") as mock_invoke:
            mock_invoke.return_value = {
                "answer": "Answer 2",
                "grounded": True,
                "llm_usage": None,
                "trace_steps": [],
            }
            chat_with_portal_assistant(
                session_id=shared_session_id,
                query="User 2 query",
                tenant_id=str(TENANT_ALPHA),
                user_id=user_2,
            )
            user_2_call_args = mock_invoke.call_args[0][0]
            assert user_2_call_args["history"] == []

    def test_portal_session_lru_capacity_eviction_at_limit(self):
        """
        Adding more than MAX_PORTAL_SESSIONS (1000) sessions evicts the oldest entries.
        """
        for i in range(MAX_PORTAL_SESSIONS):
            _save_portal_namespaced_session(f"tenant:user:sess_{i}", [{"role": "user", "content": f"msg {i}"}])

        assert len(_portal_conversation_sessions) == MAX_PORTAL_SESSIONS
        assert "tenant:user:sess_0" in _portal_conversation_sessions

        # Adding 1001st session must evict sess_0
        _save_portal_namespaced_session("tenant:user:sess_1000", [{"role": "user", "content": "overflow"}])
        assert len(_portal_conversation_sessions) == MAX_PORTAL_SESSIONS
        assert "tenant:user:sess_0" not in _portal_conversation_sessions
        assert "tenant:user:sess_1" in _portal_conversation_sessions
        assert "tenant:user:sess_1000" in _portal_conversation_sessions

    def test_portal_session_max_turns_bounding(self):
        """
        A session maintains at most MAX_TURNS_PER_SESSION (20) turns.
        """
        key = "tenant:user:turn_test"
        turns = [{"role": "user", "content": f"turn {i}"} for i in range(30)]
        _save_portal_namespaced_session(key, turns)

        retrieved = _get_portal_namespaced_session(key)
        assert len(retrieved) == MAX_TURNS_PER_SESSION
        assert retrieved[0]["content"] == "turn 10"
        assert retrieved[-1]["content"] == "turn 29"

    def test_portal_session_ttl_expiration(self):
        """
        Sessions older than SESSION_TTL_SECONDS (86400s) are dropped upon access.
        """
        key = "tenant:user:expired_sess"
        _portal_conversation_sessions[key] = {
            "history": [{"role": "user", "content": "stale"}],
            "last_accessed": time.time() - (SESSION_TTL_SECONDS + 10),
        }

        retrieved = _get_portal_namespaced_session(key)
        assert retrieved == []
        assert key not in _portal_conversation_sessions


class TestMcpStudentDataTenantScoping:
    """Verifies get_student_data tenant scoping, RLS context, and fail-closed behavior."""

    @pytest.mark.asyncio
    async def test_get_student_data_fails_closed_without_institution_id(self):
        """
        When ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE is False, calling get_student_data
        without institution_id must raise ValueError immediately.
        """
        student_id = str(uuid.uuid4())
        with patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", False):
            with pytest.raises(ValueError, match="institution_id is required"):
                await get_student_data(student_id=student_id, institution_id=None)

    @pytest.mark.asyncio
    async def test_get_student_data_rejects_invalid_institution_uuid(self):
        student_id = str(uuid.uuid4())
        with pytest.raises(ValueError, match="Invalid institution_id"):
            await get_student_data(student_id=student_id, institution_id="not-a-valid-uuid")

    @pytest.mark.asyncio
    async def test_get_student_data_rejects_invalid_student_uuid(self):
        with pytest.raises(ValueError, match="Invalid student UUID format"):
            await get_student_data(student_id="invalid-student-id", institution_id=str(TENANT_ALPHA))

    @pytest.mark.asyncio
    async def test_get_student_data_queries_with_tenant_scope_and_filters(self):
        """
        Verifies that get_student_data opens tenant_session_scope(TENANT_ALPHA)
        and explicitly filters queries by student_id and institution_id.
        """
        student_id = uuid.uuid4()
        mock_db = AsyncMock()

        # Mock exam result
        mock_exam = MagicMock()
        mock_exam.subject = "Math"
        mock_exam.topic = "Algebra"
        mock_exam.score = 90.0
        mock_exam.max_score = 100.0
        from datetime import date

        mock_exam.exam_date = date(2026, 11, 1)

        # Mock attendance
        mock_att_1 = MagicMock(status="present")
        mock_att_2 = MagicMock(status="absent")

        executed_queries = []

        async def fake_execute(query):
            query_str = str(query).lower()
            executed_queries.append(query_str)
            res = MagicMock()
            if "exam_results" in query_str:
                res.scalars.return_value.all.return_value = [mock_exam]
            elif "attendance_records" in query_str:
                res.scalars.return_value.all.return_value = [mock_att_1, mock_att_2]
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_scope(inst_id):
            assert inst_id == TENANT_ALPHA
            yield mock_db

        with patch("app.mcp.server.tenant_session_scope", side_effect=fake_scope):
            res = await get_student_data(
                student_id=str(student_id),
                institution_id=str(TENANT_ALPHA),
            )

            assert len(res["recent_exams"]) == 1
            assert res["recent_exams"][0]["subject"] == "Math"
            assert res["recent_exams"][0]["score"] == 90.0
            assert res["attendance_percentage"] == 50.0  # 1 present out of 2

            # Verify executed queries contain institution_id filter
            assert len(executed_queries) == 2
            for q in executed_queries:
                assert "institution_id" in q
                assert "student_id" in q

    @pytest.mark.asyncio
    async def test_get_student_data_legacy_fallback_uses_pilot_uuid(self):
        """
        When ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE is True, calling get_student_data
        without institution_id falls back strictly to PILOT_INSTITUTION_UUID.
        """
        student_id = uuid.uuid4()
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_res)

        from contextlib import asynccontextmanager

        scoped_institutions = []

        @asynccontextmanager
        async def fake_scope(inst_id):
            scoped_institutions.append(inst_id)
            yield mock_db

        with (
            patch.object(settings, "ENABLE_LEGACY_SINGLE_TENANT_NAMESPACE", True),
            patch("app.mcp.server.tenant_session_scope", side_effect=fake_scope),
        ):
            res = await get_student_data(student_id=str(student_id), institution_id=None)
            assert res == {"recent_exams": [], "attendance_percentage": None}
            assert scoped_institutions == [PILOT_INSTITUTION_UUID]

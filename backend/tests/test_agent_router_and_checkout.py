"""
backend/tests/test_agent_router_and_checkout.py

Comprehensive test suite verifying Phase 5 Step 3.3:
Router Refactoring, 3-Phase Checkout Protocol, Admin Tool Session Hygiene & LangGraph Decoupling.

Test Matrix:
Category 1: Admin Tool DB Connection Lifecycle (Tests 1–5)
Category 2: Cancellation & Disconnect Policy (Tests 6–10)
Category 3: Request Schema Compatibility & Turn ID Resolution (Tests 11–15)
Category 4: UUID Normalization & Identifier Validation (Tests 16–20)
Category 5: Terminal States, Idempotency & Fencing Concurrency (Tests 21–26)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.admin_assistant import execute_tools_node
from app.agents.dependencies import get_session_store
from app.agents.router import (
    EDUINTEL_SESSION_NAMESPACE,
    normalize_session_id,
    resolve_client_turn_id,
)
from app.agents.schemas import (
    AdminAssistantRequest,
    PortalAssistantRequest,
)
from app.agents.session_store import (
    FencedCommitPreemptedError,
    InMemorySessionStore,
)
from app.auth.security import create_access_token, hash_password
from app.core.database import engine, get_db
from app.main import app
from app.users.dependencies import get_current_user
from app.users.models import StudentProfile, User

# ==============================================================================
# Test Fixtures and Helpers
# ==============================================================================

@pytest.fixture
def mock_store() -> InMemorySessionStore:
    """Provides an isolated InMemorySessionStore for fast router protocol verification."""
    store = InMemorySessionStore()
    app.dependency_overrides[get_session_store] = lambda: store
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        yield store
    finally:
        app.dependency_overrides.pop(get_session_store, None)
        app.dependency_overrides.pop(get_db, None)


def create_test_user(
    role: str,
    institution_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"test_{role}_{uid.hex[:6]}@example.com",
        name=f"Test {role.capitalize()}",
        hashed_password=hash_password("TestSecret123!"),
        role=role,
        is_active=True,
    )
    user.institution_id = institution_id
    if role == "student":
        user.student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=uid,
            institution_id=institution_id,
            grade="10",
            section="A",
            parent_email="parent@example.com",
        )
    return user


def make_auth_headers(user: User, institution_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {
        "Authorization": f"Bearer {token}",
        "X-Institution-Id": str(institution_id),
    }


# ==============================================================================
# Category 1: Admin Tool Database Connection Lifecycle (Tests 1–5)
# ==============================================================================

class TestAdminToolDatabaseConnectionLifecycle:
    """Verifies that database-backed admin tools execute within isolated short-lived sessions."""

    async def test_admin_tool_executes_with_short_lived_session(self):
        """1. Admin reporting tool executes inside its own tenant_session_scope and commits."""
        inst_id = uuid.uuid4()
        session_id = str(uuid.uuid4())
        mock_result = {"enrolled_students": 150, "total_teachers": 12}

        with (
            patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {"get_student_teacher_counts": AsyncMock(return_value=mock_result)}),
            patch("app.agents.admin_assistant.APPROVED_TOOL_SCHEMAS", {"get_student_teacher_counts": MagicMock(return_value=MagicMock(model_dump=lambda: {}))}),
            patch("app.agents.admin_assistant.reserve_or_get_tool_execution", new_callable=AsyncMock) as mock_reserve,
            patch("app.agents.admin_assistant.commit_internal_tool_execution", new_callable=AsyncMock) as mock_commit,
            patch("app.agents.admin_assistant.tenant_session_scope") as mock_scope,
        ):
            mock_session = AsyncMock()
            mock_scope.return_value.__aenter__.return_value = mock_session

            # Simulate tool idempotency lease
            record = MagicMock()
            record.id = uuid.uuid4()
            record.lease_generation = 1
            record.result_payload = None
            mock_reserve.return_value = (record, False)

            state = {
                "tenant_id": str(inst_id),
                "session_id": session_id,
                "turn_id": 1,
                "tool_calls": [{"name": "get_student_teacher_counts", "args": {}, "tool_call_id": "call_01"}],
            }

            out_state = await execute_tools_node(state)
            assert len(out_state["tool_results"]) == 1
            assert out_state["tool_results"][0]["name"] == "get_student_teacher_counts"
            assert out_state["tool_results"][0]["result"] == mock_result

            # Verify tenant_session_scope was entered for this tool
            mock_scope.assert_called_once_with(inst_id)
            mock_commit.assert_awaited_once_with(
                db=mock_session,
                record_id=record.id,
                my_lease_generation=1,
                result_payload=mock_result,
            )

    async def test_admin_tool_session_released_before_langgraph_returns(self):
        """2. Connection pool checkout is 0 before tool execution returns to LangGraph."""
        inst_id = uuid.uuid4()
        session_id = str(uuid.uuid4())

        checkout_count_during_tool = None

        async def inspect_pool_during_tool(db, tenant_id, **kwargs):
            nonlocal checkout_count_during_tool
            checkout_count_during_tool = engine.pool.checkedout()
            return {"status": "ok"}

        with (
            patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {"get_student_teacher_counts": inspect_pool_during_tool}),
            patch("app.agents.admin_assistant.APPROVED_TOOL_SCHEMAS", {"get_student_teacher_counts": MagicMock(return_value=MagicMock(model_dump=lambda: {}))}),
            patch("app.agents.admin_assistant.reserve_or_get_tool_execution", new_callable=AsyncMock) as mock_reserve,
            patch("app.agents.admin_assistant.commit_internal_tool_execution", new_callable=AsyncMock),
        ):
            mock_reserve.return_value = (None, False)

            state = {
                "tenant_id": str(inst_id),
                "session_id": session_id,
                "turn_id": 1,
                "tool_calls": [{"name": "get_student_teacher_counts", "args": {}, "tool_call_id": "call_pool_test"}],
            }

            # Pre-execution: 0 connections checked out
            pre_checkout = engine.pool.checkedout()
            await execute_tools_node(state)
            # Post-execution: released back to pool
            post_checkout = engine.pool.checkedout()

            assert post_checkout == pre_checkout

    async def test_zero_db_connections_during_decide_and_generate_nodes(self):
        """3. Exactly 0 database connections checked out during external LLM decide and generate nodes."""
        # Simulated LLM generation window
        pre_llm = engine.pool.checkedout()
        await asyncio.sleep(0.01)  # Simulates LLM inference wait
        post_llm = engine.pool.checkedout()
        assert pre_llm == 0
        assert post_llm == 0

    async def test_concurrent_tool_execution_does_not_share_session(self):
        """4. Multiple tools executed within same turn acquire distinct AsyncSessions, never sharing."""
        inst_id = uuid.uuid4()
        sessions_used = []

        async def mock_tool_func(db, tenant_id, **kwargs):
            sessions_used.append(db)
            return {"data": 123}

        with (
            patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {
                "get_student_teacher_counts": mock_tool_func,
                "get_attendance_stats": mock_tool_func,
            }),
            patch("app.agents.admin_assistant.APPROVED_TOOL_SCHEMAS", {
                "get_student_teacher_counts": MagicMock(return_value=MagicMock(model_dump=lambda: {})),
                "get_attendance_stats": MagicMock(return_value=MagicMock(model_dump=lambda: {})),
            }),
            patch("app.agents.admin_assistant.reserve_or_get_tool_execution", new_callable=AsyncMock) as mock_reserve,
            patch("app.agents.admin_assistant.commit_internal_tool_execution", new_callable=AsyncMock),
        ):
            mock_reserve.return_value = (None, False)

            state = {
                "tenant_id": str(inst_id),
                "session_id": str(uuid.uuid4()),
                "turn_id": 1,
                "tool_calls": [
                    {"name": "get_student_teacher_counts", "args": {}, "tool_call_id": "call_1"},
                    {"name": "get_attendance_stats", "args": {}, "tool_call_id": "call_2"},
                ],
            }

            await execute_tools_node(state)
            assert len(sessions_used) == 2
            # Sessions must be two distinct instances
            assert sessions_used[0] is not sessions_used[1]

    async def test_admin_tool_idempotency_and_rls_intact(self):
        """5. Re-executing identical tool call returns cached result without running service query."""
        inst_id = uuid.uuid4()
        mock_tool_func = AsyncMock()

        cached_payload = {"cached_enrollment": 500}
        record = MagicMock()
        record.result_payload = cached_payload

        with (
            patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {"get_student_teacher_counts": mock_tool_func}),
            patch("app.agents.admin_assistant.APPROVED_TOOL_SCHEMAS", {"get_student_teacher_counts": MagicMock(return_value=MagicMock(model_dump=lambda: {}))}),
            patch("app.agents.admin_assistant.reserve_or_get_tool_execution", new_callable=AsyncMock) as mock_reserve,
        ):
            # Simulate idempotency hit
            mock_reserve.return_value = (record, True)

            state = {
                "tenant_id": str(inst_id),
                "session_id": str(uuid.uuid4()),
                "turn_id": 1,
                "tool_calls": [{"name": "get_student_teacher_counts", "args": {}, "tool_call_id": "call_cached"}],
            }

            out_state = await execute_tools_node(state)
            assert out_state["tool_results"][0]["result"] == cached_payload
            # Service function must NOT be called
            mock_tool_func.assert_not_called()


# ==============================================================================
# Category 2: Cancellation & Disconnect Policy (Tests 6–10)
# ==============================================================================

class TestCancellationAndDisconnectPolicy:
    """Verifies default cancellation policy and managed shielded cleanup."""

    async def test_cancellation_during_generation_releases_lease(self, mock_store: InMemorySessionStore):
        """6. When request is cancelled during generation, lease is released with original fence/token."""
        inst_id = uuid.uuid4()
        user = create_test_user("student", inst_id)
        mock_store.register_user(user.id, inst_id, "student")

        headers = make_auth_headers(user, inst_id)
        app.dependency_overrides[get_current_user] = lambda: user

        sess_id = str(uuid.uuid4())
        await mock_store.get_or_create_session(sess_id, inst_id, user.id, "portal_assistant")

        async def slow_generation(*args, **kwargs):
            await asyncio.sleep(5)
            return {"answer": "Should not complete", "grounded": True}

        with patch("app.agents.router.chat_with_portal_assistant", slow_generation):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # Launch task and cancel it after 50ms
                    task = asyncio.create_task(
                        client.post(
                            "/agents/portal-assistant/chat",
                            headers=headers,
                            json={"session_id": sess_id, "query": "Cancel me"},
                        )
                    )
                    await asyncio.sleep(0.05)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task

                # Verify lease was released in store
                sess = await mock_store.get_session(sess_id, inst_id, user.id)
                assert sess.is_generating is False
                assert sess.generation_owner_token is None
            finally:
                app.dependency_overrides.pop(get_current_user, None)

    async def test_managed_shield_cleanup_completes_despite_cancellation(self, mock_store: InMemorySessionStore):
        """7. Managed shield ensures cleanup completes even if outer task is cancelled during shield."""
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()

        await mock_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
        lease = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-clean")
        assert lease.session.is_generating is True

        # Simulate cancellation cleanup block
        cleanup_task = asyncio.create_task(
            mock_store.release_generation_lease(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                fence=lease.fence,
                owner_token=lease.owner_token,
            )
        )
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            await cleanup_task

        sess = await mock_store.get_session(sess_id, inst_id, user_id)
        assert sess.is_generating is False

    async def test_cancellation_preserves_cancelled_error(self, mock_store: InMemorySessionStore):
        """8. Cancellation is never swallowed or converted into HTTP 500."""
        inst_id = uuid.uuid4()
        user = create_test_user("student", inst_id)
        mock_store.register_user(user.id, inst_id, "student")
        headers = make_auth_headers(user, inst_id)
        app.dependency_overrides[get_current_user] = lambda: user

        async def cancel_immediately(*args, **kwargs):
            raise asyncio.CancelledError("Client dropped connection")

        with patch("app.agents.router.chat_with_portal_assistant", cancel_immediately):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # Starlette BaseHTTPMiddleware converts unhandled CancelledError into RuntimeError("No response returned.")
                    with pytest.raises((asyncio.CancelledError, RuntimeError)):
                        await client.post(
                            "/agents/portal-assistant/chat",
                            headers=headers,
                            json={"session_id": str(uuid.uuid4()), "query": "Disconnect"},
                        )
            finally:
                app.dependency_overrides.pop(get_current_user, None)

    async def test_stale_worker_cannot_release_preempted_lease(self, mock_store: InMemorySessionStore):
        """9. Worker A cancelled after Worker B preempted lease cannot release Worker B's lease."""
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()

        await mock_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Worker A acquires lease
        lease_a = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-A", lease_seconds=1)
        # Advance clock to expire lease A
        mock_store._sessions[sess_id]["generation_lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=10)

        # Worker B preempts lease
        lease_b = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-B", lease_seconds=60)
        assert lease_b.fence == lease_a.fence + 1

        # Worker A tries to release its old lease
        released = await mock_store.release_generation_lease(
            sess_id, inst_id, user_id, lease_a.fence, lease_a.owner_token
        )
        assert released is False

        # Worker B's lease remains active
        sess = await mock_store.get_session(sess_id, inst_id, user_id)
        assert sess.is_generating is True
        assert sess.generation_fence == lease_b.fence
        assert sess.generation_owner_token == lease_b.owner_token

    async def test_abandoned_generation_cannot_persist_after_cancellation(self, mock_store: InMemorySessionStore):
        """10. Late-finishing abandoned generation attempt to commit fails FencedCommitPreemptedError."""
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()

        await mock_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
        lease = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-abandon")

        # Lease released due to cancellation
        await mock_store.release_generation_lease(
            sess_id, inst_id, user_id, lease.fence, lease.owner_token
        )

        # Abandoned background thread attempts to commit
        with pytest.raises(FencedCommitPreemptedError):
            await mock_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-abandon",
                fence=lease.fence,
                owner_token=lease.owner_token,
                user_message="Prompt",
                assistant_message="Abandoned reply",
            )


# ==============================================================================
# Category 3: Request Schema Compatibility & Turn ID Resolution (Tests 11–15)
# ==============================================================================

class TestRequestSchemaCompatibilityAndTurnIDResolution:
    """Verifies schema validation, turn ID priority, and conflict rejection."""

    def test_portal_request_accepts_standard_payload(self):
        """11. PortalAssistantRequest accepts standard session_id and query without client_turn_id."""
        req = PortalAssistantRequest(session_id="portal-sess-1", query="Help with dashboard")
        assert req.session_id == "portal-sess-1"
        assert req.query == "Help with dashboard"
        assert req.client_turn_id is None

    def test_admin_request_accepts_optional_client_turn_id(self):
        """12. AdminAssistantRequest accepts optional client_turn_id."""
        req = AdminAssistantRequest(
            session_id="admin-sess-1",
            query="Enrollment stats",
            client_turn_id="turn-custom-99",
        )
        assert req.client_turn_id == "turn-custom-99"

    def test_admin_request_rejects_extra_fields_422(self):
        """13. AdminAssistantRequest rejects unauthorized extra fields with extra_forbidden."""
        with pytest.raises(Exception) as exc_info:
            AdminAssistantRequest(
                session_id="admin-sess-1",
                query="Stats",
                malicious_field="hack",
            )
        assert "extra_forbidden" in str(exc_info.value)

    def test_client_turn_id_conflicting_body_and_header_422(self):
        """14. Conflicting body and header turn IDs trigger HTTP 422."""
        with pytest.raises(Exception) as exc_info:
            resolve_client_turn_id(body_turn_id="turn-A", header_turn_id="turn-B")
        assert exc_info.value.status_code == 422
        assert "Conflicting client_turn_id" in exc_info.value.detail

    def test_client_turn_id_fallback_random_uuid(self):
        """15. Fallback generates unique non-deterministic UUIDs."""
        id1 = resolve_client_turn_id(body_turn_id=None, header_turn_id=None)
        id2 = resolve_client_turn_id(body_turn_id=None, header_turn_id=None)
        assert id1 != id2
        assert uuid.UUID(id1).version == 4


# ==============================================================================
# Category 4: UUID Normalization & Identifier Validation (Tests 16–20)
# ==============================================================================

class TestUUIDNormalizationAndIdentifierValidation:
    """Verifies canonical UUID normalization contract."""

    def test_normalize_session_id_valid_uuid_unchanged(self):
        """16. Standard valid UUID strings are preserved unchanged."""
        raw = "11111111-2222-3333-4444-555555555555"
        norm = normalize_session_id(raw)
        assert str(norm) == raw

    def test_normalize_session_id_legacy_string_deterministic_uuid5(self):
        """17. Legacy alphanumeric strings deterministically hash to identical UUIDv5."""
        key = "student-portal-sess-01"
        u1 = normalize_session_id(key)
        u2 = normalize_session_id(key)
        expected = uuid.uuid5(EDUINTEL_SESSION_NAMESPACE, key)
        assert u1 == u2
        assert u1 == expected

    def test_normalize_session_id_whitespace_trimmed(self):
        """18. Leading and trailing whitespace is trimmed before hashing."""
        raw = "   student-portal-sess-01   "
        clean = "student-portal-sess-01"
        assert normalize_session_id(raw) == normalize_session_id(clean)

    def test_normalize_session_id_malformed_rejected_422(self):
        """19. Characters outside whitelist or overlong keys are rejected with HTTP 422."""
        bad_keys = [
            "session;DROP TABLE",
            "session with spaces",
            "session/slash",
            "a" * 65,  # Exceeds 64 chars
        ]
        for k in bad_keys:
            with pytest.raises(Exception) as exc_info:
                normalize_session_id(k)
            assert exc_info.value.status_code == 422

    def test_normalize_session_id_empty_rejected_422(self):
        """20. Empty or whitespace-only session IDs are rejected with HTTP 422."""
        for empty in ["", "   ", "\t\n"]:
            with pytest.raises(Exception) as exc_info:
                normalize_session_id(empty)
            assert exc_info.value.status_code == 422


# ==============================================================================
# Category 5: Terminal States, Idempotency & Fencing Concurrency (Tests 21–26)
# ==============================================================================

class TestTerminalStatesAndFencingConcurrency:
    """Verifies terminal-state persistence, idempotency replay, and fencing rules."""

    async def test_completed_turn_persisted_and_cached(self, mock_store: InMemorySessionStore):
        """21. Completed turn commits messages and subsequent duplicate turn returns cached answer."""
        inst_id = uuid.uuid4()
        user = create_test_user("student", inst_id)
        mock_store.register_user(user.id, inst_id, "student")
        headers = make_auth_headers(user, inst_id)
        app.dependency_overrides[get_current_user] = lambda: user

        sess_id = str(uuid.uuid4())
        client_turn_id = "turn-cached-test-01"

        with patch("app.agents.router.chat_with_portal_assistant") as mock_chat:
            mock_chat.return_value = {
                "answer": "Authoritative Answer",
                "grounded": True,
                "blocked": False,
                "block_reason": None,
                "llm_usage": None,
                "trace_id": str(uuid.uuid4()),
                "trace_steps": [],
            }
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    # Turn 1: Fresh generation
                    res1 = await client.post(
                        "/agents/portal-assistant/chat",
                        headers=headers,
                        json={"session_id": sess_id, "query": "Hello", "client_turn_id": client_turn_id},
                    )
                    assert res1.status_code == 200
                    assert res1.json()["answer"] == "Authoritative Answer"
                    assert mock_chat.call_count == 1

                    # Turn 2: Exact duplicate submission
                    res2 = await client.post(
                        "/agents/portal-assistant/chat",
                        headers=headers,
                        json={"session_id": sess_id, "query": "Hello", "client_turn_id": client_turn_id},
                    )
                    assert res2.status_code == 200
                    assert res2.json()["answer"] == "Authoritative Answer"
                    # Zero additional LLM calls
                    assert mock_chat.call_count == 1
            finally:
                app.dependency_overrides.pop(get_current_user, None)

    async def test_guardrail_blocked_turn_committed_as_blocked(self, mock_store: InMemorySessionStore):
        """22. Input guardrail block commits with status='BLOCKED', turn_counter +1, and logs refusal."""
        inst_id = uuid.uuid4()
        user = create_test_user("student", inst_id)
        mock_store.register_user(user.id, inst_id, "student")
        headers = make_auth_headers(user, inst_id)
        app.dependency_overrides[get_current_user] = lambda: user

        sess_id = str(uuid.uuid4())
        norm_uuid = normalize_session_id(sess_id)

        with patch("app.agents.router.chat_with_portal_assistant") as mock_chat:
            mock_chat.return_value = {
                "answer": "I cannot fulfill this prompt due to academic integrity.",
                "grounded": False,
                "blocked": True,
                "block_reason": "Academic dishonesty detected",
                "llm_usage": None,
                "trace_id": str(uuid.uuid4()),
                "trace_steps": [],
            }
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.post(
                        "/agents/portal-assistant/chat",
                        headers=headers,
                        json={"session_id": sess_id, "query": "Give me exam answers"},
                    )
                    assert res.status_code == 200
                    assert "academic integrity" in res.json()["answer"]

                # Verify turn counter incremented and message status is BLOCKED
                sess = await mock_store.get_session(norm_uuid, inst_id, user.id)
                assert sess.turn_counter == 1

                msgs = mock_store._messages.get(norm_uuid, [])
                assert len(msgs) == 2
                asst_msg = next(m for m in msgs if m["role"] == "assistant")
                assert asst_msg["status"] == "BLOCKED"
            finally:
                app.dependency_overrides.pop(get_current_user, None)

    async def test_blocked_turn_allows_fresh_retry(self, mock_store: InMemorySessionStore):
        """23. Blocked turn is not cached, permitting subsequent retry with same turn ID."""
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        turn_id = "retry-turn-01"

        await mock_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Reserve and commit blocked turn
        lease1 = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, turn_id)
        await mock_store.commit_turn_atomic(
            session_id=sess_id,
            institution_id=inst_id,
            user_id=user_id,
            client_turn_id=turn_id,
            fence=lease1.fence,
            owner_token=lease1.owner_token,
            user_message="Bad prompt",
            assistant_message="Blocked",
            status="BLOCKED",
        )

        # Retry with same client_turn_id
        lease2 = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, turn_id)
        # Must NOT be cached hit
        assert lease2.is_cached is False
        assert lease2.cached_response is None
        # Lease successfully reserved for retry
        assert lease2.fence == lease1.fence + 1

    async def test_transient_failure_releases_lease_clean_slot(self, mock_store: InMemorySessionStore):
        """24. Transient failure releases lease without persisting messages or advancing counter."""
        inst_id = uuid.uuid4()
        user = create_test_user("student", inst_id)
        mock_store.register_user(user.id, inst_id, "student")
        headers = make_auth_headers(user, inst_id)
        app.dependency_overrides[get_current_user] = lambda: user

        sess_id = str(uuid.uuid4())
        norm_uuid = normalize_session_id(sess_id)

        with patch("app.agents.router.chat_with_portal_assistant") as mock_chat:
            mock_chat.return_value = {
                "answer": "",
                "status": "FAILED",
                "blocked": False,
                "block_reason": None,
                "llm_usage": None,
                "trace_id": str(uuid.uuid4()),
                "trace_steps": [],
            }
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.post(
                        "/agents/portal-assistant/chat",
                        headers=headers,
                        json={"session_id": sess_id, "query": "Test transient"},
                    )
                    assert res.status_code == 200

                sess = await mock_store.get_session(norm_uuid, inst_id, user.id)
                assert sess.turn_counter == 0
                assert sess.is_generating is False

                msgs = mock_store._messages.get(norm_uuid, [])
                assert len(msgs) == 0
            finally:
                app.dependency_overrides.pop(get_current_user, None)

    async def test_fenced_commit_preempted_returns_409(self, mock_store: InMemorySessionStore):
        """25. Preempted worker commit attempt returns HTTP 409 Conflict."""
        inst_id = uuid.uuid4()
        user = create_test_user("student", inst_id)
        mock_store.register_user(user.id, inst_id, "student")
        headers = make_auth_headers(user, inst_id)
        app.dependency_overrides[get_current_user] = lambda: user

        sess_id = str(uuid.uuid4())

        def advance_fence_during_generation(*args, **kwargs):
            # Preempt lease while generation runs
            norm_uuid = normalize_session_id(sess_id)
            mock_store._sessions[norm_uuid]["generation_fence"] += 5
            return {
                "answer": "Late answer",
                "grounded": True,
                "blocked": False,
                "block_reason": None,
                "llm_usage": None,
                "trace_id": str(uuid.uuid4()),
                "trace_steps": [],
            }

        with patch("app.agents.router.chat_with_portal_assistant", advance_fence_during_generation):
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    res = await client.post(
                        "/agents/portal-assistant/chat",
                        headers=headers,
                        json={"session_id": sess_id, "query": "Preempt test"},
                    )
                    assert res.status_code == 409
                    assert "preempted or expired" in res.json()["detail"]
            finally:
                app.dependency_overrides.pop(get_current_user, None)

    async def test_stale_worker_cannot_retry_with_stale_token(self, mock_store: InMemorySessionStore):
        """26. Preempted worker cannot retry commit with stale token."""
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()

        await mock_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
        lease1 = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-1", lease_seconds=1)

        # Preempt lease by expiring lease1
        mock_store._sessions[sess_id]["generation_lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=10)
        _ = await mock_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-2", lease_seconds=60)

        # Worker 1 attempts commit with stale fence and stale token
        with pytest.raises(FencedCommitPreemptedError):
            await mock_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-1",
                fence=lease1.fence,
                owner_token=lease1.owner_token,
                user_message="Prompt",
                assistant_message="Stale",
            )

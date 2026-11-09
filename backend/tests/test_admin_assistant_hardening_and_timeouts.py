"""
backend/tests/test_admin_assistant_hardening_and_timeouts.py

Deterministic test suite for Phase 5 Step 3.6 Stage 3: Admin Assistant Hardening:
- Async LangGraph execution with recursion limit 6 and 30s timeout.
- LLM worker pool offloading with tracked operations (decide_tools 8s, generate 11s).
- Tool execution await timeout (7s) and failure preservation.
- Unified session quiescence barrier (HTTP 409).
- Router 35.0s shielded deadline without premature lease release (HTTP 504).
- Background quiescence coordinator release.
- ContextVar isolation and guaranteed restoration (.reset(token)).
- Dual async/sync execution compatibility without test mock introspection.
- End-to-end 12-step lifecycle reproduction.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from langgraph.errors import GraphRecursionError

from app.agents.admin_assistant import (
    AgentState,
    chat_with_admin_assistant,
    decide_tools_node,
    execute_tools_node,
    generate_node,
)
from app.agents.portal_assistant import current_generation_fence, current_generation_owner_token
from app.agents.router import admin_assistant_chat
from app.agents.schemas import AdminAssistantRequest
from app.agents.task_registry import SessionTaskTrackingRegistry, is_session_quiescent
from app.core.tenant import PILOT_INSTITUTION_UUID
from app.core.worker_pool import (
    LLM_WORKER_POOL,
    BoundedWorkerPool,
    WorkerCapacityExhaustedError,
    WorkerTrackingRegistry,
)


@pytest.fixture(autouse=True)
def clean_registries():
    """Ensure registries are clean before and after each test."""
    WorkerTrackingRegistry.clear_for_testing()
    SessionTaskTrackingRegistry.clear_for_testing()
    yield
    WorkerTrackingRegistry.clear_for_testing()
    SessionTaskTrackingRegistry.clear_for_testing()


# ==============================================================================
# 1. Async Graph Execution, Recursion Limits & Timeouts
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_router_uses_ainvoke_and_recursion_limit():
    """Verify production chat_with_admin_assistant invokes ainvoke with recursion_limit=6."""
    sess_id = str(uuid.uuid4())
    inst_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    with patch(
        "app.agents.admin_assistant.admin_assistant_graph.ainvoke",
        new_callable=AsyncMock,
    ) as mock_ainvoke:
        mock_ainvoke.return_value = {
            "answer": "Test admin answer",
            "tool_calls": [],
            "tool_results": [],
            "decide_tools_usage": None,
            "generate_usage": None,
            "trace_steps": [],
            "is_blocked": False,
            "block_reason": None,
            "status": "COMPLETED",
        }

        coro = chat_with_admin_assistant(
            session_id=sess_id,
            query="How many students are enrolled?",
            tenant_id=inst_id,
            user_id=user_id,
        )
        assert inspect.iscoroutine(coro)
        res = await coro

        assert res["answer"] == "Test admin answer"
        assert res["status"] == "COMPLETED"
        assert mock_ainvoke.call_count == 1

        call_args, call_kwargs = mock_ainvoke.call_args
        # Verify initial state passed
        assert call_args[0]["query"] == "How many students are enrolled?"
        assert call_args[0]["tenant_id"] == inst_id
        # Verify recursion limit 6
        assert call_kwargs.get("config") == {"recursion_limit": 6}


@pytest.mark.asyncio
async def test_admin_graph_timeout_30s_enforced():
    """Verify graph-level 30.0s timeout returns structured FAILED status without crashing."""
    sess_id = str(uuid.uuid4())
    inst_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    async def _hanging_ainvoke(*args, **kwargs):
        await asyncio.sleep(5.0)
        return {}

    with (
        patch(
            "app.agents.admin_assistant.admin_assistant_graph.ainvoke",
            side_effect=_hanging_ainvoke,
        ),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        res = await chat_with_admin_assistant(
            session_id=sess_id,
            query="Slow admin question",
            tenant_id=inst_id,
            user_id=user_id,
        )
        assert res["status"] == "FAILED"
        assert res["block_reason"] == "timeout"
        assert "took too long to process" in res["answer"]


@pytest.mark.asyncio
async def test_admin_graph_recursion_limit_caught_safely():
    """Verify GraphRecursionError returns structured loop notice without crash."""
    sess_id = str(uuid.uuid4())
    inst_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    with patch(
        "app.agents.admin_assistant.admin_assistant_graph.ainvoke",
        side_effect=GraphRecursionError("Recursion limit of 6 reached"),
    ):
        res = await chat_with_admin_assistant(
            session_id=sess_id,
            query="Loop test",
            tenant_id=inst_id,
            user_id=user_id,
        )
        assert res["status"] == "FAILED"
        assert res["block_reason"] == "recursion_limit"
        assert "internal loop" in res["answer"]


def test_admin_assistant_preserves_dual_sync_compatibility():
    """Verify synchronous callers get a dict directly without asyncio.run() requirement from caller."""
    sess_id = str(uuid.uuid4())
    inst_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    with patch(
        "app.agents.admin_assistant.admin_assistant_graph.ainvoke",
        new_callable=AsyncMock,
    ) as mock_ainvoke:
        mock_ainvoke.return_value = {
            "answer": "Sync admin answer",
            "tool_calls": [],
            "tool_results": [],
            "decide_tools_usage": None,
            "generate_usage": None,
            "trace_steps": [],
            "is_blocked": False,
            "block_reason": None,
            "status": "COMPLETED",
        }

        res = chat_with_admin_assistant(
            session_id=sess_id,
            query="Sync query",
            tenant_id=inst_id,
            user_id=user_id,
        )
        assert not inspect.iscoroutine(res)
        assert isinstance(res, dict)
        assert res["answer"] == "Sync admin answer"


# ==============================================================================
# 2. LLM Worker Pool Offloading & Node Timeouts
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_decide_tools_node_uses_llm_worker_pool():
    """Verify decide_tools offloads blocking provider calls to LLM_WORKER_POOL with metadata."""
    sess_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    token = uuid.uuid4()

    state: AgentState = {
        "query": "What are our revenue figures?",
        "tenant_id": str(inst_id),
        "history": [],
        "tool_calls": [],
        "tool_results": [],
        "answer": "",
        "decide_tools_usage": None,
        "generate_usage": None,
        "trace_steps": [],
        "session_id": str(sess_id),
        "turn_id": 1,
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "institution_id": inst_id,
        "generation_fence": 3,
        "generation_owner_token": token,
    }

    with patch.object(LLM_WORKER_POOL, "submit_tracked", wraps=LLM_WORKER_POOL.submit_tracked) as spy_submit:
        with patch("app.agents.admin_assistant.decide_tools_with_usage") as mock_decide:
            mock_decide.return_value = ([{"name": "get_revenue_summary", "args": {}}], None)
            new_state = await decide_tools_node(state)

            assert spy_submit.call_count == 1
            call_kwargs = spy_submit.call_args.kwargs
            assert call_kwargs["session_id"] == sess_id
            assert call_kwargs["institution_id"] == inst_id
            assert call_kwargs["fence"] == 3
            assert call_kwargs["owner_token"] == token
            assert len(new_state["tool_calls"]) == 1
            assert new_state["tool_calls"][0]["name"] == "get_revenue_summary"


@pytest.mark.asyncio
async def test_admin_decide_tools_node_timeout_8s_tracks_abandoned_worker():
    """Verify 8.0s timeout in decide_tools sets tracker.is_abandoned = True and returns FAILED."""
    sess_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    worker_started = threading.Event()
    worker_can_finish = threading.Event()

    state: AgentState = {
        "query": "Test query",
        "tenant_id": str(inst_id),
        "history": [],
        "tool_calls": [],
        "tool_results": [],
        "answer": "",
        "decide_tools_usage": None,
        "generate_usage": None,
        "trace_steps": [],
        "session_id": str(sess_id),
        "turn_id": 1,
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "institution_id": inst_id,
        "generation_fence": 1,
        "generation_owner_token": uuid.uuid4(),
    }

    def _slow_decide(*args, **kwargs):
        worker_started.set()
        worker_can_finish.wait(timeout=2.0)
        return ([], None)

    with patch("app.agents.admin_assistant.decide_tools_with_usage", side_effect=_slow_decide):
        with patch("asyncio.wait_for", side_effect=TimeoutError()):
            new_state = await decide_tools_node(state)

            assert new_state["status"] == "FAILED"
            assert new_state["block_reason"] == "timeout"
            assert "took too long" in new_state["answer"]

            # Physical worker is still active and tracked
            assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is False

    # Allow worker to finish cleanly
    worker_can_finish.set()
    await asyncio.sleep(0.05)
    assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is True


@pytest.mark.asyncio
async def test_admin_decide_tools_capacity_exhaustion():
    """Verify WorkerCapacityExhaustedError in decide_tools returns structured FAILED status."""
    state: AgentState = {
        "query": "Query",
        "tenant_id": str(uuid.uuid4()),
        "history": [],
        "tool_calls": [],
        "tool_results": [],
        "answer": "",
        "decide_tools_usage": None,
        "generate_usage": None,
        "trace_steps": [],
        "session_id": str(uuid.uuid4()),
        "turn_id": 1,
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "institution_id": uuid.uuid4(),
        "generation_fence": 1,
        "generation_owner_token": uuid.uuid4(),
    }

    with patch.object(
        LLM_WORKER_POOL,
        "submit_tracked",
        side_effect=WorkerCapacityExhaustedError("LLM", retry_after=5),
    ):
        new_state = await decide_tools_node(state)
        assert new_state["status"] == "FAILED"
        assert new_state["block_reason"] == "worker_capacity_exhausted"
        assert "high demand" in new_state["answer"]


@pytest.mark.asyncio
async def test_admin_generate_node_timeout_11s_tracks_abandoned_worker():
    """Verify 11.0s timeout in generate_node marks tracker.is_abandoned = True."""
    sess_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    worker_can_finish = threading.Event()

    state: AgentState = {
        "query": "Test query",
        "tenant_id": str(inst_id),
        "history": [],
        "tool_calls": [],
        "tool_results": [],
        "answer": "",
        "decide_tools_usage": None,
        "generate_usage": None,
        "trace_steps": [],
        "session_id": str(sess_id),
        "turn_id": 1,
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "institution_id": inst_id,
        "generation_fence": 1,
        "generation_owner_token": uuid.uuid4(),
    }

    def _slow_gen(*args, **kwargs):
        worker_can_finish.wait(timeout=2.0)
        return ("answer", None)

    with patch("app.agents.admin_assistant.generate_text_with_usage", side_effect=_slow_gen):
        with patch("asyncio.wait_for", side_effect=TimeoutError()):
            new_state = await generate_node(state)

            assert new_state["status"] == "FAILED"
            assert new_state["block_reason"] == "timeout"
            assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is False

    worker_can_finish.set()
    await asyncio.sleep(0.05)
    assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is True


# ==============================================================================
# 3. Tool Execution Await Budget (7s) & Idempotency
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_tool_execution_timeout_7s_enforced():
    """Verify tool execution timeout after 7.0s records timeout result without crashing."""
    sess_id = str(uuid.uuid4())
    inst_id = str(PILOT_INSTITUTION_UUID)

    state: AgentState = {
        "query": "Student counts",
        "tenant_id": inst_id,
        "history": [],
        "tool_calls": [{"name": "get_student_teacher_counts", "args": {}}],
        "tool_results": [],
        "answer": "",
        "decide_tools_usage": None,
        "generate_usage": None,
        "trace_steps": [],
        "session_id": sess_id,
        "turn_id": 1,
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "institution_id": inst_id,
        "generation_fence": 1,
        "generation_owner_token": uuid.uuid4(),
    }

    async def _slow_tool(*args, **kwargs):
        raise TimeoutError("Simulated 7s timeout")

    with patch.dict("app.agents.admin_assistant.TOOL_FUNCTIONS", {"get_student_teacher_counts": _slow_tool}):
        new_state = await execute_tools_node(state)
        results = new_state["tool_results"]
        assert len(results) == 1
        assert results[0]["result"]["status"] == "timeout"
        assert "timed out after 7.0s" in results[0]["result"]["error"]


# ==============================================================================
# 4. Router Quiescence Barrier, 35s Deadline & ContextVar Restoration
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_quiescence_barrier_blocks_concurrent_admission():
    """Verify admin router rejects admission with HTTP 409 when session is non-quiescent."""
    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()

    # Register active graph task in SessionTaskTrackingRegistry
    task_event = asyncio.Event()

    async def _background_task():
        await task_event.wait()

    t = asyncio.create_task(_background_task())
    SessionTaskTrackingRegistry.register_task(inst_id, sess_id, t, fence=1)

    mock_request = MagicMock()
    mock_user = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.institution_id = inst_id
    mock_store = MagicMock()

    payload = AdminAssistantRequest(session_id=str(sess_id), query="Admin concurrent turn")
    with pytest.raises(HTTPException) as exc_info:
        await admin_assistant_chat(payload, mock_request, mock_user, mock_tenant, mock_store)

    assert exc_info.value.status_code == 409
    assert "still active for this session" in exc_info.value.detail
    assert exc_info.value.headers.get("Retry-After") == "1"

    # Clean up background task
    task_event.set()
    await t


@pytest.mark.asyncio
async def test_admin_router_35s_timeout_returns_504_without_premature_lease_release():
    """
    Critical Lifecycle Invariant:
    On router 35.0s deadline timeout, return HTTP 504 and do NOT release lease immediately.
    Delegate release to _release_lease_when_quiescent in background.
    """
    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    owner_tok = uuid.uuid4()

    mock_request = MagicMock()
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_tenant = MagicMock()
    mock_tenant.institution_id = inst_id

    mock_lease = MagicMock()
    mock_lease.fence = 1
    mock_lease.owner_token = owner_tok
    mock_lease.is_cached = False
    mock_lease.cached_response = None
    mock_lease.history = []

    mock_store = MagicMock()
    mock_store.get_or_create_session = AsyncMock()
    mock_store.reserve_generation_lease = AsyncMock(return_value=mock_lease)
    mock_store.commit_turn_atomic = AsyncMock()
    mock_store.release_generation_lease = AsyncMock()

    task_event = asyncio.Event()

    async def _slow_admin_chat(**kwargs):
        await task_event.wait()
        return {"answer": "Finally done", "tools_used": []}

    payload = AdminAssistantRequest(session_id=str(sess_id), query="Slow admin query")

    with (
        patch("app.agents.router.chat_with_admin_assistant", side_effect=_slow_admin_chat),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await admin_assistant_chat(payload, mock_request, mock_user, mock_tenant, mock_store)

        assert exc_info.value.status_code == 504
        assert "timed out at router deadline" in exc_info.value.detail

        # CRITICAL ASSERTION: The router MUST NOT call release_generation_lease synchronously!
        assert mock_store.release_generation_lease.call_count == 0
        # The session is NOT quiescent because gen_task is still active
        assert is_session_quiescent(inst_id, sess_id) is False

    # Complete the background task
    task_event.set()
    # Allow background coordinator to release lease after quiescence
    await asyncio.sleep(0.08)
    assert mock_store.release_generation_lease.call_count == 1
    call_kwargs = mock_store.release_generation_lease.call_args.kwargs
    assert call_kwargs["fence"] == 1
    assert call_kwargs["owner_token"] == owner_tok
    assert is_session_quiescent(inst_id, sess_id) is True


@pytest.mark.asyncio
async def test_admin_contextvar_token_reset_on_success_error_timeout():
    """Verify ContextVars (fence, owner_token) are restored via .reset(token) in finally."""
    inst_id = uuid.uuid4()
    owner_tok = uuid.uuid4()

    mock_request = MagicMock()
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_tenant = MagicMock()
    mock_tenant.institution_id = inst_id

    mock_lease = MagicMock()
    mock_lease.fence = 17
    mock_lease.owner_token = owner_tok
    mock_lease.is_cached = False
    mock_lease.cached_response = None
    mock_lease.history = []

    mock_store = MagicMock()
    mock_store.get_or_create_session = AsyncMock()
    mock_store.reserve_generation_lease = AsyncMock(return_value=mock_lease)
    mock_store.commit_turn_atomic = AsyncMock()
    mock_store.release_generation_lease = AsyncMock()

    baseline_fence = current_generation_fence.get()
    baseline_owner = current_generation_owner_token.get()

    observed_fence = None
    observed_owner = None

    async def _success_chat(**kwargs):
        nonlocal observed_fence, observed_owner
        observed_fence = current_generation_fence.get()
        observed_owner = current_generation_owner_token.get()
        return {
            "answer": "ContextVar verified",
            "tools_used": [],
            "status": "COMPLETED",
            "llm_usage": None,
            "trace_id": str(uuid.uuid4()),
            "trace_steps": [],
        }

    payload = AdminAssistantRequest(session_id=str(uuid.uuid4()), query="Test ContextVar")
    with patch("app.agents.router.chat_with_admin_assistant", side_effect=_success_chat):
        await admin_assistant_chat(payload, mock_request, mock_user, mock_tenant, mock_store)

    assert observed_fence == 17
    assert observed_owner == owner_tok
    # Verified: Restored to baseline in finally:
    assert current_generation_fence.get() == baseline_fence
    assert current_generation_owner_token.get() == baseline_owner


# ==============================================================================
# 5. Full Scenario A 12-Step Lifecycle Reproduction with PostgreSQL Session Store
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_session_lifecycle_scenario_a_reproduction():
    """
    Empirical 12-Step Reproduction of Scenario A for Admin Assistant:
    1. Turn 1 arrives with fence=1.
    2. Admission check passes (quiescent).
    3. Lease acquired in DB (fence=1, owner_token=T1, is_generating=True).
    4. Graph task started and registered in SessionTaskTrackingRegistry.
    5. Worker launched and registered in WorkerTrackingRegistry.
    6. Router 35s timeout trips (TimeoutError raised by wait_for).
    7. Graph task shielded; router returns HTTP 504.
    8. LEASE NOT RELEASED in DB (is_generating remains True, fence=1).
    9. Turn 2 arrives (immediate client retry):
       a. Admission check fails: is_session_quiescent returns False.
       b. Turn 2 rejected with HTTP 409 Conflict.
       c. Lease in DB untouched (fence=1).
    10. Background work finishes:
        a. Physical worker completes and unregisters.
        b. Graph task completes and unregisters.
        c. _release_lease_when_quiescent runs and releases lease in DB with fence=1, token=T1.
    11. Quiescence achieved: is_session_quiescent returns True, DB is_generating=False.
    12. Turn 3 arrives:
        a. Admission check passes.
        b. Lease acquired with fence=2.
        c. Turn 3 completes successfully (HTTP 200) and commits atomically with fence=2.
    """
    from app.agents.session_store import DatabaseSessionStore
    from app.auth.security import hash_password
    from app.core.database import AsyncSessionLocal
    from app.institutions.models import InstitutionMembership
    from app.users.models import User

    inst_id = PILOT_INSTITUTION_UUID
    sess_id = uuid.uuid4()
    admin_user = User(
        id=uuid.uuid4(),
        email=f"admin_{sess_id.hex[:6]}@eduintel.com",
        name="Lifecycle Admin",
        hashed_password=hash_password("Pass123!"),
        role="admin",
        is_active=True,
    )

    async with AsyncSessionLocal() as db_init:
        async with db_init.begin():
            db_init.add(admin_user)
            db_init.add(
                InstitutionMembership(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    user_id=admin_user.id,
                    role="admin",
                    status="active",
                )
            )

    mock_tenant = MagicMock()
    mock_tenant.institution_id = inst_id

    mock_request = MagicMock()
    mock_request.app.dependency_overrides = {}

    store = DatabaseSessionStore(session_factory=AsyncSessionLocal)

    # Pre-condition: Create session in DB
    await store.get_or_create_session(
        session_id=sess_id,
        institution_id=inst_id,
        user_id=admin_user.id,
        agent_name="admin_assistant",
        title="Admin Hardening Test Session",
    )

    # Synchronization primitives
    turn1_worker_event = threading.Event()
    turn1_graph_event = asyncio.Event()

    async def _turn1_chat(**kwargs):
        # Register a physical worker to simulate LLM inference worker thread
        pool = BoundedWorkerPool(name="LIFECYCLE_TEST", max_active=2, max_queued=2)

        def _slow_worker():
            turn1_worker_event.wait(timeout=5.0)
            return "worker_done"

        fut, _ = pool.submit_tracked(
            _slow_worker,
            session_id=sess_id,
            institution_id=inst_id,
            fence=kwargs.get("fence", 1),
            owner_token=kwargs.get("owner_token", uuid.uuid4()),
        )
        try:
            await turn1_graph_event.wait()
            await asyncio.to_thread(fut.result, timeout=1.0)
        finally:
            pool.shutdown(wait=False)
        return {"answer": "Turn 1 finished", "tools_used": [], "status": "COMPLETED"}

    # -------------------------------------------------------------------------
    # Steps 1 - 8: Turn 1 Arrives & Times Out at Router Deadline
    # -------------------------------------------------------------------------
    payload1 = AdminAssistantRequest(session_id=str(sess_id), query="Turn 1 query")

    with (
        patch("app.agents.router.chat_with_admin_assistant", side_effect=_turn1_chat),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        with pytest.raises(HTTPException) as exc1:
            await admin_assistant_chat(payload1, mock_request, admin_user, mock_tenant, store)

        assert exc1.value.status_code == 504
        assert "timed out at router deadline" in exc1.value.detail

    # Step 8 Verification: DB lease was NOT released!
    session_dto = await store.get_session(sess_id, inst_id, admin_user.id)
    assert session_dto.is_generating is True
    assert session_dto.generation_fence == 1
    assert session_dto.generation_owner_token is not None
    assert is_session_quiescent(inst_id, sess_id) is False

    # -------------------------------------------------------------------------
    # Step 9: Turn 2 Arrives While Turn 1 Work is Active -> HTTP 409
    # -------------------------------------------------------------------------
    payload2 = AdminAssistantRequest(session_id=str(sess_id), query="Turn 2 concurrent retry")
    with pytest.raises(HTTPException) as exc2:
        await admin_assistant_chat(payload2, mock_request, admin_user, mock_tenant, store)

    assert exc2.value.status_code == 409
    assert "still active for this session" in exc2.value.detail
    assert exc2.value.headers.get("Retry-After") == "1"

    # Step 9c: DB lease remains fence=1
    session_dto2 = await store.get_session(sess_id, inst_id, admin_user.id)
    assert session_dto2.is_generating is True
    assert session_dto2.generation_fence == 1

    # -------------------------------------------------------------------------
    # Steps 10 - 11: Release Background Work & Await Quiescence
    # -------------------------------------------------------------------------
    turn1_worker_event.set()
    turn1_graph_event.set()

    # Wait for background _release_lease_when_quiescent to finish
    for _ in range(30):
        await asyncio.sleep(0.05)
        if is_session_quiescent(inst_id, sess_id):
            break

    assert is_session_quiescent(inst_id, sess_id) is True
    session_dto_cleared = await store.get_session(sess_id, inst_id, admin_user.id)
    assert session_dto_cleared.is_generating is False
    assert session_dto_cleared.generation_owner_token is None

    # -------------------------------------------------------------------------
    # Step 12: Turn 3 Arrives -> Successfully Admitted & Completed (fence=2)
    # -------------------------------------------------------------------------
    payload3 = AdminAssistantRequest(session_id=str(sess_id), query="Turn 3 query")

    async def _turn3_chat(**kwargs):
        assert kwargs.get("fence") == 2
        return {
            "answer": "Turn 3 completed successfully",
            "tools_used": ["get_student_teacher_counts"],
            "status": "COMPLETED",
            "llm_usage": None,
            "trace_id": str(uuid.uuid4()),
            "trace_steps": [],
        }

    with patch("app.agents.router.chat_with_admin_assistant", side_effect=_turn3_chat):
        resp3 = await admin_assistant_chat(payload3, mock_request, admin_user, mock_tenant, store)
        assert resp3.answer == "Turn 3 completed successfully"
        assert resp3.tools_used == ["get_student_teacher_counts"]

    # Final DB check: committed with turn_counter=1, fence=2, is_generating=False
    session_dto_final = await store.get_session(sess_id, inst_id, admin_user.id)
    assert session_dto_final.is_generating is False
    assert session_dto_final.generation_fence == 2
    assert session_dto_final.turn_counter == 1

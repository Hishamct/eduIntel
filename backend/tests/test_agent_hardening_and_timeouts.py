"""
backend/tests/test_agent_hardening_and_timeouts.py

Deterministic test suite for Phase 5 Step 3.6 LangGraph Agent Hardening:
- Bounded worker pool capacity and admission control (HTTP 503).
- Independent physical executor future tracking vs coroutine cancellation.
- In-memory session quiescence barrier keyed by (institution_id, session_id).
- Thread-safe physical future callback handoff to asyncio event loop.
- Loop closure and error resilience.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import threading
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.worker_pool import (
    BoundedWorkerPool,
    WorkerCapacityExhaustedError,
    WorkerOperationTracker,
    WorkerTrackingRegistry,
    _physical_future_done_callback,
    get_chromadb_worker_pool,
    get_llm_worker_pool,
)


@pytest.fixture(autouse=True)
def clean_worker_and_task_registries():
    """Ensure WorkerTrackingRegistry and SessionTaskTrackingRegistry are clean before and after each test."""
    from app.agents.task_registry import SessionTaskTrackingRegistry

    WorkerTrackingRegistry.clear_for_testing()
    SessionTaskTrackingRegistry.clear_for_testing()
    yield
    WorkerTrackingRegistry.clear_for_testing()
    SessionTaskTrackingRegistry.clear_for_testing()


# ==============================================================================
# Category 1: Bounded Capacity Pools & Admission Control
# ==============================================================================


def test_global_worker_pools_configuration():
    """Verify global pools are configured according to specification."""
    llm_pool = get_llm_worker_pool()
    chroma_pool = get_chromadb_worker_pool()

    assert llm_pool.name == "LLM"
    assert llm_pool.max_active == 16
    assert llm_pool.max_queued == 32

    assert chroma_pool.name == "CHROMADB"
    assert chroma_pool.max_active == 8
    assert chroma_pool.max_queued == 16


def test_bounded_pool_capacity_reservation_and_release():
    """Verify slots are reserved and released deterministically."""
    pool = BoundedWorkerPool(name="TEST", max_active=2, max_queued=2)
    stats = pool.get_stats()
    assert stats["active"] == 0
    assert stats["queued"] == 0

    assert pool.try_reserve() is True
    assert pool.try_reserve() is True
    assert pool.try_reserve() is True
    assert pool.try_reserve() is True

    # 5th attempt exceeds max_active (2) + max_queued (2) = 4
    assert pool.try_reserve() is False

    pool.release_slot()
    # Now one slot is freed, so reservation succeeds
    assert pool.try_reserve() is True

    pool.shutdown(wait=False)


def test_bounded_queue_and_capacity_exhaustion_error():
    """Verify that submit_tracked raises WorkerCapacityExhaustedError when full."""
    pool = BoundedWorkerPool(name="TEST_EXHAUST", max_active=1, max_queued=1)

    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    release_event = threading.Event()

    def _slow_task():
        release_event.wait(timeout=2.0)
        return "done"

    # Task 1 (Active)
    fut1, _ = pool.submit_tracked(
        _slow_task,
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=uuid.uuid4(),
    )

    # Task 2 (Queued)
    fut2, _ = pool.submit_tracked(
        _slow_task,
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=uuid.uuid4(),
    )

    # Task 3 should be rejected immediately without blocking
    start = time.monotonic()
    with pytest.raises(WorkerCapacityExhaustedError) as exc_info:
        pool.submit_tracked(
            _slow_task,
            session_id=sess_id,
            institution_id=inst_id,
            fence=1,
            owner_token=uuid.uuid4(),
        )
    duration = time.monotonic() - start

    assert duration < 0.1  # Fail-fast non-blocking
    assert exc_info.value.pool_name == "TEST_EXHAUST"
    assert exc_info.value.retry_after == 5

    # Unblock threads and clean up
    release_event.set()
    fut1.result(timeout=1.0)
    fut2.result(timeout=1.0)
    pool.shutdown(wait=True)


# ==============================================================================
# Category 2: In-Memory Quiescence Barrier & Composite Keying
# ==============================================================================


def test_worker_tracking_registry_composite_keys():
    """Verify WorkerTrackingRegistry is strictly keyed by (institution_id, session_id)."""
    inst_a = uuid.uuid4()
    inst_b = uuid.uuid4()
    sess_id = uuid.uuid4()  # Same session UUID for testing collision isolation

    tracker_a = WorkerOperationTracker(
        operation_id="op_a",
        session_id=sess_id,
        institution_id=inst_a,
        fence=1,
        owner_token=uuid.uuid4(),
        pool_name="LLM",
        executor_future=concurrent.futures.Future(),
        pool=MagicMock(),
    )

    assert WorkerTrackingRegistry.is_session_quiescent(inst_a, sess_id) is True
    assert WorkerTrackingRegistry.is_session_quiescent(inst_b, sess_id) is True

    WorkerTrackingRegistry.register_worker(tracker_a)

    # Inst A is busy, but Inst B remains quiescent!
    assert WorkerTrackingRegistry.is_session_quiescent(inst_a, sess_id) is False
    assert WorkerTrackingRegistry.is_session_quiescent(inst_b, sess_id) is True
    assert WorkerTrackingRegistry.get_session_active_count(inst_a, sess_id) == 1
    assert WorkerTrackingRegistry.get_session_active_count(inst_b, sess_id) == 0

    WorkerTrackingRegistry.unregister_worker("op_a")

    assert WorkerTrackingRegistry.is_session_quiescent(inst_a, sess_id) is True
    assert WorkerTrackingRegistry.get_session_active_count(inst_a, sess_id) == 0


def test_session_quiescence_with_multiple_workers():
    """Verify session is only quiescent when ALL registered workers finish."""
    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()

    tracker1 = WorkerOperationTracker(
        operation_id="op_1",
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=uuid.uuid4(),
        pool_name="CHROMADB",
        executor_future=concurrent.futures.Future(),
        pool=MagicMock(),
    )
    tracker2 = WorkerOperationTracker(
        operation_id="op_2",
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=uuid.uuid4(),
        pool_name="LLM",
        executor_future=concurrent.futures.Future(),
        pool=MagicMock(),
    )

    WorkerTrackingRegistry.register_worker(tracker1)
    WorkerTrackingRegistry.register_worker(tracker2)

    assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is False
    assert WorkerTrackingRegistry.get_session_active_count(inst_id, sess_id) == 2

    # Worker 1 finishes; session must STILL be non-quiescent
    WorkerTrackingRegistry.unregister_worker("op_1")
    assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is False
    assert WorkerTrackingRegistry.get_session_active_count(inst_id, sess_id) == 1

    # Worker 2 finishes; session becomes quiescent
    WorkerTrackingRegistry.unregister_worker("op_2")
    assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is True
    assert WorkerTrackingRegistry.get_session_active_count(inst_id, sess_id) == 0


# ==============================================================================
# Category 3: Physical Worker Independence & Coroutine Timeout
# ==============================================================================


@pytest.mark.asyncio
async def test_coroutine_completing_before_physical_worker():
    """
    Verify that when an awaiting coroutine times out, the underlying
    OS worker thread continues executing safely without crash.
    """
    pool = BoundedWorkerPool(name="TEST_INDEP", max_active=2, max_queued=2)
    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    worker_finished = threading.Event()

    def _worker():
        time.sleep(0.15)
        worker_finished.set()
        return "physical_success"

    fut, tracker = pool.submit_tracked(
        _worker,
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=uuid.uuid4(),
    )

    # Coroutine awaits with short deadline (0.05s)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.wrap_future(fut), timeout=0.05)

    tracker.is_abandoned = True

    # Coroutine timed out, but physical worker thread is still active!
    assert tracker.is_physical_worker_active() is True
    assert not worker_finished.is_set()

    # Wait for physical thread to finish
    await asyncio.to_thread(worker_finished.wait, timeout=1.0)
    assert worker_finished.is_set()
    assert fut.result() == "physical_success"
    assert tracker.is_physical_worker_active() is False

    pool.shutdown(wait=True)


# ==============================================================================
# Category 4: Safe Physical Future Callback Handoff
# ==============================================================================


def test_physical_future_done_callback_exactly_once():
    """Verify done callback schedules async cleanup exactly once."""
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    mock_loop.is_closed.return_value = False

    mock_pool = MagicMock()
    fut = concurrent.futures.Future()
    fut.set_result("ok")

    tracker = WorkerOperationTracker(
        operation_id="op_once",
        session_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        fence=1,
        owner_token=uuid.uuid4(),
        pool_name="LLM",
        executor_future=fut,
        pool=mock_pool,
        is_abandoned=True,
    )
    WorkerTrackingRegistry.register_worker(tracker)

    # First invocation
    _physical_future_done_callback(
        fut=fut,
        tracker=tracker,
        loop=mock_loop,
        session_factory=MagicMock(),
    )
    assert mock_loop.call_soon_threadsafe.call_count == 1
    assert mock_pool.release_slot.call_count == 1

    # Duplicate invocation (simulated race)
    _physical_future_done_callback(
        fut=fut,
        tracker=tracker,
        loop=mock_loop,
        session_factory=MagicMock(),
    )
    # call_soon_threadsafe NOT called again
    assert mock_loop.call_soon_threadsafe.call_count == 1


def test_callback_behavior_during_event_loop_shutdown():
    """Verify that loop closure does not raise unhandled exceptions in callback."""
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = False
    mock_loop.is_closed.return_value = True

    mock_pool = MagicMock()
    fut = concurrent.futures.Future()
    fut.set_result("ok")

    tracker = WorkerOperationTracker(
        operation_id="op_shutdown",
        session_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        fence=1,
        owner_token=uuid.uuid4(),
        pool_name="LLM",
        executor_future=fut,
        pool=mock_pool,
        is_abandoned=True,
    )
    WorkerTrackingRegistry.register_worker(tracker)

    # Should not raise exception
    _physical_future_done_callback(
        fut=fut,
        tracker=tracker,
        loop=mock_loop,
        session_factory=MagicMock(),
    )

    assert mock_pool.release_slot.call_count == 1
    assert mock_loop.call_soon_threadsafe.call_count == 0


@pytest.mark.asyncio
async def test_all_stage1_tests_execute_subsecond():
    """Verify deterministic, rapid execution of worker pool test suite."""
    start = time.monotonic()
    pool = BoundedWorkerPool(name="SPEED", max_active=2, max_queued=2)
    fut, _ = pool.submit_tracked(
        lambda: 42,
        session_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        fence=1,
        owner_token=uuid.uuid4(),
    )
    res = await asyncio.wrap_future(fut)
    assert res == 42
    pool.shutdown(wait=True)
    assert (time.monotonic() - start) < 0.2


# ==============================================================================
# Category 5: Portal Assistant Hardening, Timeouts & Router Barriers (Stage 2)
# ==============================================================================


@pytest.mark.asyncio
async def test_portal_assistant_async_execution_and_recursion_limit():
    """Verify that chat_with_portal_assistant runs asynchronously and enforces recursion limit <= 5."""
    from app.agents.portal_assistant import chat_with_portal_assistant

    with patch("app.agents.portal_assistant.portal_assistant_graph.ainvoke") as mock_ainvoke:
        mock_ainvoke.return_value = {
            "query": "How do I reset password?",
            "history": [],
            "retrieved_context": "Help doc",
            "is_relevant": True,
            "answer": "Go to settings.",
            "grounded": True,
            "llm_usage": None,
            "trace_steps": [],
            "socratic_instruction": "",
            "is_blocked": False,
            "block_reason": None,
            "status": "COMPLETED",
        }

        coro = chat_with_portal_assistant(
            session_id=str(uuid.uuid4()),
            query="How do I reset password?",
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )
        assert inspect.iscoroutine(coro)
        res = await coro

        assert res["answer"] == "Go to settings."
        assert res["grounded"] is True
        assert res["blocked"] is False
        assert mock_ainvoke.call_count == 1
        call_config = mock_ainvoke.call_args[1].get("config", {})
        assert call_config.get("recursion_limit") <= 5


@pytest.mark.asyncio
async def test_portal_assistant_chromadb_timeout_graceful_fallback():
    """Verify that ChromaDB queries exceeding 4.0s timeout gracefully degrade to fallback context."""
    from app.agents.portal_assistant import retrieve_node

    sess_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    state = {
        "query": "Where is my dashboard?",
        "history": [],
        "retrieved_context": "",
        "is_relevant": True,
        "answer": "",
        "grounded": False,
        "llm_usage": None,
        "trace_steps": [],
        "socratic_instruction": "",
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "session_id": sess_id,
        "institution_id": inst_id,
        "generation_fence": 1,
        "generation_owner_token": uuid.uuid4(),
    }

    with patch("asyncio.wait_for", side_effect=TimeoutError()):
        out_state = await retrieve_node(state)

        assert out_state["is_relevant"] is False
        assert "retrieval timeout" in out_state["retrieved_context"]


@pytest.mark.asyncio
async def test_portal_assistant_llm_timeout_graceful_degradation():
    """Verify that LLM generation exceeding 23.0s returns structured failure (status=FAILED, blocked=False)."""
    from app.agents.portal_assistant import generate_node

    sess_id = uuid.uuid4()
    inst_id = uuid.uuid4()

    state = {
        "query": "Where is my dashboard?",
        "history": [],
        "retrieved_context": "Help doc content",
        "is_relevant": True,
        "answer": "",
        "grounded": False,
        "llm_usage": None,
        "trace_steps": [],
        "socratic_instruction": "",
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "session_id": sess_id,
        "institution_id": inst_id,
        "generation_fence": 1,
        "generation_owner_token": uuid.uuid4(),
    }

    with patch("asyncio.wait_for", side_effect=TimeoutError()):
        out_state = await generate_node(state)

        assert out_state["status"] == "FAILED"
        assert out_state["is_blocked"] is False
        assert out_state["block_reason"] == "timeout"
        assert "took too long" in out_state["answer"]


@pytest.mark.asyncio
async def test_router_rejects_admission_when_abandoned_worker_active():
    """
    Mandatory Directive 1: Router MUST check WorkerTrackingRegistry.is_session_quiescent
    BEFORE calling reserve_generation_lease, rejecting with HTTP 409 (Retry-After: 1).
    """
    from fastapi import HTTPException

    from app.agents.router import portal_assistant_chat
    from app.agents.schemas import PortalAssistantRequest

    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()

    # Register an active worker tracker in the in-memory registry
    active_tracker = WorkerOperationTracker(
        operation_id="active_abandoned_worker",
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=uuid.uuid4(),
        pool_name="CHROMADB",
        executor_future=concurrent.futures.Future(),
        pool=MagicMock(),
        is_abandoned=True,
    )
    WorkerTrackingRegistry.register_worker(active_tracker)

    # Prepare mocked request dependencies
    mock_request = MagicMock()
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_tenant = MagicMock()
    mock_tenant.institution_id = inst_id

    mock_store = MagicMock()

    payload = PortalAssistantRequest(
        session_id=str(sess_id),
        query="Are you available?",
    )

    with pytest.raises(HTTPException) as exc_info:
        await portal_assistant_chat(
            payload=payload,
            request=mock_request,
            current_user=mock_user,
            tenant=mock_tenant,
            store=mock_store,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.headers.get("Retry-After") == "1"
    assert "Previous generation workers are still active" in exc_info.value.detail
    # Store's reserve_generation_lease must NOT have been called!
    assert mock_store.reserve_generation_lease.call_count == 0


@pytest.mark.asyncio
async def test_router_returns_503_on_worker_pool_capacity_exhaustion():
    """Verify router catches WorkerCapacityExhaustedError, releases lease, and raises HTTP 503."""
    from fastapi import HTTPException

    from app.agents.router import portal_assistant_chat
    from app.agents.schemas import PortalAssistantRequest

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
    mock_store.release_generation_lease = AsyncMock()

    payload = PortalAssistantRequest(
        session_id=str(sess_id),
        query="Help me please",
    )

    with patch(
        "app.agents.router.chat_with_portal_assistant",
        side_effect=WorkerCapacityExhaustedError("LLM", retry_after=5),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await portal_assistant_chat(
                payload=payload,
                request=mock_request,
                current_user=mock_user,
                tenant=mock_tenant,
                store=mock_store,
            )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers.get("Retry-After") == "5"
    # Lease must be safely released
    mock_store.release_generation_lease.assert_called_once_with(
        session_id=sess_id,
        institution_id=inst_id,
        user_id=mock_user.id,
        fence=1,
        owner_token=owner_tok,
    )


@pytest.mark.asyncio
async def test_router_gateway_timeout_on_35s_deadline():
    """
    Verify router catches 35s timeout, raises HTTP 504, does NOT release lease prematurely
    while shielded graph task is still running, blocks concurrent request with 409,
    and safely releases lease only after the background task completes.
    """
    from fastapi import HTTPException

    from app.agents.router import portal_assistant_chat
    from app.agents.schemas import PortalAssistantRequest
    from app.agents.task_registry import is_session_quiescent

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
    mock_store.release_generation_lease = AsyncMock()

    payload = PortalAssistantRequest(
        session_id=str(sess_id),
        query="Help me please",
    )

    finish_chat = asyncio.Event()

    async def _hanging_chat(**kwargs):
        await finish_chat.wait()
        return {
            "answer": "Finally done",
            "grounded": True,
            "llm_usage": None,
            "trace_id": str(uuid.uuid4()),
            "trace_steps": [],
        }

    with (
        patch("app.agents.router.chat_with_portal_assistant", side_effect=_hanging_chat),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await portal_assistant_chat(
                payload=payload,
                request=mock_request,
                current_user=mock_user,
                tenant=mock_tenant,
                store=mock_store,
            )

    assert exc_info.value.status_code == 504
    assert "router deadline" in exc_info.value.detail

    # CRIT-3.6-S2-01 & LOW-3.6-S2-01: Lease must NOT have been released prematurely!
    mock_store.release_generation_lease.assert_not_called()
    assert is_session_quiescent(inst_id, sess_id) is False

    # Subsequent request arriving while background task is alive must be rejected with 409
    payload2 = PortalAssistantRequest(
        session_id=str(sess_id),
        query="Second attempt",
    )
    with pytest.raises(HTTPException) as conflict_exc:
        await portal_assistant_chat(
            payload=payload2,
            request=mock_request,
            current_user=mock_user,
            tenant=mock_tenant,
            store=mock_store,
        )
    assert conflict_exc.value.status_code == 409
    assert "Previous generation workers are still active" in conflict_exc.value.detail

    # Finish the background task
    finish_chat.set()
    await asyncio.sleep(0.05)  # Yield to allow task done callback and background watcher to run

    # Now lease is safely released with matching fence and owner_token
    mock_store.release_generation_lease.assert_called_once_with(
        session_id=sess_id,
        institution_id=inst_id,
        user_id=mock_user.id,
        fence=1,
        owner_token=owner_tok,
    )
    assert is_session_quiescent(inst_id, sess_id) is True


@pytest.mark.asyncio
async def test_advisory_f_3_6_s1_01_lease_release_when_worker_completes_after_timeout():
    """
    Advisory F-3.6-S1-01 Verification:
    When a worker outlives the graph await deadline (tracker.is_abandoned = True),
    its done callback safely unregisters from the quiescence registry and schedules
    _schedule_async_cleanup on the event loop, releasing the generation lease.
    """
    loop = asyncio.get_running_loop()
    mock_session_factory = MagicMock()
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)
    mock_db.begin = MagicMock(return_value=mock_db)
    mock_session_factory.return_value = mock_db

    pool = BoundedWorkerPool(name="ADV_TEST", max_active=2, max_queued=2)
    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    owner_tok = uuid.uuid4()
    worker_finished = threading.Event()

    def _worker():
        time.sleep(0.08)
        worker_finished.set()
        return "late_ok"

    fut, tracker = pool.submit_tracked(
        _worker,
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=owner_tok,
        loop=loop,
        session_factory=mock_session_factory,
    )

    # Mark as abandoned (simulating graph node timeout)
    tracker.is_abandoned = True

    # While worker is running: session is non-quiescent
    assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is False

    # Await physical worker completion
    await asyncio.to_thread(worker_finished.wait, timeout=1.0)
    # Give event loop a cycle to run the scheduled async cleanup
    await asyncio.sleep(0.05)

    # Session MUST now be quiescent
    assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is True
    # Async cleanup task was executed
    assert mock_db.execute.call_count >= 1

    pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_portal_assistant_worker_capacity_exhaustion_in_nodes():
    """Verify nodes handle WorkerCapacityExhaustedError by returning graceful fallbacks."""
    from app.agents.portal_assistant import generate_node, retrieve_node

    state = {
        "query": "Where is my dashboard?",
        "history": [],
        "retrieved_context": "Help doc content",
        "is_relevant": True,
        "answer": "",
        "grounded": False,
        "llm_usage": None,
        "trace_steps": [],
        "socratic_instruction": "",
        "is_blocked": False,
        "block_reason": None,
        "status": "RUNNING",
        "session_id": uuid.uuid4(),
        "institution_id": uuid.uuid4(),
        "generation_fence": 1,
        "generation_owner_token": uuid.uuid4(),
    }

    # Test ChromaDB pool capacity exhaustion in retrieve_node
    with patch(
        "app.agents.portal_assistant.CHROMADB_WORKER_POOL.submit_tracked",
        side_effect=WorkerCapacityExhaustedError("CHROMADB", retry_after=5),
    ):
        ret_state = await retrieve_node(state)
        assert ret_state["is_relevant"] is False
        assert "capacity full" in ret_state["retrieved_context"]

    # Test LLM pool capacity exhaustion in generate_node
    with patch(
        "app.agents.portal_assistant.LLM_WORKER_POOL.submit_tracked",
        side_effect=WorkerCapacityExhaustedError("LLM", retry_after=5),
    ):
        gen_state = await generate_node(state)
        assert gen_state["status"] == "FAILED"
        assert gen_state["block_reason"] == "worker_capacity_exhausted"
        assert "high demand" in gen_state["answer"]


@pytest.mark.asyncio
async def test_portal_assistant_graph_recursion_error_handling():
    """Verify graph recursion limit is caught and returns structured loop notice without crash."""
    from langgraph.errors import GraphRecursionError

    from app.agents.portal_assistant import chat_with_portal_assistant

    with patch(
        "app.agents.portal_assistant.portal_assistant_graph.ainvoke",
        side_effect=GraphRecursionError("Recursion limit of 5 reached without hitting a stop condition."),
    ):
        coro = chat_with_portal_assistant(
            session_id=str(uuid.uuid4()),
            query="Loop test",
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )
        res = await coro
        assert res["status"] == "FAILED"
        assert res["block_reason"] == "recursion_limit"
        assert "internal loop" in res["answer"]


def test_portal_assistant_preserves_dual_sync_compatibility():
    """Verify sync callers receive a dictionary directly without needing await."""
    from unittest.mock import AsyncMock, patch

    from app.agents.portal_assistant import chat_with_portal_assistant

    with patch(
        "app.agents.portal_assistant.portal_assistant_graph.ainvoke",
        new_callable=AsyncMock,
    ) as mock_ainvoke:
        mock_ainvoke.return_value = {
            "answer": "Sync answer",
            "grounded": True,
            "llm_usage": None,
            "trace_steps": [],
            "status": "COMPLETED",
        }

        res = chat_with_portal_assistant(
            session_id="sync-test-session",
            query="Sync query",
            tenant_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )

        assert not inspect.iscoroutine(res)
        assert isinstance(res, dict)
        assert res["answer"] == "Sync answer"
        assert mock_ainvoke.call_count == 1


# ==============================================================================
# Category 4: Stage 2R Remediations (Task Registry, ContextVars & Unified Quiescence)
# ==============================================================================


@pytest.mark.asyncio
async def test_unified_quiescence_evaluates_both_workers_and_tasks():
    """
    Verify unified is_session_quiescent returns:
    - False when only a physical worker thread is active.
    - False when only an asyncio graph task is active.
    - False when both are active.
    - True only when neither is active.
    """
    from app.agents.task_registry import SessionTaskTrackingRegistry, is_session_quiescent

    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()

    # Initial state: completely quiescent
    assert is_session_quiescent(inst_id, sess_id) is True

    # 1. Physical worker active only
    pool = BoundedWorkerPool(name="TEST_UNI_W", max_active=2, max_queued=2)
    worker_event = threading.Event()

    def _worker():
        worker_event.wait(timeout=1.0)
        return "w_done"

    fut, _ = pool.submit_tracked(
        _worker,
        session_id=sess_id,
        institution_id=inst_id,
        fence=1,
        owner_token=uuid.uuid4(),
    )
    try:
        assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is False
        assert SessionTaskTrackingRegistry.is_task_quiescent(inst_id, sess_id) is True
        assert is_session_quiescent(inst_id, sess_id) is False

        # 2. Both worker and asyncio task active
        task_event = asyncio.Event()

        async def _async_task():
            await task_event.wait()
            return "t_done"

        active_task = asyncio.create_task(_async_task())
        SessionTaskTrackingRegistry.register_task(
            institution_id=inst_id,
            session_id=sess_id,
            task=active_task,
            fence=1,
            owner_token=uuid.uuid4(),
        )

        assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is False
        assert SessionTaskTrackingRegistry.is_task_quiescent(inst_id, sess_id) is False
        assert is_session_quiescent(inst_id, sess_id) is False

        # 3. Release worker -> only asyncio task active
        worker_event.set()
        await asyncio.to_thread(fut.result, timeout=1.0)
        await asyncio.sleep(0.02)

        assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is True
        assert SessionTaskTrackingRegistry.is_task_quiescent(inst_id, sess_id) is False
        assert is_session_quiescent(inst_id, sess_id) is False

        # 4. Release asyncio task -> neither active
        task_event.set()
        await active_task
        await asyncio.sleep(0.02)

        assert WorkerTrackingRegistry.is_session_quiescent(inst_id, sess_id) is True
        assert SessionTaskTrackingRegistry.is_task_quiescent(inst_id, sess_id) is True
        assert is_session_quiescent(inst_id, sess_id) is True
    finally:
        pool.shutdown(wait=False)


@pytest.mark.asyncio
async def test_task_registry_lifecycle_normal_exception_cancellation():
    """
    Verify SessionTaskTrackingRegistry automatically unregisters tasks on:
    1. Normal completion
    2. Unhandled exception in task
    3. Task cancellation
    """
    from app.agents.task_registry import SessionTaskTrackingRegistry

    inst_id = uuid.uuid4()
    sess_id = uuid.uuid4()

    # Scenario 1: Normal completion
    async def _normal():
        await asyncio.sleep(0.01)
        return "ok"

    t1 = asyncio.create_task(_normal())
    SessionTaskTrackingRegistry.register_task(inst_id, sess_id, t1, fence=1)
    assert len(SessionTaskTrackingRegistry.get_active_tasks(inst_id, sess_id)) == 1
    await t1
    await asyncio.sleep(0.01)
    assert len(SessionTaskTrackingRegistry.get_active_tasks(inst_id, sess_id)) == 0
    assert SessionTaskTrackingRegistry.is_task_quiescent(inst_id, sess_id) is True

    # Scenario 2: Exception in task
    async def _failing():
        await asyncio.sleep(0.01)
        raise ValueError("Task boom")

    t2 = asyncio.create_task(_failing())
    SessionTaskTrackingRegistry.register_task(inst_id, sess_id, t2, fence=2)
    assert len(SessionTaskTrackingRegistry.get_active_tasks(inst_id, sess_id)) == 1
    with pytest.raises(ValueError, match="Task boom"):
        await t2
    await asyncio.sleep(0.01)
    assert len(SessionTaskTrackingRegistry.get_active_tasks(inst_id, sess_id)) == 0
    assert SessionTaskTrackingRegistry.is_task_quiescent(inst_id, sess_id) is True

    # Scenario 3: Task cancellation
    async def _hanging():
        await asyncio.sleep(10.0)

    t3 = asyncio.create_task(_hanging())
    SessionTaskTrackingRegistry.register_task(inst_id, sess_id, t3, fence=3)
    assert len(SessionTaskTrackingRegistry.get_active_tasks(inst_id, sess_id)) == 1
    t3.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t3
    await asyncio.sleep(0.01)
    assert len(SessionTaskTrackingRegistry.get_active_tasks(inst_id, sess_id)) == 0
    assert SessionTaskTrackingRegistry.is_task_quiescent(inst_id, sess_id) is True


@pytest.mark.asyncio
async def test_contextvar_token_reset_on_success_error_timeout():
    """
    Verify ContextVars (current_generation_fence, current_generation_owner_token)
    are properly set during execution and restored to prior values via .reset(token)
    on:
    1. Normal success
    2. Router 35s timeout
    3. Unhandled exception
    """
    from fastapi import HTTPException

    from app.agents.portal_assistant import current_generation_fence, current_generation_owner_token
    from app.agents.router import portal_assistant_chat
    from app.agents.schemas import PortalAssistantRequest

    inst_id = uuid.uuid4()
    owner_tok = uuid.uuid4()

    mock_request = MagicMock()
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_tenant = MagicMock()
    mock_tenant.institution_id = inst_id

    mock_lease = MagicMock()
    mock_lease.fence = 42
    mock_lease.owner_token = owner_tok
    mock_lease.is_cached = False
    mock_lease.cached_response = None
    mock_lease.history = []

    mock_store = MagicMock()
    mock_store.get_or_create_session = AsyncMock()
    mock_store.reserve_generation_lease = AsyncMock(return_value=mock_lease)
    mock_store.commit_turn_atomic = AsyncMock()
    mock_store.release_generation_lease = AsyncMock()

    # Baseline before test
    baseline_fence = current_generation_fence.get()
    baseline_owner = current_generation_owner_token.get()

    # Test 1: Normal success
    observed_fence = None
    observed_owner = None

    async def _success_chat(**kwargs):
        nonlocal observed_fence, observed_owner
        observed_fence = current_generation_fence.get()
        observed_owner = current_generation_owner_token.get()
        return {
            "answer": "ContextVar verified",
            "grounded": True,
            "llm_usage": None,
            "trace_id": str(uuid.uuid4()),
            "trace_steps": [],
        }

    payload1 = PortalAssistantRequest(session_id=str(uuid.uuid4()), query="Context test 1")
    with patch("app.agents.router.chat_with_portal_assistant", side_effect=_success_chat):
        await portal_assistant_chat(payload1, mock_request, mock_user, mock_tenant, mock_store)

    assert observed_fence == 42
    assert observed_owner == owner_tok
    # After normal completion: must be reset to baseline!
    assert current_generation_fence.get() == baseline_fence
    assert current_generation_owner_token.get() == baseline_owner

    # Test 2: Router 35s timeout
    payload2 = PortalAssistantRequest(session_id=str(uuid.uuid4()), query="Context test 2")
    with (
        patch("app.agents.router.chat_with_portal_assistant", side_effect=_success_chat),
        patch("asyncio.wait_for", side_effect=TimeoutError()),
    ):
        with pytest.raises(HTTPException) as exc:
            await portal_assistant_chat(payload2, mock_request, mock_user, mock_tenant, mock_store)
        assert exc.value.status_code == 504

    # After timeout: must be reset to baseline!
    assert current_generation_fence.get() == baseline_fence
    assert current_generation_owner_token.get() == baseline_owner

    # Test 3: Unhandled exception
    async def _exploding_chat(**kwargs):
        raise RuntimeError("LLM exploded")

    payload3 = PortalAssistantRequest(session_id=str(uuid.uuid4()), query="Context test 3")
    with patch("app.agents.router.chat_with_portal_assistant", side_effect=_exploding_chat):
        with pytest.raises(RuntimeError, match="LLM exploded"):
            await portal_assistant_chat(payload3, mock_request, mock_user, mock_tenant, mock_store)

    # After exception: must be reset to baseline!
    assert current_generation_fence.get() == baseline_fence
    assert current_generation_owner_token.get() == baseline_owner

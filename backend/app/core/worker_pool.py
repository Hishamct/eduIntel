"""
backend/app/core/worker_pool.py

Bounded worker pool infrastructure for Phase 5 Step 3.6:
- Thread-safe capacity partitioning (LLMWorkerPool, ChromaDBWorkerPool).
- Non-blocking admission control raising WorkerCapacityExhaustedError (HTTP 503).
- Independent physical executor future tracking decoupled from coroutine cancellation.
- Rule of Zero Cross-Thread Awaits: safe handoff to event loop via loop.call_soon_threadsafe().
- In-memory session quiescence barrier keyed by (institution_id, session_id).
- Fenced conditional cleanup preserving PostgreSQL lease tokens and tenant isolation.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import functools
import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from sqlalchemy import func, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.models import AgentSession
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Strong reference retention for asynchronous cleanup tasks running on the event loop
_RETAINED_CLEANUP_TASKS: set[asyncio.Task[Any]] = set()


class WorkerCapacityExhaustedError(Exception):
    """
    Raised immediately when a bounded worker pool has reached maximum active
    and queued capacity. Prevents unbounded thread allocation and queuing.
    """

    def __init__(self, pool_name: str, retry_after: int = 5):
        self.pool_name = pool_name
        self.retry_after = retry_after
        super().__init__(f"{pool_name} worker capacity exhausted. Please retry after {retry_after} seconds.")


@dataclass
class WorkerOperationTracker:
    """
    Tracks an individual physical OS worker operation independently from
    the asyncio coroutine awaiting it.
    """

    operation_id: str
    session_id: uuid.UUID
    institution_id: uuid.UUID
    fence: int
    owner_token: uuid.UUID
    pool_name: str
    executor_future: concurrent.futures.Future[Any]
    pool: BoundedWorkerPool
    created_at: float = field(default_factory=time.monotonic)
    is_abandoned: bool = False
    cleanup_scheduled: bool = False
    cleanup_lock: threading.Lock = field(default_factory=threading.Lock)

    def is_physical_worker_active(self) -> bool:
        """Returns True if the underlying OS thread is still executing."""
        return not self.executor_future.done()


class WorkerTrackingRegistry:
    """
    Process-wide, thread-safe registry tracking active physical workers.
    Provides session-level quiescence guarantees keyed by (institution_id, session_id).
    """

    _active_workers: dict[str, WorkerOperationTracker] = {}
    _session_active_count: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    _lock = threading.Lock()

    @classmethod
    def register_worker(cls, tracker: WorkerOperationTracker) -> None:
        """Registers an active worker tracker under its operation_id and tenant session key."""
        session_key = (tracker.institution_id, tracker.session_id)
        with cls._lock:
            cls._active_workers[tracker.operation_id] = tracker
            cls._session_active_count[session_key] += 1

    @classmethod
    def unregister_worker(cls, operation_id: str) -> None:
        """Unregisters a completed or terminated worker tracker."""
        with cls._lock:
            tracker = cls._active_workers.pop(operation_id, None)
            if tracker:
                session_key = (tracker.institution_id, tracker.session_id)
                current = cls._session_active_count.get(session_key, 0)
                if current <= 1:
                    cls._session_active_count.pop(session_key, None)
                else:
                    cls._session_active_count[session_key] = current - 1

    @classmethod
    def is_session_quiescent(cls, institution_id: uuid.UUID, session_id: uuid.UUID) -> bool:
        """
        Returns True ONLY when zero physical worker threads are active
        for the given (institution_id, session_id) pair.
        """
        session_key = (institution_id, session_id)
        with cls._lock:
            return cls._session_active_count.get(session_key, 0) == 0

    @classmethod
    def get_session_active_count(cls, institution_id: uuid.UUID, session_id: uuid.UUID) -> int:
        """Returns the number of in-flight physical workers for a session."""
        session_key = (institution_id, session_id)
        with cls._lock:
            return cls._session_active_count.get(session_key, 0)

    @classmethod
    def get_active_worker_count(cls, pool_name: str | None = None) -> int:
        """Returns total active workers, optionally filtered by pool name."""
        with cls._lock:
            if pool_name is None:
                return len(cls._active_workers)
            return sum(1 for w in cls._active_workers.values() if w.pool_name == pool_name)

    @classmethod
    def clear_for_testing(cls) -> None:
        """Test helper to reset tracking state between tests."""
        with cls._lock:
            cls._active_workers.clear()
            cls._session_active_count.clear()


def _schedule_async_cleanup(
    loop: asyncio.AbstractEventLoop,
    tracker: WorkerOperationTracker,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """
    Executes on the asyncio event loop to asynchronously release an abandoned lease
    using a fresh, tenant-scoped AsyncSession.
    """

    async def _async_cleanup() -> None:
        if not tracker.is_abandoned:
            return

        try:
            async with session_factory() as db:
                async with db.begin():
                    # Enforce tenant isolation via PostgreSQL RLS session setting
                    await db.execute(
                        text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                        {"inst_id": str(tracker.institution_id)},
                    )

                    # Conditional update matching exact generation fence and owner token
                    stmt = (
                        update(AgentSession)
                        .where(
                            AgentSession.id == tracker.session_id,
                            AgentSession.institution_id == tracker.institution_id,
                            AgentSession.generation_fence == tracker.fence,
                            AgentSession.generation_owner_token == tracker.owner_token,
                            AgentSession.is_generating.is_(True),
                        )
                        .values(
                            is_generating=False,
                            generation_owner_token=None,
                            active_client_turn_id=None,
                            last_accessed_at=func.clock_timestamp(),
                        )
                    )
                    res = await db.execute(stmt)
                    if res.rowcount > 0:
                        logger.info(
                            "[Worker Pool] Released abandoned generation lease for session %s (fence=%d)",
                            tracker.session_id,
                            tracker.fence,
                        )
        except Exception as e:
            logger.error(
                "[Worker Pool] Error during async lease release for session %s: %s",
                tracker.session_id,
                e,
            )

    cleanup_task = loop.create_task(_async_cleanup())
    _RETAINED_CLEANUP_TASKS.add(cleanup_task)
    cleanup_task.add_done_callback(_RETAINED_CLEANUP_TASKS.discard)


def _physical_future_done_callback(
    fut: concurrent.futures.Future[Any],
    tracker: WorkerOperationTracker,
    loop: asyncio.AbstractEventLoop | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """
    Executes strictly on the physical OS worker thread inside ThreadPoolExecutor
    upon task termination (successful return, exception, or timeout).
    Never accesses AsyncSession or executes async coroutines directly.
    """
    # 1. Thread-safe pool capacity cleanup
    tracker.pool.release_slot()

    # 2. Consume exception / result thread-safely to avoid unretrieved warnings
    exc = None
    try:
        exc = fut.exception()
    except Exception as e:
        exc = e

    if exc and tracker.is_abandoned:
        logger.warning(
            "[Worker Pool] Abandoned worker %s finished with exception: %s",
            tracker.operation_id,
            exc,
        )

    # 3. Unregister from in-memory tracking registry
    WorkerTrackingRegistry.unregister_worker(tracker.operation_id)

    # 4. Atomic exactly-once check for scheduling async lease release
    with tracker.cleanup_lock:
        if tracker.cleanup_scheduled:
            return
        tracker.cleanup_scheduled = True

    # Only abandoned workers need lease release cleanup (normal completions are committed or handled)
    if not tracker.is_abandoned:
        return

    # 5. Thread-safe handoff to asyncio event loop
    if loop is not None:
        try:
            if loop.is_running() and not loop.is_closed():
                loop.call_soon_threadsafe(
                    _schedule_async_cleanup,
                    loop,
                    tracker,
                    session_factory,
                )
            else:
                logger.warning(
                    "[Worker Pool] Event loop closed before cleanup could be scheduled for session %s",
                    tracker.session_id,
                )
        except RuntimeError as re:
            logger.warning(
                "[Worker Pool] Failed to schedule cleanup on closed event loop for session %s: %s",
                tracker.session_id,
                re,
            )


class BoundedWorkerPool:
    """
    Bounded worker pool with non-blocking admission checks, capacity limits,
    and tracked physical execution.
    """

    def __init__(self, name: str, max_active: int, max_queued: int):
        self.name = name
        self.max_active = max_active
        self.max_queued = max_queued
        self._active_count = 0
        self._queued_count = 0
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_active,
            thread_name_prefix=f"{name.lower()}_worker_",
        )

    def try_reserve(self) -> bool:
        """
        Atomically checks capacity and reserves an admission slot without blocking.
        Returns True if admitted, False if pool capacity is fully exhausted.
        """
        with self._lock:
            if self._active_count + self._queued_count >= (self.max_active + self.max_queued):
                return False
            self._queued_count += 1
            return True

    def _mark_active(self) -> None:
        """Transitions an admitted slot from queued to actively running on an OS thread."""
        with self._lock:
            if self._queued_count > 0:
                self._queued_count -= 1
            self._active_count += 1

    def release_slot(self) -> None:
        """Frees an active or queued slot when a physical worker thread exits."""
        with self._lock:
            if self._active_count > 0:
                self._active_count -= 1
            elif self._queued_count > 0:
                self._queued_count -= 1

    def get_stats(self) -> dict[str, int]:
        """Returns snapshot of pool capacity metrics."""
        with self._lock:
            return {
                "active": self._active_count,
                "queued": self._queued_count,
                "max_active": self.max_active,
                "max_queued": self.max_queued,
            }

    def submit_tracked(
        self,
        func: Callable[..., T],
        *args: Any,
        session_id: uuid.UUID,
        institution_id: uuid.UUID,
        fence: int,
        owner_token: uuid.UUID,
        loop: asyncio.AbstractEventLoop | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        **kwargs: Any,
    ) -> tuple[concurrent.futures.Future[T], WorkerOperationTracker]:
        """
        Submits a synchronous blocking callable to the thread pool with tracked admission.
        Raises WorkerCapacityExhaustedError if active + queued capacity is saturated.
        """
        if not self.try_reserve():
            logger.warning(
                "[Worker Pool] Admission rejected: %s pool capacity exhausted (active=%d, queued=%d)",
                self.name,
                self._active_count,
                self._queued_count,
            )
            raise WorkerCapacityExhaustedError(self.name, retry_after=5)

        operation_id = f"{self.name.lower()}_{uuid.uuid4().hex[:12]}"

        ctx = contextvars.copy_context()

        def _worker_wrapper() -> T:
            self._mark_active()
            return ctx.run(func, *args, **kwargs)

        fut = self._executor.submit(_worker_wrapper)

        effective_loop = loop
        if effective_loop is None:
            try:
                effective_loop = asyncio.get_running_loop()
            except RuntimeError:
                effective_loop = None

        effective_factory = session_factory or AsyncSessionLocal

        tracker = WorkerOperationTracker(
            operation_id=operation_id,
            session_id=session_id,
            institution_id=institution_id,
            fence=fence,
            owner_token=owner_token,
            pool_name=self.name,
            executor_future=fut,
            pool=self,
        )

        WorkerTrackingRegistry.register_worker(tracker)

        fut.add_done_callback(
            functools.partial(
                _physical_future_done_callback,
                tracker=tracker,
                loop=effective_loop,
                session_factory=effective_factory,
            )
        )

        return fut, tracker

    def shutdown(self, wait: bool = True) -> None:
        """Shuts down the underlying ThreadPoolExecutor."""
        self._executor.shutdown(wait=wait)


# ==============================================================================
# Global Worker Pools
# ==============================================================================

# LLM Worker Pool: dedicated to high-latency external provider calls (Gemini/Groq)
LLM_WORKER_POOL = BoundedWorkerPool(
    name="LLM",
    max_active=16,
    max_queued=32,
)

# ChromaDB Worker Pool: dedicated to local vector queries and index lookups
CHROMADB_WORKER_POOL = BoundedWorkerPool(
    name="CHROMADB",
    max_active=8,
    max_queued=16,
)


def get_llm_worker_pool() -> BoundedWorkerPool:
    """Returns the process-wide bounded LLM worker pool."""
    return LLM_WORKER_POOL


def get_chromadb_worker_pool() -> BoundedWorkerPool:
    """Returns the process-wide bounded ChromaDB worker pool."""
    return CHROMADB_WORKER_POOL

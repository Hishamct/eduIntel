"""
backend/app/agents/task_registry.py

Authoritative tracking registry for active LangGraph asyncio tasks and unified
session quiescence enforcement across both physical executor threads and event-loop tasks.

Key guarantees:
1. Composite indexing by (institution_id, session_id).
2. Strong references to active asyncio.Task instances to prevent premature GC.
3. Thread-safe and event-loop-safe registration and unregistration.
4. Unified quiescence check: returns True iff BOTH WorkerTrackingRegistry (threads)
   and SessionTaskTrackingRegistry (asyncio tasks) are quiescent.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.core.worker_pool import WorkerTrackingRegistry

logger = logging.getLogger("app.agents.task_registry")


class SessionTaskTrackingRegistry:
    """
    Registry tracking active LangGraph generation tasks per session.
    Keyed by (institution_id: uuid.UUID, session_id: uuid.UUID).
    """

    _active_tasks: dict[tuple[uuid.UUID, uuid.UUID], set[asyncio.Task]] = {}
    _lock = asyncio.Lock() if hasattr(asyncio, "Lock") else None

    @classmethod
    def register_task(
        cls,
        institution_id: uuid.UUID,
        session_id: uuid.UUID,
        task: asyncio.Task,
        fence: int | None = None,
        owner_token: uuid.UUID | str | None = None,
    ) -> None:
        """
        Register an active LangGraph task for a session and attach an automatic
        completion callback to unregister upon task completion.
        """
        key = (institution_id, session_id)
        if key not in cls._active_tasks:
            cls._active_tasks[key] = set()

        cls._active_tasks[key].add(task)
        logger.debug(
            f"[TaskRegistry] Registered task {task.get_name() or id(task)} for session "
            f"({institution_id}, {session_id}), fence={fence}, owner_token={owner_token}."
        )

        def _on_task_done(done_task: asyncio.Task) -> None:
            try:
                cls.unregister_task(institution_id, session_id, done_task)
            except Exception as e:
                logger.error(
                    f"[TaskRegistry] Error in task done callback for session {key}: {e}",
                    exc_info=True,
                )

        task.add_done_callback(_on_task_done)

    @classmethod
    def unregister_task(
        cls,
        institution_id: uuid.UUID,
        session_id: uuid.UUID,
        task: asyncio.Task,
    ) -> None:
        """
        Unregister a completed or cancelled LangGraph task from the session.
        """
        key = (institution_id, session_id)
        tasks = cls._active_tasks.get(key)
        if tasks is not None:
            tasks.discard(task)
            if not tasks:
                cls._active_tasks.pop(key, None)
            logger.debug(
                f"[TaskRegistry] Unregistered task {task.get_name() or id(task)} for session {key}. "
                f"Remaining active tasks: {len(tasks)}"
            )

    @classmethod
    def is_task_quiescent(
        cls,
        institution_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> bool:
        """
        Check if there are any active (non-done) LangGraph tasks for the session.
        Returns True if quiescent (no running tasks), False otherwise.
        """
        key = (institution_id, session_id)
        tasks = cls._active_tasks.get(key)
        if not tasks:
            return True

        # Clean up any tasks that completed but haven't had callback run yet
        active_remaining = [t for t in tasks if not t.done()]
        if not active_remaining:
            cls._active_tasks.pop(key, None)
            return True

        return False

    @classmethod
    def get_active_tasks(
        cls,
        institution_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> list[asyncio.Task]:
        """Return a copy of currently active tasks for a session."""
        key = (institution_id, session_id)
        tasks = cls._active_tasks.get(key)
        if not tasks:
            return []
        return [t for t in tasks if not t.done()]

    @classmethod
    def clear_for_testing(cls) -> None:
        """Clear all registered tasks (used exclusively in test fixtures)."""
        cls._active_tasks.clear()


def is_session_quiescent(
    institution_id: uuid.UUID,
    session_id: uuid.UUID,
) -> bool:
    """
    Authoritative unified quiescence barrier.

    A session is considered quiescent IF AND ONLY IF:
    1. WorkerTrackingRegistry has zero active physical worker threads for this session, AND
    2. SessionTaskTrackingRegistry has zero active asyncio graph tasks for this session.

    If either subsystem has active work, returns False.
    """
    worker_quiescent = WorkerTrackingRegistry.is_session_quiescent(institution_id, session_id)
    if not worker_quiescent:
        return False

    task_quiescent = SessionTaskTrackingRegistry.is_task_quiescent(institution_id, session_id)
    if not task_quiescent:
        return False

    return True

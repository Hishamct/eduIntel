"""
backend/app/observability/quota/adapter.py

Context propagation and adapter bridge for Stage 7.3 Metered AI Execution.
Enables seamless routing of existing LLM generation and tool decision calls through MeteredAIService.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from app.observability.quota.context import MeteredRequestContext
from app.observability.quota.service import MeteredAIService

# Global ContextVar storing active MeteredRequestContext
_CURRENT_METERED_CONTEXT: ContextVar[MeteredRequestContext | None] = ContextVar("current_metered_context", default=None)

# Optional singleton reference to MeteredAIService
_METERED_SERVICE: MeteredAIService | None = None
_MAIN_EVENT_LOOP: asyncio.AbstractEventLoop | None = None


def get_current_metered_context() -> MeteredRequestContext | None:
    """Returns the currently active MeteredRequestContext in the local async/thread context."""
    return _CURRENT_METERED_CONTEXT.get()


def set_current_metered_context(ctx: MeteredRequestContext | None) -> Token:
    """Sets the active MeteredRequestContext, returning the restoration token."""
    return _CURRENT_METERED_CONTEXT.set(ctx)


def reset_current_metered_context(token: Token) -> None:
    """Resets the active MeteredRequestContext using its restoration token."""
    _CURRENT_METERED_CONTEXT.reset(token)


@contextmanager
def metered_execution_context(ctx: MeteredRequestContext) -> Generator[MeteredRequestContext, None, None]:
    """
    Context manager activating a MeteredRequestContext for the duration of a block.
    Guarantees clean restoration even upon exceptions.
    """
    token = _CURRENT_METERED_CONTEXT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT_METERED_CONTEXT.reset(token)


def register_main_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Registers the primary application event loop for cross-thread async dispatch."""
    global _MAIN_EVENT_LOOP
    _MAIN_EVENT_LOOP = loop


def get_main_event_loop() -> asyncio.AbstractEventLoop | None:
    """Returns the primary application event loop if active."""
    global _MAIN_EVENT_LOOP
    if _MAIN_EVENT_LOOP is not None and not _MAIN_EVENT_LOOP.is_closed():
        return _MAIN_EVENT_LOOP
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_metered_ai_service() -> MeteredAIService:
    """Returns or lazily creates the singleton MeteredAIService instance."""
    global _METERED_SERVICE
    if _METERED_SERVICE is None:
        _METERED_SERVICE = MeteredAIService()
    return _METERED_SERVICE


def set_metered_ai_service(service: MeteredAIService | None) -> None:
    """Overrides the global MeteredAIService (e.g. for testing with isolated engines)."""
    global _METERED_SERVICE
    _METERED_SERVICE = service


def run_metered_coro_sync[T](coro: Any) -> T:
    """
    Thread-safely executes an async metered coroutine from a synchronous caller.
    If called from a worker thread, dispatches to the running main event loop or runs locally.
    Strictly forbids blocking the active event loop thread.
    """
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is not None and current_loop.is_running():
        raise RuntimeError(
            "Synchronous run_metered_coro_sync cannot be called from within an active event loop thread. "
            "Await the native async coroutine or dispatch synchronous work to a worker thread via asyncio.to_thread."
        )

    loop = get_main_event_loop()
    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    return asyncio.run(coro)


__all__ = [
    "get_current_metered_context",
    "get_main_event_loop",
    "get_metered_ai_service",
    "metered_execution_context",
    "register_main_event_loop",
    "reset_current_metered_context",
    "run_metered_coro_sync",
    "set_current_metered_context",
    "set_metered_ai_service",
]

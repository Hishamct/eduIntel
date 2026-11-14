"""
backend/app/agents/dependencies.py

FastAPI dependency injection for agent session storage.
Provides fail-closed production resolution for DatabaseSessionStore and
configurable InMemorySessionStore for test suites.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends

from app.agents.session_store import (
    AbstractSessionStore,
    DatabaseSessionStore,
    InMemorySessionStore,
    SessionStoreUnavailableError,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

_global_in_memory_store: InMemorySessionStore | None = None


def get_shared_in_memory_store() -> InMemorySessionStore:
    """Singleton accessor for in-memory session store during testing."""
    global _global_in_memory_store
    if _global_in_memory_store is None:
        _global_in_memory_store = InMemorySessionStore()
    return _global_in_memory_store


def get_session_store() -> AbstractSessionStore:
    """
    FastAPI dependency resolving the active session store.
    Fail-closed policy:
    - In staging and production, strictly instantiates DatabaseSessionStore.
      If database connectivity is missing/misconfigured, raises SessionStoreUnavailableError.
    - In testing and local_dev environments, allows switching to InMemorySessionStore
      when USE_IN_MEMORY_SESSION_STORE is True.
    """
    if settings.ENVIRONMENT in ("production", "staging"):
        if not getattr(settings, "DATABASE_URL", None):
            raise SessionStoreUnavailableError(
                "Primary database configuration is unavailable in production environment"
            )
        return DatabaseSessionStore()

    if getattr(settings, "USE_IN_MEMORY_SESSION_STORE", False):
        return get_shared_in_memory_store()

    return DatabaseSessionStore()


SessionStoreDep = Annotated[AbstractSessionStore, Depends(get_session_store)]


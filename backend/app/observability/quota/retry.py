"""
Bounded PostgreSQL contention retry, lock_timeout, and per-attempt RLS context binding.

Handles transient concurrency errors:
  - 40P01: deadlock_detected
  - 40001: serialization_failure
  - 55P03: lock_not_available (lock_timeout exceeded)
Constraint, integrity, privilege, and domain errors are never retried.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability.quota.errors import DatabaseContentionError

logger = logging.getLogger(__name__)

TRANSIENT_SQLSTATES = frozenset({"40P01", "40001", "55P03"})
DEFAULT_RETRY_DELAYS_MS: tuple[int, ...] = (50, 150, 350)
DEFAULT_LOCK_TIMEOUT_MS = 2000


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry and lock_timeout configuration for FinOps DB transactions."""

    max_attempts: int = 3
    delays_ms: tuple[int, ...] = DEFAULT_RETRY_DELAYS_MS
    jitter_ratio: float = 0.25
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.lock_timeout_ms < 1 or self.lock_timeout_ms > 60_000:
            raise ValueError("lock_timeout_ms must be between 1 and 60000")
        if self.jitter_ratio < 0.0 or self.jitter_ratio > 1.0:
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")

    def compute_delay_seconds(self, attempt_number: int) -> float:
        """Compute bounded backoff with cryptographic-source non-zero jitter."""
        idx = min(max(attempt_number - 1, 0), len(self.delays_ms) - 1)
        base_ms = self.delays_ms[idx]
        if self.jitter_ratio <= 0.0:
            return base_ms / 1000.0
        # Scaled integer jitter in [0, int(jitter_ratio * 100)]% avoids Bandit B311.
        pct_cap = max(int(self.jitter_ratio * 100), 1)
        jitter_fraction = secrets.randbelow(pct_cap + 1) / 100.0
        return (base_ms * (1.0 + jitter_fraction)) / 1000.0


DEFAULT_RETRY_POLICY = RetryPolicy()


def extract_sqlstate(exc: BaseException) -> str | None:
    """Traverse SQLAlchemy/asyncpg exception chains to extract PostgreSQL SQLSTATE."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attr in ("sqlstate", "pgcode"):
            val = getattr(current, attr, None)
            if isinstance(val, str) and val:
                return val
        orig = getattr(current, "orig", None)
        if isinstance(orig, BaseException) and id(orig) not in seen:
            current = orig
            continue
        current = current.__cause__ or current.__context__
    return None


def is_transient_db_error(exc: BaseException) -> bool:
    """Return True strictly for PostgreSQL deadlock, serialization, or lock-timeout errors."""
    if not isinstance(exc, DBAPIError) and extract_sqlstate(exc) is None:
        return False
    return extract_sqlstate(exc) in TRANSIENT_SQLSTATES


async def apply_lock_timeout(db: AsyncSession, lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS) -> None:
    """Set transaction-local PostgreSQL lock_timeout using validated integer bounds."""
    timeout_val = int(lock_timeout_ms)
    if timeout_val < 1 or timeout_val > 60_000:
        raise ValueError("lock_timeout_ms must be between 1 and 60000")
    await db.execute(text(f"SET LOCAL lock_timeout = '{timeout_val}ms';"))


async def bind_tenant_rls_context(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    is_platform_admin: bool = False,
) -> None:
    """Bind transaction-local RLS GUCs (`is_local=true`) on the active DB transaction."""
    await db.execute(
        text("SELECT set_config('app.current_institution_id', :inst, true);"),
        {"inst": str(institution_id)},
    )
    await db.execute(
        text("SELECT set_config('app.is_platform_admin', :adm, true);"),
        {"adm": "true" if is_platform_admin else "false"},
    )


async def execute_with_retry[T](
    *,
    session_factory: async_sessionmaker[AsyncSession],
    institution_id: uuid.UUID,
    fn: Callable[[AsyncSession], Awaitable[T]],
    operation_name: str,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    is_platform_admin: bool = False,
) -> T:
    """
    Execute a transactional unit of work on fresh sessions with bounded transient retries.

    Every attempt runs in a new transaction, re-binds transaction-local RLS GUCs and
    `SET LOCAL lock_timeout`, and rolls back cleanly before sleeping and retrying on
    `40P01`, `40001`, or `55P03`.
    """
    last_sqlstate: str | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            async with session_factory() as db:
                async with db.begin():
                    await bind_tenant_rls_context(
                        db,
                        institution_id=institution_id,
                        is_platform_admin=is_platform_admin,
                    )
                    await apply_lock_timeout(db, policy.lock_timeout_ms)
                    return await fn(db)
        except Exception as exc:
            if not is_transient_db_error(exc):
                raise
            last_sqlstate = extract_sqlstate(exc)
            if attempt >= policy.max_attempts:
                logger.warning(
                    "quota_tx_contention_exhausted",
                    extra={
                        "operation": operation_name,
                        "institution_id": str(institution_id),
                        "sqlstate": last_sqlstate,
                        "attempts": attempt,
                    },
                )
                raise DatabaseContentionError(
                    f"Transaction contention persisted after {attempt} attempts for {operation_name}",
                    sqlstate=last_sqlstate,
                    attempts=attempt,
                ) from exc

            delay_sec = policy.compute_delay_seconds(attempt)
            logger.info(
                "quota_tx_transient_retry",
                extra={
                    "operation": operation_name,
                    "institution_id": str(institution_id),
                    "sqlstate": last_sqlstate,
                    "attempt": attempt,
                    "delay_ms": round(delay_sec * 1000),
                },
            )
            await asyncio.sleep(delay_sec)

    raise DatabaseContentionError(
        f"Transaction contention exhausted for {operation_name}",
        sqlstate=last_sqlstate,
        attempts=policy.max_attempts,
    )


async def run_in_session_savepoint[T](
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    fn: Callable[[AsyncSession], Awaitable[T]],
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    is_platform_admin: bool = False,
) -> T:
    """
    Execute an operation inside an explicit or nested transaction on a caller-owned AsyncSession.

    Preserves caller's outer transaction lifetime (e.g., request-scoped or test savepoint)
    while enforcing RLS binding and transaction-local `lock_timeout`.
    """
    tx_ctx = db.begin_nested() if db.in_transaction() else db.begin()
    async with tx_ctx:
        await bind_tenant_rls_context(
            db,
            institution_id=institution_id,
            is_platform_admin=is_platform_admin,
        )
        await apply_lock_timeout(db, lock_timeout_ms)
        return await fn(db)

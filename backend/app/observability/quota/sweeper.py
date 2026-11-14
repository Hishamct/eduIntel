"""
backend/app/observability/quota/sweeper.py

Automated Reconciliation and Recovery Sweeper for Stage 7.4.
Enforces canonical lock ordering, bounded transactions, and idempotent recovery
of expired pre-dispatch reservations and stale uncertain provider dispatches.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.quota.engine import TenantQuotaEngine
from app.observability.quota_models import AITokenReservation

logger = logging.getLogger(__name__)


@dataclass
class SweepResult:
    """Outcome metrics from a reconciliation sweeper pass."""

    timestamp: str
    swept_expired_reservations: int = 0
    swept_stale_dispatched: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def expired_reservations_released(self) -> int:
        return self.swept_expired_reservations

    @property
    def stale_dispatched_marked_unknown(self) -> int:
        return self.swept_stale_dispatched


class QuotaReconciliationSweeper:
    """
    Automated background and on-demand recovery engine.
    Discovers expired reservations and unresolved provider attempts,
    reconciling them according to approved FinOps rules.
    """

    def __init__(
        self,
        session_factory: Any,
        engine: TenantQuotaEngine | None = None,
        worker_id: str | None = None,
        lease_duration_seconds: int = 60,
    ):
        if callable(session_factory) and not isinstance(session_factory, AsyncSession):
            self.session_factory = session_factory
            self._direct_session = None
        else:
            # Direct AsyncSession instance passed (e.g. test harness)
            direct_session = session_factory
            self._direct_session = direct_session

            class _SingleSessionCtx:
                def __init__(self, s: AsyncSession):
                    self.s = s

                async def __aenter__(self) -> AsyncSession:
                    return self.s

                async def __aexit__(self, *args: Any) -> None:
                    pass

            self.session_factory = lambda: _SingleSessionCtx(direct_session)

        self.engine = engine or TenantQuotaEngine(session_factory=self.session_factory)
        self.worker_id = worker_id or f"sweeper-{uuid.uuid4().hex[:8]}"
        self.lease_duration_seconds = lease_duration_seconds

    async def sweep_expired_reservations(
        self,
        *,
        batch_size: int = 50,
        as_of: datetime | None = None,
    ) -> int:
        """
        Discovers expired `RESERVED` reservations where dispatch never occurred (`dispatched_at IS NULL`)
        and releases them back to tenant daily/category quotas (`RESERVED -> RELEASED`).
        """
        now = as_of or datetime.now(UTC)
        claimed_items: list[tuple[uuid.UUID, uuid.UUID]] = []

        # Step 1: Claim expired pre-dispatch reservations using SKIP LOCKED
        async with self.session_factory() as session:
            tx_ctx = session.begin_nested() if session.in_transaction() else session.begin()
            async with tx_ctx:
                stmt = (
                    select(AITokenReservation.id, AITokenReservation.institution_id)
                    .where(
                        AITokenReservation.status == "RESERVED",
                        AITokenReservation.dispatched_at.is_(None),
                        AITokenReservation.expires_at <= now,
                        (
                            AITokenReservation.sweeper_lease_expires_at.is_(None)
                            | (AITokenReservation.sweeper_lease_expires_at <= now)
                        ),
                    )
                    .order_by(AITokenReservation.expires_at.asc())
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
                rows = (await session.execute(stmt)).all()
                for res_id, inst_id in rows:
                    claimed_items.append((res_id, inst_id))

        if not claimed_items:
            return 0

        # Step 2: Expire each claimed item using canonical engine transactions
        swept_count = 0
        for res_id, inst_id in claimed_items:
            try:
                await self.engine.expire_pre_dispatch(
                    institution_id=inst_id,
                    reservation_id=res_id,
                    reason="TTL_EXPIRED_SWEEPER",
                    as_of=now,
                    db=self._direct_session,
                )
                swept_count += 1
            except Exception as e:
                logger.warning(
                    "[Sweeper] Failed to expire pre-dispatch reservation %s for institution %s: %s",
                    res_id,
                    inst_id,
                    e,
                )

        logger.info(
            "[Sweeper] Expired %d pre-dispatch reservations (worker=%s)",
            swept_count,
            self.worker_id,
        )
        return swept_count

    async def sweep_stale_dispatched(
        self,
        *,
        batch_size: int = 50,
        as_of: datetime | None = None,
    ) -> int:
        """
        Discovers stale `DISPATCHED` reservations that timed out without completed settlement.
        Per Decision 4: Preserves financial protection by transitioning to `UNKNOWN_USAGE`
        and setting `review_status = 'NEEDS_MANUAL_REVIEW'` rather than releasing to zero.
        """
        now = as_of or datetime.now(UTC)
        claimed_items: list[tuple[uuid.UUID, uuid.UUID]] = []

        async with self.session_factory() as session:
            tx_ctx = session.begin_nested() if session.in_transaction() else session.begin()
            async with tx_ctx:
                stmt = (
                    select(AITokenReservation.id, AITokenReservation.institution_id)
                    .where(
                        AITokenReservation.status == "DISPATCHED",
                        AITokenReservation.expires_at <= now,
                        (
                            AITokenReservation.sweeper_lease_expires_at.is_(None)
                            | (AITokenReservation.sweeper_lease_expires_at <= now)
                        ),
                    )
                    .order_by(AITokenReservation.expires_at.asc())
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
                rows = (await session.execute(stmt)).all()
                for res_id, inst_id in rows:
                    claimed_items.append((res_id, inst_id))

        if not claimed_items:
            return 0

        swept_count = 0
        for res_id, inst_id in claimed_items:
            try:
                await self.engine.mark_dispatched_reservation_unknown(
                    institution_id=inst_id,
                    reservation_id=res_id,
                    as_of=now,
                    db=self._direct_session,
                )
                swept_count += 1
            except Exception as e:
                logger.warning(
                    "[Sweeper] Failed to mark stale reservation %s as UNKNOWN_USAGE: %s",
                    res_id,
                    e,
                )

        logger.info(
            "[Sweeper] Marked %d stale dispatched reservations as UNKNOWN_USAGE (worker=%s)",
            swept_count,
            self.worker_id,
        )
        return swept_count

    async def run_sweep_batch(
        self,
        *,
        batch_size: int = 50,
        as_of: datetime | None = None,
    ) -> SweepResult:
        """Executes a full reconciliation sweep pass and returns structured metrics."""
        now = as_of or datetime.now(UTC)
        res = SweepResult(timestamp=now.isoformat())

        try:
            res.swept_expired_reservations = await self.sweep_expired_reservations(
                batch_size=batch_size, as_of=now
            )
        except Exception as e:
            res.errors.append(f"Expired reservations sweep error: {e}")

        try:
            res.swept_stale_dispatched = await self.sweep_stale_dispatched(
                batch_size=batch_size, as_of=now
            )
        except Exception as e:
            res.errors.append(f"Stale dispatched sweep error: {e}")

        return res

    async def start_background_loop(
        self,
        stop_event: asyncio.Event,
        interval_seconds: int = 60,
        batch_size: int = 50,
    ) -> None:
        """Long-running background task executing periodic reconciliation sweeps."""
        logger.info(
            "[Sweeper] Background reconciliation loop started (interval=%ds, worker=%s)",
            interval_seconds,
            self.worker_id,
        )
        while not stop_event.is_set():
            try:
                await self.run_sweep_batch(batch_size=batch_size)
            except Exception as e:
                logger.error("[Sweeper] Unhandled exception in sweep iteration: %s", e)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass

        logger.info("[Sweeper] Background reconciliation loop stopped cleanly.")

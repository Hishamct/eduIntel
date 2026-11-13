"""
Stage 7.2 TenantQuotaEngine orchestration facade.

Supports both standalone retryable transactions via an AsyncSession factory and
composable caller-owned AsyncSession execution via savepoints.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability.quota.admission import (
    admit_and_reserve_tx,
    recover_reservation_by_idempotency_key_tx,
    release_pre_dispatch_tx,
)
from app.observability.quota.dispatch_and_reconcile import (
    begin_provider_dispatch_tx,
    finalize_reservation_tx,
    manual_settle_unknown_usage_tx,
    record_attempt_outcome_tx,
    record_late_provider_usage_tx,
)
from app.observability.quota.policy import (
    FailClosedMissingUsagePolicyResolver,
    MissingUsagePolicyResolver,
)
from app.observability.quota.retry import (
    DEFAULT_RETRY_POLICY,
    RetryPolicy,
    execute_with_retry,
    run_in_session_savepoint,
)
from app.observability.quota.types import (
    AdmissionResult,
    AttemptDispatchRequest,
    AttemptSnapshot,
    ReconciliationResult,
    ReservationCreateRequest,
    ReservationSnapshot,
)

T = TypeVar("T")


class TenantQuotaEngine:
    """
    Transactionally safe Stage 7.2 Pricing, FinOps Ledger & Atomic Tenant Quota Engine.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        policy_resolver: MissingUsagePolicyResolver | None = None,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> None:
        self._session_factory = session_factory
        self._policy_resolver: MissingUsagePolicyResolver = (
            policy_resolver or FailClosedMissingUsagePolicyResolver()
        )
        self._retry_policy = retry_policy

    @property
    def policy_resolver(self) -> MissingUsagePolicyResolver:
        return self._policy_resolver

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    async def _run_tx(
        self,
        *,
        institution_id: uuid.UUID,
        operation_name: str,
        fn: Callable[[AsyncSession], Awaitable[T]],
        db: AsyncSession | None = None,
    ) -> T:
        """Run transactional unit either in a caller session savepoint or managed retry loop."""
        if db is not None:
            return await run_in_session_savepoint(
                db,
                institution_id=institution_id,
                fn=fn,
                lock_timeout_ms=self._retry_policy.lock_timeout_ms,
            )
        if self._session_factory is None:
            raise ValueError(
                f"{operation_name} requires either an explicit db session or engine session_factory"
            )
        return await execute_with_retry(
            session_factory=self._session_factory,
            institution_id=institution_id,
            fn=fn,
            operation_name=operation_name,
            policy=self._retry_policy,
        )

    async def admit_and_reserve(
        self,
        request: ReservationCreateRequest,
        *,
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> AdmissionResult:
        """Tx 1: Admit against tenant quotas & create durable RESERVED ledger entry."""
        return await self._run_tx(
            institution_id=request.institution_id,
            operation_name="admit_and_reserve",
            db=db,
            fn=lambda tx_db: admit_and_reserve_tx(tx_db, request, as_of=as_of),
        )

    async def recover_reservation_by_idempotency_key(
        self,
        *,
        institution_id: uuid.UUID,
        idempotency_key: str,
        expected_request: ReservationCreateRequest | None = None,
        db: AsyncSession | None = None,
    ) -> ReservationSnapshot | None:
        """Inspect persisted state for uncertain Tx 1 commit recovery."""
        return await self._run_tx(
            institution_id=institution_id,
            operation_name="recover_reservation_by_idempotency_key",
            db=db,
            fn=lambda tx_db: recover_reservation_by_idempotency_key_tx(
                tx_db,
                institution_id=institution_id,
                idempotency_key=idempotency_key,
                expected_request=expected_request,
            ),
        )

    async def release_pre_dispatch(
        self,
        *,
        institution_id: uuid.UUID,
        reservation_id: uuid.UUID,
        reason: str = "PRE_DISPATCH_CANCELLED",
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> ReservationSnapshot:
        """Tx 1B: Release an un-dispatched `RESERVED` reservation (`RESERVED -> RELEASED`)."""
        return await self._run_tx(
            institution_id=institution_id,
            operation_name="release_pre_dispatch",
            db=db,
            fn=lambda tx_db: release_pre_dispatch_tx(
                tx_db,
                institution_id=institution_id,
                reservation_id=reservation_id,
                reason=reason,
                require_expired=False,
                as_of=as_of,
            ),
        )

    async def expire_pre_dispatch(
        self,
        *,
        institution_id: uuid.UUID,
        reservation_id: uuid.UUID,
        reason: str = "PRE_DISPATCH_TTL_EXPIRED",
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> ReservationSnapshot:
        """Tx 1B (expiry): Expire a `RESERVED` reservation whose TTL has elapsed."""
        return await self._run_tx(
            institution_id=institution_id,
            operation_name="expire_pre_dispatch",
            db=db,
            fn=lambda tx_db: release_pre_dispatch_tx(
                tx_db,
                institution_id=institution_id,
                reservation_id=reservation_id,
                reason=reason,
                require_expired=True,
                as_of=as_of,
            ),
        )

    async def begin_provider_dispatch(
        self,
        request: AttemptDispatchRequest,
        *,
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> tuple[ReservationSnapshot, AttemptSnapshot]:
        """Tx 2A: Persist durable DISPATCHED boundary & attempt before calling AI provider."""
        return await self._run_tx(
            institution_id=request.institution_id,
            operation_name="begin_provider_dispatch",
            db=db,
            fn=lambda tx_db: begin_provider_dispatch_tx(tx_db, request, as_of=as_of),
        )

    async def record_attempt_outcome(
        self,
        *,
        institution_id: uuid.UUID,
        reservation_id: uuid.UUID,
        attempt_id: uuid.UUID,
        status: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        provider_request_id: str | None = None,
        error_classification: str | None = None,
        latency_ms: int | None = None,
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> tuple[ReservationSnapshot, AttemptSnapshot]:
        """Tx 2B: Record SUCCEEDED, FAILED_CONFIRMED, or TIMEOUT_UNCERTAIN attempt outcome."""
        return await self._run_tx(
            institution_id=institution_id,
            operation_name="record_attempt_outcome",
            db=db,
            fn=lambda tx_db: record_attempt_outcome_tx(
                tx_db,
                institution_id=institution_id,
                reservation_id=reservation_id,
                attempt_id=attempt_id,
                status=status,
                policy_resolver=self._policy_resolver,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider_request_id=provider_request_id,
                error_classification=error_classification,
                latency_ms=latency_ms,
                as_of=as_of,
            ),
        )

    async def finalize_reservation(
        self,
        *,
        institution_id: uuid.UUID,
        reservation_id: uuid.UUID,
        escalate_dispatched_to_unknown: bool = False,
        recovery_reason: str | None = None,
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> ReconciliationResult:
        """Tx 3: Finalize `DISPATCHED` reservation into `COMMITTED` or `UNKNOWN_USAGE`."""
        return await self._run_tx(
            institution_id=institution_id,
            operation_name="finalize_reservation",
            db=db,
            fn=lambda tx_db: finalize_reservation_tx(
                tx_db,
                institution_id=institution_id,
                reservation_id=reservation_id,
                escalate_dispatched_to_unknown=escalate_dispatched_to_unknown,
                recovery_reason=recovery_reason,
                as_of=as_of,
            ),
        )

    async def mark_dispatched_reservation_unknown(
        self,
        *,
        institution_id: uuid.UUID,
        reservation_id: uuid.UUID,
        recovery_reason: str = "DISPATCHED_TTL_EXPIRED",
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> ReconciliationResult:
        """Transition an uncompleted or expired `DISPATCHED` reservation into `UNKNOWN_USAGE`."""
        return await self.finalize_reservation(
            institution_id=institution_id,
            reservation_id=reservation_id,
            escalate_dispatched_to_unknown=True,
            recovery_reason=recovery_reason,
            as_of=as_of,
            db=db,
        )

    async def manual_settle_unknown_usage(
        self,
        *,
        institution_id: uuid.UUID,
        reservation_id: uuid.UUID,
        settled_tokens: int,
        actor: str,
        reason: str,
        notes: str,
        attempt_id: uuid.UUID | None = None,
        settled_cost_inr: Decimal | None = None,
        settled_input_tokens: int | None = None,
        settled_output_tokens: int | None = None,
        zero_charge_release: bool = False,
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> ReconciliationResult:
        """Tx 4: Operator manual settlement of `UNKNOWN_USAGE` reservation/attempt."""
        return await self._run_tx(
            institution_id=institution_id,
            operation_name="manual_settle_unknown_usage",
            db=db,
            fn=lambda tx_db: manual_settle_unknown_usage_tx(
                tx_db,
                institution_id=institution_id,
                reservation_id=reservation_id,
                attempt_id=attempt_id,
                settled_tokens=settled_tokens,
                settled_cost_inr=settled_cost_inr,
                settled_input_tokens=settled_input_tokens,
                settled_output_tokens=settled_output_tokens,
                actor=actor,
                reason=reason,
                notes=notes,
                zero_charge_release=zero_charge_release,
                as_of=as_of,
            ),
        )

    async def record_late_provider_usage(
        self,
        *,
        institution_id: uuid.UUID,
        reservation_id: uuid.UUID,
        attempt_id: uuid.UUID,
        input_tokens: int,
        output_tokens: int,
        actor: str,
        reason: str,
        notes: str,
        provider_request_id: str | None = None,
        failed_confirmed: bool = False,
        as_of: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> ReconciliationResult:
        """Tx 5: Apply late provider usage evidence to `UNKNOWN_USAGE` or `MANUALLY_SETTLED`."""
        return await self._run_tx(
            institution_id=institution_id,
            operation_name="record_late_provider_usage",
            db=db,
            fn=lambda tx_db: record_late_provider_usage_tx(
                tx_db,
                institution_id=institution_id,
                reservation_id=reservation_id,
                attempt_id=attempt_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                actor=actor,
                reason=reason,
                notes=notes,
                provider_request_id=provider_request_id,
                failed_confirmed=failed_confirmed,
                as_of=as_of,
            ),
        )


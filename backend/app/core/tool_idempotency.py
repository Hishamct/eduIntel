"""
backend/app/core/tool_idempotency.py

Phase 5 Step 1: Fenced Tool Idempotency & External Side-Effect Boundaries.
- Enforces strict unique constraints on (institution_id, session_id, turn_id, tool_call_id).
- Arguments hash verification prevents argument divergence on duplicate call IDs.
- Monotonically increasing lease_generation fencing tokens prevent split-brain commits from stalled workers.
- Single atomic transaction invariant for internal mutations.
- Bounded external side effects: timeouts transition to UNCERTAIN status, strictly preventing blind retries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import ToolExecutionRecord

logger = logging.getLogger(__name__)


# --- Idempotency Exceptions ---
class ToolIdempotencyError(Exception):
    """Base exception for tool execution idempotency errors."""


class IdempotencyConflictError(ToolIdempotencyError):
    """Raised when an existing tool_call_id is reused with diverging arguments."""


class ToolExecutionConflictError(ToolIdempotencyError):
    """Raised when another worker is currently actively executing this tool call."""


class ToolExecutionExhaustedError(ToolIdempotencyError):
    """Raised when stalled attempts exceed the maximum allowed threshold (3 attempts)."""


class FencingTokenRevokedError(ToolIdempotencyError):
    """Raised when a worker's lease generation has been superseded by a higher fencing token."""


class UncertainExternalSideEffectError(ToolIdempotencyError):
    """Raised when attempting to execute or retry an external operation currently in UNCERTAIN state."""


def compute_arguments_hash(args: dict[str, Any] | None) -> str:
    """Computes a deterministic SHA-256 hash of JSON-serialized tool arguments."""
    payload = args if args is not None else {}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def reserve_or_get_tool_execution(
    db: AsyncSession,
    institution_id: uuid.UUID,
    session_id: str,
    turn_id: int,
    tool_call_id: str,
    tool_name: str,
    args: dict[str, Any] | None,
    lease_duration_seconds: int = 60,
) -> tuple[ToolExecutionRecord, bool]:
    """
    Atomically reserves a tool execution lease or retrieves a previously completed result.
    Returns:
        tuple[ToolExecutionRecord, bool]: (record, is_cached)
        - If is_cached is True, caller uses record.result_payload and skips tool execution.
        - If is_cached is False, caller proceeds with tool execution under record.lease_generation.
    """
    args_hash = compute_arguments_hash(args)
    now = datetime.now(UTC)
    lease_expires = now + timedelta(seconds=lease_duration_seconds)

    # 1. Check for existing record
    stmt = (
        select(ToolExecutionRecord)
        .where(
            ToolExecutionRecord.institution_id == institution_id,
            ToolExecutionRecord.session_id == session_id,
            ToolExecutionRecord.turn_id == turn_id,
            ToolExecutionRecord.tool_call_id == tool_call_id,
        )
        .with_for_update()
    )
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()

    if record is not None:
        # Enforce arguments immutability: identical ID cannot run with altered arguments
        if record.arguments_hash != args_hash:
            raise IdempotencyConflictError(
                f"Tool call '{tool_call_id}' previously executed with different arguments. "
                f"Existing hash: {record.arguments_hash}, New hash: {args_hash}."
            )

        # Previously completed: return cached payload immediately
        if record.status == "COMPLETED":
            logger.info(
                "[Idempotency] Returning cached result for tool_call_id='%s' (status=COMPLETED)",
                tool_call_id,
            )
            return record, True

        # External side-effect in UNCERTAIN state: blind retries strictly forbidden
        if record.status == "UNCERTAIN":
            raise UncertainExternalSideEffectError(
                f"Tool call '{tool_call_id}' is in UNCERTAIN state due to a previous external timeout. "
                "Automatic retry is rejected to prevent duplicate external side effects. Operator reconciliation required."
            )

        # Active or stalled execution
        if record.status in ("RESERVED", "EXECUTING"):
            if record.lease_expires_at > now:
                # Active lease held by another worker
                raise ToolExecutionConflictError(
                    f"Tool call '{tool_call_id}' is actively executing under lease expiring at {record.lease_expires_at.isoformat()}."
                )

            # Stalled lease detected (lease_expires_at <= now)
            if record.attempt_count >= 3:
                record.status = "FAILED"
                record.error_details = "Max attempt limit (3) exceeded on stalled lease recovery."
                await db.flush()
                raise ToolExecutionExhaustedError(
                    f"Tool call '{tool_call_id}' exceeded maximum recovery attempts (3). Execution marked FAILED."
                )

            # Atomically reclaim lease and increment fencing token (lease_generation)
            new_generation = record.lease_generation + 1
            new_attempts = record.attempt_count + 1
            logger.warning(
                "[Idempotency] Reclaiming stalled lease for tool_call_id='%s': generation %d -> %d, attempt %d -> %d",
                tool_call_id,
                record.lease_generation,
                new_generation,
                record.attempt_count,
                new_attempts,
            )

            record.attempt_count = new_attempts
            record.lease_generation = new_generation
            record.last_attempt_at = now
            record.lease_expires_at = lease_expires
            record.status = "EXECUTING"
            await db.flush()
            return record, False

        if record.status == "FAILED":
            # If failed, permit a new attempt if under limit
            if record.attempt_count >= 3:
                raise ToolExecutionExhaustedError(
                    f"Tool call '{tool_call_id}' previously failed and reached max attempts (3)."
                )
            record.attempt_count += 1
            record.lease_generation += 1
            record.last_attempt_at = now
            record.lease_expires_at = lease_expires
            record.status = "EXECUTING"
            record.error_details = None
            await db.flush()
            return record, False

    # 2. No record exists: create new reservation
    new_record = ToolExecutionRecord(
        id=uuid.uuid4(),
        institution_id=institution_id,
        session_id=session_id,
        turn_id=turn_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments_hash=args_hash,
        status="EXECUTING",
        attempt_count=1,
        lease_generation=1,
        last_attempt_at=now,
        lease_expires_at=lease_expires,
        result_payload=None,
        error_details=None,
    )
    try:
        async with db.begin_nested():
            db.add(new_record)
            await db.flush()
    except IntegrityError as integrity_err:
        logger.warning(
            "[Idempotency] Concurrent reservation collision on tool_call_id='%s' "
            "(unique constraint uq_tool_execution_call). Converting to controlled domain conflict: %s",
            tool_call_id,
            integrity_err,
        )
        raise ToolExecutionConflictError(
            f"Tool call '{tool_call_id}' is actively being reserved by a concurrent worker. "
            "Controlled domain conflict enforced via unique constraint uq_tool_execution_call."
        ) from integrity_err

    return new_record, False


async def commit_internal_tool_execution(
    db: AsyncSession,
    record_id: uuid.UUID,
    my_lease_generation: int,
    result_payload: dict[str, Any],
) -> None:
    """
    Commits an internal tool execution result.
    Enforces Single Atomic Transaction & Fencing Invariant:
    If a stalled worker was superseded by a higher lease_generation, rowcount is 0,
    and FencingTokenRevokedError is raised to abort the worker's transaction.
    """
    stmt = (
        update(ToolExecutionRecord)
        .where(
            ToolExecutionRecord.id == record_id,
            ToolExecutionRecord.lease_generation == my_lease_generation,
        )
        .values(
            status="COMPLETED",
            result_payload=result_payload,
            error_details=None,
        )
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        logger.error(
            "[Idempotency] Fencing token revoked for record_id='%s', generation=%d. Mutation aborted.",
            record_id,
            my_lease_generation,
        )
        raise FencingTokenRevokedError(
            f"Fencing token revoked: lease_generation {my_lease_generation} is no longer valid. Transaction rolled back."
        )


async def fail_tool_execution(
    db: AsyncSession,
    record_id: uuid.UUID,
    my_lease_generation: int,
    error_message: str,
    is_uncertain: bool = False,
) -> None:
    """
    Transitions tool execution to FAILED or UNCERTAIN status upon execution failure or external timeout.
    """
    target_status = "UNCERTAIN" if is_uncertain else "FAILED"
    stmt = (
        update(ToolExecutionRecord)
        .where(
            ToolExecutionRecord.id == record_id,
            ToolExecutionRecord.lease_generation == my_lease_generation,
        )
        .values(
            status=target_status,
            error_details=error_message,
        )
    )
    await db.execute(stmt)
    await db.flush()


async def reconcile_uncertain_tool_execution(
    db: AsyncSession,
    record_id: uuid.UUID,
    action: str,  # CONFIRM_DISPATCHED, MARK_FAILED, COMPENSATING_ACTION
    operator_notes: str,
) -> ToolExecutionRecord:
    """
    Manual reconciliation protocol for external side-effect operations stuck in UNCERTAIN status.
    - CONFIRM_DISPATCHED: Operator confirms downstream accepted payload -> COMPLETED.
    - MARK_FAILED: Operator confirms downstream never received payload -> FAILED (allows retry).
    - COMPENSATING_ACTION: Operator executes a compensating transaction -> COMPENSATED.
    """
    stmt = select(ToolExecutionRecord).where(ToolExecutionRecord.id == record_id).with_for_update()
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()
    if record is None:
        raise ValueError(f"ToolExecutionRecord '{record_id}' not found.")

    if record.status != "UNCERTAIN":
        raise ValueError(f"Record '{record_id}' is in status '{record.status}', not UNCERTAIN. Reconciliation not permitted.")

    if action == "CONFIRM_DISPATCHED":
        record.status = "COMPLETED"
        record.error_details = f"Reconciled: CONFIRM_DISPATCHED. Notes: {operator_notes}"
    elif action == "MARK_FAILED":
        record.status = "FAILED"
        record.error_details = f"Reconciled: MARK_FAILED. Notes: {operator_notes}"
    elif action == "COMPENSATING_ACTION":
        record.status = "COMPENSATED"
        record.error_details = f"Reconciled: COMPENSATING_ACTION. Notes: {operator_notes}"
    else:
        raise ValueError(f"Unsupported reconciliation action: {action}")

    await db.flush()
    return record

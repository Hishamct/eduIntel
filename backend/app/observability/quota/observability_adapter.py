"""
backend/app/observability/quota/observability_adapter.py

Observability Adapter bridging Stage 7.2 Quota Engine outcomes to legacy llm_usage_logs.
Ensures zero pricing calculation drift and avoids duplicate financial debiting.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import LLMCallUsage
from app.core.tenant import tenant_session_scope
from app.observability.models import LLMUsageLog
from app.observability.quota.types import AttemptSnapshot, ReservationSnapshot

logger = logging.getLogger(__name__)


class ObservabilityAdapter:
    """
    Persists call-level operational telemetry to llm_usage_logs from authoritative AttemptSnapshots.
    """

    @classmethod
    def attempt_to_llm_call_usage(cls, attempt: AttemptSnapshot) -> LLMCallUsage:
        """Translates an authoritative AttemptSnapshot into a legacy LLMCallUsage object."""
        return LLMCallUsage(
            provider=attempt.provider,
            model=attempt.model,
            input_tokens=attempt.input_tokens,
            output_tokens=attempt.output_tokens,
            latency_ms=attempt.latency_ms or 0,
            used_fallback=attempt.is_fallback,
        )

    @classmethod
    async def record_attempt_telemetry(
        cls,
        *,
        reservation: ReservationSnapshot,
        attempt: AttemptSnapshot,
        endpoint: str,
        db: AsyncSession | None = None,
    ) -> LLMUsageLog | None:
        """
        Records one provider attempt in llm_usage_logs.
        Uses exact quantized ledger cost from attempt.actual_cost_inr (or None).
        Never runs independent unquantized pricing calculation.
        """
        async def _persist(session: AsyncSession) -> LLMUsageLog:
            cost_float: float | None = None
            if attempt.actual_cost_inr is not None:
                cost_float = float(attempt.actual_cost_inr)
            elif attempt.estimated_cost_inr is not None:
                cost_float = float(attempt.estimated_cost_inr)

            entry = LLMUsageLog(
                institution_id=reservation.institution_id,
                endpoint=endpoint,
                provider=attempt.provider,
                model=attempt.model,
                input_tokens=attempt.input_tokens,
                output_tokens=attempt.output_tokens,
                latency_ms=attempt.latency_ms or 0,
                used_fallback=attempt.is_fallback,
                estimated_cost_inr=cost_float,
            )
            session.add(entry)
            await session.flush()
            return entry

        try:
            if db is not None:
                return await _persist(db)
            async with tenant_session_scope(reservation.institution_id) as scoped_db:
                return await _persist(scoped_db)
        except Exception as exc:
            logger.warning(
                "Failed to record operational LLMUsageLog for attempt %s: %s",
                attempt.id,
                exc,
            )
            return None


__all__ = ["ObservabilityAdapter"]

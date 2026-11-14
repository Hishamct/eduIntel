"""
backend/app/observability/quota/service.py

Stage 7.3 Metered AI Execution Service.
Orchestrates request validation, quota admission (Tx 1), durable dispatch (Tx 2A),
decoupled provider inference (0 DB connections held), usage normalization,
multi-attempt tracking (Tx 2B), reservation finalization (Tx 3), and telemetry logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.llm_client import LLMCallUsage
from app.core.llm_provider import (
    LLMConfig,
    LLMProviderRegistry,
    ProviderQuotaExhaustedError,
    ProviderTransientError,
    ToolCall,
    ToolDecisionError,
    is_rate_limit_error,
    is_transient_error,
    sanitize_prompt_for_provider,
)
from app.guardrails.engine import default_guardrails_engine
from app.observability.quota.context import MeteredRequestContext
from app.observability.quota.engine import TenantQuotaEngine
from app.observability.quota.normalizer import (
    NormalizedUsage,
    ProviderUsageNormalizer,
)
from app.observability.quota.observability_adapter import ObservabilityAdapter
from app.observability.quota.types import (
    AttemptDispatchRequest,
    AttemptSnapshot,
    ReservationCreateRequest,
    ReservationSnapshot,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MeteredAIResult:
    """Outcome of a metered text generation request."""

    text: str
    usage: LLMCallUsage
    reservation: ReservationSnapshot
    attempts: tuple[AttemptSnapshot, ...]
    normalized_usage: NormalizedUsage


@dataclass(frozen=True, slots=True)
class MeteredToolResult:
    """Outcome of a metered tool decision request."""

    tool_calls: list[dict[str, Any]]
    usage: LLMCallUsage
    reservation: ReservationSnapshot
    attempts: tuple[AttemptSnapshot, ...]
    normalized_usage: NormalizedUsage


@dataclass(frozen=True, slots=True)
class MeteredEmbeddingResult:
    """Outcome of a metered embedding generation request."""

    embeddings: list[list[float]]
    usage: LLMCallUsage
    reservation: ReservationSnapshot
    attempts: tuple[AttemptSnapshot, ...]
    normalized_usage: NormalizedUsage


class MeteredAIService:
    """
    Central service governing all metered AI execution across EduIntel.
    Enforces the mandatory 10-step transaction lifecycle and decoupled inference invariant.
    """

    def __init__(
        self,
        engine: TenantQuotaEngine | None = None,
        provider_registry: LLMProviderRegistry | None = None,
        normalizer: ProviderUsageNormalizer | None = None,
        policy_resolver: Any | None = None,
    ) -> None:
        if engine is not None:
            self._engine = engine
            if policy_resolver is not None:
                self._engine._policy_resolver = policy_resolver
        else:
            self._engine = TenantQuotaEngine(
                session_factory=AsyncSessionLocal,
                policy_resolver=policy_resolver,
            )
        self._provider_registry = provider_registry or LLMProviderRegistry.get_instance()
        self._normalizer = normalizer or ProviderUsageNormalizer()

    @property
    def engine(self) -> TenantQuotaEngine:
        return self._engine

    @property
    def provider_registry(self) -> LLMProviderRegistry:
        return self._provider_registry

    @property
    def normalizer(self) -> ProviderUsageNormalizer:
        return self._normalizer

    def _estimate_prompt_tokens(self, prompt: str) -> int:
        """Conservative token heuristic: ~4 chars per token, minimum 50 tokens."""
        if not prompt:
            return 50
        return max(len(prompt) // 4, 50)

    async def execute_text_generation(
        self,
        context: MeteredRequestContext,
        prompt: str,
        config: LLMConfig | None = None,
    ) -> MeteredAIResult:
        """
        Executes policy-governed text generation through the 10-step metered lifecycle.
        """
        cfg = config or LLMConfig()
        sanitized_prompt = sanitize_prompt_for_provider(prompt)

        # 1. Calculate estimated input tokens if using default
        estimated_input = context.estimated_input_tokens
        if estimated_input == 500 and len(prompt) > 2000:
            estimated_input = self._estimate_prompt_tokens(prompt)

        # ---------------------------------------------------------------------
        # STEP 1 & 2: Quota Admission & Reservation (Tx 1)
        # ---------------------------------------------------------------------
        admission_req = ReservationCreateRequest(
            institution_id=context.institution_id,
            user_id=context.user_id,
            usage_category=context.usage_category,
            endpoint=context.endpoint,
            provider=context.provider,
            model=cfg.model_override or context.model,
            estimated_input_tokens=estimated_input,
            reserved_output_tokens=context.reserved_output_tokens,
            ttl_seconds=context.ttl_seconds,
            idempotency_key=context.idempotency_key,
            logical_operation_id=context.logical_operation_id,
            pricing_version=context.pricing_version,
        )
        admission_result = await self.engine.admit_and_reserve(admission_req)
        res_snapshot = admission_result.reservation

        # ---------------------------------------------------------------------
        # STEP 3: Durable Provider Dispatch for Attempt 1 (Tx 2A)
        # ---------------------------------------------------------------------
        attempt1_req = AttemptDispatchRequest(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            provider=context.provider,
            model=cfg.model_override or context.model,
            estimated_tokens=estimated_input + context.reserved_output_tokens,
            is_fallback=False,
            is_retry=False,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=context.reserved_output_tokens,
            pricing_version=context.pricing_version,
        )
        res_snapshot, attempt1_snap = await self.engine.begin_provider_dispatch(attempt1_req)

        # ZERO DATABASE CONNECTION HELD BEYOND THIS POINT!

        # ---------------------------------------------------------------------
        # STEP 4: External Provider Inference (Primary: Gemini)
        # ---------------------------------------------------------------------
        start_time = time.monotonic()
        primary_success = False
        primary_response_text: str = ""
        primary_usage: Any = None
        attempt1_error: Exception | None = None

        try:
            # Inference occurs outside any database transaction
            primary_response_text, primary_usage = await asyncio.to_thread(
                self.provider_registry.primary.generate_text,
                sanitized_prompt,
                cfg,
            )
            primary_success = True
        except (ProviderQuotaExhaustedError, ProviderTransientError) as pe:
            attempt1_error = pe
        except Exception as e:
            if is_rate_limit_error(e) or is_transient_error(e):
                attempt1_error = e
            else:
                # Unexpected failure: record attempt and re-raise
                latency_ms = int((time.monotonic() - start_time) * 1000)
                await self._handle_attempt_failure(
                    res_snapshot=res_snapshot,
                    attempt_snap=attempt1_snap,
                    error=e,
                    latency_ms=latency_ms,
                    is_uncertain=True,
                )
                raise

        latency1_ms = int((time.monotonic() - start_time) * 1000)

        # ---------------------------------------------------------------------
        # STEP 5 & 6: Outcome Resolution (Success vs Fallback)
        # ---------------------------------------------------------------------
        if primary_success:
            norm_usage = self.normalizer.from_llm_call_usage(primary_usage)
            return await self._finalize_successful_attempt(
                context=context,
                res_snapshot=res_snapshot,
                attempt_snap=attempt1_snap,
                raw_text=primary_response_text,
                norm_usage=norm_usage,
                latency_ms=latency1_ms,
            )

        # Primary failed with 429 or transient error: record Attempt 1 before fallback
        is_uncertain = not is_rate_limit_error(attempt1_error)
        res_snapshot, attempt1_snap = await self._record_attempt_non_success(
            res_snapshot=res_snapshot,
            attempt_snap=attempt1_snap,
            error=attempt1_error,
            latency_ms=latency1_ms,
            is_uncertain=is_uncertain,
        )

        # ---------------------------------------------------------------------
        # STEP 7: Dispatch Fallback Attempt 2 (Groq) (Tx 2A)
        # ---------------------------------------------------------------------
        fallback_model = getattr(self.provider_registry.fallback, "model", "openai/gpt-oss-120b")
        attempt2_req = AttemptDispatchRequest(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            provider="groq",
            model=fallback_model,
            estimated_tokens=estimated_input + context.reserved_output_tokens,
            is_fallback=True,
            is_retry=False,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=context.reserved_output_tokens,
            pricing_version=context.pricing_version,
        )
        res_snapshot, attempt2_snap = await self.engine.begin_provider_dispatch(attempt2_req)

        # ZERO DATABASE CONNECTION HELD DURING FALLBACK INFERENCE!

        start2_time = time.monotonic()
        try:
            fallback_text, fallback_usage = await asyncio.to_thread(
                self.provider_registry.fallback.generate_text,
                sanitized_prompt,
                cfg,
            )
            latency2_ms = int((time.monotonic() - start2_time) * 1000)
            norm_usage = self.normalizer.from_llm_call_usage(fallback_usage)
            return await self._finalize_successful_attempt(
                context=context,
                res_snapshot=res_snapshot,
                attempt_snap=attempt2_snap,
                raw_text=fallback_text,
                norm_usage=norm_usage,
                latency_ms=latency2_ms,
            )
        except Exception as fallback_err:
            latency2_ms = int((time.monotonic() - start2_time) * 1000)
            await self._handle_attempt_failure(
                res_snapshot=res_snapshot,
                attempt_snap=attempt2_snap,
                error=fallback_err,
                latency_ms=latency2_ms,
                is_uncertain=True,
            )
            raise fallback_err from attempt1_error

    async def execute_embedding_generation(
        self,
        context: MeteredRequestContext,
        texts: list[str],
        model: str = "gemini-embedding-001",
    ) -> MeteredEmbeddingResult:
        """
        Executes policy-governed embedding generation through the metered lifecycle.
        Guarantees zero database connections are checked out during external embedding inference.
        """
        if not texts:
            raise ValueError("Cannot generate embeddings for an empty list of texts.")

        total_chars = sum(len(t) for t in texts)
        estimated_input = max(total_chars // 4, 10)

        # ---------------------------------------------------------------------
        # STEP 1 & 2: Quota Admission & Reservation (Tx 1)
        # ---------------------------------------------------------------------
        admission_req = ReservationCreateRequest(
            institution_id=context.institution_id,
            user_id=context.user_id,
            usage_category=context.usage_category or "ingestion_embeddings",
            endpoint=context.endpoint,
            provider="gemini",
            model=model,
            estimated_input_tokens=estimated_input,
            reserved_output_tokens=0,
            ttl_seconds=context.ttl_seconds,
            idempotency_key=context.idempotency_key,
            logical_operation_id=context.logical_operation_id,
            pricing_version=context.pricing_version,
        )
        admission_result = await self.engine.admit_and_reserve(admission_req)
        res_snapshot = admission_result.reservation

        # ---------------------------------------------------------------------
        # STEP 3: Durable Provider Dispatch for Attempt 1 (Tx 2A)
        # ---------------------------------------------------------------------
        attempt1_req = AttemptDispatchRequest(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            provider="gemini",
            model=model,
            estimated_tokens=estimated_input,
            is_fallback=False,
            is_retry=False,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=0,
            pricing_version=context.pricing_version,
        )
        res_snapshot, attempt1_snap = await self.engine.begin_provider_dispatch(attempt1_req)

        # ZERO DATABASE CONNECTION HELD BEYOND THIS POINT!

        # ---------------------------------------------------------------------
        # STEP 4: External Provider Inference (Gemini Embeddings)
        # ---------------------------------------------------------------------
        start_time = time.monotonic()
        raw_embeddings: list[list[float]] = []

        def _call_gemini_embed():
            client = getattr(self.provider_registry.primary, "client", None)
            if client is None:
                from google import genai

                from app.core.config import settings

                client = genai.Client(api_key=settings.GEMINI_API_KEY)
            resp = client.models.embed_content(
                model=model,
                contents=texts,
            )
            return [e.values for e in resp.embeddings]

        try:
            raw_embeddings = await asyncio.to_thread(_call_gemini_embed)
        except Exception as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            await self._handle_attempt_failure(
                res_snapshot=res_snapshot,
                attempt_snap=attempt1_snap,
                error=e,
                latency_ms=latency_ms,
                is_uncertain=True,
            )
            raise

        latency_ms = int((time.monotonic() - start_time) * 1000)

        # ---------------------------------------------------------------------
        # STEP 5 & 6: Outcome Resolution & Finalize Reservation (Tx 2B / Tx 3)
        # ---------------------------------------------------------------------
        actual_tokens = estimated_input
        norm_usage = NormalizedUsage(
            provider="gemini",
            model=model,
            input_tokens=actual_tokens,
            output_tokens=0,
            total_tokens=actual_tokens,
            provider_request_id=None,
            latency_ms=latency_ms,
            is_complete=True,
            is_valid=True,
        )

        call_usage = LLMCallUsage(
            provider="gemini",
            model=model,
            input_tokens=actual_tokens,
            output_tokens=0,
            latency_ms=latency_ms,
            used_fallback=False,
        )

        res_snapshot, updated_attempt = await self.engine.record_attempt_outcome(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            attempt_id=attempt1_snap.id,
            status="SUCCEEDED",
            input_tokens=norm_usage.input_tokens,
            output_tokens=norm_usage.output_tokens,
            provider_request_id=norm_usage.provider_request_id,
            latency_ms=latency_ms,
        )

        reconciliation = await self.engine.finalize_reservation(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
        )

        await ObservabilityAdapter.record_attempt_telemetry(
            reservation=reconciliation.reservation,
            attempt=updated_attempt,
            endpoint=context.endpoint,
        )

        return MeteredEmbeddingResult(
            embeddings=raw_embeddings,
            usage=call_usage,
            reservation=reconciliation.reservation,
            attempts=(updated_attempt,),
            normalized_usage=norm_usage,
        )

    async def execute_tool_decision(
        self,
        context: MeteredRequestContext,
        prompt: str,
        tools: Any,
        config: LLMConfig | None = None,
    ) -> MeteredToolResult:
        """
        Executes policy-governed tool decision through the 10-step metered lifecycle.
        """
        cfg = config or LLMConfig()
        sanitized_prompt = sanitize_prompt_for_provider(prompt)

        estimated_input = context.estimated_input_tokens
        if estimated_input == 500 and len(prompt) > 2000:
            estimated_input = self._estimate_prompt_tokens(prompt)

        # Tx 1: Quota Admission & Reservation
        admission_req = ReservationCreateRequest(
            institution_id=context.institution_id,
            user_id=context.user_id,
            usage_category=context.usage_category,
            endpoint=context.endpoint,
            provider=context.provider,
            model=cfg.model_override or context.model,
            estimated_input_tokens=estimated_input,
            reserved_output_tokens=context.reserved_output_tokens,
            ttl_seconds=context.ttl_seconds,
            idempotency_key=context.idempotency_key,
            logical_operation_id=context.logical_operation_id,
            pricing_version=context.pricing_version,
        )
        admission_result = await self.engine.admit_and_reserve(admission_req)
        res_snapshot = admission_result.reservation

        # Tx 2A: Durable Provider Dispatch (Attempt 1)
        attempt1_req = AttemptDispatchRequest(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            provider=context.provider,
            model=cfg.model_override or context.model,
            estimated_tokens=estimated_input + context.reserved_output_tokens,
            is_fallback=False,
            is_retry=False,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=context.reserved_output_tokens,
            pricing_version=context.pricing_version,
        )
        res_snapshot, attempt1_snap = await self.engine.begin_provider_dispatch(attempt1_req)

        # ZERO DATABASE CONNECTION HELD DURING INFERENCE!
        start_time = time.monotonic()
        primary_success = False
        tool_calls_result: list[ToolCall] = []
        primary_usage: Any = None
        attempt1_error: Exception | None = None

        try:
            tool_calls_result, primary_usage = await asyncio.to_thread(
                self.provider_registry.primary.decide_tools,
                sanitized_prompt,
                tools,
                cfg,
            )
            primary_success = True
        except (ProviderQuotaExhaustedError, ProviderTransientError, ToolDecisionError) as pe:
            attempt1_error = pe
        except Exception as e:
            if is_rate_limit_error(e) or is_transient_error(e):
                attempt1_error = e
            else:
                latency_ms = int((time.monotonic() - start_time) * 1000)
                await self._handle_attempt_failure(
                    res_snapshot=res_snapshot,
                    attempt_snap=attempt1_snap,
                    error=e,
                    latency_ms=latency_ms,
                    is_uncertain=True,
                )
                raise

        latency1_ms = int((time.monotonic() - start_time) * 1000)

        if primary_success:
            norm_usage = self.normalizer.from_llm_call_usage(primary_usage)
            call_dicts = [
                {"name": tc.name, "args": tc.args, "tool_call_id": tc.tool_call_id} for tc in tool_calls_result
            ]
            return await self._finalize_successful_tool_attempt(
                context=context,
                res_snapshot=res_snapshot,
                attempt_snap=attempt1_snap,
                tool_calls=call_dicts,
                norm_usage=norm_usage,
                latency_ms=latency1_ms,
            )

        # Primary failed: record Attempt 1 before fallback
        is_uncertain = not is_rate_limit_error(attempt1_error)
        res_snapshot, attempt1_snap = await self._record_attempt_non_success(
            res_snapshot=res_snapshot,
            attempt_snap=attempt1_snap,
            error=attempt1_error,
            latency_ms=latency1_ms,
            is_uncertain=is_uncertain,
        )

        # Fallback to Groq for tool decision
        fallback_model = getattr(self.provider_registry.fallback, "model", "openai/gpt-oss-120b")
        attempt2_req = AttemptDispatchRequest(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            provider="groq",
            model=fallback_model,
            estimated_tokens=estimated_input + context.reserved_output_tokens,
            is_fallback=True,
            is_retry=False,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=context.reserved_output_tokens,
            pricing_version=context.pricing_version,
        )
        res_snapshot, attempt2_snap = await self.engine.begin_provider_dispatch(attempt2_req)

        start2_time = time.monotonic()
        try:
            fallback_calls, fallback_usage = await asyncio.to_thread(
                self.provider_registry.fallback.decide_tools,
                sanitized_prompt,
                tools,
                cfg,
            )
            latency2_ms = int((time.monotonic() - start2_time) * 1000)
            norm_usage = self.normalizer.from_llm_call_usage(fallback_usage)
            call_dicts = [{"name": tc.name, "args": tc.args, "tool_call_id": tc.tool_call_id} for tc in fallback_calls]
            return await self._finalize_successful_tool_attempt(
                context=context,
                res_snapshot=res_snapshot,
                attempt_snap=attempt2_snap,
                tool_calls=call_dicts,
                norm_usage=norm_usage,
                latency_ms=latency2_ms,
            )
        except Exception as fallback_err:
            latency2_ms = int((time.monotonic() - start2_time) * 1000)
            await self._handle_attempt_failure(
                res_snapshot=res_snapshot,
                attempt_snap=attempt2_snap,
                error=fallback_err,
                latency_ms=latency2_ms,
                is_uncertain=True,
            )
            raise fallback_err from attempt1_error

    async def _finalize_successful_attempt(
        self,
        *,
        context: MeteredRequestContext,
        res_snapshot: ReservationSnapshot,
        attempt_snap: AttemptSnapshot,
        raw_text: str,
        norm_usage: NormalizedUsage,
        latency_ms: int,
    ) -> MeteredAIResult:
        """Records SUCCEEDED attempt, checks guardrails, finalizes reservation, and logs telemetry."""
        # 1. Evaluate output guardrails
        out_eval = default_guardrails_engine.evaluate_output(raw_text)
        final_text = (
            "Security violation: response blocked due to confidential system prompt leakage."
            if out_eval.blocked
            else out_eval.sanitized_text
        )

        # 2. Check usage completeness against Business Decision #4 boundary
        if not norm_usage.is_complete or not norm_usage.is_valid:
            # Missing usage invokes fail-closed resolver via engine.record_attempt_outcome
            logger.warning(
                "Provider %s returned incomplete or invalid usage metadata for attempt %s",
                norm_usage.provider,
                attempt_snap.id,
            )

        # 3. Tx 2B: Record SUCCEEDED attempt outcome
        res_snapshot, updated_attempt = await self.engine.record_attempt_outcome(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            attempt_id=attempt_snap.id,
            status="SUCCEEDED",
            input_tokens=norm_usage.input_tokens,
            output_tokens=norm_usage.output_tokens,
            provider_request_id=norm_usage.provider_request_id,
            latency_ms=latency_ms,
        )

        # 4. Tx 3: Finalize Reservation into COMMITTED
        reconciliation = await self.engine.finalize_reservation(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
        )

        # 5. Operational Telemetry Logging
        await ObservabilityAdapter.record_attempt_telemetry(
            reservation=reconciliation.reservation,
            attempt=updated_attempt,
            endpoint=context.endpoint,
        )

        llm_usage = ObservabilityAdapter.attempt_to_llm_call_usage(updated_attempt)
        return MeteredAIResult(
            text=final_text,
            usage=llm_usage,
            reservation=reconciliation.reservation,
            attempts=reconciliation.attempts,
            normalized_usage=norm_usage,
        )

    async def _finalize_successful_tool_attempt(
        self,
        *,
        context: MeteredRequestContext,
        res_snapshot: ReservationSnapshot,
        attempt_snap: AttemptSnapshot,
        tool_calls: list[dict[str, Any]],
        norm_usage: NormalizedUsage,
        latency_ms: int,
    ) -> MeteredToolResult:
        """Records SUCCEEDED tool decision attempt, finalizes reservation, and logs telemetry."""
        res_snapshot, updated_attempt = await self.engine.record_attempt_outcome(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
            attempt_id=attempt_snap.id,
            status="SUCCEEDED",
            input_tokens=norm_usage.input_tokens,
            output_tokens=norm_usage.output_tokens,
            provider_request_id=norm_usage.provider_request_id,
            latency_ms=latency_ms,
        )

        reconciliation = await self.engine.finalize_reservation(
            institution_id=context.institution_id,
            reservation_id=res_snapshot.id,
        )

        await ObservabilityAdapter.record_attempt_telemetry(
            reservation=reconciliation.reservation,
            attempt=updated_attempt,
            endpoint=context.endpoint,
        )

        llm_usage = ObservabilityAdapter.attempt_to_llm_call_usage(updated_attempt)
        return MeteredToolResult(
            tool_calls=tool_calls,
            usage=llm_usage,
            reservation=reconciliation.reservation,
            attempts=reconciliation.attempts,
            normalized_usage=norm_usage,
        )

    async def _record_attempt_non_success(
        self,
        *,
        res_snapshot: ReservationSnapshot,
        attempt_snap: AttemptSnapshot,
        error: Exception | None,
        latency_ms: int,
        is_uncertain: bool,
    ) -> tuple[ReservationSnapshot, AttemptSnapshot]:
        """Records a failed or uncertain provider attempt prior to fallback."""
        status = "TIMEOUT_UNCERTAIN" if is_uncertain else "FAILED_CONFIRMED"
        err_msg = str(error)[:255] if error else None
        tokens = 0 if not is_uncertain else None

        return await self.engine.record_attempt_outcome(
            institution_id=res_snapshot.institution_id,
            reservation_id=res_snapshot.id,
            attempt_id=attempt_snap.id,
            status=status,
            input_tokens=tokens,
            output_tokens=tokens,
            error_classification=err_msg,
            latency_ms=latency_ms,
        )

    async def _handle_attempt_failure(
        self,
        *,
        res_snapshot: ReservationSnapshot,
        attempt_snap: AttemptSnapshot,
        error: Exception,
        latency_ms: int,
        is_uncertain: bool,
    ) -> None:
        """Finalizes reservation on terminal error, holding uncertain exposure if needed."""
        try:
            res_snapshot, updated_att = await self._record_attempt_non_success(
                res_snapshot=res_snapshot,
                attempt_snap=attempt_snap,
                error=error,
                latency_ms=latency_ms,
                is_uncertain=is_uncertain,
            )
            # Finalize reservation: transitions to UNKNOWN_USAGE if uncertain, or RELEASED if all 0
            await self.engine.finalize_reservation(
                institution_id=res_snapshot.institution_id,
                reservation_id=res_snapshot.id,
                recovery_reason=str(error)[:100],
            )
        except Exception as exc:
            logger.error(
                "Secondary failure while finalizing failed reservation %s: %s",
                res_snapshot.id,
                exc,
                exc_info=True,
            )


__all__ = ["MeteredAIService", "MeteredAIResult", "MeteredToolResult", "MeteredEmbeddingResult"]

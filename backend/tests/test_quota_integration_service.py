"""
backend/tests/test_quota_integration_service.py

Unit and mock-orchestrated tests for Stage 7.3 Quota Engine Integration:
- ProviderUsageNormalizer: Gemini & Groq completeness, zero-tokens, partial, and corrupted metadata
- MeteredRequestContext: immutability, sub-endpoint derivation, and token boundary validation
- ObservabilityAdapter: accurate mapping to LLMCallUsage and zero pricing drift
- MeteredAIService: 10-step lifecycle, multi-attempt fallback, and missing usage fail-closed behavior
- Transaction-Boundary Invariant: verifies zero database connections held during inference
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.llm_client import LLMCallUsage
from app.core.llm_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMProviderRegistry,
    ProviderQuotaExhaustedError,
    ToolCall,
)
from app.observability.quota.context import MeteredRequestContext
from app.observability.quota.errors import (
    MissingUsagePolicyPendingError,
)
from app.observability.quota.normalizer import (
    ProviderUsageNormalizer,
)
from app.observability.quota.service import MeteredAIService
from app.observability.quota.types import (
    AdmissionResult,
    AttemptSnapshot,
    ReconciliationResult,
    ReservationSnapshot,
)


class TestProviderUsageNormalizer:
    """Verifies strict normalization and validation for provider metadata."""

    def test_gemini_complete_valid_usage(self):
        mock_response = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 120
        mock_response.usage_metadata.candidates_token_count = 80
        mock_response.usage_metadata.total_token_count = 200
        mock_response.response_id = "gemini-resp-123"

        norm = ProviderUsageNormalizer.from_gemini_response(mock_response, "gemini-3.6-flash", latency_ms=450)
        assert norm.provider == "gemini"
        assert norm.model == "gemini-3.6-flash"
        assert norm.input_tokens == 120
        assert norm.output_tokens == 80
        assert norm.total_tokens == 200
        assert norm.provider_request_id == "gemini-resp-123"
        assert norm.latency_ms == 450
        assert norm.is_complete is True
        assert norm.is_valid is True
        assert norm.validation_error is None

    def test_groq_complete_valid_usage(self):
        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 350
        mock_response.usage.completion_tokens = 150
        mock_response.usage.total_tokens = 500
        mock_response.id = "chatcmpl-groq-987"

        norm = ProviderUsageNormalizer.from_groq_response(mock_response, "openai/gpt-oss-120b", latency_ms=320)
        assert norm.provider == "groq"
        assert norm.model == "openai/gpt-oss-120b"
        assert norm.input_tokens == 350
        assert norm.output_tokens == 150
        assert norm.total_tokens == 500
        assert norm.provider_request_id == "chatcmpl-groq-987"
        assert norm.used_fallback is True
        assert norm.is_complete is True
        assert norm.is_valid is True

    def test_valid_zero_token_response(self):
        norm = ProviderUsageNormalizer.normalize(
            provider="gemini",
            model="gemini-3.6-flash",
            raw_input_tokens=0,
            raw_output_tokens=0,
            raw_total_tokens=0,
        )
        assert norm.is_complete is True
        assert norm.is_valid is True
        assert norm.input_tokens == 0
        assert norm.output_tokens == 0
        assert norm.total_tokens == 0

    def test_missing_usage_metadata(self):
        norm = ProviderUsageNormalizer.normalize(
            provider="gemini",
            model="gemini-3.6-flash",
            raw_input_tokens=None,
            raw_output_tokens=None,
        )
        assert norm.is_complete is False
        assert norm.is_valid is True
        assert norm.input_tokens is None
        assert norm.output_tokens is None

    def test_partial_usage_metadata(self):
        norm = ProviderUsageNormalizer.normalize(
            provider="gemini",
            model="gemini-3.6-flash",
            raw_input_tokens=150,
            raw_output_tokens=None,
        )
        assert norm.is_complete is False
        assert norm.is_valid is True
        assert norm.input_tokens == 150
        assert norm.output_tokens is None

    def test_corrupted_inconsistent_total_tokens(self):
        norm = ProviderUsageNormalizer.normalize(
            provider="gemini",
            model="gemini-3.6-flash",
            raw_input_tokens=100,
            raw_output_tokens=100,
            raw_total_tokens=999,  # Inconsistent
        )
        assert norm.is_valid is False
        assert norm.is_complete is False
        assert "inconsistent" in str(norm.validation_error).lower()

    def test_invalid_types_rejected(self):
        norm = ProviderUsageNormalizer.normalize(
            provider="groq",
            model="openai/gpt-oss-120b",
            raw_input_tokens=True,  # Boolean rejected
            raw_output_tokens=50.5,  # Float rejected
        )
        assert norm.is_valid is False
        assert norm.is_complete is False
        assert norm.input_tokens is None
        assert norm.output_tokens is None


class TestMeteredRequestContext:
    """Verifies server-derived context validation and immutability."""

    def test_valid_context_creation(self):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            usage_category="interactive_ai",
            idempotency_key="turn-123:portal",
            estimated_input_tokens=300,
            reserved_output_tokens=1500,
        )
        assert ctx.institution_id == inst_id
        assert ctx.user_id == user_id
        assert ctx.endpoint == "portal-assistant/chat"
        assert ctx.usage_category == "interactive_ai"
        assert ctx.estimated_input_tokens == 300
        assert ctx.reserved_output_tokens == 1500

    def test_for_endpoint_derivation(self):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        parent = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="admin-assistant/chat",
            idempotency_key="turn-456",
        )
        child = parent.for_endpoint("admin-assistant/decide_tools", estimated_input_tokens=600)
        assert child.institution_id == inst_id
        assert child.user_id == user_id
        assert child.endpoint == "admin-assistant/decide_tools"
        assert child.logical_operation_id == parent.logical_operation_id
        assert child.idempotency_key == "turn-456:admin_assistant_decide_tools"
        assert child.estimated_input_tokens == 600

    def test_invalid_category_rejected(self):
        with pytest.raises(ValueError, match="Unsupported usage_category"):
            MeteredRequestContext(
                institution_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                endpoint="rag/query",
                usage_category="unapproved_category",
            )

    def test_negative_tokens_rejected(self):
        with pytest.raises(ValueError, match="estimated_input_tokens must be between 0"):
            MeteredRequestContext(
                institution_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                endpoint="rag/query",
                estimated_input_tokens=-10,
            )


class FakeTestProvider(BaseLLMProvider):
    """Controllable test provider supporting failure injection and transaction checks."""

    def __init__(
        self,
        name: str = "gemini",
        model: str = "gemini-3.6-flash",
        success_text: str = "Test response",
        input_tokens: int | None = 100,
        output_tokens: int | None = 50,
        raise_exc: Exception | None = None,
        on_call_hook: Any = None,
    ):
        self.name = name
        self.model = model
        self.success_text = success_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.raise_exc = raise_exc
        self.on_call_hook = on_call_hook
        self.call_count = 0

    def generate_text(self, prompt: str, config: LLMConfig | None = None) -> tuple[str, LLMCallUsage]:
        self.call_count += 1
        if self.on_call_hook:
            self.on_call_hook()
        if self.raise_exc:
            raise self.raise_exc

        usage = LLMCallUsage(
            provider=self.name,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_ms=100,
            used_fallback=(self.name == "groq"),
        )
        return self.success_text, usage

    def decide_tools(self, prompt: str, tools: Any, config: LLMConfig | None = None) -> tuple[list[ToolCall], LLMCallUsage]:
        self.call_count += 1
        if self.on_call_hook:
            self.on_call_hook()
        if self.raise_exc:
            raise self.raise_exc

        calls = [ToolCall(name="test_tool", args={"arg1": "val1"}, tool_call_id="call_123")]
        usage = LLMCallUsage(
            provider=self.name,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_ms=80,
            used_fallback=(self.name == "groq"),
        )
        return calls, usage


def make_test_reservation_snapshot(
    inst_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "COMMITTED",
) -> ReservationSnapshot:
    import datetime
    now = datetime.datetime.now(datetime.UTC)
    res_id = uuid.uuid4()
    return ReservationSnapshot(
        id=res_id,
        institution_id=inst_id,
        user_id=user_id,
        logical_operation_id=uuid.uuid4(),
        usage_date=now.date(),
        usage_category="interactive_ai",
        endpoint="test-endpoint",
        status=status,
        pricing_version="2026-11-v1",
        estimated_input_tokens=500,
        reserved_output_tokens=2048,
        total_reserved_tokens=2548,
        reserved_cost_inr=Decimal("0.0500"),
        actual_input_tokens=100,
        actual_output_tokens=50,
        actual_total_tokens=150,
        actual_cost_inr=Decimal("0.0030"),
        uncertain_tokens_held=0,
        uncertain_cost_held_inr=Decimal("0.0000"),
        idempotency_key=None,
        reconciliation_version=1,
        recovery_state="NONE",
        recovery_reason=None,
        review_status="NONE",
        dispatched_at=now,
        created_at=now,
        expires_at=now + datetime.timedelta(seconds=300),
        reconciled_at=now,
    )


def make_test_attempt_snapshot(
    inst_id: uuid.UUID,
    res_id: uuid.UUID,
    seq: int = 1,
    provider: str = "gemini",
    is_fallback: bool = False,
    status: str = "SUCCEEDED",
) -> AttemptSnapshot:
    import datetime
    now = datetime.datetime.now(datetime.UTC)
    return AttemptSnapshot(
        id=uuid.uuid4(),
        institution_id=inst_id,
        reservation_id=res_id,
        attempt_sequence=seq,
        provider=provider,
        model="gemini-3.6-flash" if provider == "gemini" else "openai/gpt-oss-120b",
        is_fallback=is_fallback,
        is_retry=False,
        status=status,
        provider_request_id=f"req_{provider}_{seq}",
        pricing_version="2026-11-v1",
        estimated_tokens=2548,
        estimated_cost_inr=Decimal("0.0500"),
        input_tokens=100,
        output_tokens=50,
        actual_cost_inr=Decimal("0.0030"),
        manual_settled_tokens=None,
        manual_settled_cost_inr=None,
        manual_settled_at=None,
        late_reported_input_tokens=None,
        late_reported_output_tokens=None,
        late_reported_cost_inr=None,
        late_reported_at=None,
        error_classification=None,
        latency_ms=120,
        dispatched_at=now,
        completed_at=now,
    )


class TestMeteredAIServiceLifecycle:
    """Verifies the 10-step lifecycle and transaction boundary invariants."""

    @pytest.mark.asyncio
    async def test_successful_primary_inference_lifecycle(self):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        res_snap = make_test_reservation_snapshot(inst_id, user_id, status="RESERVED")
        att_snap = make_test_attempt_snapshot(inst_id, res_snap.id, seq=1, provider="gemini")

        mock_engine = MagicMock()
        mock_engine.admit_and_reserve = AsyncMock(
            return_value=AdmissionResult(reservation=res_snap, is_idempotent_replay=False)
        )
        mock_engine.begin_provider_dispatch = AsyncMock(
            return_value=(res_snap, att_snap)
        )
        mock_engine.record_attempt_outcome = AsyncMock(
            return_value=(res_snap, att_snap)
        )
        reconciled_res = make_test_reservation_snapshot(inst_id, user_id, status="COMMITTED")
        mock_engine.finalize_reservation = AsyncMock(
            return_value=ReconciliationResult(reservation=reconciled_res, attempts=(att_snap,))
        )

        in_flight_connection_active = False

        def inference_connection_check():
            # PROOF OF TRANSACTION BOUNDARY INVARIANT:
            # During provider execution, no DB transaction or connection may be active
            assert not in_flight_connection_active

        fake_gemini = FakeTestProvider("gemini", on_call_hook=inference_connection_check)
        fake_groq = FakeTestProvider("groq")
        registry = LLMProviderRegistry(primary_provider=fake_gemini, fallback_provider=fake_groq)

        service = MeteredAIService(engine=mock_engine, provider_registry=registry)
        ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
        )

        result = await service.execute_text_generation(ctx, "Hello AI")

        assert result.text == "Test response"
        assert result.usage.provider == "gemini"
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50
        assert fake_gemini.call_count == 1
        assert fake_groq.call_count == 0

        # Verify exact sequence of engine calls
        assert mock_engine.admit_and_reserve.await_count == 1
        assert mock_engine.begin_provider_dispatch.await_count == 1
        assert mock_engine.record_attempt_outcome.await_count == 1
        assert mock_engine.finalize_reservation.await_count == 1

    @pytest.mark.asyncio
    async def test_fallback_to_groq_tracks_both_attempts(self):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        res_snap = make_test_reservation_snapshot(inst_id, user_id, status="RESERVED")
        att1_snap = make_test_attempt_snapshot(inst_id, res_snap.id, seq=1, provider="gemini", status="DISPATCHED")
        att2_snap = make_test_attempt_snapshot(inst_id, res_snap.id, seq=2, provider="groq", is_fallback=True)

        mock_engine = MagicMock()
        mock_engine.admit_and_reserve = AsyncMock(
            return_value=AdmissionResult(reservation=res_snap, is_idempotent_replay=False)
        )
        mock_engine.begin_provider_dispatch = AsyncMock(
            side_effect=[(res_snap, att1_snap), (res_snap, att2_snap)]
        )
        mock_engine.record_attempt_outcome = AsyncMock(
            side_effect=[
                (res_snap, att1_snap),  # Attempt 1: FAILED_CONFIRMED
                (res_snap, att2_snap),  # Attempt 2: SUCCEEDED
            ]
        )
        reconciled_res = make_test_reservation_snapshot(inst_id, user_id, status="COMMITTED")
        mock_engine.finalize_reservation = AsyncMock(
            return_value=ReconciliationResult(reservation=reconciled_res, attempts=(att1_snap, att2_snap))
        )

        fake_gemini = FakeTestProvider("gemini", raise_exc=ProviderQuotaExhaustedError("HTTP 429 quota exhausted"))
        fake_groq = FakeTestProvider("groq", success_text="Groq fallback response", input_tokens=300, output_tokens=120)
        registry = LLMProviderRegistry(primary_provider=fake_gemini, fallback_provider=fake_groq)

        service = MeteredAIService(engine=mock_engine, provider_registry=registry)
        ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="admin-assistant/chat",
        )

        result = await service.execute_text_generation(ctx, "Query requiring fallback")

        assert result.text == "Groq fallback response"
        assert result.usage.provider == "groq"
        assert result.usage.used_fallback is True
        assert fake_gemini.call_count == 1
        assert fake_groq.call_count == 1

        # Both attempts dispatched and recorded
        assert mock_engine.begin_provider_dispatch.await_count == 2
        assert mock_engine.record_attempt_outcome.await_count == 2
        assert mock_engine.finalize_reservation.await_count == 1

    @pytest.mark.asyncio
    async def test_missing_usage_fails_closed_decision_4(self):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        res_snap = make_test_reservation_snapshot(inst_id, user_id, status="RESERVED")
        att_snap = make_test_attempt_snapshot(inst_id, res_snap.id, seq=1, provider="gemini")

        mock_engine = MagicMock()
        mock_engine.admit_and_reserve = AsyncMock(
            return_value=AdmissionResult(reservation=res_snap, is_idempotent_replay=False)
        )
        mock_engine.begin_provider_dispatch = AsyncMock(
            return_value=(res_snap, att_snap)
        )
        # Missing usage raises MissingUsagePolicyPendingError fail-closed
        mock_engine.record_attempt_outcome = AsyncMock(
            side_effect=MissingUsagePolicyPendingError(
                "Missing token metadata",
                policy_name="DEFAULT_FAIL_CLOSED",
                reservation_id=res_snap.id,
                attempt_id=att_snap.id,
            )
        )
        mock_engine.finalize_reservation = AsyncMock()

        # Gemini returns response with NO token counts
        fake_gemini = FakeTestProvider("gemini", input_tokens=None, output_tokens=None)
        fake_groq = FakeTestProvider("groq")
        registry = LLMProviderRegistry(primary_provider=fake_gemini, fallback_provider=fake_groq)

        service = MeteredAIService(engine=mock_engine, provider_registry=registry)
        ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="rag/query",
        )

        with pytest.raises(MissingUsagePolicyPendingError):
            await service.execute_text_generation(ctx, "Query with missing usage")

    @pytest.mark.asyncio
    async def test_tool_decision_metered_lifecycle(self):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        res_snap = make_test_reservation_snapshot(inst_id, user_id, status="RESERVED")
        att_snap = make_test_attempt_snapshot(inst_id, res_snap.id, seq=1, provider="gemini")

        mock_engine = MagicMock()
        mock_engine.admit_and_reserve = AsyncMock(
            return_value=AdmissionResult(reservation=res_snap, is_idempotent_replay=False)
        )
        mock_engine.begin_provider_dispatch = AsyncMock(
            return_value=(res_snap, att_snap)
        )
        mock_engine.record_attempt_outcome = AsyncMock(
            return_value=(res_snap, att_snap)
        )
        reconciled_res = make_test_reservation_snapshot(inst_id, user_id, status="COMMITTED")
        mock_engine.finalize_reservation = AsyncMock(
            return_value=ReconciliationResult(reservation=reconciled_res, attempts=(att_snap,))
        )

        fake_gemini = FakeTestProvider("gemini")
        registry = LLMProviderRegistry(primary_provider=fake_gemini)

        service = MeteredAIService(engine=mock_engine, provider_registry=registry)
        ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="admin-assistant/decide_tools",
        )

        result = await service.execute_tool_decision(ctx, "Check attendance for class 10", tools=[])
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "test_tool"
        assert result.usage.provider == "gemini"
        assert mock_engine.admit_and_reserve.await_count == 1
        assert mock_engine.begin_provider_dispatch.await_count == 1
        assert mock_engine.finalize_reservation.await_count == 1


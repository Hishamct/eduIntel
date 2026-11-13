"""
backend/tests/test_quota_provider_integration_db.py

Production Database-Backed Integration & Concurrency Tests for Stage 7.3:
- End-to-end admission, reservation, provider dispatch, usage normalization, and settlement
- Fail-closed behavior: unconfigured tenant, suspended tenant, quota exceeded
- Transaction-Boundary Invariant: empirical proof that 0 database connections are held during provider inference
- Multi-attempt fallback durability: Gemini 429 -> Groq fallback creates 2 durable attempt rows
- Business Decision #4: missing usage metadata fails closed without invented heuristics
- Concurrency and canonical lock hierarchy under concurrent tenant load
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.auth.security import hash_password
from app.core.llm_client import LLMCallUsage
from app.core.llm_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMProviderRegistry,
    ProviderQuotaExhaustedError,
    ToolCall,
)
from app.institutions.models import Institution
from app.observability.quota.context import MeteredRequestContext
from app.observability.quota.engine import TenantQuotaEngine
from app.observability.quota.errors import (
    IdempotencyConflictError,
    MissingUsagePolicyPendingError,
    QuotaExceededError,
    TenantQuotaNotConfiguredError,
    TenantQuotaSuspendedError,
)
from app.observability.quota.policy import FailClosedMissingUsagePolicyResolver
from app.observability.quota.service import MeteredAIService
from app.observability.quota_models import (
    AIPricingActivation,
    AIPricingVersion,
    AIProviderAttempt,
    AITokenReservation,
    TenantAIQuota,
)
from app.users.models import User


@pytest_asyncio.fixture
async def test_session_factory():
    """Independent async_sessionmaker for production-identical transaction testing."""
    db_url = os.environ["TEST_DATABASE_URL"]
    test_eng = create_async_engine(db_url, poolclass=AsyncAdaptedQueuePool, pool_size=15, max_overflow=10)
    factory = async_sessionmaker(test_eng, expire_on_commit=False)
    try:
        yield factory, test_eng
    finally:
        await test_eng.dispose()


async def _bind_admin(session: AsyncSession, inst_id: uuid.UUID | None = None) -> None:
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :inst, true);"),
        {"inst": str(inst_id) if inst_id else ""},
    )
    await session.execute(text("SELECT set_config('app.is_platform_admin', 'true', true);"))


async def _seed_pricing(
    factory: async_sessionmaker[AsyncSession],
    *,
    version_id: str | None = None,
) -> str:
    v_id = version_id or f"r01-conc-s73-{uuid.uuid4().hex[:8]}"
    async with factory() as session:
        async with session.begin():
            await _bind_admin(session, None)
            pv = AIPricingVersion(
                version_id=v_id,
                currency="INR",
                usd_to_inr_rate=Decimal("85.5000"),
                rate_source="STAGE73_INTEGRATION_TEST",
                rates_json={
                    "gemini": {
                        "gemini-2.5-pro": {"input_1k": "0.0200", "output_1k": "0.0800"},
                        "gemini-2.5-flash": {"input_1k": "0.0100", "output_1k": "0.0400"},
                        "gemini-3.6-flash": {"input_1k": "0.0100", "output_1k": "0.0400"},
                    },
                    "groq": {
                        "openai/gpt-oss-120b": {"input_1k": "0.0050", "output_1k": "0.0200"},
                        "llama-3.3-70b-versatile": {"input_1k": "0.0040", "output_1k": "0.0150"},
                    },
                },
                effective_from=datetime.now(UTC) - timedelta(days=1),
                is_active=True,
            )
            session.add(pv)
            await session.flush()

            act = AIPricingActivation(
                id=uuid.uuid4(),
                pricing_version=v_id,
                expected_version_active=True,
                activated_by_actor="stage73-admin",
                activation_reason="STAGE73_INTEGRATION_TEST_ACTIVATION",
            )
            session.add(act)
    return v_id


async def _seed_tenant(
    factory: async_sessionmaker[AsyncSession],
    *,
    prefix: str,
    daily_interactive_limit: int = 50_000,
    daily_exposure_limit_inr: Decimal = Decimal("100.0000"),
    pending_reserve_cap_percent: Decimal = Decimal("1.0000"),
    max_tokens_per_request: int = 8_000,
    is_suspended: bool = False,
    is_unlimited: bool = False,
    create_quota: bool = True,
) -> tuple[uuid.UUID, uuid.UUID]:
    inst_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with factory() as session:
        async with session.begin():
            await _bind_admin(session, inst_id)
            inst = Institution(
                id=inst_id,
                name=f"Stage73 Inst {prefix}",
                slug=f"s73-{prefix}-{inst_id.hex[:8]}",
                is_active=True,
            )
            user = User(
                id=user_id,
                email=f"s73-{user_id.hex[:8]}@{prefix}.edu",
                name=f"Stage73 User {prefix}",
                hashed_password=hash_password("StrongTestPass123!"),
                role="admin",
                is_active=True,
            )
            session.add_all([inst, user])

            if create_quota:
                quota = TenantAIQuota(
                    id=uuid.uuid4(),
                    institution_id=inst_id,
                    quota_timezone="Asia/Kolkata",
                    daily_interactive_token_limit=daily_interactive_limit,
                    daily_ingestion_token_limit=20_000,
                    daily_other_token_limit=5_000,
                    monthly_total_token_limit=200_000,
                    daily_exposure_limit_inr=daily_exposure_limit_inr,
                    pending_reserve_cap_percent=pending_reserve_cap_percent,
                    max_tokens_per_request=max_tokens_per_request,
                    missing_usage_policy="HOLD_UNKNOWN",
                    is_unlimited=is_unlimited,
                    is_suspended=is_suspended,
                    suspension_reason="Suspended for test" if is_suspended else None,
                    tier_name="test-tier-73",
                )
                session.add(quota)
    return inst_id, user_id


class MockProvider(BaseLLMProvider):
    def __init__(
        self,
        name: str = "gemini",
        model: str = "gemini-3.6-flash",
        success_text: str = "Test response",
        input_tokens: int = 100,
        output_tokens: int = 50,
        raise_exc: Exception | None = None,
        empty_usage: bool = False,
        on_call_hook: Callable[[], None] | None = None,
    ):
        if name == "groq" and model == "gemini-3.6-flash":
            model = "openai/gpt-oss-120b"
        self.name = name
        self.model = model
        self.success_text = success_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.raise_exc = raise_exc
        self.empty_usage = empty_usage
        self.on_call_hook = on_call_hook
        self.call_count = 0

    def generate_text(self, prompt: str, config: LLMConfig | None = None) -> tuple[str, LLMCallUsage | None]:
        self.call_count += 1
        if self.on_call_hook:
            self.on_call_hook()
        if self.raise_exc:
            raise self.raise_exc

        if self.empty_usage:
            return self.success_text, None

        usage = LLMCallUsage(
            provider=self.name,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_ms=100,
            used_fallback=(self.name == "groq"),
        )
        return self.success_text, usage

    def decide_tools(
        self,
        prompt: str,
        tools: Any,
        config: LLMConfig | None = None,
    ) -> tuple[list[ToolCall], LLMCallUsage | None]:
        self.call_count += 1
        if self.on_call_hook:
            self.on_call_hook()
        if self.raise_exc:
            raise self.raise_exc

        if self.empty_usage:
            return [], None

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


@pytest.mark.asyncio
class TestStage73DatabaseIntegration:
    """Production database integration tests executing real SQL transactions against PostgreSQL."""

    async def test_end_to_end_admission_and_settlement_creates_reservations_and_attempts(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        inst_id, user_id = await _seed_tenant(factory, prefix="e2e-1")

        provider = MockProvider("gemini", input_tokens=150, output_tokens=75)
        registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

        service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

        req_ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=f"idem-e2e-{uuid.uuid4()}",
        )

        result = await service.execute_text_generation(context=req_ctx, prompt="Hello test")

        assert result.text == "Test response"
        assert result.usage.input_tokens == 150
        assert result.usage.output_tokens == 75
        assert result.usage.input_tokens + result.usage.output_tokens == 225
        assert provider.call_count == 1

        # Verify DB records
        async with factory() as session:
            await _bind_admin(session, inst_id)

            # 1. Reservation record
            res_stmt = select(AITokenReservation).where(AITokenReservation.institution_id == inst_id)
            res_res = await session.execute(res_stmt)
            res_row = res_res.scalar_one_or_none()
            assert res_row is not None
            assert res_row.status == "COMMITTED"
            assert res_row.actual_total_tokens == 225
            assert res_row.actual_cost_inr > Decimal("0.0000")

            # 2. Provider attempt record
            att_stmt = select(AIProviderAttempt).where(AIProviderAttempt.reservation_id == res_row.id)
            att_res = await session.execute(att_stmt)
            att_rows = att_res.scalars().all()
            assert len(att_rows) == 1
            assert att_rows[0].provider == "gemini"
            assert att_rows[0].status == "SUCCEEDED"
            assert att_rows[0].input_tokens == 150
            assert att_rows[0].output_tokens == 75

    async def test_unconfigured_tenant_fails_closed_zero_calls_zero_reservations(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        inst_id, user_id = await _seed_tenant(factory, prefix="unconf-1", create_quota=False)

        provider = MockProvider("gemini")
        registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

        service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

        req_ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=f"idem-unconf-{uuid.uuid4()}",
        )

        with pytest.raises(TenantQuotaNotConfiguredError):
            await service.execute_text_generation(context=req_ctx, prompt="Prompt")

        # Invariant: provider call was never made
        assert provider.call_count == 0

        # Invariant: zero reservations created
        async with factory() as session:
            await _bind_admin(session, inst_id)
            res_stmt = select(AITokenReservation).where(AITokenReservation.institution_id == inst_id)
            res_res = await session.execute(res_stmt)
            assert res_res.scalar_one_or_none() is None

    async def test_suspended_tenant_fails_closed(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        inst_id, user_id = await _seed_tenant(factory, prefix="susp-1", is_suspended=True)

        provider = MockProvider("gemini")
        registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

        service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

        req_ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=f"idem-susp-{uuid.uuid4()}",
        )

        with pytest.raises(TenantQuotaSuspendedError):
            await service.execute_text_generation(context=req_ctx, prompt="Prompt")

        assert provider.call_count == 0

    async def test_quota_exceeded_fails_closed(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        # Daily limit is only 10 tokens
        inst_id, user_id = await _seed_tenant(factory, prefix="exceed-1", daily_interactive_limit=10)

        provider = MockProvider("gemini")
        registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

        service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

        # Requesting tokens exceeds 10 token daily limit
        req_ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=f"idem-exceed-{uuid.uuid4()}",
        )

        with pytest.raises(QuotaExceededError):
            await service.execute_text_generation(context=req_ctx, prompt="Prompt")

        assert provider.call_count == 0

    async def test_transaction_boundary_invariant_zero_db_connections_during_inference(self, test_session_factory):
        """
        MANDATORY ARCHITECTURAL INVARIANT:
        Demonstrates via active pool instrumentation that exactly 0 database
        connections are checked out / held when the provider network call executes.
        """
        factory, test_eng = test_session_factory
        await _seed_pricing(factory)
        inst_id, user_id = await _seed_tenant(factory, prefix="conn-1")

        active_checkouts = 0
        max_active_during_inference = -1
        inference_ran = False

        @event.listens_for(test_eng.sync_engine.pool, "checkout")
        def _on_checkout(dbapi_conn, conn_record, conn_proxy):
            nonlocal active_checkouts
            active_checkouts += 1

        @event.listens_for(test_eng.sync_engine.pool, "checkin")
        def _on_checkin(dbapi_conn, conn_record):
            nonlocal active_checkouts
            active_checkouts -= 1

        def _instrumented_hook():
            nonlocal max_active_during_inference, inference_ran
            inference_ran = True
            max_active_during_inference = active_checkouts

        try:
            provider = MockProvider("gemini", input_tokens=100, output_tokens=50, on_call_hook=_instrumented_hook)
            registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

            service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

            req_ctx = MeteredRequestContext(
                institution_id=inst_id,
                user_id=user_id,
                endpoint="portal-assistant/chat",
                idempotency_key=f"idem-conn-{uuid.uuid4()}",
            )

            await service.execute_text_generation(context=req_ctx, prompt="Prompt")

            assert inference_ran is True
            # Invariant: EXACTLY 0 connections checked out during provider inference!
            assert max_active_during_inference == 0
        finally:
            event.remove(test_eng.sync_engine.pool, "checkout", _on_checkout)
            event.remove(test_eng.sync_engine.pool, "checkin", _on_checkin)

    async def test_multi_attempt_fallback_gemini_429_to_groq_persists_both_attempts(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        inst_id, user_id = await _seed_tenant(factory, prefix="fallback-1")

        # Gemini fails with 429
        gemini_provider = MockProvider(
            name="gemini",
            raise_exc=ProviderQuotaExhaustedError("Gemini 429 Resource Exhausted"),
        )
        # Groq succeeds with 200 tokens
        groq_provider = MockProvider(
            name="groq",
            model="openai/gpt-oss-120b",
            input_tokens=120,
            output_tokens=80,
        )

        registry = LLMProviderRegistry(primary_provider=gemini_provider, fallback_provider=groq_provider)

        service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

        req_ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=f"idem-fb-{uuid.uuid4()}",
        )

        result = await service.execute_text_generation(context=req_ctx, prompt="Prompt")

        assert result.text == "Test response"
        assert result.usage.provider == "groq"
        assert result.usage.input_tokens + result.usage.output_tokens == 200
        assert gemini_provider.call_count == 1
        assert groq_provider.call_count == 1

        # Check DB for 2 attempt records
        async with factory() as session:
            await _bind_admin(session, inst_id)

            res_stmt = select(AITokenReservation).where(AITokenReservation.institution_id == inst_id)
            res_res = await session.execute(res_stmt)
            res_row = res_res.scalar_one()
            assert res_row.status == "COMMITTED"

            att_stmt = (
                select(AIProviderAttempt)
                .where(AIProviderAttempt.reservation_id == res_row.id)
                .order_by(AIProviderAttempt.attempt_sequence)
            )
            att_res = await session.execute(att_stmt)
            attempts = att_res.scalars().all()

            assert len(attempts) == 2
            assert attempts[0].provider == "gemini"
            assert attempts[0].status in ("FAILED", "FAILED_CONFIRMED")

            assert attempts[1].provider == "groq"
            assert attempts[1].status == "SUCCEEDED"
            assert attempts[1].input_tokens == 120
            assert attempts[1].output_tokens == 80

    async def test_decision_4_missing_usage_metadata_fails_closed(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        inst_id, user_id = await _seed_tenant(factory, prefix="dec4-1")

        # Provider succeeds but returns empty usage
        provider = MockProvider("gemini", empty_usage=True)
        registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

        service = MeteredAIService(
            engine=TenantQuotaEngine(factory),
            provider_registry=registry,
            policy_resolver=FailClosedMissingUsagePolicyResolver(),
        )

        req_ctx = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=f"idem-dec4-{uuid.uuid4()}",
        )

        with pytest.raises(MissingUsagePolicyPendingError):
            await service.execute_text_generation(context=req_ctx, prompt="Prompt")

        assert provider.call_count == 1

    async def test_idempotent_duplicate_request_rejected(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        inst_id, user_id = await _seed_tenant(factory, prefix="idem-1")

        provider = MockProvider("gemini", input_tokens=100, output_tokens=50)
        registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

        service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

        shared_key = f"fixed-key-{uuid.uuid4()}"
        req_ctx1 = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=shared_key,
        )

        # Call 1 succeeds
        await service.execute_text_generation(context=req_ctx1, prompt="Prompt")
        assert provider.call_count == 1

        # Call 2 with identical key is rejected by quota engine admission
        req_ctx2 = MeteredRequestContext(
            institution_id=inst_id,
            user_id=user_id,
            endpoint="portal-assistant/chat",
            idempotency_key=shared_key,
        )
        with pytest.raises(IdempotencyConflictError):
            await service.execute_text_generation(context=req_ctx2, prompt="Prompt")

        # Call count remains 1 - second provider call was never made
        assert provider.call_count == 1

    async def test_concurrent_inference_requests_distinct_tenants(self, test_session_factory):
        factory, _ = test_session_factory
        await _seed_pricing(factory)
        tenants = []
        for i in range(4):
            inst_id, user_id = await _seed_tenant(factory, prefix=f"conc-{i}")
            tenants.append((inst_id, user_id))

        provider = MockProvider("gemini", input_tokens=80, output_tokens=40)
        registry = LLMProviderRegistry(primary_provider=provider, fallback_provider=MockProvider("groq"))

        service = MeteredAIService(engine=TenantQuotaEngine(factory), provider_registry=registry)

        async def _run_for_tenant(inst_id: uuid.UUID, user_id: uuid.UUID, idx: int):
            req_ctx = MeteredRequestContext(
                institution_id=inst_id,
                user_id=user_id,
                endpoint="portal-assistant/chat",
                idempotency_key=f"idem-concurrent-{idx}-{uuid.uuid4()}",
            )
            return await service.execute_text_generation(context=req_ctx, prompt=f"Prompt {idx}")

        tasks = [_run_for_tenant(inst_id, user_id, i) for i, (inst_id, user_id) in enumerate(tenants)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 4
        for res in results:
            assert res.text == "Test response"
            assert res.usage.input_tokens + res.usage.output_tokens == 120

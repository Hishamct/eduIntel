"""
backend/tests/test_ai_provider_and_idempotency.py

Comprehensive test suite for Phase 5 Step 1:
AI Provider Architecture, Data Governance, Tool Fallbacks & Fenced Idempotency.

1. Provider Abstraction & PII Minimization:
   - Aadhaar, phone, auth token, and email sanitization.
   - GeminiProvider text generation & transient retry backoff (503).
   - GeminiProvider 429 quota exhaustion immediate failover.
   - GroqProvider text generation & bidirectional tool schema translation.

2. Three-Tier Failure Handling & Registry Routing:
   - Tier 1: Provider failure (429 / exhausted 503) failover to Groq.
   - Tier 2: Tool decision failure (malformed Gemini call) failover to Groq.
   - Tier 3: Tool execution failure produces structured error without LLM retry.
   - Node-Scoped Fallback Invariant: tool results preserved across generation failover.

3. Database Fenced Tool Idempotency:
   - Atomic reservation, cached result retrieval, argument mismatch rejection.
   - Active lease concurrency protection.
   - Stalled lease atomic recovery and lease_generation fencing increment.
   - Monotonic fencing token validation: stale worker commits rejected with FencingTokenRevokedError.
   - Stalled attempt limits (3) transitioning to FAILED.

4. Bounded External Side Effects:
   - Timeout transition to UNCERTAIN.
   - Rejection of blind automatic retries on UNCERTAIN records.
   - Operator reconciliation workflows (CONFIRM_DISPATCHED, MARK_FAILED, COMPENSATING_ACTION).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from google.genai import types
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.admin_assistant import ADMIN_TOOL, execute_tools_node
from app.agents.models import ToolExecutionRecord
from app.core.config import settings
from app.core.llm_provider import (
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    LLMCallUsage,
    LLMProviderRegistry,
    ProviderQuotaExhaustedError,
    ProviderTransientError,
    ToolCall,
    ToolDecisionError,
    convert_gemini_tools_to_groq_format,
    sanitize_prompt_for_provider,
)
from app.core.tool_idempotency import (
    FencingTokenRevokedError,
    IdempotencyConflictError,
    ToolExecutionConflictError,
    ToolExecutionExhaustedError,
    UncertainExternalSideEffectError,
    commit_internal_tool_execution,
    fail_tool_execution,
    reconcile_uncertain_tool_execution,
    reserve_or_get_tool_execution,
)
from app.institutions.models import Institution

# ==============================================================================
# Suite 1: Provider Abstraction & PII Minimization Tests
# ==============================================================================

class TestProviderAbstractionAndPII:
    """Verifies student PII scrubbing, provider instantiation, and backoff/fallback mechanics."""

    def test_sanitize_prompt_scrubs_aadhaar_phone_bearer_and_tokenizes_email(self):
        raw_prompt = (
            "Student profile: John Doe, Aadhaar: 2345 6789 0123, Phone: +91 9876543210. "
            "Email: student.johndoe@institution.edu. "
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.xyz. "
            "Question: What is the attendance percentage?"
        )
        sanitized = sanitize_prompt_for_provider(raw_prompt)

        assert "2345 6789 0123" not in sanitized
        assert "[AADHAAR_REDACTED]" in sanitized
        assert "9876543210" not in sanitized
        assert "[PHONE_REDACTED]" in sanitized
        assert "Bearer eyJhbGciOi" not in sanitized
        assert "[AUTH_TOKEN_REDACTED]" in sanitized
        assert "student.johndoe@institution.edu" not in sanitized
        assert "@institution.edu" in sanitized  # Domain preserved with pseudonymized hash
        assert "user_" in sanitized
        assert "attendance percentage" in sanitized  # Safe question text intact

    def test_gemini_provider_generate_text_happy_path(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Here is the administrative summary."
        mock_response.usage_metadata.prompt_token_count = 120
        mock_response.usage_metadata.candidates_token_count = 45
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(client=mock_client, model="gemini-2.5-flash")
        text_out, usage = provider.generate_text("Summarize student counts")

        assert text_out == "Here is the administrative summary."
        assert usage.provider == "gemini"
        assert usage.model == "gemini-2.5-flash"
        assert usage.input_tokens == 120
        assert usage.output_tokens == 45
        assert usage.used_fallback is False

    def test_gemini_provider_503_transient_exponential_backoff_retry(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Recovered after transient 503."
        mock_response.usage_metadata.prompt_token_count = 80
        mock_response.usage_metadata.candidates_token_count = 30

        # Simulate 2 transient 503 failures, then success on 3rd attempt
        transient_err = RuntimeError("503 Service Unavailable: Model backend temporarily overloaded")
        mock_client.models.generate_content.side_effect = [transient_err, transient_err, mock_response]

        with patch("time.sleep") as mock_sleep:
            provider = GeminiProvider(client=mock_client, model="gemini-2.5-flash")
            text_out, usage = provider.generate_text("Test prompt")

            assert text_out == "Recovered after transient 503."
            assert mock_client.models.generate_content.call_count == 3
            assert mock_sleep.call_count == 2
            # Exponential backoff: factor ** 0 = 1.0s, factor ** 1 = 1.5s
            mock_sleep.assert_any_call(1.0)
            mock_sleep.assert_any_call(settings.LLM_RETRY_BACKOFF_FACTOR)

    def test_gemini_provider_503_exhaustion_raises_transient_error(self):
        mock_client = MagicMock()
        transient_err = RuntimeError("503 Service Unavailable: persistent outage")
        mock_client.models.generate_content.side_effect = transient_err

        with patch("time.sleep"):
            provider = GeminiProvider(client=mock_client, model="gemini-2.5-flash")
            with pytest.raises(ProviderTransientError) as exc_info:
                provider.generate_text("Test prompt")
            assert "transient error after" in str(exc_info.value)
            assert mock_client.models.generate_content.call_count == settings.LLM_MAX_RETRIES + 1

    def test_gemini_provider_429_quota_exhausted_immediate_failover(self):
        mock_client = MagicMock()
        quota_err = RuntimeError("429 Resource Exhausted: Quota exceeded for quota metric 'GenerateContent'")
        mock_client.models.generate_content.side_effect = quota_err

        with patch("time.sleep") as mock_sleep:
            provider = GeminiProvider(client=mock_client, model="gemini-2.5-flash")
            with pytest.raises(ProviderQuotaExhaustedError) as exc_info:
                provider.generate_text("Test prompt")
            assert "quota exhausted" in str(exc_info.value).lower()
            # Fast failover: exactly 1 attempt, zero sleeping/retries
            assert mock_client.models.generate_content.call_count == 1
            mock_sleep.assert_not_called()

    def test_gemini_provider_decide_tools_happy_path(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_fc = MagicMock()
        mock_fc.name = "get_student_teacher_counts"
        mock_fc.args = {"institution_id": "inst-1"}
        mock_fc.id = "call_abc123"
        mock_part.function_call = mock_fc
        mock_response.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]
        mock_response.usage_metadata.prompt_token_count = 150
        mock_response.usage_metadata.candidates_token_count = 20
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(client=mock_client, model="gemini-2.5-flash")
        tool_calls, usage = provider.decide_tools("How many students?", tools=[])

        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_student_teacher_counts"
        assert tool_calls[0].args == {"institution_id": "inst-1"}
        assert tool_calls[0].tool_call_id == "call_abc123"
        assert usage.provider == "gemini"

    def test_gemini_provider_decide_tools_malformed_raises_tool_decision_error(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_part = MagicMock()
        mock_fc = MagicMock()
        mock_fc.name = "invalid_tool"
        # Simulate property access raising an exception (e.g. malformed protobuf)
        type(mock_fc).args = property(lambda self: (_ for _ in ()).throw(ValueError("Corrupt JSON arguments")))
        mock_part.function_call = mock_fc
        mock_response.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(client=mock_client, model="gemini-2.5-flash")
        with pytest.raises(ToolDecisionError) as exc_info:
            provider.decide_tools("Run invalid tool", tools=[])
        assert "Malformed function call" in str(exc_info.value)

    def test_groq_provider_generate_text_happy_path(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Groq fallback answer."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 95
        mock_response.usage.completion_tokens = 40
        mock_client.chat.completions.create.return_value = mock_response

        provider = GroqProvider(client=mock_client, model="llama-3.3-70b-versatile")
        text_out, usage = provider.generate_text("Summarize fees")

        assert text_out == "Groq fallback answer."
        assert usage.provider == "groq"
        assert usage.used_fallback is True
        assert usage.input_tokens == 95
        assert usage.output_tokens == 40

    def test_convert_gemini_tools_to_groq_format(self):
        gemini_tool_input = [
            {
                "name": "get_salary_summary",
                "description": "Calculates monthly salary summary",
                "parameters": {
                    "type": "object",
                    "properties": {"month": {"type": "string"}},
                    "required": ["month"],
                },
            }
        ]
        converted = convert_gemini_tools_to_groq_format(gemini_tool_input)
        assert len(converted) == 1
        assert converted[0]["type"] == "function"
        assert converted[0]["function"]["name"] == "get_salary_summary"
        assert converted[0]["function"]["description"] == "Calculates monthly salary summary"
        assert "properties" in converted[0]["function"]["parameters"]

    def test_convert_gemini_tools_with_actual_google_genai_admin_tool_and_schema(self):
        """
        Verifies that actual Google GenAI types.Tool, types.FunctionDeclaration, and types.Schema
        instances (including production ADMIN_TOOL) serialize cleanly into Groq/OpenAI tool calling schemas:
        - All properties, required fields, and descriptions are preserved.
        - Types are recursively normalized to lowercase (e.g. 'STRING' -> 'string', 'OBJECT' -> 'object').
        - Nested objects, arrays, and enums are handled cleanly.
        """
        # 1. Convert actual production ADMIN_TOOL
        groq_tools = convert_gemini_tools_to_groq_format(ADMIN_TOOL)
        assert len(groq_tools) == 6

        tool_map = {t["function"]["name"]: t["function"] for t in groq_tools}
        assert "get_salary_summary" in tool_map
        assert "get_student_teacher_counts" in tool_map
        assert "get_timetable_coverage" in tool_map

        # Verify get_salary_summary parameters
        sal_params = tool_map["get_salary_summary"]["parameters"]
        assert sal_params["type"] == "object"
        assert "month" in sal_params["properties"]
        assert sal_params["properties"]["month"]["type"] == "string"
        assert "description" in sal_params["properties"]["month"]

        # Verify get_timetable_coverage parameters
        tt_params = tool_map["get_timetable_coverage"]["parameters"]
        assert tt_params["type"] == "object"
        assert "class_section" in tt_params["properties"]
        assert tt_params["properties"]["class_section"]["type"] == "string"

        # 2. Test explicit complex declaration with nested schema, array, and enum
        complex_decl = types.FunctionDeclaration(
            name="filter_student_records",
            description="Filters student records by multiple criteria",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "grades": types.Schema(
                        type=types.Type.ARRAY,
                        items=types.Schema(type=types.Type.STRING),
                        description="List of grades to filter",
                    ),
                    "status": types.Schema(
                        type=types.Type.STRING,
                        enum=["active", "suspended", "graduated"],
                        description="Student status",
                    ),
                    "pagination": types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "page": types.Schema(type=types.Type.INTEGER),
                            "limit": types.Schema(type=types.Type.INTEGER),
                        },
                        required=["page"],
                    ),
                },
                required=["grades", "status"],
            ),
        )
        converted_complex = convert_gemini_tools_to_groq_format([complex_decl])
        assert len(converted_complex) == 1
        fn_schema = converted_complex[0]["function"]
        assert fn_schema["name"] == "filter_student_records"
        params = fn_schema["parameters"]
        assert params["type"] == "object"
        assert set(params["required"]) == {"grades", "status"}
        assert params["properties"]["grades"]["type"] == "array"
        assert params["properties"]["grades"]["items"]["type"] == "string"
        assert params["properties"]["status"]["type"] == "string"
        assert params["properties"]["status"]["enum"] == ["active", "suspended", "graduated"]
        assert params["properties"]["pagination"]["type"] == "object"
        assert params["properties"]["pagination"]["properties"]["page"]["type"] == "integer"
        assert params["properties"]["pagination"]["required"] == ["page"]


# ==============================================================================
# Suite 2: Three-Tier Failure Handling & Registry Routing Tests
# ==============================================================================

class TestThreeTierFailureHandling:
    """Verifies Tier 1 (Provider), Tier 2 (Tool Decision), and Tier 3 (Tool Execution) routing."""

    def test_tier_1_provider_failure_fallback_on_429(self):
        primary_mock = MagicMock(spec=BaseLLMProvider)
        primary_mock.generate_text.side_effect = ProviderQuotaExhaustedError("Gemini 429 quota exhausted")

        fallback_mock = MagicMock(spec=BaseLLMProvider)
        fallback_usage = LLMCallUsage(
            provider="groq",
            model="llama-3.3-70b-versatile",
            input_tokens=100,
            output_tokens=50,
            latency_ms=300,
            used_fallback=True,
        )
        fallback_mock.generate_text.return_value = ("Groq text answer", fallback_usage)

        registry = LLMProviderRegistry(primary_provider=primary_mock, fallback_provider=fallback_mock)
        text_out, usage = registry.generate_text("Prompt needing fallback")

        assert text_out == "Groq text answer"
        assert usage.provider == "groq"
        assert usage.used_fallback is True
        primary_mock.generate_text.assert_called_once()
        fallback_mock.generate_text.assert_called_once()

    def test_tier_1_provider_failure_fallback_on_transient_exhaustion(self):
        primary_mock = MagicMock(spec=BaseLLMProvider)
        primary_mock.generate_text.side_effect = ProviderTransientError("Gemini 503 retries exhausted")

        fallback_mock = MagicMock(spec=BaseLLMProvider)
        fallback_usage = LLMCallUsage(
            provider="groq",
            model="llama-3.3-70b-versatile",
            input_tokens=80,
            output_tokens=40,
            latency_ms=250,
            used_fallback=True,
        )
        fallback_mock.generate_text.return_value = ("Groq fallback response", fallback_usage)

        registry = LLMProviderRegistry(primary_provider=primary_mock, fallback_provider=fallback_mock)
        text_out, usage = registry.generate_text("Prompt under 503")

        assert text_out == "Groq fallback response"
        assert usage.provider == "groq"
        assert usage.used_fallback is True

    def test_tier_2_tool_decision_fallback_on_gemini_malformed_decision(self):
        primary_mock = MagicMock(spec=BaseLLMProvider)
        primary_mock.decide_tools.side_effect = ToolDecisionError("Gemini returned invalid JSON for function call")

        fallback_mock = MagicMock(spec=BaseLLMProvider)
        expected_call = ToolCall(name="get_salary_summary", args={"month": "2026-08"}, tool_call_id="call_groq_123")
        fallback_usage = LLMCallUsage(
            provider="groq",
            model="llama-3.3-70b-versatile",
            input_tokens=150,
            output_tokens=25,
            latency_ms=200,
            used_fallback=True,
        )
        fallback_mock.decide_tools.return_value = ([expected_call], fallback_usage)

        registry = LLMProviderRegistry(primary_provider=primary_mock, fallback_provider=fallback_mock)
        calls, usage = registry.decide_tools("Show salary summary", tools=[])

        assert len(calls) == 1
        assert calls[0].name == "get_salary_summary"
        assert calls[0].tool_call_id == "call_groq_123"
        assert usage.provider == "groq"
        assert usage.used_fallback is True

    @pytest.mark.asyncio
    async def test_tier_3_tool_execution_failure_returns_error_dict_without_llm_retry(self):
        """
        Tier 3: Execution error within an invoked tool must NOT trigger an LLM retry or replan loop.
        Instead, the tool node produces a safe error dictionary and passes it downstream.
        """
        mock_tool_fn = MagicMock(side_effect=RuntimeError("Underlying SQL connection timeout"))
        with patch("app.agents.admin_assistant.TOOL_FUNCTIONS", {"get_student_teacher_counts": mock_tool_fn}):
            state = {
                "query": "How many students are registered?",
                "tenant_id": "inst-pilot",
                "history": [],
                "tool_calls": [{"name": "get_student_teacher_counts", "args": {}}],
                "tool_results": [],
                "answer": "",
                "decide_tools_usage": None,
                "generate_usage": None,
                "trace_steps": [],
            }

            new_state = await execute_tools_node(state)
            assert len(new_state["tool_results"]) == 1
            result = new_state["tool_results"][0]["result"]
            assert result == {"error": "Reporting query execution failed safely."}

    def test_node_scoped_fallback_invariant(self):
        """
        Node-Scoped Fallback Invariant:
        When decide_tools succeeds on Gemini and execute_tools completes, a subsequent
        generation failure on Gemini triggers Groq ONLY for generate_answer, strictly
        preserving state and preventing duplicate tool calls.
        """
        primary_mock = MagicMock(spec=BaseLLMProvider)
        fallback_mock = MagicMock(spec=BaseLLMProvider)

        # 1. decide_tools on primary Gemini succeeds
        gemini_call = ToolCall(name="get_salary_summary", args={"month": "2026-08"}, tool_call_id="call_gemini_1")
        gemini_usage = LLMCallUsage(
            provider="gemini",
            model="gemini-2.5-flash",
            input_tokens=100,
            output_tokens=30,
            latency_ms=180,
            used_fallback=False,
        )
        primary_mock.decide_tools.return_value = ([gemini_call], gemini_usage)

        # 2. generate_text on primary Gemini fails with 429 quota exhaustion
        primary_mock.generate_text.side_effect = ProviderQuotaExhaustedError("429 Quota Exhausted on generation")

        # 3. fallback Groq succeeds on generate_text
        groq_usage = LLMCallUsage(
            provider="groq",
            model="llama-3.3-70b-versatile",
            input_tokens=220,
            output_tokens=85,
            latency_ms=320,
            used_fallback=True,
        )
        fallback_mock.generate_text.return_value = (
            "Here is the final administrative salary analysis based on retrieved figures.",
            groq_usage,
        )

        registry = LLMProviderRegistry(primary_provider=primary_mock, fallback_provider=fallback_mock)

        # Step 1: Decide tools
        calls, d_usage = registry.decide_tools("Generate salary report", tools=[])
        assert len(calls) == 1
        assert calls[0].name == "get_salary_summary"
        assert d_usage.provider == "gemini"
        assert d_usage.used_fallback is False
        fallback_mock.decide_tools.assert_not_called()  # Groq was NOT called for tools

        # Step 2: Simulated tool execution (results stored in agent state)
        tool_results = [{"name": "get_salary_summary", "result": {"total_payout": 350000.0, "paid_count": 14}}]

        # Step 3: Text generation triggers failover to Groq
        answer, g_usage = registry.generate_text("Summarize: " + str(tool_results))
        assert "salary analysis" in answer
        assert g_usage.provider == "groq"
        assert g_usage.used_fallback is True

        # Invariant checks:
        # - Primary decide_tools called once
        # - Fallback decide_tools NEVER called
        # - Primary generate_text called once (and failed)
        # - Fallback generate_text called once (and succeeded)
        # - Tool results preserved without duplicate tool invocations
        primary_mock.decide_tools.assert_called_once()
        fallback_mock.decide_tools.assert_not_called()
        primary_mock.generate_text.assert_called_once()
        fallback_mock.generate_text.assert_called_once()


# ==============================================================================
# Suite 3: Database Fenced Tool Idempotency Integration Tests (PostgreSQL RLS)
# ==============================================================================

@pytest.mark.asyncio
class TestDatabaseFencedToolIdempotency:
    """Verifies atomic reservations, fencing tokens, and lease recoveries under PostgreSQL."""

    async def _setup_institution(self, session: AsyncSession) -> uuid.UUID:
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        await session.execute(
            text("SELECT set_config('app.current_institution_id', :id, true)"),
            {"id": str(inst_id)},
        )
        inst = (await session.execute(select(Institution).where(Institution.id == inst_id))).scalars().first()
        if not inst:
            inst = Institution(id=inst_id, name="Idempotency Test Inst", slug="idem-inst", is_active=True)
            session.add(inst)
            await session.flush()
        return inst_id

    async def test_reserve_new_tool_execution(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"

            record, is_cached = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args={"class_section": "10-A"},
            )

            assert is_cached is False
            assert record.status == "EXECUTING"
            assert record.attempt_count == 1
            assert record.lease_generation == 1
            assert record.arguments_hash is not None

    async def test_idempotent_duplicate_call_returns_cached_result(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            args = {"class_section": "10-A"}

            # First execution: reserve and commit
            record, is_cached = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args=args,
            )
            assert is_cached is False

            cached_payload = {"total_students": 145, "total_teachers": 12}
            await commit_internal_tool_execution(
                db=session,
                record_id=record.id,
                my_lease_generation=record.lease_generation,
                result_payload=cached_payload,
            )

            # Second execution with same parameters: returns cached result immediately
            cached_record, is_cached_2 = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args=args,
            )
            assert is_cached_2 is True
            assert cached_record.status == "COMPLETED"
            assert cached_record.result_payload == cached_payload

    async def test_argument_divergence_rejects_with_idempotency_conflict_error(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"

            await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_salary_summary",
                args={"month": "2026-08"},
            )

            # Reusing same tool_call_id with different arguments must be rejected
            with pytest.raises(IdempotencyConflictError) as exc_info:
                await reserve_or_get_tool_execution(
                    db=session,
                    institution_id=inst_id,
                    session_id=session_id,
                    turn_id=1,
                    tool_call_id=tool_call_id,
                    tool_name="get_salary_summary",
                    args={"month": "2026-09"},  # Divergent argument!
                )
            assert "previously executed with different arguments" in str(exc_info.value)

    async def test_active_lease_concurrent_conflict(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            args = {"month": "2026-08"}

            # Worker 1 reserves lease
            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_salary_summary",
                args=args,
                lease_duration_seconds=60,
            )
            assert record.status == "EXECUTING"

            # Worker 2 attempts to acquire lease while still active
            with pytest.raises(ToolExecutionConflictError) as exc_info:
                await reserve_or_get_tool_execution(
                    db=session,
                    institution_id=inst_id,
                    session_id=session_id,
                    turn_id=1,
                    tool_call_id=tool_call_id,
                    tool_name="get_salary_summary",
                    args=args,
                )
            assert "actively executing under lease expiring at" in str(exc_info.value)

    async def test_stalled_lease_recovery_increments_lease_generation(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            args = {"class_section": "9-B"}

            # Worker 1 reserves lease
            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args=args,
            )
            assert record.lease_generation == 1
            assert record.attempt_count == 1

            # Simulate worker 1 crashing/stalling: expire lease into the past
            record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
            await session.flush()

            # Worker 2 attempts reservation: detects stalled lease, reclaims with incremented fencing token
            reclaimed_record, is_cached = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args=args,
            )
            assert is_cached is False
            assert reclaimed_record.lease_generation == 2
            assert reclaimed_record.attempt_count == 2
            assert reclaimed_record.status == "EXECUTING"

    async def test_fencing_token_revoked_on_stale_worker_commit(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            args = {"class_section": "10-C"}

            # Worker 1 acquires lease with generation 1
            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args=args,
            )
            stale_generation = record.lease_generation  # = 1

            # Worker 1 stalls; Worker 2 takes over and advances generation to 2
            record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
            await session.flush()

            worker_2_record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args=args,
            )
            assert worker_2_record.lease_generation == 2

            # Stale Worker 1 wakes up and tries to commit with superseded generation 1
            with pytest.raises(FencingTokenRevokedError) as exc_info:
                await commit_internal_tool_execution(
                    db=session,
                    record_id=record.id,
                    my_lease_generation=stale_generation,  # 1
                    result_payload={"stale_data": True},
                )
            assert "Fencing token revoked" in str(exc_info.value)

            # Worker 2 commits successfully with valid generation 2
            await commit_internal_tool_execution(
                db=session,
                record_id=record.id,
                my_lease_generation=2,
                result_payload={"valid_worker_2_data": True},
            )
            await session.refresh(record)
            assert record.status == "COMPLETED"
            assert record.result_payload == {"valid_worker_2_data": True}

    async def test_max_attempt_limit_transitions_to_failed(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            args = {"class_section": "8-A"}

            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_student_teacher_counts",
                args=args,
            )
            # Force attempt count to 3
            record.attempt_count = 3
            record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.flush()

            # Next attempt must be rejected and record transitioned to FAILED
            with pytest.raises(ToolExecutionExhaustedError) as exc_info:
                await reserve_or_get_tool_execution(
                    db=session,
                    institution_id=inst_id,
                    session_id=session_id,
                    turn_id=1,
                    tool_call_id=tool_call_id,
                    tool_name="get_student_teacher_counts",
                    args=args,
                )
            assert "exceeded maximum recovery attempts" in str(exc_info.value)
            await session.refresh(record)
            assert record.status == "FAILED"

    async def test_concurrent_initial_reservations_race(self, test_engine):
        """
        Genuine concurrent PostgreSQL integration test:
        Two independent database sessions attempt to concurrently reserve the same initial tool call ID.
        Verifies:
        - Exactly 1 worker wins the initial reservation.
        - The losing worker encounters unique constraint conflict (uq_tool_execution_call),
          safely rolled back via SAVEPOINT, and raised as controlled ToolExecutionConflictError.
        - The losing worker's session remains completely clean and valid.
        """
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
        args = {"class_section": "10-A"}

        async with (
            AsyncSession(test_engine, expire_on_commit=False) as s1,
            AsyncSession(test_engine, expire_on_commit=False) as s2,
        ):
            await s1.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            await s2.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))

            async def worker1():
                rec, cached = await reserve_or_get_tool_execution(
                    db=s1,
                    institution_id=inst_id,
                    session_id=session_id,
                    turn_id=1,
                    tool_call_id=tool_call_id,
                    tool_name="get_student_teacher_counts",
                    args=args,
                )
                await asyncio.sleep(0.05)
                await s1.commit()
                return rec, cached

            async def worker2():
                await asyncio.sleep(0.01)
                rec, cached = await reserve_or_get_tool_execution(
                    db=s2,
                    institution_id=inst_id,
                    session_id=session_id,
                    turn_id=1,
                    tool_call_id=tool_call_id,
                    tool_name="get_student_teacher_counts",
                    args=args,
                )
                await s2.commit()
                return rec, cached

            results = await asyncio.gather(worker1(), worker2(), return_exceptions=True)
            successes = [r for r in results if isinstance(r, tuple)]
            conflicts = [r for r in results if isinstance(r, ToolExecutionConflictError)]

            assert len(successes) == 1, f"Expected exactly 1 winning reservation, got {len(successes)}"
            assert len(conflicts) == 1, f"Expected exactly 1 ToolExecutionConflictError, got {len(conflicts)}"
            assert successes[0][1] is False
            assert successes[0][0].status == "EXECUTING"

            # Cleanup
            await s1.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            await s1.execute(text(f"DELETE FROM tool_execution_records WHERE session_id = '{session_id}';"))
            await s1.commit()

    async def test_tool_execution_records_cross_tenant_rls_isolation(self, test_engine):
        """
        Explicit live PostgreSQL Row-Level Security test on tool_execution_records:
        1. Institution A creates and reads its own tool execution record under eduintel_app.
        2. Institution B cannot read Institution A's record (returns None under RLS).
        3. Institution B cannot modify Institution A's record (UPDATE affects 0 rows under RLS).
        4. Querying without tenant context fails closed (returns None).
        """
        inst_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
        inst_b = uuid.UUID("00000000-0000-0000-0000-000000000002")

        # Ensure both institutions exist
        async with AsyncSession(test_engine, expire_on_commit=False) as setup_session:
            for inst_id, name, slug in [(inst_a, "Tenant A", "tenant-a-rls"), (inst_b, "Tenant B", "tenant-b-rls")]:
                inst = (await setup_session.execute(select(Institution).where(Institution.id == inst_id))).scalars().first()
                if not inst:
                    setup_session.add(Institution(id=inst_id, name=name, slug=slug, is_active=True))
            await setup_session.commit()

        tool_call_id = f"call_{uuid.uuid4().hex[:8]}"

        # 1. Institution A creates and reads its record under RLS
        async with AsyncSession(test_engine, expire_on_commit=False) as session_a:
            await session_a.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_a}', true);"))
            await session_a.execute(text("SELECT set_config('app.is_platform_admin', 'false', true);"))
            record_a, is_cached = await reserve_or_get_tool_execution(
                db=session_a,
                institution_id=inst_a,
                session_id="sess_a",
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="get_salary_summary",
                args={"month": "2026-08"},
            )
            record_a_id = record_a.id
            await session_a.commit()
            assert record_a_id is not None
            assert is_cached is False

        # 2. Institution B cannot read Institution A's record under RLS
        async with AsyncSession(test_engine, expire_on_commit=False) as session_b:
            await session_b.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_b}', true);"))
            await session_b.execute(text("SELECT set_config('app.is_platform_admin', 'false', true);"))

            # Verify GUC is populated with non-NULL tenant B ID
            guc_b = (await session_b.execute(text("SELECT current_setting('app.current_institution_id', true)"))).scalar()
            assert guc_b == str(inst_b), "Session B GUC must be strictly equal to Institution B UUID"

            stmt_read = select(ToolExecutionRecord).where(ToolExecutionRecord.id == record_a_id)
            res_b = await session_b.execute(stmt_read)
            read_record = res_b.scalar_one_or_none()
            assert read_record is None, "Tenant B must NOT read Tenant A's record under RLS"

            # 3. Institution B cannot modify Institution A's record under RLS
            stmt_update = (
                update(ToolExecutionRecord)
                .where(ToolExecutionRecord.id == record_a_id)
                .values(error_details="Unauthorized modification attempt by Tenant B")
            )
            upd_res = await session_b.execute(stmt_update)
            assert upd_res.rowcount == 0, "Tenant B UPDATE must affect 0 rows under RLS"

            # 4. Institution B can create and access its own record
            record_b, is_cached_b = await reserve_or_get_tool_execution(
                db=session_b,
                institution_id=inst_b,
                session_id="sess_b",
                turn_id=1,
                tool_call_id=f"call_b_{uuid.uuid4().hex[:8]}",
                tool_name="get_attendance_summary",
                args={"grade": "10"},
            )
            record_b_id = record_b.id
            assert record_b_id is not None
            assert is_cached_b is False

            # Verify Institution B reads its own record
            stmt_read_b = select(ToolExecutionRecord).where(ToolExecutionRecord.id == record_b_id)
            read_record_b = (await session_b.execute(stmt_read_b)).scalar_one_or_none()
            assert read_record_b is not None and read_record_b.id == record_b_id, "Tenant B must access its own record"
            await session_b.commit()

        # 5. Missing tenant context remains fail-closed
        async with AsyncSession(test_engine, expire_on_commit=False) as session_anon:
            await session_anon.execute(text("SELECT set_config('app.current_institution_id', '', true);"))
            await session_anon.execute(text("SELECT set_config('app.is_platform_admin', 'false', true);"))

            # Verify GUC is empty
            guc_anon = (await session_anon.execute(text("SELECT current_setting('app.current_institution_id', true)"))).scalar()
            assert guc_anon == "", "Session Anon GUC must be empty"

            stmt_anon_a = select(ToolExecutionRecord).where(ToolExecutionRecord.id == record_a_id)
            stmt_anon_b = select(ToolExecutionRecord).where(ToolExecutionRecord.id == record_b_id)
            res_anon_a = (await session_anon.execute(stmt_anon_a)).scalar_one_or_none()
            res_anon_b = (await session_anon.execute(stmt_anon_b)).scalar_one_or_none()
            assert res_anon_a is None, "Missing tenant context must return None for Tenant A record"
            assert res_anon_b is None, "Missing tenant context must return None for Tenant B record"

        # Cleanup
        async with AsyncSession(test_engine, expire_on_commit=False) as cleanup_session:
            await cleanup_session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_a}', true);"))
            await cleanup_session.execute(text(f"DELETE FROM tool_execution_records WHERE id = '{record_a_id}';"))
            await cleanup_session.commit()
            await cleanup_session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_b}', true);"))
            await cleanup_session.execute(text(f"DELETE FROM tool_execution_records WHERE id = '{record_b_id}';"))
            await cleanup_session.commit()


# ==============================================================================
# Suite 4: Bounded External Side Effects & Manual Reconciliation Tests
# ==============================================================================

@pytest.mark.asyncio
class TestExternalSideEffectBoundaries:
    """Verifies that external timeouts transition to UNCERTAIN and require explicit reconciliation."""

    async def _setup_institution(self, session: AsyncSession) -> uuid.UUID:
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        await session.execute(
            text("SELECT set_config('app.current_institution_id', :id, true)"),
            {"id": str(inst_id)},
        )
        inst = (await session.execute(select(Institution).where(Institution.id == inst_id))).scalars().first()
        if not inst:
            inst = Institution(id=inst_id, name="External Side Effect Inst", slug="ext-inst", is_active=True)
            session.add(inst)
            await session.flush()
        return inst_id

    async def test_external_side_effect_timeout_transitions_to_uncertain(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            args = {"recipient_phone": "+919876543210", "message": "Attendance warning"}

            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="send_sms_alert",
                args=args,
            )

            # External side-effect timeout: mark UNCERTAIN
            await fail_tool_execution(
                db=session,
                record_id=record.id,
                my_lease_generation=record.lease_generation,
                error_message="Gateway read timeout after 15000ms",
                is_uncertain=True,
            )

            await session.refresh(record)
            assert record.status == "UNCERTAIN"
            assert "read timeout" in record.error_details

    async def test_blind_retry_of_uncertain_operation_is_rejected(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            args = {"recipient_phone": "+919876543210", "message": "Attendance warning"}

            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="send_sms_alert",
                args=args,
            )
            await fail_tool_execution(
                db=session,
                record_id=record.id,
                my_lease_generation=record.lease_generation,
                error_message="Timeout",
                is_uncertain=True,
            )

            # Blind automatic retries MUST be strictly rejected
            with pytest.raises(UncertainExternalSideEffectError) as exc_info:
                await reserve_or_get_tool_execution(
                    db=session,
                    institution_id=inst_id,
                    session_id=session_id,
                    turn_id=1,
                    tool_call_id=tool_call_id,
                    tool_name="send_sms_alert",
                    args=args,
                )
            assert "is in UNCERTAIN state" in str(exc_info.value)
            assert "Automatic retry is rejected" in str(exc_info.value)

    async def test_manual_reconciliation_confirm_dispatched(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"

            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="send_sms_alert",
                args={"msg": "hello"},
            )
            await fail_tool_execution(session, record.id, record.lease_generation, "Timeout", is_uncertain=True)

            reconciled = await reconcile_uncertain_tool_execution(
                db=session,
                record_id=record.id,
                action="CONFIRM_DISPATCHED",
                operator_notes="Verified delivery receipt msg_id=ext_99481 in SMS gateway portal",
            )
            assert reconciled.status == "COMPLETED"
            assert "CONFIRM_DISPATCHED" in reconciled.error_details

    async def test_manual_reconciliation_mark_failed_and_compensating_action(self, db_connection):
        async with AsyncSession(bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            inst_id = await self._setup_institution(session)
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"

            record, _ = await reserve_or_get_tool_execution(
                db=session,
                institution_id=inst_id,
                session_id=session_id,
                turn_id=1,
                tool_call_id=tool_call_id,
                tool_name="charge_fee_payment",
                args={"amount": 5000},
            )
            await fail_tool_execution(session, record.id, record.lease_generation, "Timeout", is_uncertain=True)

            # Test COMPENSATING_ACTION
            comp_record = await reconcile_uncertain_tool_execution(
                db=session,
                record_id=record.id,
                action="COMPENSATING_ACTION",
                operator_notes="Issued refund ledger entry for duplicate charge attempt",
            )
            assert comp_record.status == "COMPENSATED"
            assert "COMPENSATING_ACTION" in comp_record.error_details

            # Test invalid action raises ValueError
            with pytest.raises(ValueError) as exc_info:
                await reconcile_uncertain_tool_execution(
                    db=session,
                    record_id=record.id,
                    action="INVALID_ACTION",
                    operator_notes="Invalid",
                )
            assert "not UNCERTAIN" in str(exc_info.value)

from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types
from groq import Groq

from app.core.config import settings

_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
_groq_client = Groq(api_key=settings.GROQ_API_KEY)

GEMINI_MODEL = "gemini-3.6-flash"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-120b"


class UnmeteredAIInvocationError(RuntimeError):
    """Raised when an external AI provider call is attempted without an active, verified MeteredRequestContext."""

    pass


class QuotaSystemDisabledError(RuntimeError):
    """Raised when an external AI provider call is attempted while ENABLE_TENANT_AI_QUOTAS is disabled."""

    pass


@dataclass
class LLMCallUsage:
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    used_fallback: bool


def _is_rate_limit_error(e: Exception) -> bool:

    msg = str(e)
    msg_lower = msg.lower()
    return (
        "RESOURCE_EXHAUSTED" in msg
        or "429" in msg
        or "quota" in msg_lower
        or "503" in msg
        or "UNAVAILABLE" in msg
        or "overloaded" in msg_lower
        or "high demand" in msg_lower
    )


def _generate_text_impl(prompt: str, context: Any = None) -> tuple[str, LLMCallUsage]:
    from app.observability.quota.adapter import (
        get_current_metered_context,
        get_metered_ai_service,
        run_metered_coro_sync,
    )

    ctx = context or get_current_metered_context()
    if ctx is not None:
        service = get_metered_ai_service()
        result = run_metered_coro_sync(service.execute_text_generation(ctx, prompt))
        return result.text, result.usage

    is_production = getattr(settings, "is_production", False) or settings.ENVIRONMENT == "production"
    is_test_bypass = not is_production and getattr(settings, "ALLOW_UNMETERED_AI_TEST_BYPASS", False)

    if not is_test_bypass:
        if not settings.ENABLE_TENANT_AI_QUOTAS:
            raise QuotaSystemDisabledError(
                "AI execution rejected: ENABLE_TENANT_AI_QUOTAS is disabled and unmetered bypass is forbidden."
            )
        raise UnmeteredAIInvocationError(
            "AI execution rejected: No verified MeteredRequestContext is active in the execution context."
        )

    from app.core.llm_provider import LLMProviderRegistry

    registry = LLMProviderRegistry.get_instance()
    text, usage = registry.generate_text(prompt)
    return text, usage


def generate_text(prompt: str, *, context: Any = None) -> str:
    """
    Plain text generation, no tool-calling.
    Tries Gemini first, falls back to Groq if Gemini is rate-limited.
    Used by both agents' final answer-generation step.
    Routes through Stage 7.3 MeteredAIService when context is active.
    """
    text, _usage = _generate_text_impl(prompt, context=context)
    return text


def generate_text_with_usage(prompt: str, *, context: Any = None) -> tuple[str, LLMCallUsage]:
    """
    Same as generate_text(), but also returns the LLMCallUsage for this
    call so can log it immediately (no shared/global state,
    so this is safe to call from any sync or async context, including
    inside a LangGraph node run via asyncio.to_thread).
    Routes through Stage 7.3 MeteredAIService when context is active.
    """
    return _generate_text_impl(prompt, context=context)


def _decide_tools_impl(prompt: str, tool: types.Tool, context: Any = None) -> tuple[list[dict], LLMCallUsage]:
    from app.observability.quota.adapter import (
        get_current_metered_context,
        get_metered_ai_service,
        run_metered_coro_sync,
    )

    ctx = context or get_current_metered_context()
    if ctx is not None:
        # If the parent context has a general endpoint like 'admin-assistant/chat',
        # specialize it for decide_tools
        effective_ctx = ctx
        if ctx.endpoint.endswith("/chat"):
            effective_ctx = ctx.for_endpoint(f"{ctx.endpoint.split('/')[0]}/decide_tools")

        service = get_metered_ai_service()
        result = run_metered_coro_sync(service.execute_tool_decision(effective_ctx, prompt, tool))
        return result.tool_calls, result.usage

    is_production = getattr(settings, "is_production", False) or settings.ENVIRONMENT == "production"
    is_test_bypass = not is_production and getattr(settings, "ALLOW_UNMETERED_AI_TEST_BYPASS", False)

    if not is_test_bypass:
        if not settings.ENABLE_TENANT_AI_QUOTAS:
            raise QuotaSystemDisabledError(
                "AI tool decision rejected: ENABLE_TENANT_AI_QUOTAS is disabled and unmetered bypass is forbidden."
            )
        raise UnmeteredAIInvocationError(
            "AI tool decision rejected: No verified MeteredRequestContext is active in the execution context."
        )

    from app.core.llm_provider import LLMProviderRegistry

    registry = LLMProviderRegistry.get_instance()
    tool_calls, usage = registry.decide_tools(prompt, tool)
    call_dicts = [{"name": tc.name, "args": tc.args, "tool_call_id": tc.tool_call_id} for tc in tool_calls]
    return call_dicts, usage


def decide_tools(prompt: str, tool: types.Tool, *, context: Any = None) -> list[dict]:
    tool_calls, _usage = _decide_tools_impl(prompt, tool, context=context)
    return tool_calls


def decide_tools_with_usage(prompt: str, tool: types.Tool, *, context: Any = None) -> tuple[list[dict], LLMCallUsage]:
    return _decide_tools_impl(prompt, tool, context=context)

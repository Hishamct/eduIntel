import time
from dataclasses import dataclass

from google import genai
from google.genai import types
from groq import Groq

from app.core.config import settings

_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
_groq_client = Groq(api_key=settings.GROQ_API_KEY)

GEMINI_MODEL = "gemini-3.6-flash"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-120b"


@dataclass
class LLMCallUsage:
    """
    Latency + token usage for one generate_text()/decide_tools() call.
    Cost estimation is deliberately NOT done here — see
    app/observability/service.py's estimate_cost_inr, which turns this into
    ₹ using pricing constants kept separate from this client, so a pricing
    change never touches the actual LLM-calling code.
    """

    provider: str  # "gemini" or "groq"
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    used_fallback: bool


def _is_rate_limit_error(e: Exception) -> bool:
    """
    Gemini raises different exception types depending on SDK version
    (google.genai.errors.ClientError / APIError are common). Checking the
    message text instead of a specific exception class keeps this working
    even if the exact error type differs in your installed SDK version.

    Covers both quota exhaustion (429/RESOURCE_EXHAUSTED) and transient
    server-side unavailability (503/UNAVAILABLE, "overloaded"/"high demand")
    — either way, we want to fall back to Groq rather than crash the request.
    """
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


def _generate_text_impl(prompt: str) -> tuple[str, LLMCallUsage]:
    start = time.monotonic()
    try:
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        usage = getattr(response, "usage_metadata", None)
        return response.text, LLMCallUsage(
            provider="gemini",
            model=GEMINI_MODEL,
            input_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            output_tokens=getattr(usage, "candidates_token_count", None)
            if usage
            else None,
            latency_ms=latency_ms,
            used_fallback=False,
        )
    except Exception as e:
        if not _is_rate_limit_error(e):
            raise
        fallback_start = time.monotonic()
        groq_response = _groq_client.chat.completions.create(
            model=GROQ_FALLBACK_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.monotonic() - fallback_start) * 1000)
        usage = getattr(groq_response, "usage", None)
        return groq_response.choices[0].message.content, LLMCallUsage(
            provider="groq",
            model=GROQ_FALLBACK_MODEL,
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            latency_ms=latency_ms,
            used_fallback=True,
        )


def generate_text(prompt: str) -> str:
    """
    Plain text generation, no tool-calling.
    Tries Gemini first, falls back to Groq if Gemini is rate-limited.
    Used by both agents' final answer-generation step.

    Unchanged signature/behavior — existing callers keep working exactly
    as before. Use generate_text_with_usage() instead at any call site that
    wants to log cost/latency (see app/observability/service.py:
    log_llm_usage). Two entry points over one shared implementation rather
    than a shared mutable "last usage" slot — an earlier draft tried a
    contextvar for that and it silently failed to propagate out of the
    worker thread LangGraph runs sync nodes in (asyncio.to_thread copies
    context IN, but writes inside that copy never propagate back out) —
    this version has no shared state to get out of sync.
    """
    text, _usage = _generate_text_impl(prompt)
    return text


def generate_text_with_usage(prompt: str) -> tuple[str, LLMCallUsage]:
    """
    Same as generate_text(), but also returns the LLMCallUsage for this
    call so the caller can log it immediately (no shared/global state,
    so this is safe to call from any sync or async context, including
    inside a LangGraph node run via asyncio.to_thread).
    """
    return _generate_text_impl(prompt)


def _decide_tools_impl(
    prompt: str, tool: types.Tool
) -> tuple[list[dict], LLMCallUsage]:
    start = time.monotonic()
    try:
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[tool]),
        )
    except Exception as e:
        if not _is_rate_limit_error(e):
            raise
        latency_ms = int((time.monotonic() - start) * 1000)
        usage = LLMCallUsage(
            provider="gemini",
            model=GEMINI_MODEL,
            input_tokens=None,
            output_tokens=None,
            latency_ms=latency_ms,
            used_fallback=False,
        )
        return (
            [],
            usage,
        )  # degrade gracefully — generate_node still answers, without tool data

    latency_ms = int((time.monotonic() - start) * 1000)
    usage_meta = getattr(response, "usage_metadata", None)
    usage = LLMCallUsage(
        provider="gemini",
        model=GEMINI_MODEL,
        input_tokens=getattr(usage_meta, "prompt_token_count", None)
        if usage_meta
        else None,
        output_tokens=getattr(usage_meta, "candidates_token_count", None)
        if usage_meta
        else None,
        latency_ms=latency_ms,
        used_fallback=False,
    )

    tool_calls = []
    candidate = response.candidates[0]
    for part in candidate.content.parts:
        if part.function_call:
            tool_calls.append(
                {
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args)
                    if part.function_call.args
                    else {},
                }
            )
    return tool_calls, usage


def decide_tools(prompt: str, tool: types.Tool) -> list[dict]:
    """
    Tool-calling decision step (Admin Assistant only). Gemini-only —
    if Gemini is rate-limited here, we degrade gracefully to "no tools"
    rather than replicating function-calling on Groq (different schema),
    so the assistant still answers, just without live data for that turn.

    Unchanged signature/behavior. Use decide_tools_with_usage() to also get
    latency/token info — same reasoning as generate_text_with_usage above.
    """
    tool_calls, _usage = _decide_tools_impl(prompt, tool)
    return tool_calls


def decide_tools_with_usage(
    prompt: str, tool: types.Tool
) -> tuple[list[dict], LLMCallUsage]:
    """Same as decide_tools(), but also returns the LLMCallUsage for this call."""
    return _decide_tools_impl(prompt, tool)

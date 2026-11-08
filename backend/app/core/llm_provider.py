"""
backend/app/core/llm_provider.py

Phase 5 Step 1: AI Provider Architecture, Data Governance & Tool Fallbacks.
- BaseLLMProvider: Abstract base class for AI model providers.
- GeminiProvider: Google GenAI client with exponential backoff on transient errors (503)
  and immediate failover on HTTP 429 quota exhaustion.
- GroqProvider: Groq fallback client with bidirectional schema mapping (Gemini FunctionDeclaration
  <-> OpenAI tools schema).
- LLMProviderRegistry: Manages primary/fallback routing, PII sanitization/minimization,
  and three-tier failure handling (Provider, Tool Decision, Tool Execution).
- Node-Scoped Fallback Invariant: When decide_tools succeeds on Gemini but generation fails,
  fallback to Groq executes for generate_answer ONLY, preventing duplicate tool execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types
from groq import Groq

from app.core.config import settings

logger = logging.getLogger(__name__)

# --- PII Minimization Patterns ---
AADHAAR_REGEX = re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")
PHONE_REGEX = re.compile(r"\b(?:\+?91[-.\s]?)?[6-9]\d{9}\b")
BEARER_TOKEN_REGEX = re.compile(r"\bBearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*\b", re.IGNORECASE)
EMAIL_PATTERN_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


def sanitize_prompt_for_provider(prompt: str) -> str:
    """
    Minimizes and sanitizes sensitive student PII before transmission to third-party LLMs.
    - Strips Aadhaar numbers, phone numbers, and bearer credentials.
    - Tokenizes emails to protect student contact privacy.
    """
    if not prompt:
        return ""

    sanitized = AADHAAR_REGEX.sub("[AADHAAR_REDACTED]", prompt)
    sanitized = PHONE_REGEX.sub("[PHONE_REDACTED]", sanitized)
    sanitized = BEARER_TOKEN_REGEX.sub("[AUTH_TOKEN_REDACTED]", sanitized)

    # Deterministically tokenize emails: test@example.com -> student_user_[hash]@domain
    def _redact_email(match: re.Match) -> str:
        em = match.group(0)
        h = hashlib.sha256(em.encode("utf-8")).hexdigest()[:8]
        domain = em.split("@")[-1]
        return f"user_{h}@{domain}"

    sanitized = EMAIL_PATTERN_REGEX.sub(_redact_email, sanitized)
    return sanitized


# --- Provider Exceptions ---
class LLMProviderError(Exception):
    """Base exception for LLM provider operations."""


class ProviderTransientError(LLMProviderError):
    """Transient error (503, connection timeout, network drop) eligible for backoff retry."""


class ProviderQuotaExhaustedError(LLMProviderError):
    """HTTP 429 or quota exhaustion; must trigger immediate provider fallback without retry."""


class ToolDecisionError(LLMProviderError):
    """Malformed tool call, invalid JSON arguments, or schema generation failure (Tier 2)."""


class ToolExecutionError(LLMProviderError):
    """Execution error within an invoked tool (Tier 3; must NOT retry LLM provider)."""


# --- Core Data Structures ---
@dataclass
class LLMConfig:
    temperature: float = 0.2
    max_output_tokens: int = 2048
    timeout_seconds: int = 25
    model_override: str | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    tool_call_id: str


@dataclass
class LLMCallUsage:
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    used_fallback: bool


def is_rate_limit_error(e: Exception) -> bool:
    """Detects whether an exception represents quota exhaustion or rate limits."""
    msg = str(e).lower()
    return (
        "resource_exhausted" in msg
        or "429" in msg
        or "quota" in msg
        or "rate limit" in msg
        or "tokens per minute" in msg
    )


def is_transient_error(e: Exception) -> bool:
    """Detects transient network, unavailable, or 503 errors eligible for backoff retry."""
    msg = str(e).lower()
    return (
        "503" in msg
        or "unavailable" in msg
        or "overloaded" in msg
        or "high demand" in msg
        or "connection reset" in msg
        or "timed out" in msg
        or "deadline exceeded" in msg
    )


# --- Bidirectional Tool Schema Mapping ---
def _normalize_json_schema(schema: Any) -> Any:
    """
    Recursively normalizes a JSON Schema data structure for Groq/OpenAI tool calling compatibility:
    - Normalizes uppercase Google GenAI types (e.g., 'STRING' -> 'string', 'OBJECT' -> 'object', 'INTEGER' -> 'integer', 'ARRAY' -> 'array', 'BOOLEAN' -> 'boolean', 'NUMBER' -> 'number').
    - Preserves nested properties, required fields, descriptions, items (arrays), enums, and optional fields.
    - Strips None values.
    """
    if isinstance(schema, dict):
        normalized = {}
        for k, v in schema.items():
            if v is None:
                continue
            if k == "type":
                if isinstance(v, str):
                    normalized[k] = v.lower()
                elif isinstance(v, list):
                    normalized[k] = [item.lower() if isinstance(item, str) else item for item in v]
                else:
                    normalized[k] = v
            else:
                normalized[k] = _normalize_json_schema(v)
        return normalized
    elif isinstance(schema, list):
        return [_normalize_json_schema(item) for item in schema]
    return schema


def convert_gemini_tools_to_groq_format(tools_input: Any) -> list[dict]:
    """
    Translates Google GenAI types.Tool / FunctionDeclaration objects or dictionary definitions
    into standard OpenAI/Groq tool format (JSON schema).
    """
    if not tools_input:
        return []

    # If already a list of OpenAI-formatted tool dicts
    if isinstance(tools_input, list) and tools_input and isinstance(tools_input[0], dict) and "function" in tools_input[0]:
        return tools_input

    groq_tools = []
    # If wrapped in types.Tool
    declarations = getattr(tools_input, "function_declarations", None)
    if declarations is None:
        if isinstance(tools_input, list):
            declarations = tools_input
        else:
            declarations = [tools_input]

    for decl in declarations:
        name = getattr(decl, "name", None) or (decl.get("name") if isinstance(decl, dict) else None)
        description = getattr(decl, "description", None) or (decl.get("description") if isinstance(decl, dict) else "")
        parameters = getattr(decl, "parameters", None) or (decl.get("parameters") if isinstance(decl, dict) else {})

        # Extract parameter dictionary supporting Google GenAI types.Schema, Pydantic models, or raw dicts
        param_dict = None
        if hasattr(parameters, "to_json_dict"):
            try:
                param_dict = parameters.to_json_dict()
            except Exception:
                param_dict = None
        if param_dict is None and hasattr(parameters, "model_dump"):
            try:
                param_dict = parameters.model_dump(exclude_none=True)
            except Exception:
                param_dict = None
        if param_dict is None and hasattr(parameters, "dict"):
            try:
                param_dict = parameters.dict(exclude_none=True)
            except Exception:
                param_dict = None
        if param_dict is None and hasattr(parameters, "to_dict"):
            try:
                param_dict = parameters.to_dict()
            except Exception:
                param_dict = None
        if param_dict is None and isinstance(parameters, dict):
            param_dict = parameters

        cleaned_params = _normalize_json_schema(param_dict) if param_dict else {"type": "object", "properties": {}}
        if not isinstance(cleaned_params, dict) or "type" not in cleaned_params:
            cleaned_params = {"type": "object", "properties": {}}

        groq_tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": cleaned_params,
            },
        })
    return groq_tools


# --- Provider Base Class ---
class BaseLLMProvider(ABC):
    """Abstract interface defining required LLM capabilities."""

    @abstractmethod
    def generate_text(self, prompt: str, config: LLMConfig | None = None) -> tuple[str, LLMCallUsage]:
        """Generates plain text response."""

    @abstractmethod
    def decide_tools(self, prompt: str, tools: Any, config: LLMConfig | None = None) -> tuple[list[ToolCall], LLMCallUsage]:
        """Performs function calling and outputs structured ToolCall list."""


# --- Gemini Provider Implementation ---
class GeminiProvider(BaseLLMProvider):
    """Google Gemini GenAI Provider with transient retry backoff and rate-limit classification."""

    def __init__(self, client: genai.Client | None = None, model: str | None = None):
        self._client = client
        self._model = model

    @property
    def client(self) -> genai.Client:
        if self._client is not None:
            return self._client
        try:
            import app.core.llm_client as lc
            return getattr(lc, "_gemini_client", None) or genai.Client(api_key=settings.GEMINI_API_KEY)
        except ImportError:
            return genai.Client(api_key=settings.GEMINI_API_KEY)

    @property
    def model(self) -> str:
        if self._model is not None:
            return self._model
        try:
            import app.core.llm_client as lc
            return getattr(lc, "GEMINI_MODEL", settings.GEMINI_MODEL)
        except ImportError:
            return settings.GEMINI_MODEL

    def _execute_with_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        max_retries = settings.LLM_MAX_RETRIES
        backoff_factor = settings.LLM_RETRY_BACKOFF_FACTOR
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                # HTTP 429 / Quota exhaustion: fail fast immediately for fallback
                if is_rate_limit_error(e):
                    logger.warning("[GeminiProvider] Quota exhausted (429). Triggering immediate fallback: %s", e)
                    raise ProviderQuotaExhaustedError(f"Gemini quota exhausted: {e}") from e

                # Transient 503 / Network errors: retry with backoff
                if is_transient_error(e) and attempt < max_retries:
                    sleep_time = backoff_factor ** attempt
                    logger.warning(
                        "[GeminiProvider] Transient error on attempt %d/%d. Retrying in %.2fs: %s",
                        attempt + 1,
                        max_retries,
                        sleep_time,
                        e,
                    )
                    time.sleep(sleep_time)
                    continue

                # Non-transient or exhausted retries
                if is_transient_error(e):
                    raise ProviderTransientError(f"Gemini transient error after {max_retries} retries: {e}") from e
                raise

        raise last_error  # pragma: no cover

    def generate_text(self, prompt: str, config: LLMConfig | None = None) -> tuple[str, LLMCallUsage]:
        cfg = config or LLMConfig()
        model_name = cfg.model_override or self.model
        start = time.monotonic()

        def _call():
            return self.client.models.generate_content(
                model=model_name,
                contents=prompt,
            )

        response = self._execute_with_retry(_call)
        latency_ms = int((time.monotonic() - start) * 1000)
        usage_meta = getattr(response, "usage_metadata", None)

        usage = LLMCallUsage(
            provider="gemini",
            model=model_name,
            input_tokens=getattr(usage_meta, "prompt_token_count", None) if usage_meta else None,
            output_tokens=getattr(usage_meta, "candidates_token_count", None) if usage_meta else None,
            latency_ms=latency_ms,
            used_fallback=False,
        )
        return response.text or "", usage

    def decide_tools(self, prompt: str, tools: Any, config: LLMConfig | None = None) -> tuple[list[ToolCall], LLMCallUsage]:
        cfg = config or LLMConfig()
        model_name = cfg.model_override or self.model
        start = time.monotonic()

        # Wrap in types.Tool if not already
        if isinstance(tools, types.Tool):
            gemini_tools = [tools]
        elif isinstance(tools, list) and tools and isinstance(tools[0], types.Tool):
            gemini_tools = tools
        elif isinstance(tools, list):
            gemini_tools = [types.Tool(function_declarations=tools)]
        else:
            gemini_tools = [types.Tool(function_declarations=[tools])]

        def _call():
            return self.client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(tools=gemini_tools),
            )

        try:
            response = self._execute_with_retry(_call)
        except (ProviderQuotaExhaustedError, ProviderTransientError):
            raise
        except Exception as e:
            raise ToolDecisionError(f"Gemini failed to generate tool call decision: {e}") from e

        latency_ms = int((time.monotonic() - start) * 1000)
        usage_meta = getattr(response, "usage_metadata", None)
        usage = LLMCallUsage(
            provider="gemini",
            model=model_name,
            input_tokens=getattr(usage_meta, "prompt_token_count", None) if usage_meta else None,
            output_tokens=getattr(usage_meta, "candidates_token_count", None) if usage_meta else None,
            latency_ms=latency_ms,
            used_fallback=False,
        )

        tool_calls: list[ToolCall] = []
        try:
            candidates = getattr(response, "candidates", [])
            if candidates and candidates[0].content and candidates[0].content.parts:
                for part in candidates[0].content.parts:
                    if getattr(part, "function_call", None):
                        fc = part.function_call
                        call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:10]}"
                        args = dict(fc.args) if fc.args else {}
                        tool_calls.append(ToolCall(name=fc.name, args=args, tool_call_id=call_id))
        except Exception as e:
            raise ToolDecisionError(f"Malformed function call output from Gemini: {e}") from e

        return tool_calls, usage


# --- Groq Provider Implementation ---
class GroqProvider(BaseLLMProvider):
    """Groq Provider used for fast, deterministic fallback on rate limit or tool decision failure."""

    def __init__(self, client: Groq | None = None, model: str | None = None):
        self._client = client
        self._model = model

    @property
    def client(self) -> Groq:
        if self._client is not None:
            return self._client
        try:
            import app.core.llm_client as lc
            return getattr(lc, "_groq_client", None) or Groq(api_key=settings.GROQ_API_KEY)
        except ImportError:
            return Groq(api_key=settings.GROQ_API_KEY)

    @property
    def model(self) -> str:
        if self._model is not None:
            return self._model
        try:
            import app.core.llm_client as lc
            return getattr(lc, "GROQ_FALLBACK_MODEL", settings.GROQ_FALLBACK_MODEL)
        except ImportError:
            return settings.GROQ_FALLBACK_MODEL

    def generate_text(self, prompt: str, config: LLMConfig | None = None) -> tuple[str, LLMCallUsage]:
        cfg = config or LLMConfig()
        model_name = cfg.model_override or self.model
        start = time.monotonic()

        response = self.client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=cfg.temperature,
            max_tokens=cfg.max_output_tokens,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        usage_data = getattr(response, "usage", None)

        usage = LLMCallUsage(
            provider="groq",
            model=model_name,
            input_tokens=getattr(usage_data, "prompt_tokens", None) if usage_data else None,
            output_tokens=getattr(usage_data, "completion_tokens", None) if usage_data else None,
            latency_ms=latency_ms,
            used_fallback=True,
        )
        content = response.choices[0].message.content or ""
        return content, usage

    def decide_tools(self, prompt: str, tools: Any, config: LLMConfig | None = None) -> tuple[list[ToolCall], LLMCallUsage]:
        cfg = config or LLMConfig()
        model_name = cfg.model_override or self.model
        start = time.monotonic()

        groq_tools = convert_gemini_tools_to_groq_format(tools)
        try:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                tools=groq_tools if groq_tools else None,
                tool_choice="auto" if groq_tools else None,
                temperature=cfg.temperature,
            )
        except Exception as e:
            raise ToolDecisionError(f"Groq tool decision failed: {e}") from e

        latency_ms = int((time.monotonic() - start) * 1000)
        usage_data = getattr(response, "usage", None)
        usage = LLMCallUsage(
            provider="groq",
            model=model_name,
            input_tokens=getattr(usage_data, "prompt_tokens", None) if usage_data else None,
            output_tokens=getattr(usage_data, "completion_tokens", None) if usage_data else None,
            latency_ms=latency_ms,
            used_fallback=True,
        )

        tool_calls: list[ToolCall] = []
        message = response.choices[0].message
        raw_tool_calls = getattr(message, "tool_calls", None)

        if raw_tool_calls:
            for tc in raw_tool_calls:
                fn_name = tc.function.name
                call_id = tc.id or f"call_{uuid.uuid4().hex[:10]}"
                try:
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else dict(tc.function.arguments)
                except Exception as json_err:
                    raise ToolDecisionError(f"Failed to parse Groq tool call arguments as JSON: {json_err}") from json_err

                tool_calls.append(ToolCall(name=fn_name, args=args, tool_call_id=call_id))

        return tool_calls, usage


# --- Centralized Provider Registry ---
class LLMProviderRegistry:
    """
    Central registry governing provider lifecycle, PII minimization, and three-tier failure recovery.
    Enforces Node-Scoped Fallback: if Gemini succeeds at decide_tools but fails at generate_answer,
    Groq executes ONLY for generate_answer, strictly preserving state and preventing duplicate tool calls.
    """

    _instance: LLMProviderRegistry | None = None

    def __init__(
        self,
        primary_provider: BaseLLMProvider | None = None,
        fallback_provider: BaseLLMProvider | None = None,
    ):
        self.primary = primary_provider or GeminiProvider()
        self.fallback = fallback_provider or GroqProvider()

    @classmethod
    def get_instance(cls) -> LLMProviderRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def set_instance(cls, registry: LLMProviderRegistry) -> None:
        cls._instance = registry

    def generate_text(self, prompt: str, config: LLMConfig | None = None) -> tuple[str, LLMCallUsage]:
        """
        Executes text generation with automatic failover to Groq upon primary quota exhaustion or transient failure.
        Enforces prompt PII minimization prior to dispatch and post-generation output guardrail validation
        (PII masking and metaprompt exfiltration blocking) across both primary Gemini and fallback Groq.
        """
        sanitized_prompt = sanitize_prompt_for_provider(prompt)

        try:
            raw_text, usage = self.primary.generate_text(sanitized_prompt, config)
        except (ProviderQuotaExhaustedError, ProviderTransientError) as e:
            logger.warning("[LLMProviderRegistry] Primary provider failed (%s). Triggering fallback to Groq.", e)
            raw_text, usage = self.fallback.generate_text(sanitized_prompt, config)

        from app.guardrails.engine import default_guardrails_engine

        out_eval = default_guardrails_engine.evaluate_output(raw_text)
        if out_eval.blocked:
            logger.critical("Metaprompt leakage blocked in LLMProviderRegistry: %s", out_eval.block_reason)
            return "Security violation: response blocked due to confidential system prompt leakage.", usage

        return out_eval.sanitized_text, usage

    def decide_tools(self, prompt: str, tools: Any, config: LLMConfig | None = None) -> tuple[list[ToolCall], LLMCallUsage]:
        """
        Executes tool calling decision.
        - Tier 1 (Provider failure / 429) -> Immediate fallback to Groq.
        - Tier 2 (Tool decision failure / malformed output) -> Delegates tool decision to Groq.
        - Tier 3 (Tool execution failure) -> NOT handled here; caller returns error dict without re-invoking LLM.
        """
        sanitized_prompt = sanitize_prompt_for_provider(prompt)

        try:
            return self.primary.decide_tools(sanitized_prompt, tools, config)
        except (ProviderQuotaExhaustedError, ProviderTransientError, ToolDecisionError) as e:
            logger.warning("[LLMProviderRegistry] Primary decide_tools failed (%s). Delegating decision to Groq fallback.", e)
            return self.fallback.decide_tools(sanitized_prompt, tools, config)

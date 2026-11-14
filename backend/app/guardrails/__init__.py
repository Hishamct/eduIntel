"""
backend/app/guardrails package.
"""

from app.guardrails.anti_cheating import (
    PolicyMode,
    build_socratic_instruction,
    check_for_cheating_intent,
    evaluate_institutional_policy,
)
from app.guardrails.engine import (
    GuardrailOutputResult,
    GuardrailResult,
    GuardrailsEngine,
    default_guardrails_engine,
)
from app.guardrails.pii_redaction import redact_pii
from app.guardrails.prompt_injection import (
    INJECTION_REFUSAL_MESSAGE,
    check_for_prompt_injection,
    check_for_prompt_injection_safe,
)
from app.guardrails.redos_guard import (
    SafeRegexResult,
    safe_regex_match_any,
    safe_regex_search,
    validate_patterns_at_startup,
)
from app.guardrails.streaming_buffer import (
    ConcurrentStreamLimitExceededError,
    InstitutionalStreamManager,
    StreamingValidationBuffer,
    StreamTerminalState,
    format_sse_done,
    format_sse_error,
    format_sse_security_violation,
    format_sse_token,
    format_sse_truncated,
    institutional_stream_manager,
)

__all__ = [
    "ConcurrentStreamLimitExceededError",
    "GuardrailOutputResult",
    "GuardrailResult",
    "GuardrailsEngine",
    "INJECTION_REFUSAL_MESSAGE",
    "InstitutionalStreamManager",
    "PolicyMode",
    "SafeRegexResult",
    "StreamTerminalState",
    "StreamingValidationBuffer",
    "build_socratic_instruction",
    "check_for_cheating_intent",
    "check_for_prompt_injection",
    "check_for_prompt_injection_safe",
    "default_guardrails_engine",
    "evaluate_institutional_policy",
    "format_sse_done",
    "format_sse_error",
    "format_sse_security_violation",
    "format_sse_token",
    "format_sse_truncated",
    "institutional_stream_manager",
    "redact_pii",
    "safe_regex_match_any",
    "safe_regex_search",
    "validate_patterns_at_startup",
]


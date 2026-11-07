"""
backend/app/guardrails/prompt_injection.py

Prompt-injection and jailbreak defense for EduIntel AI.
Scans user-supplied text for attempts to override system instructions,
hijack persona, extract confidential system prompts, or bypass safety guardrails.

Hardened with ReDoS protection and supervised subprocess isolation.
"""

import re

from app.guardrails.redos_guard import safe_regex_match_any

INJECTION_REFUSAL_MESSAGE = (
    "I can't process that message — it looks like it's trying to change how "
    "I'm instructed to behave rather than asking a genuine question. If you "
    "have a real question about the platform or your studies, please ask "
    "that directly."
)

# Comprehensive catalog of known injection, jailbreak, and prompt-extraction vectors
_INJECTION_PATTERNS = [
    # 1. Instruction override attempts
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|directives|rules|prompts)",
    r"disregard (the |all )?(system prompt|instructions|directives|rules)",
    r"forget (everything|what|all) (you('ve| have)? been told|i said|your instructions)",
    r"new instructions?\s*:",
    r"override (your |the )?(system prompt|instructions|rules)",
    r"stop being a tutor",
    r"abandon (your |all )?(instructions|rules|guidelines)",
    # 2. Role / persona hijacking
    r"you are now\s+\w+",
    r"act as (an?|the)\s+\w+",
    r"pretend (you('re| are)|to be)\s+\w+",
    r"from now on,? you (are|will|must)",
    r"enter (developer|debug|jailbreak|dan|unrestricted) mode",
    r"\bdan mode\b",
    r"developer mode enabled",
    # 3. System prompt extraction
    r"(reveal|show|print|output|repeat) (your |the )?(system )?prompt",
    r"what (is|are) your (system )?(prompt|instructions|rules)",
    r"repeat (the words|everything) above",
    r"print everything starting from",
    r"output your initial instructions",
    # 4. Explicit jailbreak / bypass language
    r"\bjailbreak\b",
    r"without (any )?(restrictions|limitations|filters|guidelines)",
    r"bypass (your |the )?(restrictions|filters|guidelines|safety)",
    r"no longer (bound|restricted|limited) by",
    r"hypothetical scenario where rules don't apply",
    r"for educational and research purposes only, ignore all safety",
    # 5. Delimiter & Framing Injection
    r"(?:---|===|\*\*\*)\s*(?:BEGIN|START)\s*(?:SYSTEM|ADMIN|PROMPT)",
    r"<\s*\|\s*(?:im_start|system|prompt)\s*\|?\s*>",
    r"\[\s*(?:SYSTEM|INSTRUCTION|ADMIN)\s*\]",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]
PROMPT_INJECTION_PATTERNS = _INJECTION_PATTERNS


def check_for_prompt_injection(
    text: str,
    timeout_seconds: float = 0.150,
) -> tuple[bool, str | None]:
    """
    Scans user-supplied text for known prompt-injection / jailbreak patterns.
    Protected against ReDoS via safe DFA / supervised subprocess execution.

    Returns:
        (is_flagged, matched_pattern_description)
    """
    if not text or not text.strip():
        return False, None

    result = safe_regex_match_any(
        patterns=_INJECTION_PATTERNS,
        text=text,
        timeout_seconds=timeout_seconds,
        flags=re.IGNORECASE,
    )

    if result.timed_out:
        # Fail closed on ReDoS timeout
        return True, "GUARDRAIL_TIMEOUT"

    if result.matched:
        return True, result.matched_pattern

    return False, None


def check_for_prompt_injection_safe(
    text: str,
    timeout_seconds: float = 0.150,
) -> tuple[bool, str | None, bool]:
    """
    Extended scanner returning (is_flagged, matched_pattern, timed_out).
    """
    if not text or not text.strip():
        return False, None, False

    result = safe_regex_match_any(
        patterns=_INJECTION_PATTERNS,
        text=text,
        timeout_seconds=timeout_seconds,
        flags=re.IGNORECASE,
    )

    return result.matched or result.timed_out, result.matched_pattern or result.error, result.timed_out

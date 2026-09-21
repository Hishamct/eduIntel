"""
Prompt-injection defense: detects attempts to override system instructions
embedded in user-supplied text (a student's doubt-forum question, a portal
assistant message, a study-tutor query) before that text is interpolated
into an LLM prompt.

This is a pattern/heuristic guard, not a model-based classifier — appropriate
for a capstone timeline, and transparent/auditable (you can point a reviewer
at the exact pattern list). It deliberately errs toward catching the common,
well-known jailbreak phrasings rather than trying to be exhaustive; a
production system would layer this with an LLM-based classifier as a second
line of defense.

Usage:
    from app.core.guardrails import check_for_prompt_injection

    is_flagged, matched_pattern = check_for_prompt_injection(user_query)
    if is_flagged:
        return {"answer": INJECTION_REFUSAL_MESSAGE, ...}
    # otherwise proceed to build the prompt as normal
"""

import re

INJECTION_REFUSAL_MESSAGE = (
    "I can't process that message — it looks like it's trying to change how "
    "I'm instructed to behave rather than asking a genuine question. If you "
    "have a real question about the platform or your studies, please ask "
    "that directly."
)

# Each pattern is matched case-insensitively against the raw user input.
# Grouped by the kind of attack they represent, for readability and so new
# patterns are easy to slot into the right category.
_INJECTION_PATTERNS = [
    # Instruction override attempts
    r"ignore (all |any )?(previous|prior|above|earlier) instructions",
    r"disregard (the |all )?(system prompt|instructions|rules)",
    r"forget (everything|what|all) (you('ve| have)? been told|i said|your instructions)",
    r"new instructions?\s*:",
    r"override (your |the )?(system prompt|instructions|rules)",
    # Role / persona hijacking
    r"you are now\s+\w+",
    r"act as (an?|the)\s+\w+",
    r"pretend (you('re| are)|to be)\s+\w+",
    r"from now on,? you (are|will|must)",
    r"enter (developer|debug|jailbreak|dan|unrestricted) mode",
    r"\bdan mode\b",
    # Attempts to extract the system prompt itself
    r"(reveal|show|print|output|repeat) (your |the )?(system )?prompt",
    r"what (is|are) your (system )?(prompt|instructions|rules)",
    r"repeat (the words|everything) above",
    # Explicit jailbreak / restriction-bypass language
    r"\bjailbreak\b",
    r"without (any )?(restrictions|limitations|filters|guidelines)",
    r"bypass (your |the )?(restrictions|filters|guidelines|safety)",
    r"no longer (bound|restricted|limited) by",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def check_for_prompt_injection(text: str) -> tuple[bool, str | None]:
    """
    Scans user-supplied text for known prompt-injection / jailbreak
    patterns. Returns (is_flagged, matched_pattern_description).

    is_flagged=True means the caller should NOT pass this text into an LLM
    prompt as-is — return INJECTION_REFUSAL_MESSAGE (or similar) instead.
    """
    if not text:
        return False, None

    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True, pattern.pattern

    return False, None

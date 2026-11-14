"""
backend/app/guardrails/anti_cheating.py

Anti-cheating, academic integrity, and pedagogical guidance guardrails for EduIntel AI.
Supports institutional policy modes:
- STRICT: Enforces Socratic guidance on all homework, problem-solving, and calculation requests.
- BALANCED (Default): Socratic guidance on direct solution requests; conceptual explanations permitted.
- PERMISSIVE: Allows worked solutions with pedagogical framing; flags sessions for audit logging.
- EXAM: Strict refusal on queries related to active examination topics during exam windows.
"""

import re
from enum import StrEnum

from app.guardrails.redos_guard import safe_regex_match_any


class PolicyMode(StrEnum):
    STRICT = "STRICT"
    BALANCED = "BALANCED"
    PERMISSIVE = "PERMISSIVE"
    EXAM = "EXAM"


# 1. Direct "give me the final answer" phrasing (BALANCED + STRICT)
_DIRECT_ANSWER_PATTERNS = [
    r"just (give|tell) me the answer",
    r"give me the (final |correct )?answer(s)?( to)?",
    r"what('s| is) the answer( to (this|question|q\.?\s*\d+))?",
    r"tell me the answer",
    r"do (my|this) (homework|assignment)( for me)?",
    r"solve (this|it|the (problem|question)) for me",
    r"complete (this|my) (assignment|homework|worksheet)( for me)?",
    r"write (the|my) answer(s)? for (question|q\.?\s*\d+)",
    r"without (any )?(explanation|working|steps|showing work)",
    r"skip the (explanation|steps|working)",
    r"(just|only) (the|give me the) (final )?answer",
    r"no need to explain",
    r"answer key",
    r"answers? to (all|the) (questions|problems)",
]

# 2. Broader problem-solving and homework requests (STRICT mode only)
_STRICT_HOMEWORK_PATTERNS = [
    r"find (the value of |x|y|the roots)",
    r"calculate (the |this )?",
    r"simplify (the expression|this)?",
    r"write an essay on",
    r"write code to solve",
    r"step-by-step solution to",
    r"homework question",
]

# 3. Active exam and assessment patterns (EXAM mode)
_EXAM_KEYWORDS = [
    r"\b(exam|examination|midterm|final exam|quiz|test paper)\b",
    r"question paper",
    r"during the test",
]

ACADEMIC_CHEATING_PATTERNS = _DIRECT_ANSWER_PATTERNS + _STRICT_HOMEWORK_PATTERNS
EXAM_MODE_PATTERNS = _EXAM_KEYWORDS

SOCRATIC_MODE_INSTRUCTION = """IMPORTANT — the student's message reads like a request to skip straight to a finished answer rather than to understand the material. Do NOT provide a direct final answer or a complete worked solution.

Instead, respond in Socratic mode:
- Ask a guiding question or point out the first concept/step they need to think about.
- Give at most one small hint at a time, grounded in the reference material above.
- Encourage them to attempt the next step themselves before offering more.
- If they push back and ask again for the direct answer, gently hold the line and reframe it as "let's work through it together" rather than complying.

Never say the words "I can't help you cheat" or similar — just naturally guide them like a patient tutor would, without being preachy about it."""

EXAM_REFUSAL_MESSAGE = (
    "Academic integrity policy: Direct assistance and problem-solving on active "
    "examination topics are restricted during testing windows. Please consult "
    "your course instructor or syllabus guidelines."
)


def check_for_cheating_intent(
    text: str,
    timeout_seconds: float = 0.150,
) -> tuple[bool, str | None]:
    """
    Backwards-compatible scanner for direct solution requests.
    Returns (is_cheating_attempt, matched_pattern).
    """
    if not text or not text.strip():
        return False, None

    result = safe_regex_match_any(
        patterns=_DIRECT_ANSWER_PATTERNS,
        text=text,
        timeout_seconds=timeout_seconds,
        flags=re.IGNORECASE,
    )
    if result.matched:
        return True, result.matched_pattern
    return False, None


def evaluate_institutional_policy(
    text: str,
    mode: str | PolicyMode = PolicyMode.BALANCED,
    is_exam_window: bool = False,
    exam_topics: list[str] | None = None,
    timeout_seconds: float = 0.150,
) -> tuple[bool, str | None, bool]:
    """
    Evaluates query against institutional academic policy mode.

    Returns:
        (requires_socratic: bool, matched_pattern: str | None, is_exam_refusal: bool)
    """
    if not text or not text.strip():
        return False, None, False

    mode_str = mode.value if isinstance(mode, PolicyMode) else str(mode).upper()

    # 1. EXAM Mode evaluation
    if mode_str == PolicyMode.EXAM.value and is_exam_window:
        exam_patterns = list(_EXAM_KEYWORDS)
        if exam_topics:
            for topic in exam_topics:
                exam_patterns.append(rf"\b{re.escape(topic)}\b")
        result = safe_regex_match_any(
            patterns=exam_patterns + _DIRECT_ANSWER_PATTERNS,
            text=text,
            timeout_seconds=timeout_seconds,
            flags=re.IGNORECASE,
        )
        if result.matched:
            return False, result.matched_pattern, True

    # 2. PERMISSIVE Mode: never enforces Socratic refusal
    if mode_str == PolicyMode.PERMISSIVE.value:
        # Check if direct answer requested for logging purposes
        is_direct, pat = check_for_cheating_intent(text, timeout_seconds=timeout_seconds)
        return False, pat, False

    # 3. STRICT Mode: checks both direct and homework patterns
    if mode_str == PolicyMode.STRICT.value:
        combined = _DIRECT_ANSWER_PATTERNS + _STRICT_HOMEWORK_PATTERNS
        result = safe_regex_match_any(
            patterns=combined,
            text=text,
            timeout_seconds=timeout_seconds,
            flags=re.IGNORECASE,
        )
        if result.matched:
            return True, result.matched_pattern, False
        return False, None, False

    # 4. BALANCED Mode (Default): checks direct solution requests
    is_direct, pat = check_for_cheating_intent(text, timeout_seconds=timeout_seconds)
    return is_direct, pat, False


def build_socratic_instruction(is_cheating_attempt: bool) -> str:
    """Returns Socratic guidance prompt injection text if cheating attempt detected."""
    return SOCRATIC_MODE_INSTRUCTION if is_cheating_attempt else ""

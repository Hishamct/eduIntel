import re

# Each pattern targets phrasing that asks the tutor to skip explanation and
# hand over a finished answer/solution — not ordinary academic questions.
# Grouped by the kind of request they represent, for readability.
_CHEATING_INTENT_PATTERNS = [
    # Direct "just give me the answer" requests
    r"just (give|tell) me the answer",
    r"give me the (final |correct )?answer(s)?( to)?",
    r"what('s| is) the answer( to (this|question|q\.?\s*\d+))?",
    r"tell me the answer",
    # Asking the tutor to do the work outright
    r"do (my|this) (homework|assignment)( for me)?",
    r"solve (this|it|the (problem|question)) for me",
    r"complete (this|my) (assignment|homework|worksheet)( for me)?",
    r"write (the|my) answer(s)? for (question|q\.?\s*\d+)",
    # Explicitly trying to skip explanation/reasoning
    r"without (any )?(explanation|working|steps|showing work)",
    r"skip the (explanation|steps|working)",
    r"(just|only) (the|give me the) (final )?answer",
    r"no need to explain",
    # Asking for an answer key / final answers to a set
    r"answer key",
    r"answers? to (all|the) (questions|problems)",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _CHEATING_INTENT_PATTERNS]

SOCRATIC_MODE_INSTRUCTION = """IMPORTANT — the student's message reads like a request to skip straight to a finished answer rather than to understand the material. Do NOT provide a direct final answer or a complete worked solution.

Instead, respond in Socratic mode:
- Ask a guiding question or point out the first concept/step they need to think about.
- Give at most one small hint at a time, grounded in the reference material above.
- Encourage them to attempt the next step themselves before offering more.
- If they push back and ask again for the direct answer, gently hold the line and reframe it as "let's work through it together" rather than complying.

Never say the words "I can't help you cheat" or similar — just naturally guide them like a patient tutor would, without being preachy about it."""


def check_for_cheating_intent(text: str) -> tuple[bool, str | None]:
    """
    Scans user-supplied text for phrasing that asks the tutor to skip
    straight to a finished answer/solution. Returns
    (is_cheating_attempt, matched_pattern_description).

    This never blocks the request — see build_socratic_instruction for how
    the caller should respond when is_cheating_attempt is True.
    """
    if not text:
        return False, None

    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True, pattern.pattern

    return False, None


def build_socratic_instruction(is_cheating_attempt: bool) -> str:
    """
    Returns the prompt-injection-into-OUR-OWN-prompt text (not to be
    confused with the prompt_injection.py guardrail, which defends against
    the reverse) that tells the LLM to answer in guided/Socratic mode.
    Empty string when the check didn't fire, so callers can always splice
    this into their prompt unconditionally.
    """
    return SOCRATIC_MODE_INSTRUCTION if is_cheating_attempt else ""

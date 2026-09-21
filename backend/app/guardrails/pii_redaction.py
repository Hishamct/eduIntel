"""
PII redaction: scans LLM-generated content for personally identifiable
information before it leaves the system, and masks it.

Unlike prompt_injection.py, this guardrail doesn't block anything — a
report or answer is still allowed out, just with identifiers stripped out
of it. The threat model here isn't "the user is attacking the system," it's
"the LLM echoed back something it shouldn't have." That happens most easily
in the Parent Report Generation Agent: the generation prompt includes real
teacher notes and academic data pulled straight from the DB, and a teacher's
free-text note can easily contain a phone number or email address that
belongs to someone else entirely (another parent, a colleague, the teacher
themselves) — not something that should end up verbatim in an email sent
to a different family.

This is a pattern/heuristic guard, same spirit as prompt_injection.py:
transparent, auditable, appropriate for a capstone timeline, not a
substitute for a model-based PII classifier in a production system.

Usage:
    from app.guardrails.pii_redaction import redact_pii

    redacted_text, findings = redact_pii(draft_body, allow_values={parent_email})
    # findings: [{"type": "EMAIL"}, {"type": "PHONE_INDIA"}, ...]
    # redacted_text has each match replaced with "[REDACTED-<TYPE>]"

    if findings:
        # log it (see app/observability/service.py: log_pii_redaction) —
        # never log the raw matched value, only its type and count.
        ...
"""

import re

REDACTION_TOKEN_FMT = "[REDACTED-{}]"

# Alternation order matters: at a given starting position, Python's re
# engine tries branches left-to-right and takes the first that matches, so
# more specific / longer patterns go first. CARD (16 digits) is listed
# before AADHAAR (12 digits) so a 16-digit run isn't partially swallowed by
# the AADHAAR branch matching just its first 12 digits and leaving the
# trailing 4 digits unredacted; AADHAAR/PAN/CARD are all listed before the
# looser phone patterns for the same reason.
_COMBINED_PATTERN = re.compile(
    r"(?P<EMAIL>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
    r"|(?P<CARD>(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d))"
    r"|(?P<AADHAAR>(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d))"
    r"|(?P<PAN>\b[A-Z]{5}\d{4}[A-Z]\b)"
    r"|(?P<PHONE_INDIA>(?<!\d)(?:\+91[\s-]?|0)?[6-9]\d{9}(?!\d))"
    r"|(?P<PHONE_GENERIC>(?<!\d)\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d))"
)

# Human-readable labels for audit logs / admin-facing summaries.
PII_TYPE_LABELS = {
    "EMAIL": "email address",
    "AADHAAR": "Aadhaar-style ID number",
    "PAN": "PAN-style ID number",
    "CARD": "card-style number",
    "PHONE_INDIA": "Indian phone number",
    "PHONE_GENERIC": "phone number",
}


def redact_pii(
    text: str, allow_values: set[str] | None = None
) -> tuple[str, list[dict]]:
    """
    Scans `text` for PII patterns and replaces each match with a
    "[REDACTED-<TYPE>]" token.

    allow_values: exact strings that should pass through untouched even if
    they match a pattern — e.g. the parent's own email address, which is
    expected to legitimately appear in a report footer ("Reply to this
    email or contact the school at ...").

    Returns (redacted_text, findings). findings never contains the raw
    matched value — only {"type": <pattern name>} — so a caller can safely
    log or count what was redacted without persisting the PII itself.
    """
    if not text:
        return text, []

    allow_values = allow_values or set()
    findings: list[dict] = []

    def _replace(match: re.Match) -> str:
        kind = match.lastgroup
        value = match.group()
        if value in allow_values or value.strip() in allow_values:
            return value
        findings.append({"type": kind})
        return REDACTION_TOKEN_FMT.format(kind)

    redacted_text = _COMBINED_PATTERN.sub(_replace, text)
    return redacted_text, findings


def summarize_findings(findings: list[dict]) -> list[str]:
    """Distinct PII types found, for a compact audit-log column."""
    seen = []
    for f in findings:
        if f["type"] not in seen:
            seen.append(f["type"])
    return seen

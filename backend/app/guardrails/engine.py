"""
backend/app/guardrails/engine.py

Central Guardrails Engine for EduIntel AI.
Orchestrates pre-model input safety gates, institutional academic integrity policies,
ReDoS-protected pattern evaluation, and post-generation PII/data-leak validation.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.guardrails.anti_cheating import (
    EXAM_REFUSAL_MESSAGE,
    PolicyMode,
    build_socratic_instruction,
    evaluate_institutional_policy,
)
from app.guardrails.pii_redaction import redact_pii
from app.guardrails.prompt_injection import (
    INJECTION_REFUSAL_MESSAGE,
    check_for_prompt_injection_safe,
)

logger = logging.getLogger(__name__)

# Maximum query length in characters before pre-flight rejection
MAX_QUERY_LENGTH_CHARS = 8192

# Sensitive system tokens whose presence in output signals an extraction leak
SYSTEM_LEAK_PATTERNS = [
    "you are eduintel ai",
    "you are the eduintel ai portal assistant",
    "you are the eduintel ai admin assistant",
    "you are a study assistant answering",
    "---begin system prompt---",
    "<|im_start|>system",
    "<system>",
    "internal system instructions:",
    "system instructions:",
    "system prompt:",
]


@dataclass
class GuardrailResult:
    """Evaluation result for inbound user prompts."""

    blocked: bool = False
    block_reason: str | None = None
    refusal_message: str | None = None
    requires_socratic: bool = False
    socratic_instruction: str = ""
    sanitized_text: str = ""
    audit_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailOutputResult:
    """Evaluation result for outbound model completions."""

    sanitized_text: str
    pii_detected: bool = False
    findings: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None


class GuardrailsEngine:
    """
    Centralized guardrails orchestrator implementing:
    1. Input length sanitization.
    2. ReDoS-safe prompt injection & jailbreak detection.
    3. Institutional academic policy enforcement (STRICT, BALANCED, PERMISSIVE, EXAM).
    4. Socratic guidance instruction generation.
    5. Output PII redaction and confidential metaprompt leak prevention.
    """

    def __init__(self, timeout_seconds: float = 0.150) -> None:
        self.timeout_seconds = timeout_seconds

    def evaluate_input(
        self,
        query: str,
        institution_settings: dict[str, Any] | None = None,
        is_exam_window: bool = False,
        exam_topics: list[str] | None = None,
        check_academic_integrity: bool = True,
        policy_mode: PolicyMode | str | None = None,
    ) -> GuardrailResult:
        """
        Executes pre-model guardrail pipeline on inbound student, teacher, or administrative prompt.
        If check_academic_integrity is False, skips homework/exam policy checks while strictly
        enforcing length bounds and prompt injection / jailbreak protection.
        """
        if not query or not query.strip():
            return GuardrailResult(
                blocked=False,
                sanitized_text="",
            )

        sanitized_query = query.strip()

        # 1. Enforce character length limit
        if len(sanitized_query) > MAX_QUERY_LENGTH_CHARS:
            return GuardrailResult(
                blocked=True,
                block_reason="LENGTH_EXCEEDED",
                refusal_message=(
                    f"Query exceeds the maximum allowable length of {MAX_QUERY_LENGTH_CHARS} characters. "
                    "Please shorten your question."
                ),
                sanitized_text=sanitized_query[:MAX_QUERY_LENGTH_CHARS],
                audit_metadata={"query_length": len(sanitized_query)},
            )

        # 2. Check for Prompt Injection / Jailbreaks (ReDoS protected)
        is_injection, matched_pattern, timed_out = check_for_prompt_injection_safe(
            text=sanitized_query,
            timeout_seconds=self.timeout_seconds,
        )

        if timed_out:
            logger.warning("Guardrail ReDoS timeout encountered on input query")
            return GuardrailResult(
                blocked=True,
                block_reason="GUARDRAIL_TIMEOUT",
                refusal_message=(
                    "Your request could not be processed due to a safety validation timeout. "
                    "Please simplify your query phrasing."
                ),
                sanitized_text=sanitized_query,
                audit_metadata={"timed_out": True, "error": "GUARDRAIL_TIMEOUT"},
            )

        if is_injection:
            logger.info("Prompt injection detected: pattern=%s", matched_pattern)
            return GuardrailResult(
                blocked=True,
                block_reason="PROMPT_INJECTION",
                refusal_message=INJECTION_REFUSAL_MESSAGE,
                sanitized_text=sanitized_query,
                audit_metadata={"injection_pattern": matched_pattern},
            )

        # 3. Institutional Academic Integrity Policy Mode (Skipped for administrative / parent workflows)
        if not check_academic_integrity:
            return GuardrailResult(
                blocked=False,
                requires_socratic=False,
                socratic_instruction="",
                sanitized_text=sanitized_query,
                audit_metadata={"academic_integrity_checked": False},
            )

        inst_settings = institution_settings or {}
        resolved_mode = policy_mode
        if resolved_mode is None:
            policy_mode_str = inst_settings.get("anti_cheating_mode", PolicyMode.BALANCED.value)
            try:
                resolved_mode = PolicyMode(str(policy_mode_str).upper())
            except ValueError:
                resolved_mode = PolicyMode.BALANCED
        elif isinstance(resolved_mode, str):
            try:
                resolved_mode = PolicyMode(resolved_mode.upper())
            except ValueError:
                resolved_mode = PolicyMode.BALANCED

        requires_socratic, pattern, is_exam_refusal = evaluate_institutional_policy(
            text=sanitized_query,
            mode=resolved_mode,
            is_exam_window=is_exam_window,
            exam_topics=exam_topics,
            timeout_seconds=self.timeout_seconds,
        )

        # 4. Handle EXAM Mode Refusal
        if is_exam_refusal:
            logger.info("Exam mode refusal triggered: pattern=%s", pattern)
            return GuardrailResult(
                blocked=True,
                block_reason="EXAM_MODE_REFUSAL",
                refusal_message=EXAM_REFUSAL_MESSAGE,
                sanitized_text=sanitized_query,
                audit_metadata={"policy_mode": "EXAM", "matched_pattern": pattern},
            )

        # 5. Handle Socratic Guidance vs Permissive Logging
        socratic_instruction = build_socratic_instruction(requires_socratic)
        audit_meta: dict[str, Any] = {
            "policy_mode": resolved_mode.value,
            "requires_socratic": requires_socratic,
        }
        if pattern:
            audit_meta["anti_cheating_pattern"] = pattern
        if resolved_mode == PolicyMode.PERMISSIVE and pattern:
            audit_meta["flagged_permissive_homework"] = True

        return GuardrailResult(
            blocked=False,
            requires_socratic=requires_socratic,
            socratic_instruction=socratic_instruction,
            sanitized_text=sanitized_query,
            audit_metadata=audit_meta,
        )

    def evaluate_output(
        self,
        text: str,
        allow_values: set[str] | None = None,
    ) -> GuardrailOutputResult:
        """
        Executes post-generation safety checks on LLM completions:
        1. Redacts PII (Aadhaar, PAN, Card, Phone, Email).
        2. Detects system prompt / metaprompt extraction leaks.
        """
        if not text:
            return GuardrailOutputResult(sanitized_text="")

        # 1. Check for confidential metaprompt leakage
        lower_text = text.lower()
        for leak_pattern in SYSTEM_LEAK_PATTERNS:
            if leak_pattern in lower_text:
                logger.critical("Metaprompt leakage detected in model output: '%s'", leak_pattern)
                return GuardrailOutputResult(
                    sanitized_text="",
                    blocked=True,
                    block_reason="PROMPT_LEAK_DETECTED",
                )

        # 2. PII Redaction
        redacted_text, findings = redact_pii(text, allow_values=allow_values)

        return GuardrailOutputResult(
            sanitized_text=redacted_text,
            pii_detected=bool(findings),
            findings=findings,
            blocked=False,
        )


# Global singleton engine instance
default_guardrails_engine = GuardrailsEngine(
    timeout_seconds=getattr(settings, "GUARDRAIL_TIMEOUT_MS", 150) / 1000.0,
)


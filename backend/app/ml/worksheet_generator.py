"""
backend/app/ml/worksheet_generator.py

Generates targeted practice worksheets (PDF) for specific weak topics using
the unified LLM provider registry and multi-tier AI safety guardrails.
"""

from __future__ import annotations

import html
import io
import json
import logging
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from app.core.llm_client import LLMCallUsage, generate_text_with_usage
from app.guardrails.engine import default_guardrails_engine

logger = logging.getLogger(__name__)

PRIMARY_COLOR = colors.HexColor("#26415E")
ACCENT_COLOR = colors.HexColor("#C97A2B")

N_QUESTIONS = 8
TARGET_DIFFICULTY_DIST = {"easy": 3, "medium": 3, "hard": 2}
MAX_INPUT_FIELD_LENGTH = 200     # Single unified length bound for all user input fields
MAX_RAW_RESPONSE_BYTES = 32_768  # 32 KB maximum raw response size


class WorksheetGenerationError(Exception):
    """Base exception for worksheet generation failures, carrying any captured LLM usage."""

    def __init__(self, message: str, usage: LLMCallUsage | None = None):
        super().__init__(message)
        self.message = message
        self.usage = usage


class WorksheetGuardrailError(WorksheetGenerationError):
    """Raised when safety guardrails block generation (input injection or output leakage)."""

    def __init__(
        self,
        message: str,
        refusal_message: str | None = None,
        block_reason: str | None = None,
        is_output_violation: bool = False,
        usage: LLMCallUsage | None = None,
    ):
        super().__init__(message, usage=usage)
        self.refusal_message = refusal_message or message
        self.block_reason = block_reason
        self.is_output_violation = is_output_violation


class WorksheetParsingError(WorksheetGenerationError):
    """Raised when upstream LLM output violates JSON syntax, ambiguity rules, or schema."""

    def __init__(self, message: str, usage: LLMCallUsage | None = None):
        super().__init__(message, usage=usage)


def _validate_and_sanitize_inputs(
    subject: str,
    topic: str,
    student_name: str | None = None,
    student_context: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    clean_subject = (subject or "").strip()
    clean_topic = (topic or "").strip()
    clean_name = (student_name or "").strip() if student_name else None
    clean_context = (student_context or "").strip() if student_context else None

    if not clean_subject:
        raise WorksheetGenerationError("Subject cannot be empty.")
    if not clean_topic:
        raise WorksheetGenerationError("Topic cannot be empty.")

    for field_name, value in [
        ("Subject", clean_subject),
        ("Topic", clean_topic),
        ("Student name", clean_name),
        ("Student context", clean_context),
    ]:
        if value and len(value) > MAX_INPUT_FIELD_LENGTH:
            raise WorksheetGuardrailError(
                message=f"{field_name} exceeds maximum length of {MAX_INPUT_FIELD_LENGTH} characters.",
                refusal_message=f"{field_name} exceeds maximum allowed length of {MAX_INPUT_FIELD_LENGTH} characters.",
                block_reason="PAYLOAD_TOO_LARGE",
                is_output_violation=False,
            )

    combined_query = f"Subject: {clean_subject}. Topic: {clean_topic}."
    if clean_context:
        combined_query += f" Context: {clean_context}."

    eval_result = default_guardrails_engine.evaluate_input(
        query=combined_query,
        check_academic_integrity=False,
    )
    if eval_result.blocked:
        logger.warning("[Worksheet Guardrail] Blocked input query: %s", eval_result.block_reason)
        raise WorksheetGuardrailError(
            message=f"Worksheet generation input blocked: {eval_result.block_reason}",
            refusal_message=eval_result.refusal_message or "Request blocked by safety guardrails.",
            block_reason=eval_result.block_reason,
            is_output_violation=False,
        )

    if clean_name:
        name_eval = default_guardrails_engine.evaluate_input(
            query=clean_name,
            check_academic_integrity=False,
        )
        if name_eval.blocked:
            raise WorksheetGuardrailError(
                message="Student name contains invalid or malicious content.",
                refusal_message="Student name rejected by safety guardrails.",
                block_reason=name_eval.block_reason,
                is_output_violation=False,
            )
        clean_name = name_eval.sanitized_text

    return clean_subject, clean_topic, clean_name, clean_context


def _extract_and_decode_json(raw_text: str, usage: LLMCallUsage | None = None) -> list[dict[str, Any]]:
    raw_bytes_len = len(raw_text.encode("utf-8"))
    if raw_bytes_len > MAX_RAW_RESPONSE_BYTES:
        raise WorksheetParsingError(
            f"Model output exceeded maximum permitted payload size of {MAX_RAW_RESPONSE_BYTES} bytes.",
            usage=usage,
        )

    text = raw_text.strip()

    fence_matches = list(re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE))
    if len(fence_matches) > 1:
        raise WorksheetParsingError(
            "Model output contains multiple ambiguous markdown code fences.",
            usage=usage,
        )

    if len(fence_matches) == 1:
        match = fence_matches[0]
        leading_prose = text[:match.start()].strip()
        trailing_prose = text[match.end():].strip()
        if leading_prose or trailing_prose:
            raise WorksheetParsingError(
                "Model output contains conversational text outside markdown code fence.",
                usage=usage,
            )
        candidate = match.group(1).strip()
    else:
        if not text.startswith("["):
            raise WorksheetParsingError(
                "Model output does not contain a clean JSON array structure.",
                usage=usage,
            )
        candidate = text

    first_bracket = candidate.find("[")
    if first_bracket == -1:
        raise WorksheetParsingError(
            "Model output does not contain a clean JSON array structure.",
            usage=usage,
        )

    decoder = json.JSONDecoder()
    try:
        parsed_obj, end_idx = decoder.raw_decode(candidate[first_bracket:])
        remainder = candidate[first_bracket + end_idx:].strip()
        if remainder:
            raise WorksheetParsingError(
                "Model output contains unexpected trailing content after JSON array.",
                usage=usage,
            )
    except json.JSONDecodeError as err:
        raise WorksheetParsingError(f"Model output contains invalid JSON: {err}", usage=usage) from err

    if not isinstance(parsed_obj, list):
        raise WorksheetParsingError("Model output JSON must be a list of question objects.", usage=usage)

    if len(parsed_obj) != N_QUESTIONS:
        raise WorksheetParsingError(
            f"Model generated incomplete worksheet: expected exactly {N_QUESTIONS} questions, received {len(parsed_obj)}.",
            usage=usage,
        )

    difficulty_counts = {"easy": 0, "medium": 0, "hard": 0}
    validated_items: list[dict[str, Any]] = []

    for idx, item in enumerate(parsed_obj, start=1):
        if not isinstance(item, dict):
            raise WorksheetParsingError(f"Question item #{idx} is not a valid JSON dictionary.", usage=usage)

        q_val = str(item.get("question", "")).strip()
        ans_val = str(item.get("answer", "")).strip()
        diff_val = str(item.get("difficulty", "")).strip().lower()

        if not q_val:
            raise WorksheetParsingError(f"Question item #{idx} missing required 'question' text.", usage=usage)
        if not ans_val:
            raise WorksheetParsingError(f"Question item #{idx} missing required 'answer' text.", usage=usage)
        if diff_val not in {"easy", "medium", "hard"}:
            raise WorksheetParsingError(
                f"Question item #{idx} has invalid difficulty '{diff_val}'; must be one of 'easy', 'medium', 'hard'.",
                usage=usage,
            )

        difficulty_counts[diff_val] += 1
        validated_items.append({
            "question": q_val,
            "difficulty": diff_val,
            "answer": ans_val,
        })

    if difficulty_counts != TARGET_DIFFICULTY_DIST:
        raise WorksheetParsingError(
            f"Model generated invalid difficulty distribution: {difficulty_counts}; expected exactly {TARGET_DIFFICULTY_DIST}.",
            usage=usage,
        )

    return validated_items


def _generate_questions(
    subject: str,
    topic: str,
    student_context: str | None = None,
) -> tuple[list[dict[str, Any]], LLMCallUsage]:
    context_note = (
        f"\n\nContext: this worksheet is targeted at a student who is currently struggling specifically with {topic}, so questions should build from fundamentals rather than assume mastery."
        if student_context
        else ""
    )

    prompt = f"""Generate exactly {N_QUESTIONS} practice questions for a student studying {topic} under {subject}, at a level appropriate for secondary/high school coaching institute students.{context_note}

Include a mix of difficulty: exactly 3 easy (fundamentals/recall), 3 medium (application), 2 harder (multi-step problem solving).

Respond with ONLY a JSON array, no other text, no markdown code fences. Each item must have exactly these fields:
- "question": the question text
- "difficulty": one of "easy", "medium", "hard"
- "answer": the correct answer or solution, concise but complete enough to be useful as an answer key

Example format:
[{{"question": "...", "difficulty": "easy", "answer": "..."}}]"""

    raw_text, usage = generate_text_with_usage(prompt)
    raw_text = raw_text.strip()

    if "Security violation: response blocked" in raw_text:
        raise WorksheetGuardrailError(
            message="Model output blocked due to confidential prompt leakage.",
            refusal_message="Security violation: response blocked due to confidential system prompt leakage.",
            block_reason="PROMPT_LEAK_DETECTED",
            is_output_violation=True,
            usage=usage,
        )

    raw_eval = default_guardrails_engine.evaluate_output(raw_text)
    if raw_eval.blocked:
        logger.critical("[Worksheet Guardrail] Raw output contained metaprompt leakage: %s", raw_eval.block_reason)
        raise WorksheetGuardrailError(
            message=f"Model output contained confidential instructions: {raw_eval.block_reason}",
            refusal_message="Security violation: response blocked due to confidential system prompt leakage.",
            block_reason=raw_eval.block_reason,
            is_output_violation=True,
            usage=usage,
        )

    raw_questions = _extract_and_decode_json(raw_text, usage=usage)

    sanitized_questions: list[dict[str, Any]] = []
    for q_item in raw_questions:
        q_eval = default_guardrails_engine.evaluate_output(q_item["question"])
        a_eval = default_guardrails_engine.evaluate_output(q_item["answer"])

        if q_eval.blocked or a_eval.blocked:
            logger.critical("[Worksheet Guardrail] Metaprompt leakage in parsed question/answer field.")
            raise WorksheetGuardrailError(
                message="Parsed question or answer field contained confidential instructions.",
                refusal_message="Security violation: response blocked due to confidential system prompt leakage.",
                block_reason="PROMPT_LEAK_DETECTED",
                is_output_violation=True,
                usage=usage,
            )

        sanitized_questions.append({
            "question": q_eval.sanitized_text,
            "difficulty": q_item["difficulty"],
            "answer": a_eval.sanitized_text,
        })

    return sanitized_questions, usage


def generate_worksheet_pdf(
    subject: str,
    topic: str,
    student_name: str | None = None,
    student_context: str | None = None,
) -> tuple[bytes, LLMCallUsage]:
    clean_sub, clean_top, clean_name, clean_ctx = _validate_and_sanitize_inputs(
        subject=subject,
        topic=topic,
        student_name=student_name,
        student_context=student_context,
    )

    questions, usage = _generate_questions(
        subject=clean_sub,
        topic=clean_top,
        student_context=clean_ctx,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "WorksheetTitle",
        parent=styles["Heading1"],
        textColor=PRIMARY_COLOR,
        fontSize=20,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "WorksheetSubtitle",
        parent=styles["Normal"],
        textColor=colors.HexColor("#5F6774"),
        fontSize=11,
        spaceAfter=20,
    )
    question_style = ParagraphStyle(
        "Question",
        parent=styles["Normal"],
        fontSize=12,
        spaceAfter=6,
        spaceBefore=14,
        leading=16,
    )
    difficulty_style = ParagraphStyle(
        "Difficulty",
        parent=styles["Normal"],
        fontSize=9,
        textColor=ACCENT_COLOR,
        spaceAfter=2,
    )
    answer_style = ParagraphStyle(
        "Answer",
        parent=styles["Normal"],
        fontSize=11,
        leading=15,
        spaceAfter=10,
        textColor=colors.HexColor("#1B2330"),
    )
    section_header_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        textColor=PRIMARY_COLOR,
        fontSize=16,
        spaceBefore=10,
        spaceAfter=14,
    )

    elements = []

    safe_topic = html.escape(clean_top)
    safe_sub = html.escape(clean_sub)
    elements.append(Paragraph(f"Targeted Practice Worksheet: {safe_topic}", title_style))
    subtitle = f"Subject: {safe_sub}"
    if clean_name:
        safe_name = html.escape(clean_name)
        subtitle += f" &nbsp;&nbsp;|&nbsp;&nbsp; Prepared for: {safe_name}"
    elements.append(Paragraph(subtitle, subtitle_style))

    elements.append(
        Paragraph(
            "Generated by EduIntel AI based on identified areas for improvement. "
            "Work through each question before checking the answer key at the end.",
            styles["Italic"],
        )
    )
    elements.append(Spacer(1, 12))

    for i, q in enumerate(questions, start=1):
        safe_q = html.escape(q["question"])
        safe_diff = html.escape(q["difficulty"].upper())
        elements.append(Paragraph(f"<b>Q{i}.</b> {safe_q}", question_style))
        elements.append(Paragraph(f"[{safe_diff}]", difficulty_style))
        elements.append(Spacer(1, 20))

    elements.append(PageBreak())
    elements.append(Paragraph("Answer Key", section_header_style))

    for i, q in enumerate(questions, start=1):
        safe_ans = html.escape(q["answer"])
        elements.append(Paragraph(f"<b>Q{i}.</b> {safe_ans}", answer_style))

    try:
        doc.build(elements)
    except Exception as build_err:
        logger.exception("[Worksheet Generator] ReportLab document compilation failed: %s", build_err)
        raise WorksheetGenerationError(f"PDF compilation failed: {build_err}", usage=usage) from build_err

    buffer.seek(0)
    return buffer.read(), usage

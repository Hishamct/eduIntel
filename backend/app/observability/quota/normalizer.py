"""
backend/app/observability/quota/normalizer.py

Provider Usage Normalizer for Gemini and Groq responses.
Extracts, validates, and normalizes token metadata into a common representation.
Enforces strict discrimination between complete, zero-token, partial, and corrupted metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.observability.quota.types import (
    MAX_TERM_TOKENS,
    MAX_TOTAL_OP_TOKENS,
    validate_non_empty_text,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    """
    Normalized, validated provider usage record.

    is_complete: True strictly when both input_tokens and output_tokens are valid non-None integers.
    is_valid: False if any token field has an invalid type, negative value, or total mismatch.
    """

    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    provider_request_id: str | None
    latency_ms: int
    is_complete: bool
    is_valid: bool
    used_fallback: bool = False
    validation_error: str | None = None


class ProviderUsageNormalizer:
    """
    Validates and normalizes provider usage metadata from raw API responses or LLMCallUsage.
    """

    @classmethod
    def _validate_single_token_count(
        cls,
        raw_val: Any,
        field_name: str,
        upper_bound: int = MAX_TERM_TOKENS,
    ) -> tuple[int | None, str | None]:
        """
        Validates that a token count is an exact integer, rejecting bool, float, string, and negative.
        Returns (int_val, error_str).
        """
        if raw_val is None:
            return None, None
        if isinstance(raw_val, bool):
            return None, f"{field_name} cannot be a boolean"
        if not isinstance(raw_val, int):
            return None, f"{field_name} must be an integer, got {type(raw_val).__name__}"
        if raw_val < 0 or raw_val > upper_bound:
            return None, f"{field_name} must be between 0 and {upper_bound}, got {raw_val}"
        return raw_val, None

    @classmethod
    def normalize(
        cls,
        *,
        provider: str,
        model: str,
        raw_input_tokens: Any,
        raw_output_tokens: Any,
        raw_total_tokens: Any = None,
        provider_request_id: str | None = None,
        latency_ms: int = 0,
        used_fallback: bool = False,
    ) -> NormalizedUsage:
        """
        Normalizes token counts across providers with strict consistency validation.
        """
        clean_provider = validate_non_empty_text(provider, field_name="provider", max_length=50).lower()
        clean_model = validate_non_empty_text(model, field_name="model", max_length=100)

        in_tok, in_err = cls._validate_single_token_count(raw_input_tokens, "input_tokens")
        out_tok, out_err = cls._validate_single_token_count(raw_output_tokens, "output_tokens")
        tot_tok, tot_err = cls._validate_single_token_count(
            raw_total_tokens, "total_tokens", upper_bound=MAX_TOTAL_OP_TOKENS
        )

        errors = [err for err in (in_err, out_err, tot_err) if err is not None]

        # Total token consistency check
        if in_tok is not None and out_tok is not None:
            computed_sum = in_tok + out_tok
            if tot_tok is not None and tot_tok != computed_sum:
                errors.append(
                    f"total_tokens ({tot_tok}) inconsistent with input ({in_tok}) + output ({out_tok})"
                )
            elif tot_tok is None:
                tot_tok = computed_sum

        is_valid = len(errors) == 0
        is_complete = is_valid and (in_tok is not None) and (out_tok is not None)

        validation_error = "; ".join(errors) if errors else None
        clean_req_id = None
        if provider_request_id is not None and isinstance(provider_request_id, str) and provider_request_id.strip():
            clean_req_id = provider_request_id.strip()[:255]

        return NormalizedUsage(
            provider=clean_provider,
            model=clean_model,
            input_tokens=in_tok if is_valid else None,
            output_tokens=out_tok if is_valid else None,
            total_tokens=tot_tok if is_valid else None,
            provider_request_id=clean_req_id,
            latency_ms=max(int(latency_ms), 0),
            is_complete=is_complete,
            is_valid=is_valid,
            used_fallback=used_fallback,
            validation_error=validation_error,
        )

    @classmethod
    def from_gemini_response(
        cls,
        response: Any,
        model: str,
        latency_ms: int = 0,
    ) -> NormalizedUsage:
        """Extracts and normalizes usage from Google GenAI response object."""
        usage_meta = getattr(response, "usage_metadata", None)
        in_tok = getattr(usage_meta, "prompt_token_count", None) if usage_meta else None
        out_tok = getattr(usage_meta, "candidates_token_count", None) if usage_meta else None
        tot_tok = getattr(usage_meta, "total_token_count", None) if usage_meta else None
        req_id = getattr(response, "response_id", None) or getattr(response, "id", None)

        return cls.normalize(
            provider="gemini",
            model=model,
            raw_input_tokens=in_tok,
            raw_output_tokens=out_tok,
            raw_total_tokens=tot_tok,
            provider_request_id=str(req_id) if req_id else None,
            latency_ms=latency_ms,
            used_fallback=False,
        )

    @classmethod
    def from_groq_response(
        cls,
        response: Any,
        model: str,
        latency_ms: int = 0,
    ) -> NormalizedUsage:
        """Extracts and normalizes usage from Groq ChatCompletion response object."""
        usage_data = getattr(response, "usage", None)
        in_tok = getattr(usage_data, "prompt_tokens", None) if usage_data else None
        out_tok = getattr(usage_data, "completion_tokens", None) if usage_data else None
        tot_tok = getattr(usage_data, "total_tokens", None) if usage_data else None
        req_id = getattr(response, "id", None)

        return cls.normalize(
            provider="groq",
            model=model,
            raw_input_tokens=in_tok,
            raw_output_tokens=out_tok,
            raw_total_tokens=tot_tok,
            provider_request_id=str(req_id) if req_id else None,
            latency_ms=latency_ms,
            used_fallback=True,
        )

    @classmethod
    def from_llm_call_usage(
        cls,
        usage: Any,
    ) -> NormalizedUsage:
        """Normalizes an existing LLMCallUsage object from llm_provider / llm_client."""
        if usage is None:
            return NormalizedUsage(
                provider="unknown",
                model="unknown",
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                provider_request_id=None,
                latency_ms=0,
                is_complete=False,
                is_valid=True,
                used_fallback=False,
                validation_error="Empty or None LLMCallUsage",
            )

        provider = getattr(usage, "provider", "unknown")
        model = getattr(usage, "model", "unknown")
        in_tok = getattr(usage, "input_tokens", None)
        out_tok = getattr(usage, "output_tokens", None)
        latency = getattr(usage, "latency_ms", 0)
        fallback = bool(getattr(usage, "used_fallback", False))

        return cls.normalize(
            provider=provider,
            model=model,
            raw_input_tokens=in_tok,
            raw_output_tokens=out_tok,
            latency_ms=latency,
            used_fallback=fallback,
        )


__all__ = ["NormalizedUsage", "ProviderUsageNormalizer"]


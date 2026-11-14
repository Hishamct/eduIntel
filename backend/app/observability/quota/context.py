"""
backend/app/observability/quota/context.py

Strongly typed request context for Stage 7.3 Metered AI Execution.
Enforces server-verified tenant isolation, usage categorization, and token bounds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.observability.quota.types import (
    validate_non_empty_text,
    validate_token_count,
    validate_usage_category,
)


@dataclass(frozen=True, slots=True)
class MeteredRequestContext:
    """
    Validated server-side context required for every metered AI provider call.

    Guarantees:
    - Tenant identity strictly originates from authenticated server context.
    - Usage category matches valid Stage 7.1/7.2 schema constraints.
    - Zero prompt, completion, PII, or credentials can be stored in metadata.
    """

    institution_id: uuid.UUID
    user_id: uuid.UUID
    endpoint: str
    usage_category: str = "interactive_ai"
    provider: str = "gemini"
    model: str = "gemini-3.6-flash"
    idempotency_key: str | None = None
    logical_operation_id: uuid.UUID = field(default_factory=uuid.uuid4)
    estimated_input_tokens: int = 500
    reserved_output_tokens: int = 2048
    ttl_seconds: int = 300
    pricing_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.institution_id, uuid.UUID):
            raise ValueError(f"institution_id must be a UUID, got {type(self.institution_id).__name__}")
        if not isinstance(self.user_id, uuid.UUID):
            raise ValueError(f"user_id must be a UUID, got {type(self.user_id).__name__}")
        if not isinstance(self.logical_operation_id, uuid.UUID):
            raise ValueError(f"logical_operation_id must be a UUID, got {type(self.logical_operation_id).__name__}")

        validate_usage_category(self.usage_category)
        validate_non_empty_text(self.endpoint, field_name="endpoint", max_length=100)
        validate_non_empty_text(self.provider, field_name="provider", max_length=50)
        validate_non_empty_text(self.model, field_name="model", max_length=100)
        validate_token_count(self.estimated_input_tokens, field_name="estimated_input_tokens")
        validate_token_count(self.reserved_output_tokens, field_name="reserved_output_tokens")

        if isinstance(self.ttl_seconds, bool) or not isinstance(self.ttl_seconds, int) or self.ttl_seconds < 1:
            raise ValueError("ttl_seconds must be a positive integer")

        if self.idempotency_key is not None:
            validate_non_empty_text(self.idempotency_key, field_name="idempotency_key", max_length=255)

        if self.pricing_version is not None:
            validate_non_empty_text(self.pricing_version, field_name="pricing_version", max_length=64)

    def for_endpoint(
        self,
        sub_endpoint: str,
        *,
        estimated_input_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        idempotency_key: str | None = None,
    ) -> MeteredRequestContext:
        """
        Derives a sub-context for multi-call agent turns (e.g. decide_tools then generate).
        Preserves tenant context, user identity, and logical operation linkage while scoping endpoint.
        """
        derived_idempotency = idempotency_key
        if derived_idempotency is None and self.idempotency_key is not None:
            clean_sub = sub_endpoint.replace("/", "_").replace("-", "_")
            derived_idempotency = f"{self.idempotency_key}:{clean_sub}"

        return MeteredRequestContext(
            institution_id=self.institution_id,
            user_id=self.user_id,
            endpoint=sub_endpoint,
            usage_category=self.usage_category,
            provider=self.provider,
            model=self.model,
            idempotency_key=derived_idempotency,
            logical_operation_id=self.logical_operation_id,
            estimated_input_tokens=estimated_input_tokens if estimated_input_tokens is not None else self.estimated_input_tokens,
            reserved_output_tokens=reserved_output_tokens if reserved_output_tokens is not None else self.reserved_output_tokens,
            ttl_seconds=self.ttl_seconds,
            pricing_version=self.pricing_version,
        )


__all__ = ["MeteredRequestContext"]


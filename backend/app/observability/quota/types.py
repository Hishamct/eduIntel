"""
Typed DTOs, immutable snapshots, and shared bounds for Stage 7.2 Quota & FinOps Engine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.observability.quota_models import (
    VALID_ADJUSTMENT_TYPES,
    VALID_ATTEMPT_STATUSES,
    VALID_RECOVERY_STATES,
    VALID_RESERVATION_STATUSES,
    VALID_REVIEW_STATUSES,
    VALID_USAGE_CATEGORIES,
)

MAX_TERM_TOKENS = 1_000_000_000_000_000
MAX_TOTAL_OP_TOKENS = 2_000_000_000_000_000
INR_QUANTIZE = Decimal("0.0001")
MAX_COST_INR_12_4 = Decimal("99999999.9999")


def validate_token_count(value: int, *, field_name: str, upper_bound: int = MAX_TERM_TOKENS) -> int:
    """Validate that a token count is an exact non-bool int within safe PostgreSQL bounds."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0 or value > upper_bound:
        raise ValueError(f"{field_name} must be between 0 and {upper_bound}")
    return value


def validate_non_empty_text(value: str, *, field_name: str, max_length: int | None = None) -> str:
    """Validate that a string field is non-empty after trimming."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    stripped = value.strip()
    if max_length is not None and len(stripped) > max_length:
        raise ValueError(f"{field_name} exceeds maximum length {max_length}")
    return stripped


def validate_usage_category(category: str) -> str:
    """Validate category against Stage 7.1 schema enum."""
    if category not in VALID_USAGE_CATEGORIES:
        raise ValueError(
            f"Unsupported usage_category {category!r}; expected one of {VALID_USAGE_CATEGORIES}"
        )
    return category


def validate_choice(value: str, valid_values: tuple[str, ...], *, field_name: str) -> str:
    """Validate any domain status against its canonical Stage 7.1 tuple."""
    if value not in valid_values:
        raise ValueError(f"Invalid {field_name}={value!r}; expected one of {valid_values}")
    return value


@dataclass(frozen=True, slots=True)
class PricingRateSpec:
    """Resolved per-1k token INR rates for a single (provider, model) pair."""

    provider: str
    model: str
    input_inr_per_1k: Decimal
    output_inr_per_1k: Decimal
    source_currency: str
    usd_to_inr_rate: Decimal


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Centralized Decimal monetary breakdown quantized to NUMERIC(12, 4)."""

    pricing_version: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost_inr: Decimal
    output_cost_inr: Decimal
    total_cost_inr: Decimal


@dataclass(frozen=True, slots=True)
class ReservationCreateRequest:
    """Validated admission request for Tx 1 pre-dispatch reservation."""

    institution_id: uuid.UUID
    user_id: uuid.UUID
    usage_category: str
    endpoint: str
    provider: str
    model: str
    estimated_input_tokens: int
    reserved_output_tokens: int
    ttl_seconds: int = 300
    idempotency_key: str | None = None
    logical_operation_id: uuid.UUID | None = None
    pricing_version: str | None = None

    def __post_init__(self) -> None:
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


@dataclass(frozen=True, slots=True)
class AttemptDispatchRequest:
    """Validated request for Tx 2A durable dispatch boundary."""

    institution_id: uuid.UUID
    reservation_id: uuid.UUID
    provider: str
    model: str
    estimated_tokens: int
    is_fallback: bool = False
    is_retry: bool = False
    provider_request_id: str | None = None
    estimated_input_tokens: int | None = None
    estimated_output_tokens: int | None = None
    pricing_version: str | None = None

    def __post_init__(self) -> None:
        validate_non_empty_text(self.provider, field_name="provider", max_length=50)
        validate_non_empty_text(self.model, field_name="model", max_length=100)
        validate_token_count(
            self.estimated_tokens,
            field_name="estimated_tokens",
            upper_bound=MAX_TOTAL_OP_TOKENS,
        )
        if self.estimated_input_tokens is not None:
            validate_token_count(self.estimated_input_tokens, field_name="estimated_input_tokens")
        if self.estimated_output_tokens is not None:
            validate_token_count(self.estimated_output_tokens, field_name="estimated_output_tokens")
        if self.provider_request_id is not None:
            validate_non_empty_text(
                self.provider_request_id, field_name="provider_request_id", max_length=255
            )


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
    """Immutable snapshot of an AITokenReservation row."""

    id: uuid.UUID
    institution_id: uuid.UUID
    user_id: uuid.UUID
    logical_operation_id: uuid.UUID
    usage_date: date
    usage_category: str
    endpoint: str
    status: str
    pricing_version: str
    estimated_input_tokens: int
    reserved_output_tokens: int
    total_reserved_tokens: int
    reserved_cost_inr: Decimal
    actual_input_tokens: int
    actual_output_tokens: int
    actual_total_tokens: int
    actual_cost_inr: Decimal
    uncertain_tokens_held: int
    uncertain_cost_held_inr: Decimal
    idempotency_key: str | None
    reconciliation_version: int
    recovery_state: str
    recovery_reason: str | None
    review_status: str
    dispatched_at: datetime | None
    created_at: datetime
    expires_at: datetime
    reconciled_at: datetime | None

    @property
    def reservation_id(self) -> uuid.UUID:
        return self.id


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    """Result returned by Tx 1 quota admission."""

    reservation: ReservationSnapshot
    is_idempotent_replay: bool
    cost_breakdown: CostBreakdown | None = None


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    """Immutable snapshot of an AIProviderAttempt row."""

    id: uuid.UUID
    institution_id: uuid.UUID
    reservation_id: uuid.UUID
    attempt_sequence: int
    provider: str
    model: str
    is_fallback: bool
    is_retry: bool
    status: str
    provider_request_id: str | None
    pricing_version: str
    estimated_tokens: int
    estimated_cost_inr: Decimal
    input_tokens: int | None
    output_tokens: int | None
    actual_cost_inr: Decimal | None
    manual_settled_tokens: int | None
    manual_settled_cost_inr: Decimal | None
    manual_settled_at: datetime | None
    late_reported_input_tokens: int | None
    late_reported_output_tokens: int | None
    late_reported_cost_inr: Decimal | None
    late_reported_at: datetime | None
    error_classification: str | None
    latency_ms: int | None
    dispatched_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdjustmentSnapshot:
    """Immutable snapshot of an append-only AIFinancialAdjustment row."""

    id: uuid.UUID
    institution_id: uuid.UUID
    reservation_id: uuid.UUID | None
    attempt_id: uuid.UUID | None
    adjusted_by_actor: str
    adjustment_type: str
    token_delta: int
    cost_inr_delta: Decimal
    adjustment_reason: str
    notes: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Combined outcome of reservation finalization, manual settlement, or late reconciliation."""

    reservation: ReservationSnapshot
    attempts: tuple[AttemptSnapshot, ...]
    adjustment: AdjustmentSnapshot | None = None
    was_idempotent_noop: bool = False


__all__ = [
    "AdmissionResult",
    "AdjustmentSnapshot",
    "AttemptDispatchRequest",
    "AttemptSnapshot",
    "CostBreakdown",
    "INR_QUANTIZE",
    "MAX_COST_INR_12_4",
    "MAX_TERM_TOKENS",
    "MAX_TOTAL_OP_TOKENS",
    "PricingRateSpec",
    "ReconciliationResult",
    "ReservationCreateRequest",
    "ReservationSnapshot",
    "VALID_ADJUSTMENT_TYPES",
    "VALID_ATTEMPT_STATUSES",
    "VALID_RECOVERY_STATES",
    "VALID_RESERVATION_STATUSES",
    "VALID_REVIEW_STATUSES",
    "VALID_USAGE_CATEGORIES",
    "validate_choice",
    "validate_non_empty_text",
    "validate_token_count",
    "validate_usage_category",
]


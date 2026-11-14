"""
Domain exceptions for Stage 7.2 Pricing, FinOps Ledger & Atomic Tenant Quota Engine.

Every exception carries structured, non-sensitive diagnostic fields safe for logging.
"""

from __future__ import annotations

import uuid
from decimal import Decimal


class QuotaEngineError(Exception):
    """Base exception for all Stage 7.2 pricing, quota, and ledger errors."""

    def __init__(self, message: str, *, code: str = "QUOTA_ENGINE_ERROR") -> None:
        super().__init__(message)
        self.code = code


class QuotaConfigurationError(QuotaEngineError):
    """Raised when required pricing or tenant quota configuration is missing or invalid."""

    def __init__(self, message: str, *, code: str = "QUOTA_CONFIGURATION_ERROR") -> None:
        super().__init__(message, code=code)


class PricingVersionNotFoundError(QuotaConfigurationError):
    """Raised when no active pricing version exists or a requested version is missing."""

    def __init__(
        self,
        message: str,
        *,
        version_id: str | None = None,
    ) -> None:
        super().__init__(message, code="PRICING_VERSION_NOT_FOUND")
        self.version_id = version_id


class PricingModelRateNotFoundError(QuotaConfigurationError):
    """Raised when an active pricing version omits rates for a provider/model pair."""

    def __init__(
        self,
        message: str,
        *,
        version_id: str,
        provider: str,
        model: str,
    ) -> None:
        super().__init__(message, code="PRICING_MODEL_RATE_NOT_FOUND")
        self.version_id = version_id
        self.provider = provider
        self.model = model


class InvalidPricingSchemaError(QuotaConfigurationError):
    """Raised when rates_json or pricing numeric fields violate the pricing schema contract."""

    def __init__(self, message: str, *, version_id: str | None = None) -> None:
        super().__init__(message, code="INVALID_PRICING_SCHEMA")
        self.version_id = version_id


class TenantQuotaNotConfiguredError(QuotaConfigurationError):
    """Raised when an institution has no row in tenant_ai_quotas (fail-closed)."""

    def __init__(self, institution_id: uuid.UUID) -> None:
        super().__init__(
            f"Tenant quota configuration missing for institution {institution_id}",
            code="TENANT_QUOTA_NOT_CONFIGURED",
        )
        self.institution_id = institution_id


class TenantQuotaSuspendedError(QuotaEngineError):
    """Raised when an institution's AI quota is suspended."""

    def __init__(self, institution_id: uuid.UUID, reason: str | None = None) -> None:
        super().__init__(
            f"Tenant AI quota suspended for institution {institution_id}",
            code="TENANT_QUOTA_SUSPENDED",
        )
        self.institution_id = institution_id
        self.reason = reason


class QuotaExceededError(QuotaEngineError):
    """Raised when an admission check rejects a request due to token or INR cap."""

    def __init__(
        self,
        message: str,
        *,
        limit_type: str,
        institution_id: uuid.UUID,
        usage_category: str,
        current_value: int | Decimal,
        requested_value: int | Decimal,
        limit_value: int | Decimal,
    ) -> None:
        super().__init__(message, code="QUOTA_EXCEEDED")
        self.limit_type = limit_type
        self.institution_id = institution_id
        self.usage_category = usage_category
        self.current_value = current_value
        self.requested_value = requested_value
        self.limit_value = limit_value


class IdempotencyConflictError(QuotaEngineError):
    """Raised when an idempotency_key is reused with mismatched parameters."""

    def __init__(
        self,
        message: str,
        *,
        institution_id: uuid.UUID,
        idempotency_key: str,
        mismatched_fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, code="IDEMPOTENCY_CONFLICT")
        self.institution_id = institution_id
        self.idempotency_key = idempotency_key
        self.mismatched_fields = mismatched_fields


class ReservationNotFoundError(QuotaEngineError):
    """Raised when the target reservation does not exist within the tenant scope."""

    def __init__(self, reservation_id: uuid.UUID, institution_id: uuid.UUID) -> None:
        super().__init__(
            f"Reservation {reservation_id} not found for institution {institution_id}",
            code="RESERVATION_NOT_FOUND",
        )
        self.reservation_id = reservation_id
        self.institution_id = institution_id


class AttemptNotFoundError(QuotaEngineError):
    """Raised when the target provider attempt does not exist under the reservation."""

    def __init__(self, attempt_id: uuid.UUID, reservation_id: uuid.UUID) -> None:
        super().__init__(
            f"Provider attempt {attempt_id} not found for reservation {reservation_id}",
            code="ATTEMPT_NOT_FOUND",
        )
        self.attempt_id = attempt_id
        self.reservation_id = reservation_id


class InvalidStateTransitionError(QuotaEngineError):
    """Raised when an invalid reservation or attempt state transition is attempted."""

    def __init__(
        self,
        message: str,
        *,
        current_state: str,
        target_state: str,
        entity_type: str = "reservation",
    ) -> None:
        super().__init__(message, code="INVALID_STATE_TRANSITION")
        self.current_state = current_state
        self.target_state = target_state
        self.entity_type = entity_type


class ReservationExpiredError(InvalidStateTransitionError):
    """Raised when dispatching a RESERVED reservation whose TTL has already elapsed."""

    def __init__(self, reservation_id: uuid.UUID) -> None:
        super().__init__(
            f"Pre-dispatch reservation {reservation_id} has expired and cannot be dispatched",
            current_state="RESERVED",
            target_state="DISPATCHED",
            entity_type="reservation",
        )
        self.code = "RESERVATION_EXPIRED"
        self.reservation_id = reservation_id


class MissingUsagePolicyPendingError(QuotaEngineError):
    """
    Raised when missing provider usage metadata invokes the unresolved Business Decision #4 policy.

    Stage 7.2 fails closed until stakeholders formally approve the exact settlement policy
    or a caller injects an approved MissingUsagePolicyResolver implementation.
    """

    def __init__(
        self,
        message: str,
        *,
        policy_name: str,
        reservation_id: uuid.UUID,
        attempt_id: uuid.UUID,
    ) -> None:
        super().__init__(message, code="MISSING_USAGE_POLICY_PENDING")
        self.policy_name = policy_name
        self.reservation_id = reservation_id
        self.attempt_id = attempt_id


class DatabaseContentionError(QuotaEngineError):
    """Raised when transient PostgreSQL lock/deadlock/serialization retries are exhausted."""

    def __init__(
        self,
        message: str,
        *,
        sqlstate: str | None,
        attempts: int,
    ) -> None:
        super().__init__(message, code="DATABASE_CONTENTION_EXHAUSTED")
        self.sqlstate = sqlstate
        self.attempts = attempts


class UncertainCommitRecoveryError(QuotaEngineError):
    """Raised when post-failure commit verification cannot resolve unambiguously."""

    def __init__(self, message: str, *, idempotency_key: str) -> None:
        super().__init__(message, code="UNCERTAIN_COMMIT_RECOVERY_ERROR")
        self.idempotency_key = idempotency_key


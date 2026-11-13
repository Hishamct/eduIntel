"""
Policy-neutral Missing-Usage Policy interface for Stage 7 Business Decision #4.

Stage 7 Business Decision #4 (tenant_ai_quotas.missing_usage_policy approved values and
settlement rules when a provider omits token counts) has NOT yet been approved.
This module isolates that decision behind a clean Protocol so Stage 7.2 core accounting
remains agnostic and fails closed by default without inventing unapproved behavior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.observability.quota.errors import MissingUsagePolicyPendingError


@dataclass(frozen=True, slots=True)
class MissingUsageContext:
    """Inputs passed to a MissingUsagePolicyResolver when provider usage metadata is absent."""

    institution_id: uuid.UUID
    reservation_id: uuid.UUID
    attempt_id: uuid.UUID
    policy_name: str
    attempt_status: str
    estimated_input_tokens: int
    reserved_output_tokens: int
    total_reserved_tokens: int


@dataclass(frozen=True, slots=True)
class MissingUsageResolution:
    """
    Directive returned by an approved MissingUsagePolicyResolver implementation.

    action:
      - 'UNKNOWN_USAGE': Hold conservative exposure on UNKNOWN_USAGE for later reconciliation.
      - 'SETTLE_TOKENS': Settle explicit fallback token counts approved by policy.
    """

    action: str
    settled_input_tokens: int | None = None
    settled_output_tokens: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.action not in ("UNKNOWN_USAGE", "SETTLE_TOKENS"):
            raise ValueError(f"Unsupported MissingUsageResolution action={self.action!r}")
        if self.action == "SETTLE_TOKENS":
            if self.settled_input_tokens is None or self.settled_output_tokens is None:
                raise ValueError("SETTLE_TOKENS requires settled_input_tokens and settled_output_tokens")


@runtime_checkable
class MissingUsagePolicyResolver(Protocol):
    """Strategy interface for resolving missing provider token metadata."""

    def resolve_missing_usage(self, context: MissingUsageContext) -> MissingUsageResolution:
        """Return a MissingUsageResolution or raise MissingUsagePolicyPendingError."""


class FailClosedMissingUsagePolicyResolver:
    """
    Default policy resolver used in Stage 7.2.

    Always refuses to fabricate missing usage policies and raises a structured
    MissingUsagePolicyPendingError until Business Decision #4 is ratified.
    """

    def resolve_missing_usage(self, context: MissingUsageContext) -> MissingUsageResolution:
        raise MissingUsagePolicyPendingError(
            "Provider usage metadata is missing and missing_usage_policy semantics "
            "(Stage 7 Business Decision #4) are awaiting stakeholder approval",
            policy_name=context.policy_name,
            reservation_id=context.reservation_id,
            attempt_id=context.attempt_id,
        )


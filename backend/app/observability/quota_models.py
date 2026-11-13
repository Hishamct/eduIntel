"""
backend/app/observability/quota_models.py

Stage 7.1 Database Foundation: SQLAlchemy Models for Tenant Token Quotas,
Multi-Attempt Provider Accounting, and FinOps Financial Reconciliation.

Architectural Invariants:
1. Canonical Lock Hierarchy (enforced in later service layer transactions):
   Level 1: TenantDailyAIUsage (tenant_daily_ai_usage)
   Level 2: TenantDailyCategoryUsage (tenant_daily_category_usage)
   Level 3: AITokenReservation (ai_token_reservations)
   Level 4: AIProviderAttempt (ai_provider_attempts, ordered by attempt_sequence ASC)
2. Financial Precision:
   All INR monetary columns strictly use fixed-point Decimal / NUMERIC(12|14, 4).
   Floating-point types are prohibited in financial accounting columns.
3. Reservation Lifecycle Statuses:
   Strictly RESERVED, DISPATCHED, COMMITTED, RELEASED, UNKNOWN_USAGE.
   Lease expiry uses dedicated recovery metadata columns rather than an EXPIRED status.
4. Immutability & Append-Only Enforcement:
   ai_pricing_versions, ai_pricing_activations, and ai_financial_adjustments are
   protected by least-privilege ACLs, RLS policies, and database triggers against
   UPDATE, DELETE, and TRUNCATE mutations.
5. No Unapproved Business Defaults:
   Policy limits, financial ceilings, and pricing schedules contain zero hardcoded
   unapproved business values and must be configured per tenant/version.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

VALID_RESERVATION_STATUSES = (
    "RESERVED",
    "DISPATCHED",
    "COMMITTED",
    "RELEASED",
    "UNKNOWN_USAGE",
)

VALID_USAGE_CATEGORIES = (
    "interactive_ai",
    "ingestion_embeddings",
    "other_metered",
)

VALID_RECOVERY_STATES = (
    "NONE",
    "SWEEPER_CLAIMED",
    "LEASE_EXPIRED_RECOVERED",
)

VALID_REVIEW_STATUSES = (
    "NONE",
    "NEEDS_MANUAL_REVIEW",
    "MANUALLY_SETTLED",
    "LATE_EVIDENCE_REVIEW_REQUIRED",
)

VALID_ATTEMPT_STATUSES = (
    "DISPATCHED",
    "SUCCEEDED",
    "FAILED_CONFIRMED",
    "TIMEOUT_UNCERTAIN",
    "MANUALLY_SETTLED",
)

VALID_ADJUSTMENT_TYPES = (
    "LATE_SETTLEMENT",
    "MANUAL_SETTLE",
    "VARIANCE_DEBIT",
    "VARIANCE_CREDIT",
    "REFUND",
)


class AIPricingVersion(Base):
    """
    Global immutable versioned pricing schedule.
    Not tenant-owned; readable by authenticated runtime roles and insert-only
    under platform-admin authorization. Existing pricing versions cannot be updated
    or deleted once created.
    `is_active` records immutable eligibility at creation time (true = eligible for
    runtime activation); active-version switching is tracked append-only via
    AIPricingActivation (`ai_pricing_activations`) without mutating historical rows.
    """

    __tablename__ = "ai_pricing_versions"

    version_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    usd_to_inr_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    rate_source: Mapped[str] = mapped_column(String(100), nullable=False)
    rates_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "is_active",
            name="uq_ai_pricing_versions_id_active",
        ),
        CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency)",
            name="ck_ai_pricing_versions_currency_iso",
        ),
        CheckConstraint(
            "usd_to_inr_rate > 0",
            name="ck_ai_pricing_versions_rate_pos",
        ),
        CheckConstraint(
            "char_length(btrim(version_id)) > 0",
            name="ck_ai_pricing_versions_version_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(rate_source)) > 0",
            name="ck_ai_pricing_versions_source_nonempty",
        ),
    )


class AIPricingActivation(Base):
    """
    Append-only global active pricing version selection ledger.
    Separates mutable active-version pointer transitions from immutable
    ai_pricing_versions records: switching active pricing inserts a new event row
    ordered by `activation_seq DESC`, preserving full audit history without UPDATEs.
    """

    __tablename__ = "ai_pricing_activations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    activation_seq: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        nullable=False,
    )
    pricing_version: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("ai_pricing_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    expected_version_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    activated_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    activation_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("activation_seq", name="uq_ai_pricing_activations_seq"),
        ForeignKeyConstraint(
            ["pricing_version", "expected_version_active"],
            ["ai_pricing_versions.version_id", "ai_pricing_versions.is_active"],
            ondelete="RESTRICT",
            name="fk_pricing_activation_eligible_version",
        ),
        # Global active-version lookup (`ORDER BY activation_seq DESC LIMIT 1`) uses
        # uq_ai_pricing_activations_seq directly via Index Scan Backward; this composite
        # index serves the pricing_version FK and version-filtered activation history.
        Index(
            "ix_ai_pricing_activations_version_seq",
            "pricing_version",
            "activation_seq",
        ),
        CheckConstraint(
            "activation_seq >= 1",
            name="ck_ai_pricing_activations_seq_pos",
        ),
        CheckConstraint(
            "expected_version_active = true",
            name="ck_ai_pricing_activations_must_be_active",
        ),
        CheckConstraint(
            "char_length(btrim(activated_by_actor)) > 0",
            name="ck_ai_pricing_activations_actor_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(activation_reason)) > 0",
            name="ck_ai_pricing_activations_reason_nonempty",
        ),
    )


class AIQuotaPlan(Base):
    """
    Subscription-aligned AI quota plan definition.
    Defines daily financial ceilings, risk reserve percentage, and separate token limits.
    Templates: Starter, Growth, Enterprise, Custom.
    """

    __tablename__ = "ai_quota_plans"

    plan_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    daily_financial_ceiling_inr: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    risk_reserve_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.1000"),
        server_default=text("0.1000"),
    )
    daily_interactive_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_ingestion_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_other_token_limit: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=50_000,
        server_default=text("50000"),
    )
    monthly_total_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_tokens_per_request: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=4096,
        server_default=text("4096"),
    )
    missing_usage_policy: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="HOLD_UNKNOWN",
        server_default=text("'HOLD_UNKNOWN'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint("char_length(btrim(plan_id)) > 0", name="ck_ai_quota_plans_id_nonempty"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_ai_quota_plans_name_nonempty"),
        CheckConstraint("daily_financial_ceiling_inr >= 0", name="ck_ai_quota_plans_ceiling_nonneg"),
        CheckConstraint(
            "risk_reserve_percent >= 0 AND risk_reserve_percent <= 1",
            name="ck_ai_quota_plans_reserve_pct",
        ),
        CheckConstraint("daily_interactive_token_limit >= 0", name="ck_ai_quota_plans_interactive_nonneg"),
        CheckConstraint("daily_ingestion_token_limit >= 0", name="ck_ai_quota_plans_ingestion_nonneg"),
        CheckConstraint("daily_other_token_limit >= 0", name="ck_ai_quota_plans_other_nonneg"),
        CheckConstraint(
            "monthly_total_token_limit IS NULL OR monthly_total_token_limit >= 0",
            name="ck_ai_quota_plans_monthly_nonneg",
        ),
        CheckConstraint("max_tokens_per_request > 0", name="ck_ai_quota_plans_max_tok_pos"),
    )


class TenantAIQuota(Base):
    """
    Per-institution configurable AI quota and financial exposure policy.
    Requires explicit policy configuration; does not embed unapproved production defaults.
    """

    __tablename__ = "tenant_ai_quotas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quota_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    daily_interactive_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_ingestion_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_other_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_total_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    daily_exposure_limit_inr: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    pending_reserve_cap_percent: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    risk_reserve_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    plan_id: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("ai_quota_plans.plan_id", ondelete="RESTRICT"),
        nullable=True,
    )
    max_tokens_per_request: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_usage_policy: Mapped[str] = mapped_column(String(40), nullable=False)
    is_unlimited: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_suspended: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier_name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("institution_id", name="uq_tenant_ai_quotas_institution_id"),
        CheckConstraint(
            "daily_interactive_token_limit >= 0",
            name="ck_tenant_ai_quotas_interactive_nonneg",
        ),
        CheckConstraint(
            "daily_ingestion_token_limit >= 0",
            name="ck_tenant_ai_quotas_ingestion_nonneg",
        ),
        CheckConstraint(
            "daily_other_token_limit >= 0",
            name="ck_tenant_ai_quotas_other_nonneg",
        ),
        CheckConstraint(
            "monthly_total_token_limit IS NULL OR monthly_total_token_limit >= 0",
            name="ck_tenant_ai_quotas_monthly_nonneg",
        ),
        CheckConstraint(
            "daily_exposure_limit_inr >= 0",
            name="ck_tenant_ai_quotas_exposure_nonneg",
        ),
        CheckConstraint(
            "pending_reserve_cap_percent >= 0 AND pending_reserve_cap_percent <= 1",
            name="ck_tenant_ai_quotas_reserve_pct_range",
        ),
        CheckConstraint(
            "max_tokens_per_request > 0",
            name="ck_tenant_ai_quotas_max_tokens_pos",
        ),
        CheckConstraint("char_length(btrim(quota_timezone)) > 0", name="ck_tenant_ai_quotas_tz_nonempty"),
        # NOTE (Stage 7.1R2 / R-03.4): Enumerating missing_usage_policy values at DB level
        # remains blocked pending stakeholder approval of Stage 7 Business Decision #4; only
        # trimmed non-empty enforcement is applied without inventing unapproved policy names.
        CheckConstraint(
            "char_length(btrim(missing_usage_policy)) > 0",
            name="ck_tenant_ai_quotas_missing_policy_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(tier_name)) > 0",
            name="ck_tenant_ai_quotas_tier_nonempty",
        ),
    )


class TenantDailyAIUsage(Base):
    """
    Lock Hierarchy Level 1: Parent daily financial exposure and token rollup row
    per (institution_id, usage_date). Serializes concurrent quota & cost admissions.
    """

    __tablename__ = "tenant_daily_ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    committed_cost_inr: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    pending_reserved_cost_inr: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    uncertain_exposure_cost_inr: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    committed_total_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    pending_reserved_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    uncertain_reserved_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    request_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    fallback_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    unknown_usage_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("institution_id", "usage_date", name="uq_tenant_daily_usage_date"),
        Index("ix_tenant_daily_ai_usage_date_inst", "usage_date", "institution_id"),
        CheckConstraint("committed_cost_inr >= 0", name="ck_tenant_daily_ai_usage_committed_cost_nonneg"),
        CheckConstraint("pending_reserved_cost_inr >= 0", name="ck_tenant_daily_ai_usage_pending_cost_nonneg"),
        CheckConstraint("uncertain_exposure_cost_inr >= 0", name="ck_tenant_daily_ai_usage_uncertain_cost_nonneg"),
        CheckConstraint("committed_total_tokens >= 0", name="ck_tenant_daily_ai_usage_committed_tokens_nonneg"),
        CheckConstraint("pending_reserved_tokens >= 0", name="ck_tenant_daily_ai_usage_pending_tokens_nonneg"),
        CheckConstraint("uncertain_reserved_tokens >= 0", name="ck_tenant_daily_ai_usage_uncertain_tokens_nonneg"),
        CheckConstraint("request_count >= 0", name="ck_tenant_daily_ai_usage_req_count_nonneg"),
        CheckConstraint("fallback_count >= 0", name="ck_tenant_daily_ai_usage_fallback_count_nonneg"),
        CheckConstraint("unknown_usage_count >= 0", name="ck_tenant_daily_ai_usage_unknown_count_nonneg"),
        CheckConstraint("version >= 1", name="ck_tenant_daily_ai_usage_version_pos"),
        CheckConstraint(
            "committed_total_tokens <= 100000000000000000 "
            "AND pending_reserved_tokens <= 100000000000000000 "
            "AND uncertain_reserved_tokens <= 100000000000000000",
            name="ck_tenant_daily_ai_usage_tok_bounds",
        ),
    )


class TenantDailyCategoryUsage(Base):
    """
    Lock Hierarchy Level 2: Per-category daily token ledger enforcing independent
    interactive, ingestion, and other metered quotas under the parent daily rollup.
    """

    __tablename__ = "tenant_daily_category_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    usage_category: Mapped[str] = mapped_column(String(40), nullable=False)
    committed_input_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    committed_output_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    committed_total_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    pending_reserved_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    uncertain_reserved_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    committed_cost_inr: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "usage_date"],
            ["tenant_daily_ai_usage.institution_id", "tenant_daily_ai_usage.usage_date"],
            ondelete="RESTRICT",
            name="fk_category_usage_daily_parent",
        ),
        UniqueConstraint(
            "institution_id",
            "usage_date",
            "usage_category",
            name="uq_tenant_daily_category_date",
        ),
        CheckConstraint(
            "usage_category IN ('interactive_ai', 'ingestion_embeddings', 'other_metered')",
            name="ck_tenant_daily_category_usage_category",
        ),
        CheckConstraint("committed_input_tokens >= 0", name="ck_tenant_daily_cat_committed_in_nonneg"),
        CheckConstraint("committed_output_tokens >= 0", name="ck_tenant_daily_cat_committed_out_nonneg"),
        CheckConstraint("committed_total_tokens >= 0", name="ck_tenant_daily_cat_committed_tot_nonneg"),
        CheckConstraint("pending_reserved_tokens >= 0", name="ck_tenant_daily_cat_pending_nonneg"),
        CheckConstraint("uncertain_reserved_tokens >= 0", name="ck_tenant_daily_cat_uncertain_nonneg"),
        CheckConstraint("committed_cost_inr >= 0", name="ck_tenant_daily_cat_cost_nonneg"),
        CheckConstraint(
            "committed_input_tokens <= 100000000000000000 "
            "AND committed_output_tokens <= 100000000000000000 "
            "AND committed_total_tokens <= 100000000000000000 "
            "AND pending_reserved_tokens <= 100000000000000000 "
            "AND uncertain_reserved_tokens <= 100000000000000000",
            name="ck_tenant_daily_cat_tok_bounds",
        ),
    )


class AITokenReservation(Base):
    """
    Lock Hierarchy Level 3: Logical AI operation reservation & dispatch ledger.
    Lifecycle statuses: RESERVED, DISPATCHED, COMMITTED, RELEASED, UNKNOWN_USAGE.
    Cross-row finalization and dispatch transition constraints are enforced at
    the service layer (Stage 7.2/7.3) under canonical locking.
    """

    __tablename__ = "ai_token_reservations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    logical_operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    usage_category: Mapped[str] = mapped_column(String(40), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="RESERVED",
        server_default=text("'RESERVED'"),
    )
    pricing_version: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("ai_pricing_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    estimated_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_reserved_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_cost_inr: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    actual_input_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    actual_output_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    actual_total_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    actual_cost_inr: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    uncertain_tokens_held: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    uncertain_cost_held_inr: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reconciliation_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    recovery_state: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="NONE",
        server_default=text("'NONE'"),
    )
    recovery_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sweeper_lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sweeper_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="NONE",
        server_default=text("'NONE'"),
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts: Mapped[list[AIProviderAttempt]] = relationship(
        "AIProviderAttempt",
        back_populates="reservation",
        primaryjoin="and_(AITokenReservation.institution_id == foreign(AIProviderAttempt.institution_id), "
        "AITokenReservation.id == foreign(AIProviderAttempt.reservation_id))",
        order_by="AIProviderAttempt.attempt_sequence",
        passive_deletes=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "usage_date", "usage_category"],
            [
                "tenant_daily_category_usage.institution_id",
                "tenant_daily_category_usage.usage_date",
                "tenant_daily_category_usage.usage_category",
            ],
            ondelete="RESTRICT",
            name="fk_reservation_category_parent",
        ),
        UniqueConstraint("institution_id", "id", name="uq_ai_token_reservations_inst_id"),
        Index(
            "uq_ai_reservations_idempotency",
            "institution_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_ai_reservations_recovery",
            "status",
            "expires_at",
            postgresql_where=text("status IN ('RESERVED', 'DISPATCHED')"),
        ),
        Index("ix_ai_reservations_inst_created", "institution_id", "created_at"),
        Index("ix_ai_reservations_logical_op", "institution_id", "logical_operation_id"),
        CheckConstraint(
            "status IN ('RESERVED', 'DISPATCHED', 'COMMITTED', 'RELEASED', 'UNKNOWN_USAGE')",
            name="ck_ai_token_reservations_status",
        ),
        CheckConstraint(
            "usage_category IN ('interactive_ai', 'ingestion_embeddings', 'other_metered')",
            name="ck_ai_token_reservations_category",
        ),
        CheckConstraint(
            "recovery_state IN ('NONE', 'SWEEPER_CLAIMED', 'LEASE_EXPIRED_RECOVERED')",
            name="ck_ai_token_reservations_recovery_state",
        ),
        CheckConstraint(
            "review_status IN ('NONE', 'NEEDS_MANUAL_REVIEW', 'MANUALLY_SETTLED', 'LATE_EVIDENCE_REVIEW_REQUIRED')",
            name="ck_ai_token_reservations_review_status",
        ),
        CheckConstraint(
            "status NOT IN ('DISPATCHED', 'COMMITTED', 'UNKNOWN_USAGE') OR dispatched_at IS NOT NULL",
            name="ck_ai_token_reservations_dispatched_ts",
        ),
        CheckConstraint(
            "status <> 'RESERVED' OR dispatched_at IS NULL",
            name="ck_ai_token_reservations_reserved_no_dispatch",
        ),
        # Exception note: RELEASED may occur from RESERVED (dispatched_at IS NULL) or from
        # UNKNOWN_USAGE after operator manual zero-charge settlement (dispatched_at IS NOT NULL).
        # UNKNOWN_USAGE is an unsettled in-progress hold state and must have reconciled_at IS NULL.
        CheckConstraint(
            "(status NOT IN ('COMMITTED', 'RELEASED') OR reconciled_at IS NOT NULL) "
            "AND (status NOT IN ('RESERVED', 'DISPATCHED', 'UNKNOWN_USAGE') OR reconciled_at IS NULL)",
            name="ck_ai_token_reservations_reconciled_ts",
        ),
        CheckConstraint(
            "expires_at >= created_at",
            name="ck_ai_token_reservations_expires_after_created",
        ),
        CheckConstraint(
            "dispatched_at IS NULL OR reconciled_at IS NULL OR reconciled_at >= dispatched_at",
            name="ck_ai_token_reservations_reconciled_after_dispatch",
        ),
        CheckConstraint("estimated_input_tokens >= 0", name="ck_ai_res_est_in_nonneg"),
        CheckConstraint("reserved_output_tokens >= 0", name="ck_ai_res_res_out_nonneg"),
        CheckConstraint("total_reserved_tokens >= 0", name="ck_ai_res_tot_res_nonneg"),
        CheckConstraint(
            "estimated_input_tokens <= 1000000000000000 AND reserved_output_tokens <= 1000000000000000",
            name="ck_ai_res_reserved_bounds",
        ),
        CheckConstraint(
            "total_reserved_tokens = estimated_input_tokens + reserved_output_tokens",
            name="ck_ai_res_tot_res_sum",
        ),
        CheckConstraint("reserved_cost_inr >= 0", name="ck_ai_res_cost_nonneg"),
        CheckConstraint("actual_input_tokens >= 0", name="ck_ai_res_act_in_nonneg"),
        CheckConstraint("actual_output_tokens >= 0", name="ck_ai_res_act_out_nonneg"),
        CheckConstraint("actual_total_tokens >= 0", name="ck_ai_res_act_tot_nonneg"),
        CheckConstraint(
            "actual_input_tokens <= 1000000000000000 AND actual_output_tokens <= 1000000000000000",
            name="ck_ai_res_actual_bounds",
        ),
        CheckConstraint(
            "actual_total_tokens = actual_input_tokens + actual_output_tokens",
            name="ck_ai_res_act_tot_sum",
        ),
        CheckConstraint("actual_cost_inr >= 0", name="ck_ai_res_act_cost_nonneg"),
        CheckConstraint("uncertain_tokens_held >= 0", name="ck_ai_res_unc_tok_nonneg"),
        CheckConstraint("uncertain_tokens_held <= 2000000000000000", name="ck_ai_res_unc_tok_bounds"),
        CheckConstraint("uncertain_cost_held_inr >= 0", name="ck_ai_res_unc_cost_nonneg"),
        CheckConstraint("reconciliation_version >= 1", name="ck_ai_res_rec_ver_pos"),
        CheckConstraint(
            "char_length(btrim(endpoint)) > 0",
            name="ck_ai_res_endpoint_nonempty",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR char_length(btrim(idempotency_key)) > 0",
            name="ck_ai_res_idem_key_nonempty",
        ),
    )


class AIProviderAttempt(Base):
    """
    Lock Hierarchy Level 4: Individual external provider attempt linked to a
    logical reservation. Ordered by attempt_sequence ASC during locking.
    Preserves manual settlement snapshots and late vendor evidence separately.
    """

    __tablename__ = "ai_provider_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    logical_operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    is_fallback: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_retry: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="DISPATCHED",
        server_default=text("'DISPATCHED'"),
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pricing_version: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("ai_pricing_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    estimated_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_cost_inr: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    manual_settled_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    manual_settled_cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    manual_settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    late_reported_input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    late_reported_output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    late_reported_cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    late_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_classification: Mapped[str | None] = mapped_column(String(60), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reservation: Mapped[AITokenReservation] = relationship(
        "AITokenReservation",
        back_populates="attempts",
        primaryjoin="and_(AITokenReservation.institution_id == foreign(AIProviderAttempt.institution_id), "
        "AITokenReservation.id == foreign(AIProviderAttempt.reservation_id))",
        overlaps="attempts",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "reservation_id"],
            ["ai_token_reservations.institution_id", "ai_token_reservations.id"],
            ondelete="RESTRICT",
            name="fk_attempt_reservation_tenant",
        ),
        UniqueConstraint("institution_id", "id", name="uq_ai_provider_attempts_inst_id"),
        UniqueConstraint(
            "institution_id",
            "reservation_id",
            "id",
            name="uq_ai_provider_attempts_inst_res_id",
        ),
        UniqueConstraint("reservation_id", "attempt_sequence", name="uq_ai_attempt_seq"),
        Index(
            "uq_ai_attempt_provider_req_id",
            "institution_id",
            "provider",
            "provider_request_id",
            unique=True,
            postgresql_where=text("provider_request_id IS NOT NULL"),
        ),
        Index("ix_ai_attempts_inst_dispatched", "institution_id", "dispatched_at"),
        CheckConstraint("attempt_sequence >= 1", name="ck_ai_provider_attempts_seq_pos"),
        CheckConstraint(
            "status IN ('DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED', 'TIMEOUT_UNCERTAIN', 'MANUALLY_SETTLED')",
            name="ck_ai_provider_attempts_status",
        ),
        CheckConstraint("char_length(btrim(provider)) > 0", name="ck_ai_att_provider_nonempty"),
        CheckConstraint("char_length(btrim(model)) > 0", name="ck_ai_att_model_nonempty"),
        CheckConstraint(
            "provider_request_id IS NULL OR char_length(btrim(provider_request_id)) > 0",
            name="ck_ai_att_provider_req_id_nonempty",
        ),
        CheckConstraint("estimated_tokens >= 0", name="ck_ai_att_est_tok_nonneg"),
        CheckConstraint("estimated_tokens <= 2000000000000000", name="ck_ai_att_est_tok_bounds"),
        CheckConstraint("estimated_cost_inr >= 0", name="ck_ai_att_est_cost_nonneg"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_att_in_tok_nonneg"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens <= 1000000000000000",
            name="ck_ai_att_in_tok_bounds",
        ),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_att_out_tok_nonneg"),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens <= 1000000000000000",
            name="ck_ai_att_out_tok_bounds",
        ),
        CheckConstraint("actual_cost_inr IS NULL OR actual_cost_inr >= 0", name="ck_ai_att_act_cost_nonneg"),
        CheckConstraint(
            "manual_settled_tokens IS NULL OR manual_settled_tokens >= 0",
            name="ck_ai_att_man_tok_nonneg",
        ),
        CheckConstraint(
            "manual_settled_tokens IS NULL OR manual_settled_tokens <= 2000000000000000",
            name="ck_ai_att_man_tok_bounds",
        ),
        CheckConstraint(
            "manual_settled_cost_inr IS NULL OR manual_settled_cost_inr >= 0",
            name="ck_ai_att_man_cost_nonneg",
        ),
        CheckConstraint(
            "late_reported_input_tokens IS NULL OR late_reported_input_tokens >= 0",
            name="ck_ai_att_late_in_nonneg",
        ),
        CheckConstraint(
            "late_reported_input_tokens IS NULL OR late_reported_input_tokens <= 1000000000000000",
            name="ck_ai_att_late_in_bounds",
        ),
        CheckConstraint(
            "late_reported_output_tokens IS NULL OR late_reported_output_tokens >= 0",
            name="ck_ai_att_late_out_nonneg",
        ),
        CheckConstraint(
            "late_reported_output_tokens IS NULL OR late_reported_output_tokens <= 1000000000000000",
            name="ck_ai_att_late_out_bounds",
        ),
        CheckConstraint(
            "late_reported_cost_inr IS NULL OR late_reported_cost_inr >= 0",
            name="ck_ai_att_late_cost_nonneg",
        ),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_ai_att_latency_nonneg"),
    )


class AIFinancialAdjustment(Base):
    """
    Append-only FinOps adjustment audit ledger.
    Protected by SQL ACLs (SELECT/INSERT only), RLS UPDATE/DELETE DENY policies,
    and database immutability triggers. Records manual settlements, late settlements,
    and true-up credit/debit variances without altering historical records.
    """

    __tablename__ = "ai_financial_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    adjusted_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    token_delta: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    cost_inr_delta: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )
    adjustment_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "reservation_id"],
            ["ai_token_reservations.institution_id", "ai_token_reservations.id"],
            ondelete="RESTRICT",
            name="fk_adjustment_reservation_tenant",
        ),
        ForeignKeyConstraint(
            ["institution_id", "reservation_id", "attempt_id"],
            [
                "ai_provider_attempts.institution_id",
                "ai_provider_attempts.reservation_id",
                "ai_provider_attempts.id",
            ],
            ondelete="RESTRICT",
            name="fk_adjustment_res_attempt_tenant",
        ),
        CheckConstraint(
            "attempt_id IS NULL OR reservation_id IS NOT NULL",
            name="ck_ai_financial_adjustments_attempt_requires_res",
        ),
        Index("ix_ai_financial_adjustments_inst_created", "institution_id", "created_at"),
        Index(
            "ix_ai_financial_adjustments_reservation",
            "reservation_id",
            postgresql_where=text("reservation_id IS NOT NULL"),
        ),
        CheckConstraint(
            "adjustment_type IN ('LATE_SETTLEMENT', 'MANUAL_SETTLE', 'VARIANCE_DEBIT', 'VARIANCE_CREDIT', 'REFUND')",
            name="ck_ai_financial_adjustments_type",
        ),
        CheckConstraint(
            "char_length(btrim(notes)) > 0",
            name="ck_ai_financial_adjustments_notes_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(adjustment_reason)) > 0",
            name="ck_ai_financial_adjustments_reason_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(adjusted_by_actor)) > 0",
            name="ck_ai_financial_adjustments_actor_nonempty",
        ),
        CheckConstraint(
            "token_delta >= -2000000000000000 AND token_delta <= 2000000000000000",
            name="ck_ai_financial_adjustments_token_delta_bounds",
        ),
    )


class TenantQuotaProvisioningLog(Base):
    """
    Append-only audit log for tenant AI quota provisioning and plan transitions.
    Protected by PostgreSQL RLS and immutability triggers (INSERT/SELECT only).
    """

    __tablename__ = "tenant_quota_provisioning_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    changed_by_actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_plan_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    new_plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    change_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_quota_provisioning_logs_inst_created", "institution_id", "created_at"),
        CheckConstraint("char_length(btrim(changed_by_actor)) > 0", name="ck_quota_prov_actor_nonempty"),
        CheckConstraint("char_length(btrim(action)) > 0", name="ck_quota_prov_action_nonempty"),
        CheckConstraint("char_length(btrim(change_reason)) > 0", name="ck_quota_prov_reason_nonempty"),
    )


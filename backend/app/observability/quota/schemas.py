"""
backend/app/observability/quota/schemas.py

Pydantic v2 schemas for Stage 7.4 FinOps and Quota Administration APIs.
Enforces strict type safety, Decimal arithmetic representation, and extra="forbid".
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FinOpsBaseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# -----------------------------------------------------------------------------
# Plan & Provisioning Schemas
# -----------------------------------------------------------------------------


class QuotaPlanResponse(FinOpsBaseSchema):
    plan_id: str
    name: str
    description: str
    daily_financial_ceiling_inr: Decimal
    risk_reserve_percent: Decimal
    daily_interactive_token_limit: int
    daily_ingestion_token_limit: int
    daily_other_token_limit: int
    monthly_total_token_limit: int | None
    max_tokens_per_request: int
    missing_usage_policy: str
    is_active: bool


class QuotaPlanUpsertRequest(FinOpsBaseSchema):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    daily_financial_ceiling_inr: Decimal = Field(..., ge=0)
    risk_reserve_percent: Decimal = Field(default=Decimal("0.1000"), ge=0, le=1)
    daily_interactive_token_limit: int = Field(default=750_000, ge=0)
    daily_ingestion_token_limit: int = Field(default=500_000, ge=0)
    daily_other_token_limit: int = Field(default=250_000, ge=0)
    monthly_total_token_limit: int | None = Field(default=None, ge=0)
    max_tokens_per_request: int = Field(default=16384, gt=0)
    is_active: bool = True


class TenantQuotaProvisionRequest(FinOpsBaseSchema):
    plan_id: str = Field(..., min_length=1, max_length=50)
    change_reason: str = Field(..., min_length=1, max_length=255)
    custom_financial_ceiling_inr: Decimal | None = Field(default=None, ge=0)
    custom_risk_reserve_percent: Decimal | None = Field(default=None, ge=0, le=1)
    custom_interactive_tokens: int | None = Field(default=None, ge=0)
    custom_ingestion_tokens: int | None = Field(default=None, ge=0)
    custom_other_tokens: int | None = Field(default=None, ge=0)
    custom_monthly_tokens: int | None = Field(default=None, ge=0)


class TenantQuotaSuspendRequest(FinOpsBaseSchema):
    reason: str = Field(..., min_length=1, max_length=255)


# -----------------------------------------------------------------------------
# Reporting & Overview Schemas
# -----------------------------------------------------------------------------


class CategoryUsageSummary(FinOpsBaseSchema):
    category: str
    committed_tokens: int
    pending_reserved_tokens: int
    uncertain_reserved_tokens: int
    limit_tokens: int
    percent_used: float
    remaining_tokens: int


class FinancialOverview(FinOpsBaseSchema):
    daily_ceiling_inr: str
    confirmed_cost_inr: str
    pending_reserved_cost_inr: str
    uncertain_exposure_cost_inr: str
    total_reserved_exposure_inr: str
    risk_reserve_percent: str
    risk_reserve_inr: str
    total_projected_exposure_inr: str
    available_admission_capacity_inr: str
    percent_capacity_utilized: float


class TokensTodaySummary(FinOpsBaseSchema):
    total_committed_tokens: int
    request_count: int
    fallback_count: int
    unknown_usage_count: int


class MonthlyUsageSummary(FinOpsBaseSchema):
    month_start: str
    monthly_token_limit: int | None
    monthly_tokens_used: int
    monthly_cost_inr: str
    percent_used: float | None


class ExceptionsSummary(FinOpsBaseSchema):
    outstanding_reservations_count: int
    unknown_usage_reservations_count: int


class TenantOverviewResponse(FinOpsBaseSchema):
    configured: bool
    institution_id: str
    quota_timezone: str | None = None
    usage_date: str | None = None
    tier_name: str | None = None
    plan_id: str | None = None
    is_suspended: bool | None = None
    suspension_reason: str | None = None
    financial: FinancialOverview | None = None
    tokens_today: TokensTodaySummary | None = None
    categories: dict[str, CategoryUsageSummary] | None = None
    monthly: MonthlyUsageSummary | None = None
    exceptions: ExceptionsSummary | None = None
    detail: str | None = None


class DailySeriesItem(FinOpsBaseSchema):
    usage_date: str
    committed_cost_inr: str
    pending_reserved_cost_inr: str
    uncertain_exposure_cost_inr: str
    committed_total_tokens: int
    request_count: int
    fallback_count: int
    unknown_usage_count: int


class CategoryBreakdownItem(FinOpsBaseSchema):
    usage_category: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_inr: str


class ProviderBreakdownItem(FinOpsBaseSchema):
    provider: str
    model: str
    attempt_count: int
    succeeded_count: int
    fallback_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    actual_cost_inr: str
    avg_latency_ms: float


class ReservationListItem(FinOpsBaseSchema):
    id: str
    usage_date: str
    usage_category: str
    endpoint: str
    status: str
    total_reserved_tokens: int
    reserved_cost_inr: str
    actual_total_tokens: int
    actual_cost_inr: str
    uncertain_tokens_held: int
    uncertain_cost_held_inr: str
    review_status: str
    recovery_state: str
    recovery_reason: str | None
    created_at: str
    expires_at: str
    reconciled_at: str | None


class AdjustmentListItem(FinOpsBaseSchema):
    id: str
    reservation_id: str | None
    attempt_id: str | None
    adjusted_by_actor: str
    adjustment_type: str
    token_delta: int
    cost_inr_delta: str
    adjustment_reason: str
    notes: str
    created_at: str


# -----------------------------------------------------------------------------
# Platform-Admin Schemas
# -----------------------------------------------------------------------------


class PlatformOverviewResponse(FinOpsBaseSchema):
    timestamp: str
    institutions_configured_count: int
    today: dict[str, Any]
    current_month: dict[str, Any]
    reconciliation_backlog: dict[str, Any]


class PlatformInstitutionListItem(FinOpsBaseSchema):
    institution_id: str
    name: str
    slug: str
    is_active: bool
    is_configured: bool
    plan_id: str | None
    tier_name: str | None
    daily_ceiling_inr: str
    today_confirmed_cost_inr: str
    today_exposure_inr: str
    utilization_percent: float
    is_suspended: bool


class ReconciliationBacklogItem(FinOpsBaseSchema):
    id: str
    institution_id: str
    usage_date: str
    usage_category: str
    endpoint: str
    status: str
    total_reserved_tokens: int
    reserved_cost_inr: str
    uncertain_tokens_held: int
    uncertain_cost_held_inr: str
    review_status: str
    recovery_state: str
    recovery_reason: str | None
    created_at: str
    dispatched_at: str | None
    expires_at: str


class ManualSettlementRequest(FinOpsBaseSchema):
    institution_id: uuid.UUID
    reservation_id: uuid.UUID
    attempt_id: uuid.UUID | None = None
    settled_input_tokens: int = Field(..., ge=0)
    settled_output_tokens: int = Field(..., ge=0)
    settled_cost_inr: Decimal = Field(..., ge=0)
    settlement_reason: str = Field(..., min_length=1, max_length=100)
    notes: str = Field(..., min_length=1)


class SweepTriggerResponse(FinOpsBaseSchema):
    timestamp: str
    swept_expired_reservations: int
    swept_stale_dispatched: int
    errors: list[str]
    expired_reservations_released: int | None = None
    stale_dispatched_marked_unknown: int | None = None


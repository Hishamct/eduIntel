"""
backend/app/observability/quota/router.py

Secure Administrative APIs for FinOps, Tenant Quota Administration,
Reconciliation, and Observability (Stage 7.4).
Provides strictly isolated institution-admin routes and verified platform-admin routes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import (
    TenantContext,
    get_platform_admin_db,
    get_tenant_db,
    require_tenant_role,
)
from app.observability.quota.engine import TenantQuotaEngine
from app.observability.quota.pricing import (
    resolve_active_pricing_version,
)
from app.observability.quota.provisioning import (
    InstitutionNotFoundError,
    QuotaPlanInactiveError,
    QuotaPlanNotFoundError,
    QuotaProvisioningService,
)
from app.observability.quota.reporting import FinOpsReportingService
from app.observability.quota.schemas import (
    CategoryBreakdownItem,
    DailySeriesItem,
    ManualSettlementRequest,
    PlatformOverviewResponse,
    ProviderBreakdownItem,
    QuotaPlanResponse,
    QuotaPlanUpsertRequest,
    SweepTriggerResponse,
    TenantOverviewResponse,
    TenantQuotaProvisionRequest,
    TenantQuotaSuspendRequest,
)
from app.observability.quota.sweeper import QuotaReconciliationSweeper
from app.observability.quota_models import (
    AIPricingActivation,
    AIPricingVersion,
)
from app.users.dependencies import require_platform_admin, require_role
from app.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["finops"])


# =============================================================================
# Institution-Admin Endpoints (Scoped to Caller Tenant via get_tenant_db)
# =============================================================================


@router.get("/finops/overview", response_model=TenantOverviewResponse)
async def get_institution_finops_overview(
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, Any]:
    """
    Returns today's comprehensive FinOps metrics for the caller's institution:
    quota plan, confirmed cost, pending exposure, risk reserve, and token limits.
    """
    return await FinOpsReportingService.get_tenant_overview(
        db, institution_id=tenant.institution_id
    )


@router.get("/finops/daily", response_model=list[DailySeriesItem])
async def get_institution_daily_series(
    start_date: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict[str, Any]]:
    """Returns daily usage time series over a date range (defaults to last 30 days)."""
    today = datetime.now(UTC).date()
    effective_end = end_date or today
    effective_start = start_date or (effective_end - timedelta(days=30))

    if effective_start > effective_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date.",
        )

    return await FinOpsReportingService.get_tenant_daily_series(
        db,
        institution_id=tenant.institution_id,
        start_date=effective_start,
        end_date=effective_end,
    )


@router.get("/finops/by-category", response_model=list[CategoryBreakdownItem])
async def get_institution_category_breakdown(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict[str, Any]]:
    """Returns token and cost aggregations by category (interactive_ai, ingestion, other)."""
    today = datetime.now(UTC).date()
    effective_end = end_date or today
    effective_start = start_date or (effective_end - timedelta(days=30))

    return await FinOpsReportingService.get_tenant_category_breakdown(
        db,
        institution_id=tenant.institution_id,
        start_date=effective_start,
        end_date=effective_end,
    )


@router.get("/finops/by-provider", response_model=list[ProviderBreakdownItem])
async def get_institution_provider_breakdown(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict[str, Any]]:
    """Returns token and cost aggregations by provider and model."""
    today = datetime.now(UTC).date()
    effective_end = end_date or today
    effective_start = start_date or (effective_end - timedelta(days=30))

    return await FinOpsReportingService.get_tenant_provider_breakdown(
        db,
        institution_id=tenant.institution_id,
        start_date=effective_start,
        end_date=effective_end,
    )


@router.get("/finops/reservations", response_model=dict[str, Any])
async def get_institution_reservations(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, Any]:
    """Returns paginated list of reservations for the caller's institution."""
    return await FinOpsReportingService.get_tenant_reservations(
        db,
        institution_id=tenant.institution_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/finops/adjustments", response_model=dict[str, Any])
async def get_institution_adjustments(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, Any]:
    """Returns paginated list of financial adjustments for the caller's institution."""
    return await FinOpsReportingService.get_tenant_adjustments(
        db,
        institution_id=tenant.institution_id,
        limit=limit,
        offset=offset,
    )


# =============================================================================
# Platform-Admin Endpoints (Privileged Cross-Tenant via get_platform_admin_db)
# =============================================================================


@router.get("/platform-admin/finops/overview", response_model=PlatformOverviewResponse)
async def get_platform_finops_overview(
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """Returns platform-wide aggregate financial spend, token usage, and backlog counts."""
    return await FinOpsReportingService.get_platform_overview(db)


@router.get("/platform-admin/finops/institutions", response_model=dict[str, Any])
async def list_platform_institutions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """Lists institutions with their quota plans, today's spend, and utilization %."""
    return await FinOpsReportingService.get_platform_institutions(
        db, limit=limit, offset=offset
    )


@router.get("/platform-admin/finops/plans", response_model=list[QuotaPlanResponse])
async def list_quota_plans(
    include_inactive: bool = Query(default=False),
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> list[Any]:
    """Lists all available AI Quota Plan templates."""
    plans = await QuotaProvisioningService.list_plans(db, include_inactive=include_inactive)
    return [
        QuotaPlanResponse(
            plan_id=p.plan_id,
            name=p.name,
            description=p.description,
            daily_financial_ceiling_inr=p.daily_financial_ceiling_inr,
            risk_reserve_percent=p.risk_reserve_percent,
            daily_interactive_token_limit=p.daily_interactive_token_limit,
            daily_ingestion_token_limit=p.daily_ingestion_token_limit,
            daily_other_token_limit=p.daily_other_token_limit,
            monthly_total_token_limit=p.monthly_total_token_limit,
            max_tokens_per_request=p.max_tokens_per_request,
            missing_usage_policy=p.missing_usage_policy,
            is_active=p.is_active,
        )
        for p in plans
    ]


@router.post("/platform-admin/finops/plans/{plan_id}", response_model=QuotaPlanResponse)
async def upsert_quota_plan(
    plan_id: str,
    payload: QuotaPlanUpsertRequest,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> QuotaPlanResponse:
    """Creates or updates a custom AI Quota Plan template."""
    plan = await QuotaProvisioningService.upsert_custom_plan(
        db,
        plan_id=plan_id,
        name=payload.name,
        description=payload.description,
        daily_financial_ceiling_inr=payload.daily_financial_ceiling_inr,
        risk_reserve_percent=payload.risk_reserve_percent,
        daily_interactive_token_limit=payload.daily_interactive_token_limit,
        daily_ingestion_token_limit=payload.daily_ingestion_token_limit,
        daily_other_token_limit=payload.daily_other_token_limit,
        monthly_total_token_limit=payload.monthly_total_token_limit,
        max_tokens_per_request=payload.max_tokens_per_request,
        is_active=payload.is_active,
    )
    return QuotaPlanResponse(
        plan_id=plan.plan_id,
        name=plan.name,
        description=plan.description,
        daily_financial_ceiling_inr=plan.daily_financial_ceiling_inr,
        risk_reserve_percent=plan.risk_reserve_percent,
        daily_interactive_token_limit=plan.daily_interactive_token_limit,
        daily_ingestion_token_limit=plan.daily_ingestion_token_limit,
        daily_other_token_limit=plan.daily_other_token_limit,
        monthly_total_token_limit=plan.monthly_total_token_limit,
        max_tokens_per_request=plan.max_tokens_per_request,
        missing_usage_policy=plan.missing_usage_policy,
        is_active=plan.is_active,
    )


@router.post(
    "/platform-admin/finops/institutions/{institution_id}/provision",
    status_code=status.HTTP_200_OK,
)
async def provision_institution_quota(
    institution_id: uuid.UUID,
    payload: TenantQuotaProvisionRequest,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """
    Explicit platform-admin operation to assign or update a tenant's AI Quota.
    Validates plan, configures financial & token ceilings, and logs audit record.
    """
    try:
        quota = await QuotaProvisioningService.provision_tenant_quota(
            db,
            institution_id=institution_id,
            plan_id=payload.plan_id,
            actor=current_admin.email or f"admin-{current_admin.id}",
            change_reason=payload.change_reason,
            custom_financial_ceiling_inr=payload.custom_financial_ceiling_inr,
            custom_risk_reserve_percent=payload.custom_risk_reserve_percent,
            custom_interactive_tokens=payload.custom_interactive_tokens,
            custom_ingestion_tokens=payload.custom_ingestion_tokens,
            custom_other_tokens=payload.custom_other_tokens,
            custom_monthly_tokens=payload.custom_monthly_tokens,
        )
        return {
            "success": True,
            "institution_id": str(institution_id),
            "plan_id": quota.plan_id,
            "tier_name": quota.tier_name,
            "daily_ceiling_inr": str(quota.daily_exposure_limit_inr),
            "risk_reserve_percent": str(quota.risk_reserve_percent),
            "daily_interactive_token_limit": quota.daily_interactive_token_limit,
            "daily_ingestion_token_limit": quota.daily_ingestion_token_limit,
        }
    except (QuotaPlanNotFoundError, QuotaPlanInactiveError, InstitutionNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve)) from ve


@router.post("/platform-admin/finops/institutions/{institution_id}/suspend")
async def suspend_institution_quota(
    institution_id: uuid.UUID,
    payload: TenantQuotaSuspendRequest,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """Suspends AI access for an institution while preserving all accounting ledgers."""
    try:
        quota = await QuotaProvisioningService.suspend_tenant_quota(
            db,
            institution_id=institution_id,
            actor=current_admin.email or f"admin-{current_admin.id}",
            reason=payload.reason,
        )
        return {
            "success": True,
            "institution_id": str(institution_id),
            "is_suspended": quota.is_suspended,
            "suspension_reason": quota.suspension_reason,
        }
    except InstitutionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/platform-admin/finops/institutions/{institution_id}/resume")
async def resume_institution_quota(
    institution_id: uuid.UUID,
    payload: TenantQuotaSuspendRequest,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """Resumes suspended AI access for an institution."""
    try:
        quota = await QuotaProvisioningService.resume_tenant_quota(
            db,
            institution_id=institution_id,
            actor=current_admin.email or f"admin-{current_admin.id}",
            reason=payload.reason,
        )
        return {
            "success": True,
            "institution_id": str(institution_id),
            "is_suspended": quota.is_suspended,
        }
    except InstitutionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/platform-admin/finops/reconciliation-backlog", response_model=dict[str, Any])
async def get_reconciliation_backlog(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """Lists reservations requiring operator investigation (UNKNOWN_USAGE, expired, or review needed)."""
    return await FinOpsReportingService.get_reconciliation_backlog(
        db, limit=limit, offset=offset
    )


@router.post("/platform-admin/finops/reconciliation/manual-settle")
async def manual_settle_reservation(
    payload: ManualSettlementRequest,
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """
    Authorizes manual settlement for an UNKNOWN_USAGE reservation.
    Creates an immutable AIFinancialAdjustment record and reconciles ledgers.
    """
    engine = TenantQuotaEngine()
    try:
        recon = await engine.manual_settle_unknown_usage(
            institution_id=payload.institution_id,
            reservation_id=payload.reservation_id,
            attempt_id=payload.attempt_id,
            settled_tokens=payload.settled_input_tokens + payload.settled_output_tokens,
            settled_input_tokens=payload.settled_input_tokens,
            settled_output_tokens=payload.settled_output_tokens,
            settled_cost_inr=payload.settled_cost_inr,
            actor=current_admin.email or f"admin-{current_admin.id}",
            reason=payload.settlement_reason,
            notes=payload.notes,
            db=db,
        )
        return {
            "success": True,
            "reservation_id": str(recon.reservation.id),
            "status": recon.reservation.status,
            "review_status": recon.reservation.review_status,
            "actual_total_tokens": recon.reservation.actual_total_tokens,
            "actual_cost_inr": str(recon.reservation.actual_cost_inr),
            "variance_cost_inr": str(recon.adjustment.cost_inr_delta if recon.adjustment else Decimal("0.0000")),
        }
    except Exception as e:
        logger.error("[Manual Settlement Error] %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/platform-admin/finops/reconciliation/sweep", response_model=SweepTriggerResponse)
async def trigger_reconciliation_sweep(
    batch_size: int = Query(default=50, ge=1, le=200),
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> SweepTriggerResponse:
    """Triggers an on-demand reconciliation sweep pass for expired & stale reservations."""
    sweeper = QuotaReconciliationSweeper(
        session_factory=db,
        worker_id=f"admin-sweep-{current_admin.id}",
    )
    result = await sweeper.run_sweep_batch(batch_size=batch_size)
    return SweepTriggerResponse(
        timestamp=result.timestamp,
        swept_expired_reservations=result.swept_expired_reservations,
        swept_stale_dispatched=result.swept_stale_dispatched,
        expired_reservations_released=result.swept_expired_reservations,
        stale_dispatched_marked_unknown=result.swept_stale_dispatched,
        errors=result.errors,
    )


@router.get("/platform-admin/finops/adjustments", response_model=dict[str, Any])
async def list_all_adjustments(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """Lists financial adjustments audit log across all institutions."""
    from app.observability.quota_models import AIFinancialAdjustment

    adj_stmt = (
        select(AIFinancialAdjustment)
        .order_by(AIFinancialAdjustment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    total_stmt = select(func.count(AIFinancialAdjustment.id))

    total = int((await db.execute(total_stmt)).scalar_one() or 0)
    rows = (await db.execute(adj_stmt)).scalars().all()

    items = [
        {
            "id": str(r.id),
            "institution_id": str(r.institution_id),
            "reservation_id": str(r.reservation_id) if r.reservation_id else None,
            "attempt_id": str(r.attempt_id) if r.attempt_id else None,
            "adjusted_by_actor": r.adjusted_by_actor,
            "adjustment_type": r.adjustment_type,
            "token_delta": r.token_delta,
            "cost_inr_delta": str(r.cost_inr_delta),
            "adjustment_reason": r.adjustment_reason,
            "notes": r.notes,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/platform-admin/finops/pricing")
async def get_pricing_overview(
    current_admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_platform_admin_db),
) -> dict[str, Any]:
    """Returns active pricing version and activation history."""
    active_version = await resolve_active_pricing_version(db)

    # List recent activations
    act_stmt = (
        select(AIPricingActivation)
        .order_by(AIPricingActivation.activation_seq.desc())
        .limit(10)
    )
    acts = (await db.execute(act_stmt)).scalars().all()

    # List available pricing versions
    ver_stmt = (
        select(AIPricingVersion)
        .order_by(AIPricingVersion.effective_from.desc())
        .limit(10)
    )
    vers = (await db.execute(ver_stmt)).scalars().all()

    return {
        "active_pricing_version": active_version.version_id,
        "active_rates": active_version.rates_json,
        "currency": active_version.currency,
        "usd_to_inr_rate": str(active_version.usd_to_inr_rate),
        "recent_activations": [
            {
                "activation_seq": a.activation_seq,
                "pricing_version": a.pricing_version,
                "activated_by_actor": a.activated_by_actor,
                "activation_reason": a.activation_reason,
                "activated_at": a.activated_at.isoformat(),
            }
            for a in acts
        ],
        "versions": [
            {
                "version_id": v.version_id,
                "currency": v.currency,
                "usd_to_inr_rate": str(v.usd_to_inr_rate),
                "is_active": v.is_active,
                "effective_from": v.effective_from.isoformat(),
            }
            for v in vers
        ],
    }

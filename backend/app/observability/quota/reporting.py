"""
backend/app/observability/quota/reporting.py

FinOps Usage Analytics and Reporting Services for Stage 7.4.
Provides tenant-scoped and platform-scoped usage aggregations, time series,
category and provider breakdowns, financial capacity analysis, and reconciliation visibility.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.institutions.models import Institution
from app.observability.quota.timezone import month_date_bounds, resolve_tenant_usage_date
from app.observability.quota_models import (
    AIFinancialAdjustment,
    AIProviderAttempt,
    AITokenReservation,
    TenantAIQuota,
    TenantDailyAIUsage,
    TenantDailyCategoryUsage,
)

logger = logging.getLogger(__name__)


class FinOpsReportingService:
    """
    Reporting service providing accurate SQL-aggregated FinOps metrics.
    Prevents double-counting, memory bloat, and cross-tenant leakage.
    """

    @classmethod
    async def get_tenant_overview(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Calculates today's comprehensive FinOps overview for an institution:
        - Quota plan configuration & limits
        - Confirmed vs reserved vs protected risk reserve financial exposure
        - Interactive and embedding token consumption
        - Monthly quota progress
        - Outstanding review and unknown usage counts
        """
        now = as_of or datetime.now(UTC)

        # 1. Load tenant AI quota policy
        quota_stmt = select(TenantAIQuota).where(TenantAIQuota.institution_id == institution_id)
        quota = (await db.execute(quota_stmt)).scalar_one_or_none()

        if quota is None:
            return {
                "configured": False,
                "institution_id": str(institution_id),
                "detail": "Tenant AI quotas are not configured. Explicit platform provisioning required.",
            }

        usage_date = resolve_tenant_usage_date(quota_timezone=quota.quota_timezone, as_of=now)

        # 2. Today's parent daily usage
        daily_stmt = select(TenantDailyAIUsage).where(
            TenantDailyAIUsage.institution_id == institution_id,
            TenantDailyAIUsage.usage_date == usage_date,
        )
        daily = (await db.execute(daily_stmt)).scalar_one_or_none()

        committed_cost_inr = daily.committed_cost_inr if daily else Decimal("0.0000")
        pending_reserved_cost_inr = daily.pending_reserved_cost_inr if daily else Decimal("0.0000")
        uncertain_exposure_cost_inr = daily.uncertain_exposure_cost_inr if daily else Decimal("0.0000")
        total_reserved_exposure_inr = pending_reserved_cost_inr + uncertain_exposure_cost_inr

        # Approved Decision 1 & 2: Risk reserve protection
        risk_reserve_pct = getattr(quota, "risk_reserve_percent", Decimal("0.1000"))
        risk_reserve_inr = (quota.daily_exposure_limit_inr * risk_reserve_pct).quantize(Decimal("0.0001"))
        total_projected_exposure_inr = committed_cost_inr + total_reserved_exposure_inr + risk_reserve_inr
        available_admission_capacity_inr = max(
            Decimal("0.0000"), quota.daily_exposure_limit_inr - total_projected_exposure_inr
        )

        daily_tokens_used = daily.committed_total_tokens if daily else 0
        request_count = daily.request_count if daily else 0
        fallback_count = daily.fallback_count if daily else 0
        unknown_usage_count = daily.unknown_usage_count if daily else 0

        # 3. Category token limits vs consumption
        cat_stmt = select(TenantDailyCategoryUsage).where(
            TenantDailyCategoryUsage.institution_id == institution_id,
            TenantDailyCategoryUsage.usage_date == usage_date,
        )
        cat_rows = (await db.execute(cat_stmt)).scalars().all()
        cats_by_name = {c.usage_category: c for c in cat_rows}

        def _cat_summary(cat_name: str, limit: int) -> dict[str, Any]:
            row = cats_by_name.get(cat_name)
            used = row.committed_total_tokens if row else 0
            pending = row.pending_reserved_tokens if row else 0
            uncertain = row.uncertain_reserved_tokens if row else 0
            pct = min(100.0, round((used / limit) * 100, 2)) if limit > 0 else 0.0
            return {
                "category": cat_name,
                "committed_tokens": used,
                "pending_reserved_tokens": pending,
                "uncertain_reserved_tokens": uncertain,
                "limit_tokens": limit,
                "percent_used": pct,
                "remaining_tokens": max(0, limit - (used + pending + uncertain)),
            }

        categories = {
            "interactive_ai": _cat_summary("interactive_ai", quota.daily_interactive_token_limit),
            "ingestion_embeddings": _cat_summary("ingestion_embeddings", quota.daily_ingestion_token_limit),
            "other_metered": _cat_summary("other_metered", quota.daily_other_token_limit),
        }

        # 4. Monthly token limits & consumption
        month_start, next_month_start = month_date_bounds(usage_date)
        monthly_stmt = select(
            func.coalesce(func.sum(TenantDailyAIUsage.committed_total_tokens), 0),
            func.coalesce(func.sum(TenantDailyAIUsage.committed_cost_inr), Decimal("0.0000")),
        ).where(
            TenantDailyAIUsage.institution_id == institution_id,
            TenantDailyAIUsage.usage_date >= month_start,
            TenantDailyAIUsage.usage_date < next_month_start,
        )
        month_res = (await db.execute(monthly_stmt)).one()
        monthly_tokens_used = int(month_res[0])
        monthly_cost_inr = Decimal(month_res[1])
        monthly_limit = quota.monthly_total_token_limit
        monthly_pct = (
            min(100.0, round((monthly_tokens_used / monthly_limit) * 100, 2))
            if monthly_limit and monthly_limit > 0
            else None
        )

        # 5. Outstanding operational exceptions
        backlog_stmt = select(
            func.count(
                case(
                    (AITokenReservation.status.in_(["RESERVED", "DISPATCHED"]), 1),
                )
            ),
            func.count(
                case(
                    (AITokenReservation.status == "UNKNOWN_USAGE", 1),
                )
            ),
        ).where(
            AITokenReservation.institution_id == institution_id,
            AITokenReservation.status.in_(["RESERVED", "DISPATCHED", "UNKNOWN_USAGE"]),
        )
        res_counts = (await db.execute(backlog_stmt)).one()
        outstanding_reservations_count = int(res_counts[0] or 0)
        unknown_usage_reservations_count = int(res_counts[1] or 0)

        return {
            "configured": True,
            "institution_id": str(institution_id),
            "quota_timezone": quota.quota_timezone,
            "usage_date": usage_date.isoformat(),
            "tier_name": quota.tier_name,
            "plan_id": quota.plan_id or quota.tier_name.lower(),
            "is_suspended": quota.is_suspended,
            "suspension_reason": quota.suspension_reason,
            "financial": {
                "daily_ceiling_inr": str(quota.daily_exposure_limit_inr),
                "confirmed_cost_inr": str(committed_cost_inr),
                "pending_reserved_cost_inr": str(pending_reserved_cost_inr),
                "uncertain_exposure_cost_inr": str(uncertain_exposure_cost_inr),
                "total_reserved_exposure_inr": str(total_reserved_exposure_inr),
                "risk_reserve_percent": str(risk_reserve_pct),
                "risk_reserve_inr": str(risk_reserve_inr),
                "total_projected_exposure_inr": str(total_projected_exposure_inr),
                "available_admission_capacity_inr": str(available_admission_capacity_inr),
                "percent_capacity_utilized": min(
                    100.0,
                    round(
                        float(total_projected_exposure_inr / quota.daily_exposure_limit_inr) * 100,
                        2,
                    ),
                )
                if quota.daily_exposure_limit_inr > 0
                else 0.0,
            },
            "tokens_today": {
                "total_committed_tokens": daily_tokens_used,
                "request_count": request_count,
                "fallback_count": fallback_count,
                "unknown_usage_count": unknown_usage_count,
            },
            "categories": categories,
            "monthly": {
                "month_start": month_start.isoformat(),
                "monthly_token_limit": monthly_limit,
                "monthly_tokens_used": monthly_tokens_used,
                "monthly_cost_inr": str(monthly_cost_inr),
                "percent_used": monthly_pct,
            },
            "exceptions": {
                "outstanding_reservations_count": outstanding_reservations_count,
                "unknown_usage_reservations_count": unknown_usage_reservations_count,
            },
        }

    @classmethod
    async def get_tenant_daily_series(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Returns time series of daily usage within a date range."""
        stmt = (
            select(TenantDailyAIUsage)
            .where(
                TenantDailyAIUsage.institution_id == institution_id,
                TenantDailyAIUsage.usage_date >= start_date,
                TenantDailyAIUsage.usage_date <= end_date,
            )
            .order_by(TenantDailyAIUsage.usage_date.asc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "usage_date": r.usage_date.isoformat(),
                "committed_cost_inr": str(r.committed_cost_inr),
                "pending_reserved_cost_inr": str(r.pending_reserved_cost_inr),
                "uncertain_exposure_cost_inr": str(r.uncertain_exposure_cost_inr),
                "committed_total_tokens": r.committed_total_tokens,
                "request_count": r.request_count,
                "fallback_count": r.fallback_count,
                "unknown_usage_count": r.unknown_usage_count,
            }
            for r in rows
        ]

    @classmethod
    async def get_tenant_category_breakdown(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Aggregates usage per category over a date range."""
        stmt = (
            select(
                TenantDailyCategoryUsage.usage_category,
                func.sum(TenantDailyCategoryUsage.committed_input_tokens).label("input_tokens"),
                func.sum(TenantDailyCategoryUsage.committed_output_tokens).label("output_tokens"),
                func.sum(TenantDailyCategoryUsage.committed_total_tokens).label("total_tokens"),
                func.sum(TenantDailyCategoryUsage.committed_cost_inr).label("total_cost_inr"),
            )
            .where(
                TenantDailyCategoryUsage.institution_id == institution_id,
                TenantDailyCategoryUsage.usage_date >= start_date,
                TenantDailyCategoryUsage.usage_date <= end_date,
            )
            .group_by(TenantDailyCategoryUsage.usage_category)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "usage_category": r.usage_category,
                "input_tokens": int(r.input_tokens or 0),
                "output_tokens": int(r.output_tokens or 0),
                "total_tokens": int(r.total_tokens or 0),
                "total_cost_inr": str(Decimal(r.total_cost_inr or Decimal("0.0000"))),
            }
            for r in rows
        ]

    @classmethod
    async def get_tenant_provider_breakdown(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Aggregates usage per provider and model over a date range."""
        stmt = (
            select(
                AIProviderAttempt.provider,
                AIProviderAttempt.model,
                func.count(AIProviderAttempt.id).label("attempt_count"),
                func.sum(
                    case((AIProviderAttempt.status == "SUCCEEDED", 1), else_=0)
                ).label("succeeded_count"),
                func.sum(
                    case((AIProviderAttempt.is_fallback.is_(True), 1), else_=0)
                ).label("fallback_count"),
                func.coalesce(func.sum(AIProviderAttempt.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(AIProviderAttempt.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(AIProviderAttempt.actual_cost_inr), Decimal("0.0000")).label(
                    "actual_cost_inr"
                ),
                func.avg(AIProviderAttempt.latency_ms).label("avg_latency_ms"),
            )
            .where(
                AIProviderAttempt.institution_id == institution_id,
                cast(AIProviderAttempt.dispatched_at, Date) >= start_date,
                cast(AIProviderAttempt.dispatched_at, Date) <= end_date,
            )
            .group_by(AIProviderAttempt.provider, AIProviderAttempt.model)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "provider": r.provider,
                "model": r.model,
                "attempt_count": int(r.attempt_count or 0),
                "succeeded_count": int(r.succeeded_count or 0),
                "fallback_count": int(r.fallback_count or 0),
                "input_tokens": int(r.input_tokens or 0),
                "output_tokens": int(r.output_tokens or 0),
                "total_tokens": int(r.input_tokens or 0) + int(r.output_tokens or 0),
                "actual_cost_inr": str(Decimal(r.actual_cost_inr or Decimal("0.0000"))),
                "avg_latency_ms": round(float(r.avg_latency_ms), 1) if r.avg_latency_ms else 0,
            }
            for r in rows
        ]

    @classmethod
    async def get_tenant_reservations(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Returns paginated list of reservations for an institution."""
        stmt = select(AITokenReservation).where(AITokenReservation.institution_id == institution_id)
        if status:
            stmt = stmt.where(AITokenReservation.status == status.upper().strip())

        total_stmt = select(func.count(AITokenReservation.id)).where(
            AITokenReservation.institution_id == institution_id
        )
        if status:
            total_stmt = total_stmt.where(AITokenReservation.status == status.upper().strip())
        total = int((await db.execute(total_stmt)).scalar_one() or 0)

        stmt = stmt.order_by(AITokenReservation.created_at.desc()).limit(limit).offset(offset)
        rows = (await db.execute(stmt)).scalars().all()

        items = [
            {
                "id": str(r.id),
                "usage_date": r.usage_date.isoformat(),
                "usage_category": r.usage_category,
                "endpoint": r.endpoint,
                "status": r.status,
                "total_reserved_tokens": r.total_reserved_tokens,
                "reserved_cost_inr": str(r.reserved_cost_inr),
                "actual_total_tokens": r.actual_total_tokens,
                "actual_cost_inr": str(r.actual_cost_inr),
                "uncertain_tokens_held": r.uncertain_tokens_held,
                "uncertain_cost_held_inr": str(r.uncertain_cost_held_inr),
                "review_status": r.review_status,
                "recovery_state": r.recovery_state,
                "recovery_reason": r.recovery_reason,
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "reconciled_at": r.reconciled_at.isoformat() if r.reconciled_at else None,
            }
            for r in rows
        ]
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    @classmethod
    async def get_tenant_adjustments(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Returns paginated financial adjustments audit history."""
        stmt = (
            select(AIFinancialAdjustment)
            .where(AIFinancialAdjustment.institution_id == institution_id)
            .order_by(AIFinancialAdjustment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        total_stmt = select(func.count(AIFinancialAdjustment.id)).where(
            AIFinancialAdjustment.institution_id == institution_id
        )
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        rows = (await db.execute(stmt)).scalars().all()

        items = [
            {
                "id": str(r.id),
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

    # -------------------------------------------------------------------------
    # Platform-Admin Cross-Tenant Reporting
    # -------------------------------------------------------------------------

    @classmethod
    async def get_platform_overview(
        cls,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Platform-wide aggregate metrics across all institutions."""
        now = as_of or datetime.now(UTC)
        today = now.date()

        # 1. Total configured institutions
        inst_count_stmt = select(func.count(TenantAIQuota.id))
        total_configured = int((await db.execute(inst_count_stmt)).scalar_one() or 0)

        # 2. Today's aggregate spend and tokens across all tenants
        daily_agg_stmt = select(
            func.coalesce(func.sum(TenantDailyAIUsage.committed_cost_inr), Decimal("0.0000")),
            func.coalesce(func.sum(TenantDailyAIUsage.pending_reserved_cost_inr), Decimal("0.0000")),
            func.coalesce(func.sum(TenantDailyAIUsage.uncertain_exposure_cost_inr), Decimal("0.0000")),
            func.coalesce(func.sum(TenantDailyAIUsage.committed_total_tokens), 0),
            func.coalesce(func.sum(TenantDailyAIUsage.request_count), 0),
            func.coalesce(func.sum(TenantDailyAIUsage.unknown_usage_count), 0),
        ).where(TenantDailyAIUsage.usage_date == today)
        daily_res = (await db.execute(daily_agg_stmt)).one()

        # 3. Monthly aggregate spend
        month_start, next_month_start = month_date_bounds(today)
        month_agg_stmt = select(
            func.coalesce(func.sum(TenantDailyAIUsage.committed_cost_inr), Decimal("0.0000")),
            func.coalesce(func.sum(TenantDailyAIUsage.committed_total_tokens), 0),
        ).where(
            TenantDailyAIUsage.usage_date >= month_start,
            TenantDailyAIUsage.usage_date < next_month_start,
        )
        month_res = (await db.execute(month_agg_stmt)).one()

        # 4. Unknown usage and reconciliation backlog
        backlog_stmt = select(
            func.count(
                case((AITokenReservation.status == "UNKNOWN_USAGE", 1))
            ),
            func.count(
                case((AITokenReservation.review_status == "NEEDS_MANUAL_REVIEW", 1))
            ),
        )
        backlog_res = (await db.execute(backlog_stmt)).one()

        return {
            "timestamp": now.isoformat(),
            "institutions_configured_count": total_configured,
            "today": {
                "date": today.isoformat(),
                "confirmed_cost_inr": str(daily_res[0]),
                "pending_reserved_cost_inr": str(daily_res[1]),
                "uncertain_exposure_cost_inr": str(daily_res[2]),
                "total_tokens_used": int(daily_res[3]),
                "request_count": int(daily_res[4]),
                "unknown_usage_count": int(daily_res[5]),
            },
            "current_month": {
                "month_start": month_start.isoformat(),
                "confirmed_cost_inr": str(month_res[0]),
                "total_tokens_used": int(month_res[1]),
            },
            "reconciliation_backlog": {
                "unknown_usage_count": int(backlog_res[0] or 0),
                "needs_manual_review_count": int(backlog_res[1] or 0),
            },
        }

    @classmethod
    async def get_platform_institutions(
        cls,
        db: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Lists institutions with their quota plans, today's spend, and utilization %."""
        now = as_of or datetime.now(UTC)
        today = now.date()

        # Join institutions with quotas and today's usage
        stmt = (
            select(
                Institution.id,
                Institution.name,
                Institution.slug,
                Institution.is_active,
                TenantAIQuota.plan_id,
                TenantAIQuota.tier_name,
                TenantAIQuota.daily_exposure_limit_inr,
                TenantAIQuota.risk_reserve_percent,
                TenantAIQuota.is_suspended,
                TenantDailyAIUsage.committed_cost_inr,
                TenantDailyAIUsage.pending_reserved_cost_inr,
                TenantDailyAIUsage.uncertain_exposure_cost_inr,
                TenantDailyAIUsage.committed_total_tokens,
            )
            .outerjoin(TenantAIQuota, TenantAIQuota.institution_id == Institution.id)
            .outerjoin(
                TenantDailyAIUsage,
                (TenantDailyAIUsage.institution_id == Institution.id)
                & (TenantDailyAIUsage.usage_date == today),
            )
            .order_by(Institution.name.asc())
            .limit(limit)
            .offset(offset)
        )
        total_stmt = select(func.count(Institution.id))
        total = int((await db.execute(total_stmt)).scalar_one() or 0)

        rows = (await db.execute(stmt)).all()
        items = []
        for r in rows:
            has_quota = r.plan_id is not None or r.tier_name is not None
            ceiling = Decimal(r.daily_exposure_limit_inr or Decimal("0.0000"))
            risk_pct = Decimal(r.risk_reserve_percent or Decimal("0.1000"))
            comm_cost = Decimal(r.committed_cost_inr or Decimal("0.0000"))
            pend_cost = Decimal(r.pending_reserved_cost_inr or Decimal("0.0000"))
            unc_cost = Decimal(r.uncertain_exposure_cost_inr or Decimal("0.0000"))
            risk_buf = (ceiling * risk_pct).quantize(Decimal("0.0001"))
            total_exp = comm_cost + pend_cost + unc_cost + risk_buf
            util_pct = min(100.0, round(float(total_exp / ceiling) * 100, 2)) if ceiling > 0 else 0.0

            items.append(
                {
                    "institution_id": str(r.id),
                    "name": r.name,
                    "slug": r.slug,
                    "is_active": r.is_active,
                    "is_configured": has_quota,
                    "plan_id": r.plan_id or (r.tier_name.lower() if r.tier_name else None),
                    "tier_name": r.tier_name,
                    "daily_ceiling_inr": str(ceiling),
                    "today_confirmed_cost_inr": str(comm_cost),
                    "today_exposure_inr": str(total_exp),
                    "utilization_percent": util_pct,
                    "is_suspended": bool(r.is_suspended) if has_quota else False,
                }
            )

        return {"total": total, "limit": limit, "offset": offset, "items": items}

    @classmethod
    async def get_reconciliation_backlog(
        cls,
        db: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Lists reservations requiring operator investigation (UNKNOWN_USAGE, expired, or review needed)."""
        stmt = (
            select(AITokenReservation)
            .where(
                (AITokenReservation.status == "UNKNOWN_USAGE")
                | (AITokenReservation.review_status == "NEEDS_MANUAL_REVIEW")
                | (AITokenReservation.recovery_state != "NONE")
            )
            .order_by(AITokenReservation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        total_stmt = select(func.count(AITokenReservation.id)).where(
            (AITokenReservation.status == "UNKNOWN_USAGE")
            | (AITokenReservation.review_status == "NEEDS_MANUAL_REVIEW")
            | (AITokenReservation.recovery_state != "NONE")
        )
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        rows = (await db.execute(stmt)).scalars().all()

        items = [
            {
                "id": str(r.id),
                "institution_id": str(r.institution_id),
                "usage_date": r.usage_date.isoformat(),
                "usage_category": r.usage_category,
                "endpoint": r.endpoint,
                "status": r.status,
                "total_reserved_tokens": r.total_reserved_tokens,
                "reserved_cost_inr": str(r.reserved_cost_inr),
                "uncertain_tokens_held": r.uncertain_tokens_held,
                "uncertain_cost_held_inr": str(r.uncertain_cost_held_inr),
                "review_status": r.review_status,
                "recovery_state": r.recovery_state,
                "recovery_reason": r.recovery_reason,
                "created_at": r.created_at.isoformat(),
                "dispatched_at": r.dispatched_at.isoformat() if r.dispatched_at else None,
                "expires_at": r.expires_at.isoformat(),
            }
            for r in rows
        ]
        return {"total": total, "limit": limit, "offset": offset, "items": items}


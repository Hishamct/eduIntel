"""
backend/app/observability/quota/provisioning.py

Centralized Quota Plan Management and Tenant Provisioning Architecture for Stage 7.4.
Enforces explicit platform-admin provisioning, audit logging, plan templates,
safe plan changes during active days, and fail-closed tenant validation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.institutions.models import Institution
from app.observability.quota.errors import (
    QuotaEngineError,
)
from app.observability.quota.retry import bind_tenant_rls_context
from app.observability.quota_models import (
    AIQuotaPlan,
    TenantAIQuota,
    TenantQuotaProvisioningLog,
)

logger = logging.getLogger(__name__)


class QuotaPlanNotFoundError(QuotaEngineError):
    """Raised when an unrecognized quota plan is requested."""

    def __init__(self, plan_id: str):
        super().__init__(f"AI quota plan '{plan_id}' does not exist.")
        self.plan_id = plan_id


class QuotaPlanInactiveError(QuotaEngineError):
    """Raised when an inactive quota plan is assigned."""

    def __init__(self, plan_id: str):
        super().__init__(f"AI quota plan '{plan_id}' is currently inactive and cannot be assigned.")
        self.plan_id = plan_id


class InstitutionNotFoundError(QuotaEngineError):
    """Raised when the target institution does not exist."""

    def __init__(self, institution_id: uuid.UUID):
        super().__init__(f"Institution '{institution_id}' was not found.")
        self.institution_id = institution_id


class QuotaProvisioningService:
    """
    Service governing centralized AI Quota Plans and explicit Tenant Provisioning.
    """

    @classmethod
    async def list_plans(
        cls,
        db: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> list[AIQuotaPlan]:
        """Lists available quota plan templates."""
        stmt = select(AIQuotaPlan)
        if not include_inactive:
            stmt = stmt.where(AIQuotaPlan.is_active.is_(True))
        stmt = stmt.order_by(AIQuotaPlan.daily_financial_ceiling_inr.asc())
        return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def get_plan(
        cls,
        db: AsyncSession,
        plan_id: str,
    ) -> AIQuotaPlan | None:
        """Retrieves a specific plan template by plan_id."""
        stmt = select(AIQuotaPlan).where(AIQuotaPlan.plan_id == plan_id.lower().strip())
        return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def upsert_custom_plan(
        cls,
        db: AsyncSession,
        *,
        plan_id: str,
        name: str,
        description: str,
        daily_financial_ceiling_inr: Decimal,
        risk_reserve_percent: Decimal = Decimal("0.1000"),
        daily_interactive_token_limit: int = 750_000,
        daily_ingestion_token_limit: int = 500_000,
        daily_other_token_limit: int = 250_000,
        monthly_total_token_limit: int | None = None,
        max_tokens_per_request: int = 16384,
        is_active: bool = True,
    ) -> AIQuotaPlan:
        """Creates or updates an enterprise/custom plan template."""
        clean_id = plan_id.lower().strip()
        plan = await cls.get_plan(db, clean_id)
        if plan is None:
            plan = AIQuotaPlan(
                plan_id=clean_id,
                name=name.strip(),
                description=description.strip(),
                daily_financial_ceiling_inr=daily_financial_ceiling_inr,
                risk_reserve_percent=risk_reserve_percent,
                daily_interactive_token_limit=daily_interactive_token_limit,
                daily_ingestion_token_limit=daily_ingestion_token_limit,
                daily_other_token_limit=daily_other_token_limit,
                monthly_total_token_limit=monthly_total_token_limit,
                max_tokens_per_request=max_tokens_per_request,
                is_active=is_active,
            )
            db.add(plan)
        else:
            plan.name = name.strip()
            plan.description = description.strip()
            plan.daily_financial_ceiling_inr = daily_financial_ceiling_inr
            plan.risk_reserve_percent = risk_reserve_percent
            plan.daily_interactive_token_limit = daily_interactive_token_limit
            plan.daily_ingestion_token_limit = daily_ingestion_token_limit
            plan.daily_other_token_limit = daily_other_token_limit
            plan.monthly_total_token_limit = monthly_total_token_limit
            plan.max_tokens_per_request = max_tokens_per_request
            plan.is_active = is_active
            plan.updated_at = datetime.now(UTC)

        await db.flush()
        return plan

    @classmethod
    async def provision_tenant_quota(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        plan_id: str,
        change_reason: str,
        actor: str | None = None,
        actor_user_id: uuid.UUID | str | None = None,
        custom_financial_ceiling_inr: Decimal | None = None,
        custom_risk_reserve_percent: Decimal | None = None,
        custom_interactive_tokens: int | None = None,
        custom_ingestion_tokens: int | None = None,
        custom_other_tokens: int | None = None,
        custom_monthly_tokens: int | None = None,
        quota_timezone: str = "Asia/Kolkata",
    ) -> TenantAIQuota:
        """
        Explicit platform-admin operation to assign or update a tenant's AI Quota.
        Maintains historical daily ledger integrity and records an immutable provisioning log.
        """
        actor_val = str(actor_user_id) if actor_user_id is not None else (actor or "system")

        await bind_tenant_rls_context(db, institution_id=institution_id, is_platform_admin=True)

        # 1. Verify target institution exists
        inst_stmt = select(Institution).where(Institution.id == institution_id)
        inst = (await db.execute(inst_stmt)).scalar_one_or_none()
        if inst is None:
            raise InstitutionNotFoundError(institution_id)

        # 2. Verify selected plan template
        clean_plan_id = plan_id.lower().strip()
        plan = await cls.get_plan(db, clean_plan_id)
        if plan is None:
            raise QuotaPlanNotFoundError(clean_plan_id)
        if not plan.is_active:
            raise QuotaPlanInactiveError(clean_plan_id)

        # 3. Determine effective limits (plan defaults + approved custom overrides)
        effective_financial_ceiling = (
            custom_financial_ceiling_inr
            if custom_financial_ceiling_inr is not None
            else plan.daily_financial_ceiling_inr
        )
        effective_risk_reserve_pct = (
            custom_risk_reserve_percent
            if custom_risk_reserve_percent is not None
            else plan.risk_reserve_percent
        )
        effective_interactive_tokens = (
            custom_interactive_tokens
            if custom_interactive_tokens is not None
            else plan.daily_interactive_token_limit
        )
        effective_ingestion_tokens = (
            custom_ingestion_tokens
            if custom_ingestion_tokens is not None
            else plan.daily_ingestion_token_limit
        )
        effective_other_tokens = (
            custom_other_tokens
            if custom_other_tokens is not None
            else plan.daily_other_token_limit
        )
        effective_monthly_tokens = (
            custom_monthly_tokens
            if custom_monthly_tokens is not None
            else plan.monthly_total_token_limit
        )

        if effective_financial_ceiling < Decimal("0.0000"):
            raise ValueError("Daily financial ceiling cannot be negative.")
        if effective_risk_reserve_pct < Decimal("0.0000") or effective_risk_reserve_pct > Decimal("1.0000"):
            raise ValueError("Risk reserve percent must be between 0.0 and 1.0.")
        if effective_interactive_tokens < 0 or effective_ingestion_tokens < 0 or effective_other_tokens < 0:
            raise ValueError("Token limits cannot be negative.")

        # 4. Check if tenant already has an active quota record
        quota_stmt = (
            select(TenantAIQuota)
            .where(TenantAIQuota.institution_id == institution_id)
            .with_for_update()
        )
        existing_quota = (await db.execute(quota_stmt)).scalar_one_or_none()

        action = "PROVISION" if existing_quota is None else "PLAN_CHANGE"
        previous_plan = existing_quota.plan_id if existing_quota else None

        if existing_quota is None:
            # Create new quota configuration
            new_quota = TenantAIQuota(
                institution_id=institution_id,
                plan_id=clean_plan_id,
                tier_name=plan.name,
                quota_timezone=quota_timezone,
                daily_exposure_limit_inr=effective_financial_ceiling,
                pending_reserve_cap_percent=effective_risk_reserve_pct,
                risk_reserve_percent=effective_risk_reserve_pct,
                daily_interactive_token_limit=effective_interactive_tokens,
                daily_ingestion_token_limit=effective_ingestion_tokens,
                daily_other_token_limit=effective_other_tokens,
                monthly_total_token_limit=effective_monthly_tokens,
                max_tokens_per_request=plan.max_tokens_per_request,
                missing_usage_policy=plan.missing_usage_policy,
                is_unlimited=False,
                is_suspended=False,
            )
            db.add(new_quota)
            active_quota = new_quota
        else:
            # Update existing configuration without modifying daily usage historical ledgers
            existing_quota.plan_id = clean_plan_id
            existing_quota.tier_name = plan.name
            existing_quota.daily_exposure_limit_inr = effective_financial_ceiling
            existing_quota.pending_reserve_cap_percent = effective_risk_reserve_pct
            existing_quota.risk_reserve_percent = effective_risk_reserve_pct
            existing_quota.daily_interactive_token_limit = effective_interactive_tokens
            existing_quota.daily_ingestion_token_limit = effective_ingestion_tokens
            existing_quota.daily_other_token_limit = effective_other_tokens
            existing_quota.monthly_total_token_limit = effective_monthly_tokens
            existing_quota.max_tokens_per_request = plan.max_tokens_per_request
            existing_quota.missing_usage_policy = plan.missing_usage_policy
            existing_quota.updated_at = datetime.now(UTC)
            active_quota = existing_quota

        await db.flush()

        # 5. Create immutable audit record
        snapshot: dict[str, Any] = {
            "plan_id": clean_plan_id,
            "tier_name": plan.name,
            "daily_financial_ceiling_inr": str(effective_financial_ceiling),
            "risk_reserve_percent": str(effective_risk_reserve_pct),
            "daily_interactive_token_limit": effective_interactive_tokens,
            "daily_ingestion_token_limit": effective_ingestion_tokens,
            "daily_other_token_limit": effective_other_tokens,
            "monthly_total_token_limit": effective_monthly_tokens,
            "max_tokens_per_request": plan.max_tokens_per_request,
            "missing_usage_policy": plan.missing_usage_policy,
        }

        audit_log = TenantQuotaProvisioningLog(
            institution_id=institution_id,
            changed_by_actor=actor_val.strip(),
            action=action,
            previous_plan_id=previous_plan,
            new_plan_id=clean_plan_id,
            change_reason=change_reason.strip(),
            effective_at=datetime.now(UTC),
            snapshot_json=snapshot,
        )
        db.add(audit_log)
        await db.flush()

        logger.info(
            "tenant_quota_provisioned",
            extra={
                "institution_id": str(institution_id),
                "plan_id": clean_plan_id,
                "action": action,
                "actor": actor,
                "ceiling_inr": str(effective_financial_ceiling),
            },
        )
        return active_quota

    @classmethod
    async def suspend_tenant_quota(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        reason: str,
        actor: str | None = None,
        actor_user_id: uuid.UUID | str | None = None,
    ) -> TenantAIQuota:
        """Suspends AI access for an institution while preserving all ledgers."""
        actor_val = str(actor_user_id) if actor_user_id is not None else (actor or "system")
        await bind_tenant_rls_context(db, institution_id=institution_id, is_platform_admin=True)
        quota_stmt = (
            select(TenantAIQuota)
            .where(TenantAIQuota.institution_id == institution_id)
            .with_for_update()
        )
        quota = (await db.execute(quota_stmt)).scalar_one_or_none()
        if quota is None:
            raise InstitutionNotFoundError(institution_id)

        quota.is_suspended = True
        quota.suspension_reason = reason.strip()
        quota.updated_at = datetime.now(UTC)

        audit_log = TenantQuotaProvisioningLog(
            institution_id=institution_id,
            changed_by_actor=actor_val.strip(),
            action="SUSPEND",
            previous_plan_id=quota.plan_id,
            new_plan_id=quota.plan_id or "unknown",
            change_reason=reason.strip(),
            effective_at=datetime.now(UTC),
            snapshot_json={"is_suspended": True, "reason": reason.strip()},
        )
        db.add(audit_log)
        await db.flush()
        return quota

    @classmethod
    async def resume_tenant_quota(
        cls,
        db: AsyncSession,
        *,
        institution_id: uuid.UUID,
        reason: str,
        actor: str | None = None,
        actor_user_id: uuid.UUID | str | None = None,
    ) -> TenantAIQuota:
        """Resumes suspended AI access for an institution."""
        actor_val = str(actor_user_id) if actor_user_id is not None else (actor or "system")
        await bind_tenant_rls_context(db, institution_id=institution_id, is_platform_admin=True)
        quota_stmt = (
            select(TenantAIQuota)
            .where(TenantAIQuota.institution_id == institution_id)
            .with_for_update()
        )
        quota = (await db.execute(quota_stmt)).scalar_one_or_none()
        if quota is None:
            raise InstitutionNotFoundError(institution_id)

        quota.is_suspended = False
        quota.suspension_reason = None
        quota.updated_at = datetime.now(UTC)

        audit_log = TenantQuotaProvisioningLog(
            institution_id=institution_id,
            changed_by_actor=actor_val.strip(),
            action="RESUME",
            previous_plan_id=quota.plan_id,
            new_plan_id=quota.plan_id or "unknown",
            change_reason=reason.strip(),
            effective_at=datetime.now(UTC),
            snapshot_json={"is_suspended": False, "reason": reason.strip()},
        )
        db.add(audit_log)
        await db.flush()
        return quota

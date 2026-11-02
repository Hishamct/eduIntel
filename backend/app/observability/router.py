from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext, get_tenant_db, require_tenant_role
from app.observability.service import (
    get_agent_trace_detail,
    get_agent_trace_summary,
    get_llm_usage_summary,
)
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/llm-usage-summary")
async def llm_usage_summary(
    since_days: int | None = Query(
        default=30,
        ge=0,
        description="Limit to the last N days. Pass 0 or omit with ?since_days= to get all-time totals.",
    ),
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    LLM cost/latency summary for the Owner/Admin analytics dashboard —
    overall totals plus a per-endpoint breakdown, strictly scoped to caller's
    institution. Admin-only: this is business-facing cost data, not
    something a student or teacher needs to see.
    """
    effective_since_days = None if not since_days else since_days
    return await get_llm_usage_summary(
        db=db,
        institution_id=tenant.institution_id,
        since_days=effective_since_days,
    )


@router.get("/agent-traces/summary")
async def agent_traces_summary(
    since_days: int = Query(default=30, ge=0, description="Limit to the last N days."),
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    LangGraph agent-tracing summary for the Owner/Admin dashboard: per-node
    call count/avg/max duration/error count for each agent, run counts,
    and a list of recently active runs, strictly scoped to caller's institution.
    """
    return await get_agent_trace_summary(
        db=db,
        institution_id=tenant.institution_id,
        since_days=since_days,
    )


@router.get("/agent-traces/{trace_id}")
async def agent_trace_detail(
    trace_id: str,
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Full ordered step-by-step execution path for one agent run, strictly scoped
    to caller's institution.
    """
    return {
        "trace_id": trace_id,
        "steps": await get_agent_trace_detail(
            db=db,
            institution_id=tenant.institution_id,
            trace_id=trace_id,
        ),
    }

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
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
        description="Limit to the last N days. Pass 0 or omit with ?since_days= to get all-time totals.",
    ),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    LLM cost/latency summary for the Owner/Admin analytics dashboard —
    overall totals plus a per-endpoint breakdown (which assistant/feature
    is costing the most, which is slowest, how often the Groq fallback
    is kicking in). Admin-only: this is business-facing cost data, not
    something a student or teacher needs to see.
    """
    effective_since_days = None if not since_days else since_days
    return await get_llm_usage_summary(db=db, since_days=effective_since_days)


@router.get("/agent-traces/summary")
async def agent_traces_summary(
    since_days: int = Query(default=30, description="Limit to the last N days."),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    LangGraph agent-tracing summary for the Owner/Admin dashboard: per-node
    call count/avg/max duration/error count for each agent (Admin
    Assistant, Portal Assistant), run counts, and a list of recently
    active runs to drill into via /agent-traces/{trace_id}. Admin-only —
    this is an internal debugging/observability view, not something a
    student or teacher needs.
    """
    return await get_agent_trace_summary(db=db, since_days=since_days)


@router.get("/agent-traces/{trace_id}")
async def agent_trace_detail(
    trace_id: str,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Full ordered step-by-step execution path for one agent run (one
    chat_with_admin_assistant()/chat_with_portal_assistant() call) — the
    "what exactly did the agent do here" drill-down for a trace_id
    surfaced by /agent-traces/summary.
    """
    return {
        "trace_id": trace_id,
        "steps": await get_agent_trace_detail(db=db, trace_id=trace_id),
    }

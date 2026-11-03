from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.admin_assistant import chat_with_admin_assistant
from app.agents.portal_assistant import chat_with_portal_assistant
from app.agents.schemas import (
    AdminAssistantRequest,
    AdminAssistantResponse,
    PortalAssistantRequest,
    PortalAssistantResponse,
)
from app.core.tenant import TenantContext, get_tenant_db, require_tenant_role
from app.observability.service import log_agent_trace, log_ai_query, log_llm_usage
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/portal-assistant/chat", response_model=PortalAssistantResponse)
async def portal_assistant_chat(
    payload: PortalAssistantRequest,
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = chat_with_portal_assistant(
        session_id=payload.session_id,
        query=payload.query,
        tenant_id=str(tenant.institution_id),
        user_id=current_user.id,
    )

    await log_ai_query(
        db=db,
        user_id=current_user.id,
        endpoint="portal-assistant/chat",
        query_text=payload.query,
        was_blocked=result.get("blocked", False),
        block_reason=result.get("block_reason"),
        institution_id=tenant.institution_id,
    )
    await log_llm_usage(
        db=db,
        endpoint="portal-assistant/generate",
        usage=result.get("llm_usage"),
        institution_id=tenant.institution_id,
    )
    await log_agent_trace(
        db=db,
        trace_id=result["trace_id"],
        agent_name="portal-assistant",
        session_id=payload.session_id,
        trace_steps=result.get("trace_steps", []),
        institution_id=tenant.institution_id,
    )

    return result


@router.post("/admin-assistant/chat", response_model=AdminAssistantResponse)
async def admin_assistant_chat(
    payload: AdminAssistantRequest,
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await chat_with_admin_assistant(
        session_id=payload.session_id,
        query=payload.query,
        tenant_id=str(tenant.institution_id),
        user_id=current_user.id,
    )

    await log_ai_query(
        db=db,
        user_id=current_user.id,
        endpoint="admin-assistant/chat",
        query_text=payload.query,
        was_blocked=result.get("blocked", False),
        block_reason=result.get("block_reason"),
        institution_id=tenant.institution_id,
    )
    for endpoint_tag, usage in result.get("llm_usage", {}).items():
        await log_llm_usage(
            db=db,
            endpoint=endpoint_tag,
            usage=usage,
            institution_id=tenant.institution_id,
        )
    await log_agent_trace(
        db=db,
        trace_id=result["trace_id"],
        agent_name="admin-assistant",
        session_id=payload.session_id,
        trace_steps=result.get("trace_steps", []),
        institution_id=tenant.institution_id,
    )

    return result

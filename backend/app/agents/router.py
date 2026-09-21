from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.portal_assistant import chat_with_portal_assistant
from app.agents.schemas import PortalAssistantRequest, PortalAssistantResponse
from app.core.database import get_db
from app.observability.service import log_agent_trace, log_ai_query, log_llm_usage
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/portal-assistant/chat", response_model=PortalAssistantResponse)
async def portal_assistant_chat(
    payload: PortalAssistantRequest,
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    result = chat_with_portal_assistant(
        session_id=payload.session_id,
        query=payload.query,
    )

    await log_ai_query(
        db=db,
        user_id=current_user.id,
        endpoint="portal-assistant/chat",
        query_text=payload.query,
        was_blocked=result.get("blocked", False),
        block_reason=result.get("block_reason"),
    )
    await log_llm_usage(
        db=db, endpoint="portal-assistant/generate", usage=result.get("llm_usage")
    )
    await log_agent_trace(
        db=db,
        trace_id=result["trace_id"],
        agent_name="portal-assistant",
        session_id=payload.session_id,
        trace_steps=result.get("trace_steps", []),
    )

    return result


from app.agents.admin_assistant import chat_with_admin_assistant
from app.agents.schemas import AdminAssistantRequest, AdminAssistantResponse


@router.post("/admin-assistant/chat", response_model=AdminAssistantResponse)
async def admin_assistant_chat(
    payload: AdminAssistantRequest,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await chat_with_admin_assistant(
        session_id=payload.session_id,
        query=payload.query,
    )

    await log_ai_query(
        db=db,
        user_id=current_user.id,
        endpoint="admin-assistant/chat",
        query_text=payload.query,
        was_blocked=result.get("blocked", False),
        block_reason=result.get("block_reason"),
    )
    for endpoint_tag, usage in result.get("llm_usage", {}).items():
        await log_llm_usage(db=db, endpoint=endpoint_tag, usage=usage)
    await log_agent_trace(
        db=db,
        trace_id=result["trace_id"],
        agent_name="admin-assistant",
        session_id=payload.session_id,
        trace_steps=result.get("trace_steps", []),
    )

    return result

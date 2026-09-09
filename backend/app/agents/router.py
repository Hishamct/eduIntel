from fastapi import APIRouter, Depends
from app.agents.schemas import PortalAssistantRequest, PortalAssistantResponse
from app.agents.portal_assistant import chat_with_portal_assistant
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/portal-assistant/chat", response_model=PortalAssistantResponse)
async def portal_assistant_chat(
    payload: PortalAssistantRequest,
    current_user: User = Depends(require_role("student")),
):
    result = chat_with_portal_assistant(
        session_id=payload.session_id,
        query=payload.query,
    )
    return result

from app.agents.schemas import AdminAssistantRequest, AdminAssistantResponse
from app.agents.admin_assistant import chat_with_admin_assistant


@router.post("/admin-assistant/chat", response_model=AdminAssistantResponse)
async def admin_assistant_chat(
    payload: AdminAssistantRequest,
    current_user: User = Depends(require_role("admin")),
):
    result = await chat_with_admin_assistant(
        session_id=payload.session_id,
        query=payload.query,
    )
    return result
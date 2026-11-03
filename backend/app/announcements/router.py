from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import TenantContext, get_tenant_db, require_tenant_role
from app.users.dependencies import require_role
from app.users.models import User

from . import service
from .schemas import AnnouncementCreate, AnnouncementOut

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("/", response_model=list[AnnouncementOut])
async def list_announcements(
    current_user: User = Depends(require_role("student", "teacher", "admin")),
    tenant: TenantContext = Depends(require_tenant_role("student", "teacher", "admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await service.get_all_announcements(
        db=db,
        institution_id=tenant.institution_id,
    )


@router.post("/", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
async def post_announcement(
    payload: AnnouncementCreate,
    current_user: User = Depends(require_role("admin")),
    tenant: TenantContext = Depends(require_tenant_role("admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await service.create_announcement(
        db=db,
        institution_id=tenant.institution_id,
        title=payload.title,
        body=payload.body,
        posted_by=current_user.name or current_user.email,
    )

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.users.dependencies import require_role
from app.users.models import User

from . import service
from .schemas import AnnouncementOut

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("/", response_model=list[AnnouncementOut])
async def list_announcements(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role("student", "teacher", "admin")
    ),  # any logged-in user can view
):
    return await service.get_all_announcements(db)

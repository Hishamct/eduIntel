from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.users import service
from app.users.dependencies import get_current_user
from app.users.models import User
from app.users.schemas import (
    AdminProfileUpdate,
    MeResponse,
    StudentProfileUpdate,
    TeacherProfileUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=MeResponse)
async def read_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_user_with_profile(db, current_user.id)


@router.put("/me", response_model=MeResponse)
async def update_my_profile(
    data: StudentProfileUpdate | TeacherProfileUpdate | AdminProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_profile(db, current_user, data.model_dump())

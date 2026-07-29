from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from app.users.models import User, StudentProfile, TeacherProfile, AdminProfile


async def get_user_with_profile(db: AsyncSession, user_id) -> User:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.student_profile),
            selectinload(User.teacher_profile),
            selectinload(User.admin_profile),
        )
        .where(User.id == user_id)
    )
    return result.scalar_one()


async def update_profile(db: AsyncSession, user: User, data: dict) -> User:
   
    user = await get_user_with_profile(db, user.id)

    profile_map = {
        "student": (user.student_profile, StudentProfile),
        "teacher": (user.teacher_profile, TeacherProfile),
        "admin": (user.admin_profile, AdminProfile),
    }
    profile, _ = profile_map[user.role]

    for field, value in data.items():
        if value is not None:
            setattr(profile, field, value)

    await db.commit()
    return await get_user_with_profile(db, user.id)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Announcement

async def get_all_announcements(db: AsyncSession):
    result = await db.execute(
        select(Announcement).order_by(Announcement.created_at.desc())
    )
    return result.scalars().all()
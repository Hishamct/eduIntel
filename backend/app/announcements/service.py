import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Announcement


async def get_all_announcements(
    db: AsyncSession,
    institution_id: uuid.UUID,
) -> list[Announcement]:
    result = await db.execute(
        select(Announcement)
        .where(Announcement.institution_id == institution_id)
        .order_by(Announcement.created_at.desc())
    )
    return result.scalars().all()


async def create_announcement(
    db: AsyncSession,
    institution_id: uuid.UUID,
    title: str,
    body: str,
    posted_by: str,
) -> Announcement:
    announcement = Announcement(
        institution_id=institution_id,
        title=title,
        body=body,
        posted_by=posted_by,
    )
    db.add(announcement)
    await db.flush()
    await db.refresh(announcement)
    return announcement

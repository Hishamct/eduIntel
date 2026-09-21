import asyncio
import uuid

from app.announcements.models import Announcement
from app.core.database import AsyncSessionLocal

SAMPLE_ANNOUNCEMENTS = [
    {
        "title": "Diwali Break Notice",
        "body": "The institute will remain closed from Oct 20 to Oct 24 for Diwali. Classes resume Oct 25.",
        "posted_by": "Admin Office",
    },
    {
        "title": "Mid-Term Exam Schedule Released",
        "body": "Mid-term exams for Grades 9-12 begin next Monday. Check the timetable section for your slot.",
        "posted_by": "Admin Office",
    },
    {
        "title": "New Study Material Uploaded",
        "body": "Chapter 5 notes for Physics (Class 11) have been uploaded by your subject teacher. Check the study materials section.",
        "posted_by": "Priya Menon",
    },
]


async def seed_announcements():
    async with AsyncSessionLocal() as db:
        for item in SAMPLE_ANNOUNCEMENTS:
            announcement = Announcement(id=uuid.uuid4(), **item)
            db.add(announcement)
        await db.commit()
    print(f"Seeded {len(SAMPLE_ANNOUNCEMENTS)} announcements.")


if __name__ == "__main__":
    asyncio.run(seed_announcements())

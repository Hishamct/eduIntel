from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from app.users.dependencies import require_role
from app.core.database import AsyncSessionLocal
from app.users.models import User, StudentProfile
from app.reports.parent_report_agent import generate_and_send_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/parent-report/{student_id}")
async def trigger_parent_report(student_id: str, current_user=Depends(require_role("admin"))):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User, StudentProfile)
            .join(StudentProfile, StudentProfile.user_id == User.id)
            .where(User.id == student_id)
        )
        row = result.first()
        if not row:
            raise HTTPException(404, "Student not found")
        user, profile = row

        if not profile.parent_email:
            raise HTTPException(400, "No parent email on file for this student")

    result = await generate_and_send_report(student_id, user.name, profile.parent_email)
    return result
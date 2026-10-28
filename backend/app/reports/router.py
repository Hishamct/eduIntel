import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.reports.parent_report_agent import generate_and_send_report
from app.users.models import StudentProfile, User

router = APIRouter(prefix="/reports", tags=["reports"])


class ParentReportPayload(BaseModel):
    parent_email: str | None = None
    student_name: str | None = None


@router.post("/parent-report/{student_id}")
async def trigger_parent_report(
    student_id: str,
    payload: ParentReportPayload | None = None,
):
    target_student_name = payload.student_name if payload and payload.student_name else None
    target_parent_email = payload.parent_email if payload and payload.parent_email else None

    # Check if student exists in database
    async with AsyncSessionLocal() as db:
        row = None
        try:
            uid = uuid.UUID(student_id)
            result = await db.execute(
                select(User, StudentProfile)
                .join(StudentProfile, StudentProfile.user_id == User.id)
                .where(User.id == uid)
            )
            row = result.first()
        except ValueError:
            pass

        if not row and target_student_name:
            result = await db.execute(
                select(User, StudentProfile)
                .join(StudentProfile, StudentProfile.user_id == User.id)
                .where(User.name.ilike(f"%{target_student_name}%"))
            )
            row = result.first()

        if row:
            user, profile = row
            target_student_name = target_student_name or user.name
            target_parent_email = target_parent_email or profile.parent_email

    if not target_student_name:
        target_student_name = "Student"

    if not target_parent_email:
        raise HTTPException(400, "No parent email provided or on file for this student")

    try:
        result = await generate_and_send_report(
            student_id=student_id,
            student_name=target_student_name,
            parent_email=target_parent_email,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to generate or deliver email via SMTP: {str(e)}",
        )

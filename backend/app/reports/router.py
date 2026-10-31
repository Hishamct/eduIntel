import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Attendance, Timetable
from app.core.database import get_db
from app.reports.parent_report_agent import generate_and_send_report
from app.student.models import HomeworkSubmission
from app.teacher.models import ExamResult
from app.users.dependencies import require_role
from app.users.models import StudentProfile, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


class ParentReportRequest(BaseModel):
    custom_message_note: str | None = None  # ZERO client recipient overrides allowed
    model_config = ConfigDict(extra="forbid")


@router.post("/parent-report/{student_id}")
async def trigger_parent_report(
    student_id: str,
    payload: ParentReportRequest | None = None,
    current_user: User = Depends(require_role("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(student_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid student UUID format",
        ) from e

    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(User.id == uid, User.role == "student")
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    student_user, profile = row
    student_section = (
        f"{profile.grade}-{profile.section}"
        if profile.grade and profile.section
        else None
    )

    # Multi-Factor Teacher Authorization Verification
    if current_user.role == "teacher":
        if not student_section:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Student is not assigned to any grade/section",
            )

        # 1. Condition A: Timetable Class Assignment
        tt_res = await db.execute(
            select(Timetable.id)
            .where(
                Timetable.teacher_id == current_user.id,
                Timetable.class_section == student_section,
            )
            .limit(1)
        )
        if not tt_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authorization denied: You are not assigned to teach this student's class section.",
            )

        # 2. Condition B: Concrete Student-Specific Academic Relationship
        # Must match at least one student-specific record entered or graded by this teacher
        exam_link = await db.execute(
            select(ExamResult.id)
            .where(
                ExamResult.student_id == uid,
                ExamResult.entered_by == current_user.id,
                ExamResult.class_section == student_section,
            )
            .limit(1)
        )
        att_link = await db.execute(
            select(Attendance.id)
            .where(
                Attendance.student_id == uid,
                Attendance.marked_by == current_user.id,
                Attendance.class_section == student_section,
            )
            .limit(1)
        )
        hw_link = await db.execute(
            select(HomeworkSubmission.id)
            .where(
                HomeworkSubmission.student_id == uid,
                HomeworkSubmission.graded_by == current_user.id,
                HomeworkSubmission.status == "graded",
            )
            .limit(1)
        )

        has_student_specific_link = (
            exam_link.scalar_one_or_none() is not None
            or att_link.scalar_one_or_none() is not None
            or hw_link.scalar_one_or_none() is not None
        )
        if not has_student_specific_link:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Authorization denied: No student-specific academic records "
                    "(entered exam scores, marked attendance, or graded homework) link you to this student."
                ),
            )

    # Strictly enforce verified parent email from database
    if not profile.parent_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student has no registered parent email on file. Update student profile before generating report.",
        )

    # Dispatch strictly to verified database email
    try:
        report_result = await generate_and_send_report(
            student_id=str(uid),
            student_name=student_user.name or "Student",
            parent_email=profile.parent_email,
            db=db,
            generated_by_user_id=current_user.id,
        )
        return report_result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Parent report generation/delivery failed | actor_id=%s | student_id=%s | error_type=%s",
            current_user.id,
            uid,
            type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Failed to generate or deliver progress report. "
                "Please contact system support if this issue persists."
            ),
        ) from e

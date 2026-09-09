from fastapi import APIRouter, Depends,HTTPException
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.users.dependencies import require_role
from app.users.models import User
from app.core.database import get_db
from app.teacher.schemas import GradeSubmission, TeacherHomeworkSubmissionRead, AssignmentCreate, AssignmentRead,StudyMaterialRead
from app.student.schemas import HomeworkSubmissionRead
from typing import List
from app.teacher.service import (
    grade_homework_submission,
    list_all_submissions,
    create_assignment,
    list_assignments,
    get_teacher_dashboard_summary,
    save_study_material, list_study_materials,
)
from app.teacher.models import Assignment
from fastapi import UploadFile, File, Form
from sqlalchemy import select


router = APIRouter(prefix="/teacher", tags=["teacher"])


@router.get("/dashboard")
async def teacher_dashboard(
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    summary = await get_teacher_dashboard_summary(db=db)
    return {
        "message": f"Welcome, {current_user.email}",
        "role": current_user.role,
        "students_assigned": summary["students_assigned"],
        "pending_grading": summary["pending_grading"],
        "flagged_students": 0,  # genuinely blocked on ml module — not built yet
    }


@router.patch("/homework/{submission_id}/grade", response_model=HomeworkSubmissionRead)
async def grade_homework(
    submission_id: uuid.UUID,
    payload: GradeSubmission,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    submission = await grade_homework_submission(
        db=db,
        submission_id=submission_id,
        grader_id=current_user.id,
        score=payload.score,
        max_score=payload.max_score,
        feedback=payload.feedback,
    )
    return submission





@router.get("/homework", response_model=List[TeacherHomeworkSubmissionRead])
async def get_all_submissions(
    status: str | None = None,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    submissions = await list_all_submissions(db=db, status_filter=status)
    return submissions


@router.post("/assignments", response_model=AssignmentRead)
async def post_assignment(
    payload: AssignmentCreate,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    assignment = await create_assignment(
        db=db,
        created_by=current_user.id,
        title=payload.title,
        subject=payload.subject,
        class_section=payload.class_section,
        due_date=payload.due_date,
        max_score=payload.max_score,
        instructions=payload.instructions,
    )
    return assignment


@router.get("/assignments", response_model=List[AssignmentRead])
async def get_assignments(
    class_section: str | None = None,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    assignments = await list_assignments(db=db, class_section=class_section)
    return assignments




@router.post("/study-materials/upload", response_model=StudyMaterialRead)
async def upload_study_material(
    subject: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("teacher")),
):
    return await save_study_material(
        db=db,
        teacher_id=current_user.id,
        subject=subject,
        title=title,
        description=description,
        file=file,
    )


@router.get("/study-materials", response_model=list[StudyMaterialRead])
async def get_study_materials(
    subject: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("teacher")),
):
    return await list_study_materials(db=db, subject=subject)

from fastapi.responses import FileResponse
from app.student.models import HomeworkSubmission

@router.get("/homework/{submission_id}/file")
async def download_homework_file(
    submission_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HomeworkSubmission).where(HomeworkSubmission.id == submission_id)
    )
    submission = result.scalar_one_or_none()

    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    return FileResponse(
        path=submission.file_path,
        filename=submission.original_filename,
    )

from app.teacher.service import list_students_for_teacher
from app.teacher.schemas import StudentListItem


@router.get("/students", response_model=List[StudentListItem])
async def get_teacher_students(
    class_section: str | None = None,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    return await list_students_for_teacher(db=db, class_section=class_section)
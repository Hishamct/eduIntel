import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.student.models import HomeworkSubmission
from app.student.schemas import (
    DoubtMessageCreate,
    DoubtThreadCreate,
    DoubtThreadRead,
    HomeworkSubmissionRead,
    StudyMaterialRead,
)
from app.student.service import (
    add_doubt_message,
    create_doubt_thread,
    get_dashboard_summary,
    list_doubt_threads,
    list_study_materials_for_student,
    save_homework_submission,
)
from app.teacher.models import StudyMaterial
from app.teacher.schemas import AssignmentRead
from app.teacher.service import list_assignments
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/student", tags=["student"])


@router.get("/dashboard")
async def student_dashboard(
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    summary = await get_dashboard_summary(db=db, student_id=current_user.id)
    return {
        "message": f"Welcome, {current_user.email}",
        "role": current_user.role,
        "homework_count": summary["pending_homework"],
        "unresolved_doubts": summary["unresolved_doubts"],
        "study_plan_ready": False,
        "recent_activity": summary["recent_activity"],
    }


@router.post("/homework/upload", response_model=HomeworkSubmissionRead)
async def upload_homework(
    subject: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    submission = await save_homework_submission(
        db=db,
        student_id=current_user.id,
        subject=subject,
        title=title,
        description=description,
        file=file,
    )
    return submission


@router.get("/homework", response_model=list[HomeworkSubmissionRead])
async def list_homework(
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HomeworkSubmission)
        .where(HomeworkSubmission.student_id == current_user.id)
        .order_by(HomeworkSubmission.created_at.desc())
    )
    submissions = result.scalars().all()
    return submissions


@router.post("/doubts", response_model=DoubtThreadRead)
async def post_doubt(
    payload: DoubtThreadCreate,
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    thread = await create_doubt_thread(
        db=db,
        student_id=current_user.id,
        subject=payload.subject,
        title=payload.title,
        body=payload.body,
    )
    return thread


@router.get("/doubts", response_model=list[DoubtThreadRead])
async def get_doubts(
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    threads = await list_doubt_threads(db=db, student_id=current_user.id)
    return threads


@router.post("/doubts/{thread_id}/messages", response_model=DoubtThreadRead)
async def reply_to_doubt(
    thread_id: uuid.UUID,
    payload: DoubtMessageCreate,
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    thread = await add_doubt_message(
        db=db,
        thread_id=thread_id,
        sender_id=current_user.id,
        sender_role=current_user.role,
        body=payload.body,
    )
    return thread


@router.get("/assignments", response_model=list[AssignmentRead])
async def get_student_assignments(
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    # NOTE: no real class enrollment yet — see memory note on this scope gap.
    # For now, returns ALL assignments regardless of section, since we can't
    # filter by "this student's actual section" without a real enrollment link
    # (StudentProfile.section exists but isn't cross-checked here yet).
    assignments = await list_assignments(db=db, class_section=None)
    return assignments


@router.get("/study-materials", response_model=list[StudyMaterialRead])
async def get_study_materials(
    subject: str | None = None,
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    return await list_study_materials_for_student(db=db, subject=subject)


@router.get("/study-materials/{material_id}/file")
async def download_study_material_file(
    material_id: uuid.UUID,
    current_user: User = Depends(require_role("student")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StudyMaterial).where(StudyMaterial.id == material_id)
    )
    material = result.scalar_one_or_none()

    if material is None:
        raise HTTPException(status_code=404, detail="Study material not found")

    return FileResponse(
        path=material.file_path,
        filename=material.original_filename,
    )

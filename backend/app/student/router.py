import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Timetable
from app.core.tenant import TenantContext, get_tenant_db, require_tenant_role
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
from app.users.models import StudentProfile, User

router = APIRouter(prefix="/student", tags=["student"])


@router.get("/dashboard")
async def student_dashboard(
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    summary = await get_dashboard_summary(
        db=db,
        institution_id=tenant.institution_id,
        student_id=current_user.id,
    )
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
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    # SEC-S3-02: Sanitize uploaded filename before passing to storage or persisting metadata
    raw_filename = file.filename or "upload"
    sanitized_filename = os.path.basename(raw_filename.replace("\\", "/")).strip() or "upload"
    file.filename = sanitized_filename

    submission = await save_homework_submission(
        db=db,
        institution_id=tenant.institution_id,
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
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        select(HomeworkSubmission)
        .where(
            HomeworkSubmission.institution_id == tenant.institution_id,
            HomeworkSubmission.student_id == current_user.id,
        )
        .order_by(HomeworkSubmission.created_at.desc())
    )
    submissions = result.scalars().all()
    return submissions


@router.post("/doubts", response_model=DoubtThreadRead)
async def post_doubt(
    payload: DoubtThreadCreate,
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    thread = await create_doubt_thread(
        db=db,
        institution_id=tenant.institution_id,
        student_id=current_user.id,
        subject=payload.subject,
        title=payload.title,
        body=payload.body,
    )
    return thread


@router.get("/doubts", response_model=list[DoubtThreadRead])
async def get_doubts(
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    threads = await list_doubt_threads(
        db=db,
        institution_id=tenant.institution_id,
        student_id=current_user.id,
    )
    return threads


@router.post("/doubts/{thread_id}/messages", response_model=DoubtThreadRead)
async def reply_to_doubt(
    thread_id: uuid.UUID,
    payload: DoubtMessageCreate,
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    thread = await add_doubt_message(
        db=db,
        institution_id=tenant.institution_id,
        thread_id=thread_id,
        sender_id=current_user.id,
        sender_role=current_user.role,
        body=payload.body,
    )
    return thread


@router.get("/assignments", response_model=list[AssignmentRead])
async def get_student_assignments(
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    prof_res = await db.execute(
        select(StudentProfile).where(
            StudentProfile.user_id == current_user.id,
            StudentProfile.institution_id == tenant.institution_id,
        )
    )
    profile = prof_res.scalar_one_or_none()
    student_section = f"{profile.grade}-{profile.section}" if profile and profile.grade and profile.section else None
    assignments = await list_assignments(
        db=db,
        institution_id=tenant.institution_id,
        class_section=student_section,
    )
    return assignments


@router.get("/study-materials", response_model=list[StudyMaterialRead])
async def get_study_materials(
    subject: str | None = None,
    current_user: User = Depends(require_role("student")),
    tenant: TenantContext = Depends(require_tenant_role("student")),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await list_study_materials_for_student(
        db=db,
        institution_id=tenant.institution_id,
        subject=subject,
    )


@router.get("/study-materials/{material_id}/file")
async def download_study_material_file(
    material_id: uuid.UUID,
    current_user: User = Depends(require_role("student", "teacher", "admin")),
    tenant: TenantContext = Depends(require_tenant_role("student", "teacher", "admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Downloads a study material file with IDOR and tenant protection:
    - Verifies the study material exists within the caller's institution.
    - If caller is a student:
        - Resolves the student's profile and class section within the caller's institution.
        - Verifies that the student's class section is taught this subject on the institutional Timetable.
    - If caller is a teacher:
        - Verifies that the teacher uploaded the material or teaches that subject within the caller's institution.
    - Universal authorization for administrators within the caller's institution.
    - Validates file presence on disk.
    """
    result = await db.execute(
        select(StudyMaterial).where(
            StudyMaterial.id == material_id,
            StudyMaterial.institution_id == tenant.institution_id,
        )
    )
    material = result.scalar_one_or_none()

    if material is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Study material not found",
        )

    if tenant.role == "student":
        prof_res = await db.execute(
            select(StudentProfile).where(
                StudentProfile.user_id == current_user.id,
                StudentProfile.institution_id == tenant.institution_id,
            )
        )
        profile = prof_res.scalar_one_or_none()
        student_section = (
            f"{profile.grade}-{profile.section}" if profile and profile.grade and profile.section else None
        )
        if not student_section:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Student is not assigned to any grade/section",
            )

        # Check if student's section is scheduled for this subject by this teacher or in this section
        tt_res = await db.execute(
            select(Timetable.id)
            .where(
                Timetable.institution_id == tenant.institution_id,
                Timetable.class_section == student_section,
                Timetable.subject.ilike(material.subject),
            )
            .limit(1)
        )
        if not tt_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authorization denied: You are not enrolled in any class section for this subject.",
            )

    elif tenant.role == "teacher":
        is_owner = material.teacher_id == current_user.id
        if not is_owner:
            tt_res = await db.execute(
                select(Timetable.id)
                .where(
                    Timetable.institution_id == tenant.institution_id,
                    Timetable.teacher_id == current_user.id,
                    Timetable.subject.ilike(material.subject),
                )
                .limit(1)
            )
            if not tt_res.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Authorization denied: You do not teach this subject.",
                )

    if not os.path.exists(material.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Study material file not found on disk",
        )

    return FileResponse(
        path=material.file_path,
        filename=material.original_filename,
    )

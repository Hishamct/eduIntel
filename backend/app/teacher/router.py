import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Timetable
from app.core.tenant import TenantContext, get_tenant_db, require_tenant_role
from app.student.models import HomeworkSubmission
from app.student.schemas import HomeworkSubmissionRead
from app.teacher.schemas import (
    AssignmentCreate,
    AssignmentRead,
    GradeSubmission,
    StudentListItem,
    StudyMaterialRead,
    TeacherHomeworkSubmissionRead,
)
from app.teacher.service import (
    create_assignment,
    get_teacher_dashboard_summary,
    grade_homework_submission,
    list_all_submissions,
    list_assignments,
    list_students_for_teacher,
    list_study_materials,
    save_study_material,
)
from app.users.dependencies import require_role
from app.users.models import StudentProfile, User

router = APIRouter(prefix="/teacher", tags=["teacher"])


@router.get("/dashboard")
async def teacher_dashboard(
    current_user: User = Depends(require_role("teacher")),
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    summary = await get_teacher_dashboard_summary(db=db, institution_id=tenant.institution_id)
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
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    submission = await grade_homework_submission(
        db=db,
        institution_id=tenant.institution_id,
        submission_id=submission_id,
        grader_id=current_user.id,
        score=payload.score,
        max_score=payload.max_score,
        feedback=payload.feedback,
    )
    return submission


@router.get("/homework", response_model=list[TeacherHomeworkSubmissionRead])
async def get_all_submissions(
    status: str | None = None,
    limit: int = 100,
    current_user: User = Depends(require_role("teacher")),
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    submissions = await list_all_submissions(
        db=db,
        institution_id=tenant.institution_id,
        status_filter=status,
        limit=limit,
    )
    return submissions


@router.post("/assignments", response_model=AssignmentRead)
async def post_assignment(
    payload: AssignmentCreate,
    current_user: User = Depends(require_role("teacher")),
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    assignment = await create_assignment(
        db=db,
        institution_id=tenant.institution_id,
        created_by=current_user.id,
        title=payload.title,
        subject=payload.subject,
        class_section=payload.class_section,
        due_date=payload.due_date,
        max_score=payload.max_score,
        instructions=payload.instructions,
    )
    return assignment


@router.get("/assignments", response_model=list[AssignmentRead])
async def get_assignments(
    class_section: str | None = None,
    current_user: User = Depends(require_role("teacher")),
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    assignments = await list_assignments(
        db=db,
        institution_id=tenant.institution_id,
        class_section=class_section,
    )
    return assignments


@router.post("/study-materials/upload", response_model=StudyMaterialRead)
async def upload_study_material(
    subject: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("teacher")),
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await save_study_material(
        db=db,
        institution_id=tenant.institution_id,
        teacher_id=current_user.id,
        subject=subject,
        title=title,
        description=description,
        file=file,
    )


@router.get("/study-materials", response_model=list[StudyMaterialRead])
async def get_study_materials(
    subject: str | None = None,
    current_user: User = Depends(require_role("teacher")),
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await list_study_materials(
        db=db,
        institution_id=tenant.institution_id,
        subject=subject,
    )


@router.get("/homework/{submission_id}/file")
async def download_homework_file(
    submission_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher", "admin")),
    tenant: TenantContext = Depends(require_tenant_role("teacher", "admin")),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Downloads a student's homework submission file with IDOR and tenant protection:
    - Verifies the submission exists within the caller's institution.
    - Resolves the student's profile and class section within the caller's institution.
    - Restricts teachers to either:
        a) Being assigned to the student's class section on the institutional Timetable.
        b) Being the designated grader of the submission.
    - Universal authorization for administrators within the institution.
    - Validates file presence on disk.
    """
    result = await db.execute(
        select(HomeworkSubmission, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == HomeworkSubmission.student_id)
        .where(
            HomeworkSubmission.id == submission_id,
            HomeworkSubmission.institution_id == tenant.institution_id,
            StudentProfile.institution_id == tenant.institution_id,
        )
    )
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    submission, profile = row
    student_section = f"{profile.grade}-{profile.section}" if profile.grade and profile.section else None

    if current_user.role == "teacher":
        is_assigned_teacher = False
        if student_section:
            tt_res = await db.execute(
                select(Timetable.id)
                .where(
                    Timetable.institution_id == tenant.institution_id,
                    Timetable.teacher_id == current_user.id,
                    Timetable.class_section == student_section,
                )
                .limit(1)
            )
            is_assigned_teacher = tt_res.scalar_one_or_none() is not None

        is_grader = submission.graded_by == current_user.id

        if not is_assigned_teacher and not is_grader:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Authorization denied: You are not assigned to teach this student's "
                    "class section or grade this submission."
                ),
            )

    if not os.path.exists(submission.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission file not found on disk",
        )

    return FileResponse(
        path=submission.file_path,
        filename=submission.original_filename,
    )


@router.get("/students", response_model=list[StudentListItem])
async def get_teacher_students(
    class_section: str | None = None,
    current_user: User = Depends(require_role("teacher")),
    tenant: TenantContext = Depends(require_tenant_role("teacher")),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await list_students_for_teacher(
        db=db,
        institution_id=tenant.institution_id,
        class_section=class_section,
    )

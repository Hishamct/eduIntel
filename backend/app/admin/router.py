import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import (
    SalaryRecordCreate,
    SalaryRecordRead,
    StudentEnrollCreate,
    StudentRead,
    StudentUpdate,
    TeacherSummary,
    TimetableEntryCreate,
    TimetableEntryRead,
)
from app.admin.service import (
    create_salary_record,
    create_timetable_entry,
    enroll_student,
    get_admin_dashboard_summary,
    list_salary_records,
    list_students,
    list_teachers,
    list_timetable,
    update_student_profile,
)
from app.core.database import get_db
from app.users.dependencies import require_role
from app.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard")
async def admin_dashboard(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    summary = await get_admin_dashboard_summary(db=db)
    display_name = current_user.name or current_user.email.split("@")[0]
    return {
        "message": f"Welcome, {display_name}",
        "name": display_name,
        "role": current_user.role,
        "total_students": summary["total_students"],
        "total_teachers": summary["total_teachers"],
        "revenue_this_month": 0, 
    }


@router.post("/timetable", response_model=TimetableEntryRead)
async def post_timetable_entry(
    payload: TimetableEntryCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    entry = await create_timetable_entry(
        db=db,
        created_by=current_user.id,
        class_section=payload.class_section,
        day_of_week=payload.day_of_week,
        period=payload.period,
        subject=payload.subject,
        teacher_id=payload.teacher_id,
    )
    return entry


@router.get("/timetable", response_model=list[TimetableEntryRead])
async def get_timetable(
    class_section: str | None = None,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    entries = await list_timetable(db=db, class_section=class_section)
    return entries


@router.post("/salary", response_model=SalaryRecordRead)
async def post_salary_record(
    payload: SalaryRecordCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    record = await create_salary_record(
        db=db,
        created_by=current_user.id,
        teacher_id=payload.teacher_id,
        month=payload.month,
        base_salary=payload.base_salary,
        bonus=payload.bonus,
        deduction=payload.deduction,
        payment_status=payload.payment_status,
    )
    return record


@router.get("/salary", response_model=list[SalaryRecordRead])
async def get_salary_records(
    teacher_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    records = await list_salary_records(db=db, teacher_id=teacher_id)
    return records


@router.get("/teachers", response_model=list[TeacherSummary])
async def get_teachers(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    teachers = await list_teachers(db=db)
    return teachers


@router.post("/students", response_model=StudentRead)
async def post_student(
    payload: StudentEnrollCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    student = await enroll_student(
        db=db,
        email=payload.email,
        password=payload.password,
        name=payload.name,
        grade=payload.grade,
        section=payload.section,
        roll_number=payload.roll_number,
        parent_email=payload.parent_email,
        phone=payload.phone,
        address=payload.address,
        guardian_name=payload.guardian_name,
        guardian_phone=payload.guardian_phone,
    )
    return student


@router.get("/students", response_model=list[StudentRead])
async def get_students(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    students = await list_students(db=db)
    return students


from datetime import date

from app.admin.service import (
    get_attendance_stats,
    get_revenue_summary,
    get_salary_summary,
    get_student_teacher_counts,
    get_teacher_grading_performance,
    get_timetable_coverage,
)

# add StudentUpdate to the schemas import, update_student_profile to the service import


@router.patch("/students/{student_id}", response_model=StudentRead)
async def patch_student(
    student_id: uuid.UUID,
    payload: StudentUpdate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    student = await update_student_profile(
        db=db,
        student_id=student_id,
        grade=payload.grade,
        section=payload.section,
        roll_number=payload.roll_number,
        parent_email=payload.parent_email,
        phone=payload.phone,
        address=payload.address,
        guardian_name=payload.guardian_name,
        guardian_phone=payload.guardian_phone,
    )
    return student


@router.get("/debug/student-teacher-counts")
async def debug_student_teacher_counts(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await get_student_teacher_counts(db=db)


@router.get("/debug/salary-summary")
async def debug_salary_summary(
    month: date | None = None,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await get_salary_summary(db=db, month=month)


@router.get("/debug/timetable-coverage")
async def debug_timetable_coverage(
    class_section: str | None = None,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await get_timetable_coverage(db=db, class_section=class_section)


@router.get("/debug/teacher-grading-performance")
async def debug_teacher_grading_performance(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await get_teacher_grading_performance(db=db)


@router.get("/debug/revenue-summary")
async def debug_revenue_summary(
    month: date | None = None,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await get_revenue_summary(db=db, month=month)


@router.get("/debug/attendance-stats")
async def debug_attendance_stats(
    class_section: str | None = None,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await get_attendance_stats(db=db, class_section=class_section)

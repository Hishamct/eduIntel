from sqlalchemy.ext.asyncio import AsyncSession
from app.admin.models import Timetable, SalaryRecord
import uuid
from sqlalchemy import select, func
from fastapi import HTTPException
from app.auth.security import hash_password
from app.users.models import User, StudentProfile
from datetime import date
from sqlalchemy.orm import selectinload
from app.student.models import HomeworkSubmission

async def create_timetable_entry(
    db: AsyncSession,
    created_by: uuid.UUID,
    class_section: str,
    day_of_week: str,
    period: int,
    subject: str,
    teacher_id: uuid.UUID | None,
) -> Timetable:
    entry = Timetable(
        class_section=class_section,
        day_of_week=day_of_week,
        period=period,
        subject=subject,
        teacher_id=teacher_id,
        created_by=created_by,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def list_timetable(db: AsyncSession, class_section: str | None = None):
    query = select(Timetable).order_by(Timetable.day_of_week, Timetable.period)
    if class_section:
        query = query.where(Timetable.class_section == class_section)
    result = await db.execute(query)
    return result.scalars().all()


async def create_salary_record(
    db: AsyncSession,
    created_by: uuid.UUID,
    teacher_id: uuid.UUID,
    month,
    base_salary: float,
    bonus: float,
    deduction: float,
    payment_status: str,
) -> SalaryRecord:
    record = SalaryRecord(
        teacher_id=teacher_id,
        month=month,
        base_salary=base_salary,
        bonus=bonus,
        deduction=deduction,
        payment_status=payment_status,
        created_by=created_by,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def list_salary_records(db: AsyncSession, teacher_id: uuid.UUID | None = None):
    query = select(SalaryRecord).order_by(SalaryRecord.month.desc())
    if teacher_id:
        query = query.where(SalaryRecord.teacher_id == teacher_id)
    result = await db.execute(query)
    return result.scalars().all()




async def list_teachers(db: AsyncSession):
    result = await db.execute(select(User).where(User.role == "teacher"))
    return result.scalars().all()

async def get_admin_dashboard_summary(db: AsyncSession) -> dict:
    students_result = await db.execute(
        select(func.count()).select_from(User).where(User.role == "student")
    )
    total_students = students_result.scalar_one()

    teachers_result = await db.execute(
        select(func.count()).select_from(User).where(User.role == "teacher")
    )
    total_teachers = teachers_result.scalar_one()

    return {
        "total_students": total_students,
        "total_teachers": total_teachers,
    }




async def enroll_student(
    db: AsyncSession,
    email: str,
    password: str,
    name: str,
    grade: str | None,
    section: str | None,
    roll_number: str | None,
    parent_email: str | None,
    phone: str | None,
    address: str | None,
    guardian_name: str | None,
    guardian_phone: str | None,
) -> dict:
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="A user with this email already exists")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        name=name,
        role="student",
    )
    db.add(user)
    await db.flush()  # assigns user.id without committing yet

    profile = StudentProfile(
        user_id=user.id,
        grade=grade,
        section=section,
        roll_number=roll_number,
        parent_email=parent_email,
        phone=phone,
        address=address,
        guardian_name=guardian_name,
        guardian_phone=guardian_phone,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(user)
    await db.refresh(profile)

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "grade": profile.grade,
        "section": profile.section,
        "roll_number": profile.roll_number,
        "parent_email": profile.parent_email,
        "phone": profile.phone,
        "address": profile.address,
        "guardian_name": profile.guardian_name,
        "guardian_phone": profile.guardian_phone,
        "created_at": user.created_at,
    }


async def list_students(db: AsyncSession):
    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(User.role == "student")
        .order_by(User.created_at.desc())
    )
    rows = result.all()

    return [
        {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "grade": profile.grade,
            "section": profile.section,
            "roll_number": profile.roll_number,
            "parent_email": profile.parent_email,
            "phone": profile.phone,
            "address": profile.address,
            "guardian_name": profile.guardian_name,
            "guardian_phone": profile.guardian_phone,
            "created_at": user.created_at,
        }
        for user, profile in rows
    ]


from app.admin.models import FeeRecord, Attendance


async def get_revenue_summary(db: AsyncSession, month: date | None = None) -> dict:
    """Real revenue data from FeeRecord. Filters to a given month if provided."""
    query = select(FeeRecord)
    if month:
        query = query.where(
            func.extract("year", FeeRecord.due_date) == month.year,
            func.extract("month", FeeRecord.due_date) == month.month,
        )
    result = await db.execute(query)
    records = result.scalars().all()

    collected = sum(float(r.amount) for r in records if r.payment_status == "paid")
    pending = sum(float(r.amount) for r in records if r.payment_status == "pending")
    overdue = sum(float(r.amount) for r in records if r.payment_status == "overdue")

    return {
        "total_collected": round(collected, 2),
        "total_pending": round(pending, 2),
        "total_overdue": round(overdue, 2),
        "record_count": len(records),
        "overdue_count": len([r for r in records if r.payment_status == "overdue"]),
    }


async def get_attendance_stats(db: AsyncSession, class_section: str | None = None) -> dict:
    """Real attendance data from Attendance. Computes attendance % overall and per section."""
    query = select(Attendance)
    if class_section:
        query = query.where(Attendance.class_section == class_section)
    result = await db.execute(query)
    records = result.scalars().all()

    if not records:
        return {"sections": {}, "overall_attendance_percent": None, "total_records": 0}

    by_section: dict[str, dict] = {}
    for r in records:
        sec = by_section.setdefault(r.class_section, {"present": 0, "absent": 0, "late": 0, "total": 0})
        sec[r.status] += 1
        sec["total"] += 1

    for sec_data in by_section.values():
        sec_data["attendance_percent"] = round(
            (sec_data["present"] + sec_data["late"]) / sec_data["total"] * 100, 1
        )

    total_present = sum(1 for r in records if r.status in ("present", "late"))
    overall_percent = round(total_present / len(records) * 100, 1)

    return {
        "sections": by_section,
        "overall_attendance_percent": overall_percent,
        "total_records": len(records),
    }

async def get_student_teacher_counts(db: AsyncSession) -> dict:
    students_result = await db.execute(
        select(func.count()).select_from(User).where(User.role == "student")
    )
    total_students = students_result.scalar_one()

    teachers_result = await db.execute(
        select(func.count()).select_from(User).where(User.role == "teacher")
    )
    total_teachers = teachers_result.scalar_one()

    return {
        "total_students": total_students,
        "total_teachers": total_teachers,
    }


async def get_salary_summary(db: AsyncSession, month: date | None = None) -> dict:
    query = select(SalaryRecord)
    if month:
        query = query.where(
            func.extract("year", SalaryRecord.month) == month.year,
            func.extract("month", SalaryRecord.month) == month.month,
        )
    result = await db.execute(query)
    records = result.scalars().all()

    total_base = sum(float(r.base_salary) for r in records)
    total_bonus = sum(float(r.bonus) for r in records)
    total_deduction = sum(float(r.deduction) for r in records)
    total_payout = total_base + total_bonus - total_deduction

    pending = [r for r in records if r.payment_status == "pending"]
    paid = [r for r in records if r.payment_status == "paid"]

    return {
        "record_count": len(records),
        "total_payout": round(total_payout, 2),
        "total_base_salary": round(total_base, 2),
        "total_bonus": round(total_bonus, 2),
        "total_deduction": round(total_deduction, 2),
        "pending_count": len(pending),
        "pending_teacher_ids": [str(r.teacher_id) for r in pending],
        "paid_count": len(paid),
    }


async def get_timetable_coverage(db: AsyncSession, class_section: str | None = None) -> dict:
    query = select(Timetable)
    if class_section:
        query = query.where(Timetable.class_section == class_section)
    result = await db.execute(query)
    entries = result.scalars().all()

    by_section: dict[str, dict] = {}
    for entry in entries:
        sec = by_section.setdefault(entry.class_section, {"total_periods": 0, "unassigned_periods": 0})
        sec["total_periods"] += 1
        if entry.teacher_id is None:
            sec["unassigned_periods"] += 1

    return {
        "sections": by_section,
        "total_entries": len(entries),
    }


async def get_teacher_grading_performance(db: AsyncSession) -> dict:
    result = await db.execute(
        select(HomeworkSubmission)
        .options(selectinload(HomeworkSubmission.grader))
        .where(HomeworkSubmission.status == "graded")
        .where(HomeworkSubmission.graded_by.isnot(None))
    )
    graded_submissions = result.scalars().all()

    by_teacher: dict[str, dict] = {}
    for sub in graded_submissions:
        teacher_key = str(sub.graded_by)
        turnaround_hours = (sub.updated_at - sub.created_at).total_seconds() / 3600

        entry = by_teacher.setdefault(teacher_key, {
            "teacher_email": sub.grader.email if sub.grader else "unknown",
            "graded_count": 0,
            "_turnaround_sum_hours": 0.0,
        })
        entry["graded_count"] += 1
        entry["_turnaround_sum_hours"] += turnaround_hours

    for entry in by_teacher.values():
        entry["avg_turnaround_hours"] = round(
            entry["_turnaround_sum_hours"] / entry["graded_count"], 1
        )
        del entry["_turnaround_sum_hours"]

    return {"teachers": by_teacher, "total_graded_submissions": len(graded_submissions)}
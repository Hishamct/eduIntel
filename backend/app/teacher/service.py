from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.student.models import HomeworkSubmission
import uuid
from sqlalchemy.orm import selectinload
from app.teacher.schemas import TeacherHomeworkSubmissionRead
from app.teacher.models import Assignment
from sqlalchemy import select,func
import os
import aiofiles
from fastapi import UploadFile
import logging
from app.teacher.models import StudyMaterial
from app.ocr import service as ocr_service
from app.rag.service import ingest_study_material

logger = logging.getLogger(__name__)

STUDY_MATERIAL_UPLOAD_DIR = "uploads/study_materials"

async def grade_homework_submission(
    db: AsyncSession,
    submission_id: uuid.UUID,
    grader_id: uuid.UUID,
    score: int,
    max_score: int,
    feedback: str | None,
) -> HomeworkSubmission:
    result = await db.execute(
        select(HomeworkSubmission).where(HomeworkSubmission.id == submission_id)
    )
    submission = result.scalar_one_or_none()

    if submission is None:
        raise HTTPException(status_code=404, detail="Homework submission not found")

    # NOTE: no ownership/class-assignment check yet — see memory note on this gap.
    # Once admin module defines teacher-class-student assignments, verify here
    # that grader_id is actually assigned to submission.student_id's class/section
    # before allowing the grade to proceed.

    submission.score = score
    submission.max_score = max_score
    submission.feedback = feedback
    submission.graded_by = grader_id
    submission.status = "graded"

    await db.commit()
    await db.refresh(submission)

    return submission


async def list_all_submissions(db: AsyncSession, status_filter: str | None = None):
    query = (
        select(HomeworkSubmission)
        .options(selectinload(HomeworkSubmission.student))
        .order_by(HomeworkSubmission.created_at.desc())
    )
    if status_filter:
        query = query.where(HomeworkSubmission.status == status_filter)
    result = await db.execute(query)
    submissions = result.scalars().all()

    return [
        TeacherHomeworkSubmissionRead(
            id=s.id,
            student_id=s.student_id,
            student_email=s.student.email,
            subject=s.subject,
            title=s.title,
            description=s.description,
            original_filename=s.original_filename,
            status=s.status,
            created_at=s.created_at,
            score=s.score,
            max_score=s.max_score,
            feedback=s.feedback,
            extracted_text=s.extracted_text,
            ocr_confidence=s.ocr_confidence,
        )
        for s in submissions
    ]


async def create_assignment(
    db: AsyncSession,
    created_by: uuid.UUID,
    title: str,
    subject: str,
    class_section: str,
    due_date,
    max_score: int,
    instructions: str | None,
) -> Assignment:
    assignment = Assignment(
        title=title,
        subject=subject,
        class_section=class_section,
        due_date=due_date,
        max_score=max_score,
        instructions=instructions,
        created_by=created_by,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def list_assignments(db: AsyncSession, class_section: str | None = None):
    query = select(Assignment).order_by(Assignment.created_at.desc())
    if class_section:
        query = query.where(Assignment.class_section == class_section)
    result = await db.execute(query)
    return result.scalars().all()

async def get_teacher_dashboard_summary(db: AsyncSession) -> dict:
    pending_result = await db.execute(
        select(func.count()).select_from(HomeworkSubmission)
        .where(HomeworkSubmission.status == "submitted")
    )
    pending_grading = pending_result.scalar_one()

    students_result = await db.execute(
        select(func.count(func.distinct(HomeworkSubmission.student_id)))
        .select_from(HomeworkSubmission)
    )
    students_assigned = students_result.scalar_one()

    return {
        "pending_grading": pending_grading,
        "students_assigned": students_assigned,
    }




async def save_study_material(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    subject: str,
    title: str,
    description: str | None,
    file: UploadFile,
) -> StudyMaterial:
    os.makedirs(STUDY_MATERIAL_UPLOAD_DIR, exist_ok=True)

    file_id = uuid.uuid4()
    safe_filename = f"{file_id}_{file.filename}"
    file_path = os.path.join(STUDY_MATERIAL_UPLOAD_DIR, safe_filename)

    contents = await file.read()
    async with aiofiles.open(file_path, "wb") as out_file:
        await out_file.write(contents)

    extracted_text = None
    extraction_method = None

    if file.content_type in {"image/jpeg", "image/png", "image/jpg", "image/webp"}:
        try:
            result = ocr_service.extract_text(contents)
            extracted_text = result["extracted_text"]
            extraction_method = "ocr"
        except HTTPException as e:
            logger.warning(f"OCR failed for study material upload: {e.detail}")

    elif file.content_type == "application/pdf":
        try:
            result = ocr_service.extract_text_from_pdf(contents)
            extracted_text = result["extracted_text"]
            extraction_method = "pdf_text"
        except HTTPException as e:
            logger.warning(f"PDF extraction failed for study material upload: {e.detail}")

    material = StudyMaterial(
        teacher_id=teacher_id,
        subject=subject,
        title=title,
        description=description,
        file_path=file_path,
        original_filename=file.filename,
        extracted_text=extracted_text,
        extraction_method=extraction_method,
    )

    db.add(material)
    await db.commit()
    await db.refresh(material)

    if extracted_text:
        try:
            ingest_study_material(
                material_id=material.id,
                subject=material.subject,
                title=material.title,
                extracted_text=extracted_text,
            )
        except Exception as e:
            logger.warning(f"RAG ingestion failed for study material {material.id}: {e}")

    return material


async def list_study_materials(db: AsyncSession, subject: str | None = None):
    query = select(StudyMaterial).order_by(StudyMaterial.created_at.desc())
    if subject:
        query = query.where(StudyMaterial.subject == subject)
    result = await db.execute(query)
    return result.scalars().all()

from app.users.models import User, StudentProfile
from sqlalchemy import select


async def list_students_for_teacher(db: AsyncSession, class_section: str | None = None):
    query = (
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(User.role == "student")
        .order_by(User.name)
    )
    if class_section:
        # class_section like "10-A" — StudentProfile stores grade/section separately
        grade, _, section = class_section.partition("-")
        query = query.where(StudentProfile.grade == grade, StudentProfile.section == section)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "grade": profile.grade,
            "section": profile.section,
            "roll_number": profile.roll_number,
        }
        for user, profile in rows
    ]
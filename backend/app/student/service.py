import logging
import os
import uuid

import aiofiles
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ocr import service as ocr_service
from app.student.models import DoubtMessage, DoubtThread, HomeworkSubmission
from app.teacher.models import StudyMaterial

logger = logging.getLogger(__name__)
UPLOAD_DIR = "uploads/homework"


async def save_homework_submission(
    db: AsyncSession,
    student_id: uuid.UUID,
    subject: str,
    title: str,
    description: str | None,
    file: UploadFile,
) -> HomeworkSubmission:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    file_id = uuid.uuid4()
    safe_filename = f"{file_id}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    contents = await file.read()
    async with aiofiles.open(file_path, "wb") as out_file:
        await out_file.write(contents)

    extracted_text = None
    ocr_confidence = None

    if file.content_type in {"image/jpeg", "image/png", "image/jpg", "image/webp"}:
        try:
            ocr_result = ocr_service.extract_text(contents)
            extracted_text = ocr_result["extracted_text"]
            ocr_confidence = ocr_result["confidence"]
        except HTTPException as e:
            logger.warning(f"OCR failed for homework upload: {e.detail}")

    submission = HomeworkSubmission(
        student_id=student_id,
        subject=subject,
        title=title,
        description=description,
        file_path=file_path,
        original_filename=file.filename,
        extracted_text=extracted_text,
        ocr_confidence=ocr_confidence,
    )

    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    return submission


async def create_doubt_thread(
    db: AsyncSession,
    student_id: uuid.UUID,
    subject: str,
    title: str,
    body: str,
) -> DoubtThread:
    thread = DoubtThread(
        student_id=student_id,
        subject=subject,
        title=title,
    )
    db.add(thread)
    await db.flush()  # assigns thread.id without committing yet

    first_message = DoubtMessage(
        thread_id=thread.id,
        sender_id=student_id,
        sender_role="student",
        body=body,
    )
    db.add(first_message)

    await db.commit()

    # Re-fetch with messages eagerly loaded, so the response has the full thread
    result = await db.execute(
        select(DoubtThread)
        .options(selectinload(DoubtThread.messages))
        .where(DoubtThread.id == thread.id)
    )
    return result.scalar_one()


async def add_doubt_message(
    db: AsyncSession,
    thread_id: uuid.UUID,
    sender_id: uuid.UUID,
    sender_role: str,
    body: str,
) -> DoubtThread:
    message = DoubtMessage(
        thread_id=thread_id,
        sender_id=sender_id,
        sender_role=sender_role,
        body=body,
    )
    db.add(message)
    await db.commit()

    result = await db.execute(
        select(DoubtThread)
        .options(selectinload(DoubtThread.messages))
        .where(DoubtThread.id == thread_id)
    )
    return result.scalar_one()


async def list_doubt_threads(
    db: AsyncSession, student_id: uuid.UUID
) -> list[DoubtThread]:
    result = await db.execute(
        select(DoubtThread)
        .options(selectinload(DoubtThread.messages))
        .where(DoubtThread.student_id == student_id)
        .order_by(DoubtThread.created_at.desc())
    )
    return result.scalars().all()


async def get_dashboard_summary(db: AsyncSession, student_id: uuid.UUID) -> dict:
    homework_count_result = await db.execute(
        select(func.count())
        .select_from(HomeworkSubmission)
        .where(
            HomeworkSubmission.student_id == student_id,
            HomeworkSubmission.status == "submitted",
        )
    )
    pending_homework = homework_count_result.scalar_one()

    doubts_count_result = await db.execute(
        select(func.count())
        .select_from(DoubtThread)
        .where(DoubtThread.student_id == student_id, DoubtThread.status == "open")
    )
    unresolved_doubts = doubts_count_result.scalar_one()

    recent_homework = await db.execute(
        select(HomeworkSubmission)
        .where(HomeworkSubmission.student_id == student_id)
        .order_by(HomeworkSubmission.created_at.desc())
        .limit(3)
    )
    recent_doubts = await db.execute(
        select(DoubtThread)
        .where(DoubtThread.student_id == student_id)
        .order_by(DoubtThread.created_at.desc())
        .limit(3)
    )

    activity = []
    for hw in recent_homework.scalars().all():
        activity.append(
            {
                "type": "homework",
                "text": f'Submitted "{hw.title}" ({hw.subject})',
                "timestamp": hw.created_at,
            }
        )
    for doubt in recent_doubts.scalars().all():
        activity.append(
            {
                "type": "doubt",
                "text": f'Asked a doubt: "{doubt.title}" ({doubt.subject})',
                "timestamp": doubt.created_at,
            }
        )

    activity.sort(key=lambda x: x["timestamp"], reverse=True)
    activity = activity[:5]

    return {
        "pending_homework": pending_homework,
        "unresolved_doubts": unresolved_doubts,
        "recent_activity": activity,
    }


async def list_study_materials_for_student(
    db: AsyncSession, subject: str | None = None
):
    query = select(StudyMaterial).order_by(StudyMaterial.created_at.desc())
    if subject:
        query = query.where(StudyMaterial.subject == subject)
    result = await db.execute(query)
    return result.scalars().all()

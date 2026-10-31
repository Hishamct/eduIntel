import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Timetable
from app.core.database import get_db
from app.core.tenant import get_trusted_tenant_id
from app.ml.diagnosis import diagnose_student
from app.ml.explain import get_at_risk_explanation
from app.ml.recommendations import get_recommendations_for_weak_topics
from app.ml.schemas import AtRiskPrediction, WeakTopicResponse
from app.ml.service import get_at_risk_prediction, get_weak_topic_predictions
from app.ml.worksheet_generator import generate_worksheet_pdf
from app.users.dependencies import require_role
from app.users.models import StudentProfile, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml", tags=["ml"])


async def authorize_student_ml_access(
    student_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> tuple[User, StudentProfile]:
    """
    Validates access to student ML diagnostics:
    1. Verifies the target student exists, has role 'student', and has a StudentProfile (404 otherwise).
    2. Administrators have universal platform access to student ML diagnostics.
    3. Teachers require:
       a) Student must have a valid grade and section (403 if unassigned).
       b) Teacher must have an assigned Timetable entry for that class_section (403 if unassigned).
    4. Any other role is forbidden (403).
    """
    result = await db.execute(
        select(User, StudentProfile)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .where(User.id == student_id, User.role == "student")
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    student_user, profile = row

    if current_user.role == "admin":
        return student_user, profile

    if current_user.role == "teacher":
        if not profile.grade or not profile.section:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Student is not assigned to any grade/section",
            )

        student_section = f"{profile.grade}-{profile.section}"
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
        return student_user, profile

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden",
    )


@router.get("/predict/at-risk/{student_id}", response_model=AtRiskPrediction)
async def predict_at_risk(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        return await get_at_risk_prediction(db=db, student_id=student_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Inference error in predict_at_risk for student_id=%s", student_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/predict/at-risk-admin/{student_id}", response_model=AtRiskPrediction)
async def predict_at_risk_admin(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        return await get_at_risk_prediction(db=db, student_id=student_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Inference error in predict_at_risk_admin for student_id=%s", student_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/explain/at-risk/{student_id}")
async def explain_at_risk(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        return await get_at_risk_explanation(db=db, student_id=student_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Inference error in explain_at_risk for student_id=%s", student_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/predict/weak-topics/{student_id}", response_model=WeakTopicResponse)
async def predict_weak_topics(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        predictions = await get_weak_topic_predictions(db=db, student_id=student_id)
        return {"student_id": student_id, "predictions": predictions}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Inference error in predict_weak_topics for student_id=%s", student_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/diagnose/{student_id}")
async def diagnose_student_endpoint(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        at_risk_result = await get_at_risk_prediction(db=db, student_id=student_id)
        weak_topics = await get_weak_topic_predictions(db=db, student_id=student_id)
        diagnosis = diagnose_student(at_risk_result, weak_topics)
        return {"student_id": student_id, **diagnosis}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Inference error in diagnose_student for student_id=%s", student_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/diagnose-with-recommendations/{student_id}")
async def diagnose_with_recommendations(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    await authorize_student_ml_access(student_id=student_id, current_user=current_user, db=db)
    try:
        at_risk_result = await get_at_risk_prediction(db=db, student_id=student_id)
        weak_topics = await get_weak_topic_predictions(db=db, student_id=student_id)
        diagnosis = diagnose_student(at_risk_result, weak_topics)

        trusted_tenant = get_trusted_tenant_id(current_user)
        recommendations = get_recommendations_for_weak_topics(
            diagnosis["top_weak_topics"],
            tenant_id=trusted_tenant,
        )
        diagnosis["recommendations"] = recommendations

        return {"student_id": student_id, **diagnosis}
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Inference error in diagnose_with_recommendations for student_id=%s", student_id
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ML service temporarily unavailable. Please try again later.",
        ) from None


@router.get("/recommend-topic")
async def recommend_for_topic(
    subject: str,
    topic: str,
    current_user: User = Depends(require_role("teacher")),
):
    trusted_tenant = get_trusted_tenant_id(current_user)
    recommendations = get_recommendations_for_weak_topics(
        [{"subject": subject, "topic": topic}],
        tenant_id=trusted_tenant,
        n_results_per_topic=3,
    )
    return (
        recommendations[0]
        if recommendations
        else {"subject": subject, "topic": topic, "recommendation": None, "sources": []}
    )


@router.get("/generate-worksheet")
async def generate_worksheet(
    subject: str,
    topic: str,
    student_name: str | None = None,
    current_user: User = Depends(require_role("teacher")),
):
    pdf_bytes = generate_worksheet_pdf(
        subject=subject, topic=topic, student_name=student_name
    )

    filename = f"{topic.replace(' ', '_')}_worksheet.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.users.dependencies import require_role
from app.users.models import User
from app.core.database import get_db
from app.ml.schemas import AtRiskPrediction, WeakTopicResponse
from app.ml.service import get_at_risk_prediction, get_weak_topic_predictions
from app.ml.explain import get_at_risk_explanation

router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/predict/at-risk/{student_id}", response_model=AtRiskPrediction)
async def predict_at_risk(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await get_at_risk_prediction(db=db, student_id=student_id)
    return result


@router.get("/predict/at-risk-admin/{student_id}", response_model=AtRiskPrediction)
async def predict_at_risk_admin(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await get_at_risk_prediction(db=db, student_id=student_id)
    return result

@router.get("/explain/at-risk/{student_id}")
async def explain_at_risk(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    result = await get_at_risk_explanation(db=db, student_id=student_id)
    return result

@router.get("/predict/weak-topics/{student_id}", response_model=WeakTopicResponse)
async def predict_weak_topics(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    predictions = await get_weak_topic_predictions(db=db, student_id=student_id)
    return {"student_id": student_id, "predictions": predictions}

from app.ml.diagnosis import diagnose_student


@router.get("/diagnose/{student_id}")
async def diagnose_student_endpoint(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    at_risk_result = await get_at_risk_prediction(db=db, student_id=student_id)
    weak_topics = await get_weak_topic_predictions(db=db, student_id=student_id)
    diagnosis = diagnose_student(at_risk_result, weak_topics)
    return {"student_id": student_id, **diagnosis}

from app.ml.recommendations import get_recommendations_for_weak_topics


@router.get("/diagnose-with-recommendations/{student_id}")
async def diagnose_with_recommendations(
    student_id: uuid.UUID,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
):
    at_risk_result = await get_at_risk_prediction(db=db, student_id=student_id)
    weak_topics = await get_weak_topic_predictions(db=db, student_id=student_id)
    diagnosis = diagnose_student(at_risk_result, weak_topics)

    recommendations = get_recommendations_for_weak_topics(diagnosis["top_weak_topics"])
    diagnosis["recommendations"] = recommendations

    return {"student_id": student_id, **diagnosis}

from app.ml.recommendations import get_recommendations_for_weak_topics


@router.get("/recommend-topic")
async def recommend_for_topic(
    subject: str,
    topic: str,
    current_user: User = Depends(require_role("teacher")),
):
    recommendations = get_recommendations_for_weak_topics(
        [{"subject": subject, "topic": topic}],
        n_results_per_topic=3,
    )
    return recommendations[0] if recommendations else {"subject": subject, "topic": topic, "recommendation": None, "sources": []}

from fastapi.responses import StreamingResponse
import io
from app.ml.worksheet_generator import generate_worksheet_pdf


@router.get("/generate-worksheet")
async def generate_worksheet(
    subject: str,
    topic: str,
    student_name: str | None = None,
    current_user: User = Depends(require_role("teacher")),
):
    pdf_bytes = generate_worksheet_pdf(subject=subject, topic=topic, student_name=student_name)

    filename = f"{topic.replace(' ', '_')}_worksheet.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
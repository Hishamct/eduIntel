"""
Loads the trained at-risk and weak-topic models and runs predictions against
LIVE student data. Rebuilds the same feature engineering used at training
time (see app/ml/train_at_risk_model.py and train_weak_topic_model.py), but
computed over each student's full available history up to now, rather than
the fixed synthetic feature/label window used during training.

NOTE: this is a genuine limitation worth documenting — the model was trained
on a fixed 8-month synthetic feature window; at inference time we don't have
a clean "held-out future period" to validate against, we're just applying
the learned pattern to each student's current standing. This is the normal/
expected way trained models are used in production, but worth being explicit
about for a reviewer.
"""
import uuid
import numpy as np
import joblib
from functools import lru_cache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.admin.models import Attendance
from app.student.models import HomeworkSubmission, DoubtThread
from app.teacher.models import ExamResult

AT_RISK_MODEL_PATH = "app/ml/models/at_risk_model.joblib"
WEAK_TOPIC_MODEL_PATH = "app/ml/models/weak_topic_model.joblib"

EXPECTED_HW_PER_MONTH = 4 * 4  # 4 weeks * 4 subjects, matches training assumption


@lru_cache(maxsize=1)
def _load_at_risk_model():
    return joblib.load(AT_RISK_MODEL_PATH)


@lru_cache(maxsize=1)
def _load_weak_topic_model():
    return joblib.load(WEAK_TOPIC_MODEL_PATH)


async def _get_student_history(db: AsyncSession, student_id: uuid.UUID):
    attendance_result = await db.execute(
        select(Attendance).where(Attendance.student_id == student_id)
    )
    attendance = attendance_result.scalars().all()

    homework_result = await db.execute(
        select(HomeworkSubmission).where(HomeworkSubmission.student_id == student_id)
    )
    homework = homework_result.scalars().all()

    exam_result = await db.execute(
        select(ExamResult).where(ExamResult.student_id == student_id)
    )
    exams = exam_result.scalars().all()

    doubt_result = await db.execute(
        select(DoubtThread).where(DoubtThread.student_id == student_id)
    )
    doubts = doubt_result.scalars().all()

    return attendance, homework, exams, doubts


def _months_of_history(attendance) -> float:
    if not attendance:
        return 0.0
    dates = [a.date for a in attendance]
    span_days = (max(dates) - min(dates)).days
    return max(span_days / 30, 0.1)  # avoid divide-by-zero for brand-new students


def _compute_at_risk_features(attendance, homework, exams, doubts) -> dict:
    """Shared feature-computation used by both get_at_risk_prediction (below)
    and app/ml/explain.py's SHAP explanation, so predictions and their
    explanations can never silently drift out of sync."""
    attendance_rate = sum(1 for a in attendance if a.status in ("present", "late")) / len(attendance)

    months = _months_of_history(attendance)
    expected_hw = months * EXPECTED_HW_PER_MONTH
    homework_rate = min(len(homework) / expected_hw, 1.0) if expected_hw > 0 else 0

    exams_sorted = sorted(exams, key=lambda e: e.exam_date)
    if len(exams_sorted) >= 2:
        avg_score_early = np.mean([float(e.score) for e in exams_sorted[:len(exams_sorted)//2]])
        avg_score_late = np.mean([float(e.score) for e in exams_sorted[len(exams_sorted)//2:]])
    else:
        avg_score_early = avg_score_late = float(exams_sorted[0].score)
    score_trend = avg_score_late - avg_score_early

    avg_score_overall = np.mean([float(e.score) for e in exams])
    doubt_count = len(doubts)

    return {
        "attendance_rate": round(attendance_rate, 3),
        "homework_submission_rate": round(homework_rate, 3),
        "avg_score_overall": round(float(avg_score_overall), 2),
        "score_trend": round(float(score_trend), 2),
        "doubt_thread_count": doubt_count,
    }


async def get_at_risk_prediction(db: AsyncSession, student_id: uuid.UUID) -> dict:
    attendance, homework, exams, doubts = await _get_student_history(db, student_id)

    if not attendance or not exams:
        return {
            "student_id": student_id,
            "is_at_risk": False,
            "risk_probability": None,
            "features_used": {},
            "note": "Insufficient history to generate a prediction (needs attendance and exam records).",
        }

    features = _compute_at_risk_features(attendance, homework, exams, doubts)

    bundle = _load_at_risk_model()
    model = bundle["model"]
    feature_cols = bundle["feature_cols"]

    X = [[features[col] for col in feature_cols]]
    probability = float(model.predict_proba(X)[0][1])

    return {
        "student_id": student_id,
        "is_at_risk": probability >= 0.5,
        "risk_probability": round(probability, 3),
        "features_used": features,
    }


async def get_weak_topic_predictions(db: AsyncSession, student_id: uuid.UUID) -> list[dict]:
    attendance, homework, exams, _ = await _get_student_history(db, student_id)

    if not attendance or not exams:
        return []

    attendance_rate = sum(1 for a in attendance if a.status in ("present", "late")) / len(attendance)
    months = _months_of_history(attendance)
    expected_hw = months * EXPECTED_HW_PER_MONTH
    homework_rate = min(len(homework) / expected_hw, 1.0) if expected_hw > 0 else 0

    # group exams by (subject, topic)
    by_topic: dict = {}
    for e in exams:
        by_topic.setdefault((e.subject, e.topic), []).append(e)

    if not by_topic:
        return []

    overall_avg = np.mean([float(e.score) for e in exams])

    bundle = _load_weak_topic_model()
    model = bundle["model"]
    feature_cols = bundle["feature_cols"]
    subject_cols = [c for c in feature_cols if c.startswith("subject_")]

    predictions = []
    for (subject, topic), topic_exams in by_topic.items():
        topic_avg_score = np.mean([float(e.score) for e in topic_exams])

        other_scores = [
            float(e.score) for (s, t), exs in by_topic.items()
            if (s, t) != (subject, topic) for e in exs
        ]
        student_overall_avg = np.mean(other_scores) if other_scores else topic_avg_score
        relative_gap = topic_avg_score - student_overall_avg

        row = {
            "attendance_rate": round(attendance_rate, 3),
            "homework_submission_rate": round(homework_rate, 3),
            "topic_avg_score": round(float(topic_avg_score), 2),
            "student_overall_avg": round(float(student_overall_avg), 2),
            "relative_gap": round(float(relative_gap), 2),
        }
        # one-hot subject columns — set the matching one to 1, rest 0
        subject_col_name = f"subject_{subject}"
        for col in subject_cols:
            row[col] = 1 if col == subject_col_name else 0

        X = [[row.get(col, 0) for col in feature_cols]]
        probability = float(model.predict_proba(X)[0][1])

        predictions.append({
            "subject": subject,
            "topic": topic,
            "is_weak": probability >= 0.5,
            "weak_probability": round(probability, 3),
        })

    # most concerning first
    predictions.sort(key=lambda p: -p["weak_probability"])
    return predictions
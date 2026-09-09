"""
Trains the at-risk prediction model using a temporal train/label split to avoid
data leakage: features from months 1-8, label (at-risk) from months 9-10.

This is an OFFLINE training script — run manually, not part of the API request path.
Produces a saved model file + prints evaluation metrics.

Run: python -m app.ml.train_at_risk_model
"""
import asyncio
import datetime
import pandas as pd
import numpy as np
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
import joblib
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.users.models import User
from app.admin.models import Attendance
from app.student.models import HomeworkSubmission, DoubtThread
from app.teacher.models import ExamResult

FEATURE_WINDOW_MONTHS = 8   # months 1-8: used to compute features
LABEL_WINDOW_MONTHS = 2     # months 9-10: used to compute the label
AT_RISK_SCORE_THRESHOLD = 50  # avg score below this in the label window = at-risk

MODEL_OUTPUT_PATH = "app/ml/models/at_risk_model.joblib"


async def build_dataset() -> pd.DataFrame:
    async with AsyncSessionLocal() as db:
        students_result = await db.execute(select(User).where(User.role == "student"))
        students = students_result.scalars().all()

        attendance_result = await db.execute(select(Attendance))
        attendance_rows = attendance_result.scalars().all()

        homework_result = await db.execute(select(HomeworkSubmission))
        homework_rows = homework_result.scalars().all()

        exam_result = await db.execute(select(ExamResult))
        exam_rows = exam_result.scalars().all()

        doubt_result = await db.execute(select(DoubtThread))
        doubt_rows = doubt_result.scalars().all()

    if not attendance_rows:
        raise RuntimeError("No attendance data found — run the seed_ml_dataset script first.")

    all_dates = [a.date for a in attendance_rows]
    dataset_start = min(all_dates)
    dataset_end = max(all_dates)
    feature_cutoff = dataset_start + datetime.timedelta(days=30 * FEATURE_WINDOW_MONTHS)

    print(f"Dataset span: {dataset_start} to {dataset_end}")
    print(f"Feature window: {dataset_start} to {feature_cutoff}")
    print(f"Label window: {feature_cutoff} to {dataset_end}")

    # --- Index raw rows by student_id for fast lookup ---
    attendance_by_student: dict = {}
    for a in attendance_rows:
        attendance_by_student.setdefault(a.student_id, []).append(a)

    homework_by_student: dict = {}
    for h in homework_rows:
        homework_by_student.setdefault(h.student_id, []).append(h)

    exams_by_student: dict = {}
    for e in exam_rows:
        exams_by_student.setdefault(e.student_id, []).append(e)

    doubts_by_student: dict = {}
    for d in doubt_rows:
        doubts_by_student.setdefault(d.student_id, []).append(d)

    records = []

    for student in students:
        sid = student.id

        # --- FEATURES: months 1-8 only ---
        att = [a for a in attendance_by_student.get(sid, []) if a.date < feature_cutoff]
        hw = [h for h in homework_by_student.get(sid, []) if h.created_at.date() < feature_cutoff]
        exams_feat = [e for e in exams_by_student.get(sid, []) if e.exam_date < feature_cutoff]
        doubts = [d for d in doubts_by_student.get(sid, []) if d.created_at.date() < feature_cutoff]

        if not att or not exams_feat:
            continue  # not enough history for this student, skip

        attendance_rate = sum(1 for a in att if a.status in ("present", "late")) / len(att)

        # crude homework "expected" count: ~4 subjects/week over feature window
        expected_hw = FEATURE_WINDOW_MONTHS * 4 * 4  # 4 weeks/month * 4 subjects
        homework_rate = min(len(hw) / expected_hw, 1.0) if expected_hw > 0 else 0

        exam_scores_sorted = sorted(exams_feat, key=lambda e: e.exam_date)
        avg_score_early = np.mean([float(e.score) for e in exam_scores_sorted[:len(exam_scores_sorted)//2]]) if len(exam_scores_sorted) >= 2 else float(exam_scores_sorted[0].score)
        avg_score_late = np.mean([float(e.score) for e in exam_scores_sorted[len(exam_scores_sorted)//2:]])
        score_trend = avg_score_late - avg_score_early  # positive = improving, negative = declining

        avg_score_overall = np.mean([float(e.score) for e in exams_feat])
        doubt_count = len(doubts)

        # --- LABEL: months 9-10 average score ---
        exams_label = [e for e in exams_by_student.get(sid, []) if e.exam_date >= feature_cutoff]
        if not exams_label:
            continue  # no future data to form a label, skip

        avg_score_label_period = np.mean([float(e.score) for e in exams_label])
        at_risk = 1 if avg_score_label_period < AT_RISK_SCORE_THRESHOLD else 0

        records.append({
            "student_id": str(sid),
            "attendance_rate": round(attendance_rate, 3),
            "homework_submission_rate": round(homework_rate, 3),
            "avg_score_overall": round(avg_score_overall, 2),
            "score_trend": round(score_trend, 2),
            "doubt_thread_count": doubt_count,
            "at_risk": at_risk,
        })

    df = pd.DataFrame(records)
    print(f"\nBuilt dataset: {len(df)} students with valid feature+label windows")
    print(f"At-risk rate: {df['at_risk'].mean():.1%}")
    return df


def train_model(df: pd.DataFrame):
    feature_cols = ["attendance_rate", "homework_submission_rate", "avg_score_overall", "score_trend", "doubt_thread_count"]
    X = df[feature_cols]
    y = df["at_risk"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.1,
        eval_metric="logloss",
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    print("\n--- Evaluation on held-out test set ---")
    print(classification_report(y_test, y_pred, target_names=["not_at_risk", "at_risk"]))
    print(f"ROC-AUC: {roc_auc_score(y_test, y_proba):.3f}")

    print("\n--- Feature importance ---")
    for feat, importance in sorted(zip(feature_cols, model.feature_importances_), key=lambda x: -x[1]):
        print(f"  {feat}: {importance:.3f}")

    import os
    os.makedirs("app/ml/models", exist_ok=True)
    joblib.dump({"model": model, "feature_cols": feature_cols}, MODEL_OUTPUT_PATH)
    print(f"\nModel saved to {MODEL_OUTPUT_PATH}")

    return model


async def main():
    df = await build_dataset()
    if len(df) < 30:
        print(f"WARNING: only {len(df)} students have valid data — this is too small for a reliable model.")
        return
    train_model(df)


if __name__ == "__main__":
    asyncio.run(main())
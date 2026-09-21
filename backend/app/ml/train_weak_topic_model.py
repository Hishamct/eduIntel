"""
Trains the weak-topic prediction model: for each (student, subject, topic)
combination, predicts whether the student will be weak in that specific topic,
using a temporal train/label split (features: months 1-8, label: months 9-10)
to avoid data leakage, same discipline as the at-risk model.

Run: python -m app.ml.train_weak_topic_model
"""

import asyncio
import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sqlalchemy import select
from xgboost import XGBClassifier

from app.admin.models import Attendance
from app.core.database import AsyncSessionLocal
from app.student.models import HomeworkSubmission
from app.teacher.models import ExamResult
from app.users.models import User

FEATURE_WINDOW_MONTHS = 8
LABEL_WINDOW_MONTHS = 2
WEAK_TOPIC_SCORE_THRESHOLD = (
    55  # avg score below this for a topic in the label window = weak
)

MODEL_OUTPUT_PATH = "app/ml/models/weak_topic_model.joblib"


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

    if not exam_rows:
        raise RuntimeError("No exam data found — run the seed_ml_dataset script first.")

    all_dates = [a.date for a in attendance_rows]
    dataset_start = min(all_dates)
    dataset_end = max(all_dates)
    feature_cutoff = dataset_start + datetime.timedelta(days=30 * FEATURE_WINDOW_MONTHS)

    print(f"Dataset span: {dataset_start} to {dataset_end}")
    print(f"Feature window: {dataset_start} to {feature_cutoff}")
    print(f"Label window: {feature_cutoff} to {dataset_end}")

    attendance_by_student: dict = {}
    for a in attendance_rows:
        attendance_by_student.setdefault(a.student_id, []).append(a)

    homework_by_student: dict = {}
    for h in homework_rows:
        homework_by_student.setdefault(h.student_id, []).append(h)

    # exams indexed by (student_id, subject, topic) for per-topic lookup
    exams_by_key: dict = {}
    for e in exam_rows:
        key = (e.student_id, e.subject, e.topic)
        exams_by_key.setdefault(key, []).append(e)

    records = []

    for student in students:
        sid = student.id

        # --- Student-level features (shared across all topics for this student), months 1-8 ---
        att = [a for a in attendance_by_student.get(sid, []) if a.date < feature_cutoff]
        hw = [
            h
            for h in homework_by_student.get(sid, [])
            if h.created_at.date() < feature_cutoff
        ]

        if not att:
            continue

        attendance_rate = sum(1 for a in att if a.status in ("present", "late")) / len(
            att
        )
        expected_hw = FEATURE_WINDOW_MONTHS * 4 * 4
        homework_rate = min(len(hw) / expected_hw, 1.0) if expected_hw > 0 else 0

        # --- Per-topic features + label ---
        student_topic_keys = {k for k in exams_by_key if k[0] == sid}

        for _, subject, topic in student_topic_keys:
            all_exams_for_topic = exams_by_key[(sid, subject, topic)]
            feat_exams = [
                e for e in all_exams_for_topic if e.exam_date < feature_cutoff
            ]
            label_exams = [
                e for e in all_exams_for_topic if e.exam_date >= feature_cutoff
            ]

            if not feat_exams or not label_exams:
                continue  # not enough history in one of the windows for this topic

            topic_avg_score = np.mean([float(e.score) for e in feat_exams])

            # also compute this student's overall avg (excluding this topic) as a
            # baseline comparison feature — lets the model learn "weak relative to
            # this student's own norm", not just "low absolute score"
            other_topic_scores = [
                float(e.score)
                for k, exams in exams_by_key.items()
                if k[0] == sid and k != (sid, subject, topic)
                for e in exams
                if e.exam_date < feature_cutoff
            ]
            student_overall_avg = (
                np.mean(other_topic_scores) if other_topic_scores else topic_avg_score
            )
            relative_gap = (
                topic_avg_score - student_overall_avg
            )  # negative = weaker than own average

            label_avg_score = np.mean([float(e.score) for e in label_exams])
            weak_topic = 1 if label_avg_score < WEAK_TOPIC_SCORE_THRESHOLD else 0

            records.append(
                {
                    "student_id": str(sid),
                    "subject": subject,
                    "topic": topic,
                    "attendance_rate": round(attendance_rate, 3),
                    "homework_submission_rate": round(homework_rate, 3),
                    "topic_avg_score": round(topic_avg_score, 2),
                    "student_overall_avg": round(student_overall_avg, 2),
                    "relative_gap": round(relative_gap, 2),
                    "weak_topic": weak_topic,
                }
            )

    df = pd.DataFrame(records)
    print(f"\nBuilt dataset: {len(df)} (student, topic) rows")
    print(f"Weak-topic rate: {df['weak_topic'].mean():.1%}")
    return df


def train_model(df: pd.DataFrame):
    # One-hot encode subject since it's categorical and low-cardinality
    df_encoded = pd.get_dummies(df, columns=["subject"], prefix="subject")

    feature_cols = [
        "attendance_rate",
        "homework_submission_rate",
        "topic_avg_score",
        "student_overall_avg",
        "relative_gap",
    ] + [c for c in df_encoded.columns if c.startswith("subject_")]

    X = df_encoded[feature_cols]
    y = df_encoded["weak_topic"]

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
    print(
        classification_report(y_test, y_pred, target_names=["not_weak", "weak_topic"])
    )
    print(f"ROC-AUC: {roc_auc_score(y_test, y_proba):.3f}")

    print("\n--- Feature importance ---")
    for feat, importance in sorted(
        zip(feature_cols, model.feature_importances_), key=lambda x: -x[1]
    ):
        print(f"  {feat}: {importance:.3f}")

    import os

    os.makedirs("app/ml/models", exist_ok=True)
    joblib.dump({"model": model, "feature_cols": feature_cols}, MODEL_OUTPUT_PATH)
    print(f"\nModel saved to {MODEL_OUTPUT_PATH}")


async def main():
    df = await build_dataset()
    if len(df) < 100:
        print(
            f"WARNING: only {len(df)} (student, topic) rows — may be too small for a reliable model."
        )
        return
    train_model(df)


if __name__ == "__main__":
    asyncio.run(main())

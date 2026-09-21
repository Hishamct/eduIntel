"""
SHAP explainability for the at-risk model. Answers "why was this student
flagged?" with a per-feature breakdown, rather than just a risk score.

Uses shap.TreeExplainer, which works natively with XGBoost and needs no
background dataset for the default tree_path_dependent mode. Contributions
are on the model's raw log-odds (margin) scale, not probability — this is
the standard/expected SHAP output for a tree ensemble binary classifier,
and is reported here as relative direction + magnitude rather than an
exact probability delta, which is the common, defensible way to present
SHAP values without adding a probability-space background sample.

Reuses the exact same feature-computation helper as the live prediction
path (service._compute_at_risk_features) so the explanation can never
silently drift out of sync with what the model actually saw.
"""

import uuid
from functools import lru_cache

import shap
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.service import (
    _compute_at_risk_features,
    _get_student_history,
    _load_at_risk_model,
)

FEATURE_LABELS = {
    "attendance_rate": "Attendance rate",
    "homework_submission_rate": "Homework submission rate",
    "avg_score_overall": "Overall average exam score",
    "score_trend": "Recent score trend",
    "doubt_thread_count": "Doubt forum activity",
}


@lru_cache(maxsize=1)
def _get_explainer():
    bundle = _load_at_risk_model()
    model = bundle["model"]
    return shap.TreeExplainer(model), bundle["feature_cols"]


async def get_at_risk_explanation(db: AsyncSession, student_id: uuid.UUID) -> dict:
    attendance, homework, exams, doubts = await _get_student_history(db, student_id)

    if not attendance or not exams:
        return {
            "student_id": student_id,
            "risk_probability": None,
            "top_factors": [],
            "summary": "Insufficient history to generate an explanation (needs attendance and exam records).",
        }

    features = _compute_at_risk_features(attendance, homework, exams, doubts)

    explainer, feature_cols = _get_explainer()
    bundle = _load_at_risk_model()
    model = bundle["model"]

    X = [[features[col] for col in feature_cols]]
    risk_probability = float(model.predict_proba(X)[0][1])

    shap_values = explainer.shap_values(X)
    # shap_values shape: (1, n_features) for a single-sample binary classifier
    contributions = shap_values[0]

    factors = []
    for col, contribution in zip(feature_cols, contributions):
        factors.append(
            {
                "feature": col,
                "label": FEATURE_LABELS.get(col, col),
                "value": features[col],
                "contribution": round(float(contribution), 4),
                "direction": "increases_risk" if contribution > 0 else "decreases_risk",
            }
        )

    # most influential first, regardless of direction
    factors.sort(key=lambda f: -abs(f["contribution"]))

    top = factors[0]
    verb = "increasing" if top["direction"] == "increases_risk" else "reducing"
    summary = f"{top['label']} ({top['value']}) is the strongest factor {verb} this student's risk."

    return {
        "student_id": student_id,
        "risk_probability": round(risk_probability, 3),
        "top_factors": factors,
        "summary": summary,
    }

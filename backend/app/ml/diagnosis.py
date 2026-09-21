"""
Diagnosis logic: takes a student's at-risk prediction, weak-topic predictions,
and their raw academic/attendance factors, and produces a small set of
concrete, explainable flag reasons — strictly academic/attendance-based
(attendance rate, homework submission rate, score trend, doubt-forum
inactivity). Never references personal circumstances or wellbeing.
"""

ATTENDANCE_CONCERN_THRESHOLD = 0.75
HOMEWORK_CONCERN_THRESHOLD = 0.60
SCORE_TREND_CONCERN_THRESHOLD = -5.0
DOUBT_INACTIVITY_THRESHOLD = 1  # fewer than this many doubt threads = inactive
MAX_WEAK_TOPICS_SURFACED = 3  # cap noisy full-list flags down to the worst few


def diagnose_student(at_risk_result: dict, weak_topic_predictions: list[dict]) -> dict:
    features = at_risk_result.get("features_used") or {}
    reasons = []

    attendance_rate = features.get("attendance_rate")
    if attendance_rate is not None and attendance_rate < ATTENDANCE_CONCERN_THRESHOLD:
        reasons.append(
            {
                "factor": "attendance",
                "detail": f"Attendance rate is {attendance_rate:.0%}, below the {ATTENDANCE_CONCERN_THRESHOLD:.0%} concern threshold.",
            }
        )

    homework_rate = features.get("homework_submission_rate")
    if homework_rate is not None and homework_rate < HOMEWORK_CONCERN_THRESHOLD:
        reasons.append(
            {
                "factor": "homework_submission",
                "detail": f"Homework submission rate is {homework_rate:.0%}, below the {HOMEWORK_CONCERN_THRESHOLD:.0%} concern threshold.",
            }
        )

    score_trend = features.get("score_trend")
    if score_trend is not None and score_trend < SCORE_TREND_CONCERN_THRESHOLD:
        reasons.append(
            {
                "factor": "score_trend",
                "detail": f"Exam scores have declined by {abs(score_trend):.1f} points over the tracked period.",
            }
        )

    doubt_count = features.get("doubt_thread_count")
    if doubt_count is not None and doubt_count < DOUBT_INACTIVITY_THRESHOLD:
        reasons.append(
            {
                "factor": "forum_inactivity",
                "detail": "No activity in the doubt forum — student may not be seeking help when struggling.",
            }
        )

    # Cap weak topics down to the most concerning few, ranked by probability —
    # this is what fixes the "15 red flags" noise problem from raw predictions.
    top_weak_topics = sorted(
        [p for p in weak_topic_predictions if p["is_weak"]],
        key=lambda p: -p["weak_probability"],
    )[:MAX_WEAK_TOPICS_SURFACED]

    total_weak_count = sum(1 for p in weak_topic_predictions if p["is_weak"])
    broadly_weak = total_weak_count >= max(5, len(weak_topic_predictions) * 0.6)

    return {
        "is_at_risk": at_risk_result.get("is_at_risk", False),
        "risk_probability": at_risk_result.get("risk_probability"),
        "contributing_factors": reasons,
        "top_weak_topics": top_weak_topics,
        "total_weak_topic_count": total_weak_count,
        "broadly_weak_across_subjects": broadly_weak,  # true = struggling generally, not one specific gap
    }

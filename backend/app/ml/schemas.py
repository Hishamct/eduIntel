from uuid import UUID
from pydantic import BaseModel


class AtRiskPrediction(BaseModel):
    student_id: UUID
    is_at_risk: bool
    risk_probability: float  # 0.0-1.0
    features_used: dict


class WeakTopicPrediction(BaseModel):
    subject: str
    topic: str
    is_weak: bool
    weak_probability: float


class WeakTopicResponse(BaseModel):
    student_id: UUID
    predictions: list[WeakTopicPrediction]
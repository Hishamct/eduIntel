from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID


class HomeworkSubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    title: str
    description: str | None
    original_filename: str
    status: str
    created_at: datetime
    score: int | None
    max_score: int | None
    feedback: str | None
    graded_by: UUID | None
    extracted_text: str | None
    ocr_confidence: float | None

class DoubtThreadCreate(BaseModel):
    subject: str
    title: str
    body: str  # the initial question text


class DoubtMessageCreate(BaseModel):
    body: str


class DoubtMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_id: UUID
    sender_role: str
    body: str
    created_at: datetime


class DoubtThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    title: str
    status: str
    created_at: datetime
    messages: list[DoubtMessageRead]

class StudyMaterialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    title: str
    description: str | None
    original_filename: str
    created_at: datetime
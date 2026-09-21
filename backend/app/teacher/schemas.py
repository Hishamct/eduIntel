from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GradeSubmission(BaseModel):
    score: int
    max_score: int
    feedback: str | None = None


class TeacherHomeworkSubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    student_email: str
    subject: str
    title: str
    description: str | None
    original_filename: str
    status: str
    created_at: datetime
    score: int | None
    max_score: int | None
    feedback: str | None
    extracted_text: str | None
    ocr_confidence: float | None


class AssignmentCreate(BaseModel):
    title: str
    subject: str
    class_section: str
    due_date: date | None = None
    max_score: int = 100
    instructions: str | None = None


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    subject: str
    class_section: str
    due_date: date | None
    max_score: int
    instructions: str | None
    created_at: datetime


class StudyMaterialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    title: str
    description: str | None
    original_filename: str
    extracted_text: str | None
    extraction_method: str | None
    created_at: datetime


class StudentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    email: str
    grade: str | None
    section: str | None
    roll_number: str | None

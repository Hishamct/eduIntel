from uuid import UUID
from pydantic import BaseModel, ConfigDict
from datetime import date, datetime

class TimetableEntryCreate(BaseModel):
    class_section: str
    day_of_week: str
    period: int
    subject: str
    teacher_id: UUID | None = None


class TimetableEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    class_section: str
    day_of_week: str
    period: int
    subject: str
    teacher_id: UUID | None


class SalaryRecordCreate(BaseModel):
    teacher_id: UUID
    month: date
    base_salary: float
    bonus: float = 0
    deduction: float = 0
    payment_status: str = "pending"


class SalaryRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    teacher_id: UUID
    month: date
    base_salary: float
    bonus: float
    deduction: float
    payment_status: str
    created_at: datetime

class TeacherSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str

class StudentEnrollCreate(BaseModel):
    email: str
    password: str
    name: str
    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: str | None = None
    phone: str | None = None
    address: str | None = None
    guardian_name: str | None = None
    guardian_phone: str | None = None

class StudentUpdate(BaseModel):
    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: str | None = None
    phone: str | None = None
    address: str | None = None
    guardian_name: str | None = None
    guardian_phone: str | None = None


class StudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str | None
    grade: str | None
    section: str | None
    roll_number: str | None
    parent_email: str | None
    phone: str | None
    address: str | None
    guardian_name: str | None
    guardian_phone: str | None
    created_at: datetime


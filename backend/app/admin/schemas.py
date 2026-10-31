from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    name: str | None = None


class StudentEnrollCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    guardian_name: str | None = None
    guardian_phone: str | None = None
    parent_name: str | None = None
    parent_phone: str | None = None


StudentProvisionRequest = StudentEnrollCreate


class StaffProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)
    name: str
    department: str | None = None
    designation: str | None = None
    subjects: str | None = None


class StudentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: EmailStr | None = None
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

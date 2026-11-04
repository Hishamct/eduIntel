import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class StudentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: str | None = None


class TeacherProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subjects: str | None = None
    department: str | None = None


class AdminProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    designation: str | None = None


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    name: str | None = None
    role: str
    is_active: bool
    is_platform_admin: bool = False
    student_profile: StudentProfileResponse | None = None
    teacher_profile: TeacherProfileResponse | None = None
    admin_profile: AdminProfileResponse | None = None

    @field_validator("is_platform_admin", mode="before")
    @classmethod
    def coerce_is_platform_admin(cls, v: Any) -> bool:
        return bool(v) if v is not None else False


class StudentProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: str | None = None


class TeacherProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subjects: str | None = None
    department: str | None = None


class AdminProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    designation: str | None = None

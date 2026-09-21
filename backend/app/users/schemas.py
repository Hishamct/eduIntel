import uuid

from pydantic import BaseModel, EmailStr


class StudentProfileResponse(BaseModel):
    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: str | None = None

    class Config:
        from_attributes = True


class TeacherProfileResponse(BaseModel):
    subjects: str | None = None
    department: str | None = None

    class Config:
        from_attributes = True


class AdminProfileResponse(BaseModel):
    designation: str | None = None

    class Config:
        from_attributes = True


class MeResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    student_profile: StudentProfileResponse | None = None
    teacher_profile: TeacherProfileResponse | None = None
    admin_profile: AdminProfileResponse | None = None

    class Config:
        from_attributes = True


class StudentProfileUpdate(BaseModel):
    grade: str | None = None
    section: str | None = None
    roll_number: str | None = None
    parent_email: str | None = None


class TeacherProfileUpdate(BaseModel):
    subjects: str | None = None
    department: str | None = None


class AdminProfileUpdate(BaseModel):
    designation: str | None = None

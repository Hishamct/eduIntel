from pydantic import BaseModel, EmailStr
from typing import Optional
import uuid


class StudentProfileResponse(BaseModel):
    grade: Optional[str] = None
    section: Optional[str] = None
    roll_number: Optional[str] = None
    parent_email: Optional[str] = None

    class Config:
        from_attributes = True


class TeacherProfileResponse(BaseModel):
    subjects: Optional[str] = None
    department: Optional[str] = None

    class Config:
        from_attributes = True


class AdminProfileResponse(BaseModel):
    designation: Optional[str] = None

    class Config:
        from_attributes = True


class MeResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    student_profile: Optional[StudentProfileResponse] = None
    teacher_profile: Optional[TeacherProfileResponse] = None
    admin_profile: Optional[AdminProfileResponse] = None

    class Config:
        from_attributes = True


class StudentProfileUpdate(BaseModel):
    grade: Optional[str] = None
    section: Optional[str] = None
    roll_number: Optional[str] = None
    parent_email: Optional[str] = None


class TeacherProfileUpdate(BaseModel):
    subjects: Optional[str] = None
    department: Optional[str] = None


class AdminProfileUpdate(BaseModel):
    designation: Optional[str] = None
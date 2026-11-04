import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InstitutionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    contact_email: EmailStr | None = Field(default=None, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    tier: str = Field(default="standard", max_length=50)
    settings: dict[str, Any] = Field(default_factory=dict)


class InstitutionCreate(InstitutionBase):
    pass


class InstitutionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    tier: str | None = Field(default=None, max_length=50)
    settings: dict[str, Any] | None = None


class InstitutionResponse(InstitutionBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MembershipBase(BaseModel):
    role: Literal["student", "teacher", "admin"]
    status: Literal["active", "suspended", "revoked"] = "active"


class MembershipCreate(MembershipBase):
    institution_id: uuid.UUID
    user_id: uuid.UUID


class MembershipUpdate(BaseModel):
    role: Literal["student", "teacher", "admin"] | None = None
    status: Literal["active", "suspended", "revoked"] | None = None


class MembershipResponse(MembershipBase):
    id: uuid.UUID
    institution_id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InstitutionStatusUpdate(BaseModel):
    is_active: bool


class InstitutionOnboardRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    contact_email: EmailStr | None = Field(default=None, max_length=255)
    admin_email: EmailStr = Field(..., max_length=255)
    admin_name: str = Field(..., min_length=1, max_length=255)


class InstitutionOnboardResponse(BaseModel):
    institution_id: uuid.UUID
    name: str
    slug: str
    contact_email: EmailStr | None = None
    admin_user_id: uuid.UUID
    admin_email: EmailStr
    admin_name: str
    activation_token: str | None = None
    expires_at: datetime
    invitation_sent: bool = Field(
        default=False,
        description=(
            "True if invitation email was successfully dispatched via configured SMTP; "
            "False if unconfigured or failed."
        ),
    )
    invitation_status: str = Field(
        default="unconfigured",
        description="Detailed invitation email delivery status: 'sent', 'unconfigured', or 'failed'.",
    )


class InstitutionListItemResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    contact_email: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    student_count: int = 0
    teacher_count: int = 0
    admin_count: int = 0
    total_memberships: int = 0

    model_config = ConfigDict(from_attributes=True)


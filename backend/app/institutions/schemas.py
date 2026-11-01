import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class InstitutionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
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

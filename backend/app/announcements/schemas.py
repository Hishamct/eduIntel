from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    body: str
    posted_by: str
    created_at: datetime

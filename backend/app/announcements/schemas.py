from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class AnnouncementOut(BaseModel):
    id: UUID
    title: str
    body: str
    posted_by: str
    created_at: datetime

    class Config:
        from_attributes = True
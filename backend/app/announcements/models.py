import uuid

from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base
from app.core.models import (
    TimestampMixin,  # adjust import if your mixin lives elsewhere
)


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    posted_by = Column(
        String(255), nullable=False
    )  # simple for demo; could be FK to users.id

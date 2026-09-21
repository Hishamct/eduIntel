import uuid

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import TimestampMixin
from app.users.models import (
    User,
)


class HomeworkSubmission(Base, TimestampMixin):
    __tablename__ = "homework_submissions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("submitted", "graded", name="homework_status"),
        default="submitted",
        nullable=False,
    )

    # Grading fields — populated by teacher module. NULL until graded.
    score: Mapped[int] = mapped_column(nullable=True)
    max_score: Mapped[int] = mapped_column(nullable=True)
    feedback: Mapped[str] = mapped_column(Text, nullable=True)
    graded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    grader: Mapped["User"] = relationship(foreign_keys=[graded_by])


class DoubtThread(Base, TimestampMixin):
    __tablename__ = "doubt_threads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("open", "resolved", name="doubt_status"),
        default="open",
        nullable=False,
    )

    student: Mapped["User"] = relationship()
    messages: Mapped[list["DoubtMessage"]] = relationship(
        back_populates="thread",
        order_by="DoubtMessage.created_at",
        cascade="all, delete-orphan",
    )


class DoubtMessage(Base, TimestampMixin):
    __tablename__ = "doubt_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doubt_threads.id"), nullable=False, index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    sender_role: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    thread: Mapped["DoubtThread"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship()

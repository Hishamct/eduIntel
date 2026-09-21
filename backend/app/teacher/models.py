import datetime
import uuid

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import TimestampMixin
from app.users.models import (
    User,
)


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    class_section: Mapped[str] = mapped_column(String, nullable=False, index=True)
    due_date: Mapped[datetime.date] = mapped_column(Date, nullable=True)
    max_score: Mapped[int] = mapped_column(nullable=False, default=100)
    instructions: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    creator: Mapped["User"] = relationship()


class StudyMaterial(Base, TimestampMixin):
    __tablename__ = "study_materials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # "ocr" or "pdf_text"

    teacher: Mapped["User"] = relationship()


from sqlalchemy import Numeric  # add if not already imported


class ExamResult(Base, TimestampMixin):
    __tablename__ = "exam_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    class_section: Mapped[str] = mapped_column(String, nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(
        String, nullable=False
    )  # e.g. "Trigonometry" under MATHEMATICS
    exam_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    max_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=100)
    entered_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=True)

    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    enterer: Mapped["User"] = relationship(foreign_keys=[entered_by])

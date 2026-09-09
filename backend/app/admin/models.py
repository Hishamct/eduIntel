from sqlalchemy import String, ForeignKey, Enum, Date, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.core.models import TimestampMixin
import uuid
import datetime
from app.users.models import User  # noqa: F401 — needed for relationship() string reference


class Timetable(Base, TimestampMixin):
    __tablename__ = "timetable_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    class_section: Mapped[str] = mapped_column(String, nullable=False, index=True)
    day_of_week: Mapped[str] = mapped_column(
        Enum("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", name="day_of_week"),
        nullable=False,
    )
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])


class SalaryRecord(Base, TimestampMixin):
    __tablename__ = "salary_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    month: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    base_salary: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    bonus: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    deduction: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(
        Enum("pending", "paid", name="payment_status"),
        default="pending",
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])

from sqlalchemy import Numeric  # add to existing sqlalchemy imports at top
import datetime  # already imported


class FeeRecord(Base, TimestampMixin):
    __tablename__ = "fee_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    fee_type: Mapped[str] = mapped_column(String, nullable=False, default="tuition")  # tuition, exam, materials
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    due_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    paid_date: Mapped[datetime.date] = mapped_column(Date, nullable=True)
    payment_status: Mapped[str] = mapped_column(
        Enum("pending", "paid", "overdue", name="fee_payment_status"),
        default="pending",
        nullable=False,
    )

    student: Mapped["User"] = relationship()


class Attendance(Base, TimestampMixin):
    __tablename__ = "attendance_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    class_section: Mapped[str] = mapped_column(String, nullable=False, index=True)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        Enum("present", "absent", "late", name="attendance_status"),
        nullable=False,
    )
    marked_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=True)

    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    marker: Mapped["User"] = relationship(foreign_keys=[marked_by])
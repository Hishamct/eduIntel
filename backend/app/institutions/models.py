import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import TimestampMixin
from app.users.models import User


class Institution(Base, TimestampMixin):
    __tablename__ = "institutions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(50), default="standard", nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    memberships: Mapped[list["InstitutionMembership"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )


class InstitutionMembership(Base, TimestampMixin):
    __tablename__ = "institution_memberships"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)

    __table_args__ = (
        UniqueConstraint("institution_id", "user_id", name="uq_institution_memberships_inst_user"),
    )

    institution: Mapped["Institution"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship()

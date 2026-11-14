"""
backend/app/agents/models.py

SQLAlchemy models for Phase 5 AI agents, durable sessions, and tool execution tracking:
- ToolExecutionRecord: Fenced tool idempotency ledger tracking lease generation,
  attempt counts, and deterministic cached results across session turns.
- AgentSession: Multi-tenant, user-owned durable conversation session with explicit
  4-stage lifecycle and monotonic generation-fencing tokens.
- AgentSessionMessage: Ordered conversational turn record with composite foreign key
  guaranteeing strict cross-tenant integrity and terminal status tracking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.institutions.models import Institution
    from app.users.models import User


class ToolExecutionRecord(Base):
    """
    Durable, concurrency-safe tool execution record implementing fenced idempotency:
    1. Composite unique constraint (institution_id, session_id, turn_id, tool_call_id).
    2. Lease generation fencing token preventing split-brain mutations from stalled workers.
    3. Status lifecycle: RESERVED, EXECUTING, COMPLETED, FAILED, UNCERTAIN.
    4. Row-Level Security enabled and enforced across all tenant institutions.
    """

    __tablename__ = "tool_execution_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    turn_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RESERVED")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "session_id",
            "turn_id",
            "tool_call_id",
            name="uq_tool_execution_call",
        ),
    )


class AgentSession(Base):
    """
    Multi-tenant durable conversation session with strict user-level ownership,
    composite cross-tenant integrity constraints, explicit 4-stage lifecycle,
    and monotonically increasing generation-fencing tokens.
    """

    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New Conversation")

    # Explicit 4-Stage Lifecycle State
    is_expired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Monotonic Turn Counter
    turn_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Monotonic Generation Fencing & In-Flight Lease Control
    is_generating: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_client_turn_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_fence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generation_owner_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Telemetry and Timestamps
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # Composite unique constraint enabling cross-tenant foreign key verification
        UniqueConstraint("institution_id", "id", name="uq_agent_sessions_institution_id"),
        Index(
            "ix_agent_sessions_inst_user_access",
            "institution_id",
            "user_id",
            "last_accessed_at",
            postgresql_where=text("is_deleted = FALSE"),
        ),
        Index(
            "ix_agent_sessions_lifecycle_purge",
            "is_deleted",
            "deleted_at",
            "is_expired",
            "expired_at",
        ),
        Index(
            "ix_agent_sessions_lease",
            "is_generating",
            "generation_lease_expires_at",
            postgresql_where=text("is_generating = TRUE"),
        ),
        CheckConstraint("turn_counter >= 0", name="ck_agent_sessions_turn_counter_nonneg"),
        CheckConstraint("generation_fence >= 0", name="ck_agent_sessions_generation_fence_nonneg"),
    )

    # Relationships
    messages: Mapped[list[AgentSessionMessage]] = relationship(
        "AgentSessionMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        foreign_keys="[AgentSessionMessage.institution_id, AgentSessionMessage.session_id]",
        primaryjoin="and_(AgentSession.id==AgentSessionMessage.session_id, AgentSession.institution_id==AgentSessionMessage.institution_id)",
        order_by="AgentSessionMessage.turn_id",
    )
    institution: Mapped[Institution] = relationship("Institution")
    user: Mapped[User] = relationship("User")


class AgentSessionMessage(Base):
    """
    Immutable conversational message turn belonging to an AgentSession.
    Enforces composite foreign key referencing (institution_id, session_id) on agent_sessions,
    guaranteeing that cross-tenant message linkage is physically impossible.
    """

    __tablename__ = "agent_session_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    turn_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    client_turn_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # Composite foreign key to agent_sessions(institution_id, id)
        ForeignKeyConstraint(
            ["institution_id", "session_id"],
            ["agent_sessions.institution_id", "agent_sessions.id"],
            ondelete="CASCADE",
            name="fk_agent_session_messages_session",
        ),
        # Unique turn-role constraint per session
        UniqueConstraint(
            "institution_id",
            "session_id",
            "turn_id",
            "role",
            name="uq_session_turn_role",
        ),
        Index(
            "ix_agent_session_messages_session_turn",
            "institution_id",
            "session_id",
            "turn_id",
        ),
        Index(
            "ix_agent_session_messages_client_turn",
            "institution_id",
            "client_turn_id",
            postgresql_where=text("client_turn_id IS NOT NULL"),
        ),
        Index(
            "uq_agent_messages_client_turn_assistant_completed",
            "institution_id",
            "session_id",
            "client_turn_id",
            unique=True,
            postgresql_where=text("client_turn_id IS NOT NULL AND role = 'assistant' AND status = 'COMPLETED'"),
        ),
        CheckConstraint(
            "status IN ('COMPLETED', 'TRUNCATED', 'BLOCKED', 'FAILED')",
            name="ck_agent_session_messages_status",
        ),
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_agent_session_messages_role",
        ),
        CheckConstraint(
            "turn_id >= 1",
            name="ck_agent_session_messages_turn_id_pos",
        ),
    )

    # Relationships
    session: Mapped[AgentSession] = relationship(
        "AgentSession",
        back_populates="messages",
        foreign_keys="[AgentSessionMessage.institution_id, AgentSessionMessage.session_id]",
        primaryjoin="and_(AgentSession.id==AgentSessionMessage.session_id, AgentSession.institution_id==AgentSessionMessage.institution_id)",
        overlaps="institution",
    )
    institution: Mapped[Institution] = relationship("Institution", overlaps="messages,session")

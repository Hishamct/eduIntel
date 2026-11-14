"""
backend/app/agents/session_store.py

Phase 5 Step 3.2: Session Store Architecture, Generation Fencing & Concurrency Control.
Provides durable, multi-tenant conversational memory for EduIntel AI assistants:
- AbstractSessionStore: Unified abstract interface and domain exception hierarchy.
- DatabaseSessionStore: PostgreSQL-backed implementation leveraging SQLAlchemy AsyncSession,
  composite Row-Level Security, mandatory user ownership predicates, monotonic generation fencing,
  and wall-clock lease expiry via clock_timestamp().
- InMemorySessionStore: Fully compliant in-memory implementation for unit testing and local development.
- Single active generation lease per session with duplicate turn caching and fail-closed isolation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.agents.models import AgentSession, AgentSessionMessage
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.institutions.models import InstitutionMembership
from app.users.models import User

logger = logging.getLogger(__name__)

DEFAULT_GENERATION_LEASE_SECONDS = getattr(settings, "AGENT_GENERATION_LEASE_SECONDS", 60)
SESSION_INACTIVITY_TTL_SECONDS = 86400  # 24 hours


# ==============================================================================
# Domain Transfer Objects (DTOs)
# ==============================================================================

@dataclass(frozen=True)
class AgentSessionDTO:
    id: uuid.UUID
    institution_id: uuid.UUID
    user_id: uuid.UUID
    agent_name: str
    title: str
    turn_counter: int
    is_generating: bool
    generation_lease_expires_at: datetime | None
    active_client_turn_id: str | None
    generation_fence: int
    generation_owner_token: uuid.UUID | None
    is_expired: bool
    expired_at: datetime | None
    is_deleted: bool
    deleted_at: datetime | None
    closed_at: datetime | None
    last_accessed_at: datetime
    created_at: datetime
    metadata_json: dict[str, Any]


@dataclass(frozen=True)
class AgentMessageDTO:
    id: uuid.UUID
    institution_id: uuid.UUID
    session_id: uuid.UUID
    turn_id: int
    role: str
    content: str
    status: str
    client_turn_id: str | None
    token_count: int | None
    llm_usage: dict[str, Any] | None
    trace_id: uuid.UUID | None
    metadata_json: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class SessionTurnLeaseResult:
    session: AgentSessionDTO
    fence: int
    owner_token: uuid.UUID
    history: list[dict[str, str]]
    cached_response: dict[str, Any] | None = None
    is_cached: bool = False


# ==============================================================================
# Domain Exceptions Hierarchy
# ==============================================================================

class SessionStoreError(Exception):
    """Base exception for all agent session store operations."""


class SessionNotFoundError(SessionStoreError):
    """Raised when a requested session does not exist."""


class SessionAccessDeniedError(SessionStoreError):
    """Raised when a user attempts to access a session belonging to another user."""


class SessionExpiredError(SessionStoreError):
    """Raised when an operation is attempted on an expired session."""


class SessionDeletedError(SessionStoreError):
    """Raised when an operation is attempted on a soft-deleted session."""


class SessionConcurrencyError(SessionStoreError):
    """Raised when an operation conflicts with an active generation lease."""

    def __init__(self, message: str, retry_after: int = 5, is_duplicate: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.is_duplicate = is_duplicate


class FencedCommitPreemptedError(SessionStoreError):
    """Raised when an atomic turn commit is rejected because the fencing token was superseded or lease expired."""


class SessionStoreUnavailableError(SessionStoreError):
    """Raised in production when primary database datastore cannot be reached."""


# ==============================================================================
# Abstract Session Store Interface
# ==============================================================================

class AbstractSessionStore(ABC):
    """
    Unified asynchronous contract for conversational session persistence,
    generation fencing, and concurrency control.
    """

    @abstractmethod
    async def get_or_create_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        agent_name: str,
        title: str = "New Conversation",
        metadata: dict[str, Any] | None = None,
    ) -> AgentSessionDTO:
        """Retrieve existing active session or create a new session under user ownership."""
        ...

    @abstractmethod
    async def get_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentSessionDTO:
        """Retrieve an active session verifying user ownership."""
        ...

    @abstractmethod
    async def reserve_generation_lease(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        client_turn_id: str,
        lease_seconds: int = DEFAULT_GENERATION_LEASE_SECONDS,
        history_limit: int = 10,
    ) -> SessionTurnLeaseResult:
        """
        Atomically reserve a generation lease on the session row.
        - Returns cached response if client_turn_id was already completed (status='COMPLETED').
        - Raises SessionConcurrencyError if another generation is currently in progress.
        - Preempts stalled leases if lease_expires_at has passed.
        - Increments generation_fence and returns new owner_token.
        - Retrieves the most recent N history messages in chronological order.
        """
        ...

    @abstractmethod
    async def commit_turn_atomic(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        client_turn_id: str,
        fence: int,
        owner_token: uuid.UUID,
        user_message: str,
        assistant_message: str,
        llm_usage: dict[str, Any] | None = None,
        trace_id: uuid.UUID | None = None,
        status: str = "COMPLETED",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, AgentMessageDTO, AgentMessageDTO]:
        """
        Atomically commit completed conversational turn using conditional fencing token.
        - Verifies generation_fence, owner_token, and unexpired lease (lease_expires_at > clock_timestamp()).
        - Increments turn_counter, clears is_generating and lease attributes.
        - Inserts user and assistant AgentSessionMessage records in the same transaction.
        - Raises FencedCommitPreemptedError and rolls back completely if lease was preempted or expired.
        """
        ...

    @abstractmethod
    async def release_generation_lease(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        fence: int,
        owner_token: uuid.UUID,
    ) -> bool:
        """
        Safely release in-flight generation lease upon error, guardrail block, or failure.
        Only clears lease if fence and owner_token match. Does not increment turn_counter.
        """
        ...

    @abstractmethod
    async def soft_delete_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Soft-delete session by setting is_deleted=TRUE, deleted_at=clock_timestamp()."""
        ...

    @abstractmethod
    async def get_institution_session_audit(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        admin_user_id: uuid.UUID,
    ) -> tuple[AgentSessionDTO, list[AgentMessageDTO]]:
        """Authorized institutional administrator audit lookup bypassing user_id predicate."""
        ...


# ==============================================================================
# PostgreSQL Database Implementation
# ==============================================================================

class DatabaseSessionStore(AbstractSessionStore):
    """
    PostgreSQL-backed session store implementing generation fencing, RLS binding,
    mandatory user ownership predicates, and wall-clock lease expiry checks.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self.session_factory = session_factory or AsyncSessionLocal

    @staticmethod
    def _to_session_dto(session: AgentSession) -> AgentSessionDTO:
        return AgentSessionDTO(
            id=session.id,
            institution_id=session.institution_id,
            user_id=session.user_id,
            agent_name=session.agent_name,
            title=session.title,
            turn_counter=session.turn_counter,
            is_generating=session.is_generating,
            generation_lease_expires_at=session.generation_lease_expires_at,
            active_client_turn_id=session.active_client_turn_id,
            generation_fence=session.generation_fence,
            generation_owner_token=session.generation_owner_token,
            is_expired=session.is_expired,
            expired_at=session.expired_at,
            is_deleted=session.is_deleted,
            deleted_at=session.deleted_at,
            closed_at=session.closed_at,
            last_accessed_at=session.last_accessed_at,
            created_at=session.created_at,
            metadata_json=dict(session.metadata_json) if session.metadata_json else {},
        )

    @staticmethod
    def _to_message_dto(msg: AgentSessionMessage) -> AgentMessageDTO:
        return AgentMessageDTO(
            id=msg.id,
            institution_id=msg.institution_id,
            session_id=msg.session_id,
            turn_id=msg.turn_id,
            role=msg.role,
            content=msg.content,
            status=msg.status,
            client_turn_id=msg.client_turn_id,
            token_count=msg.token_count,
            llm_usage=dict(msg.llm_usage) if msg.llm_usage else None,
            trace_id=msg.trace_id,
            metadata_json=dict(msg.metadata_json) if msg.metadata_json else {},
            created_at=msg.created_at,
        )

    async def get_or_create_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        agent_name: str,
        title: str = "New Conversation",
        metadata: dict[str, Any] | None = None,
    ) -> AgentSessionDTO:
        sess_uuid = uuid.UUID(str(session_id))
        async with self.session_factory() as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                    {"inst_id": str(institution_id)},
                )
                stmt = select(AgentSession).where(
                    AgentSession.id == sess_uuid,
                    AgentSession.institution_id == institution_id,
                )
                session = (await db.execute(stmt)).scalars().first()
                if session:
                    if session.user_id != user_id:
                        raise SessionAccessDeniedError(
                            f"Access denied: session {sess_uuid} does not belong to user {user_id}"
                        )
                    if session.is_deleted:
                        raise SessionDeletedError(f"Session {sess_uuid} has been deleted")
                    return self._to_session_dto(session)

                # Create new session
                new_session = AgentSession(
                    id=sess_uuid,
                    institution_id=institution_id,
                    user_id=user_id,
                    agent_name=agent_name,
                    title=title,
                    turn_counter=0,
                    is_generating=False,
                    generation_fence=0,
                    is_expired=False,
                    is_deleted=False,
                    metadata_json=metadata or {},
                )
                db.add(new_session)
                await db.flush()
                return self._to_session_dto(new_session)

    async def get_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentSessionDTO:
        sess_uuid = uuid.UUID(str(session_id))
        async with self.session_factory() as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                    {"inst_id": str(institution_id)},
                )
                stmt = select(AgentSession).where(
                    AgentSession.id == sess_uuid,
                    AgentSession.institution_id == institution_id,
                )
                session = (await db.execute(stmt)).scalars().first()
                if not session:
                    raise SessionNotFoundError(f"Session {sess_uuid} not found")
                if session.user_id != user_id:
                    raise SessionAccessDeniedError(
                        f"Access denied: session {sess_uuid} does not belong to user {user_id}"
                    )
                if session.is_deleted:
                    raise SessionDeletedError(f"Session {sess_uuid} has been deleted")
                return self._to_session_dto(session)

    async def reserve_generation_lease(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        client_turn_id: str,
        lease_seconds: int = DEFAULT_GENERATION_LEASE_SECONDS,
        history_limit: int = 10,
    ) -> SessionTurnLeaseResult:
        sess_uuid = uuid.UUID(str(session_id))
        now = datetime.now(UTC)

        async with self.session_factory() as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                    {"inst_id": str(institution_id)},
                )
                # 1. Fetch and row-lock session
                stmt = (
                    select(AgentSession)
                    .where(
                        AgentSession.id == sess_uuid,
                        AgentSession.institution_id == institution_id,
                    )
                    .with_for_update()
                )
                session = (await db.execute(stmt)).scalars().first()
                if not session:
                    raise SessionNotFoundError(f"Session {sess_uuid} not found")
                if session.user_id != user_id:
                    raise SessionAccessDeniedError(
                        f"Access denied: session {sess_uuid} does not belong to user {user_id}"
                    )
                if session.is_deleted:
                    raise SessionDeletedError(f"Session {sess_uuid} has been deleted")

                # 2. Inactivity expiration check (24h)
                if session.is_expired or (now - session.last_accessed_at > timedelta(seconds=SESSION_INACTIVITY_TTL_SECONDS)):
                    session.is_expired = True
                    if not session.expired_at:
                        session.expired_at = now
                    await db.flush()
                    raise SessionExpiredError(f"Session {sess_uuid} has expired")

                # 3. Check for authoritative completed turn response
                cached_stmt = (
                    select(AgentSessionMessage)
                    .where(
                        AgentSessionMessage.institution_id == institution_id,
                        AgentSessionMessage.session_id == sess_uuid,
                        AgentSessionMessage.client_turn_id == client_turn_id,
                        AgentSessionMessage.role == "assistant",
                        AgentSessionMessage.status == "COMPLETED",
                    )
                    .order_by(AgentSessionMessage.created_at.desc())
                    .limit(1)
                )
                cached_msg = (await db.execute(cached_stmt)).scalars().first()

                # 4. Fetch recent N messages in chronological order (nested descending limit query)
                subq = (
                    select(AgentSessionMessage)
                    .where(
                        AgentSessionMessage.institution_id == institution_id,
                        AgentSessionMessage.session_id == sess_uuid,
                    )
                    .order_by(AgentSessionMessage.turn_id.desc(), AgentSessionMessage.created_at.desc())
                    .limit(history_limit)
                    .subquery("recent_messages")
                )
                hist_stmt = (
                    select(aliased(AgentSessionMessage, subq))
                    .order_by(subq.c.turn_id.asc(), subq.c.created_at.asc())
                )
                hist_records = (await db.execute(hist_stmt)).scalars().all()
                history = [{"role": m.role, "content": m.content} for m in hist_records]

                if cached_msg:
                    # Authoritative completed response cached: return without acquiring lease
                    return SessionTurnLeaseResult(
                        session=self._to_session_dto(session),
                        fence=session.generation_fence,
                        owner_token=session.generation_owner_token or uuid.uuid4(),
                        history=history,
                        cached_response={
                            "answer": cached_msg.content,
                            "llm_usage": cached_msg.llm_usage,
                            "trace_id": str(cached_msg.trace_id) if cached_msg.trace_id else None,
                            "status": cached_msg.status,
                        },
                        is_cached=True,
                    )

                # 5. Concurrency checks
                if session.is_generating and session.generation_lease_expires_at and session.generation_lease_expires_at > now:
                    if session.active_client_turn_id == client_turn_id:
                        raise SessionConcurrencyError("Duplicate request in flight", retry_after=2, is_duplicate=True)
                    raise SessionConcurrencyError(
                        "Another message is currently being processed for this session.",
                        retry_after=5,
                        is_duplicate=False,
                    )

                # 6. Acquire or preempt lease
                new_owner_token = uuid.uuid4()
                session.generation_fence += 1
                session.generation_owner_token = new_owner_token
                session.is_generating = True
                session.active_client_turn_id = client_turn_id
                session.generation_lease_expires_at = now + timedelta(seconds=lease_seconds)
                session.last_accessed_at = now

                await db.flush()
                return SessionTurnLeaseResult(
                    session=self._to_session_dto(session),
                    fence=session.generation_fence,
                    owner_token=new_owner_token,
                    history=history,
                    is_cached=False,
                )

    async def commit_turn_atomic(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        client_turn_id: str,
        fence: int,
        owner_token: uuid.UUID,
        user_message: str,
        assistant_message: str,
        llm_usage: dict[str, Any] | None = None,
        trace_id: uuid.UUID | None = None,
        status: str = "COMPLETED",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, AgentMessageDTO, AgentMessageDTO]:
        sess_uuid = uuid.UUID(str(session_id))
        now = datetime.now(UTC)

        async with self.session_factory() as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                    {"inst_id": str(institution_id)},
                )

                # 1. Acquire row lock verifying initial fencing preconditions to wait out concurrent lock holders
                lock_stmt = (
                    select(AgentSession.id)
                    .where(
                        AgentSession.id == sess_uuid,
                        AgentSession.institution_id == institution_id,
                        AgentSession.user_id == user_id,
                        AgentSession.generation_fence == fence,
                        AgentSession.generation_owner_token == owner_token,
                        AgentSession.is_generating.is_(True),
                    )
                    .with_for_update()
                )
                locked = (await db.execute(lock_stmt)).scalar_one_or_none()
                if locked is None:
                    raise FencedCommitPreemptedError(
                        f"Commit rejected: generation lease was preempted or missing for session {sess_uuid}"
                    )

                # 2. Conditional atomic database update enforcing ownership, fence, and unexpired lease via clock_timestamp()
                update_stmt = (
                    update(AgentSession)
                    .where(
                        AgentSession.id == sess_uuid,
                        AgentSession.institution_id == institution_id,
                        AgentSession.user_id == user_id,
                        AgentSession.generation_fence == fence,
                        AgentSession.generation_owner_token == owner_token,
                        AgentSession.is_generating.is_(True),
                        AgentSession.generation_lease_expires_at > func.clock_timestamp(),
                    )
                    .values(
                        is_generating=False,
                        generation_owner_token=None,
                        active_client_turn_id=None,
                        turn_counter=AgentSession.turn_counter + 1,
                        last_accessed_at=func.clock_timestamp(),
                        updated_at=func.clock_timestamp(),
                    )
                    .returning(AgentSession.turn_counter)
                )
                result = await db.execute(update_stmt)
                new_turn_counter = result.scalar_one_or_none()

                if new_turn_counter is None:
                    raise FencedCommitPreemptedError(
                        f"Commit rejected: generation lease was preempted or expired for session {sess_uuid}"
                    )

                # 2. Insert user message
                user_msg = AgentSessionMessage(
                    institution_id=institution_id,
                    session_id=sess_uuid,
                    turn_id=new_turn_counter,
                    role="user",
                    content=user_message,
                    status="COMPLETED",
                    client_turn_id=client_turn_id,
                    metadata_json=metadata or {},
                    created_at=now,
                )
                db.add(user_msg)

                # 3. Insert assistant message
                assistant_msg = AgentSessionMessage(
                    institution_id=institution_id,
                    session_id=sess_uuid,
                    turn_id=new_turn_counter,
                    role="assistant",
                    content=assistant_message,
                    status=status,
                    client_turn_id=client_turn_id,
                    llm_usage=llm_usage,
                    trace_id=trace_id,
                    metadata_json=metadata or {},
                    created_at=now,
                )
                db.add(assistant_msg)

                await db.flush()
                return (
                    new_turn_counter,
                    self._to_message_dto(user_msg),
                    self._to_message_dto(assistant_msg),
                )

    async def release_generation_lease(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        fence: int,
        owner_token: uuid.UUID,
    ) -> bool:
        sess_uuid = uuid.UUID(str(session_id))
        async with self.session_factory() as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                    {"inst_id": str(institution_id)},
                )
                stmt = (
                    update(AgentSession)
                    .where(
                        AgentSession.id == sess_uuid,
                        AgentSession.institution_id == institution_id,
                        AgentSession.user_id == user_id,
                        AgentSession.generation_fence == fence,
                        AgentSession.generation_owner_token == owner_token,
                    )
                    .values(
                        is_generating=False,
                        generation_owner_token=None,
                        active_client_turn_id=None,
                        last_accessed_at=func.clock_timestamp(),
                    )
                )
                result = await db.execute(stmt)
                return result.rowcount > 0

    async def soft_delete_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        sess_uuid = uuid.UUID(str(session_id))
        async with self.session_factory() as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                    {"inst_id": str(institution_id)},
                )
                stmt = (
                    update(AgentSession)
                    .where(
                        AgentSession.id == sess_uuid,
                        AgentSession.institution_id == institution_id,
                        AgentSession.user_id == user_id,
                        AgentSession.is_deleted.is_(False),
                    )
                    .values(
                        is_deleted=True,
                        deleted_at=func.clock_timestamp(),
                        last_accessed_at=func.clock_timestamp(),
                    )
                )
                result = await db.execute(stmt)
                return result.rowcount > 0

    async def get_institution_session_audit(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        admin_user_id: uuid.UUID,
    ) -> tuple[AgentSessionDTO, list[AgentMessageDTO]]:
        sess_uuid = uuid.UUID(str(session_id))
        async with self.session_factory() as db:
            async with db.begin():
                await db.execute(
                    text("SELECT set_config('app.current_institution_id', :inst_id, true)"),
                    {"inst_id": str(institution_id)},
                )

                # 1. Authorize admin status
                admin_stmt = select(User).where(User.id == admin_user_id)
                admin_user = (await db.execute(admin_stmt)).scalars().first()
                if not admin_user or not getattr(admin_user, "is_active", True):
                    raise SessionAccessDeniedError(f"User {admin_user_id} not found or inactive")

                is_platform_admin = getattr(admin_user, "is_platform_admin", False)
                is_admin_role = admin_user.role in ("admin", "institute_admin", "superadmin")

                if not (is_platform_admin or is_admin_role):
                    raise SessionAccessDeniedError(
                        f"User {admin_user_id} does not possess administrative audit rights"
                    )

                # For non-platform admins, strictly verify active membership within the target institution
                if not is_platform_admin:
                    membership_stmt = select(InstitutionMembership).where(
                        InstitutionMembership.institution_id == institution_id,
                        InstitutionMembership.user_id == admin_user_id,
                        InstitutionMembership.status == "active",
                    )
                    membership = (await db.execute(membership_stmt)).scalars().first()
                    if not membership:
                        raise SessionAccessDeniedError(
                            f"User {admin_user_id} does not possess an active membership in institution {institution_id}"
                        )
                    if membership.role not in ("admin", "institute_admin", "superadmin") and admin_user.role not in ("admin", "institute_admin", "superadmin"):
                        raise SessionAccessDeniedError(
                            f"User {admin_user_id} does not possess administrative role in institution {institution_id}"
                        )

                # 2. Query session within institution
                sess_stmt = select(AgentSession).where(
                    AgentSession.id == sess_uuid,
                    AgentSession.institution_id == institution_id,
                )
                session = (await db.execute(sess_stmt)).scalars().first()
                if not session:
                    raise SessionNotFoundError(f"Session {sess_uuid} not found for institution {institution_id}")

                # 3. Query all messages
                msg_stmt = (
                    select(AgentSessionMessage)
                    .where(
                        AgentSessionMessage.institution_id == institution_id,
                        AgentSessionMessage.session_id == sess_uuid,
                    )
                    .order_by(AgentSessionMessage.turn_id.asc(), AgentSessionMessage.created_at.asc())
                )
                messages = (await db.execute(msg_stmt)).scalars().all()

                return (
                    self._to_session_dto(session),
                    [self._to_message_dto(m) for m in messages],
                )


# ==============================================================================
# In-Memory Session Store Implementation (Testing & Development)
# ==============================================================================

class InMemorySessionStore(AbstractSessionStore):
    """
    Thread-safe / asyncio-safe in-memory session store providing 100% public
    contract parity with DatabaseSessionStore for isolated tests and local development.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[uuid.UUID, dict[str, Any]] = {}
        self._messages: dict[uuid.UUID, list[dict[str, Any]]] = {}
        self._users: dict[uuid.UUID, dict[str, Any]] = {}
        self._memberships: dict[tuple[uuid.UUID, uuid.UUID], dict[str, Any]] = {}

    def clear(self) -> None:
        self._sessions.clear()
        self._messages.clear()
        self._users.clear()
        self._memberships.clear()

    def register_user(
        self,
        user_id: uuid.UUID,
        role: str = "student",
        is_platform_admin: bool = False,
        is_active: bool = True,
    ) -> None:
        self._users[user_id] = {
            "id": user_id,
            "role": role,
            "is_platform_admin": is_platform_admin,
            "is_active": is_active,
        }

    def register_membership(
        self,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str = "admin",
        status: str = "active",
    ) -> None:
        self._memberships[(institution_id, user_id)] = {
            "institution_id": institution_id,
            "user_id": user_id,
            "role": role,
            "status": status,
        }

    async def get_or_create_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        agent_name: str,
        title: str = "New Conversation",
        metadata: dict[str, Any] | None = None,
    ) -> AgentSessionDTO:
        sess_uuid = uuid.UUID(str(session_id))
        async with self._lock:
            session = self._sessions.get(sess_uuid)
            if session:
                if session["institution_id"] != institution_id or session["user_id"] != user_id:
                    raise SessionAccessDeniedError("Access to session denied")
                if session["is_deleted"]:
                    raise SessionDeletedError(f"Session {sess_uuid} is soft-deleted")
                return self._dict_to_session_dto(session)

            now = datetime.now(UTC)
            session_data = {
                "id": sess_uuid,
                "institution_id": institution_id,
                "user_id": user_id,
                "agent_name": agent_name,
                "title": title,
                "turn_counter": 0,
                "is_generating": False,
                "generation_lease_expires_at": None,
                "active_client_turn_id": None,
                "generation_fence": 0,
                "generation_owner_token": None,
                "is_expired": False,
                "expired_at": None,
                "is_deleted": False,
                "deleted_at": None,
                "closed_at": None,
                "last_accessed_at": now,
                "created_at": now,
                "metadata_json": metadata or {},
            }
            self._sessions[sess_uuid] = session_data
            self._messages[sess_uuid] = []
            return self._dict_to_session_dto(session_data)

    async def get_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentSessionDTO:
        sess_uuid = uuid.UUID(str(session_id))
        async with self._lock:
            session = self._sessions.get(sess_uuid)
            if not session or session["institution_id"] != institution_id:
                raise SessionNotFoundError(f"Session {sess_uuid} not found")
            if session["user_id"] != user_id:
                raise SessionAccessDeniedError(f"Access to session {sess_uuid} denied")
            if session["is_deleted"]:
                raise SessionDeletedError(f"Session {sess_uuid} is soft-deleted")
            return self._dict_to_session_dto(session)

    async def reserve_generation_lease(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        client_turn_id: str,
        lease_seconds: int = DEFAULT_GENERATION_LEASE_SECONDS,
        history_limit: int = 10,
    ) -> SessionTurnLeaseResult:
        sess_uuid = uuid.UUID(str(session_id))
        now = datetime.now(UTC)
        async with self._lock:
            session = self._sessions.get(sess_uuid)
            if not session or session["institution_id"] != institution_id:
                raise SessionNotFoundError(f"Session {sess_uuid} not found")
            if session["user_id"] != user_id:
                raise SessionAccessDeniedError(f"Access to session {sess_uuid} denied")
            if session["is_deleted"]:
                raise SessionDeletedError(f"Session {sess_uuid} is soft-deleted")

            # Inactivity check
            if session["is_expired"] or (now - session["last_accessed_at"] > timedelta(seconds=SESSION_INACTIVITY_TTL_SECONDS)):
                session["is_expired"] = True
                if not session["expired_at"]:
                    session["expired_at"] = now
                raise SessionExpiredError(f"Session {sess_uuid} has expired")

            # Check for authoritative completed turn response
            messages = self._messages.get(sess_uuid, [])
            cached_msg = None
            for m in reversed(messages):
                if m.get("client_turn_id") == client_turn_id and m.get("role") == "assistant" and m.get("status") == "COMPLETED":
                    cached_msg = m
                    break

            # Recent N history messages in chronological order
            recent_slice = messages[-history_limit:] if history_limit > 0 else messages
            history = [{"role": m["role"], "content": m["content"]} for m in recent_slice]

            if cached_msg:
                return SessionTurnLeaseResult(
                    session=self._dict_to_session_dto(session),
                    fence=session["generation_fence"],
                    owner_token=session["generation_owner_token"] or uuid.uuid4(),
                    history=history,
                    cached_response={
                        "answer": cached_msg["content"],
                        "llm_usage": cached_msg.get("llm_usage"),
                        "trace_id": str(cached_msg["trace_id"]) if cached_msg.get("trace_id") else None,
                        "status": cached_msg["status"],
                    },
                    is_cached=True,
                )

            # Concurrency check
            if session["is_generating"] and session["generation_lease_expires_at"] and session["generation_lease_expires_at"] > now:
                if session["active_client_turn_id"] == client_turn_id:
                    raise SessionConcurrencyError("Duplicate request in flight", retry_after=2, is_duplicate=True)
                raise SessionConcurrencyError(
                    "Another message is currently being processed for this session.",
                    retry_after=5,
                    is_duplicate=False,
                )

            # Acquire or preempt lease
            new_owner_token = uuid.uuid4()
            session["generation_fence"] += 1
            session["generation_owner_token"] = new_owner_token
            session["is_generating"] = True
            session["active_client_turn_id"] = client_turn_id
            session["generation_lease_expires_at"] = now + timedelta(seconds=lease_seconds)
            session["last_accessed_at"] = now

            return SessionTurnLeaseResult(
                session=self._dict_to_session_dto(session),
                fence=session["generation_fence"],
                owner_token=new_owner_token,
                history=history,
                is_cached=False,
            )

    async def commit_turn_atomic(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        client_turn_id: str,
        fence: int,
        owner_token: uuid.UUID,
        user_message: str,
        assistant_message: str,
        llm_usage: dict[str, Any] | None = None,
        trace_id: uuid.UUID | None = None,
        status: str = "COMPLETED",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, AgentMessageDTO, AgentMessageDTO]:
        sess_uuid = uuid.UUID(str(session_id))
        now = datetime.now(UTC)
        async with self._lock:
            session = self._sessions.get(sess_uuid)
            if not session:
                raise SessionNotFoundError(f"Session {sess_uuid} not found")

            # Conditional fenced verification using wall-clock time
            if (
                session["institution_id"] != institution_id
                or session["user_id"] != user_id
                or session["generation_fence"] != fence
                or session["generation_owner_token"] != owner_token
                or not session["is_generating"]
                or session["generation_lease_expires_at"] is None
                or session["generation_lease_expires_at"] <= now
            ):
                raise FencedCommitPreemptedError(
                    f"Commit rejected: generation lease was preempted or expired for session {sess_uuid}"
                )

            session["turn_counter"] += 1
            new_turn_counter = session["turn_counter"]
            session["is_generating"] = False
            session["generation_owner_token"] = None
            session["active_client_turn_id"] = None
            session["last_accessed_at"] = now

            user_msg_dict = {
                "id": uuid.uuid4(),
                "institution_id": institution_id,
                "session_id": sess_uuid,
                "turn_id": new_turn_counter,
                "role": "user",
                "content": user_message,
                "status": "COMPLETED",
                "client_turn_id": client_turn_id,
                "token_count": None,
                "llm_usage": None,
                "trace_id": None,
                "metadata_json": metadata or {},
                "created_at": now,
            }
            assistant_msg_dict = {
                "id": uuid.uuid4(),
                "institution_id": institution_id,
                "session_id": sess_uuid,
                "turn_id": new_turn_counter,
                "role": "assistant",
                "content": assistant_message,
                "status": status,
                "client_turn_id": client_turn_id,
                "token_count": None,
                "llm_usage": llm_usage,
                "trace_id": trace_id,
                "metadata_json": metadata or {},
                "created_at": now,
            }

            self._messages[sess_uuid].append(user_msg_dict)
            self._messages[sess_uuid].append(assistant_msg_dict)

            return (
                new_turn_counter,
                self._dict_to_message_dto(user_msg_dict),
                self._dict_to_message_dto(assistant_msg_dict),
            )

    async def release_generation_lease(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        fence: int,
        owner_token: uuid.UUID,
    ) -> bool:
        sess_uuid = uuid.UUID(str(session_id))
        now = datetime.now(UTC)
        async with self._lock:
            session = self._sessions.get(sess_uuid)
            if (
                session
                and session["institution_id"] == institution_id
                and session["user_id"] == user_id
                and session["generation_fence"] == fence
                and session["generation_owner_token"] == owner_token
            ):
                session["is_generating"] = False
                session["generation_owner_token"] = None
                session["active_client_turn_id"] = None
                session["last_accessed_at"] = now
                return True
            return False

    async def soft_delete_session(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        sess_uuid = uuid.UUID(str(session_id))
        now = datetime.now(UTC)
        async with self._lock:
            session = self._sessions.get(sess_uuid)
            if (
                session
                and session["institution_id"] == institution_id
                and session["user_id"] == user_id
                and not session["is_deleted"]
            ):
                session["is_deleted"] = True
                session["deleted_at"] = now
                session["last_accessed_at"] = now
                return True
            return False

    async def get_institution_session_audit(
        self,
        session_id: uuid.UUID | str,
        institution_id: uuid.UUID,
        admin_user_id: uuid.UUID,
    ) -> tuple[AgentSessionDTO, list[AgentMessageDTO]]:
        sess_uuid = uuid.UUID(str(session_id))
        async with self._lock:
            # If user registry is populated, enforce admin authorization & membership
            if admin_user_id in self._users:
                user = self._users[admin_user_id]
                if not user.get("is_active", True):
                    raise SessionAccessDeniedError(f"User {admin_user_id} is inactive")
                is_platform_admin = user.get("is_platform_admin", False)
                is_admin_role = user.get("role") in ("admin", "institute_admin", "superadmin")
                if not (is_platform_admin or is_admin_role):
                    raise SessionAccessDeniedError(
                        f"User {admin_user_id} does not possess administrative audit rights"
                    )
                if not is_platform_admin:
                    mem = self._memberships.get((institution_id, admin_user_id))
                    if not mem or mem.get("status") != "active":
                        raise SessionAccessDeniedError(
                            f"User {admin_user_id} does not possess an active membership in institution {institution_id}"
                        )
                    if mem.get("role") not in ("admin", "institute_admin", "superadmin") and user.get("role") not in ("admin", "institute_admin", "superadmin"):
                        raise SessionAccessDeniedError(
                            f"User {admin_user_id} does not possess administrative role in institution {institution_id}"
                        )

            session = self._sessions.get(sess_uuid)
            if not session or session["institution_id"] != institution_id:
                raise SessionNotFoundError(f"Session {sess_uuid} not found for institution {institution_id}")
            messages = self._messages.get(sess_uuid, [])
            return (
                self._dict_to_session_dto(session),
                [self._dict_to_message_dto(m) for m in messages],
            )

    @staticmethod
    def _dict_to_session_dto(d: dict[str, Any]) -> AgentSessionDTO:
        return AgentSessionDTO(
            id=d["id"],
            institution_id=d["institution_id"],
            user_id=d["user_id"],
            agent_name=d["agent_name"],
            title=d["title"],
            turn_counter=d["turn_counter"],
            is_generating=d["is_generating"],
            generation_lease_expires_at=d["generation_lease_expires_at"],
            active_client_turn_id=d["active_client_turn_id"],
            generation_fence=d["generation_fence"],
            generation_owner_token=d["generation_owner_token"],
            is_expired=d["is_expired"],
            expired_at=d["expired_at"],
            is_deleted=d["is_deleted"],
            deleted_at=d["deleted_at"],
            closed_at=d["closed_at"],
            last_accessed_at=d["last_accessed_at"],
            created_at=d["created_at"],
            metadata_json=dict(d["metadata_json"]),
        )

    @staticmethod
    def _dict_to_message_dto(d: dict[str, Any]) -> AgentMessageDTO:
        return AgentMessageDTO(
            id=d["id"],
            institution_id=d["institution_id"],
            session_id=d["session_id"],
            turn_id=d["turn_id"],
            role=d["role"],
            content=d["content"],
            status=d["status"],
            client_turn_id=d["client_turn_id"],
            token_count=d["token_count"],
            llm_usage=d["llm_usage"],
            trace_id=d["trace_id"],
            metadata_json=dict(d["metadata_json"]),
            created_at=d["created_at"],
        )

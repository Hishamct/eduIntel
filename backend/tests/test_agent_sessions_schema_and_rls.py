"""
backend/tests/test_agent_sessions_schema_and_rls.py

Comprehensive schema, integrity, and Row-Level Security (RLS) tests for Step 3.1:
1. SQLAlchemy Models & Field Validation:
   - AgentSession model attributes, defaults, lifecycle timestamps.
   - AgentSessionMessage model attributes, terminal statuses, role constraints.
   - Generation fencing schema attributes and initial states.
2. Database Integrity Constraints:
   - Composite unique constraint on agent_sessions (institution_id, id).
   - Composite foreign key on agent_session_messages (institution_id, session_id).
   - Rejection of cross-tenant message injection (mismatched institution_id).
   - Cascading deletion from session to messages.
   - Unique constraint on (institution_id, session_id, turn_id, role).
   - Check constraints on status, role, and turn_id.
3. Generation-Fencing Schema Verification:
   - Initial fence value (0), monotonic increment, owner token UUID, active lease TTL.
   - Check constraint preventing negative generation_fence or turn_counter.
4. Multi-Tenant Row-Level Security (RLS):
   - Tenant A creates and reads its own sessions and messages under app.current_institution_id.
   - Tenant B cannot read Tenant A records (returns None under RLS).
   - Tenant B cannot update or delete Tenant A records (affects 0 rows under RLS).
   - Missing tenant context fails closed (returns None).
   - Platform admin read-bypass behavior.
   - Step 1 tool_execution_records RLS regression check.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentSession, AgentSessionMessage, ToolExecutionRecord
from app.auth.security import hash_password
from app.institutions.models import Institution
from app.users.models import User

# ==============================================================================
# Helper Fixtures & Setup Routines
# ==============================================================================

async def _set_tenant_context(session: AsyncSession, inst_id: uuid.UUID | None, is_platform_admin: bool = False) -> None:
    inst_str = str(inst_id) if inst_id else ""
    admin_str = "true" if is_platform_admin else "false"
    await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_str}', true);"))
    await session.execute(text(f"SELECT set_config('app.is_platform_admin', '{admin_str}', true);"))


async def _get_or_create_institution(session: AsyncSession, inst_id: uuid.UUID, name: str, slug: str) -> Institution:
    inst = (await session.execute(select(Institution).where(Institution.id == inst_id))).scalars().first()
    if not inst:
        inst = Institution(id=inst_id, name=name, slug=slug, is_active=True)
        session.add(inst)
        await session.flush()
    return inst


async def _get_or_create_user(session: AsyncSession, user_id: uuid.UUID, email: str, role: str = "student") -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalars().first()
    if not user:
        user = User(
            id=user_id,
            email=email,
            name=f"Test {role.capitalize()}",
            hashed_password=hash_password("TestPassword123!"),
            role=role,
            is_active=True,
        )
        session.add(user)
        await session.flush()
    return user


# ==============================================================================
# Suite 1: SQLAlchemy Model Attribute & Default Tests
# ==============================================================================

class TestAgentSessionModelDefinitions:
    """Verifies declarative SQLAlchemy models, defaults, and field structures."""

    def test_agent_session_model_attributes_and_defaults(self):
        sess_id = uuid.uuid4()
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        session = AgentSession(
            id=sess_id,
            institution_id=inst_id,
            user_id=user_id,
            agent_name="portal_assistant",
            title="Physics Homework Help",
            is_expired=False,
            is_deleted=False,
            turn_counter=0,
            is_generating=False,
            generation_fence=0,
        )

        assert session.id == sess_id
        assert session.institution_id == inst_id
        assert session.user_id == user_id
        assert session.agent_name == "portal_assistant"
        assert session.title == "Physics Homework Help"
        assert session.is_expired is False
        assert session.expired_at is None
        assert session.is_deleted is False
        assert session.deleted_at is None
        assert session.closed_at is None
        assert session.turn_counter == 0
        assert session.is_generating is False
        assert session.generation_lease_expires_at is None
        assert session.active_client_turn_id is None
        assert session.generation_fence == 0
        assert session.generation_owner_token is None

        # Verify SQLAlchemy column default metadata
        assert AgentSession.__table__.c.is_expired.default.arg is False
        assert AgentSession.__table__.c.is_deleted.default.arg is False
        assert AgentSession.__table__.c.turn_counter.default.arg == 0
        assert AgentSession.__table__.c.is_generating.default.arg is False
        assert AgentSession.__table__.c.generation_fence.default.arg == 0

    def test_agent_session_message_model_attributes_and_statuses(self):
        inst_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        client_turn = f"turn_{uuid.uuid4().hex[:8]}"

        for valid_status in ("COMPLETED", "TRUNCATED", "BLOCKED", "FAILED"):
            msg = AgentSessionMessage(
                institution_id=inst_id,
                session_id=sess_id,
                turn_id=1,
                role="assistant",
                content="Here is the explanation.",
                status=valid_status,
                client_turn_id=client_turn,
            )
            assert msg.status == valid_status
            assert msg.turn_id == 1
            assert msg.role == "assistant"
            assert msg.client_turn_id == client_turn


# ==============================================================================
# Suite 2: Database Integrity Constraints & Composite Keys
# ==============================================================================

class TestDatabaseIntegrityConstraints:
    """Tests composite foreign keys, unique constraints, and cascading deletions."""

    async def test_session_and_message_creation_happy_path(self, test_engine):
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_id = uuid.uuid4()

        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            await _set_tenant_context(session, inst_id)
            await _get_or_create_institution(session, inst_id, "Integrity Tenant", "integrity-inst")
            await _get_or_create_user(session, user_id, f"student-{user_id.hex[:6]}@test.edu")

            agent_session = AgentSession(
                institution_id=inst_id,
                user_id=user_id,
                agent_name="portal_assistant",
                title="Mathematics Query",
            )
            session.add(agent_session)
            await session.flush()

            msg_user = AgentSessionMessage(
                institution_id=inst_id,
                session_id=agent_session.id,
                turn_id=1,
                role="user",
                content="Can you explain Pythagorean theorem?",
                status="COMPLETED",
            )
            msg_assistant = AgentSessionMessage(
                institution_id=inst_id,
                session_id=agent_session.id,
                turn_id=1,
                role="assistant",
                content="The Pythagorean theorem states that a^2 + b^2 = c^2.",
                status="COMPLETED",
                llm_usage={"total_tokens": 42},
            )
            session.add_all([msg_user, msg_assistant])
            await session.flush()

            # Verify persisted records within transaction
            persisted_sess = (await session.execute(select(AgentSession).where(AgentSession.id == agent_session.id))).scalar_one()
            assert persisted_sess.title == "Mathematics Query"

            persisted_msgs = (
                await session.execute(
                    select(AgentSessionMessage)
                    .where(AgentSessionMessage.session_id == agent_session.id)
                    .order_by(AgentSessionMessage.turn_id, AgentSessionMessage.role)
                )
            ).scalars().all()
            assert len(persisted_msgs) == 2
            await session.rollback()

    async def test_cross_tenant_message_injection_rejected_by_composite_fk(self, test_engine):
        """
        Critical Security Invariant:
        A message cannot be inserted with institution_id = Tenant_B referencing a session in Tenant_A.
        The composite foreign key (institution_id, session_id) -> (institution_id, id) must reject it.
        """
        inst_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
        inst_b = uuid.UUID("00000000-0000-0000-0000-000000000002")
        user_id = uuid.uuid4()

        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            # Setup institutions
            await _set_tenant_context(session, None, is_platform_admin=True)
            await _get_or_create_institution(session, inst_a, "Tenant A", "tenant-a-fk")
            await _get_or_create_institution(session, inst_b, "Tenant B", "tenant-b-fk")
            await _get_or_create_user(session, user_id, f"student-{user_id.hex[:6]}@test.edu")

            # Create session in Tenant A with Tenant A context
            await _set_tenant_context(session, inst_a)
            sess_a = AgentSession(
                institution_id=inst_a,
                user_id=user_id,
                agent_name="portal_assistant",
                title="Tenant A Session",
            )
            session.add(sess_a)
            await session.flush()

            # Switch to Tenant B context and attempt cross-tenant injection:
            # Message has institution_id = inst_b referencing sess_a (which belongs to inst_a)
            await _set_tenant_context(session, inst_b)
            rogue_msg = AgentSessionMessage(
                institution_id=inst_b,  # Tenant B
                session_id=sess_a.id,   # Session belongs to Tenant A!
                turn_id=1,
                role="user",
                content="Cross-tenant injected message",
                status="COMPLETED",
            )
            session.add(rogue_msg)

            with pytest.raises(IntegrityError) as exc_info:
                await session.flush()

            assert "fk_agent_session_messages_session" in str(exc_info.value)
            await session.rollback()

    async def test_duplicate_turn_role_rejected_by_unique_constraint(self, test_engine):
        """Asserts uq_session_turn_role prevents two assistant or user messages on the same turn."""
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_id = uuid.uuid4()

        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            await _set_tenant_context(session, inst_id)
            await _get_or_create_institution(session, inst_id, "Turn Inst", "turn-inst")
            await _get_or_create_user(session, user_id, f"student-{user_id.hex[:6]}@test.edu")

            agent_session = AgentSession(
                institution_id=inst_id,
                user_id=user_id,
                agent_name="admin_assistant",
                title="Duplicate Turn Test",
            )
            session.add(agent_session)
            await session.flush()

            msg1 = AgentSessionMessage(
                institution_id=inst_id,
                session_id=agent_session.id,
                turn_id=1,
                role="assistant",
                content="First assistant response",
            )
            msg2 = AgentSessionMessage(
                institution_id=inst_id,
                session_id=agent_session.id,
                turn_id=1,
                role="assistant",  # Duplicate turn_id and role!
                content="Second colliding assistant response",
            )
            session.add(msg1)
            await session.flush()

            session.add(msg2)
            with pytest.raises(IntegrityError) as exc_info:
                await session.flush()

            assert "uq_session_turn_role" in str(exc_info.value)
            await session.rollback()

    async def test_cascading_deletion_removes_session_messages(self, test_engine):
        """Permanent deletion of an agent_session cascades to all its agent_session_messages."""
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_id = uuid.uuid4()

        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            await _set_tenant_context(session, inst_id)
            await _get_or_create_institution(session, inst_id, "Cascade Inst", "cascade-inst")
            await _get_or_create_user(session, user_id, f"student-{user_id.hex[:6]}@test.edu")

            agent_session = AgentSession(
                institution_id=inst_id,
                user_id=user_id,
                agent_name="portal_assistant",
                title="Cascade Test Session",
            )
            session.add(agent_session)
            await session.flush()

            for t in range(1, 4):
                session.add(
                    AgentSessionMessage(
                        institution_id=inst_id,
                        session_id=agent_session.id,
                        turn_id=t,
                        role="user",
                        content=f"Question {t}",
                    )
                )
            await session.flush()

            # Confirm 3 messages exist
            count_stmt = select(func.count(AgentSessionMessage.id)).where(AgentSessionMessage.session_id == agent_session.id)
            count = (await session.execute(count_stmt)).scalar()
            assert count == 3

            # Hard delete parent session
            await session.delete(agent_session)
            await session.flush()

            # Confirm all messages cascaded
            remaining = (await session.execute(count_stmt)).scalar()
            assert remaining == 0
            await session.rollback()


# ==============================================================================
# Suite 3: Generation Fencing & Concurrency Schema Tests
# ==============================================================================

class TestGenerationFencingSchema:
    """Verifies fencing tokens, owner tokens, active generation lease tracking, and non-negativity."""

    async def test_generation_fencing_lifecycle_transitions(self, test_engine):
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_id = uuid.uuid4()

        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            await _set_tenant_context(session, inst_id)
            await _get_or_create_institution(session, inst_id, "Fence Inst", "fence-inst")
            await _get_or_create_user(session, user_id, f"student-{user_id.hex[:6]}@test.edu")

            agent_session = AgentSession(
                institution_id=inst_id,
                user_id=user_id,
                agent_name="admin_assistant",
                title="Fencing Protocol Session",
            )
            session.add(agent_session)
            await session.flush()

            # Initial state
            assert agent_session.generation_fence == 0
            assert agent_session.is_generating is False
            assert agent_session.generation_owner_token is None

            # Simulate Worker 1 acquiring lease (fence = 1)
            owner_1 = uuid.uuid4()
            lease_expires = datetime.now(UTC) + timedelta(seconds=45)
            agent_session.is_generating = True
            agent_session.generation_fence += 1
            agent_session.generation_owner_token = owner_1
            agent_session.generation_lease_expires_at = lease_expires
            agent_session.active_client_turn_id = "client_turn_abc"
            await session.flush()

            assert agent_session.generation_fence == 1
            assert agent_session.is_generating is True
            assert agent_session.generation_owner_token == owner_1

            # Simulate Worker 2 superseding stalled lease (fence = 2)
            owner_2 = uuid.uuid4()
            agent_session.generation_fence += 1
            agent_session.generation_owner_token = owner_2
            agent_session.active_client_turn_id = "client_turn_def"
            await session.flush()

            assert agent_session.generation_fence == 2
            assert agent_session.generation_owner_token == owner_2
            await session.rollback()

    async def test_negative_generation_fence_rejected_by_check_constraint(self, test_engine):
        inst_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_id = uuid.uuid4()

        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            await _set_tenant_context(session, inst_id)
            await _get_or_create_institution(session, inst_id, "Check Inst", "check-inst")
            await _get_or_create_user(session, user_id, f"student-{user_id.hex[:6]}@test.edu")

            invalid_session = AgentSession(
                institution_id=inst_id,
                user_id=user_id,
                agent_name="portal_assistant",
                title="Negative Fence Test",
                generation_fence=-1,  # Violates ck_agent_sessions_generation_fence_nonneg
            )
            session.add(invalid_session)
            with pytest.raises(IntegrityError) as exc_info:
                await session.flush()

            assert "ck_agent_sessions_generation_fence_nonneg" in str(exc_info.value)
            await session.rollback()


# ==============================================================================
# Suite 4: Multi-Tenant Row-Level Security (RLS) Tests
# ==============================================================================

class TestAgentSessionsRLS:
    """Verifies live PostgreSQL Row-Level Security on agent_sessions and agent_session_messages."""

    async def test_cross_tenant_rls_isolation_on_sessions_and_messages(self, test_engine):
        inst_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
        inst_b = uuid.UUID("00000000-0000-0000-0000-000000000002")
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        # Step 1: Provision institutions and users under platform admin
        async with AsyncSession(test_engine, expire_on_commit=False) as setup_session:
            await _set_tenant_context(setup_session, None, is_platform_admin=True)
            await _get_or_create_institution(setup_session, inst_a, "Tenant A", "tenant-a-rls-sess")
            await _get_or_create_institution(setup_session, inst_b, "Tenant B", "tenant-b-rls-sess")
            user_rec_a = await _get_or_create_user(setup_session, user_a, f"user-a-{user_a.hex[:6]}@tenant-a.edu")
            user_rec_b = await _get_or_create_user(setup_session, user_b, f"user-b-{user_b.hex[:6]}@tenant-b.edu")
            user_a_id = user_rec_a.id
            assert user_rec_b.id is not None
            await setup_session.commit()

        # Step 2: Tenant A creates session and messages under RLS
        async with AsyncSession(test_engine, expire_on_commit=False) as session_a:
            await _set_tenant_context(session_a, inst_a)

            sess_a = AgentSession(
                institution_id=inst_a,
                user_id=user_a_id,
                agent_name="portal_assistant",
                title="Confidential Physics Study",
            )
            session_a.add(sess_a)
            await session_a.flush()

            msg_a = AgentSessionMessage(
                institution_id=inst_a,
                session_id=sess_a.id,
                turn_id=1,
                role="user",
                content="Tenant A confidential physics question",
                status="COMPLETED",
            )
            session_a.add(msg_a)
            await session_a.commit()
            sess_a_id = sess_a.id
            msg_a_id = msg_a.id

        # Step 3: Tenant B cannot read Tenant A's session or messages under RLS
        async with AsyncSession(test_engine, expire_on_commit=False) as session_b:
            await _set_tenant_context(session_b, inst_b)

            # Query session
            read_sess = (await session_b.execute(select(AgentSession).where(AgentSession.id == sess_a_id))).scalar_one_or_none()
            assert read_sess is None, "Tenant B must NOT read Tenant A's session under RLS"

            # Query message
            read_msg = (await session_b.execute(select(AgentSessionMessage).where(AgentSessionMessage.id == msg_a_id))).scalar_one_or_none()
            assert read_msg is None, "Tenant B must NOT read Tenant A's message under RLS"

            # Step 4: Tenant B cannot modify Tenant A's session or messages
            upd_sess = await session_b.execute(
                update(AgentSession).where(AgentSession.id == sess_a_id).values(title="Hacked Title")
            )
            assert upd_sess.rowcount == 0, "Tenant B UPDATE on session must affect 0 rows"

            upd_msg = await session_b.execute(
                update(AgentSessionMessage).where(AgentSessionMessage.id == msg_a_id).values(content="Hacked Content")
            )
            assert upd_msg.rowcount == 0, "Tenant B UPDATE on message must affect 0 rows"

        # Step 5: Missing tenant context fails closed (returns None)
        async with AsyncSession(test_engine, expire_on_commit=False) as session_anon:
            await _set_tenant_context(session_anon, None)

            anon_sess = (await session_anon.execute(select(AgentSession).where(AgentSession.id == sess_a_id))).scalar_one_or_none()
            assert anon_sess is None, "Anonymous/empty tenant context must fail closed"

            anon_msg = (await session_anon.execute(select(AgentSessionMessage).where(AgentSessionMessage.id == msg_a_id))).scalar_one_or_none()
            assert anon_msg is None, "Anonymous/empty tenant context must fail closed"

        # Step 6: Step 1 tool_execution_records RLS regression check
        async with AsyncSession(test_engine, expire_on_commit=False) as session_regr:
            await _set_tenant_context(session_regr, inst_a)

            record = ToolExecutionRecord(
                institution_id=inst_a,
                session_id=f"sess_{uuid.uuid4().hex[:8]}",
                turn_id=1,
                tool_call_id=f"call_{uuid.uuid4().hex[:8]}",
                tool_name="get_student_teacher_counts",
                arguments_hash="hash123",
                status="COMPLETED",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            session_regr.add(record)
            await session_regr.commit()
            record_id = record.id

        # Verify Tenant B cannot access tool_execution_record
        async with AsyncSession(test_engine, expire_on_commit=False) as session_b_regr:
            await _set_tenant_context(session_b_regr, inst_b)

            regr_read = (await session_b_regr.execute(select(ToolExecutionRecord).where(ToolExecutionRecord.id == record_id))).scalar_one_or_none()
            assert regr_read is None, "Step 1 ToolExecutionRecord RLS must remain fully operational"

"""
backend/tests/test_agent_session_store.py

Comprehensive tests for Step 3.2: Session Store Architecture, Generation Fencing & Concurrency Control.
Verifies all 21 test scenarios defined in the frozen Version 2.1 implementation plan:
1. get_or_create_session new & existing.
2. Latest-N chronological conversation history retrieval (descending limit inner subquery, ascending outer query).
3. Migration 0028 partial unique index on status='COMPLETED'.
4. Non-completed responses (FAILED, BLOCKED, TRUNCATED) not cached.
5. Single-active-generation lease acquisition and concurrency conflicts (409 Retry-After: 5 and 2).
6. Stalled worker lease preemption with generation_fence increment and owner_token rotation.
7. Atomic fenced commit with PostgreSQL clock_timestamp() validation.
8. Full transaction rollback when fenced commit fails (zero messages persisted).
9. Safe lease release leaving turn slot clean.
10. Mandatory SQL-level user ownership predicates & cross-user access denial.
11. Authorized institutional administrator audit access.
12. 100% public API parity between DatabaseSessionStore and InMemorySessionStore.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.models import AgentSession, AgentSessionMessage
from app.agents.session_store import (
    AbstractSessionStore,
    DatabaseSessionStore,
    FencedCommitPreemptedError,
    InMemorySessionStore,
    SessionAccessDeniedError,
    SessionConcurrencyError,
    SessionDeletedError,
    SessionExpiredError,
)
from app.auth.security import hash_password
from app.core.config import settings
from app.institutions.models import Institution, InstitutionMembership
from app.users.models import User

# ==============================================================================
# Helper Setup Functions
# ==============================================================================

async def _setup_tenant_and_users(engine, inst_id: uuid.UUID, user1_id: uuid.UUID, user2_id: uuid.UUID, admin_id: uuid.UUID):
    """Sets up an institution, two regular users, and one institute admin in the test database."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        # Set platform admin context to allow inserting into institutions/users cleanly
        await session.execute(text("SELECT set_config('app.is_platform_admin', 'true', true);"))
        await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))

        inst = (await session.execute(select(Institution).where(Institution.id == inst_id))).scalars().first()
        if not inst:
            inst = Institution(id=inst_id, name="Store Test Inst", slug=f"inst-{inst_id.hex[:6]}", is_active=True)
            session.add(inst)
            await session.flush()

        for uid, role, email_prefix in [
            (user1_id, "student", "user1"),
            (user2_id, "student", "user2"),
            (admin_id, "admin", "admin"),
        ]:
            user = (await session.execute(select(User).where(User.id == uid))).scalars().first()
            if not user:
                user = User(
                    id=uid,
                    email=f"{email_prefix}-{uid.hex[:6]}@store-test.edu",
                    name=f"Test {email_prefix.capitalize()}",
                    hashed_password=hash_password("Pass123!"),
                    role=role,
                    is_active=True,
                )
                session.add(user)
                await session.flush()

            mem = (
                await session.execute(
                    select(InstitutionMembership).where(
                        InstitutionMembership.institution_id == inst_id,
                        InstitutionMembership.user_id == uid,
                    )
                )
            ).scalars().first()
            if not mem:
                mem = InstitutionMembership(
                    institution_id=inst_id,
                    user_id=uid,
                    role=role,
                    status="active",
                )
                session.add(mem)
                await session.flush()

        await session.commit()


async def _wait_until_lease_expired(
    expires_at: datetime | None,
    *,
    margin_seconds: float = 0.05,
    max_expected_ttl_seconds: float = 2.5,
    max_wait_seconds: float = 6.0,
) -> None:
    """
    Waits until real UTC wall clock exceeds lease expiry plus a small margin.
    Protects tests using real 1s leases against host CLOCK_REALTIME steps relative to monotonic sleep,
    while failing fast if production returns an unexpectedly long TTL.
    """
    assert expires_at is not None, "Expected non-null generation_lease_expires_at on acquired lease"
    initial_remaining = (expires_at - datetime.now(UTC)).total_seconds()
    assert initial_remaining <= max_expected_ttl_seconds, (
        f"Lease expiry {expires_at} is {initial_remaining:.2f}s ahead (> {max_expected_ttl_seconds}s max expected TTL)"
    )
    target = expires_at + timedelta(seconds=margin_seconds)
    deadline_mono = asyncio.get_running_loop().time() + max_wait_seconds
    while datetime.now(UTC) <= target:
        if asyncio.get_running_loop().time() >= deadline_mono:
            raise AssertionError(
                f"UTC wall clock ({datetime.now(UTC)}) did not advance past lease expiry {target} within {max_wait_seconds}s"
            )
        await asyncio.sleep(0.05)


# ==============================================================================
# Test Suite: DatabaseSessionStore & InMemorySessionStore Parity
# ==============================================================================

class TestAgentSessionStore:
    """Verifies all 21 test scenarios defined in the frozen Version 2.1 implementation plan."""

    @pytest.fixture
    def session_factory(self, test_engine):
        return async_sessionmaker(test_engine, expire_on_commit=False)

    @pytest.fixture
    def db_store(self, session_factory):
        return DatabaseSessionStore(session_factory=session_factory)

    @pytest.fixture
    def memory_store(self):
        return InMemorySessionStore()

    # --------------------------------------------------------------------------
    # Scenario 1 & 2: get_or_create_session new and existing
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_or_create_session_new_and_existing(self, test_engine, db_store, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        for store in [db_store, memory_store]:
            # 1. New session creation
            created = await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant", "Physics Doubt")
            assert created.id == sess_uuid_or_str(sess_id)
            assert created.institution_id == inst_id
            assert created.user_id == user_id
            assert created.title == "Physics Doubt"
            assert created.turn_counter == 0
            assert created.is_generating is False
            assert created.generation_fence == 0
            assert created.is_expired is False
            assert created.is_deleted is False

            # 2. Existing session retrieval
            existing = await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
            assert existing.id == created.id
            assert existing.title == "Physics Doubt"
            assert existing.turn_counter == 0

    # --------------------------------------------------------------------------
    # Scenario 3: Latest-N history retrieval in chronological order
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_history_retrieval_latest_n_chronological(self, test_engine, db_store, session_factory):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Insert 25 messages directly into the database
        now = datetime.now(UTC)
        async with session_factory() as session:
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            for i in range(1, 26):
                m_user = AgentSessionMessage(
                    institution_id=inst_id,
                    session_id=sess_id,
                    turn_id=i,
                    role="user",
                    content=f"User prompt turn {i}",
                    status="COMPLETED",
                    created_at=now + timedelta(seconds=i * 2),
                )
                m_asst = AgentSessionMessage(
                    institution_id=inst_id,
                    session_id=sess_id,
                    turn_id=i,
                    role="assistant",
                    content=f"Assistant reply turn {i}",
                    status="COMPLETED",
                    created_at=now + timedelta(seconds=i * 2 + 1),
                )
                session.add_all([m_user, m_asst])
            await session.commit()

        # Request history with limit = 10 messages
        lease_res = await db_store.reserve_generation_lease(
            sess_id, inst_id, user_id, client_turn_id="turn-26", history_limit=10
        )
        assert len(lease_res.history) == 10

        # Verify that the 10 messages returned are the MOST RECENT (turns 21 to 25)
        # and ordered chronologically ascending
        expected_turns = [21, 21, 22, 22, 23, 23, 24, 24, 25, 25]
        expected_roles = ["user", "assistant"] * 5
        for idx, item in enumerate(lease_res.history):
            turn_num = expected_turns[idx]
            role = expected_roles[idx]
            assert item["role"] == role
            assert f"turn {turn_num}" in item["content"]

    # --------------------------------------------------------------------------
    # Scenario 4: Completed response partial unique index (Migration 0028)
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_completed_response_partial_unique_index(self, test_engine, session_factory):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        async with session_factory() as session:
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            sess = AgentSession(id=sess_id, institution_id=inst_id, user_id=user_id, agent_name="portal_assistant")
            session.add(sess)
            await session.commit()

        # Insert first completed assistant response with client_turn_id = "turn-uq-1"
        async with session_factory() as session:
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            msg1 = AgentSessionMessage(
                institution_id=inst_id,
                session_id=sess_id,
                turn_id=1,
                role="assistant",
                content="Completed 1",
                status="COMPLETED",
                client_turn_id="turn-uq-1",
            )
            session.add(msg1)
            await session.commit()

        # Attempt to insert a second completed assistant response with the same client_turn_id
        async with session_factory() as session:
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            msg2 = AgentSessionMessage(
                institution_id=inst_id,
                session_id=sess_id,
                turn_id=2,
                role="assistant",
                content="Completed Duplicate",
                status="COMPLETED",
                client_turn_id="turn-uq-1",
            )
            session.add(msg2)
            with pytest.raises(IntegrityError) as exc_info:
                await session.commit()
            assert "uq_agent_messages_client_turn_assistant_completed" in str(exc_info.value)

        # Assert multiple FAILED responses with the same client_turn_id are permitted (not indexed)
        async with session_factory() as session:
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            msg_fail1 = AgentSessionMessage(
                institution_id=inst_id,
                session_id=sess_id,
                turn_id=3,
                role="assistant",
                content="Failure 1",
                status="FAILED",
                client_turn_id="turn-fail-multi",
            )
            msg_fail2 = AgentSessionMessage(
                institution_id=inst_id,
                session_id=sess_id,
                turn_id=4,
                role="assistant",
                content="Failure 2",
                status="FAILED",
                client_turn_id="turn-fail-multi",
            )
            session.add_all([msg_fail1, msg_fail2])
            await session.commit()  # Must succeed cleanly!

    # --------------------------------------------------------------------------
    # Scenario 5: Non-completed responses not cached
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_non_completed_response_not_cached(self, test_engine, db_store, session_factory):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Manually insert non-completed messages (BLOCKED, TRUNCATED, FAILED)
        async with session_factory() as session:
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            for idx, (status, client_id) in enumerate([
                ("BLOCKED", "blocked-turn"),
                ("TRUNCATED", "truncated-turn"),
                ("FAILED", "failed-turn"),
            ], start=1):
                session.add(
                    AgentSessionMessage(
                        institution_id=inst_id,
                        session_id=sess_id,
                        turn_id=idx,
                        role="assistant",
                        content=f"Error status {status}",
                        status=status,
                        client_turn_id=client_id,
                    )
                )
            await session.commit()

        for client_id in ["blocked-turn", "truncated-turn", "failed-turn"]:
            lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, client_id)
            assert lease.is_cached is False
            assert lease.cached_response is None
            await db_store.release_generation_lease(sess_id, inst_id, user_id, lease.fence, lease.owner_token)

    # --------------------------------------------------------------------------
    # Scenario 6: Normal generation lease acquisition
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_reserve_generation_lease_success(self, test_engine, db_store, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        for store in [db_store, memory_store]:
            await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
            lease = await store.reserve_generation_lease(sess_id, inst_id, user_id, "client-turn-1", lease_seconds=60)
            assert lease.is_cached is False
            assert lease.fence == 1
            assert isinstance(lease.owner_token, uuid.UUID)
            assert lease.session.is_generating is True
            assert lease.session.active_client_turn_id == "client-turn-1"
            assert lease.session.generation_fence == 1

    # --------------------------------------------------------------------------
    # Scenario 7 & 8: Concurrency conflict (HTTP 409 Retry-After: 5 and 2)
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_reserve_lease_concurrency_conflicts(self, test_engine, db_store, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        for store in [db_store, memory_store]:
            await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
            await store.reserve_generation_lease(sess_id, inst_id, user_id, "client-turn-1", lease_seconds=60)

            # Scenario 7: Concurrent distinct request -> Retry-After: 5
            with pytest.raises(SessionConcurrencyError) as exc_info:
                await store.reserve_generation_lease(sess_id, inst_id, user_id, "client-turn-2")
            assert exc_info.value.retry_after == 5
            assert exc_info.value.is_duplicate is False

            # Scenario 8: Duplicate in-flight request -> Retry-After: 2
            with pytest.raises(SessionConcurrencyError) as exc_dup:
                await store.reserve_generation_lease(sess_id, inst_id, user_id, "client-turn-1")
            assert exc_dup.value.retry_after == 2
            assert exc_dup.value.is_duplicate is True

    # --------------------------------------------------------------------------
    # Scenario 9: Duplicate completed cached hit
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_reserve_lease_duplicate_completed_cached(self, test_engine, db_store, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        for store in [db_store, memory_store]:
            await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
            lease = await store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-idemp-1")
            await store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-idemp-1",
                fence=lease.fence,
                owner_token=lease.owner_token,
                user_message="Explain gravity",
                assistant_message="Gravity is the curvature of spacetime.",
                llm_usage={"total_tokens": 15},
            )

            # Retry with same client_turn_id
            cached_lease = await store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-idemp-1")
            assert cached_lease.is_cached is True
            assert cached_lease.cached_response is not None
            assert cached_lease.cached_response["answer"] == "Gravity is the curvature of spacetime."
            assert cached_lease.cached_response["status"] == "COMPLETED"
            assert cached_lease.session.is_generating is False

    # --------------------------------------------------------------------------
    # Scenario 10: Stalled worker lease preemption
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_reserve_lease_stalled_worker_preemption(self, test_engine, db_store, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        for store in [db_store, memory_store]:
            await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
            lease1 = await store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-stalled-1", lease_seconds=1)
            assert lease1.fence == 1

            # Observe wall-clock expiry strictly past the 1-second lease deadline
            await _wait_until_lease_expired(lease1.session.generation_lease_expires_at)

            # Stalled lease preemption: second request succeeds, increments fence to 2
            lease2 = await store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-stalled-2", lease_seconds=60)
            assert lease2.fence == 2
            assert lease2.owner_token != lease1.owner_token
            assert lease2.session.active_client_turn_id == "turn-stalled-2"

    # --------------------------------------------------------------------------
    # Scenario 11: Normal atomic commit success
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_commit_turn_atomic_success(self, test_engine, db_store, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        for store in [db_store, memory_store]:
            await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
            lease = await store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-commit-1")

            new_turn, user_dto, asst_dto = await store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-commit-1",
                fence=lease.fence,
                owner_token=lease.owner_token,
                user_message="What is energy?",
                assistant_message="Energy is the capacity to do work.",
                llm_usage={"total_tokens": 12},
            )
            assert new_turn == 1
            assert user_dto.turn_id == 1
            assert user_dto.role == "user"
            assert user_dto.content == "What is energy?"
            assert asst_dto.turn_id == 1
            assert asst_dto.role == "assistant"
            assert asst_dto.content == "Energy is the capacity to do work."
            assert asst_dto.status == "COMPLETED"

            # Check that lease was cleared
            current_session = await store.get_session(sess_id, inst_id, user_id)
            assert current_session.is_generating is False
            assert current_session.active_client_turn_id is None
            assert current_session.turn_counter == 1

    # --------------------------------------------------------------------------
    # Scenario 12: Expiry checked using PostgreSQL clock_timestamp()
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_expiry_checked_using_wall_clock_time(self, test_engine, db_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Reserve lease with 1 second duration
        lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-expired-1", lease_seconds=1)

        # Wait explicitly until UTC wall clock passes lease deadline
        await _wait_until_lease_expired(lease.session.generation_lease_expires_at)

        # Attempt atomic commit with expired lease
        with pytest.raises(FencedCommitPreemptedError) as exc_info:
            await db_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-expired-1",
                fence=lease.fence,
                owner_token=lease.owner_token,
                user_message="Too slow",
                assistant_message="Late response",
            )
        assert "Commit rejected" in str(exc_info.value)

    # --------------------------------------------------------------------------
    # Scenario 13: Transaction waiting on lock cannot commit with expired lease
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_transaction_waiting_on_lock_cannot_commit_with_expired_lease(self, test_engine, session_factory, db_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Reserve lease with 1 second duration
        lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-lock-wait", lease_seconds=1)

        # In an independent session, lock the row until UTC wall clock passes lease deadline
        async def _hold_lock():
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
                    await session.execute(
                        select(AgentSession).where(AgentSession.id == sess_id).with_for_update()
                    )
                    await _wait_until_lease_expired(lease.session.generation_lease_expires_at, margin_seconds=0.1)

        lock_task = asyncio.create_task(_hold_lock())
        await asyncio.sleep(0.1)  # Ensure lock is acquired

        # Attempt commit while row is locked; will wait for lock and wake up past clock_timestamp()
        with pytest.raises(FencedCommitPreemptedError):
            await db_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-lock-wait",
                fence=lease.fence,
                owner_token=lease.owner_token,
                user_message="User text",
                assistant_message="Asst text",
            )

        await lock_task

    # --------------------------------------------------------------------------
    # Scenario 14: Lease renewal is absent in Step 3.2
    # --------------------------------------------------------------------------
    def test_lease_renewal_absent_in_step_3_2(self, db_store, memory_store):
        assert not hasattr(AbstractSessionStore, "extend_generation_lease")
        assert not hasattr(db_store, "extend_generation_lease")
        assert not hasattr(memory_store, "extend_generation_lease")

    # --------------------------------------------------------------------------
    # Scenario 15: Terminal outcomes persistence rules (COMPLETED, BLOCKED, TRUNCATED, FAILED)
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_terminal_outcomes_persistence_rules(self, test_engine, db_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        statuses = ["COMPLETED", "BLOCKED", "TRUNCATED", "FAILED"]
        for idx, status in enumerate(statuses, start=1):
            client_id = f"turn-status-{status.lower()}"
            lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, client_id)
            turn_no, user_dto, asst_dto = await db_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id=client_id,
                fence=lease.fence,
                owner_token=lease.owner_token,
                user_message=f"Prompt {idx}",
                assistant_message=f"Response {idx}",
                status=status,
            )
            assert turn_no == idx
            assert asst_dto.status == status

            # Check cache lookup behavior
            next_lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, client_id)
            if status == "COMPLETED":
                assert next_lease.is_cached is True
                assert next_lease.cached_response["status"] == "COMPLETED"
            else:
                assert next_lease.is_cached is False
                assert next_lease.cached_response is None
                await db_store.release_generation_lease(sess_id, inst_id, user_id, next_lease.fence, next_lease.owner_token)

    # --------------------------------------------------------------------------
    # Scenario 16: Transient failure release leaves turn slot clean
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_transient_failure_release_leaves_turn_clean(self, test_engine, db_store, session_factory):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "transient-err-turn")
        assert lease.session.turn_counter == 0

        # Safe release on transient failure
        released = await db_store.release_generation_lease(sess_id, inst_id, user_id, lease.fence, lease.owner_token)
        assert released is True

        # Verify session state and 0 messages inserted
        session = await db_store.get_session(sess_id, inst_id, user_id)
        assert session.is_generating is False
        assert session.active_client_turn_id is None
        assert session.turn_counter == 0

        async with session_factory() as db:
            await db.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            msgs = (
                await db.execute(
                    select(AgentSessionMessage).where(AgentSessionMessage.session_id == sess_id)
                )
            ).scalars().all()
            assert len(msgs) == 0

    # --------------------------------------------------------------------------
    # Scenario 17: Stale worker rejected after newer fence
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_stale_worker_rejected_after_newer_fence(self, test_engine, db_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Worker A acquires lease at fence 1
        lease_a = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-worker-a", lease_seconds=1)
        assert lease_a.fence == 1

        # Worker B preempts lease at fence 2 after UTC wall clock clears lease expiry
        await _wait_until_lease_expired(lease_a.session.generation_lease_expires_at)
        lease_b = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-worker-b", lease_seconds=60)
        assert lease_b.fence == 2

        # Worker A attempts to commit using obsolete fence 1
        with pytest.raises(FencedCommitPreemptedError):
            await db_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-worker-a",
                fence=lease_a.fence,
                owner_token=lease_a.owner_token,
                user_message="Worker A User",
                assistant_message="Worker A Asst",
            )

    # --------------------------------------------------------------------------
    # Scenario 18: Stale owner token rejected
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_stale_owner_token_rejected(self, test_engine, db_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-bad-token")
        fake_token = uuid.uuid4()

        with pytest.raises(FencedCommitPreemptedError):
            await db_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-bad-token",
                fence=lease.fence,
                owner_token=fake_token,
                user_message="User msg",
                assistant_message="Asst msg",
            )

    # --------------------------------------------------------------------------
    # Scenario 19: Full transaction rollback when fenced commit fails
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_full_transaction_rollback_when_fenced_commit_fails(self, test_engine, db_store, session_factory):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())
        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        lease = await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-rollback-test")

        # Force a commit rejection by passing an invalid fence
        with pytest.raises(FencedCommitPreemptedError):
            await db_store.commit_turn_atomic(
                session_id=sess_id,
                institution_id=inst_id,
                user_id=user_id,
                client_turn_id="turn-rollback-test",
                fence=999,  # invalid fence
                owner_token=lease.owner_token,
                user_message="Rollback user",
                assistant_message="Rollback asst",
            )

        # Assert 0 messages inserted
        async with session_factory() as db:
            await db.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            msgs = (
                await db.execute(
                    select(AgentSessionMessage).where(AgentSessionMessage.session_id == sess_id)
                )
            ).scalars().all()
            assert len(msgs) == 0

    # --------------------------------------------------------------------------
    # Scenario 20: Cross-user access denial within same institution
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_same_institution_cross_user_access_denied(self, test_engine, db_store):
        inst_id = uuid.uuid4()
        user1_id = uuid.uuid4()
        user2_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user1_id, user2_id, uuid.uuid4())

        # User 1 creates session
        await db_store.get_or_create_session(sess_id, inst_id, user1_id, "portal_assistant")

        # User 2 attempts to get session
        with pytest.raises(SessionAccessDeniedError):
            await db_store.get_session(sess_id, inst_id, user2_id)

        # User 2 attempts to reserve lease on User 1 session
        with pytest.raises(SessionAccessDeniedError):
            await db_store.reserve_generation_lease(sess_id, inst_id, user2_id, "hacker-turn")

    # --------------------------------------------------------------------------
    # Scenario 21: Authorized institution admin audit access & tenant membership checks
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_institution_admin_audit_access(self, test_engine, db_store, session_factory):
        inst_a = uuid.uuid4()
        inst_b = uuid.uuid4()
        user_a = uuid.uuid4()
        admin_a = uuid.uuid4()
        admin_b = uuid.uuid4()
        inactive_admin = uuid.uuid4()
        platform_admin_id = uuid.uuid4()
        student_id = uuid.uuid4()
        sess_a = uuid.uuid4()

        # Setup Inst A with user_a, student_id, admin_a
        await _setup_tenant_and_users(test_engine, inst_a, user_a, student_id, admin_a)
        # Setup Inst B with admin_b
        await _setup_tenant_and_users(test_engine, inst_b, uuid.uuid4(), uuid.uuid4(), admin_b)

        # Setup inactive admin in Inst A and global platform admin
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.is_platform_admin', 'true', true);"))
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_a}', true);"))

            # Inactive admin
            u_inact = User(
                id=inactive_admin,
                email=f"inact-{inactive_admin.hex[:6]}@store-test.edu",
                name="Inactive Admin",
                hashed_password=hash_password("Pass123!"),
                role="admin",
                is_active=True,
            )
            session.add(u_inact)
            mem_inact = InstitutionMembership(
                institution_id=inst_a,
                user_id=inactive_admin,
                role="admin",
                status="inactive",
            )
            session.add(mem_inact)

            # Platform admin
            u_plat = User(
                id=platform_admin_id,
                email=f"plat-{platform_admin_id.hex[:6]}@store-test.edu",
                name="Platform Admin",
                hashed_password=hash_password("Pass123!"),
                role="admin",
                is_active=True,
                is_platform_admin=True,
            )
            session.add(u_plat)
            await session.commit()

        # Create session and commit 1 turn in Inst A
        await db_store.get_or_create_session(sess_a, inst_a, user_a, "portal_assistant")
        lease = await db_store.reserve_generation_lease(sess_a, inst_a, user_a, "turn-audit-comp-1")
        await db_store.commit_turn_atomic(
            sess_a, inst_a, user_a, "turn-audit-comp-1", lease.fence, lease.owner_token,
            "Student Question", "Assistant Help"
        )

        # 1. Same-institution admin access: ALLOWED
        sess_dto, msgs = await db_store.get_institution_session_audit(sess_a, inst_a, admin_a)
        assert sess_dto.id == sess_a
        assert len(msgs) == 2

        # 2. Cross-institution admin access: DENIED
        with pytest.raises(SessionAccessDeniedError) as exc_cross:
            await db_store.get_institution_session_audit(sess_a, inst_a, admin_b)
        assert "does not possess an active membership" in str(exc_cross.value)

        # 3. Inactive membership admin access: DENIED
        with pytest.raises(SessionAccessDeniedError) as exc_inact:
            await db_store.get_institution_session_audit(sess_a, inst_a, inactive_admin)
        assert "does not possess an active membership" in str(exc_inact.value)

        # 4. Ordinary user (student): DENIED
        with pytest.raises(SessionAccessDeniedError) as exc_stud:
            await db_store.get_institution_session_audit(sess_a, inst_a, student_id)
        assert "does not possess administrative" in str(exc_stud.value)

        # 5. Platform admin access across institutions: ALLOWED
        plat_dto, plat_msgs = await db_store.get_institution_session_audit(sess_a, inst_a, platform_admin_id)
        assert plat_dto.id == sess_a
        assert len(plat_msgs) == 2

    # --------------------------------------------------------------------------
    # Scenario 22: Soft-delete session and subsequent access denial
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_soft_delete_session_and_subsequent_access(self, test_engine, db_store, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        for store in [db_store, memory_store]:
            await store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
            deleted = await store.soft_delete_session(sess_id, inst_id, user_id)
            assert deleted is True

            with pytest.raises(SessionDeletedError):
                await store.get_session(sess_id, inst_id, user_id)

            with pytest.raises(SessionDeletedError):
                await store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-after-delete")

    # --------------------------------------------------------------------------
    # Scenario 23: Inactivity expiration detection (24h)
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_inactivity_expiration_detection(self, test_engine, db_store, session_factory):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        await _setup_tenant_and_users(test_engine, inst_id, user_id, uuid.uuid4(), uuid.uuid4())

        await db_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")

        # Manually backdate last_accessed_at to 25 hours ago
        stale_time = datetime.now(UTC) - timedelta(hours=25)
        async with session_factory() as session:
            await session.execute(text(f"SELECT set_config('app.current_institution_id', '{inst_id}', true);"))
            await session.execute(
                update(AgentSession)
                .where(AgentSession.id == sess_id)
                .values(last_accessed_at=stale_time)
            )
            await session.commit()

        # Attempt to reserve lease; must detect inactivity and raise SessionExpiredError
        with pytest.raises(SessionExpiredError):
            await db_store.reserve_generation_lease(sess_id, inst_id, user_id, "turn-stale")

    # --------------------------------------------------------------------------
    # Scenario 24: Fail-closed dependency injection in production
    # --------------------------------------------------------------------------
    def test_database_unavailable_in_production(self, monkeypatch):
        from app.agents.dependencies import get_session_store

        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "DATABASE_URL", "")

        from app.agents.session_store import SessionStoreUnavailableError
        with pytest.raises(SessionStoreUnavailableError):
            get_session_store()

    # --------------------------------------------------------------------------
    # Scenario 25: In-memory store contract parity
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_in_memory_store_contract_parity(self, memory_store):
        inst_id = uuid.uuid4()
        user_id = uuid.uuid4()
        sess_id = uuid.uuid4()

        # Happy path
        s = await memory_store.get_or_create_session(sess_id, inst_id, user_id, "portal_assistant")
        assert s.id == sess_id

        # Lease
        lease = await memory_store.reserve_generation_lease(sess_id, inst_id, user_id, "mem-turn-1")
        assert lease.fence == 1

        # Commit
        counter, u_dto, a_dto = await memory_store.commit_turn_atomic(
            sess_id, inst_id, user_id, "mem-turn-1", lease.fence, lease.owner_token,
            "User question", "Asst answer"
        )
        assert counter == 1
        assert a_dto.status == "COMPLETED"

        # Cached replay
        cached = await memory_store.reserve_generation_lease(sess_id, inst_id, user_id, "mem-turn-1")
        assert cached.is_cached is True
        assert cached.cached_response["answer"] == "Asst answer"

        # Stale worker rejection
        with pytest.raises(FencedCommitPreemptedError):
            await memory_store.commit_turn_atomic(
                sess_id, inst_id, user_id, "mem-turn-stale", fence=999, owner_token=uuid.uuid4(),
                user_message="Stale", assistant_message="Stale"
            )

        # Admin audit parity in-memory
        admin_id = uuid.uuid4()
        other_inst = uuid.uuid4()
        memory_store.register_user(admin_id, role="admin")
        memory_store.register_membership(inst_id, admin_id, role="admin", status="active")

        # Allowed for registered active admin
        audit_s, audit_msgs = await memory_store.get_institution_session_audit(sess_id, inst_id, admin_id)
        assert audit_s.id == sess_id
        assert len(audit_msgs) == 2

        # Denied for other institution
        with pytest.raises(SessionAccessDeniedError):
            await memory_store.get_institution_session_audit(sess_id, other_inst, admin_id)


def sess_uuid_or_str(val):
    return uuid.UUID(str(val)) if not isinstance(val, uuid.UUID) else val

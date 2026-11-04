"""
tests/conftest.py

Shared pytest fixtures: a dedicated test Postgres database (created fresh
and torn down per test session) and an httpx AsyncClient wired to your
FastAPI app, plus helper fixtures that sign up + log in throwaway test
users for each role.

*** THINGS YOU MUST ADJUST BEFORE THIS RUNS — clearly marked below ***
I don't have visibility into your actual signup endpoint's exact field
names (I only confirmed login is POST /auth/login with {email, password}),
so the signup payload below is my best guess at a typical FastAPI signup
shape and is marked for you to correct. Everything else (test DB setup,
client fixtures, role fixtures) should work as-is.

Setup:
    1. Create a separate test database in your existing Postgres container:
         docker exec -it <your_postgres_container> psql -U eduintel -c "CREATE DATABASE eduintel_test;"
    2. Set TEST_DATABASE_URL as an env var before running pytest, e.g.:
         export TEST_DATABASE_URL="postgresql+asyncpg://eduintel:<password>@localhost:5432/eduintel_test"
       (adjust user/password/port to match your actual docker-compose config —
       same credentials as your regular DATABASE_URL, just a different db name)
    3. pip install pytest pytest-asyncio httpx --break-system-packages
    4. Run: pytest tests/ -v
"""
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# --- ADJUST THIS IMPORT if your FastAPI app instance or Base live elsewhere ---
from app.auth.security import create_access_token, hash_password
from app.core.database import Base, get_db
from app.main import app
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://eduintel:eduintel_dev@localhost:5432/eduintel_test",
)


@pytest_asyncio.fixture
async def test_engine():
    """
    Function-scoped on purpose (not session-scoped). pytest-asyncio gives
    each test function its own event loop runner by default, but asyncpg
    connections are bound to the loop that created them. A session-scoped
    engine's pooled connections get created on the SESSION runner's loop,
    then get used from each TEST's own (different) runner/loop — which is
    exactly what produced the "another operation in progress" errors: the
    connection object was being driven from a loop it wasn't created on.
    Creating a fresh engine (and NullPool, so nothing is pooled/reused
    across checkouts either) inside each test's own loop avoids this
    entirely. Cost: schema is created/dropped per test instead of once —
    negligible for a suite this size.
    """
    engine = create_async_engine(TEST_DATABASE_URL, future=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
def prevent_live_smtp_during_tests(monkeypatch):
    """
    Globally intercepts all SMTP calls so tests never connect to live Gmail SMTP servers
    or dispatch real emails.
    """
    from unittest.mock import MagicMock
    mock_send = MagicMock(return_value={"status": "sent"})
    monkeypatch.setattr("app.auth.service.send_email_direct", mock_send)
    monkeypatch.setattr("app.reports.parent_report_agent.send_email_direct", mock_send)
    yield mock_send


@pytest_asyncio.fixture(autouse=True)
async def reset_app_engine_pool():
    """
    Teardown fixture that disposes pooled connections on the global application engine
    between pytest test cases. In test suites where test cases use function-scoped event
    loops, pooled asyncpg connections from a completed test's event loop will fail if
    reused in a subsequent test's new loop ('got Future attached to a different loop').
    Disposing the engine ensures each test case creates fresh connections in its active loop.
    """
    yield
    from app.core.database import engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_engine):
    """
    An httpx AsyncClient that hits your FastAPI app in-process (no real
    server needed), with get_db overridden to hand out a FRESH session per
    request from a session factory.

    Important: each httpx call through ASGITransport runs the app in its
    own asyncio task. Sharing a single AsyncSession/connection across
    multiple requests (the original version of this fixture did) makes
    asyncpg choke with "another operation is in progress", because the
    same underlying connection gets driven from more than one task
    context. A fresh session per request (this version) avoids that —
    it's also just what a real get_db() typically does.
    """
    TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _provision_user(test_engine, role: str) -> str:
    """
    Creates a throwaway test user and profile directly in the test database
    and returns a valid access token. Does NOT use public signup since
    public signup is disabled in SEC-02.
    """
    unique = uuid.uuid4().hex[:8]
    email = f"test-{role}-{unique}@example.com"
    password = "TestPassword123!"

    TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSessionLocal() as session:
        from sqlalchemy import select

        from app.institutions.models import Institution, InstitutionMembership
        inst = (await session.execute(select(Institution))).scalars().first()
        if not inst:
            inst = Institution(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                name="Default Test Institution",
                slug="test-inst",
                is_active=True,
            )
            session.add(inst)
            await session.flush()

        user = User(
            email=email,
            name=f"Test {role.capitalize()}",
            hashed_password=hash_password(password),
            role=role,
            is_active=True,
            is_platform_admin=False,
        )
        session.add(user)
        await session.flush()

        session.add(
            InstitutionMembership(
                id=uuid.uuid4(),
                institution_id=inst.id,
                user_id=user.id,
                role=role,
                status="active",
            )
        )

        if role == "student":
            session.add(StudentProfile(institution_id=inst.id, user_id=user.id, grade="10", section="A"))
        elif role == "teacher":
            session.add(
                TeacherProfile(
                    institution_id=inst.id, user_id=user.id, department="Science", subjects="Physics"
                )
            )
        elif role == "admin":
            session.add(
                AdminProfile(institution_id=inst.id, user_id=user.id, designation="Test Administrator")
            )

        await session.commit()
        return create_access_token({"sub": str(user.id), "role": role})


@pytest_asyncio.fixture
async def admin_token(test_engine) -> str:
    return await _provision_user(test_engine, "admin")


@pytest_asyncio.fixture
async def teacher_token(test_engine) -> str:
    return await _provision_user(test_engine, "teacher")


@pytest_asyncio.fixture
async def student_token(test_engine) -> str:
    return await _provision_user(test_engine, "student")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
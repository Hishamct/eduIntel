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
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

# --- ADJUST THIS IMPORT if your FastAPI app instance or Base live elsewhere ---
from app.main import app
from app.core.database import Base, get_db

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://eduintel:eduintel@localhost:5432/eduintel_test",
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


async def _signup_and_login(client: AsyncClient, role: str) -> str:
    """
    Creates a throwaway test user with the given role and returns a bearer
    token for them.

    *** ADJUST THE SIGNUP PAYLOAD BELOW to match your real POST /auth/signup
    field names *** — I don't know your exact schema (e.g. whether it's
    `full_name` or `name`, whether role is a plain string or an enum value,
    whether signup itself takes a role at all vs. assigning "student" by
    default and requiring an admin to promote teachers/admins). Login is
    confirmed as POST /auth/login with {email, password}.
    """
    unique = uuid.uuid4().hex[:8]
    email = f"test-{role}-{unique}@example.com"
    password = "TestPassword123!"

    signup_payload = {
        "email": email,
        "password": password,
        "full_name": f"Test {role.capitalize()}",
        "role": role,
    }
    signup_resp = await client.post("/auth/signup", json=signup_payload)
    assert signup_resp.status_code in (200, 201), (
        f"Signup failed for role={role}: {signup_resp.status_code} {signup_resp.text}\n"
        f"--> Fix the signup_payload shape in tests/conftest.py to match your "
        f"real POST /auth/signup schema."
    )

    login_resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200, f"Login failed for {email}: {login_resp.text}"
    token = login_resp.json()["access_token"]  # ADJUST if your login response key differs
    return token


@pytest_asyncio.fixture
async def admin_token(client) -> str:
    return await _signup_and_login(client, "admin")


@pytest_asyncio.fixture
async def teacher_token(client) -> str:
    return await _signup_and_login(client, "teacher")


@pytest_asyncio.fixture
async def student_token(client) -> str:
    return await _signup_and_login(client, "student")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
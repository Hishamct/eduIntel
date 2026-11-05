"""
backend/tests/conftest.py

Phase 04 Test Harness:
1. Strict multi-factor test database safety verification (host, port, DB name allowlist, params).
2. Realistic PostgreSQL 16 schema powered by dynamic Alembic upgrade verification.
3. Live Row-Level Security assertion (17 FORCE RLS tables, 68 split policies, unprivileged eduintel_app).
4. Savepoint transaction isolation (join_transaction_mode="create_savepoint") eliminating cross-test state leaks.
5. Resilient teardown session state cleanup traps (RESET ROLE, RESET ALL, GUC nullification).
"""

import os
import re
import socket
import uuid

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

# ==============================================================================
# Multi-Tier Loopback-Aware Network Guard
# ==============================================================================
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "", None}

_orig_getaddrinfo = socket.getaddrinfo
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex


def is_loopback_host(host: str | None) -> bool:
    """Determines whether a host or address is an authorized local loopback endpoint."""
    if not host or host in LOOPBACK_HOSTS:
        return True
    if isinstance(host, str) and (host.startswith("127.") or host.startswith("::1")):
        return True
    return False


def guarded_getaddrinfo(host, port, *args, **kwargs):
    """Intercepts outbound DNS lookups; fails closed if host is non-loopback."""
    if host is not None and not is_loopback_host(host):
        raise RuntimeError(
            f"CRITICAL: Unmocked external network call detected during test execution! "
            f"Blocked outbound DNS lookup for '{host}:{port}'"
        )
    return _orig_getaddrinfo(host, port, *args, **kwargs)


def guarded_connect(self, address):
    """Intercepts socket.connect; fails closed if target host is non-loopback."""
    if isinstance(address, (str, bytes)):
        return _orig_connect(self, address)
    host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
    if not is_loopback_host(host):
        raise RuntimeError(
            f"CRITICAL: Unmocked external network call detected during test execution! "
            f"Blocked outbound socket connection to '{address}'"
        )
    return _orig_connect(self, address)


def guarded_connect_ex(self, address):
    """Intercepts socket.connect_ex; fails closed if target host is non-loopback."""
    if isinstance(address, (str, bytes)):
        return _orig_connect_ex(self, address)
    host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
    if not is_loopback_host(host):
        raise RuntimeError(
            f"CRITICAL: Unmocked external network call detected during test execution! "
            f"Blocked outbound socket connection to '{address}'"
        )
    return _orig_connect_ex(self, address)


# Activate socket-level loopback guard globally for test session
socket.getaddrinfo = guarded_getaddrinfo
socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex

# Establish testing mode environment variables early before application models bind
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("EDUINTEL_TEST_MODE", "true")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://eduintel_app:eduintel_dev@localhost:5432/eduintel_test",
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from app.auth.security import create_access_token, hash_password
from app.core.database import get_db
from app.institutions.models import Institution, InstitutionMembership
from app.main import app
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]


def assert_safe_test_database(url_str: str) -> None:
    """
    Enforces fail-closed multi-factor verification before any test interacts with a database:
    1. Both ENVIRONMENT='testing' AND EDUINTEL_TEST_MODE='true' must be present simultaneously.
    2. Host must be strictly 'localhost' or '127.0.0.1'.
    3. Port must be 5432 (standard PostgreSQL port) or omitted.
    4. Query parameters are strictly rejected to prevent connection injection.
    5. Database name must match the strict regex ^eduintel_test(_[a-zA-Z0-9_-]+)?$.
    6. Protected database names ('eduintel', 'postgres', 'production', 'staging') are forbidden.
    """
    env = os.getenv("ENVIRONMENT")
    test_mode = os.getenv("EDUINTEL_TEST_MODE")
    if env != "testing" or test_mode != "true":
        raise RuntimeError(
            f"FATAL: Tests may only run when ENVIRONMENT='testing' AND EDUINTEL_TEST_MODE='true'. "
            f"Current state: ENVIRONMENT='{env}', EDUINTEL_TEST_MODE='{test_mode}'"
        )

    url = make_url(url_str)

    # 1. Host restriction
    if url.host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError(
            f"FATAL: Test database host '{url.host}' is not localhost/127.0.0.1. "
            "Refusing to execute tests against a remote or non-loopback host."
        )

    # 2. Port restriction
    if url.port is not None and url.port != 5432:
        raise RuntimeError(
            f"FATAL: Non-standard database port '{url.port}'. Tests strictly require port 5432."
        )

    # 3. Reject unexpected query parameters
    if url.query:
        raise RuntimeError(
            f"FATAL: Test database URL contains unexpected query parameters: {url.query}"
        )

    # 4. Prohibit protected database names
    db_name = url.database or ""
    if db_name.lower() in {"eduintel", "postgres", "production", "staging"}:
        raise RuntimeError(
            f"FATAL: Test target '{db_name}' is a protected production/development database name. Aborting."
        )

    # 5. Strict allowlist regex check
    if not re.match(r"^eduintel_test(_[a-zA-Z0-9_-]+)?$", db_name):
        raise RuntimeError(
            f"FATAL: Test database name '{db_name}' violates allowlist regex '^eduintel_test(_[a-zA-Z0-9_-]+)?$'."
        )


@pytest.fixture(scope="session", autouse=True)
def verify_and_prepare_test_database():
    """
    Session-level initialization:
    1. Validates test database safety invariants.
    2. Verifies Alembic schema is upgraded to 'head'.
    3. Dynamically asserts schema integrity: 22 tables, 17 FORCE RLS tables, split policies,
       and unprivileged status of the application role.
    """
    assert_safe_test_database(TEST_DATABASE_URL)

    import asyncio

    import alembic.config

    from alembic import command

    alembic_cfg = alembic.config.Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(alembic_cfg, "head")

    # Run dynamic schema verification queries
    url = make_url(TEST_DATABASE_URL)
    raw_url = f"postgresql://{url.username}:{url.password}@{url.host}:{url.port}/{url.database}"

    async def _verify_schema():
        conn = await asyncpg.connect(raw_url)
        try:
            # 1. Assert minimum table count
            tables = [r["tablename"] for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
            if len(tables) < 22:
                raise RuntimeError(f"Expected at least 22 tables in test DB, found {len(tables)}: {tables}")

            # 2. Assert RLS and FORCE RLS on tenant tables
            rls_tables = [
                r["relname"]
                for r in await conn.fetch("""
                    SELECT c.relname
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity = true AND c.relforcerowsecurity = true
                """)
            ]
            if len(rls_tables) != 17:
                raise RuntimeError(f"Expected 17 FORCE RLS tables, found {len(rls_tables)}: {rls_tables}")

            # 3. Assert split RLS policies from Migration 0025
            split_policies = await conn.fetch("""
                SELECT policyname FROM pg_policies
                WHERE schemaname = 'public' AND (
                    policyname LIKE '%_read_policy' OR
                    policyname LIKE '%_insert_policy' OR
                    policyname LIKE '%_update_policy' OR
                    policyname LIKE '%_delete_policy'
                )
            """)
            if len(split_policies) < 68:
                raise RuntimeError(f"Expected at least 68 split policies, found {len(split_policies)}")

            # 4. Assert eduintel_app is unprivileged
            app_role = await conn.fetchrow("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'eduintel_app'")
            if not app_role:
                raise RuntimeError("Unprivileged application role 'eduintel_app' does not exist in PostgreSQL")
            if app_role["rolsuper"] or app_role["rolbypassrls"]:
                raise RuntimeError("Role 'eduintel_app' must NOT have rolsuper or rolbypassrls privileges")
        finally:
            await conn.close()

    asyncio.run(_verify_schema())


@pytest_asyncio.fixture
async def test_engine():
    """Provides an AsyncEngine with NullPool bound to TEST_DATABASE_URL."""
    engine = create_async_engine(TEST_DATABASE_URL, future=True, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(test_engine):
    """
    Per-test connection fixture providing savepoint transaction isolation.
    Opens an outer transaction that is unconditionally rolled back at teardown,
    followed by a resilient multi-parameter reset trap.
    """
    conn = await test_engine.connect()
    trans = await conn.begin()
    try:
        yield conn
    finally:
        await trans.rollback()
        # Resilient state cleanup
        await conn.execute(text("RESET ROLE;"))
        await conn.execute(text("RESET ALL;"))
        await conn.execute(
            text(
                "DO $$ BEGIN "
                "PERFORM set_config('app.current_institution_id', '', false); "
                "PERFORM set_config('app.is_platform_admin', '', false); "
                "END $$;"
            )
        )
        await conn.close()


@pytest_asyncio.fixture
async def client(db_connection):
    """
    An httpx AsyncClient hitting the FastAPI app with get_db overridden to
    hand out a session bound to db_connection with savepoint isolation.
    """
    async def _override_get_db():
        session = AsyncSession(
            bind=db_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _provision_user(
    db_connection,
    role: str,
    is_platform_admin: bool = False,
    institution_id: uuid.UUID | None = None,
) -> str:
    """
    Provisions a throwaway test user and profile inside the active savepoint.
    Sets transaction-local tenant context so RLS permits profile creation.
    """
    unique = uuid.uuid4().hex[:8]
    email = f"test-{role}-{unique}@example.com"
    password = "TestPassword123!"

    session = AsyncSession(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    inst_id = institution_id or uuid.UUID("00000000-0000-0000-0000-000000000001")

    # Set institution context so RLS policies allow insertion
    await session.execute(
        text("SELECT set_config('app.current_institution_id', :id, true)"),
        {"id": str(inst_id)},
    )

    inst = (await session.execute(select(Institution).where(Institution.id == inst_id))).scalars().first()
    if not inst:
        inst = Institution(
            id=inst_id,
            name=f"Test Institution {inst_id.hex[:6]}",
            slug=f"test-inst-{inst_id.hex[:6]}",
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
        is_platform_admin=is_platform_admin,
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
    await session.close()
    return create_access_token({"sub": str(user.id), "role": role})


@pytest_asyncio.fixture
async def platform_admin_token(db_connection) -> str:
    return await _provision_user(db_connection, "admin", is_platform_admin=True)


@pytest_asyncio.fixture
async def admin_token(db_connection) -> str:
    return await _provision_user(db_connection, "admin")


@pytest_asyncio.fixture
async def teacher_token(db_connection) -> str:
    return await _provision_user(db_connection, "teacher")


@pytest_asyncio.fixture
async def student_token(db_connection) -> str:
    return await _provision_user(db_connection, "student")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def prevent_live_smtp_during_tests(monkeypatch):
    """Globally intercepts all SMTP calls to prevent external dispatch and records them in an in-memory sink."""
    from unittest.mock import MagicMock

    outbox = []

    def fake_send(to_email, subject, body, *args, **kwargs):
        msg = {
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "args": args,
            "kwargs": kwargs,
            "status": "sent",
        }
        outbox.append(msg)
        return {"status": "sent"}

    mock_send = MagicMock(side_effect=fake_send)
    mock_send.outbox = outbox
    monkeypatch.setattr("app.auth.service.send_email_direct", mock_send)
    monkeypatch.setattr("app.reports.parent_report_agent.send_email_direct", mock_send)
    yield mock_send


@pytest.fixture(autouse=True)
def mock_gemini_llm(monkeypatch):
    """Centralized deterministic mock for Google Gemini LLM API calls."""
    from unittest.mock import MagicMock

    from app.core import llm_client

    mock_resp = MagicMock()
    mock_resp.text = "Mocked AI response for testing."
    mock_resp.usage_metadata = MagicMock(
        prompt_token_count=15, candidates_token_count=25
    )
    mock_resp.candidates = [MagicMock(content=MagicMock(parts=[]))]

    mock_generate = MagicMock(return_value=mock_resp)
    monkeypatch.setattr(
        llm_client._gemini_client.models, "generate_content", mock_generate
    )
    yield mock_generate


@pytest.fixture(autouse=True)
def mock_groq_llm(monkeypatch):
    """Centralized deterministic mock for Groq LLM API fallback calls."""
    from unittest.mock import MagicMock

    from app.core import llm_client

    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(message=MagicMock(content="Mocked Groq fallback response."))
    ]
    mock_resp.usage = MagicMock(prompt_tokens=15, completion_tokens=25)

    mock_create = MagicMock(return_value=mock_resp)
    monkeypatch.setattr(
        llm_client._groq_client.chat.completions, "create", mock_create
    )
    yield mock_create


@pytest.fixture(autouse=True)
def mock_chroma_embeddings(monkeypatch):
    """Centralized deterministic mock for ChromaDB vector embeddings (GeminiEmbeddingFunction)."""
    from app.rag import client

    def mock_embed(self, input):
        return [[0.05] * 768 for _ in input]

    monkeypatch.setattr(client.GeminiEmbeddingFunction, "__call__", mock_embed)
    yield mock_embed


@pytest_asyncio.fixture(autouse=True)
async def reset_app_engine_pool():
    """Teardown fixture that disposes pooled connections on global engine."""
    yield
    from app.core.database import engine

    await engine.dispose()

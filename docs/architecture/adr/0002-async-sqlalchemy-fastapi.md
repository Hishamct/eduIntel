# ADR 0002: AsyncIO with FastAPI and SQLAlchemy 2.0 (asyncpg)

- **Status**: Accepted
- **Deciders**: EduIntel Engineering Team
- **Date**: 2026-10-16

---

## Context and Problem Statement

EduIntel's backend is built using FastAPI on Python 3.12. The application handles high-concurrency workloads: concurrent student doubt submissions, real-time teacher grading, administrative analytics, and streaming/polling AI responses.

Relational databases accessed via traditional synchronous ORMs (such as SQLAlchemy 1.x with `psycopg2`) block worker threads during I/O wait times. In high-concurrency environments, thread pool exhaustion occurs quickly, drastically limiting throughput unless large worker fleets are deployed.

We needed an asynchronous database persistence strategy compatible with modern Python typing, FastAPI dependency injection, and Alembic migrations.

---

## Decision Outcome

We chose **SQLAlchemy 2.0 AsyncIO** coupled with the high-performance **`asyncpg`** PostgreSQL driver.

### Architectural Rules:
- The async engine is instantiated in [`backend/app/core/database.py`](file:///home/dell/projects/eduIntel/backend/app/core/database.py) using `create_async_engine(settings.DATABASE_URL, ...)` with explicit async pooling parameters.
- **Connection Pool Architecture (`AsyncAdaptedQueuePool`)**: Rather than unmanaged default pooling, the engine utilizes SQLAlchemy's native async pool configured with:
  - `pool_size = settings.DB_POOL_SIZE` (Default: 10 connections per worker process)
  - `max_overflow = settings.DB_MAX_OVERFLOW` (Default: 5 surge connections)
  - `pool_timeout = settings.DB_POOL_TIMEOUT` (Default: 30 seconds wait before raising `TimeoutError`)
  - `pool_recycle = settings.DB_POOL_RECYCLE` (Default: 1800 seconds / 30 minutes to recycle stale sockets)
  - `pool_pre_ping = settings.DB_POOL_PRE_PING` (Default: True, transparently pings `SELECT 1` to discard severed sockets)
  - `echo = settings.DB_ECHO` (Default: False, prevents PII and student records leakage to stdout)
- **Pool Sizing Mathematics**: Sized to prevent PostgreSQL connection storms (`sorry, too many clients already`):
  $$P_{\text{pool}} = \left\lfloor \frac{C_{\text{max}} - C_{\text{reserve}}}{W_{\text{workers}}} \right\rfloor = \left\lfloor \frac{100 - 20}{4} \right\rfloor = 20\text{ max per worker}$$
- **Sanitized Active Health Probe**: System liveness probe in `check_database_health()` executes active `SELECT 1;` round-trips, measures execution latency in milliseconds, captures pool checkout metrics, and masks internal exception traces.
- Database sessions are injected into FastAPI route handlers via an async generator dependency (`get_db()`) yielding `AsyncSession`.
- All database queries use SQLAlchemy 2.0 explicit executable syntax (`select()`, `execute()`, `scalars()`) with `await`.
- Alembic migrations use `env.py` configured with `asyncio.run(run_migrations_online())` to safely execute DDL.

---

## Consequences

### Positive Consequences
- **High Concurrency & Non-Blocking I/O**: The server handles thousands of concurrent connections with a minimal memory footprint, as coroutines yield execution during database round-trips.
- **Modern Python Typing**: SQLAlchemy 2.0 provides first-class `Mapped` and `mapped_column` type annotations that integrate cleanly with Pydantic v2 schemas.
- **Connection Pooling Resilience**: `AsyncAdaptedQueuePool` strictly caps client connections, absorbs sudden surges via `max_overflow`, recovers seamlessly from severed sockets via `pre_ping`, and fails closed with actionable metrics.

### Negative Consequences
- **Developer Complexity**: Async Python requires discipline: accidental synchronous blocking calls (e.g. standard file I/O or synchronous libraries) inside async route handlers can stall the event loop.
- **Lazy Loading Pitfalls**: SQLAlchemy relationship lazy-loading is unavailable in async mode without explicit `selectinload` or `joinedload`, requiring intentional query construction to avoid `MissingGreenlet` errors.

---

## Alternatives Considered

- **Synchronous SQLAlchemy (psycopg2)**: Rejected due to thread blocking and scalability bottlenecks under concurrent AI/portal load.
- **Tortoise ORM / Piccolo**: Rejected due to a smaller community ecosystem, less mature migration tooling compared to Alembic, and lack of enterprise-grade typing.


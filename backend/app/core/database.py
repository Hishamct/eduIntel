import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def check_database_health() -> dict[str, Any]:
    """Fast liveness and readiness probe for container readiness and /health."""
    start = time.monotonic()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        pool = engine.pool
        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "pool": {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            },
        }
    except Exception as exc:
        logger.error("Database health check failed: %s", exc, exc_info=True)
        pool = getattr(engine, "pool", None)
        return {
            "status": "unhealthy",
            "error": "Database connectivity check failed",
            "pool": {
                "size": pool.size() if pool and hasattr(pool, "size") else None,
                "checked_in": pool.checkedin() if pool and hasattr(pool, "checkedin") else None,
                "checked_out": pool.checkedout() if pool and hasattr(pool, "checkedout") else None,
                "overflow": pool.overflow() if pool and hasattr(pool, "overflow") else None,
            },
        }

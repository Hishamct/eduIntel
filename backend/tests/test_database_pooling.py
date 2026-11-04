"""Tests for async connection pooling configuration, health checks, and resilience (ADR-0002)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.pool import AsyncAdaptedQueuePool, QueuePool

from app.core.config import settings
from app.core.database import check_database_health, engine


class TestDatabasePoolConfiguration:
    """Verifies that database pooling parameters are properly bound and deployment-aware."""

    def test_pool_settings_defaults(self):
        """Settings must reflect conservative production defaults (ADR-0002)."""
        assert settings.DB_POOL_SIZE == 10
        assert settings.DB_MAX_OVERFLOW == 5
        assert settings.DB_POOL_TIMEOUT == 30
        assert settings.DB_POOL_RECYCLE == 1800
        assert settings.DB_POOL_PRE_PING is True
        assert settings.DB_ECHO is False

    def test_engine_pool_initialization(self):
        """Engine pool must instantiate AsyncAdaptedQueuePool with matching configuration."""
        pool = engine.pool
        assert isinstance(pool, AsyncAdaptedQueuePool)
        assert pool.size() == 10
        assert pool._max_overflow == 5
        assert pool._timeout == 30
        assert pool._recycle == 1800
        assert pool._pre_ping is True


class TestDatabaseHealthCheck:
    """Verifies the active liveness and latency health probe utility."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Mocked successful connection returns healthy status, latency, and pool stats."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn
        mock_engine.pool.size.return_value = 10
        mock_engine.pool.checkedin.return_value = 8
        mock_engine.pool.checkedout.return_value = 2
        mock_engine.pool.overflow.return_value = 0

        with patch("app.core.database.engine", mock_engine):
            health = await check_database_health()
            assert health["status"] == "healthy"
            assert isinstance(health["latency_ms"], float)
            assert "pool" in health
            assert health["pool"]["size"] == 10
            assert health["pool"]["checked_in"] == 8
            assert health["pool"]["checked_out"] == 2
            assert health["pool"]["overflow"] == 0

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """Failed connection returns sanitized error string without raising unhandled exceptions."""
        mock_fail_engine = MagicMock()
        mock_fail_engine.connect.side_effect = Exception("Database connection refused: internal socket error")
        mock_fail_engine.pool.size.return_value = 10
        mock_fail_engine.pool.checkedin.return_value = 0
        mock_fail_engine.pool.checkedout.return_value = 0
        mock_fail_engine.pool.overflow.return_value = 0

        with patch("app.core.database.engine", mock_fail_engine):
            health = await check_database_health()
            assert health["status"] == "unhealthy"
            assert health["error"] == "Database connectivity check failed"
            # Verify internal raw exception details are NOT exposed to caller
            assert "internal socket error" not in health["error"]
            assert "pool" in health


class TestPoolSaturationAndRecovery:
    """Validates pool behavior under high concurrency, timeout queueing, and recovery."""

    def test_queue_pool_saturation_and_timeout(self):
        """Saturating pool_size + max_overflow queues requests and times out cleanly."""
        mock_dbapi_conn = MagicMock()

        def creator():
            return mock_dbapi_conn

        # Test pool with size=2, overflow=1, timeout=0.1s
        pool = QueuePool(creator, pool_size=2, max_overflow=1, timeout=0.1)

        # 1. Acquire baseline connections up to pool_size (2)
        c1 = pool.connect()
        c2 = pool.connect()
        assert pool.checkedout() == 2
        assert pool.overflow() == 0

        # 2. Acquire burst connection into overflow (1)
        c3 = pool.connect()
        assert pool.checkedout() == 3
        assert pool.overflow() == 1

        # 3. 4th connection exceeds pool_size + max_overflow (3 slots total) -> TimeoutError
        with pytest.raises(SATimeoutError):
            pool.connect()

        # 4. Release connections -> pool recovers
        c1.close()
        c2.close()
        c3.close()
        assert pool.checkedout() == 0
        assert pool.checkedin() == 2
        assert pool.overflow() == 0

        # 5. Subsequent request succeeds immediately
        c4 = pool.connect()
        assert pool.checkedout() == 1
        c4.close()

    @pytest.mark.asyncio
    async def test_pool_pre_ping_enabled_on_engine(self):
        """Verifies that the engine has pool_pre_ping configured on its pool."""
        assert engine.pool._pre_ping is True

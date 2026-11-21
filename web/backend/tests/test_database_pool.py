"""
Tests unitarios para BlockingThreadedConnectionPool y get_db (V113).
Verifica que el pool bloquee en lugar de fallar inmediatamente bajo ráfagas concurrentes.
"""
from unittest.mock import MagicMock, patch
import pytest
from psycopg2 import pool as pg_pool
from app.database import BlockingThreadedConnectionPool, get_db, get_pool_status


@pytest.mark.unit
def test_blocking_pool_initialization():
    with patch("psycopg2.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        pool = BlockingThreadedConnectionPool(minconn=1, maxconn=3, timeout=2.0, dsn="fake")
        assert pool.minconn == 1
        assert pool.maxconn == 3
        assert pool._timeout == 2.0
        assert pool._semaphore._value == 3


@pytest.mark.unit
def test_blocking_pool_exhaustion_timeout():
    """Si se alcanza maxconn y expira el timeout, lanza PoolError con mensaje claro."""
    with patch("psycopg2.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        pool = BlockingThreadedConnectionPool(minconn=1, maxconn=1, timeout=0.05, dsn="fake")
        
        conn1 = pool.getconn()
        assert conn1 is not None

        with pytest.raises(pg_pool.PoolError) as excinfo:
            pool.getconn()
        assert "timeout waiting for connection" in str(excinfo.value)

        pool.putconn(conn1)
        assert pool._semaphore._value == 1


@pytest.mark.unit
def test_blocking_pool_putconn_releases_semaphore():
    """Al liberar una conexión, el slot queda disponible para el siguiente getconn."""
    with patch("psycopg2.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        pool = BlockingThreadedConnectionPool(minconn=1, maxconn=2, timeout=1.0, dsn="fake")
        
        c1 = pool.getconn()
        c2 = pool.getconn()
        assert pool._semaphore._value == 0

        pool.putconn(c1)
        assert pool._semaphore._value == 1

        c3 = pool.getconn()
        assert pool._semaphore._value == 0

        pool.putconn(c2)
        pool.putconn(c3)
        assert pool._semaphore._value == 2


@pytest.mark.unit
def test_get_pool_status():
    with patch("psycopg2.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        with patch("app.database._connection_pool", None):
            assert get_pool_status()["status"] == "uninitialized"

        pool = BlockingThreadedConnectionPool(minconn=1, maxconn=5, timeout=1.0, dsn="fake")
        with patch("app.database._connection_pool", pool):
            status = get_pool_status()
            assert status["status"] == "active"
            assert status["minconn"] == 1
            assert status["maxconn"] == 5
            assert status["used"] == 0
            assert status["available_slots"] == 5

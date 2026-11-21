"""
Gestión de conexiones a PostgreSQL usando pool de psycopg2.
Provee funciones para obtener y liberar conexiones del pool.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

from app.config import settings

logger = logging.getLogger(__name__)


class BlockingThreadedConnectionPool(pg_pool.ThreadedConnectionPool):
    """Pool de conexiones thread-safe con cola de espera (Semaphore) y timeout.

    A diferencia del ThreadedConnectionPool básico de psycopg2 (que lanza
    PoolError('connection pool exhausted') inmediatamente cuando maxconn está
    ocupado en ese instante), este pool bloquea de forma segura hasta `timeout`
    segundos esperando que otra petición libere una conexión.

    Esto absorbe los picos de peticiones concurrentes (p. ej., cuando el
    Dashboard de React dispara 15+ consultas simultáneas con Promise.all)
    sin fallar con error 500.
    """

    def __init__(self, minconn: int, maxconn: int, *args, timeout: float = 10.0, **kwargs):
        self._timeout = timeout
        self._semaphore = threading.Semaphore(maxconn)
        super().__init__(minconn, maxconn, *args, **kwargs)

    def getconn(self, key=None, timeout: float | None = None):
        wait_time = self._timeout if timeout is None else timeout
        acquired = self._semaphore.acquire(timeout=wait_time)
        if not acquired:
            raise pg_pool.PoolError(
                f"connection pool exhausted: timeout waiting for connection ({wait_time}s)"
            )
        try:
            return super().getconn(key)
        except Exception:
            self._semaphore.release()
            raise

    def putconn(self, conn, key=None, close=False):
        try:
            super().putconn(conn, key, close)
        finally:
            self._semaphore.release()


# Pool de conexiones: configurable vía settings
_connection_pool: BlockingThreadedConnectionPool | None = None


def init_db_pool() -> None:
    """Inicializa el pool de conexiones al arrancar la aplicación.

    V113: Utiliza BlockingThreadedConnectionPool con tamaño y timeout configurables
    desde settings (DB_POOL_MIN_CONN, DB_POOL_MAX_CONN, DB_POOL_TIMEOUT).
    Valores por defecto robustos: minconn=4, maxconn=35, timeout=10s.
    Evita que ráfagas simultáneas del frontend o tareas background agoten el pool.
    """
    global _connection_pool
    minconn = getattr(settings, "db_pool_min_conn", 4)
    maxconn = getattr(settings, "db_pool_max_conn", 35)
    timeout = getattr(settings, "db_pool_timeout", 10.0)

    _connection_pool = BlockingThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        timeout=timeout,
        dsn=settings.database_url,
        connect_timeout=5,
    )


def close_db_pool() -> None:
    """Cierra todas las conexiones del pool al apagar la aplicación."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None


@contextmanager
def get_db() -> Generator:
    """
    Context manager que entrega una conexión del pool y la devuelve al terminar.
    Hace rollback automático si ocurre un error.
    Fija la zona horaria a Lima/Perú para que ::date se interprete correctamente.
    Descarta conexiones rotas o cerradas para no contaminar el pool.
    """
    if _connection_pool is None:
        raise RuntimeError("El pool de base de datos no está inicializado")

    conn = _connection_pool.getconn()
    is_broken = False
    try:
        # Si la conexión vino cerrada o rota del pool, descartar y pedir una nueva
        if getattr(conn, "closed", 0) != 0:
            _connection_pool.putconn(conn, close=True)
            conn = _connection_pool.getconn()

        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'America/Lima'")
        yield conn
        conn.commit()
    except Exception:
        if getattr(conn, "closed", 0) == 0:
            try:
                conn.rollback()
            except Exception:
                is_broken = True
        else:
            is_broken = True
        raise
    finally:
        try:
            if is_broken or getattr(conn, "closed", 0) != 0:
                _connection_pool.putconn(conn, close=True)
            else:
                _connection_pool.putconn(conn)
        except Exception as exc:
            logger.warning("Error devolviendo conexión al pool: %s", exc)


def check_db_connection() -> bool:
    """Verifica que la conexión a la base de datos esté activa."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def get_pool_status() -> dict:
    """Retorna métricas del pool de conexiones para monitoreo y diagnóstico."""
    if not _connection_pool:
        return {"status": "uninitialized"}
    used = len(getattr(_connection_pool, "_used", {}))
    max_c = _connection_pool.maxconn
    sem_val = getattr(_connection_pool, "_semaphore", None)
    return {
        "status": "active",
        "minconn": _connection_pool.minconn,
        "maxconn": max_c,
        "used": used,
        "available_slots": sem_val._value if sem_val is not None else (max_c - used),
    }


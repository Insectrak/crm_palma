"""Checkpoint de polling por (provider, account_id).

Alimenta al poller de TikTok (y cualquier futuro proveedor sin webhook).
La tabla `crm.integrations_checkpoint` guarda:
  - last_run_at        — cuándo se intentó por última vez
  - last_success_at    — última corrida exitosa (cursor de "traer desde aquí")
  - last_error         — mensaje del último error si lo hubo
  - consecutive_errors — para backoff en el scheduler
  - items_last_run     — items traídos en la última corrida

Responsabilidad única: leer y escribir esas filas. Nada de HTTP ni
lógica de proveedor.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)


def get_checkpoint(provider: str, account_id: str) -> Optional[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT provider, account_id, last_run_at, last_success_at,
                       last_error, consecutive_errors, items_last_run, updated_at
                FROM crm.integrations_checkpoint
                WHERE provider = %s AND account_id = %s
                """,
                (provider.strip().lower(), account_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def mark_run_start(provider: str, account_id: str) -> None:
    """Marca el inicio de una corrida — para que rins paralelas no pisen."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crm.integrations_checkpoint
                    (provider, account_id, last_run_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                ON CONFLICT (provider, account_id) DO UPDATE SET
                    last_run_at = NOW(),
                    updated_at  = NOW()
                """,
                (provider.strip().lower(), account_id),
            )
        conn.commit()


def mark_run_success(
    provider: str,
    account_id: str,
    items: int,
    cursor_at: Optional[datetime] = None,
) -> None:
    """Cierra la corrida con éxito: resetea consecutive_errors y
    avanza last_success_at al timestamp del último item procesado
    (fallback: NOW)."""
    cur_time = cursor_at or datetime.utcnow()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.integrations_checkpoint
                   SET last_success_at    = %s,
                       last_error         = NULL,
                       consecutive_errors = 0,
                       items_last_run     = %s,
                       updated_at         = NOW()
                 WHERE provider = %s AND account_id = %s
                """,
                (cur_time, items, provider.strip().lower(), account_id),
            )
        conn.commit()


def reset_checkpoint(provider: str, account_id: str) -> bool:
    """Resetea last_success_at a NULL — usado por backfill admin.

    El próximo poll automático caerá al lookback default. No borra la fila
    para preservar el historial de errores e items_last_run.

    Devuelve True si la fila existía y se reseteó, False si no había nada.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.integrations_checkpoint
                   SET last_success_at    = NULL,
                       last_error         = NULL,
                       consecutive_errors = 0,
                       updated_at         = NOW()
                 WHERE provider = %s AND account_id = %s
                """,
                (provider.strip().lower(), account_id),
            )
            updated = cur.rowcount
        conn.commit()
    return updated > 0


def mark_run_error(provider: str, account_id: str, error: str) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.integrations_checkpoint
                   SET last_error         = %s,
                       consecutive_errors = consecutive_errors + 1,
                       updated_at         = NOW()
                 WHERE provider = %s AND account_id = %s
                """,
                (str(error)[:500], provider.strip().lower(), account_id),
            )
        conn.commit()

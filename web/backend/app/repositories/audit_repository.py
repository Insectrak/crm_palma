"""
Repositorio de auditoria de acceso a leads.

Encapsula la escritura en `crm.audit_lead_access`. Todas las funciones son
idempotentes y tolerantes a fallos: si la tabla no existe (migracion pendiente)
o la inserción falla, NO rompen la request principal — el audit es una capa
secundaria que nunca debe degradar la UX.

Schema: ver `database/migrations/V020_audit_lead_access.sql`.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.database import get_db

logger = logging.getLogger(__name__)


# Acciones canonicas — deben coincidir con los comentarios del DDL.
ACTION_LIST = "list"
ACTION_EXPORT = "export"
ACTION_DETAIL = "detail"
ACTION_COPY_ATTEMPT = "copy_attempt"


def _insert(
    *,
    user_id: str,
    action: str,
    lead_count: Optional[int],
    filters: Optional[dict[str, Any]],
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> None:
    """Insert raw con manejo defensivo de errores.

    Si algo falla (tabla inexistente, conexion caida, lo que sea) se registra
    un warning y se retorna silenciosamente. El llamador no debe envolver esto
    en un try/except — esta funcion ya es fail-safe.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm.audit_lead_access
                        (user_id, action, lead_count, filters, ip_address, user_agent)
                    VALUES (%s::uuid, %s, %s, %s::jsonb, %s::inet, %s)
                    """,
                    (
                        user_id,
                        action,
                        lead_count,
                        json.dumps(filters) if filters is not None else None,
                        ip_address,
                        user_agent,
                    ),
                )
    except Exception as exc:  # noqa: BLE001 — audit no debe romper la request
        logger.warning(
            "audit_lead_access INSERT failed (action=%s, user=%s): %s",
            action, user_id, exc,
        )


def log_list(
    *,
    user_id: str,
    lead_count: int,
    filters: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Listado paginado de leads (GET /api/leads)."""
    _insert(
        user_id=user_id,
        action=ACTION_LIST,
        lead_count=lead_count,
        filters=filters,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def log_export(
    *,
    user_id: str,
    lead_count: int,
    filters: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Descarga Excel de leads (GET /api/leads/exportar)."""
    _insert(
        user_id=user_id,
        action=ACTION_EXPORT,
        lead_count=lead_count,
        filters=filters,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def log_detail(
    *,
    user_id: str,
    lead_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Vista de ficha individual (GET /api/leads/{id})."""
    _insert(
        user_id=user_id,
        action=ACTION_DETAIL,
        lead_count=1,
        filters={"lead_id": lead_id},
        ip_address=ip_address,
        user_agent=user_agent,
    )


def log_copy_attempt(
    *,
    user_id: str,
    page: str,
    action_type: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Intento bloqueado de copiar desde el frontend.

    `page`       — 'leads' | 'asignacion' | ...
    `action_type` — 'copy' | 'cut' | 'contextmenu'
    """
    _insert(
        user_id=user_id,
        action=ACTION_COPY_ATTEMPT,
        lead_count=None,
        filters={"page": page, "action": action_type},
        ip_address=ip_address,
        user_agent=user_agent,
    )


def purge_older_than(days: int = 90) -> int:
    """Elimina registros mas antiguos que N dias. Retorna cantidad borrada.

    Pensado para ser llamado desde un cron nocturno (ej: `cron_cleanup.py` o
    un job en n8n). No se ejecuta automaticamente — la politica de retencion
    la dispara el operador del sistema.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM crm.audit_lead_access
                    WHERE created_at < NOW() - (%s || ' days')::interval
                    """,
                    (days,),
                )
                return cur.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_lead_access purge failed: %s", exc)
        return 0

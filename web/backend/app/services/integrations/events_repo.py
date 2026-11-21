"""Log de eventos de integraciones — observabilidad.

Se escribe en cada paso relevante del ciclo (webhook recibido, poll
ejecutado, lead creado/duplicado, error). La UI "Historial" consume esta
tabla y los incidentes se diagnostican sin tocar logs del servidor.

Reglas:
  - `raw_payload` guarda el evento ya normalizado. Los servicios de
    proveedor deben redactar (o simplemente no incluir) tokens/secretos
    antes de pasar el payload acá — este repo confía en su caller.
  - `external_id` es opcional pero recomendado: permite dedupe y correla
    eventos del mismo lead externo (webhook + creación + error).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from psycopg2.extras import Json, RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)

# Niveles operativos del evento — se validan en log_event.
_VALID_STATUS = {"ok", "error", "skipped"}
_VALID_TYPES = {
    "webhook_received",
    "webhook_verified",
    "poll_success",
    "poll_error",
    "lead_created",
    "lead_duplicated",
    "credential_updated",
    "credential_deleted",
    "error",
}


def log_event(
    provider: str,
    event_type: str,
    status: str = "ok",
    account_id: Optional[str] = None,
    external_id: Optional[str] = None,
    lead_id: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    raw_payload: Optional[Any] = None,
) -> int:
    """Inserta un evento. Devuelve el id generado. No levanta en caller."""
    if event_type not in _VALID_TYPES:
        # No bloqueamos el flujo — solo loggeamos y seguimos
        logger.warning("events_repo: event_type desconocido '%s'", event_type)
    if status not in _VALID_STATUS:
        logger.warning("events_repo: status desconocido '%s'", status)

    payload_json = None
    if raw_payload is not None:
        try:
            payload_json = Json(raw_payload)
        except (TypeError, ValueError):
            try:
                payload_json = Json(json.loads(json.dumps(raw_payload, default=str)))
            except Exception:
                payload_json = Json({"_unserializable": True})

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm.integrations_events
                        (provider, account_id, event_type, status, external_id,
                         lead_id, latency_ms, error_message, raw_payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        (provider or "").strip().lower(),
                        (account_id or None),
                        event_type,
                        status,
                        external_id,
                        lead_id,
                        latency_ms,
                        error_message,
                        payload_json,
                    ),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
        return int(new_id)
    except Exception as exc:  # noqa: BLE001
        # Observabilidad no debe tumbar el ingreso — solo log.
        logger.exception("events_repo: fallo al registrar evento: %s", exc)
        return 0


def list_events(
    provider: Optional[str] = None,
    account_id: Optional[str] = None,
    status: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Lista eventos paginados para la UI de historial.

    `limit` se clampea en [1, 500] para evitar consultas accidentales
    gigantes; la UI debe pedir páginas pequeñas.
    """
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    where: list[str] = []
    params: list = []
    if provider:
        where.append("provider = %s")
        params.append(provider.strip().lower())
    if account_id:
        where.append("account_id = %s")
        params.append(account_id)
    if status:
        where.append("status = %s")
        params.append(status)
    if event_type:
        where.append("event_type = %s")
        params.append(event_type)

    sql = """
        SELECT id, provider, account_id, event_type, status,
               external_id, lead_id, latency_ms, error_message, raw_payload,
               created_at
        FROM crm.integrations_events
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return rows


def count_events_24h(provider: str) -> dict:
    """Resumen (ok / error / skipped) de las últimas 24 horas por provider.
    Usado por la UI de Integraciones para el badge de estado en la card.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT status, COUNT(*)::int AS n
                FROM crm.integrations_events
                WHERE provider = %s
                  AND created_at > NOW() - INTERVAL '24 hours'
                GROUP BY status
                """,
                (provider.strip().lower(),),
            )
            rows = cur.fetchall()
    out = {"ok": 0, "error": 0, "skipped": 0}
    for r in rows:
        if r["status"] in out:
            out[r["status"]] = r["n"]
    return out

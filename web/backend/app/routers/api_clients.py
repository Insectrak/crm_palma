"""
api_clients.py — Router admin para gestionar API keys de proveedores.

Solo admin puede crear / regenerar / revocar / eliminar.
Supervisor puede VER stats (read-only).

CRITICO: la key plana se devuelve UNA SOLA VEZ al crear / regenerar.
Despues solo se guarda el hash SHA-256.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.database import get_db
from app.services import api_clients_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/api-clients", tags=["Admin / API Clients"])

# V062: router publico (cualquier rol autenticado) para el lookup de
# proveedores. Asesores y supervisores necesitan poder poblar el filtro
# "Proveedor" en /leads sin tener permisos sobre el CRUD admin.
public_router = APIRouter(prefix="/api/api-clients", tags=["API Clients (lookup)"])


# ─── Schemas ───────────────────────────────────────────────────────────────

class ApiClientCreate(BaseModel):
    nombre:                 str = Field(..., min_length=2, max_length=120)
    slug:                   str = Field(..., min_length=2, max_length=60)
    fuente_id:              int
    rate_limit_per_minute:  int = Field(60, ge=1, le=1000)
    ip_whitelist:           Optional[list[str]] = None
    contacto_email:         Optional[str] = Field(None, max_length=120)
    contacto_telefono:      Optional[str] = Field(None, max_length=40)
    notas:                  Optional[str] = None
    expires_at:             Optional[str] = None     # ISO 8601
    sede_id_default:        Optional[str] = None     # V065: sede asignada a leads de esta key


class ApiClientUpdate(BaseModel):
    nombre:                 Optional[str] = None
    fuente_id:              Optional[int] = None
    activo:                 Optional[bool] = None
    rate_limit_per_minute:  Optional[int] = Field(None, ge=1, le=1000)
    ip_whitelist:           Optional[list[str]] = None
    contacto_email:         Optional[str] = None
    contacto_telefono:      Optional[str] = None
    notas:                  Optional[str] = None
    expires_at:             Optional[str] = None
    # V058 — Outbound webhooks
    webhook_url:            Optional[str] = Field(None, max_length=500)
    webhook_events:         Optional[list[str]] = None
    webhook_enabled:        Optional[bool] = None
    # V059 — Privacy toggles
    webhook_include_asesor_contact:     Optional[bool] = None
    webhook_include_supervisor:         Optional[bool] = None
    webhook_include_supervisor_contact: Optional[bool] = None
    # V065 — Sede default
    sede_id_default:                    Optional[str] = None


# ─── Helpers ───────────────────────────────────────────────────────────────

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$")


def _validate_slug(slug: str) -> str:
    s = slug.strip().lower()
    if not SLUG_RE.match(s):
        raise HTTPException(400, "Slug invalido. Solo a-z, 0-9, '-', '_'. Min 2 chars.")
    return s


def _serialize_client(row: dict, include_secret: Optional[str] = None) -> dict:
    """Devuelve el client al frontend SIN el hash. Si se incluye secret
    (solo en create/regenerate), va separado."""
    out = {
        "id":                     str(row["id"]),
        "nombre":                 row["nombre"],
        "slug":                   row["slug"],
        "api_key_prefix":         row["api_key_prefix"],
        "fuente_id":              row["fuente_id"],
        "fuente_nombre":          row.get("fuente_nombre"),
        "activo":                 row["activo"],
        "rate_limit_per_minute":  row["rate_limit_per_minute"],
        "ip_whitelist":           row.get("ip_whitelist"),
        "contacto_email":         row.get("contacto_email"),
        "contacto_telefono":      row.get("contacto_telefono"),
        "notas":                  row.get("notas"),
        "total_leads":            row.get("total_leads", 0),
        "leads_duplicados":       row.get("leads_duplicados", 0),
        "leads_rechazados":       row.get("leads_rechazados", 0),
        "ultimo_lead_at":         row["ultimo_lead_at"].isoformat() if row.get("ultimo_lead_at") else None,
        "expires_at":             row["expires_at"].isoformat() if row.get("expires_at") else None,
        "revoked_at":             row["revoked_at"].isoformat() if row.get("revoked_at") else None,
        "created_at":             row["created_at"].isoformat() if row.get("created_at") else None,
        # V058 — Outbound webhooks
        "webhook_url":            row.get("webhook_url"),
        "webhook_events":         list(row.get("webhook_events") or []),
        "webhook_enabled":        bool(row.get("webhook_enabled")) if row.get("webhook_enabled") is not None else False,
        "has_webhook_secret":     bool(row.get("webhook_secret")),
        # V059 — Privacy toggles (defaults conservadores si la migracion aun no aplico)
        "webhook_include_asesor_contact":     bool(row["webhook_include_asesor_contact"]) if row.get("webhook_include_asesor_contact") is not None else True,
        "webhook_include_supervisor":         bool(row["webhook_include_supervisor"]) if row.get("webhook_include_supervisor") is not None else True,
        "webhook_include_supervisor_contact": bool(row["webhook_include_supervisor_contact"]) if row.get("webhook_include_supervisor_contact") is not None else False,
        # V065: sede default — se aplica a leads que entran por esta key
        # cuando el payload no trae 'sede' explicito.
        "sede_id_default": str(row["sede_id_default"]) if row.get("sede_id_default") else None,
    }
    if include_secret:
        out["api_key_plain"] = include_secret
    return out


# ─── CRUD ──────────────────────────────────────────────────────────────────

@router.get("")
def list_clients(_admin: TokenData = Depends(check_permission("integraciones.manage"))):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT c.*, f.nombre AS fuente_nombre
                FROM crm.api_clients c
                LEFT JOIN crm.fuentes f ON f.id = c.fuente_id
                ORDER BY c.activo DESC, c.created_at DESC
                """
            )
            rows = cur.fetchall()
    return [_serialize_client(r) for r in rows]


@router.post("", status_code=201)
def create_client(data: ApiClientCreate, admin: TokenData = Depends(check_permission("integraciones.manage"))):
    slug = _validate_slug(data.slug)
    key_full, key_prefix, key_hash = svc.generate_key()

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar slug unico
            cur.execute("SELECT 1 FROM crm.api_clients WHERE slug = %s", (slug,))
            if cur.fetchone():
                raise HTTPException(409, "Ya existe un proveedor con ese slug.")
            # Validar fuente
            cur.execute("SELECT id FROM crm.fuentes WHERE id = %s", (data.fuente_id,))
            if not cur.fetchone():
                raise HTTPException(400, "Fuente no encontrada.")

            cur.execute(
                """
                INSERT INTO crm.api_clients
                    (nombre, slug, api_key_hash, api_key_prefix, fuente_id,
                     rate_limit_per_minute, ip_whitelist,
                     contacto_email, contacto_telefono, notas, expires_at, created_by,
                     sede_id_default)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::uuid,
                        CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END)
                RETURNING *
                """,
                (
                    data.nombre.strip(), slug, key_hash, key_prefix, data.fuente_id,
                    data.rate_limit_per_minute, data.ip_whitelist,
                    data.contacto_email, data.contacto_telefono, data.notas,
                    data.expires_at, admin.user_id,
                    data.sede_id_default, data.sede_id_default,
                ),
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT nombre FROM crm.fuentes WHERE id = %s",
                (data.fuente_id,),
            )
            fuente = cur.fetchone()
            row["fuente_nombre"] = fuente["nombre"] if fuente else None
        conn.commit()

    logger.info("[api_clients] CREATED slug=%s prefix=%s by admin=%s", slug, key_prefix, admin.user_id)
    return _serialize_client(row, include_secret=key_full)


@router.patch("/{client_id}")
def update_client(client_id: str, data: ApiClientUpdate, admin: TokenData = Depends(check_permission("integraciones.manage"))):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar")

    # V058: validar eventos webhook contra la allowlist del servicio
    if "webhook_events" in fields:
        from app.services import webhook_service
        invalid = [e for e in fields["webhook_events"] if e not in webhook_service.ALL_EVENTS]
        if invalid:
            raise HTTPException(
                400,
                f"Eventos no soportados: {invalid}. Soportados: {sorted(webhook_service.ALL_EVENTS)}",
            )

    set_parts = []
    params: list = []
    for k, v in fields.items():
        if k == "expires_at":
            set_parts.append("expires_at = %s::timestamptz")
        elif k == "ip_whitelist":
            set_parts.append("ip_whitelist = %s")
        elif k == "webhook_events":
            set_parts.append("webhook_events = %s")
        elif k == "sede_id_default":
            # V065: cast a uuid; sede_id_default puede ser None para limpiar.
            set_parts.append("sede_id_default = CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END")
            params.append(v)  # se appendea dos veces
        else:
            set_parts.append(f"{k} = %s")
        params.append(v)
    params.append(client_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.api_clients SET {', '.join(set_parts)}, updated_at = NOW() "
                "WHERE id = %s::uuid RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "API client no encontrado")
            cur.execute(
                "SELECT nombre FROM crm.fuentes WHERE id = %s",
                (row["fuente_id"],),
            )
            fuente = cur.fetchone()
            row["fuente_nombre"] = fuente["nombre"] if fuente else None
        conn.commit()
    logger.info("[api_clients] UPDATED id=%s by admin=%s fields=%s", client_id, admin.user_id, list(fields.keys()))
    return _serialize_client(row)


@router.post("/{client_id}/regenerate")
def regenerate_key(client_id: str, admin: TokenData = Depends(check_permission("integraciones.manage"))):
    """Genera una key nueva, revoca la anterior. La key plana se devuelve UNA VEZ."""
    key_full, key_prefix, key_hash = svc.generate_key()
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE crm.api_clients
                SET api_key_hash   = %s,
                    api_key_prefix = %s,
                    revoked_at     = NULL,
                    updated_at     = NOW()
                WHERE id = %s::uuid
                RETURNING *
                """,
                (key_hash, key_prefix, client_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "API client no encontrado")
            cur.execute(
                "SELECT nombre FROM crm.fuentes WHERE id = %s",
                (row["fuente_id"],),
            )
            fuente = cur.fetchone()
            row["fuente_nombre"] = fuente["nombre"] if fuente else None
        conn.commit()
    logger.info("[api_clients] REGENERATED id=%s prefix=%s by admin=%s", client_id, key_prefix, admin.user_id)
    return _serialize_client(row, include_secret=key_full)


@router.post("/{client_id}/revoke")
def revoke_client(client_id: str, admin: TokenData = Depends(check_permission("integraciones.manage"))):
    """Soft revoke: marca revoked_at y desactiva. Mantiene historico de logs."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.api_clients
                SET activo = FALSE, revoked_at = NOW(), updated_at = NOW()
                WHERE id = %s::uuid
                RETURNING id
                """,
                (client_id,),
            )
            if not cur.fetchone():
                raise HTTPException(404, "API client no encontrado")
        conn.commit()
    logger.warning("[api_clients] REVOKED id=%s by admin=%s", client_id, admin.user_id)
    return {"ok": True}


@router.delete("/{client_id}")
def delete_client(client_id: str, admin: TokenData = Depends(check_permission("integraciones.manage"))):
    """Hard delete. Si tiene leads asociados, se prefiere /revoke para mantener trazabilidad."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM crm.leads WHERE api_client_id = %s::uuid", (client_id,))
            count = cur.fetchone()[0]
            if count > 0:
                raise HTTPException(
                    409,
                    f"No se puede eliminar: hay {count} leads asociados. Usar /revoke para mantener trazabilidad.",
                )
            cur.execute("DELETE FROM crm.api_clients WHERE id = %s::uuid RETURNING id", (client_id,))
            if not cur.fetchone():
                raise HTTPException(404, "API client no encontrado")
        conn.commit()
    logger.warning("[api_clients] DELETED id=%s by admin=%s", client_id, admin.user_id)
    return {"ok": True}


@router.post("/{client_id}/unlink-leads")
def unlink_leads(
    client_id: str,
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """V061: desvincula los leads asociados (api_client_id = NULL) para
    permitir el hard delete del proveedor despues. Es destructivo en el
    sentido de que se pierde la atribucion comercial al proveedor — pero
    los leads en si quedan intactos (asesor, estado, contactos, etc.).

    V062: antes de poner api_client_id = NULL se snapshotean slug+nombre
    en api_client_legacy_slug / api_client_legacy_nombre para no perder
    la trazabilidad historica. Asi reportes y filtros pueden seguir
    diciendo 'estos leads vinieron de Wedo' aunque el proveedor ya no
    exista en api_clients.

    Solo admin. Util para casos de testing / sandbox: 'cree el proveedor
    con leads de prueba y ahora quiero borrar todo limpio'.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Verificar que el client existe (para 404 antes que update)
            cur.execute(
                "SELECT nombre, slug FROM crm.api_clients WHERE id = %s::uuid",
                (client_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "API client no encontrado")
            client_name, client_slug = row[0], row[1]

            # V062: snapshot legacy + desvincular en bulk (atomico)
            cur.execute(
                """
                UPDATE crm.leads
                SET api_client_id            = NULL,
                    api_client_legacy_slug   = %s,
                    api_client_legacy_nombre = %s
                WHERE api_client_id = %s::uuid
                """,
                (client_slug, client_name, client_id),
            )
            unlinked = cur.rowcount
            conn.commit()

    logger.warning(
        "[api_clients] UNLINKED %d leads de client=%s (%s) by admin=%s",
        unlinked, client_id, client_name, admin.user_id,
    )
    return {"ok": True, "unlinked": unlinked, "client_name": client_name}


# ─── Stats + Logs ──────────────────────────────────────────────────────────

@router.get("/{client_id}/stats")
def get_stats(
    client_id: str,
    dias: int = Query(30, ge=1, le=365),
    _admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Metricas de los ultimos N dias para este proveedor."""
    desde = date.today() - timedelta(days=dias)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar existencia
            cur.execute(
                "SELECT id, nombre, total_leads, leads_duplicados, leads_rechazados "
                "FROM crm.api_clients WHERE id = %s::uuid",
                (client_id,),
            )
            cliente = cur.fetchone()
            if not cliente:
                raise HTTPException(404, "API client no encontrado")

            # Leads por dia
            cur.execute(
                """
                SELECT DATE(created_at) AS dia, COUNT(*)::int AS total
                FROM crm.leads
                WHERE api_client_id = %s::uuid AND DATE(created_at) >= %s
                GROUP BY DATE(created_at) ORDER BY dia
                """,
                (client_id, desde),
            )
            leads_por_dia = [dict(r) for r in cur.fetchall()]

            # Tasa de conversion: cuantos leads de este proveedor llegaron a Ganado
            cur.execute(
                """
                SELECT COUNT(*) FILTER (WHERE e.nombre = 'Ganado')::int AS ganados,
                       COUNT(*)::int AS total
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.api_client_id = %s::uuid AND DATE(l.created_at) >= %s
                """,
                (client_id, desde),
            )
            conv = cur.fetchone()
            tasa = round(conv["ganados"] * 100 / conv["total"], 1) if conv["total"] else 0

            # Stats agregados de logs (status codes)
            cur.execute(
                """
                SELECT status_code,
                       COUNT(*)::int AS total,
                       COUNT(*) FILTER (WHERE duplicated)::int AS duplicados
                FROM crm.api_client_logs
                WHERE api_client_id = %s::uuid AND created_at >= %s::date
                GROUP BY status_code ORDER BY status_code
                """,
                (client_id, desde),
            )
            por_status = [dict(r) for r in cur.fetchall()]

    return {
        "cliente": dict(cliente),
        "dias": dias,
        "leads_por_dia": leads_por_dia,
        "conversion": {"ganados": conv["ganados"], "total": conv["total"], "tasa_pct": tasa},
        "por_status": por_status,
    }


# ─── V058: Outbound webhooks ──────────────────────────────────────────────

@router.post("/{client_id}/webhook/regenerate-secret")
def regenerate_webhook_secret(
    client_id: str,
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Genera un secret nuevo (32 bytes hex = 64 chars). Lo devuelve UNA
    sola vez — no se puede recuperar despues. El proveedor lo usa para
    verificar la firma HMAC-SHA256 del payload en X-Crm-Signature."""
    import secrets as pysecrets
    new_secret = pysecrets.token_hex(32)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE crm.api_clients
                SET webhook_secret = %s, updated_at = NOW()
                WHERE id = %s::uuid
                RETURNING id
                """,
                (new_secret, client_id),
            )
            if not cur.fetchone():
                raise HTTPException(404, "API client no encontrado")
            conn.commit()
    logger.info("[api_clients.webhook] secret regenerado client=%s by admin=%s",
                client_id, admin.user_id)
    return {"webhook_secret": new_secret, "warning": "Guárdalo ahora — no se vuelve a mostrar."}


@router.get("/{client_id}/webhook/deliveries")
def list_webhook_deliveries(
    client_id: str,
    limit: int = Query(50, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status"),
    _admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Lista los ultimos N deliveries de webhooks para este cliente.
    Util para debugging: ver que eventos se enviaron, http_status,
    response_body del proveedor, intentos, tiempo de respuesta."""
    where = ["client_id = %s::uuid"]
    params: list = [client_id]
    if status_filter:
        where.append("status = %s")
        params.append(status_filter)
    where_sql = " AND ".join(where)
    params.append(limit)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    id, lead_id, event_type, status, attempt, max_attempts,
                    http_status, response_body, error_message,
                    next_retry_at::text AS next_retry_at,
                    last_attempt_at::text AS last_attempt_at,
                    delivered_at::text AS delivered_at,
                    duration_ms,
                    created_at::text AS created_at
                FROM crm.webhook_deliveries
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"deliveries": rows, "total": len(rows)}


@router.post("/{client_id}/webhook/test")
def send_test_webhook(
    client_id: str,
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Envia un evento sintetico al webhook del proveedor para verificar
    la conexion sin esperar a un lead real.

    UX paridad patrón estándar / apps externas: el admin hace click "Enviar
    evento de prueba" y ve el delivery aparecer en webhook.site (o en el
    endpoint del proveedor) en < 1s. Si llega, sabe que URL, secret, firma
    HMAC y reachability estan bien.

    El payload tiene event='webhook.test' y test=true para que el proveedor
    pueda filtrarlo (no contar como lead real). Insertamos en
    webhook_deliveries con event_type='lead.received' (valor permitido por
    el CHECK) y un payload claramente marcado como test.
    """
    from datetime import datetime, timezone

    from app.services import webhook_service

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar que el cliente exista, tenga webhook habilitado y URL.
            cur.execute(
                """
                SELECT id, nombre, webhook_url, webhook_enabled, webhook_secret
                FROM crm.api_clients
                WHERE id = %s::uuid AND activo = TRUE AND revoked_at IS NULL
                """,
                (client_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Proveedor no encontrado o revocado")
            if not row.get("webhook_url"):
                raise HTTPException(
                    400,
                    "Este proveedor no tiene URL de webhook configurada.",
                )
            if not row.get("webhook_enabled"):
                raise HTTPException(
                    400,
                    "El webhook esta deshabilitado. Actívalo antes de enviar la prueba.",
                )
            if not row.get("webhook_secret"):
                raise HTTPException(
                    400,
                    "El proveedor no tiene secret generado. Regenéralo desde "
                    "el modal de webhook antes de probar.",
                )

            payload = {
                "event": "webhook.test",
                "test": True,
                "delivered_at": datetime.now(timezone.utc).isoformat(),
                "client": {
                    "id":     str(row["id"]),
                    "nombre": row["nombre"],
                },
                "message": (
                    "Este es un evento de prueba enviado desde el CRM. "
                    "Si lo recibes, tu webhook está correctamente configurado. "
                    "Para diferenciarlo de eventos reales, verifica que el "
                    "campo test=true o event='webhook.test'."
                ),
            }

            # INSERT directo (NO usamos enqueue_event porque ese chequea la
            # subscription de eventos del proveedor — el test debe funcionar
            # incluso si el admin todavía no suscribió ningún evento).
            # Usamos event_type='lead.received' porque es valor permitido en
            # el CHECK constraint. El proveedor identifica el test mirando
            # payload.event = 'webhook.test' o test=true.
            cur.execute(
                """
                INSERT INTO crm.webhook_deliveries
                    (client_id, lead_id, event_type, payload, status, next_retry_at)
                VALUES (%s::uuid, NULL, 'lead.received', %s, 'pending', NOW())
                RETURNING id
                """,
                (client_id, Json(payload)),
            )
            delivery_row = cur.fetchone()
            delivery_id = delivery_row["id"] if delivery_row else None
            if not delivery_id:
                raise HTTPException(500, "No se pudo encolar el evento de prueba")
            conn.commit()

    # Dispatch inmediato — el caller ve en < 1s si llego o no en /deliveries.
    webhook_service.dispatch_async(delivery_id)
    logger.info(
        "[api_clients.webhook] test event enviado client=%s delivery=%s by admin=%s",
        client_id, delivery_id, admin.user_id,
    )
    return {
        "ok": True,
        "delivery_id": delivery_id,
        "message": (
            "Evento de prueba enviado. Verifica el inbox del proveedor "
            "(webhook.site, tu endpoint, etc) o la pestaña 'Deliveries' "
            "en este modal."
        ),
    }


@router.post("/{client_id}/webhook/deliveries/{delivery_id}/retry")
def retry_webhook_delivery(
    client_id: str,
    delivery_id: int,
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Re-encola un delivery muerto/fallido para retry inmediato.
    Util cuando el proveedor arreglo un bug y queremos reenviarle eventos
    perdidos."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE crm.webhook_deliveries
                SET status = 'retrying',
                    attempt = 0,
                    next_retry_at = NOW(),
                    error_message = NULL
                WHERE id = %s AND client_id = %s::uuid
                RETURNING id
                """,
                (delivery_id, client_id),
            )
            if not cur.fetchone():
                raise HTTPException(404, "Delivery no encontrado")
            conn.commit()
    logger.info("[api_clients.webhook] retry forzado delivery=%s by admin=%s",
                delivery_id, admin.user_id)
    return {"ok": True, "delivery_id": delivery_id}


@router.get("/{client_id}/logs")
def get_logs(
    client_id: str,
    limit: int = Query(100, ge=1, le=1000),
    _admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Ultimos N requests de este proveedor — forensics."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, ip::text, method, path, status_code, lead_id,
                       duplicated, error_msg, idempotency_key,
                       request_size, user_agent,
                       created_at::text AS created_at
                FROM crm.api_client_logs
                WHERE api_client_id = %s::uuid
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (client_id, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"logs": rows, "total": len(rows)}


# ─── V062: Lookup publico (cualquier rol autenticado) ─────────────────────

@public_router.get("/lookup")
def lookup_clients(_user: TokenData = Depends(get_current_user)):
    """Devuelve proveedores para poblar el dropdown del filtro 'Proveedor'
    en /leads. Visible a cualquier rol autenticado (asesor, supervisor,
    admin) — no expone keys ni hashes ni configuracion sensible, solo
    id/slug/nombre/activo.

    Tambien devuelve la lista de slugs legacy realmente en uso en
    crm.leads (proveedores ya desvinculados/borrados pero cuyos leads
    aun existen). Esto permite mostrar 'Proveedor original' incluso
    cuando el api_client desaparecio del catalogo.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text AS id, slug, nombre, activo
                FROM crm.api_clients
                ORDER BY activo DESC, nombre
                """
            )
            clients = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT api_client_legacy_slug   AS slug,
                       api_client_legacy_nombre AS nombre,
                       COUNT(*)::int            AS leads_count
                FROM crm.leads
                WHERE api_client_legacy_slug IS NOT NULL
                  AND activo = TRUE
                GROUP BY api_client_legacy_slug, api_client_legacy_nombre
                ORDER BY api_client_legacy_nombre
                """
            )
            legacy = [dict(r) for r in cur.fetchall()]

    return {"clients": clients, "legacy": legacy}

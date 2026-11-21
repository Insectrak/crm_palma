"""Outbound webhook service (V058).

Responsabilidades (SRP):
  - Persistir eventos en `crm.webhook_deliveries` (encolar)
  - Procesar la cola con retry exponencial y firma HMAC
  - Marcar success / retrying / dead segun resultado HTTP

Diseno escalable:
  - El INSERT de delivery es sincrono y barato (no bloquea el ingest)
  - El POST HTTP corre en un worker background (process_pending_queue)
  - Backoff exponencial: 1m, 5m, 30m, 2h, 12h (5 attempts, ~14h max)
  - Timeout corto (10s) para no acumular latencia en la red del proveedor
  - Truncamos response_body a 2k chars (evita hinchar la DB)
  - Idempotencia: cada delivery tiene id unico; reintentar es safe
  - Firma HMAC-SHA256 con webhook_secret en header X-Crm-Signature

Eventos:
  - lead.assigned        : primera asignacion de asesor
  - lead.reassigned      : cambio de asesor (manual o auto)
  - lead.status_changed  : cambio de estado del lead

Payload schema:
  {
    "event":      "lead.assigned",
    "delivered_at": "2026-05-08T19:30:00Z",
    "lead": {
      "id":         123,
      "external_id": "wedo_abc",
      "telefono":   "+51999...",
      "nombres":    "Carlos",
      "apellidos":  "Ramirez",
      "estado":     "Nuevo",
      "fuente":     "Instagram",
      "campana":    "Test Mayo"
    },
    "asesor": {
      "id":       "uuid",
      "nombre":   "Rosmary Vilca",
      "email":    "asesor2@...",
      "telefono": "999111111"
    },
    "supervisor": { ... },
    "previous_asesor": { ... }   // solo en lead.reassigned
  }
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from psycopg2.extras import Json, RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)


# ── Configuracion del retry ──────────────────────────────────────────────

# Backoff exponencial por intento (en segundos). Suma ~14h en 5 attempts.
RETRY_DELAYS_SEC = [60, 300, 1800, 7200, 43200]  # 1m, 5m, 30m, 2h, 12h
MAX_ATTEMPTS_DEFAULT = 5

# Limite de proceso por tick del worker (evita hold de conexiones)
WORKER_BATCH_SIZE = 10
HTTP_TIMEOUT_SEC = 5.0
RESPONSE_BODY_MAX_CHARS = 2000


# ── Eventos soportados (extensible) ──────────────────────────────────────

EVENT_LEAD_RECEIVED       = "lead.received"        # V076: lead entró al CRM (con o sin asesor)
EVENT_LEAD_ASSIGNED       = "lead.assigned"
EVENT_LEAD_REASSIGNED     = "lead.reassigned"
EVENT_LEAD_STATUS_CHANGED = "lead.status_changed"
EVENT_LEAD_RECONTACTO     = "lead.recontacto"      # V084: lead existente reactivado por un nuevo touch
                                                    # del proveedor (otra campaña/anuncio/conjunto).
                                                    # Patron patrón estándar 'lead_re_engagement' /
                                                    # patrón estándar 'contact_reactivated'.

ALL_EVENTS = frozenset({
    EVENT_LEAD_RECEIVED,
    EVENT_LEAD_ASSIGNED,
    EVENT_LEAD_REASSIGNED,
    EVENT_LEAD_STATUS_CHANGED,
    EVENT_LEAD_RECONTACTO,
})


# ─── HMAC signing ────────────────────────────────────────────────────────

def _sign_payload(secret: str, payload_bytes: bytes) -> str:
    """HMAC-SHA256 hex digest. El proveedor verifica con
    `hmac.compare_digest(expected, header)` usando el mismo secret."""
    mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256)
    return mac.hexdigest()


# ─── ENQUEUE: persistir un delivery pendiente ────────────────────────────

def enqueue_event(
    cur,
    *,
    client_id: str,
    lead_id: Optional[int],
    event_type: str,
    payload: dict,
) -> Optional[int]:
    """Guarda un delivery con status='pending' para que el worker lo procese.

    Devuelve el id del delivery o None si:
      - El client no tiene webhook configurado/habilitado
      - El cliente no esta suscripto al evento
      - El client_id no existe

    NUNCA levanta — los fallos se loguean. El caller no debe enterarse de
    problemas de webhook (no deben afectar el flujo de negocio).
    """
    if event_type not in ALL_EVENTS:
        logger.warning("[webhook] event_type no soportado: %s", event_type)
        return None

    try:
        cur.execute(
            """
            SELECT webhook_url, webhook_enabled, webhook_events
            FROM crm.api_clients
            WHERE id = %s::uuid AND activo = TRUE AND revoked_at IS NULL
            """,
            (client_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        # row puede ser tuple o RealDict — soportamos ambos
        if isinstance(row, dict):
            url     = row.get("webhook_url")
            enabled = row.get("webhook_enabled")
            events  = row.get("webhook_events") or []
        else:
            url, enabled, events = row[0], row[1], row[2] or []

        if not url or not enabled:
            return None
        if event_type not in events:
            return None

        cur.execute(
            """
            INSERT INTO crm.webhook_deliveries
                (client_id, lead_id, event_type, payload, status, next_retry_at)
            VALUES (%s::uuid, %s, %s, %s, 'pending', NOW())
            RETURNING id
            """,
            (client_id, lead_id, event_type, Json(payload)),
        )
        delivery_id = cur.fetchone()
        delivery_id = delivery_id["id"] if isinstance(delivery_id, dict) else delivery_id[0]
        logger.info(
            "[webhook] enqueued delivery=%s client=%s lead=%s event=%s",
            delivery_id, client_id, lead_id, event_type,
        )
        return delivery_id
    except Exception:  # noqa: BLE001 — webhook NUNCA debe romper el flujo
        logger.exception("[webhook] enqueue fallo client=%s event=%s", client_id, event_type)
        return None


def enqueue_event_in_new_conn(
    *,
    client_id: str,
    lead_id: Optional[int],
    event_type: str,
    payload: dict,
) -> Optional[int]:
    """Variante que abre su propia conexion. Util cuando el caller no
    tiene un cursor abierto (background tasks, post-commit hooks)."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                did = enqueue_event(
                    cur, client_id=client_id, lead_id=lead_id,
                    event_type=event_type, payload=payload,
                )
                conn.commit()
                return did
    except Exception:  # noqa: BLE001
        logger.exception("[webhook] enqueue_event_in_new_conn fallo")
        return None


# ─── WORKER: procesa la cola ─────────────────────────────────────────────

def process_pending_queue(batch_size: int = WORKER_BATCH_SIZE) -> dict:
    """Procesa hasta N deliveries listos (next_retry_at <= NOW()).

    Toma con `FOR UPDATE SKIP LOCKED` para que multiples workers/instancias
    puedan correr en paralelo sin pisarse. Devuelve resumen con conteos.

    Hace POST con timeout, captura status/body/error y actualiza la fila:
      - 2xx              -> success, delivered_at = NOW()
      - 4xx (excepto 408,429) -> dead inmediato (cliente mal config, no retry)
      - 5xx, 408, 429, timeout, conn error -> retrying con backoff
      - max_attempts agotado -> dead
    """
    stats = {"processed": 0, "success": 0, "retrying": 0, "dead": 0}
    now = datetime.now(timezone.utc)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Tomar batch con lock no-bloqueante (multi-worker safe)
            cur.execute(
                """
                SELECT
                    wd.id, wd.client_id::text AS client_id, wd.lead_id,
                    wd.event_type, wd.payload, wd.attempt, wd.max_attempts,
                    ac.webhook_url, ac.webhook_secret
                FROM crm.webhook_deliveries wd
                JOIN crm.api_clients ac ON ac.id = wd.client_id
                WHERE wd.status IN ('pending', 'retrying')
                  AND (wd.next_retry_at IS NULL OR wd.next_retry_at <= NOW())
                  AND ac.webhook_enabled = TRUE
                  AND ac.activo = TRUE
                ORDER BY wd.next_retry_at NULLS FIRST, wd.id
                LIMIT %s
                FOR UPDATE OF wd SKIP LOCKED
                """,
                (batch_size,),
            )
            deliveries = cur.fetchall()

            for d in deliveries:
                stats["processed"] += 1
                _process_one_delivery(cur, d, now, stats)

            conn.commit()

    if stats["processed"]:
        logger.info("[webhook.worker] %s", stats)
    return stats


def process_one_delivery_now(delivery_id: int, retry_after_commit_ms: int = 80) -> None:
    """V060.2: Dispatch INMEDIATO de un delivery especifico.

    Diseno escalable patrón estándar/servicio externo:
      1. enqueue_event inserta el delivery (status='pending')
      2. el caller hace commit
      3. esta funcion procesa el delivery en un thread fire-and-forget
         -> latencia P50 ~150-300ms en lugar de los 30-60s del worker.
      4. el worker periodico (cada 60s) sigue corriendo como SAFETY NET
         para retries y casos donde el thread fallo (server crash, etc.).

    Multi-worker safe: usa SELECT ... FOR UPDATE SKIP LOCKED, asi si el
    worker periodico ya tomo este delivery, este thread lo saltea.

    NUNCA levanta — los fallos se loguean. El thread es daemon=True asi
    que no bloquea el shutdown del proceso.
    """
    # Pequeno delay para dar tiempo al caller de commitear su transaccion.
    # Sin esto el SELECT no encontraria la fila (race condition con el commit).
    if retry_after_commit_ms > 0:
        import time as _time
        _time.sleep(retry_after_commit_ms / 1000.0)

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        wd.id, wd.client_id::text AS client_id, wd.lead_id,
                        wd.event_type, wd.payload, wd.attempt, wd.max_attempts,
                        ac.webhook_url, ac.webhook_secret
                    FROM crm.webhook_deliveries wd
                    JOIN crm.api_clients ac ON ac.id = wd.client_id
                    WHERE wd.id = %s
                      AND wd.status IN ('pending', 'retrying')
                      AND ac.webhook_enabled = TRUE
                      AND ac.activo = TRUE
                    FOR UPDATE OF wd SKIP LOCKED
                    """,
                    (delivery_id,),
                )
                row = cur.fetchone()
                if not row:
                    # Ya fue procesado por otro worker, fue cancelado o el
                    # cliente desactivo el webhook entre commit y dispatch.
                    return
                stats = {"processed": 1, "success": 0, "retrying": 0, "dead": 0}
                _process_one_delivery(cur, row, datetime.now(timezone.utc), stats)
                conn.commit()
                logger.info(
                    "[webhook.async] delivery=%s success=%d retrying=%d dead=%d",
                    delivery_id, stats["success"], stats["retrying"], stats["dead"],
                )
    except Exception:  # noqa: BLE001
        logger.exception("[webhook.async] error procesando delivery=%s", delivery_id)


def dispatch_async(delivery_id: Optional[int]) -> None:
    """Lanza un thread daemon para procesar el delivery inmediatamente.
    El caller debe haber commiteado su transaccion ANTES de llamar esta
    funcion. Si delivery_id es None (enqueue rechazado), no hace nada."""
    if not delivery_id:
        return
    import threading
    threading.Thread(
        target=process_one_delivery_now,
        args=(delivery_id,),
        daemon=True,
        name=f"webhook-async-{delivery_id}",
    ).start()


def _process_one_delivery(cur, d: dict, now: datetime, stats: dict) -> None:
    """Procesa una delivery. Asume cursor con lock activo en la fila."""
    delivery_id = d["id"]
    payload     = d["payload"]
    secret      = d["webhook_secret"] or ""
    url         = d["webhook_url"]
    attempt     = (d["attempt"] or 0) + 1
    max_attempts = d["max_attempts"] or MAX_ATTEMPTS_DEFAULT

    # Serializacion canonica + firma
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = _sign_payload(secret, payload_bytes) if secret else ""

    headers = {
        "Content-Type":     "application/json; charset=utf-8",
        "User-Agent":       "CRM-Webhook/1.0",
        "X-Crm-Event":      d["event_type"],
        "X-Crm-Delivery":   str(delivery_id),
        "X-Crm-Signature":  f"sha256={signature}" if signature else "",
        "X-Crm-Attempt":    str(attempt),
    }

    t0 = datetime.now(timezone.utc)
    http_status: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    is_success = False
    is_retryable = False

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SEC) as client:
            resp = client.post(url, content=payload_bytes, headers=headers)
            http_status = resp.status_code
            response_body = (resp.text or "")[:RESPONSE_BODY_MAX_CHARS]
            if 200 <= resp.status_code < 300:
                is_success = True
            elif resp.status_code in (408, 429) or 500 <= resp.status_code < 600:
                is_retryable = True
            # 4xx (excepto 408, 429) => dead inmediato
    except httpx.TimeoutException as exc:
        error_message = f"timeout: {exc}"
        is_retryable = True
    except httpx.HTTPError as exc:
        error_message = f"http_error: {exc}"
        is_retryable = True
    except Exception as exc:  # noqa: BLE001
        error_message = f"unexpected: {exc}"
        is_retryable = True

    duration_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)

    # Decision final
    if is_success:
        new_status = "success"
        next_retry_at = None
        delivered_at = now
        stats["success"] += 1
    elif is_retryable and attempt < max_attempts:
        new_status = "retrying"
        delay = RETRY_DELAYS_SEC[min(attempt - 1, len(RETRY_DELAYS_SEC) - 1)]
        next_retry_at = now + timedelta(seconds=delay)
        delivered_at = None
        stats["retrying"] += 1
    else:
        new_status = "dead"
        next_retry_at = None
        delivered_at = None
        stats["dead"] += 1

    cur.execute(
        """
        UPDATE crm.webhook_deliveries
        SET status         = %s,
            attempt        = %s,
            signature      = %s,
            http_status    = %s,
            response_body  = %s,
            error_message  = %s,
            next_retry_at  = %s,
            last_attempt_at = NOW(),
            delivered_at   = %s,
            duration_ms    = %s
        WHERE id = %s
        """,
        (
            new_status, attempt, signature, http_status, response_body,
            error_message, next_retry_at, delivered_at, duration_ms,
            delivery_id,
        ),
    )

    logger.info(
        "[webhook.worker] delivery=%s client=%s event=%s attempt=%d status=%s http=%s ms=%d",
        delivery_id, d["client_id"], d["event_type"],
        attempt, new_status, http_status, duration_ms,
    )


# ─── Helper para construir payload estandar ───────────────────────────────

def _get_privacy_config(cur, client_id: str) -> dict:
    """V059: Lee los toggles de privacidad del api_client. Si el client
    no existe (race condition raro), defaults conservadores."""
    try:
        cur.execute(
            """
            SELECT
                webhook_include_asesor_contact,
                webhook_include_supervisor,
                webhook_include_supervisor_contact
            FROM crm.api_clients
            WHERE id = %s::uuid
            """,
            (client_id,),
        )
        row = cur.fetchone()
        if not row:
            return {
                "include_asesor_contact": True,
                "include_supervisor": True,
                "include_supervisor_contact": False,
            }
        if isinstance(row, dict):
            return {
                "include_asesor_contact":     bool(row.get("webhook_include_asesor_contact", True)),
                "include_supervisor":         bool(row.get("webhook_include_supervisor", True)),
                "include_supervisor_contact": bool(row.get("webhook_include_supervisor_contact", False)),
            }
        return {
            "include_asesor_contact":     bool(row[0]),
            "include_supervisor":         bool(row[1]),
            "include_supervisor_contact": bool(row[2]),
        }
    except Exception:  # noqa: BLE001
        return {
            "include_asesor_contact": True,
            "include_supervisor": True,
            "include_supervisor_contact": False,
        }


def build_lead_payload(
    cur,
    *,
    lead_id: int,
    event_type: str,
    previous_asesor_id: Optional[str] = None,
    previous_estado_id: Optional[int] = None,
    client_id: Optional[str] = None,
    recontacto_id: Optional[int] = None,
) -> Optional[dict]:
    """Construye el payload estandar para eventos lead.*.

    Devuelve None si el lead no existe (race condition con DELETE).

    V059: si se pasa client_id, aplica los toggles de privacidad del
    api_client (filtra email/telefono del asesor y/o supervisor segun
    config). Sin client_id, devuelve el payload completo (caller debe
    asegurar que no se envia a destinatarios no autorizados).

    V084: si event_type='lead.recontacto' y se pasa recontacto_id, agrega
    un bloque 'recontacto' con la atribucion del NUEVO touch (campaña,
    anuncio, conjunto, fuente, etc.). El bloque 'lead' mantiene la
    atribucion ORIGINAL (patron estandar de la industria: el lead canonico
    nunca se pisa).
    """
    privacy = _get_privacy_config(cur, client_id) if client_id else {
        "include_asesor_contact": True,
        "include_supervisor": True,
        "include_supervisor_contact": False,
    }
    # V096 — form_id real + nombres legibles via meta_catalog_cache.
    # Patron identico al de leads_repository: el cache guarda
    # (entity_type, entity_id, name) y se hidrata al INSERT del lead.
    # Si no hay fila en el cache, mc_*.name queda NULL y el consumer
    # ve null en el JSON (acepta cualquier consumer JSON razonable).
    cur.execute(
        """
        SELECT
            l.id, l.fuente_externa_id AS external_id,
            l.nombres, l.apellidos, l.telefono, l.email, l.dni,
            l.campana, l.conjunto, l.anuncio,
            l.fuente_form_id,
            mc_c.name AS campaign_name,
            mc_f.name AS form_name,
            f.nombre AS fuente,
            e.nombre AS estado,
            l.asesor_id::text AS asesor_id,
            l.supervisor_id::text AS supervisor_id,
            ua.email AS asesor_email, ua.telefono AS asesor_telefono,
            TRIM(CONCAT_WS(' ', ua.first_name, ua.last_name)) AS asesor_nombre,
            us.email AS supervisor_email, us.telefono AS supervisor_telefono,
            TRIM(CONCAT_WS(' ', us.first_name, us.last_name)) AS supervisor_nombre,
            l.created_at::text AS created_at
        FROM crm.leads l
        LEFT JOIN crm.fuentes f       ON f.id = l.fuente_id
        LEFT JOIN crm.estados_lead e  ON e.id = l.estado_id
        LEFT JOIN auth.users ua       ON ua.id = l.asesor_id
        LEFT JOIN auth.users us       ON us.id = l.supervisor_id
        LEFT JOIN crm.meta_catalog_cache mc_c
          ON mc_c.entity_type = 'campaign' AND mc_c.entity_id = l.campana
        LEFT JOIN crm.meta_catalog_cache mc_f
          ON mc_f.entity_type = 'form'     AND mc_f.entity_id = l.fuente_form_id
        WHERE l.id = %s
        """,
        (lead_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    # V059: filtrar campos sensibles segun los toggles de privacidad
    asesor_block = None
    if row.get("asesor_id"):
        asesor_block = {
            "id":     row.get("asesor_id"),
            "nombre": row.get("asesor_nombre"),
        }
        if privacy["include_asesor_contact"]:
            asesor_block["email"]    = row.get("asesor_email")
            asesor_block["telefono"] = row.get("asesor_telefono")

    supervisor_block = None
    if row.get("supervisor_id") and privacy["include_supervisor"]:
        supervisor_block = {
            "id":     row.get("supervisor_id"),
            "nombre": row.get("supervisor_nombre"),
        }
        if privacy["include_supervisor_contact"]:
            supervisor_block["email"]    = row.get("supervisor_email")
            supervisor_block["telefono"] = row.get("supervisor_telefono")

    payload: dict[str, Any] = {
        "event":        event_type,
        "delivered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lead": {
            "id":             row["id"],
            "external_id":    row.get("external_id"),
            "nombres":        row["nombres"],
            "apellidos":      row.get("apellidos"),
            "telefono":       row["telefono"],
            "email":          row.get("email"),
            "dni":            row.get("dni"),
            "fuente":         row.get("fuente"),
            "campana":        row.get("campana"),
            # V096: nombres legibles resueltos via cache. NULL si no hay cache.
            "campaign_name":  row.get("campaign_name"),
            "fuente_form_id": row.get("fuente_form_id"),
            "form_name":      row.get("form_name"),
            "conjunto":       row.get("conjunto"),
            "anuncio":        row.get("anuncio"),
            "estado":         row.get("estado"),
            "created_at":     row.get("created_at"),
        },
        "asesor":     asesor_block,
        "supervisor": supervisor_block,
    }

    # Para reassigned: incluir el asesor anterior (respetando privacy)
    if event_type == EVENT_LEAD_REASSIGNED and previous_asesor_id:
        cur.execute(
            """
            SELECT id::text AS id, email, telefono,
                   TRIM(CONCAT_WS(' ', first_name, last_name)) AS nombre
            FROM auth.users WHERE id = %s::uuid
            """,
            (previous_asesor_id,),
        )
        prev = cur.fetchone()
        if prev:
            prev_block = {
                "id":     prev["id"],
                "nombre": prev["nombre"],
            }
            if privacy["include_asesor_contact"]:
                prev_block["email"]    = prev.get("email")
                prev_block["telefono"] = prev.get("telefono")
            payload["previous_asesor"] = prev_block

    # Para status_changed: incluir el estado anterior
    if event_type == EVENT_LEAD_STATUS_CHANGED and previous_estado_id is not None:
        cur.execute(
            "SELECT nombre FROM crm.estados_lead WHERE id = %s",
            (previous_estado_id,),
        )
        prev_est = cur.fetchone()
        if prev_est:
            payload["previous_estado"] = prev_est["nombre"] if isinstance(prev_est, dict) else prev_est[0]

    # V084 — Para lead.recontacto: bloque con la atribucion del NUEVO touch.
    # El bloque 'lead' arriba sigue mostrando la atribucion original; este
    # bloque revela la campaña/anuncio/conjunto que generó este re-engagement.
    # Si no hay recontacto_id o la fila no se encuentra, omitimos el bloque
    # silenciosamente (defensa contra race conditions con purges).
    if event_type == EVENT_LEAD_RECONTACTO and recontacto_id is not None:
        try:
            # V096.4 — campaign_name y form_name al bloque recontacto via JOINs
            # al meta_catalog_cache (mismo patron que el bloque `lead` arriba).
            # Antes el recontacto solo devolvia los IDs (campana, fuente_form_id);
            # los consumers tenian que hacer lookup propio. Ahora simetria total.
            cur.execute(
                """
                SELECT
                    r.id,
                    r.campana,
                    mc_c.name AS campaign_name,
                    r.anuncio,
                    r.conjunto,
                    r.fuente_form_id,
                    mc_f.name AS form_name,
                    r.fuente_externa_id,
                    r.external_created_at,
                    r.estrategia,
                    r.estado_lead_anterior,
                    r.razon,
                    r.created_at,
                    f.nombre AS fuente
                FROM crm.lead_recontactos r
                LEFT JOIN crm.fuentes f ON f.id = r.fuente_id
                LEFT JOIN crm.meta_catalog_cache mc_c
                  ON mc_c.entity_type = 'campaign' AND mc_c.entity_id = r.campana
                LEFT JOIN crm.meta_catalog_cache mc_f
                  ON mc_f.entity_type = 'form'     AND mc_f.entity_id = r.fuente_form_id
                WHERE r.id = %s
                """,
                (recontacto_id,),
            )
            rr = cur.fetchone()
            if rr:
                def _iso(v):
                    if v is None:
                        return None
                    try:
                        return v.isoformat().replace("+00:00", "Z") if hasattr(v, "isoformat") else str(v)
                    except Exception:  # noqa: BLE001
                        return str(v)
                # Acceso solo por nombre (cursor RealDict). El soporte por
                # indice se removio porque agregar columnas al SELECT obligaba
                # a renumerar los indices — fuente de bugs de mantenimiento.
                payload["recontacto"] = {
                    "id":                   rr["id"],
                    "campana":              rr.get("campana"),
                    "campaign_name":        rr.get("campaign_name"),
                    "anuncio":              rr.get("anuncio"),
                    "conjunto":             rr.get("conjunto"),
                    "fuente_form_id":       rr.get("fuente_form_id"),
                    "form_name":            rr.get("form_name"),
                    "fuente_externa_id":    rr.get("fuente_externa_id"),
                    "external_created_at":  _iso(rr.get("external_created_at")),
                    "estrategia":           rr.get("estrategia"),
                    "estado_lead_anterior": rr.get("estado_lead_anterior"),
                    "razon":                rr.get("razon"),
                    "fuente":               rr.get("fuente"),
                    "created_at":           _iso(rr.get("created_at")),
                }
        except Exception:  # noqa: BLE001
            logger.warning(
                "[webhook] no se pudo cargar recontacto_id=%s para lead=%s",
                recontacto_id, lead_id, exc_info=True,
            )

    return payload

"""
Ingesta automatica de leads desde n8n (Facebook, TikTok, WhatsApp) y
proveedores externos via API key.

- POST /api/ingest/leads     — crea un lead asignandolo al siguiente
                               supervisor segun round-robin diario.
- GET  /api/ingest/rotacion  — estado actual de la rotacion del dia (admin).

AUTENTICACION (dual mode):
  1. Multi-tenant (recomendado): header `X-Api-Key: cli_<prefix>_<secret>`
     buscado en crm.api_clients. Permite atribucion + revocacion + rate
     limit por proveedor. Auto-asigna fuente desde el client (no del body).
  2. Legacy: header `X-Api-Key: <INGEST_API_KEY>` — backwards compat con
     n8n actual. Sin trazabilidad por proveedor.

HARDENING:
  - Hash SHA-256 con timing-safe compare.
  - IP whitelist opcional por client.
  - Rate limit por client (sliding window 60s).
  - Idempotency-Key dedupe (24h cache en DB).
  - Audit log de cada request en crm.api_client_logs.

Dedupe: por telefono contra crm.leads. Si ya existe, responde
        {duplicated: true, id} sin avanzar el contador de rotacion.

Nota de arquitectura: toda la logica reusable vive en
`services.integrations.ingest_core.ingest_lead_core`. Este router es solo
el transport para n8n — el mismo core lo usan el webhook de Meta y el
poller de TikTok.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Depends, Request
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import get_db
from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.services.integrations.ingest_core import (
    IngestError,
    IngestPayload,
    ingest_lead_core,
)
from app.services import api_clients_service as api_clients

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingest", tags=["Ingest"])


# ── Auth por API key (dual: multi-tenant + legacy) ──────────────────────────

def _get_client_ip(request: Request) -> Optional[str]:
    """Extrae IP real respetando proxy. Prioriza X-Forwarded-For (EasyPanel
    usa traefik). Cae en request.client.host."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        # Primer IP en la cadena = cliente original
        return fwd.split(",")[0].strip()
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    return request.client.host if request.client else None


class IngestAuth:
    """Resultado de la autenticacion de ingest. Si usa client multi-tenant,
    .client trae el row; si es legacy, .client es None."""
    def __init__(self, *, client: Optional[dict] = None, key_prefix: Optional[str] = None):
        self.client = client
        self.key_prefix = key_prefix

    @property
    def is_multitenant(self) -> bool:
        return self.client is not None

    @property
    def client_id(self) -> Optional[str]:
        return str(self.client["id"]) if self.client else None


def authenticate_ingest(request: Request, x_api_key: Optional[str] = Header(None, alias="X-Api-Key")) -> IngestAuth:
    """Valida la key recibida. Soporta ambos formatos."""
    if not x_api_key:
        raise HTTPException(401, "API key ausente.")

    ip = _get_client_ip(request)

    # Modo 1: cli_... (multi-tenant)
    if x_api_key.startswith(api_clients.KEY_PREFIX):
        try:
            client_row = api_clients.authenticate(x_api_key, request_ip=ip)
        except api_clients.ApiClientAuthError as exc:
            api_clients.log_request(
                client_id=None,
                api_key_prefix=api_clients.parse_prefix(x_api_key),
                ip=ip, method=request.method, path=str(request.url.path),
                status_code=exc.code, error_msg=str(exc),
                user_agent=request.headers.get("User-Agent"),
            )
            raise HTTPException(exc.code, str(exc)) from exc

        # Rate limit
        ok, remaining = api_clients.check_rate_limit(
            str(client_row["id"]), client_row["rate_limit_per_minute"]
        )
        if not ok:
            api_clients.log_request(
                client_id=str(client_row["id"]),
                api_key_prefix=client_row["api_key_prefix"],
                ip=ip, method=request.method, path=str(request.url.path),
                status_code=429, error_msg="rate limit exceeded",
                user_agent=request.headers.get("User-Agent"),
            )
            raise HTTPException(429, f"Rate limit excedido ({client_row['rate_limit_per_minute']}/min). Intenta en 60s.")
        return IngestAuth(client=client_row, key_prefix=client_row["api_key_prefix"])

    # Modo 2: legacy INGEST_API_KEY (backwards compat con n8n)
    if not settings.ingest_api_key:
        raise HTTPException(500, "INGEST_API_KEY no configurado en el servidor.")
    if x_api_key != settings.ingest_api_key:
        raise HTTPException(401, "API key invalida.")
    return IngestAuth(client=None, key_prefix="legacy")


# Compat: muchos otros endpoints usan require_api_key — mantenemos el alias.
def require_api_key(x_api_key: str = Header(None, alias="X-Api-Key")):
    if not settings.ingest_api_key:
        raise HTTPException(500, "INGEST_API_KEY no configurado en el servidor.")
    if not x_api_key or x_api_key != settings.ingest_api_key:
        raise HTTPException(401, "API key invalido o ausente.")
    return True


# ── Schemas ──────────────────────────────────────────────────────────────────

class IngestLead(BaseModel):
    fuente: str                           # 'facebook' | 'tiktok' | 'whatsapp' | ...
    telefono: str
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    email: Optional[str] = None
    campana: Optional[str] = None
    fuente_externa_id: Optional[str] = None
    # V068.7 — timestamp REAL del evento en el proveedor (ej. cuando el
    # cliente realmente lleno el form, no cuando se ingreso al CRM).
    # Habilita la validacion de Backfill Protection (V068.4): si el
    # external_created_at es anterior al created_at del lead, no se
    # cuenta como reactivacion. Formato ISO 8601 (ej. "2026-05-13T14:32:18Z").
    external_created_at: Optional[str] = None
    observaciones: Optional[str] = None

    # V053 — campos opcionales para integracion con proveedores IA externos
    # (We Do, similares). Todos son optionales y retrocompatibles: drivers
    # existentes (Meta nativo, TikTok, n8n legacy) los ignoran sin romper.
    nombre_completo: Optional[str] = None     # Fallback si no vienen nombres+apellidos
    apellido:        Optional[str] = None     # Schema We Do (apellido singular)
    dni:             Optional[str] = None
    # V086.1 — datos demográficos del proveedor (enriquecimiento conservador).
    ciudad:          Optional[str] = None
    trabajo:         Optional[str] = None
    anuncio:         Optional[str] = None     # Nivel Ad de Meta
    conjunto:        Optional[str] = None     # Nivel Ad Set de Meta
    form_name:       Optional[str] = None     # Hint del nombre del form
    # V096: IDs reales de Meta/TikTok para trazabilidad por ID (no por nombre).
    # Sin estos campos el proveedor solo podia mandar el nombre legible, que
    # se rompe cuando renombran la campania/form en Ads Manager. Con el ID
    # los reportes agrupan consistente aunque el nombre cambie.
    fuente_form_id:  Optional[str] = None     # form_id de Meta/TikTok (texto, no numero — los IDs exceden Number.MAX_SAFE_INTEGER)
    campaign_name:   Optional[str] = None     # Hint del nombre de la campania (display)
    nivel:           Optional[str] = None     # 'Nuevo' | 'Contactado' (allowlist)
    asesor_telefono: Optional[str] = None     # Pre-asignacion via vendedor
    resumen_ia:      Optional[str] = None     # Transcripcion conversacion IA
    extra:           Optional[Dict[str, Any]] = None    # Campos custom → datos_extra

    # V065 — sede de destino del lead. El provider puede mandar el slug
    # de la sede (case-insensitive) y el backend lo resuelve a sede_id.
    # Si NO viene, se usa api_clients.sede_id_default de la key. Si
    # tampoco hay default, el lead queda con sede=NULL.
    sede:            Optional[str] = None     # codigo/slug de la sede


# ── Endpoints ────────────────────────────────────────────────────────────────

_FECHA_LIMA = "(NOW() AT TIME ZONE 'America/Lima')::date"


@router.post("/leads", status_code=201)
def ingest_lead(
    payload: IngestLead,
    request: Request,
    auth: IngestAuth = Depends(authenticate_ingest),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Inserta un lead y lo asigna al siguiente supervisor por round-robin.

    Si la auth es multi-tenant (cli_...), la fuente se toma del client.fuente_id
    (no del body — el provider no puede mentir sobre su origen).
    Si la auth es legacy, se respeta payload.fuente.
    """
    ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    request_size = int(request.headers.get("Content-Length") or 0) or None

    # Idempotency: si la misma key vino en las ultimas 24h, devolvemos el cache.
    if auth.is_multitenant and idempotency_key:
        cached = api_clients.get_idempotent_response(auth.client_id, idempotency_key)
        if cached:
            api_clients.log_request(
                client_id=auth.client_id, api_key_prefix=auth.key_prefix,
                ip=ip, method=request.method, path=str(request.url.path),
                status_code=200, lead_id=cached.get("id"), duplicated=True,
                error_msg="idempotent replay", idempotency_key=idempotency_key,
                request_size=request_size, user_agent=user_agent,
            )
            return cached

    # V070.58 — Resolución de fuente con fallback al default del client
    # (paridad con APIs profesionales). Comportamiento:
    #
    # 1. Si el body declara `fuente` no-vacía → se respeta (el proveedor
    #    sabe mejor que nadie el canal real: instagram, tiktok, etc).
    # 2. Si el body NO declara `fuente` Y el client tiene `fuente_id`
    #    default configurado en el panel → se usa esa.
    # 3. Si ninguno está disponible → 400 con mensaje claro.
    #
    # Antes el body SIEMPRE mandaba y el campo "Fuente default" del panel
    # se ignoraba silenciosamente — la UI prometía algo que el código no
    # cumplía. Ahora el default funciona como un fallback útil cuando el
    # proveedor no declara.
    fuente_real = (payload.fuente or "").strip()
    if not fuente_real and auth.is_multitenant and auth.client.get("fuente_id"):
        # Lookup del nombre de la fuente default del client.
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT nombre FROM crm.fuentes WHERE id = %s AND activo = TRUE",
                    (auth.client["fuente_id"],),
                )
                row = cur.fetchone()
                if row:
                    fuente_real = row["nombre"]
                    logger.info(
                        "[ingest] usando fuente default del client (id=%s nombre=%s)",
                        auth.client["fuente_id"], fuente_real,
                    )
    if not fuente_real:
        raise HTTPException(
            status_code=400,
            detail=(
                "Falta el campo 'fuente' en el payload y el proveedor no tiene una "
                "fuente default configurada. Soluciones: 1) Agrega 'fuente' en el body "
                "(ej: 'instagram', 'facebook', 'tiktok', 'web'), o 2) Pide al admin "
                "del CRM que configure una 'Fuente default' en tu proveedor."
            ),
        )

    # V068.7 — parse external_created_at del provider si vino.
    # Aceptamos ISO 8601 con o sin offset (ej. "2026-05-13T14:32:18Z" o
    # "2026-05-13 14:32:18+00:00"). Si falla el parse, ignoramos y caemos
    # a la regla per-day (V068.3) sin bloquear el ingest.
    _ext_created = None
    if payload.external_created_at:
        try:
            from datetime import datetime as _dt, timezone as _tz
            s = payload.external_created_at.strip().replace("Z", "+00:00")
            _ext_created = _dt.fromisoformat(s)
            if _ext_created.tzinfo is None:
                _ext_created = _ext_created.replace(tzinfo=_tz.utc)
        except Exception:  # noqa: BLE001
            _ext_created = None  # silent fallback

    core_payload = IngestPayload(
        fuente=fuente_real,
        telefono=payload.telefono,
        nombres=payload.nombres,
        apellidos=payload.apellidos,
        email=payload.email,
        campana=payload.campana,
        fuente_externa_id=payload.fuente_externa_id,
        external_created_at=_ext_created,  # V068.7
        observaciones=payload.observaciones,
        # V053 — campos del proveedor IA (todos opcionales)
        nombre_completo=payload.nombre_completo,
        apellido=payload.apellido,
        dni=payload.dni,
        ciudad=payload.ciudad,
        trabajo=payload.trabajo,
        anuncio=payload.anuncio,
        conjunto=payload.conjunto,
        form_name=payload.form_name,
        # V096: paridad con drivers nativos (Meta/TikTok) que ya pasan estos
        # campos al core. Sin esto se descartaban silenciosamente aunque el
        # core los soportaba — bug visible para integraciones IA externas (Wedo).
        fuente_form_id=payload.fuente_form_id,
        campaign_name=payload.campaign_name,
        nivel=payload.nivel,
        asesor_telefono=payload.asesor_telefono,
        resumen_ia=payload.resumen_ia,
        extra=payload.extra,
        # V085 — Pasar api_client_id al core para que lead_recapture lo
        # persista en crm.lead_recontactos.api_client_id. Sin esto, los
        # recontactos no se podian filtrar por proveedor y el badge del
        # frontend no funcionaba para wedo/wedo3.
        api_client_id=auth.client_id if auth.is_multitenant else None,
    )

    webhook_delivery_id = None  # V060.2: para dispatch async post-commit
    webhook_received_delivery_id = None  # V076: lead.received (siempre, sin importar asesor)
    webhook_recontacto_delivery_id = None  # V084: lead.recontacto (re-engagement)
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = ingest_lead_core(cur, core_payload)
                # Trazabilidad: api_client_id en el lead (solo si nuevo + multi-tenant).
                # V054.1: ya NO pisamos fuente_id con auth.client["fuente_id"].
                # ingest_lead_core ya seteo el fuente_id correcto a partir de
                # payload.fuente (el canal real: instagram/facebook/etc).
                # Solo guardamos el api_client_id para preservar la atribucion
                # al proveedor que entrego el lead.
                if auth.is_multitenant and not result.get("duplicated") and result.get("id"):
                    cur.execute(
                        "UPDATE crm.leads SET api_client_id = %s::uuid WHERE id = %s",
                        (auth.client_id, result["id"]),
                    )
                    # V065: resolver sede para este lead.
                    # Prioridad: payload.sede (slug) > api_client.sede_id_default.
                    # El slug se valida y resuelve a uuid; si no existe la
                    # sede, se loguea y se cae al default del client.
                    sede_uuid = None
                    if payload.sede:
                        slug = payload.sede.strip().lower()
                        cur.execute(
                            "SELECT id FROM crm.sedes WHERE codigo = %s AND activo = TRUE",
                            (slug,),
                        )
                        sede_row = cur.fetchone()
                        if sede_row:
                            sede_uuid = sede_row["id"]
                        else:
                            logger.warning(
                                "[ingest] sede '%s' no encontrada o inactiva — usando default del client",
                                slug,
                            )
                    if not sede_uuid and auth.client.get("sede_id_default"):
                        sede_uuid = auth.client["sede_id_default"]
                    if sede_uuid:
                        cur.execute(
                            "UPDATE crm.leads SET sede_id = %s::uuid WHERE id = %s",
                            (sede_uuid, result["id"]),
                        )
                # V058 + V076 + V084: encolar webhooks despues del INSERT.
                # IMPORTANTE: este bloque vive AFUERA del `if not duplicated`
                # porque un recontacto tambien debe disparar webhook
                # (`lead.recontacto`). Antes el bloque estaba adentro y los
                # recontactos quedaban invisibles para el proveedor.
                #
                # Reglas (paridad con CRMs profesionales):
                #   - lead.received   → solo lead NUEVO (no recontacto).
                #   - lead.assigned   → solo lead NUEVO con asesor.
                #   - lead.recontacto → recontacto REAL (persistido en
                #     lead_recontactos). Skip si fue duplicate_event,
                #     backfill_skip, same_day_resubmission, o
                #     fext_already_processed — esos no son señal comercial.
                if auth.is_multitenant and result.get("id"):
                    try:
                        from app.services import webhook_service
                        if not result.get("duplicated"):
                            # 1) lead.received SIEMPRE para leads nuevos
                            payload_recv = webhook_service.build_lead_payload(
                                cur, lead_id=result["id"],
                                event_type=webhook_service.EVENT_LEAD_RECEIVED,
                                client_id=auth.client_id,
                            )
                            if payload_recv:
                                webhook_received_delivery_id = webhook_service.enqueue_event(
                                    cur, client_id=auth.client_id,
                                    lead_id=result["id"],
                                    event_type=webhook_service.EVENT_LEAD_RECEIVED,
                                    payload=payload_recv,
                                )
                            # 2) lead.assigned solo si entró con asesor
                            if result.get("asesor_id"):
                                payload_evt = webhook_service.build_lead_payload(
                                    cur, lead_id=result["id"],
                                    event_type=webhook_service.EVENT_LEAD_ASSIGNED,
                                    client_id=auth.client_id,
                                )
                                if payload_evt:
                                    webhook_delivery_id = webhook_service.enqueue_event(
                                        cur, client_id=auth.client_id,
                                        lead_id=result["id"],
                                        event_type=webhook_service.EVENT_LEAD_ASSIGNED,
                                        payload=payload_evt,
                                    )
                        else:
                            # V084: recontacto REAL (no re-import, no backfill).
                            # Skip si el recontacto no se persistio o fue dedup.
                            is_real_recontacto = (
                                result.get("recontacto") is True
                                and result.get("recontacto_id") is not None
                                and not result.get("duplicate_event")
                                and not result.get("backfill_skip")
                            )
                            if is_real_recontacto:
                                payload_rec = webhook_service.build_lead_payload(
                                    cur, lead_id=result["id"],
                                    event_type=webhook_service.EVENT_LEAD_RECONTACTO,
                                    client_id=auth.client_id,
                                    recontacto_id=result["recontacto_id"],
                                )
                                if payload_rec:
                                    webhook_recontacto_delivery_id = webhook_service.enqueue_event(
                                        cur, client_id=auth.client_id,
                                        lead_id=result["id"],
                                        event_type=webhook_service.EVENT_LEAD_RECONTACTO,
                                        payload=payload_rec,
                                    )
                    except Exception:  # noqa: BLE001
                        logger.exception("[ingest] webhook enqueue fallo lead=%s", result.get("id"))
            conn.commit()
            # V060.2: dispatch INMEDIATO de los webhooks (fire-and-forget thread).
            # Latencia P50 ~150-300ms vs los 30-60s del worker periodico.
            # El worker sigue corriendo como safety net para retries.
            if auth.is_multitenant:
                from app.services import webhook_service
                if webhook_received_delivery_id:
                    webhook_service.dispatch_async(webhook_received_delivery_id)
                if webhook_delivery_id:
                    webhook_service.dispatch_async(webhook_delivery_id)
                if webhook_recontacto_delivery_id:
                    webhook_service.dispatch_async(webhook_recontacto_delivery_id)
    except IngestError as exc:
        # V070.76 — SLI counter: lead rechazado (telefono invalido, sin fuente, etc).
        try:
            from app.metrics import ingest_leads
            ingest_leads.labels(
                api_client_prefix=auth.key_prefix or "legacy",
                fuente=fuente_real or "unknown",
                result="rejected",
            ).inc()
        except Exception:  # noqa: BLE001
            pass
        if auth.is_multitenant:
            api_clients.log_request(
                client_id=auth.client_id, api_key_prefix=auth.key_prefix,
                ip=ip, method=request.method, path=str(request.url.path),
                status_code=exc.status_code, error_msg=exc.detail,
                idempotency_key=idempotency_key,
                request_size=request_size, user_agent=user_agent,
            )
            api_clients.increment_metrics(auth.client_id, rechazados=1)
        raise HTTPException(exc.status_code, exc.detail) from exc

    # V070.76 — SLI counter: lead procesado exitosamente.
    try:
        from app.metrics import ingest_leads
        if result.get("duplicated"):
            metric_result = "duplicated"
        elif result.get("recontacto_id"):
            metric_result = "reactivated"
        else:
            metric_result = "created"
        ingest_leads.labels(
            api_client_prefix=auth.key_prefix or "legacy",
            fuente=fuente_real or "unknown",
            result=metric_result,
        ).inc()
    except Exception:  # noqa: BLE001
        pass

    response: dict
    if result["duplicated"]:
        response = result
    else:
        # Push notification: si el lead ya quedo asignado a un asesor (via
        # V053 pre-asignacion o V046 auto-assign), notificamos al asesor
        # que recibe el lead. Si no se pudo asignar y queda en cola del
        # supervisor, notificamos al supervisor — pattern consistente con
        # assignments_service.py y whatsapp.py.
        from app.services.notification_service import notify_new_lead
        lead_name = f"{result['nombres']} {result.get('apellidos') or ''}".strip()
        target_user = result.get("asesor_id") or result["supervisor_id"]
        target_role = "asesor" if result.get("asesor_id") else "supervisor"
        try:
            # V070.91 — Pasamos lead_id para deep-link en mobile al tap.
            sent = notify_new_lead(
                target_user, lead_name, fuente_real,
                lead_id=result.get("id"),
            )
            logger.info(
                "[ingest] push lead=%s target=%s role=%s name=%r sent=%s",
                result.get("id"), target_user, target_role, lead_name, sent,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ingest] push notification fallido lead=%s: %s",
                           result.get("id"), exc)
        response = {
            "duplicated":    False,
            "id":            result["id"],
            "mode":          result["mode"],
            "asesor_id":     result["asesor_id"],
            "supervisor_id": result["supervisor_id"],
        }

    if auth.is_multitenant:
        # Audit + metricas
        api_clients.log_request(
            client_id=auth.client_id, api_key_prefix=auth.key_prefix,
            ip=ip, method=request.method, path=str(request.url.path),
            status_code=200 if result["duplicated"] else 201,
            lead_id=result.get("id"), duplicated=bool(result["duplicated"]),
            idempotency_key=idempotency_key,
            request_size=request_size, user_agent=user_agent,
        )
        if result["duplicated"]:
            api_clients.increment_metrics(auth.client_id, duplicados=1)
        else:
            api_clients.increment_metrics(auth.client_id, leads=1)
        # Cache para Idempotency-Key
        if idempotency_key:
            api_clients.store_idempotent_response(auth.client_id, idempotency_key, response)

    logger.info(
        "Ingest lead %s -> supervisor=%s (mode=%s, fuente=%s, client=%s)",
        result.get("id"), result.get("supervisor_id"), result.get("mode"),
        fuente_real, auth.key_prefix or "legacy",
    )
    return response


@router.get("/rotacion")
def rotacion_hoy(current_user: TokenData = Depends(require_admin)):
    """Estado de la rotacion del dia (admin). Incluye supervisores sin actividad."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    u.id::text AS supervisor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS supervisor_nombre,
                    u.email,
                    u.activo_rotacion,
                    -- V094.7 — surfacing del flag al UI para distinguir
                    -- "saltado por login bloqueado" vs "pausado manualmente".
                    COALESCE(u.login_blocked, FALSE) AS login_blocked,
                    COALESCE(r.contador, 0) AS contador,
                    r.ultimo_lead_id,
                    r.updated_at
                FROM auth.users u
                LEFT JOIN crm.rotacion_diaria r
                    ON r.supervisor_id = u.id
                   AND r.fecha = {_FECHA_LIMA}
                WHERE u.role = 'supervisor' AND u.is_active = TRUE
                ORDER BY contador DESC, supervisor_nombre
                """
            )
            rows = cur.fetchall()
    for r in rows:
        if r.get("updated_at"):
            r["updated_at"] = r["updated_at"].isoformat()
    return {"fecha_lima": None, "items": rows}


class RotacionToggle(BaseModel):
    activo_rotacion: bool


@router.patch("/rotacion/{supervisor_id}")
def toggle_rotacion(
    supervisor_id: str,
    payload: RotacionToggle,
    current_user: TokenData = Depends(require_admin),
):
    """Activa/desactiva temporalmente a un supervisor del round-robin (admin).

    Issue #59 — Toggles INDEPENDIENTES, estilo CRMs profesionales.

    Pausar al supervisor en distribucion entre supervisores NO altera el toggle
    `auto_asignar_enabled` del equipo. Esto soporta el caso "supervisor en
    escalation": equipo pausado y supervisor activo para que el manager
    distribuya manualmente leads atrasados. O viceversa.

    El frontend visualiza las combinaciones inusuales con un banner.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE auth.users
                   SET activo_rotacion = %s
                 WHERE id = %s::uuid
                   AND role = 'supervisor'
                   AND is_active = TRUE
                RETURNING id::text AS id, activo_rotacion
                """,
                (payload.activo_rotacion, supervisor_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Supervisor no encontrado.")
        conn.commit()
    logger.info(
        "Rotacion toggle: supervisor=%s activo=%s (by %s)",
        supervisor_id, payload.activo_rotacion, current_user.email,
    )
    return row

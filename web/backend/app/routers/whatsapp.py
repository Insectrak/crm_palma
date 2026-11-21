"""
WhatsApp Business Cloud API — integracion oficial con Meta.

Endpoints:
- GET  /api/whatsapp/webhook         — verificacion del webhook (hub challenge)
- POST /api/whatsapp/webhook         — recepcion de eventos (mensajes, status, referral)
- POST /api/whatsapp/send            — enviar mensaje (texto / template / interactive)
- GET  /api/whatsapp/conversations   — listar chats (con filtros)
- GET  /api/whatsapp/conversations/{id}/messages — historial de un chat
- PATCH /api/whatsapp/conversations/{id}/read   — marcar como leido

Webhook no usa JWT — se verifica con verify_token (query param) en GET y
firma HMAC-SHA256 del body (header X-Hub-Signature-256) en POST.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import psycopg2
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from psycopg2.extras import RealDictCursor, Json
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user, require_admin
from app.auth.permissions import can_view_all_data
from app.auth.schemas import TokenData
from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

META_GRAPH_BASE = "https://graph.facebook.com/v20.0"

# ─────────────────────────────────────────────────────────────────────────────
# IA mode (auto vs manual) — extraido a app.services.wa_ia_mode_service
# ─────────────────────────────────────────────────────────────────────────────
# V070.70 (Bundle C): la logica del cache + persistencia vive en el modulo
# de service. Mantenemos los wrappers privados aqui para que el resto del
# router siga llamandolos como antes (cero refactor de callers internos).
from app.services.wa_ia_mode_service import (
    DEFAULT_IA_MODE as _DEFAULT_IA_MODE,
    IA_MODE_KEY as _IA_MODE_KEY,
    VALID_IA_MODES as _VALID_IA_MODES,
    invalidate_ia_mode_cache as _invalidate_ia_mode_cache,
    load_ia_mode as _load_ia_mode,
)


# ─────────────────────────────────────────────────────────────────────────────
# Schemas (entrada de /send)
# ─────────────────────────────────────────────────────────────────────────────

class SendTextPayload(BaseModel):
    to: str = Field(..., description="Telefono destino en E164 sin '+' (ej: 51987654321)")
    text: str = Field(..., min_length=1, max_length=4096)
    wa_number_id: Optional[int] = Field(
        None,
        description="ID de la linea propia desde la que enviar. "
                    "Si no se especifica, se infiere del conversation o se usa la default.",
    )


class SendTemplatePayload(BaseModel):
    to: str
    template_name: str
    language: str = "es"
    components: Optional[list] = None
    wa_number_id: Optional[int] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — Meta Cloud API
# ─────────────────────────────────────────────────────────────────────────────

# V070.71 (Bundle C.2): los helpers de Meta API estan en
# app.services.wa_meta_api_service. Mantenemos wrappers privados aqui
# para que los callers internos del router no cambien (Strangler Pattern).
from app.services.wa_meta_api_service import (
    meta_headers as _meta_headers,
    meta_send_url as _meta_send_url,
    resolve_access_token as _resolve_access_token,
    resolve_sending_number as _resolve_sending_number,
)


def _signature_matches(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """V070.70 (Bundle C): delega a app.services.wa_security_service.

    Mantenemos el wrapper privado por compat con codigo y tests existentes
    que importan `_signature_matches` desde este modulo. La logica real
    vive en wa_security_service.verify_signature() — facilita testeo
    aislado de la barrera de seguridad y la hace reutilizable.
    """
    from app.services.wa_security_service import verify_signature
    return verify_signature(raw_body, signature_header, secret)


def _find_verifying_baba(
    raw_body: bytes,
    signature_header: Optional[str],
) -> tuple[bool, Optional[dict]]:
    """Busca cual WABA activa firmo este webhook (multi-WABA).

    Retorna (valido, baba_dict). baba_dict puede ser None si se acepto por
    fallback legacy (env var sin WABAs registradas).

    Estrategia:
      1. Si no hay WABAs registradas: usa env META_WA_APP_SECRET (legacy).
      2. Si hay WABAs, prueba la firma contra el app_secret de cada una.
      3. Si ninguna WABA matchea pero el env tiene app_secret, prueba ese
         como ultimo recurso (durante migracion).
    """
    from app.services import wa_babas_service

    if not signature_header or not signature_header.startswith("sha256="):
        # Sin firma: solo aceptamos si ninguna WABA tiene app_secret
        # configurado (modo dev inicial). Con cualquier WABA con app_secret
        # la firma se vuelve obligatoria.
        babas = wa_babas_service.list_all(only_active=True)
        any_has_secret = any(b.get("has_app_secret") for b in babas)
        env_secret = settings.meta_wa_app_secret
        if not any_has_secret and not env_secret:
            logger.warning(
                "wa webhook: request sin firma aceptado (no hay app_secret configurado)"
            )
            return True, None
        logger.warning("wa webhook: request sin firma y hay app_secret configurado — rechazado")
        return False, None

    # 1) Intentar con todas las WABAs activas
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM crm.wa_babas WHERE activo = TRUE"
            )
            rows = cur.fetchall()

    for row in rows:
        app_secret_ct = row["app_secret_encrypted"] or ""
        if not app_secret_ct:
            continue
        from app.services.secrets_service import decrypt as _dec
        secret = _dec(app_secret_ct)
        if not secret:
            continue
        if _signature_matches(raw_body, signature_header, secret):
            return True, wa_babas_service._row_to_cache_dict(row)

    # 2) Fallback legacy: env var META_WA_APP_SECRET
    env_secret = settings.meta_wa_app_secret
    if env_secret and _signature_matches(raw_body, signature_header, env_secret):
        logger.warning(
            "wa webhook: firma verificada con env META_WA_APP_SECRET (legacy). "
            "Considera registrar una WABA y mover el secreto a DB."
        )
        return True, None

    return False, None


def _audit_webhook_event(
    cur,
    *,
    event_type: str,
    outcome: str,
    wa_phone: Optional[str] = None,
    wamid: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    display_phone_number: Optional[str] = None,
    contact_name: Optional[str] = None,
    has_referral: bool = False,
    referral_ad_id: Optional[str] = None,
    referral_headline: Optional[str] = None,
    referral_source_type: Optional[str] = None,
    lead_id: Optional[int] = None,
    conversation_id: Optional[int] = None,
    error_detail: Optional[str] = None,
    metadata: Optional[dict] = None,
    payload: Optional[dict] = None,
) -> None:
    """Registra de manera continua y a prueba de fallos un evento de webhook en crm.wa_webhook_events.

    Usa SAVEPOINT para garantizar que un fallo en auditoria jamas rompa la transaccion
    principal ni afecte el flujo critico de recepcion de mensajes.
    """
    try:
        cur.execute("SAVEPOINT wa_audit_sp")
        cur.execute(
            """
            INSERT INTO crm.wa_webhook_events (
                event_type, outcome, wa_phone, wamid,
                phone_number_id, display_phone_number, contact_name,
                has_referral, referral_ad_id, referral_headline, referral_source_type,
                lead_id, conversation_id, error_detail, metadata, payload
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                event_type,
                outcome,
                wa_phone,
                wamid,
                phone_number_id,
                display_phone_number,
                contact_name,
                has_referral,
                referral_ad_id,
                referral_headline,
                referral_source_type,
                lead_id,
                conversation_id,
                error_detail,
                Json(metadata) if metadata is not None else None,
                Json(payload) if payload is not None else None,
            ),
        )
        cur.execute("RELEASE SAVEPOINT wa_audit_sp")
    except Exception as exc:  # noqa: BLE001
        try:
            cur.execute("ROLLBACK TO SAVEPOINT wa_audit_sp")
        except Exception:
            pass
        logger.warning("Fallo al registrar evento de auditoria continua de WhatsApp: %s", exc)


def _get_or_create_conversation(
    cur,
    wa_phone: str,
    contact_name: Optional[str],
    wa_number_id: Optional[int] = None,
) -> int:
    """V070.71 (Bundle C.3): delega a wa_conversation_service."""
    from app.services.wa_conversation_service import get_or_create_conversation
    return get_or_create_conversation(cur, wa_phone, contact_name, wa_number_id)


# V070.71 (Bundle C.3): los estados terminales y la logica de liberacion
# viven en app.services.wa_conversation_service. Re-export para
# compatibilidad con codigo y tests que referencian estos simbolos.
from app.services.wa_conversation_service import (
    TERMINAL_LEAD_STATES as _TERMINAL_LEAD_STATES,
    release_lead_if_terminal as _release_lead_if_terminal,
)


def _create_lead_from_ctwa(
    cur,
    wa_phone: str,
    contact_name: Optional[str],
    referral: dict,
) -> Optional[dict]:
    """Crea un lead nuevo cuando llega un referral CTWA y no hay match de telefono.

    El click en un anuncio Click-to-WhatsApp es senal fuerte de intencion: si
    no existe un lead activo asociado al telefono, lo creamos al toque y le
    aplicamos la rotacion estandar de supervisores. Asi el chat aparece en
    la lista de Leads desde el primer mensaje, sin esperar al clasificador IA.

    Devuelve el dict de `ingest_lead_core` (incluye id, asesor_id, supervisor_id,
    duplicated, nombres, apellidos) o None si la ingesta fallo (telefono
    invalido, sin supervisores, etc.) — en ese caso seguimos el flujo normal
    sin lead.
    """
    if not wa_phone or not referral:
        return None

    from app.services.integrations.ingest_core import (
        IngestError,
        IngestPayload,
        ingest_lead_core,
    )

    headline = (referral.get("headline") or "").strip() or None
    nombre_full = (contact_name or "Lead WhatsApp").strip()
    parts = nombre_full.split(" ", 1)
    nombres = parts[0] or "Lead"
    apellidos = parts[1] if len(parts) > 1 else None

    obs_lines = ["Lead creado automaticamente desde Click-to-WhatsApp Ad."]
    if headline:
        obs_lines.append(f"Anuncio: {headline}")
    if referral.get("source_id"):
        obs_lines.append(f"ad_id: {referral['source_id']}")

    payload = IngestPayload(
        fuente="whatsapp",
        telefono=wa_phone,
        nombres=nombres,
        apellidos=apellidos,
        campana=headline,
        observaciones="\n".join(obs_lines),
    )
    # ingest_lead_core hace dict-access en sus rows -> necesita RealDictCursor.
    # Compartimos la misma conexion (misma transaccion) para que un rollback
    # del webhook tambien borre el lead recien creado si algo falla despues.
    # V070.69 (Bundle A — P1-3): enmascarar telefono en logs.
    # Ley 29733 PE exige minimizacion del dato. Antes el telefono completo
    # del cliente final viajaba a Sentry como breadcrumb. Ahora solo los
    # ultimos 4 digitos — suficiente para correlacionar incidentes sin
    # filtrar PII.
    from app.pii_utils import mask_phone
    phone_masked = mask_phone(wa_phone)
    try:
        with cur.connection.cursor(cursor_factory=RealDictCursor) as rdc:
            result = ingest_lead_core(rdc, payload)
    except IngestError as exc:
        logger.warning(
            "CTWA auto-create lead skipped (phone=%s headline=%r): %s",
            phone_masked, headline, exc.detail,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception("CTWA auto-create lead falló (phone=%s): %s", phone_masked, exc)
        return None

    # Log explicito del outcome: id del lead, supervisor asignado y duplicacion.
    # Imprescindible para diagnosticar "el lead no aparece en mi vista" — la
    # asignacion va al supervisor, no al asesor logueado.
    logger.info(
        "CTWA auto-create lead OK: id=%s phone=%s duplicated=%s asesor_id=%s "
        "headline=%r",
        result.get("id"), phone_masked, result.get("duplicated"),
        result.get("asesor_id"), headline,
    )
    return result


def _handle_referral(cur, lead_id: Optional[int], referral: dict) -> Optional[str]:
    """Guarda atribucion de campana en crm.leads si viene referral del CTWA.

    Devuelve el `ad_id` (source_id) si el referral trajo uno — el caller lo
    usa para encolar el enrichment de jerarquia Meta en background. None si
    no hubo ad_id o el referral estaba vacio.
    """
    if not lead_id or not referral:
        return None
    ad_id     = referral.get("source_id")
    headline  = referral.get("headline")
    ctwa_clid = referral.get("ctwa_clid")

    ad_id_str = str(ad_id).strip() if ad_id else None
    ctwa_clid_str = str(ctwa_clid).strip() if ctwa_clid else None

    # Busca o crea campaña por ad_id
    campaign_id = None
    if ad_id_str:
        # ON CONFLICT (ad_id) DO UPDATE permite usar RETURNING incluso cuando
        # la fila ya existia — sin esto, el INSERT no devuelve id en colision
        # y obliga a un SELECT extra. Apoyado por el UNIQUE parcial
        # uq_wa_campaigns_ad_id (V033).
        cur.execute(
            """
            INSERT INTO crm.wa_campaigns (name, platform, ad_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (ad_id) WHERE ad_id IS NOT NULL
            DO UPDATE SET ad_id = EXCLUDED.ad_id
            RETURNING id
            """,
            (headline or f"Ad {ad_id_str}", "facebook", ad_id_str),
        )
        row = cur.fetchone()
        campaign_id = row[0] if row else None

    cur.execute(
        """
        UPDATE crm.leads SET
            wa_campaign_id       = COALESCE(wa_campaign_id, %s),
            wa_campaign_ad_id    = COALESCE(wa_campaign_ad_id, %s),
            wa_campaign_headline = COALESCE(wa_campaign_headline, %s),
            wa_ctwa_clid         = COALESCE(wa_ctwa_clid, %s),
            wa_referral_payload  = COALESCE(wa_referral_payload, %s)
        WHERE id = %s
        """,
        (campaign_id, ad_id_str, headline, ctwa_clid_str, Json(referral), lead_id),
    )
    return ad_id_str or None


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK — verificacion (GET)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/webhook")
def webhook_verify(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta llama esto una sola vez al registrar el webhook.

    Debe responder el challenge en plain text si el verify_token coincide.
    Busca primero entre los verify_token de todas las WABAs registradas
    (multi-WABA V034); fallback a env var por compatibilidad con la
    instalacion previa a la migracion.
    """
    from app.services import wa_babas_service
    if mode != "subscribe" or not challenge or not token:
        raise HTTPException(403, "Parametros de verificacion incompletos")

    # 1) Buscar en WABAs registradas (multi-WABA)
    baba = wa_babas_service.find_baba_by_verify_token(token)
    if baba:
        logger.info(
            "WhatsApp webhook verificado contra WABA id=%s (%s)",
            baba["id"], baba.get("display_name"),
        )
        return PlainTextResponse(challenge)

    # 2) Fallback env (legacy, pre-V034)
    env_token = settings.meta_wa_webhook_verify_token
    if env_token and hmac.compare_digest(env_token, token):
        logger.info("WhatsApp webhook verificado contra env (legacy)")
        return PlainTextResponse(challenge)

    logger.warning("WhatsApp webhook verify fallido — token no coincide en ninguna WABA")
    raise HTTPException(403, "Verify token invalido")


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK — eventos (POST)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def webhook_receive(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
):
    """Recibe eventos de Meta: mensajes entrantes, status updates, referrals.

    Formato del body:
    {
      "entry": [{
        "changes": [{
          "value": {
            "messages": [...],     -- mensajes entrantes
            "statuses": [...],     -- delivery/read receipts
            "contacts": [...]
          }
        }]
      }]
    }

    Tras persistir, encola clasificacion IA (background) para cada
    conversacion cuyo primer mensaje acabe de llegar (status='pending'
    en la BD). La clasificacion es fire-and-forget: el webhook responde
    200 a Meta inmediatamente para no bloquear su queue.
    """
    raw = await request.body()
    valid, verifying_baba = _find_verifying_baba(raw, x_hub_signature_256)
    if not valid:
        # V070.72 — SLO-4: contabilizamos rechazos por firma invalida.
        from app.metrics import wa_webhook_processed
        wa_webhook_processed.labels(status="invalid_signature").inc()
        logger.warning("Firma de webhook invalida — no matchea ninguna WABA")
        raise HTTPException(403, "Firma invalida")

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        from app.metrics import wa_webhook_processed
        wa_webhook_processed.labels(status="parse_error").inc()
        raise HTTPException(400, "Body no es JSON valido")

    # Modo IA leido UNA vez por webhook — afecta si encolamos clasificacion
    ia_mode = _load_ia_mode()

    conv_ids_to_classify: list[int] = []
    msg_ids_to_scan: list[int] = []
    ctwa_ad_ids_to_enrich: list[str] = []
    ctwa_lead_notifs: list[dict] = []
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                for entry in data.get("entry", []):
                    for change in entry.get("changes", []):
                        value = change.get("value", {}) or {}
                        conv_ids, msg_ids, ctwa_ads, ctwa_notifs = _process_messages(
                            cur, value, ia_mode,
                        )
                        conv_ids_to_classify.extend(conv_ids)
                        msg_ids_to_scan.extend(msg_ids)
                        ctwa_ad_ids_to_enrich.extend(ctwa_ads)
                        ctwa_lead_notifs.extend(ctwa_notifs)
                        _process_statuses(cur, value)
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        from app.metrics import wa_webhook_processed
        wa_webhook_processed.labels(status="persist_error").inc()
        logger.exception("Error procesando webhook WhatsApp: %s", exc)
        try:
            with get_db() as err_conn:
                with err_conn.cursor() as err_cur:
                    _audit_webhook_event(
                        err_cur,
                        event_type="system_error",
                        outcome="webhook_processing_failed",
                        error_detail=str(exc),
                        payload=data,
                    )
                err_conn.commit()
        except Exception:
            pass
        # Respondemos 200 igual para que Meta no reintente infinitamente.
        # El log queda para diagnostico.
    else:
        # V070.72 — SLO-4: contabilizamos exito (procesamiento + persist OK).
        from app.metrics import wa_webhook_processed
        wa_webhook_processed.labels(status="ok").inc()

    # Encolar clasificacion IA (fuera de la transaccion BD).
    # En modo manual la lista viene vacia (CAS no transiciono a 'queued').
    for cid in set(conv_ids_to_classify):
        background_tasks.add_task(_classify_conversation_task, cid)

    # Encolar analisis de phishing por mensaje entrante con texto
    for mid in set(msg_ids_to_scan):
        background_tasks.add_task(_phishing_scan_task, mid)

    # Encolar enrichment de jerarquia Meta (ad/adset/campaign) para CTWA.
    # El helper es idempotente y corta rapido si ya fue enriquecido recientemente.
    for aid in set(ctwa_ad_ids_to_enrich):
        background_tasks.add_task(_enrich_ctwa_task, aid)

    # Push FCM al supervisor por cada lead CTWA recien creado. Lo hacemos en
    # background para no bloquear el 200 al webhook de Meta.
    for notif in ctwa_lead_notifs:
        if notif.get("asesor_id"):
            background_tasks.add_task(
                _ctwa_lead_push_task,
                notif["asesor_id"],
                notif.get("lead_name") or "Nuevo lead WhatsApp",
                notif.get("campaign") or "Click-to-WhatsApp",
            )

    return {"ok": True, "ia_mode": ia_mode}


async def _classify_conversation_task(
    conversation_id: int,
    force_new_lead: bool = False,
) -> None:
    """Wrapper de BackgroundTask: aisla errores del classifier del webhook.

    force_new_lead: cuando la tarea viene de `new_case` (usuario pidio
    explicitamente abrir un caso nuevo), el router debe saltarse el
    phone-dedupe y crear un lead fresco con rotacion — aunque el cliente
    ya tenga leads activos por el mismo telefono.
    """
    try:
        # Import diferido: evita cargar httpx del classifier en el startup.
        from app.services.wa_classifier_service import classify_conversation
        await classify_conversation(conversation_id, force_new_lead=force_new_lead)
    except Exception as exc:  # noqa: BLE001
        logger.exception("BackgroundTask classify conv=%s fallo: %s", conversation_id, exc)


async def _phishing_scan_task(message_id: int) -> None:
    """Wrapper de BackgroundTask: analiza phishing y aisla errores."""
    try:
        from app.services.phishing_detector import analyze_message
        await analyze_message(message_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("BackgroundTask phishing msg=%s fallo: %s", message_id, exc)


def _ctwa_lead_push_task(asesor_id: str, lead_name: str, campaign: str) -> None:
    """BackgroundTask: notifica al supervisor que se creo un lead via CTWA."""
    try:
        from app.services.notification_service import notify_new_lead
        body = f"{lead_name} — {campaign}"
        notify_new_lead(asesor_id, body, campaign)
    except Exception as exc:  # noqa: BLE001
        logger.exception("BackgroundTask ctwa_lead_push asesor=%s fallo: %s", asesor_id, exc)


def _enrich_ctwa_task(ad_id: str) -> None:
    """Wrapper de BackgroundTask: resuelve jerarquia Meta para un ad de CTWA.

    Idempotente. La funcion subyacente lee el ads_access_token de credenciales,
    llama a Graph API una sola vez por ad_id y persiste ad_name/adset_name/
    meta_campaign_name en crm.wa_campaigns. Si ya fue enriquecido en los
    ultimos dias, corta sin hacer I/O.
    """
    try:
        from app.services.integrations import meta_service
        result = meta_service.enrich_wa_campaign_by_ad_id(ad_id)
        if not result.get("ok"):
            logger.info("ctwa_enrich ad=%s reason=%s", ad_id, result.get("reason"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("BackgroundTask ctwa_enrich ad=%s fallo: %s", ad_id, exc)


def _process_messages(
    cur,
    value: dict,
    ia_mode: str = _DEFAULT_IA_MODE,
) -> tuple[list[int], list[int], list[str], list[dict]]:
    """Persiste mensajes entrantes y retorna cuatro listas:
      - conversation_ids a clasificar (IA categorica)
      - message_ids a escanear por phishing
      - ad_ids (CTWA) a enriquecer en background via Graph API
      - notificaciones de leads CTWA recien creados (push FCM)

    Solo se clasifica el PRIMER mensaje de una conversacion (cuando el
    status es 'pending'). Transiciona atomicamente a 'queued' para evitar
    que dos webhooks seguidos disparen dos clasificaciones para el mismo
    chat.

    `ia_mode='manual'` desactiva la transicion CAS pending->queued: el
    chat queda en 'pending' hasta que un supervisor lo reclasifique a mano
    desde el UI.
    """
    to_classify: list[int] = []
    phishing_msg_ids: list[int] = []
    ctwa_ad_ids: list[str] = []
    ctwa_lead_notifs: list[dict] = []
    messages = value.get("messages") or []
    if not messages:
        return to_classify, phishing_msg_ids, ctwa_ad_ids, ctwa_lead_notifs
    contacts = value.get("contacts") or []
    contact_name = None
    if contacts:
        profile = contacts[0].get("profile") or {}
        contact_name = profile.get("name")

    # Multi-numero: identifica cual linea propia recibio este batch
    metadata = value.get("metadata") or {}
    receiving_phone_id = metadata.get("phone_number_id")
    receiving_display  = metadata.get("display_phone_number")
    wa_number_id: Optional[int] = None
    if receiving_phone_id:
        from app.services.wa_numbers_service import get_or_register
        num = get_or_register(receiving_phone_id, receiving_display)
        wa_number_id = num["id"] if num else None

    for m in messages:
        wa_phone = m.get("from")
        wamid    = m.get("id")
        msg_type = m.get("type", "text")
        ts_raw   = m.get("timestamp")
        ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc) if ts_raw else datetime.now(timezone.utc)

        # Extrae contenido segun tipo
        content = None
        if msg_type == "text":
            content = (m.get("text") or {}).get("body")
        elif msg_type == "interactive":
            inter = m.get("interactive") or {}
            if inter.get("type") == "button_reply":
                content = (inter.get("button_reply") or {}).get("title")
            elif inter.get("type") == "list_reply":
                content = (inter.get("list_reply") or {}).get("title")
        elif msg_type in ("image", "audio", "video", "document"):
            caption = (m.get(msg_type) or {}).get("caption")
            content = caption or f"[{msg_type}]"
        elif msg_type == "location":
            content = "[ubicacion]"
        else:
            content = f"[{msg_type}]"

        conv_id = _get_or_create_conversation(cur, wa_phone, contact_name, wa_number_id)

        # Si el caso anterior cerro (Ganado/Perdido/No interesado), liberamos
        # la atadura ANTES de buscar lead — asi la IA reclasifica y rotacion
        # crea un lead nuevo (Opcion 1 de la recomendacion).
        _release_lead_if_terminal(cur, conv_id)

        # Match con lead por telefono — IGNORANDO leads terminales para no
        # re-pegar el caso viejo despues de liberarlo. Solo nos interesa un
        # lead activo y vigente.
        cur.execute(
            """
            SELECT l.id
            FROM crm.leads l
            LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
            WHERE regexp_replace(COALESCE(l.telefono,''), '\\D', '', 'g') = %s
              AND l.activo = TRUE
              AND COALESCE(e.nombre, '') <> ALL(%s)
            ORDER BY l.created_at DESC
            LIMIT 1
            """,
            (wa_phone, list(_TERMINAL_LEAD_STATES)),
        )
        lead_row = cur.fetchone()
        lead_id = lead_row[0] if lead_row else None

        # Atribucion (referral de CTWA)
        referral = m.get("referral")
        has_referral = bool(referral)
        ref_ad_id = str(referral.get("source_id")).strip() if referral and referral.get("source_id") else None
        ref_headline = (referral.get("headline") or "").strip() if referral else None
        ref_source_type = referral.get("source_type") if referral else None
        outcome = "message_received"
        error_detail = None
        audit_metadata: dict[str, Any] = {
            "msg_type": msg_type,
            "ia_mode": ia_mode,
        }

        if referral:
            # V070.73 (Defense-in-depth): Usamos SAVEPOINT para aislar la creacion
            # del lead y atribucion de campaña. Si Meta envia un referral con datos
            # inesperados, el SAVEPOINT previene que la transaccion aborte y garantiza
            # que el mensaje entrante SIEMPRE se guarde en crm.wa_messages.
            try:
                cur.execute("SAVEPOINT ctwa_referral_sp")
                # Fast-path: si el cliente vino haciendo clic en un anuncio y NO
                # tenemos lead matcheado por telefono, lo creamos al toque (con
                # rotacion estandar). El click en CTWA es senal fuerte de intencion
                # — no esperamos al gate de IA para que aparezca en Leads.
                if lead_id is None:
                    created = _create_lead_from_ctwa(cur, wa_phone, contact_name, referral)
                    if created:
                        lead_id = created["id"]
                        is_dup = bool(created.get("duplicated"))
                        outcome = "lead_matched_duplicate" if is_dup else "lead_created"
                        audit_metadata["lead_created"] = True
                        audit_metadata["duplicated"] = is_dup
                        audit_metadata["asesor_id"] = str(created.get("asesor_id") or "")
                        audit_metadata["supervisor_id"] = str(created.get("supervisor_id") or "")
                        if not is_dup:
                            ctwa_lead_notifs.append({
                                "asesor_id": created.get("asesor_id"),
                                "lead_name": (
                                    f"{created.get('nombres','')} "
                                    f"{created.get('apellidos','') or ''}"
                                ).strip(),
                                "campaign":  (referral.get("headline") or "Click-to-WhatsApp"),
                            })
                    else:
                        outcome = "lead_creation_failed"
                        error_detail = "ingest_lead_core omitio la creacion del lead"
                else:
                    outcome = "lead_matched_existing"
                    audit_metadata["matched_existing_lead_id"] = lead_id

                ctwa_ad_id = _handle_referral(cur, lead_id, referral)
                if ctwa_ad_id:
                    ctwa_ad_ids.append(ctwa_ad_id)
                cur.execute("RELEASE SAVEPOINT ctwa_referral_sp")
            except Exception as exc:  # noqa: BLE001
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT ctwa_referral_sp")
                except Exception:
                    pass
                outcome = "referral_error"
                error_detail = str(exc)
                logger.exception("Error procesando referral de CTWA (phone=%s): %s", wa_phone, exc)
        else:
            if lead_id is not None:
                outcome = "message_lead_matched"
                audit_metadata["matched_existing_lead_id"] = lead_id
            else:
                outcome = "message_organic_no_lead"

        # Proactive enrichment: si el lead ya está atribuido a un ad CTWA pero
        # la wa_campaign sigue sin meta_ad_name (enrichment pendiente o falló
        # con `no_token` en el primer intento), re-encolamos enrichment. Meta
        # solo manda `referral` en el PRIMER mensaje tras el clic, así que sin
        # esta red de seguridad la campaña se queda con el headline crudo
        # ("NewCompany") para siempre.
        if lead_id:
            cur.execute(
                """
                SELECT l.wa_campaign_ad_id
                  FROM crm.leads l
                  LEFT JOIN crm.wa_campaigns cam ON cam.id = l.wa_campaign_id
                 WHERE l.id = %s
                   AND l.wa_campaign_ad_id IS NOT NULL
                   AND cam.ad_name IS NULL
                """,
                (lead_id,),
            )
            stale = cur.fetchone()
            if stale and stale[0]:
                ctwa_ad_ids.append(stale[0])

        # Persiste mensaje. RETURNING id nos da el PK solo si se inserto
        # (con ON CONFLICT DO NOTHING, duplicados no retornan fila).
        cur.execute(
            """
            INSERT INTO crm.wa_messages
                (conversation_id, wa_message_id, direction, msg_type, content,
                 payload, status, timestamp, wa_number_id)
            VALUES (%s, %s, 'inbound', %s, %s, %s, 'received', %s, %s)
            ON CONFLICT (wa_message_id) DO NOTHING
            RETURNING id
            """,
            (conv_id, wamid, msg_type, content, Json(m), ts, wa_number_id),
        )
        inserted = cur.fetchone()
        if not inserted:
            outcome = "duplicate_message"
            audit_metadata["duplicate_wamid"] = wamid
        elif content and content.strip():
            # Solo analizamos phishing si hay texto real (no media sin caption)
            phishing_msg_ids.append(inserted[0])

        # Actualiza conversacion (ventana 24h + preview).
        # RETURNING nos da asesor_id y nuevo unread_count para decidir si
        # mandar push: solo notificamos en el "primer" mensaje del burst
        # (unread=1 post-update) para no spamear con cada respuesta seguida.
        # V070 — Herencia del asesor desde el lead cuando la conv aun no
        # tiene uno. Bug previo: el chat mostraba "Sin asignar" aunque el
        # lead vinculado tuviera asesor (ej. Fabiola Gamero). Inconsistente
        # con la lista de Leads, que sí mostraba el asesor del lead.
        #
        # Fix: en el mismo UPDATE que setea lead_id, copiamos el asesor del
        # lead a la conv si la conv no tiene asesor todavia. Usa subselect
        # para evitar otro round-trip a la DB.
        cur.execute(
            """
            UPDATE crm.wa_conversations c SET
                last_message_at      = %s,
                last_message_preview = LEFT(COALESCE(%s,''), 200),
                unread_count         = unread_count + 1,
                window_expires_at    = %s + INTERVAL '24 hours',
                lead_id              = COALESCE(c.lead_id, %s),
                asesor_id            = COALESCE(
                    c.asesor_id,
                    (SELECT l.asesor_id FROM crm.leads l
                      WHERE l.id = COALESCE(c.lead_id, %s)
                      LIMIT 1)
                )
            WHERE c.id = %s
            RETURNING c.asesor_id::text, c.unread_count, c.contact_name, c.wa_phone
            """,
            (ts, content, ts, lead_id, lead_id, conv_id),
        )
        conv_state = cur.fetchone()
        if (
            conv_state
            and conv_state[0]                  # tiene asesor asignado
            and (conv_state[1] or 0) == 1       # primer msg del burst
            and inserted                        # no era duplicado
            and content                         # tiene texto (no media sin caption)
        ):
            try:
                from app.services.notification_service import notify_wa_message_inbound
                notify_wa_message_inbound(
                    asesor_id=conv_state[0],
                    contact_name=conv_state[2] or "Cliente",
                    message_preview=content,
                    wa_phone=conv_state[3] or "",
                    conversation_id=conv_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify_wa_message_inbound fallo conv=%s: %s", conv_id, exc)

        # CAS atomico: si el status es 'pending' y NO hay lead_id, marcamos
        # 'queued' y agendamos clasificacion IA. Si ya es queued/classified
        # /skipped/archived, nada: el UPDATE no retorna filas y no encolamos.
        #
        # Esto garantiza "solo el primer mensaje dispara clasificacion"
        # sin race conditions cuando llegan mensajes seguidos.
        #
        # En modo 'manual' saltamos esto: el chat se queda en 'pending'
        # esperando trigger humano.
        if ia_mode == "auto":
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET classification_status = 'queued'
                WHERE id = %s
                  AND classification_status = 'pending'
                  AND lead_id IS NULL
                RETURNING id
                """,
                (conv_id,),
            )
            if cur.fetchone():
                to_classify.append(conv_id)

        # Auditoría continua en crm.wa_webhook_events
        _audit_webhook_event(
            cur,
            event_type="inbound_message",
            outcome=outcome,
            wa_phone=wa_phone,
            wamid=wamid,
            phone_number_id=receiving_phone_id,
            display_phone_number=receiving_display,
            contact_name=contact_name,
            has_referral=has_referral,
            referral_ad_id=ref_ad_id,
            referral_headline=ref_headline,
            referral_source_type=ref_source_type,
            lead_id=lead_id,
            conversation_id=conv_id,
            error_detail=error_detail,
            metadata=audit_metadata,
            payload=m,
        )
    return to_classify, phishing_msg_ids, ctwa_ad_ids, ctwa_lead_notifs


def _process_statuses(cur, value: dict) -> None:
    metadata = value.get("metadata") or {}
    receiving_phone_id = metadata.get("phone_number_id")
    receiving_display  = metadata.get("display_phone_number")
    statuses = value.get("statuses") or []
    for s in statuses:
        wamid = s.get("id")
        status = s.get("status")  # sent | delivered | read | failed
        recipient_id = s.get("recipient_id")
        if not wamid or not status:
            continue
        # Para failed, Meta envia errors=[{code, title, message, error_data:{details}}].
        # Concatenamos title + message + details en error_detail para que el
        # asesor vea el motivo completo en el chat sin tener que ir a logs.
        err_code = None
        err_detail = None
        errors = s.get("errors") or []
        if errors:
            e0 = errors[0]
            err_code = e0.get("code")
            parts = []
            if e0.get("title"):
                parts.append(e0["title"])
            if e0.get("message") and e0["message"] != e0.get("title"):
                parts.append(e0["message"])
            details = (e0.get("error_data") or {}).get("details")
            if details and details not in parts:
                parts.append(details)
            err_detail = " — ".join(parts) if parts else None

        cur.execute(
            """
            UPDATE crm.wa_messages
            SET status = %s,
                error_code = %s,
                error_detail = %s
            WHERE wa_message_id = %s
            RETURNING conversation_id
            """,
            (status, err_code, err_detail, wamid),
        )
        row = cur.fetchone()
        conv_id = row[0] if row else None

        _audit_webhook_event(
            cur,
            event_type="status_update",
            outcome=f"status_{status}",
            wamid=wamid,
            wa_phone=recipient_id,
            phone_number_id=receiving_phone_id,
            display_phone_number=receiving_display,
            conversation_id=conv_id,
            error_detail=err_detail,
            metadata={"error_code": err_code, "status": status},
            payload=s,
        )


# ─────────────────────────────────────────────────────────────────────────────
# SEND — enviar mensaje saliente
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATES — listar + enviar plantillas aprobadas (fuera de ventana 24h)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates(
    current_user: TokenData = Depends(get_current_user),
    wa_number_id: Optional[int] = None,
):
    """Lista las plantillas aprobadas en Meta para una WABA.

    Endpoint Meta: GET /{waba_id}/message_templates
    Filtra por status=APPROVED (las pending/rejected no se pueden enviar).

    Devuelve estructura simplificada para la UI:
      [{
        id: str,
        name: str,
        language: str,
        category: str,         # MARKETING | UTILITY | AUTHENTICATION
        status: "APPROVED",
        body: str,             # texto del componente "BODY"
      }]

    Si la cuenta no tiene templates aprobadas, devuelve lista vacia (no 404)
    junto con un campo "meta" para que la UI explique por que (WABA no
    registrada / Meta API fallo / templates pero ninguno aprobado).
    """
    from app.services import wa_babas_service

    # Resolver WABA en este orden:
    #   1) wa_number_id local → JOIN para encontrar la WABA del numero usado
    #      por la conversacion. Asi templates respeta multi-WABA.
    #   2) WABA default activa.
    # Nota: el bug previo pasaba str(wa_number_id) a get_baba_for_phone, que
    # busca por phone_number_id de Meta (string largo). Como wa_number_id es
    # un id local pequenio, nunca matcheaba y devolvia siempre vacio.
    baba = None
    if wa_number_id:
        baba = wa_babas_service.get_baba_by_wa_number_id(wa_number_id)
    if not baba:
        baba = wa_babas_service.get_default_baba()

    if not baba or not baba.get("waba_id"):
        logger.info("templates: sin WABA registrada con waba_id (wa_number_id=%s)", wa_number_id)
        return {
            "templates": [],
            "meta": {
                "reason": "no_waba",
                "message": "No hay ninguna WABA registrada en el CRM. Configurala en Configuracion > WhatsApp > Cuentas Empresariales.",
            },
        }

    waba_id = baba["waba_id"]
    token = wa_babas_service.get_access_token(baba)
    if not token:
        token = settings.meta_wa_access_token
    if not token:
        raise HTTPException(500, "Sin access_token para listar templates.")

    url = f"{META_GRAPH_BASE}/{waba_id}/message_templates"
    params = {"limit": 100, "fields": "id,name,language,category,status,components"}
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.get(url, params=params, headers=headers)
            if r.status_code >= 400:
                err_text = r.text[:300]
                logger.warning("Meta templates fetch %d (waba=%s): %s", r.status_code, waba_id, err_text)
                return {
                    "templates": [],
                    "meta": {
                        "reason": "meta_error",
                        "status_code": r.status_code,
                        "waba_id": waba_id,
                        "message": (
                            f"Meta rechazo la consulta de plantillas ({r.status_code}). "
                            "Verifica que el access_token tenga el permiso "
                            "'whatsapp_business_management' y que la WABA registrada "
                            "sea donde aprobaste las plantillas."
                        ),
                        "detail": err_text,
                    },
                }
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Meta templates fetch error (waba=%s): %s", waba_id, exc)
        return {
            "templates": [],
            "meta": {
                "reason": "network_error",
                "waba_id": waba_id,
                "message": f"Error de red consultando Meta: {exc}",
            },
        }

    # Templates que Meta auto-crea en cada WABA pero no se pueden enviar desde
    # numeros de produccion (solo desde Public Test Numbers de sandbox). Se
    # filtran porque no son borrables y solo confunden a los asesores —
    # apareceria en el modal pero el envio fallaria con error 131058 de Meta.
    DEMO_TEMPLATE_NAMES = {"hello_world"}

    items = data.get("data") or []
    out = []
    status_breakdown: dict[str, int] = {}
    skipped_demo = 0
    for it in items:
        status = (it.get("status") or "").upper()
        status_breakdown[status] = status_breakdown.get(status, 0) + 1
        if status != "APPROVED":
            continue
        name = it.get("name") or ""
        if name in DEMO_TEMPLATE_NAMES:
            skipped_demo += 1
            continue
        # Extraer body text del componente "BODY"
        body_text = ""
        for comp in (it.get("components") or []):
            if (comp.get("type") or "").upper() == "BODY":
                body_text = comp.get("text") or ""
                break
        out.append({
            "id":       it.get("id"),
            "name":     name,
            "language": it.get("language") or "es",
            "category": it.get("category") or "UTILITY",
            "status":   it.get("status") or "APPROVED",
            "body":     body_text,
        })

    logger.info(
        "templates: waba=%s total=%d approved=%d skipped_demo=%d breakdown=%s",
        waba_id, len(items), len(out), skipped_demo, status_breakdown,
    )

    response: dict = {"templates": out}
    if not out:
        # Diagnostico cuando la WABA respondio pero no hay APPROVED enviables.
        if skipped_demo > 0 and not items_with_other_statuses(status_breakdown, skipped_demo):
            # Solo habia templates demo aprobados (hello_world). El asesor
            # creyo que estaba todo bien pero no hay nada enviable.
            response["meta"] = {
                "reason": "only_demo",
                "waba_id": waba_id,
                "skipped_demo": skipped_demo,
                "message": (
                    "Solo hay plantillas de demostracion (como hello_world) que Meta "
                    "no permite enviar desde numeros de produccion. Crea tus propias "
                    "plantillas desde Business Manager > WhatsApp Manager > Plantillas, "
                    "espera la aprobacion y apareceran aqui."
                ),
            }
        elif items:
            response["meta"] = {
                "reason": "none_approved",
                "waba_id": waba_id,
                "total_received": len(items),
                "skipped_demo": skipped_demo,
                "status_breakdown": status_breakdown,
                "message": (
                    f"Meta devolvio {len(items)} plantilla(s) pero ninguna apta para envio. "
                    f"Status encontrados: {status_breakdown}. Espera a que Meta apruebe o "
                    f"revisa que esten en la WABA correcta."
                ),
            }
        else:
            response["meta"] = {
                "reason": "empty_waba",
                "waba_id": waba_id,
                "message": (
                    f"La WABA {waba_id} no tiene plantillas creadas. Crealas desde "
                    "Business Manager > WhatsApp Manager > Plantillas."
                ),
            }
    elif skipped_demo > 0:
        # Habia templates enviables Y demos. Informa que se ocultaron sin
        # bloquear la lista — el usuario ya puede usar las suyas.
        response["meta"] = {
            "reason": "demo_filtered",
            "waba_id": waba_id,
            "skipped_demo": skipped_demo,
        }
    return response


def items_with_other_statuses(breakdown: dict[str, int], skipped_demo: int) -> bool:
    """Devuelve True si en el breakdown hay status ademas de APPROVED, o si
    hay APPROVED no demo. Sirve para distinguir "solo hay demo aprobado" de
    "hay otros pendientes/rejected ademas".
    """
    approved = breakdown.get("APPROVED", 0)
    others = sum(v for k, v in breakdown.items() if k != "APPROVED")
    # Si APPROVED > skipped_demo, hay aprobados no-demo (caso ya cubierto antes).
    # Si others > 0, hay pendientes/rejected ademas — vale la pena mencionarlo.
    return others > 0 or approved > skipped_demo


@router.post("/send/template")
async def send_template(
    payload: SendTemplatePayload,
    current_user: TokenData = Depends(get_current_user),
):
    """Envia un template aprobado. Funciona DENTRO y fuera de ventana 24h.

    Acepta `components` con parametros si el template los tiene:
      [{"type":"body","parameters":[{"type":"text","text":"Juan"}]}]
    """
    if not payload.to or not payload.template_name:
        raise HTTPException(400, "Faltan campos: to y template_name son requeridos.")

    # Resolver el numero de envio igual que /send (texto libre): el frontend
    # manda wa_number_id como id local de crm.wa_numbers, y necesitamos
    # traducirlo al phone_number_id de Meta antes de armar la URL. Antes
    # esto pasaba el id local como si fuera el phone_number_id y Meta
    # respondia "Object with ID '1' does not exist".
    advisor_default = None
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT default_wa_number_id FROM auth.users WHERE id = %s",
                (current_user.user_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                advisor_default = row[0]

    wa_number_id, phone_number_id = _resolve_sending_number(
        payload.wa_number_id, payload.to, advisor_default_wa_number_id=advisor_default,
    )

    body = {
        "messaging_product": "whatsapp",
        "to":   payload.to,
        "type": "template",
        "template": {
            "name":     payload.template_name,
            "language": {"code": payload.language or "es"},
        },
    }
    if payload.components:
        body["template"]["components"] = payload.components

    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                _meta_send_url(phone_number_id),
                headers=_meta_headers(phone_number_id),
                json=body,
            )
            if r.status_code >= 400:
                detail = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300]
                logger.warning("Meta send/template %d: %s", r.status_code, detail)
                raise HTTPException(
                    status_code=400,
                    detail=f"Meta rechazo el template: {detail}",
                )
            response = r.json()
    except httpx.HTTPError as exc:
        logger.exception("Meta send/template HTTP error")
        raise HTTPException(502, f"Error de red enviando template: {exc}") from exc

    # Persistir el outbound como mensaje en la conv (para que aparezca en el feed).
    # Best-effort — si no hay conv todavia, no rompe.
    wa_message_id = (response.get("messages") or [{}])[0].get("id")
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM crm.wa_conversations WHERE wa_phone = %s LIMIT 1",
                    (payload.to,),
                )
                row = cur.fetchone()
                conv_id = row[0] if row else None
                if conv_id:
                    cur.execute(
                        """
                        INSERT INTO crm.wa_messages
                            (conversation_id, wa_message_id, direction, msg_type,
                             content, payload, status, timestamp, wa_number_id)
                        VALUES (%s, %s, 'outbound', 'template', %s, %s, 'sent', NOW(),
                                %s)
                        ON CONFLICT (wa_message_id) DO NOTHING
                        """,
                        (
                            conv_id, wa_message_id,
                            f"[Template: {payload.template_name}]",
                            Json(body),
                            wa_number_id,
                        ),
                    )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("send/template persistencia mensaje fallo: %s", exc)

    return {
        "ok":            True,
        "wa_message_id": wa_message_id,
        "template":      payload.template_name,
        "wa_number_id":  wa_number_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SEND — texto libre dentro de ventana 24h
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/send")
async def send_text(
    payload: SendTextPayload,
    current_user: TokenData = Depends(get_current_user),
):
    """Envia texto libre. Solo funciona dentro de ventana 24h.

    Fuera de ventana (incluyendo primer contacto sin inbound previo)
    usar /send/template con un template aprobado.

    GUARD CRITICO (V040.7): valida server-side que la ventana 24h este abierta
    antes de mandar a Meta. Sin este guard, una APK con bug podria mandar
    free-form a un numero que nunca escribio → strike de Meta y eventual
    bloqueo de la cuenta de WhatsApp Business.
    """
    # V035: si el asesor tiene linea por defecto asignada, usarla como prioridad
    # cuando no viene payload.wa_number_id explicito ni hay conversacion previa.
    # Tambien chequeamos visibilidad: si ya existe una conv para este telefono,
    # el usuario debe poder verla segun su rol (mismo modelo que list/get).
    advisor_default = None
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT default_wa_number_id FROM auth.users WHERE id = %s",
                (current_user.user_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                advisor_default = row[0]
            cur.execute(
                "SELECT id, window_expires_at FROM crm.wa_conversations WHERE wa_phone = %s LIMIT 1",
                (payload.to,),
            )
            existing = cur.fetchone()
            if existing:
                _assert_conv_visible(cur, existing[0], current_user)
                # Guard de ventana 24h: rechaza con 409 si esta cerrada o nunca
                # se abrio. La APK ya bloquea el input pero defendemos el endpoint
                # como ultima linea (defense in depth).
                window_expires_at = existing[1]
                if window_expires_at is None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Primer contacto: este numero nunca te ha escrito. "
                            "Envia un template aprobado primero."
                        ),
                    )
                cur.execute("SELECT NOW() > %s", (window_expires_at,))
                window_closed = cur.fetchone()[0]
                if window_closed:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Ventana 24h cerrada. Envia un template aprobado "
                            "para reabrir la conversacion."
                        ),
                    )
            else:
                # Sin conversacion previa = primer contacto cold = obligatorio template.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Primer contacto: este numero nunca te ha escrito. "
                        "Envia un template aprobado primero."
                    ),
                )

    wa_number_id, phone_number_id = _resolve_sending_number(
        payload.wa_number_id, payload.to, advisor_default_wa_number_id=advisor_default,
    )

    body = {
        "messaging_product": "whatsapp",
        "to": payload.to,
        "type": "text",
        "text": {"body": payload.text},
    }

    async with httpx.AsyncClient(timeout=15.0) as cli:
        r = await cli.post(
            _meta_send_url(phone_number_id),
            headers=_meta_headers(phone_number_id),
            json=body,
        )

    if r.status_code >= 400:
        logger.error("Meta API error: %s %s", r.status_code, r.text)
        raise HTTPException(r.status_code, f"Meta API: {r.text}")

    resp = r.json()
    wamid = ((resp.get("messages") or [{}])[0]).get("id")

    # Persiste outbound
    with get_db() as conn:
        with conn.cursor() as cur:
            conv_id = _get_or_create_conversation(cur, payload.to, None, wa_number_id)
            cur.execute(
                """
                INSERT INTO crm.wa_messages
                    (conversation_id, wa_message_id, direction, msg_type, content,
                     payload, status, sent_by_user_id, wa_number_id)
                VALUES (%s, %s, 'outbound', 'text', %s, %s, 'sent', %s::uuid, %s)
                """,
                (conv_id, wamid, payload.text, Json(body), current_user.user_id, wa_number_id),
            )
            cur.execute(
                """
                UPDATE crm.wa_conversations SET
                    last_message_at      = NOW(),
                    last_message_preview = LEFT(%s, 200)
                WHERE id = %s
                """,
                (payload.text, conv_id),
            )
        conn.commit()

    return {"ok": True, "wa_message_id": wamid, "wa_number_id": wa_number_id}


# ─────────────────────────────────────────────────────────────────────────────
# LISTAR conversaciones
# ─────────────────────────────────────────────────────────────────────────────

# Columnas comunes para la respuesta de conversaciones (listado y fetch unitario).
# Se mantienen en una sola constante para que el shape sea identico y el frontend
# pueda inyectar una conv suelta en la lista sin transformaciones.
_CONV_SELECT_COLUMNS = """
    c.id,
    c.wa_phone,
    c.contact_name,
    c.last_message_at,
    c.last_message_preview,
    c.unread_count,
    c.window_expires_at,
    c.lead_id,
    l.nombres || ' ' || COALESCE(l.apellidos,'') AS lead_name,
    l.wa_campaign_id,
    l.wa_campaign_headline,
    cam.name AS campaign_name,
    cam.ad_name AS meta_ad_name,
    cam.adset_name AS meta_adset_name,
    cam.meta_campaign_name AS meta_campaign_name,
    cam.creative_body AS meta_creative_body,
    cam.creative_title AS meta_creative_title,
    cam.creative_media_type AS meta_creative_media_type,
    (cam.creative_media_cached_at IS NOT NULL) AS meta_creative_thumbnail_ready,
    cam.creative_media_error AS meta_creative_media_error,
    cam.ad_id AS meta_ad_id,
    cam.enriched_at AS meta_enriched_at,
    -- V070.21 — Display fallback robusto en 4 niveles:
    --   1. c.asesor_id (la conv tiene asesor)
    --   2. l.asesor_id (heredado del lead linkeado)
    --   3. phone_match.asesor_id (orphan conv: match por wa_phone vs telefono)
    --   4. uw.id (asesor cuyo default_wa_number_id = c.wa_number_id)
    --
    -- Caso 4 (nuevo): conv huerfana donde el wa_phone del cliente NO matchea
    -- ningun lead (es un contacto que aun no fue creado como lead) PERO el
    -- cliente le escribio al WhatsApp Business de un asesor especifico.
    -- El "dueno" logico de esa conv es ese asesor — sino el InfoTab muestra
    -- "Asesor: —" eternamente aunque Roger Bravo sea quien recibio el mensaje.
    COALESCE(
        c.asesor_id::text,
        l.asesor_id::text,
        phone_match.asesor_id::text,
        uw.id::text
    ) AS asesor_id,
    TRIM(COALESCE(u.first_name, ul.first_name, up.first_name, uw.first_name, '') || ' '
         || COALESCE(u.last_name, ul.last_name, up.last_name, uw.last_name, '')) AS asesor_nombre,
    COALESCE(u.role, ul.role, up.role, uw.role) AS asesor_role,
    c.wa_number_id,
    wn.display_name AS wa_number_name,
    wn.display_phone AS wa_number_phone,
    (SELECT COUNT(*) FROM crm.wa_conversation_leads wcl
     WHERE wcl.conversation_id = c.id) AS cases_count,
    c.classification_status,
    c.classification_category,
    c.classification_confidence,
    c.classification_interest,
    c.classification_urgency,
    c.classification_summary,
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', t.id,
                'nombre', t.nombre,
                'color_hex', t.color_hex
            ) ORDER BY t.orden, t.nombre
        )
        FROM crm.lead_tags lt
        JOIN crm.tags t ON t.id = lt.tag_id
        WHERE lt.lead_id = c.lead_id AND t.activo = TRUE
    ), '[]'::jsonb) AS tags
"""

_CONV_JOIN = """
    FROM crm.wa_conversations c
    LEFT JOIN crm.leads l ON l.id = c.lead_id
    LEFT JOIN crm.wa_campaigns cam ON cam.id = l.wa_campaign_id
    LEFT JOIN auth.users u  ON u.id  = c.asesor_id
    -- V070.8 — Fallbacks SIN condiciones de bloqueo. La version anterior
    -- requeria 'AND c.asesor_id IS NULL' en ul/up. Eso fallaba si
    -- c.asesor_id apuntaba a un user con first_name/last_name vacios o
    -- inconsistentes: u.first_name=NULL → COALESCE no cae a ul/up porque
    -- esos JOINs estaban deshabilitados. Resultado: InfoTab "Asesor: —".
    --
    -- Patron patrón estándar: las queries de display NUNCA dependen de
    -- una sola fuente. Encadenamos JOINs en cascada y dejamos que
    -- COALESCE elija el primer no-NULL — defense in depth real.
    --
    -- Semantica preservada: si c.asesor_id apunta a un user valido, u.* gana
    -- (es la primera opcion en cada COALESCE). Solo si u.* es NULL/vacio
    -- entra ul.* (asesor del lead linkeado) o up.* (asesor por phone match).
    LEFT JOIN auth.users ul ON ul.id = l.asesor_id
    -- LATERAL por phone match para convs HUERFANAS (lead_id NULL). Mantiene
    -- la condicion porque es un scan costoso y solo tiene sentido para
    -- orfanas. El indice idx_leads_telefono_digits acelera a O(log n).
    LEFT JOIN LATERAL (
        -- V070.22 — Match por ULTIMOS 9 DIGITOS (longitud celular Peru sin
        -- codigo pais). Antes comparabamos toda la cadena de digitos, lo
        -- que fallaba en el caso muy comun:
        --   lead.telefono = "924223814"        (9 dig, sin 51)
        --   conv.wa_phone = "51924223814"      (11 dig, Meta siempre manda 51)
        -- Toda la digit-string no matchea, RIGHT(_, 9) si. Mismo patron que
        -- el sync de llamadas en llamadas.py:106-114.
        --
        -- Ademas removemos la restriccion lp.asesor_id IS NOT NULL: si el
        -- lead existe pero sin asesor (carga masiva pendiente de asignar),
        -- igual queremos linkearlo a la conv para que el frontend muestre
        -- el lead aunque el asesor salga vacio en ese nivel.
        SELECT lp.id        AS lead_id,
               lp.asesor_id AS asesor_id
          FROM crm.leads lp
         WHERE c.lead_id IS NULL
           AND lp.activo = TRUE
           AND RIGHT(REGEXP_REPLACE(COALESCE(lp.telefono, ''), '\\D', '', 'g'), 9)
             = RIGHT(REGEXP_REPLACE(COALESCE(c.wa_phone, ''), '\\D', '', 'g'), 9)
           AND LENGTH(REGEXP_REPLACE(COALESCE(lp.telefono, ''), '\\D', '', 'g')) >= 9
         ORDER BY (lp.asesor_id IS NOT NULL) DESC, lp.created_at DESC
         LIMIT 1
    ) phone_match ON TRUE
    LEFT JOIN auth.users up ON up.id = phone_match.asesor_id
    -- V070.21 — Fallback nivel 4: asesor cuyo default_wa_number_id matchea
    -- el wa_number_id de la conv. Solo aplica cuando NO hay un dueno mas
    -- especifico (orden de COALESCE lo garantiza). LATERAL con LIMIT 1 por
    -- si dos asesores comparten default por error de config — toma el activo
    -- mas recientemente creado para ser deterministico.
    LEFT JOIN LATERAL (
        SELECT uw0.id, uw0.first_name, uw0.last_name, uw0.role
          FROM auth.users uw0
         WHERE c.wa_number_id IS NOT NULL
           AND uw0.default_wa_number_id = c.wa_number_id
           AND uw0.is_active = TRUE
         ORDER BY uw0.created_at DESC
         LIMIT 1
    ) uw ON TRUE
    LEFT JOIN crm.wa_numbers wn ON wn.id = c.wa_number_id
"""


def _fetch_conversation_row(cur, conv_id: int) -> Optional[dict]:
    """Trae una conv unica con el mismo shape que el listado."""
    cur.execute(
        f"SELECT {_CONV_SELECT_COLUMNS} {_CONV_JOIN} WHERE c.id = %s",
        (conv_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


_VALID_STATUS_FILTERS = {
    "pending", "queued", "classified", "manual_review", "archived", "failed", "skipped",
}
# Alias para simplificar el UI (no exponemos los 7 estados crudos).
# 'delegar' es especial — no filtra por classification_status, filtra por
# rol del asesor asignado (supervisor = aun por delegar a un asesor del equipo).
_STATUS_FILTER_BUCKETS = {
    "potenciales":    ["classified"],                 # filtrar adicionalmente por categoria abajo
    "revisar":        ["manual_review", "failed"],
    "archivados":     ["archived"],
    "sin_clasificar": ["pending", "queued"],
    "delegar":        [],                             # logica especial — ver list_conversations
}


# ─────────────────────────────────────────────────────────────────────────────
# VISIBILIDAD POR ROL (modelo CRMs profesionales: own → team → all)
# ─────────────────────────────────────────────────────────────────────────────
# Pool compartido entre supervisores: chats aun sin owner que estan en
# alguno de estos estados. Cualquier supervisor puede triarlos; cuando uno
# los toma, dejan de estar en el pool y pasan a su equipo.
_SHARED_POOL_STATUSES = ("pending", "queued", "manual_review", "failed")


def _conversation_visibility_clause(user: TokenData) -> tuple[str, list]:
    """Devuelve (sql, params) para restringir filas de crm.wa_conversations
    (alias `c`) segun el rol del usuario.

    - admin      → todo.
    - asesor     → solo chats asignados a si mismo.
    - supervisor → lead en cola del supervisor (lead.supervisor_id = self,
                   V035) + chats de asesores de su equipo + chats asignados
                   a si mismo (recien clasificados por IA, pre-V035) +
                   pool compartido sin owner en estados de triage.
    """
    if can_view_all_data(user, "chat"):
        return "TRUE", []
    if user.role == "supervisor":
        placeholders = ",".join(["%s"] * len(_SHARED_POOL_STATUSES))
        # Reglas (OR entre si):
        # 1. Chat asignado directamente al supervisor, PERO solo si el lead
        #    no tiene OTRO supervisor dueno (cubre datos sucios legacy donde
        #    conv.asesor_id quedo apuntando a un supervisor obsoleto tras
        #    reasignacion del lead a otro supervisor).
        # 2. Chat de algun asesor del equipo del supervisor.
        # 3. Lead en cola del supervisor (lead.supervisor_id = self
        #    AND lead.asesor_id IS NULL, V041). Antes solo exigia
        #    supervisor_id = self y mostraba a Paola chats que un admin
        #    le habia tomado (asesor_id pasaba a admin pero supervisor_id
        #    seguia historicamente en Paola). La cola es por definicion
        #    "lead sin asesor"; si alguien lo tomo, sale.
        # 4. Pool huerfano: sin asesor, sin supervisor_id en el lead,
        #    en estado de triage — visible a cualquier supervisor.
        # 5. Lead vinculado a la conv que el supervisor puede ver por las
        #    reglas de leads (asesor_id en equipo, sin asesor sin supervisor).
        #    Cubre el caso "lead viene de TikTok/FB, supervisor abre el chat
        #    desde el listado de leads → /conversations/open crea la conv pero
        #    no le hereda asesor_id, y la conv quedaba invisible para el
        #    supervisor aunque el lead si era visible". Es el fix que unifica
        #    visibility entre leads y conversations.
        sql = (
            "("
            "("
            "c.asesor_id = %s::uuid"
            " AND NOT EXISTS ("
            "   SELECT 1 FROM crm.leads l0"
            "   WHERE l0.id = c.lead_id"
            "     AND l0.supervisor_id IS NOT NULL"
            "     AND l0.supervisor_id <> %s::uuid"
            " )"
            ")"
            " OR c.asesor_id IN ("
            "   SELECT asesor_id FROM crm.equipos"
            "   WHERE supervisor_id = %s::uuid AND activo = TRUE"
            " )"
            " OR EXISTS ("
            "   SELECT 1 FROM crm.leads l"
            "   WHERE l.id = c.lead_id"
            "     AND l.supervisor_id = %s::uuid"
            "     AND l.asesor_id IS NULL"
            " )"
            " OR ("
            "   c.asesor_id IS NULL"
            f"   AND c.classification_status IN ({placeholders})"
            "   AND NOT EXISTS ("
            "     SELECT 1 FROM crm.leads l2"
            "     WHERE l2.id = c.lead_id AND l2.supervisor_id IS NOT NULL"
            "   )"
            " )"
            " OR EXISTS ("
            "   SELECT 1 FROM crm.leads l3"
            "   WHERE l3.id = c.lead_id"
            "     AND ("
            "       l3.asesor_id IN ("
            "         SELECT asesor_id FROM crm.equipos"
            "         WHERE supervisor_id = %s::uuid AND activo = TRUE"
            "       )"
            "       OR (l3.asesor_id IS NULL AND l3.supervisor_id IS NULL)"
            "     )"
            " )"
            ")"
        )
        params: list = [
            user.user_id,  # c.asesor_id = self
            user.user_id,  # NOT EXISTS: otro supervisor dueno del lead
            user.user_id,  # crm.equipos
            user.user_id,  # l.supervisor_id = self
            *_SHARED_POOL_STATUSES,
            user.user_id,  # l3 → equipos del supervisor
        ]
        return sql, params
    return "c.asesor_id = %s::uuid", [user.user_id]


def _assert_conv_visible(cur, conversation_id: int, user: TokenData) -> None:
    """Valida que el usuario pueda ver esta conversacion. 403 si no.

    Se usa en endpoints que reciben conversation_id directo para aplicar
    las mismas reglas de visibilidad que list_conversations.
    """
    if can_view_all_data(user, "chat"):
        return
    vis_sql, vis_params = _conversation_visibility_clause(user)
    cur.execute(
        f"SELECT 1 FROM crm.wa_conversations c WHERE c.id = %s AND {vis_sql}",
        [conversation_id, *vis_params],
    )
    if not cur.fetchone():
        raise HTTPException(403, "Sin acceso a esta conversación")


class OpenConversationPayload(BaseModel):
    wa_phone: str           # solo digitos con codigo pais (ej: '51933037149')
    lead_id: Optional[int] = None
    contact_name: Optional[str] = None
    wa_number_id: Optional[int] = None  # linea propia desde la que se abre


@router.post("/conversations/open")
def open_conversation(
    payload: OpenConversationPayload,
    current_user: TokenData = Depends(get_current_user),
):
    """Crea (o reutiliza) la conversacion para ese telefono y la ata al
    lead indicado. Idempotente — si ya existe, solo devuelve el id.

    Usado cuando el asesor quiere iniciar contacto hacia un lead antiguo
    desde el detalle del lead — asi el chat aparece en /chat antes de
    que el cliente responda.

    Nota: no envia nada a Meta. El asesor debe escribir el mensaje en el
    chat y disparar /send, que aplicara las reglas de ventana 24h.
    """
    phone = (payload.wa_phone or "").strip()
    if not phone.isdigit():
        raise HTTPException(400, "wa_phone debe ser solo digitos con codigo de pais")

    # V070.5 — Preflight: sin WABA conectada NO creamos convs huerfanas.
    # Antes de este guard, la conv se creaba con wa_number_id=NULL y luego
    # /send fallaba con 500 dejando al usuario con un chat fantasma en el
    # sidebar imposible de operar. Patron CRMs profesionales: rechazar
    # temprano en el boundary con detalle accionable.
    from app.services import wa_numbers_service
    if not wa_numbers_service.has_sending_capability():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WHATSAPP_NOT_CONFIGURED",
                "message": (
                    "WhatsApp Business no esta configurado. Pide al admin "
                    "que conecte una WABA en Integraciones."
                ),
            },
        )

    # Resolver numero: explicit o default activo
    resolved_wa_number_id: Optional[int] = None
    if payload.wa_number_id:
        resolved_wa_number_id = payload.wa_number_id
    else:
        default_num = wa_numbers_service.get_default()
        if default_num:
            resolved_wa_number_id = default_num["id"]

    with get_db() as conn:
        with conn.cursor() as cur:
            conv_id = _get_or_create_conversation(
                cur, phone, payload.contact_name, resolved_wa_number_id,
            )
            # Si viene lead_id, aseguramos que la conv quede atada a ese lead y
            # que herede su asesor — de lo contrario el filtro por asesor del
            # sidebar esconde la conv recien abierta.
            if payload.lead_id:
                cur.execute(
                    """
                    UPDATE crm.wa_conversations c
                    SET lead_id   = %s,
                        asesor_id = COALESCE(c.asesor_id, l.asesor_id)
                    FROM crm.leads l
                    WHERE c.id = %s
                      AND l.id = %s
                    """,
                    (payload.lead_id, conv_id, payload.lead_id),
                )
                # Registra en el historial de casos (V025). Fail-safe si la
                # tabla aun no existe en la instalacion.
                # V070.94 — SAVEPOINT obligatorio. Antes el except sin rollback
                # dejaba la transaccion en estado "current transaction is
                # aborted" y la UPDATE siguiente (linea 1599) tiraba 500.
                # Reproducido en cliente Palma Rio donde tabla V025 no
                # estaba creada → cualquier asesor abriendo WhatsApp desde
                # un lead recibia 'Error del servidor'.
                cur.execute("SAVEPOINT sp_wa_conv_leads")
                try:
                    cur.execute(
                        """
                        INSERT INTO crm.wa_conversation_leads
                            (conversation_id, lead_id, created_by)
                        VALUES (%s, %s, 'manual_user')
                        ON CONFLICT (conversation_id, lead_id) DO NOTHING
                        """,
                        (conv_id, payload.lead_id),
                    )
                    cur.execute("RELEASE SAVEPOINT sp_wa_conv_leads")
                except Exception as exc:  # noqa: BLE001 — V025 puede no existir
                    cur.execute("ROLLBACK TO SAVEPOINT sp_wa_conv_leads")
                    logger.warning(
                        "wa_conversation_leads INSERT fallido (tabla V025 ausente?): %s",
                        exc,
                    )
            # Fallback: si la conv sigue sin asesor (lead sin asesor, o no hubo
            # lead_id) y quien abre es asesor, la toma el. Admin/supervisor no
            # se auto-asignan — pueden dejarla para que la tome un asesor.
            if current_user.role == "asesor":
                cur.execute(
                    "UPDATE crm.wa_conversations SET asesor_id = %s::uuid "
                    "WHERE id = %s AND asesor_id IS NULL",
                    (current_user.user_id, conv_id),
                )
        conn.commit()

        # Devolvemos la conv completa (mismo shape que el listado) para que el
        # frontend pueda inyectarla sin esperar al proximo poll.
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            conversation = _fetch_conversation_row(cur, conv_id)

    return {"ok": True, "conversation_id": conv_id, "conversation": conversation}


@router.get("/conversations/counts")
def conversation_counts(
    campaign_id: Optional[str] = Query(
        None,
        description="Mismo formato que /conversations: id o lista CSV",
    ),
    wa_number_id: Optional[int] = None,
    tag_id: Optional[int] = None,
    current_user: TokenData = Depends(get_current_user),
):
    """Conteos por bandeja para los chips del sidebar de chats.

    Devuelve los inventarios que veria el usuario al cambiar de bandeja
    respetando los mismos filtros (campaña / linea / etiqueta) y la misma
    visibilidad por rol que /conversations. 'todos' excluye archived/skipped
    igual que el listado por defecto — refleja la bandeja real, no el total
    crudo en BD.

    Una sola query con FILTER para no abrir 6 conexiones por refresh.
    """
    where_parts = ["1=1"]
    params: list = []

    # Delegar (solo supervisor): cuenta unicamente lo que ese supervisor
    # debe pasar a su equipo, no las delegaciones de otros supervisores.
    # El %s aparece DENTRO del SELECT (FILTER), antes que cualquier otro
    # %s — debe ir primero en la lista de params.
    delegar_extra = ""
    if current_user.role == "supervisor":
        delegar_extra = " AND c.asesor_id = %s::uuid"
        params.append(current_user.user_id)

    vis_sql, vis_params = _conversation_visibility_clause(current_user)
    where_parts.append(vis_sql)
    params.extend(vis_params)

    if campaign_id is not None:
        campaign_ids: list[int] = []
        for token in str(campaign_id).split(","):
            token = token.strip()
            if not token:
                continue
            try:
                campaign_ids.append(int(token))
            except ValueError:
                continue
        if campaign_ids:
            where_parts.append("l.wa_campaign_id = ANY(%s::int[])")
            params.append(campaign_ids)

    if wa_number_id is not None:
        where_parts.append("c.wa_number_id = %s")
        params.append(wa_number_id)

    if tag_id is not None:
        where_parts.append(
            "EXISTS (SELECT 1 FROM crm.lead_tags lt "
            "JOIN crm.tags t ON t.id = lt.tag_id "
            "WHERE lt.lead_id = c.lead_id AND lt.tag_id = %s AND t.activo = TRUE)"
        )
        params.append(tag_id)

    where_sql = " AND ".join(where_parts)

    query = f"""
        SELECT
          COUNT(*) FILTER (
            WHERE c.classification_status NOT IN ('archived', 'skipped')
          ) AS todos,
          COUNT(*) FILTER (
            WHERE c.classification_status = 'classified'
              AND c.classification_category = 'cliente_potencial'
          ) AS potenciales,
          COUNT(*) FILTER (
            WHERE c.classification_status IN ('manual_review', 'failed')
          ) AS revisar,
          COUNT(*) FILTER (
            WHERE c.classification_status IN ('pending', 'queued')
          ) AS sin_clasificar,
          COUNT(*) FILTER (
            WHERE c.classification_status = 'archived'
          ) AS archivados,
          -- Chats archivados con mensajes no leidos. Necesario para que el
          -- encabezado "Archivados (N)" del sidebar senale con pill verde
          -- cuando hay algo esperando atencion, estilo WhatsApp Web.
          COUNT(*) FILTER (
            WHERE c.classification_status = 'archived'
              AND c.unread_count > 0
          ) AS archivados_unread,
          COUNT(*) FILTER (
            WHERE c.lead_id IS NOT NULL
              AND c.asesor_id IN (SELECT id FROM auth.users WHERE role = 'supervisor' AND is_active = TRUE)
              {delegar_extra}
          ) AS delegar
        FROM crm.wa_conversations c
        LEFT JOIN crm.leads l ON l.id = c.lead_id
        WHERE {where_sql}
    """

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()

    counts = {k: int(v or 0) for k, v in (dict(row) if row else {}).items()}
    return {"counts": counts}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
):
    """Trae una conv unica por id. Usado como fallback por el frontend cuando
    llega via deep-link y aun no esta presente en el listado paginado.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            row = _fetch_conversation_row(cur, conversation_id)
    if not row:
        raise HTTPException(404, "Conversación no encontrada")

    # V037 lazy self-heal: campanas pre-V037 quedaron enriquecidas sin los
    # campos visuales del creative (thumbnail/image/video). En cuanto el
    # usuario abre un chat atribuido a una de esas campanas, re-disparamos
    # el enrich en background — el fresh-check lo detecta via
    # needs_v037_backfill (creative_media_cached_at IS NULL y sin error) y
    # vuelve a pegarle a Graph una sola vez. Sin error_flag tambien para
    # no loopear en ads cuya descarga ya fallo.
    ad_id = row.get("meta_ad_id")
    if (
        ad_id
        and not row.get("meta_creative_thumbnail_ready")
        and not row.get("meta_creative_media_error")
    ):
        background_tasks.add_task(_enrich_ctwa_task, ad_id)

    return {"conversation": row}


@router.get("/conversations")
def list_conversations(
    campaign_id: Optional[str] = Query(
        None,
        description="Filtro por campaña: id único o lista separada por comas (multi-ad con mismo copy)",
    ),
    asesor_id: Optional[str] = None,
    wa_number_id: Optional[int] = Query(
        None,
        description="Filtro por linea propia (multi-numero V033)",
    ),
    status: Optional[str] = Query(
        None,
        description="Filtro por bandeja: potenciales | revisar | archivados | sin_clasificar",
    ),
    tag_id: Optional[int] = Query(
        None,
        description="Filtro por etiqueta del lead — solo chats con lead que tenga esa tag",
    ),
    limit: int = Query(50, ge=1, le=200),
    current_user: TokenData = Depends(get_current_user),
):
    """Lista chats ordenados por ultimo mensaje.

    Filtros:
    - campaign_id: solo chats de leads atribuidos a esa campaña
    - asesor_id: solo chats del asesor (admin/supervisor override)
    - status: bandeja IA (potenciales | revisar | archivados | sin_clasificar)
    - tag_id: solo chats cuyo lead tenga la etiqueta indicada (V026)

    Visibilidad por rol (modelo own → team → all):
    - asesor: solo sus chats.
    - supervisor: su equipo (via crm.equipos) + chats propios + pool
      compartido sin owner en estados de triage.
    - admin: todo.
    """
    params: list = []
    where_parts = ["1=1"]

    vis_sql, vis_params = _conversation_visibility_clause(current_user)
    where_parts.append(vis_sql)
    params.extend(vis_params)

    # asesor_id como override explicito (admin/supervisor). El AND con la
    # clausula de visibilidad garantiza que un supervisor no pueda ver
    # asesores fuera de su equipo aunque pase el id.
    if asesor_id and current_user.role in ("admin", "supervisor"):
        where_parts.append("c.asesor_id = %s::uuid")
        params.append(asesor_id)

    if campaign_id is not None:
        campaign_ids: list[int] = []
        for token in str(campaign_id).split(","):
            token = token.strip()
            if not token:
                continue
            try:
                campaign_ids.append(int(token))
            except ValueError:
                continue
        if campaign_ids:
            where_parts.append("l.wa_campaign_id = ANY(%s::int[])")
            params.append(campaign_ids)

    if wa_number_id is not None:
        where_parts.append("c.wa_number_id = %s")
        params.append(wa_number_id)

    if tag_id is not None:
        # Solo chats cuyo lead tenga la etiqueta activa. Chats sin lead no
        # aparecen — las etiquetas viven en el lead, no en la conversacion.
        where_parts.append(
            "EXISTS (SELECT 1 FROM crm.lead_tags lt "
            "JOIN crm.tags t ON t.id = lt.tag_id "
            "WHERE lt.lead_id = c.lead_id AND lt.tag_id = %s AND t.activo = TRUE)"
        )
        params.append(tag_id)

    # Filtro por bandeja IA
    if status:
        status_key = status.lower()
        if status_key not in _STATUS_FILTER_BUCKETS:
            raise HTTPException(400, f"status invalido. Valores: {list(_STATUS_FILTER_BUCKETS)}")

        if status_key == "delegar":
            # Bandeja especial: chats ya con lead asignado a un supervisor
            # (auto-asignados por wa_router_service tras clasificacion alta).
            # El supervisor debe pasarlos a un asesor de su equipo.
            # Derivamos del rol — no agregamos columna `requires_delegation`
            # para evitar drift con el rol real.
            where_parts.append("c.lead_id IS NOT NULL")
            where_parts.append(
                "c.asesor_id IN (SELECT id FROM auth.users WHERE role = 'supervisor' AND is_active = TRUE)"
            )
            # Supervisor: solo lo suyo (es lo que el debe delegar).
            # Admin: todos los pendientes de delegar (vista global).
            if current_user.role == "supervisor":
                where_parts.append("c.asesor_id = %s::uuid")
                params.append(current_user.user_id)
        else:
            bucket = _STATUS_FILTER_BUCKETS[status_key]
            placeholders = ",".join(["%s"] * len(bucket))
            where_parts.append(f"c.classification_status IN ({placeholders})")
            params.extend(bucket)
            # Para 'potenciales' filtrar solo los que el modelo marco como cliente_potencial
            if status_key == "potenciales":
                where_parts.append("c.classification_category = 'cliente_potencial'")
    else:
        # Por defecto (sin filtro de bandeja) ocultar chats archivados/skipped
        # — estilo CRMs profesionales: "disqualified" no aparece en inbox
        # principal, solo si filtras "archivados" explicitamente.
        where_parts.append(
            "c.classification_status NOT IN ('archived', 'skipped')"
        )

    where_sql = " AND ".join(where_parts)

    query = f"""
        SELECT {_CONV_SELECT_COLUMNS}
        {_CONV_JOIN}
        WHERE {where_sql}
        -- Ordena por actividad reciente. Conversaciones sin mensajes (recien
        -- abiertas desde LeadDetalle, p.ej.) caen al creado_at para que no se
        -- pierdan al fondo con NULLS LAST — aparecen arriba como recientes.
        ORDER BY GREATEST(c.last_message_at, c.created_at) DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return {"conversations": [dict(r) for r in rows]}


@router.get("/conversations/{conversation_id}/messages")
def get_messages(
    conversation_id: int,
    background_tasks: BackgroundTasks,
    limit: int = Query(100, ge=1, le=500),
    current_user: TokenData = Depends(get_current_user),
):
    """Historial de mensajes de una conversacion (mas reciente primero)."""
    ctwa_ad_to_enrich: Optional[str] = None
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                """
                SELECT id, wa_message_id, direction, msg_type, content, payload,
                       status, error_code, error_detail, sent_by_user_id,
                       timestamp, risk_flags, wa_number_id
                FROM crm.wa_messages
                WHERE conversation_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (conversation_id, limit),
            )
            msgs = [dict(r) for r in cur.fetchall()]

            # V037 lazy self-heal: si el chat esta atribuido a una campana
            # pre-V037 (enriquecida antes de los campos visuales), disparamos
            # un re-fetch en background. El fresh-check en meta_service detecta
            # needs_v037_backfill y re-pega a Graph una sola vez.
            cur.execute(
                """
                SELECT cam.ad_id
                  FROM crm.wa_conversations c
                  JOIN crm.leads l ON l.id = c.lead_id
                  JOIN crm.wa_campaigns cam ON cam.id = l.wa_campaign_id
                 WHERE c.id = %s
                   AND cam.ad_id IS NOT NULL
                   AND cam.creative_media_cached_at IS NULL
                   AND cam.creative_media_error IS NULL
                """,
                (conversation_id,),
            )
            row_ad = cur.fetchone()
            if row_ad:
                ctwa_ad_to_enrich = row_ad["ad_id"]

    if ctwa_ad_to_enrich:
        background_tasks.add_task(_enrich_ctwa_task, ctwa_ad_to_enrich)

    return {"messages": msgs}


@router.patch("/conversations/{conversation_id}/read")
def mark_read(
    conversation_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    with get_db() as conn:
        with conn.cursor() as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                "UPDATE crm.wa_conversations SET unread_count = 0 WHERE id = %s",
                (conversation_id,),
            )
        conn.commit()
    return {"ok": True}


# Regex de URL reusado por el endpoint de attachments. http(s) + cualquier
# char no whitespace/quote. Limite defensivo al final con rstrip de puntuacion.
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


@router.get("/conversations/{conversation_id}/attachments")
def get_conversation_attachments(
    conversation_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Panel "Info del contacto" estilo WhatsApp Web.

    Devuelve:
      - media: mensajes con adjunto (imagen/video/audio/doc/sticker) ordenados
               por timestamp desc. Solo metadatos — el binario se descarga
               bajo demanda via /api/whatsapp/media/{id}.
      - links: URLs extraidas de mensajes de texto, con el mensaje y timestamp
               para contexto. Se deduplica por (url, message_id).
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                """
                SELECT id, wa_message_id, direction, msg_type, content, payload, timestamp
                FROM crm.wa_messages
                WHERE conversation_id = %s
                  AND msg_type IN ('image', 'sticker', 'video', 'audio', 'document')
                ORDER BY timestamp DESC
                """,
                (conversation_id,),
            )
            media = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT id, direction, content, timestamp
                FROM crm.wa_messages
                WHERE conversation_id = %s
                  AND msg_type = 'text'
                  AND content ~* 'https?://'
                ORDER BY timestamp DESC
                """,
                (conversation_id,),
            )
            text_rows = cur.fetchall()

    links: list[dict] = []
    for row in text_rows:
        body = row["content"] or ""
        for raw_url in _URL_RE.findall(body):
            # Limpia puntuacion adherida al final (.,;!?) pero preserva /)]
            url = raw_url.rstrip(".,;!?:")
            links.append(
                {
                    "url": url,
                    "message_id": row["id"],
                    "direction": row["direction"],
                    "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                    "context": body[:200],
                }
            )

    return {
        "media": media,
        "links": links,
        "counts": {"media": len(media), "links": len(links)},
    }


# ─────────────────────────────────────────────────────────────────────────────
# MEDIA — proxy + cache para descargar imágenes/audio/video/documentos (V031)
# ─────────────────────────────────────────────────────────────────────────────
# Meta Cloud API entrega la media en dos pasos:
#   1. GET /{media_id}         → devuelve JSON con url firmada (expira ~5 min)
#   2. GET {url} (con Bearer)  → devuelve el binario
# La url firmada solo se puede consumir desde backend con el access_token.
# Cacheamos el binario en crm.wa_media_cache para no repetir el round-trip
# cada vez que el frontend pinte el chat.

_MEDIA_TYPES = ("image", "sticker", "audio", "video", "document")


def _extract_media_id(payload: dict, msg_type: str) -> tuple[str | None, str | None]:
    """Extrae (media_id, mime_type) del payload crudo de WA segun el tipo."""
    if not payload or msg_type not in _MEDIA_TYPES:
        return None, None
    node = payload.get(msg_type) or {}
    return node.get("id"), node.get("mime_type")


async def _fetch_media_from_meta(
    media_id: str,
    phone_number_id: Optional[str] = None,
) -> tuple[bytes, str]:
    """Dos pasos contra Graph API: metadata → binario. Retorna (bytes, mime).

    El token se resuelve per-WABA: el mensaje entro por un phone_number_id
    concreto — usamos el access_token de esa WABA (multi-WABA V034).
    """
    token = _resolve_access_token(phone_number_id)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as cli:
        # Paso 1: metadata + url firmada
        meta_url = f"{META_GRAPH_BASE}/{media_id}"
        r1 = await cli.get(meta_url, headers=headers)
        if r1.status_code != 200:
            logger.warning("meta media metadata fallo %s: %s", r1.status_code, r1.text[:300])
            raise HTTPException(502, "No se pudo obtener la media de WhatsApp")
        meta = r1.json()
        signed_url = meta.get("url")
        mime_type  = meta.get("mime_type") or "application/octet-stream"
        if not signed_url:
            raise HTTPException(502, "Meta no devolvio url de descarga")

        # Paso 2: binario (url firmada tambien requiere el Bearer)
        r2 = await cli.get(signed_url, headers=headers)
        if r2.status_code != 200:
            logger.warning("meta media binary fallo %s", r2.status_code)
            raise HTTPException(502, "No se pudo descargar el binario de WhatsApp")
        return r2.content, mime_type


def _get_cached_media(media_id: str) -> tuple[bytes, str] | None:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT data, mime_type FROM crm.wa_media_cache WHERE media_id = %s",
                (media_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return bytes(row["data"]), row["mime_type"]


def _store_cached_media(media_id: str, mime_type: str, data: bytes) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crm.wa_media_cache (media_id, mime_type, size_bytes, data)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (media_id) DO NOTHING
                """,
                (media_id, mime_type, len(data), psycopg2.Binary(data)),
            )
        conn.commit()


@router.get("/media/{message_id}")
async def get_media(
    message_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Descarga el binario de una media de WhatsApp (img/audio/video/doc).

    Flujo: busca el mensaje, extrae media_id del payload, intenta servir de
    cache. Si no esta cacheado, baja de Meta Graph API, cachea y sirve.
    """
    from fastapi.responses import Response

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT m.msg_type, m.payload, n.phone_number_id
                FROM crm.wa_messages m
                LEFT JOIN crm.wa_numbers n ON n.id = m.wa_number_id
                WHERE m.id = %s
                """,
                (message_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(404, "Mensaje no encontrado")

    media_id, payload_mime = _extract_media_id(row["payload"], row["msg_type"])
    if not media_id:
        raise HTTPException(404, "Este mensaje no tiene media")

    cached = _get_cached_media(media_id)
    if cached:
        data, mime = cached
    else:
        # phone_number_id del mensaje → token de la WABA correcta (multi-WABA).
        # Si el mensaje es antiguo y no tiene wa_number_id, _resolve_access_token
        # cae a la default WABA / env como fallback.
        data, mime = await _fetch_media_from_meta(media_id, row.get("phone_number_id"))
        # Si Meta no devolvio mime_type, usa el del payload de entrada.
        if not mime or mime == "application/octet-stream":
            mime = payload_mime or mime
        try:
            _store_cached_media(media_id, mime, data)
        except Exception as exc:
            # No bloqueamos la respuesta si el cache falla — servimos igual.
            logger.warning("wa_media_cache insert fallo: %s", exc)

    return Response(
        content=data,
        media_type=mime,
        headers={
            # Cache del navegador: la media no cambia (media_id es inmutable).
            "Cache-Control": "private, max-age=86400",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# CREATIVE MEDIA — thumbnail del ad (V037)
# ─────────────────────────────────────────────────────────────────────────────
# Sirve el thumbnail binario cacheado en crm.meta_creative_cache para que la
# UI lo consuma desde nuestro dominio (evita CORS + URL firmada que caduca).

@router.get("/campaigns/{wa_campaign_id}/creative-thumbnail")
def get_campaign_creative_thumbnail(
    wa_campaign_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Devuelve el binario del thumbnail del creative del ad."""
    from fastapi.responses import Response
    from app.services.integrations import creative_media_service

    cached = creative_media_service.get_cached_thumbnail(wa_campaign_id)
    if cached is None:
        raise HTTPException(404, "Thumbnail no disponible")
    data, mime = cached
    return Response(
        content=data,
        media_type=mime or "image/jpeg",
        headers={
            # El thumbnail de un ad es practicamente inmutable (si se cambia
            # el creative, se rehace la campana). 7 dias es razonable.
            "Cache-Control": "private, max-age=604800",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# PHISHING — re-analisis manual (V032)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/messages/{message_id}/reanalyze-phishing")
async def reanalyze_message_phishing(
    message_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Fuerza re-analisis anti-phishing de un mensaje. Util si se ajustaron
    las reglas o el prompt LLM y se quiere re-evaluar mensajes historicos.
    """
    from app.services.phishing_detector import reanalyze_message
    result = await reanalyze_message(message_id)
    if result is None:
        raise HTTPException(
            404,
            "Mensaje no existe, no es inbound, o no tiene contenido textual",
        )
    return {"ok": True, "risk_flags": result}


# ─────────────────────────────────────────────────────────────────────────────
# CASES — historico de leads asociados a la conversacion (V025)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}/cases")
def list_conversation_cases(
    conversation_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Devuelve la timeline de casos (leads) que ha tenido este chat.

    Ordenado del mas reciente al mas antiguo. Cada entrada incluye el
    estado actual del lead, el asesor que lo manejo y el motivo por el
    que el caso se abrio (auto_classifier / auto_terminal / manual_user).

    Util cuando un cliente vuelve por un nuevo lote: el asesor ve el
    histórico y puede contextualizar (ej. "ya compro el Lote 8 antes").
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                """
                SELECT
                    wcl.id,
                    wcl.lead_id,
                    wcl.created_at::text  AS opened_at,
                    wcl.closed_at::text   AS closed_at,
                    wcl.created_by,
                    wcl.reason,
                    l.nombres || ' ' || COALESCE(l.apellidos,'') AS lead_name,
                    l.campana,
                    e.nombre              AS estado,
                    e.color_hex           AS estado_color,
                    l.asesor_id::text     AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                                          AS asesor_nombre
                FROM crm.wa_conversation_leads wcl
                LEFT JOIN crm.leads        l ON l.id = wcl.lead_id
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN auth.users       u ON u.id = l.asesor_id
                WHERE wcl.conversation_id = %s
                ORDER BY wcl.created_at DESC
                """,
                (conversation_id,),
            )
            cases = [dict(r) for r in cur.fetchall()]

    return {"conversation_id": conversation_id, "cases": cases}


# ─────────────────────────────────────────────────────────────────────────────
# NEW CASE — apertura manual de un nuevo caso (cliente vuelve por nuevo lote)
# ─────────────────────────────────────────────────────────────────────────────

class NewCaseBody(BaseModel):
    """Motivo opcional explicando por que el asesor abre un nuevo caso.

    Se persiste en wa_conversation_leads.reason del caso CERRADO (no del
    nuevo) — describe el corte, no el caso futuro. Ej.:
      "Cliente compro Lote 8 y ahora pregunta por Lote 12 sector B"
    """
    reason: str | None = None


@router.post("/conversations/{conversation_id}/new_case")
async def open_new_case(
    conversation_id: int,
    body: NewCaseBody,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
):
    """Cierra el caso activo y reinicia la conversacion para que la IA
    cree un nuevo lead via rotacion. Pensado para cuando el asesor sabe
    que el cliente esta pidiendo algo distinto al caso actual.

    Flujo:
      1. Cierra wa_conversation_leads.closed_at del caso activo (si hay).
      2. Reset wa_conversations: lead_id=NULL, status='queued'.
      3. Encola classifier en background → wa_router_service crea lead
         nuevo con rotacion de supervisor (la IA decide categoria).

    Permisos: cualquier usuario logueado. Si la conversacion ya esta
    sin lead, solo encola reclasificacion (idempotente).
    """
    reason = (body.reason or "").strip() or None

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                "SELECT id, lead_id FROM crm.wa_conversations WHERE id = %s",
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Conversacion no existe")

            prior_lead_id = row["lead_id"]

            # Cierra el caso activo en el historial (si V025 aplico) +
            # registra quien y por que. Si la tabla no existe, log y sigue.
            if prior_lead_id:
                try:
                    cur.execute(
                        """
                        UPDATE crm.wa_conversation_leads
                        SET closed_at       = NOW(),
                            reason          = COALESCE(%s, reason),
                            created_by_user = COALESCE(created_by_user, %s::uuid)
                        WHERE conversation_id = %s
                          AND lead_id         = %s
                          AND closed_at IS NULL
                        """,
                        (reason, current_user.user_id, conversation_id, prior_lead_id),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "wa new_case: no se pudo cerrar caso historico conv=%s lead=%s: %s",
                        conversation_id, prior_lead_id, exc,
                    )

            # Reset: liberamos el chat para que la IA lo reclasifique
            # como un caso nuevo. classification_attempts=0 para que el
            # classifier no aborte por retry-cap.
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET lead_id                 = NULL,
                    classification_status   = 'queued',
                    classification_attempts = 0,
                    classified_at           = NULL
                WHERE id = %s
                """,
                (conversation_id,),
            )
        conn.commit()

    # Encola IA — el router decidira rotacion + creara nuevo lead.
    # force_new_lead=True: el usuario pidio explicitamente un caso nuevo,
    # el router debe crear un lead fresco aunque exista otro lead activo
    # con el mismo telefono (caso tipico: cliente vuelve por otro lote).
    background_tasks.add_task(
        _classify_conversation_task, conversation_id, force_new_lead=True,
    )

    logger.info(
        "wa new_case: conv=%s caso anterior=%s cerrado por user=%s reason=%r",
        conversation_id, prior_lead_id, current_user.user_id, reason,
    )

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "previous_lead_id": prior_lead_id,
        "status": "queued",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TAKE — auto-asignar este chat al usuario actual
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/take")
def take_conversation(
    conversation_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Reasigna esta conversacion al usuario actual.

    Casos de uso:
      1. Supervisor abre chat de "Pendientes de delegar" y decide atenderlo
         personalmente (en vez de pasarlo a un asesor).
      2. Admin toma cualquier chat para resolver una urgencia.
      3. Asesor reclama un chat que ya tiene lead asignado a el (evita
         confusion si el chat aun mostraba al supervisor por desincronia).

    Si la conversacion tiene `lead_id`, delegamos al servicio de asignacion
    de leads — asi mantenemos el audit log en `crm.asignaciones_log`,
    disparamos push y aprovechamos B1 (sync automatico a wa_conversations).
    Si no hay lead, hacemos UPDATE directo en wa_conversations (no hay
    nada que loguear porque la asignacion no afecta a un lead).
    """
    # Asesor solo puede tomar chats sin asesor o ya suyos. Reasignar
    # entre asesores es responsabilidad de supervisor/admin.
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                """
                SELECT id, lead_id, asesor_id::text AS asesor_id
                FROM crm.wa_conversations
                WHERE id = %s
                """,
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Conversacion no existe")

            current_owner = row["asesor_id"]
            lead_id = row["lead_id"]

    # No-op: ya es mio Y ya tiene lead. Si es mio pero sin lead, caemos al
    # Camino 2 que crea el lead (sucede con convs tomadas antes del fix de
    # take→crea-lead — quedaron "huerfanas" sin aparecer en /Leads).
    if current_owner == current_user.user_id and lead_id is not None:
        return {
            "ok": True,
            "already_owned": True,
            "conversation_id": conversation_id,
            "lead_id": lead_id,
        }

    # Asesor no puede quitar a otro
    if (
        current_user.role == "asesor"
        and current_owner is not None
        and current_owner != current_user.user_id
    ):
        raise HTTPException(
            403,
            "Como asesor solo puedes tomar chats sin asignar.",
        )

    # Camino 1: hay lead → delegamos al servicio (audit + push + B1 sync)
    if lead_id:
        from app.services.assignments_service import reassign_one as svc_reassign_one
        result = svc_reassign_one(
            lead_id=lead_id,
            new_asesor_id=current_user.user_id,
            current_user=current_user,
        )
        return {
            "ok": True,
            "conversation_id": conversation_id,
            "via": "lead_reassign",
            "previous_asesor_id": result.get("previous_asesor_id"),
            "lead_name": result.get("lead_name"),
        }

    # Camino 2: chat sin lead — crear/reusar lead y asignarlo al taker.
    # Antes este camino solo hacia UPDATE de asesor_id en wa_conversations,
    # lo que dejaba la conv "huerfana" (no aparecia en /Leads). Ahora el flujo
    # es completo: tomar = adueñarse del chat AND crear el lead.
    from app.services.wa_router_service import create_lead_from_take_action
    try:
        result = create_lead_from_take_action(
            conversation_id=conversation_id,
            taker_user_id=current_user.user_id,
            taker_role=current_user.role,
        )
    except ValueError as exc:
        logger.error(
            "wa take_conversation: create_lead fallo conv=%s: %s",
            conversation_id, exc,
        )
        raise HTTPException(500, f"No se pudo crear el lead: {exc}") from exc

    return {
        "ok":                  True,
        "conversation_id":     conversation_id,
        "via":                 "lead_created" if result["lead_created"] else "lead_reused",
        "previous_asesor_id":  current_owner,
        "lead_id":             result["lead_id"],
        "lead_created":        result["lead_created"],
        "lead_name":           result["lead_name"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# ARCHIVAR — descalificar conversacion (patrón estándar "disqualify")
# ─────────────────────────────────────────────────────────────────────────────

_ARCHIVE_REASONS = {"not_a_lead", "spam", "duplicate", "no_response", "other"}


class ArchiveConversationPayload(BaseModel):
    reason: str
    notes: Optional[str] = None


@router.post("/conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: int,
    payload: ArchiveConversationPayload,
    current_user: TokenData = Depends(get_current_user),
):
    """Archiva una conversacion con razon auditada.

    Usar para chats que NO son leads comerciales (consulta administrativa,
    spam, duplicado) y no deben ocupar el inbox. Los mensajes se preservan
    para auditoria. Reversible via POST /{id}/reclassify.

    Solo admin/supervisor. Motivos validos:
      not_a_lead | spam | duplicate | no_response | other
    """
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "Solo admin/supervisor puede archivar")

    reason = (payload.reason or "").strip().lower()
    if reason not in _ARCHIVE_REASONS:
        raise HTTPException(
            400,
            f"reason invalido. Valores: {sorted(_ARCHIVE_REASONS)}",
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                """
                UPDATE crm.wa_conversations
                   SET classification_status = 'archived',
                       archived_reason       = %s,
                       archived_notes        = %s,
                       archived_by           = %s::uuid,
                       archived_at           = NOW()
                 WHERE id = %s
                 RETURNING id
                """,
                (reason, payload.notes, current_user.user_id, conversation_id),
            )
            if not cur.fetchone():
                raise HTTPException(404, "Conversacion no existe")
        conn.commit()

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "status": "archived",
        "reason": reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RECLASIFICAR — trigger manual
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/reclassify")
async def reclassify_conversation(
    conversation_id: int,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
):
    """Fuerza re-clasificacion IA de una conversacion.

    Casos de uso:
      1. Conversaciones pre-existentes a V024 (nunca se clasificaron)
      2. Retry manual de status='failed'
      3. Re-evaluar tras revision manual

    Solo admin/supervisor. Pone el status en 'queued' si corresponde y
    encola BackgroundTask; el resultado se ve por polling del sidebar.
    """
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "Solo admin/supervisor puede reclasificar")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_visible(cur, conversation_id, current_user)
            cur.execute(
                "SELECT id, classification_status, lead_id FROM crm.wa_conversations WHERE id = %s",
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Conversacion no existe")

            # Si ya tiene lead_id asociado, la IA no decide nada — skip
            if row["lead_id"]:
                raise HTTPException(
                    409,
                    "Esta conversacion ya esta asociada a un lead existente. "
                    "No se re-clasifica.",
                )

            # CASO ESPECIAL — desarchivar:
            # Si el chat estaba 'archived', un humano esta diciendo "no, esto
            # SI es lead". Re-correr la IA aca seria un loop: misma data →
            # misma decision → re-archivada. Vamos directo a manual_review,
            # limpiamos los campos de auditoria de archivo, y NO encolamos
            # background task.
            if row["classification_status"] == "archived":
                cur.execute(
                    """
                    UPDATE crm.wa_conversations
                       SET classification_status = 'manual_review',
                           archived_reason       = NULL,
                           archived_notes        = NULL,
                           archived_by           = NULL,
                           archived_at           = NULL
                     WHERE id = %s
                    """,
                    (conversation_id,),
                )
                conn.commit()
                return {
                    "ok": True,
                    "conversation_id": conversation_id,
                    "status": "manual_review",
                    "unarchived": True,
                }

            # Reinicia el status a 'queued' para que classify_conversation
            # lo procese (su guard permite pending/queued/failed).
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET classification_status = 'queued'
                WHERE id = %s
                """,
                (conversation_id,),
            )
        conn.commit()

    background_tasks.add_task(_classify_conversation_task, conversation_id)
    return {"ok": True, "conversation_id": conversation_id, "status": "queued"}


# ─────────────────────────────────────────────────────────────────────────────
# RECLASIFICAR EN BULK — todas las stuck
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/conversations/_reclassify_stuck")
def reclassify_stuck(
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
):
    """Limpia conversaciones stuck en pending/queued/failed.

    Dos rutas segun si la conversacion ya tiene lead asociado:
      - lead_id IS NULL  -> 'queued' + encolar BackgroundTask (IA decide)
      - lead_id IS NOT NULL -> 'skipped' directamente (ya hay asesor,
        no hay nada que decidir; el classifier hubiera hecho lo mismo)

    Util tras un deploy donde V024 acaba de aplicarse y hay
    conversaciones pre-existentes que nunca se procesaron, o tras
    un worker restart que mato BackgroundTasks en vuelo.

    Solo admin. Limita a 100 reclassifies para no saturar Ollama de golpe.
    """
    if current_user.role != "admin":
        raise HTTPException(403, "Solo admin")

    with get_db() as conn:
        with conn.cursor() as cur:
            # 1) Las que YA tienen lead -> mark skipped (no necesitan IA)
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET classification_status = 'skipped',
                    classified_at         = NOW()
                WHERE classification_status IN ('pending', 'queued', 'failed')
                  AND lead_id IS NOT NULL
                RETURNING id
                """,
            )
            skipped_ids = [r[0] for r in cur.fetchall()]

            # 2) Las que NO tienen lead -> encolar reclasificacion
            cur.execute(
                """
                WITH stuck AS (
                    SELECT id
                    FROM crm.wa_conversations
                    WHERE classification_status IN ('pending', 'queued', 'failed')
                      AND lead_id IS NULL
                    ORDER BY last_message_at DESC NULLS LAST
                    LIMIT 100
                )
                UPDATE crm.wa_conversations c
                SET classification_status = 'queued'
                FROM stuck s
                WHERE c.id = s.id
                RETURNING c.id
                """,
            )
            queued_ids = [r[0] for r in cur.fetchall()]
        conn.commit()

    for cid in queued_ids:
        background_tasks.add_task(_classify_conversation_task, cid)

    return {
        "ok": True,
        "queued_count":  len(queued_ids),
        "skipped_count": len(skipped_ids),
        "queued_ids":    queued_ids,
        "skipped_ids":   skipped_ids,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTICO — ping a Ollama
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTICS — health del pipeline WhatsApp (webhook + DB)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/diagnostics")
def whatsapp_diagnostics(current_user: TokenData = Depends(get_current_user)):
    """Devuelve el estado del pipeline WhatsApp para diagnostico rapido.

    Pensado para responder "el cliente dice que escribio pero no veo nada":
      - last_inbound_at: timestamp del ultimo mensaje recibido (NULL = jamas)
      - inbound_5min / inbound_1h / inbound_24h: cuentas para detectar
        si Meta esta entregando webhooks
      - outbound_24h: si se mandaron respuestas
      - config: phone_number_id, webhook_token, app_secret estan cargados

    Solo admin/supervisor — los conteos no exponen datos personales pero
    el nivel de info es operativo.
    """
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "Solo admin/supervisor")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    MAX(CASE WHEN direction='inbound'  THEN timestamp END)::text AS last_inbound_at,
                    MAX(CASE WHEN direction='outbound' THEN timestamp END)::text AS last_outbound_at,
                    COUNT(*) FILTER (
                        WHERE direction='inbound'
                          AND timestamp > NOW() - INTERVAL '5 minutes'
                    ) AS inbound_5min,
                    COUNT(*) FILTER (
                        WHERE direction='inbound'
                          AND timestamp > NOW() - INTERVAL '1 hour'
                    ) AS inbound_1h,
                    COUNT(*) FILTER (
                        WHERE direction='inbound'
                          AND timestamp > NOW() - INTERVAL '24 hours'
                    ) AS inbound_24h,
                    COUNT(*) FILTER (
                        WHERE direction='outbound'
                          AND timestamp > NOW() - INTERVAL '24 hours'
                    ) AS outbound_24h,
                    COUNT(*) FILTER (WHERE direction='inbound')  AS inbound_total,
                    COUNT(*) FILTER (WHERE direction='outbound') AS outbound_total
                FROM crm.wa_messages
                """
            )
            stats = dict(cur.fetchone())

            cur.execute(
                "SELECT COUNT(*) AS total FROM crm.wa_conversations"
            )
            stats["conversations_total"] = cur.fetchone()["total"]

            try:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_events,
                        COUNT(*) FILTER (WHERE event_type = 'inbound_message') AS inbound_messages,
                        COUNT(*) FILTER (WHERE has_referral = TRUE) AS events_with_referral,
                        COUNT(DISTINCT wa_phone) FILTER (WHERE has_referral = TRUE) AS unique_referral_phones,
                        COUNT(*) FILTER (WHERE outcome IN ('lead_created', 'lead_attributed')) AS leads_created,
                        COUNT(*) FILTER (WHERE outcome IN ('lead_matched', 'lead_matched_existing', 'lead_matched_duplicate')) AS leads_matched,
                        COUNT(*) FILTER (WHERE outcome IN ('lead_creation_failed', 'referral_error', 'webhook_processing_failed')) AS errors
                    FROM crm.wa_webhook_events
                    WHERE received_at >= NOW() - INTERVAL '7 days'
                    """
                )
                stats["audit_7d"] = dict(cur.fetchone())
            except Exception as audit_err:
                logger.warning("Diagnostics audit query fallback: %s", audit_err)
                stats["audit_7d"] = None

    # Inventario de WABAs registradas (multi-WABA V034)
    from app.services import wa_babas_service
    babas = wa_babas_service.list_all(only_active=False)
    babas_report = [
        {
            "id":                b["id"],
            "display_name":      b["display_name"],
            "waba_id":           b["waba_id"],
            "activo":            b["activo"],
            "is_default":        b["is_default"],
            "has_access_token":  bool(b.get("access_token_fp")),
            "has_app_secret":    b.get("has_app_secret"),
            "has_verify_token":  b.get("has_verify_token"),
            "access_token_mask": b.get("access_token_mask"),
            "access_token_fp":   b.get("access_token_fp"),
        }
        for b in babas
    ]

    return {
        "ok": True,
        "stats": stats,
        "babas_count": len(babas),
        "babas": babas_report,
        "config": {
            "phone_number_id_set":     bool(settings.meta_wa_phone_number_id),
            "verify_token_set":        bool(settings.meta_wa_webhook_verify_token),
            "app_secret_set":          bool(settings.meta_wa_app_secret),
            "business_account_id_set": bool(settings.meta_wa_business_account_id),
            "env_legacy_note":         (
                "Las credenciales reales ahora se gestionan en Configuracion > "
                "WhatsApp > Cuentas Empresariales. Las env vars son solo "
                "compatibilidad con instalaciones previas."
            ),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# AUDITORIA CONTINUA — eventos y conciliacion de webhooks (Meta Ads vs CRM)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/audit-events")
def list_audit_events(
    start_date: Optional[str] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="Fecha fin YYYY-MM-DD"),
    outcome: Optional[str] = Query(None, description="Filtrar por outcome"),
    has_referral: Optional[bool] = Query(None, description="Solo con referral CTWA"),
    ad_id: Optional[str] = Query(None, description="Filtrar por Meta Ad ID"),
    search: Optional[str] = Query(None, description="Buscar por teléfono o titular"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: TokenData = Depends(get_current_user),
):
    """Auditoría continua de webhooks de WhatsApp.
    Permite conciliar eventos recibidos vs leads creados y analizar drop-off de anuncios CTWA.
    """
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "Solo admin/supervisor")

    from app.pii_utils import mask_phone

    filters = []
    params: list[Any] = []

    if start_date:
        filters.append("e.received_at >= %s::date")
        params.append(start_date)
    if end_date:
        filters.append("e.received_at < (%s::date + INTERVAL '1 day')")
        params.append(end_date)
    if outcome:
        filters.append("e.outcome = %s")
        params.append(outcome)
    if has_referral is not None:
        filters.append("e.has_referral = %s")
        params.append(has_referral)
    if ad_id:
        filters.append("e.referral_ad_id = %s")
        params.append(ad_id)
    if search:
        filters.append("(e.wa_phone ILIKE %s OR e.referral_headline ILIKE %s OR e.contact_name ILIKE %s)")
        search_pattern = f"%{search.strip()}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Resumen estadístico
            summary_query = f"""
                SELECT
                    COUNT(*) AS total_events,
                    COUNT(*) FILTER (WHERE e.event_type = 'inbound_message') AS inbound_messages,
                    COUNT(*) FILTER (WHERE e.has_referral = TRUE) AS events_with_referral,
                    COUNT(DISTINCT e.wa_phone) FILTER (WHERE e.has_referral = TRUE) AS unique_referral_phones,
                    COUNT(*) FILTER (WHERE e.outcome IN ('lead_created', 'lead_attributed')) AS leads_created,
                    COUNT(*) FILTER (WHERE e.outcome IN ('lead_matched', 'lead_matched_existing', 'lead_matched_duplicate')) AS leads_matched,
                    COUNT(*) FILTER (WHERE e.outcome LIKE 'status_%%') AS status_updates,
                    COUNT(*) FILTER (WHERE e.outcome IN ('lead_creation_failed', 'referral_error', 'webhook_processing_failed')) AS errors
                FROM crm.wa_webhook_events e
                {where_clause}
            """
            cur.execute(summary_query, params)
            summary = dict(cur.fetchone())

            # 2. Desglose por Anuncio / Campaña
            ads_where = f"{where_clause} AND e.referral_ad_id IS NOT NULL" if where_clause else "WHERE e.referral_ad_id IS NOT NULL"
            ads_query = f"""
                SELECT
                    e.referral_ad_id,
                    COALESCE(e.referral_headline, 'Sin titular') AS headline,
                    COUNT(*) AS total_events,
                    COUNT(DISTINCT e.wa_phone) AS unique_phones,
                    COUNT(*) FILTER (WHERE e.outcome IN ('lead_created', 'lead_attributed')) AS leads_created,
                    COUNT(*) FILTER (WHERE e.outcome IN ('lead_matched', 'lead_matched_existing', 'lead_matched_duplicate')) AS leads_matched
                FROM crm.wa_webhook_events e
                {ads_where}
                GROUP BY e.referral_ad_id, e.referral_headline
                ORDER BY total_events DESC
                LIMIT 20
            """
            cur.execute(ads_query, params)
            ad_breakdown = [dict(r) for r in cur.fetchall()]
            summary["ad_breakdown"] = ad_breakdown

            # 3. Lista de eventos paginada
            list_params = list(params)
            list_params.extend([limit, offset])
            events_query = f"""
                SELECT
                    e.id,
                    e.received_at,
                    e.event_type,
                    e.wa_phone,
                    e.wamid,
                    e.phone_number_id,
                    e.display_phone_number,
                    e.contact_name,
                    e.has_referral,
                    e.referral_ad_id,
                    e.referral_headline,
                    e.referral_source_type,
                    e.lead_id,
                    e.conversation_id,
                    e.outcome,
                    e.error_detail,
                    e.metadata,
                    e.payload,
                    l.nombres AS lead_nombres,
                    l.apellidos AS lead_apellidos,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre
                FROM crm.wa_webhook_events e
                LEFT JOIN crm.leads l ON l.id = e.lead_id
                LEFT JOIN auth.users u ON u.id = l.asesor_id
                {where_clause}
                ORDER BY e.received_at DESC, e.id DESC
                LIMIT %s OFFSET %s
            """
            cur.execute(events_query, list_params)
            events = []
            for r in cur.fetchall():
                d = dict(r)
                if d.get("received_at"):
                    d["received_at"] = d["received_at"].isoformat()
                if current_user.role != "admin" and d.get("wa_phone"):
                    d["wa_phone"] = mask_phone(d["wa_phone"])
                events.append(d)

    return {
        "ok": True,
        "summary": summary,
        "events": events,
        "limit": limit,
        "offset": offset,
    }


# ─────────────────────────────────────────────────────────────────────────────
# UNREAD SUMMARY — contadores para sidebar (badge "Chat")
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/unread_summary")
def unread_summary(current_user: TokenData = Depends(get_current_user)):
    """Contadores de chats que requieren atencion del usuario actual.

    Pensado para el badge del sidebar (NavLink "Chat") y para chips de
    bandeja en el UI. Filtrado por rol:

      - asesor:     unread_chats = chats asignados a el con unread_count > 0
      - supervisor: unread_chats = chats de su equipo OR sin asesor (delegar)
                    + sin_clasificar/requieren_revision globales (su equipo)
      - admin:      contadores globales

    Polling barato — ejecutado cada 30s desde el sidebar.
    """
    role = current_user.role
    user_id = current_user.user_id

    with get_db() as conn:
        with conn.cursor() as cur:
            # ── Asesor: solo lo suyo ─────────────────────────────────────────
            if role == "asesor":
                cur.execute(
                    """
                    SELECT COUNT(*) FROM crm.wa_conversations
                    WHERE asesor_id = %s::uuid AND unread_count > 0
                    """,
                    (user_id,),
                )
                unread = cur.fetchone()[0]
                return {
                    "unread_chats":       unread,
                    "sin_clasificar":     0,
                    "requieren_revision": 0,
                    "badge_total":        unread,
                }

            # ── Supervisor: su equipo + sin asignar (potenciales a delegar) ─
            if role == "supervisor":
                # Chats no leidos del equipo o sin asesor
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM crm.wa_conversations c
                    WHERE c.unread_count > 0
                      AND (
                        c.asesor_id IS NULL
                        OR c.asesor_id IN (
                            SELECT asesor_id FROM crm.equipos
                            WHERE supervisor_id = %s::uuid AND activo = TRUE
                        )
                        OR c.asesor_id = %s::uuid
                      )
                    """,
                    (user_id, user_id),
                )
                unread = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COUNT(*) FROM crm.wa_conversations
                    WHERE classification_status IN ('pending','queued')
                      AND lead_id IS NULL
                    """,
                )
                sin_clasificar = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT COUNT(*) FROM crm.wa_conversations
                    WHERE classification_status IN ('manual_review','failed')
                    """,
                )
                requieren_revision = cur.fetchone()[0]

                return {
                    "unread_chats":       unread,
                    "sin_clasificar":     sin_clasificar,
                    "requieren_revision": requieren_revision,
                    # Solo unread en el badge: los chats que requieren revision
                    # ya tienen su propio chip visible en el listado, mezclarlos
                    # en el contador del sidebar generaba badges que el usuario
                    # no podia "encontrar" en la lista.
                    "badge_total":        unread,
                }

            # ── Admin: visibilidad global ────────────────────────────────────
            cur.execute(
                "SELECT COUNT(*) FROM crm.wa_conversations WHERE unread_count > 0"
            )
            unread = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*) FROM crm.wa_conversations
                WHERE classification_status IN ('pending','queued')
                  AND lead_id IS NULL
                """,
            )
            sin_clasificar = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*) FROM crm.wa_conversations
                WHERE classification_status IN ('manual_review','failed')
                """,
            )
            requieren_revision = cur.fetchone()[0]

    return {
        "unread_chats":       unread,
        "sin_clasificar":     sin_clasificar,
        "requieren_revision": requieren_revision,
        # Ver nota en rama supervisor — badge solo cuenta unreads.
        "badge_total":        unread,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS — modo IA (auto vs manual)
# ─────────────────────────────────────────────────────────────────────────────

class IaModeUpdate(BaseModel):
    mode: str = Field(..., description="'auto' | 'manual'")


@router.get("/settings")
def get_wa_settings(current_user: TokenData = Depends(get_current_user)):
    """Retorna config actual de WhatsApp (modo IA).

    Visible para admin y supervisor: ambos necesitan saber si la IA esta
    activa para entender por que un chat se quedo en 'pending'.
    Solo admin puede modificar (ver PATCH).
    """
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "Solo admin/supervisor")
    return {"ia_mode": _load_ia_mode()}


@router.patch("/settings")
def patch_wa_settings(
    payload: IaModeUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    """Cambia el modo IA. Solo admin.

    'manual' deja todos los nuevos chats en 'pending' hasta que un
    supervisor los reclasifique a mano (boton 'Reclasificar' en el chat).
    'auto' restaura la clasificacion automatica del primer mensaje.
    """
    if current_user.role != "admin":
        raise HTTPException(403, "Solo admin puede cambiar la config IA")
    if payload.mode not in _VALID_IA_MODES:
        raise HTTPException(
            400, f"mode invalido. Valores: {list(_VALID_IA_MODES)}",
        )

    # Reusa la tabla public.app_settings creada por routers/settings.py.
    # Nos aseguramos de su existencia delegando en el helper alli definido
    # — DRY y evita duplicar el DDL.
    from app.routers.settings import _ensure_table  # type: ignore

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                """,
                (_IA_MODE_KEY, json.dumps({"mode": payload.mode})),
            )
        conn.commit()

    # V061: invalidar cache para que el proximo webhook vea el modo nuevo
    # (sin esperar al TTL de 60s).
    _invalidate_ia_mode_cache()

    logger.info(
        "wa_ia_mode actualizado a '%s' por user=%s",
        payload.mode, current_user.user_id,
    )
    return {"ok": True, "ia_mode": payload.mode}


@router.get("/_diagnostics/classifier")
async def diagnostics_classifier(
    current_user: TokenData = Depends(get_current_user),
):
    """Ping a Ollama con un prompt minimo. Retorna status + latencia.

    Util para diagnosticar por que una conversacion quedo stuck en
    'queued': si Ollama no responde desde el container, ninguna
    clasificacion pasa de 'queued' -> 'classified'.
    """
    if current_user.role != "admin":
        raise HTTPException(403, "Solo admin")

    import time
    result = {
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model":    settings.ollama_model,
        "reachable":       False,
        "latency_ms":      None,
        "error":           None,
        "sample_response": None,
    }
    t0 = time.monotonic()
    try:
        url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        payload = {
            "model":  settings.ollama_model,
            "prompt": 'Responde SOLO con JSON: {"ok": true}',
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 20},
        }
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            result["reachable"]       = True
            result["sample_response"] = data.get("response", "")[:200]
    except httpx.TimeoutException:
        result["error"] = "timeout (15s) — Ollama no responde desde el container"
    except httpx.ConnectError as exc:
        result["error"] = f"connect error: {exc} — URL o red mal configurada"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["latency_ms"] = int((time.monotonic() - t0) * 1000)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# UI labels editables — chips de Chat (category / urgency / inbox)
# ─────────────────────────────────────────────────────────────────────────────

import re as _re_ui_labels

_HEX_RE_UI = _re_ui_labels.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_ALLOWED_ICONS = {
    "Sparkles", "MessageCircle", "AlertCircle", "Archive", "Flame", "Clock",
    "Tag", "UserCheck", "Layers", "Wand2", "Check", "CheckCheck", "Send",
}


class UiLabelUpdate(BaseModel):
    label:      Optional[str] = None
    color_hex:  Optional[str] = None
    icon_name:  Optional[str] = None
    sort_order: Optional[int] = None
    activo:     Optional[bool] = None


@router.get("/ui-labels")
def list_ui_labels(current_user: TokenData = Depends(get_current_user)):
    """Lista los labels de chips (category/urgency/inbox). Todos los usuarios
    pueden leerlos porque el Chat.jsx los necesita para pintar la UI."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, kind, key, label, color_hex, icon_name, sort_order, activo
                FROM crm.wa_ui_labels
                ORDER BY kind, sort_order, id
                """
            )
            return cur.fetchall()


@router.patch("/ui-labels/{label_id}")
def update_ui_label(
    label_id: int,
    data: UiLabelUpdate,
    admin: TokenData = Depends(require_admin),
):
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    # Validaciones
    if "color_hex" in fields and not _HEX_RE_UI.match(fields["color_hex"]):
        raise HTTPException(status_code=400, detail="Color invalido, usa #RRGGBB")
    if "icon_name" in fields and fields["icon_name"] not in _ALLOWED_ICONS:
        raise HTTPException(
            status_code=400,
            detail=f"Icono no permitido. Opciones: {sorted(_ALLOWED_ICONS)}",
        )
    if "label" in fields:
        fields["label"] = fields["label"].strip()
        if not fields["label"]:
            raise HTTPException(status_code=400, detail="El label no puede quedar vacio")
        if len(fields["label"]) > 60:
            raise HTTPException(status_code=400, detail="Maximo 60 caracteres")

    allowed_cols = {"label", "color_hex", "icon_name", "sort_order", "activo"}
    set_parts = []
    params = []
    for k, v in fields.items():
        if k not in allowed_cols:
            continue
        set_parts.append(f"{k} = %s")
        params.append(v)
    if not set_parts:
        raise HTTPException(status_code=400, detail="Sin campos validos")
    params.append(label_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE crm.wa_ui_labels
                SET {', '.join(set_parts)}
                WHERE id = %s
                RETURNING id, kind, key, label, color_hex, icon_name, sort_order, activo
                """,
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Label no encontrado")
        conn.commit()
    return row


@router.post("/ui-labels/reset-defaults", status_code=200)
def reset_ui_labels_defaults(admin: TokenData = Depends(require_admin)):
    """Restaura los labels a los valores por defecto del seed. Util para
    recuperar la configuracion de fabrica si alguien la rompe."""
    defaults = [
        ('category', 'cliente_potencial', 'Potencial',      '#16a34a', 'Sparkles',     10),
        ('category', 'cliente_existente', 'Cliente',        '#6366f1', 'UserCheck',    20),
        ('category', 'consulta_general',  'Consulta',       '#0ea5e9', 'MessageCircle',30),
        ('category', 'spam',              'Spam',           '#6b7280', 'Archive',      40),
        ('category', 'no_relacionado',    'No relacionado', '#6b7280', 'Archive',      50),
        ('category', 'manual_review',     'Revisar',        '#f59e0b', 'AlertCircle',  60),
        ('category', 'pending',           'Clasificando',   '#64748b', 'Clock',        70),
        ('category', 'archived',          'Archivado',      '#6b7280', 'Archive',      80),
        ('category', 'skipped',           'Cliente',        '#6366f1', 'Sparkles',     90),
        ('urgency',  'alta',              'Urgente',        '#dc2626', 'Flame',        10),
        ('inbox',    'potenciales',       'Clientes potenciales',  '#16a34a', 'Sparkles',    10),
        ('inbox',    'revisar',           'Requieren revision',    '#f59e0b', 'AlertCircle', 20),
        ('inbox',    'sin_clasificar',    'Sin clasificar',        '#64748b', 'Clock',       30),
        ('inbox',    'delegar',           'Pendientes de delegar', '#8b5cf6', 'UserCheck',   40),
        ('inbox',    'archivados',        'Archivados',            '#6b7280', 'Archive',     50),
    ]
    with get_db() as conn:
        with conn.cursor() as cur:
            for kind, key, label, color, icon, sort in defaults:
                cur.execute(
                    """
                    UPDATE crm.wa_ui_labels
                    SET label = %s, color_hex = %s, icon_name = %s,
                        sort_order = %s, activo = TRUE
                    WHERE kind = %s AND key = %s
                    """,
                    (label, color, icon, sort, kind, key),
                )
        conn.commit()
    return {"message": "Labels restaurados a valores por defecto"}


# ─────────────────────────────────────────────────────────────────────────────
# NUMBERS — gestion de numeros propios (multi-linea, V033)
# ─────────────────────────────────────────────────────────────────────────────

class WaNumberCreate(BaseModel):
    phone_number_id: str = Field(..., min_length=5, max_length=60)
    display_phone:   Optional[str] = None
    display_name:    str = Field(..., min_length=1, max_length=100)
    waba_id:         Optional[str] = None
    waba_id_ref:     Optional[int] = Field(
        None,
        description="FK a crm.wa_babas.id — WABA que aloja este numero (V034)",
    )
    is_default:      bool = False


class WaNumberUpdate(BaseModel):
    display_phone:   Optional[str] = None
    display_name:    Optional[str] = None
    waba_id:         Optional[str] = None
    waba_id_ref:     Optional[int] = None
    activo:          Optional[bool] = None


@router.get("/numbers")
def list_wa_numbers(
    only_active: bool = Query(False),
    current_user: TokenData = Depends(get_current_user),
):
    """Lista numeros propios. Todo usuario autenticado puede leer."""
    from app.services import wa_numbers_service
    return {"items": wa_numbers_service.list_all(only_active=only_active)}


@router.get("/status")
def whatsapp_status(current_user: TokenData = Depends(get_current_user)):
    """Status check de configuracion WhatsApp Business — patron estandar.

    Lo consume el frontend (Chat y LeadDetalle) para decidir si:
      - Mostrar la UI funcional de chat
      - Mostrar empty state de onboarding ("conecta tu WhatsApp")
      - Habilitar / deshabilitar el boton WhatsApp en el detalle de lead

    Diseño:
      - Endpoint barato (1 EXISTS query) — pensado para llamarse en cada
        mount de pagina sin penalizar performance.
      - Payload minimo: solo booleanos + ids — NO expone phone_number_id ni
        credenciales (defense in depth: aunque el endpoint pide auth, no
        confiamos en eso para exponer datos sensibles).
      - SRP: delega la verdad a wa_numbers_service.has_sending_capability().
    """
    from app.services import wa_numbers_service
    has_capability = wa_numbers_service.has_sending_capability()
    default = wa_numbers_service.get_default() if has_capability else None
    return {
        "has_sending_capability": has_capability,
        "default_wa_number_id": default["id"] if default else None,
    }


@router.post("/numbers", status_code=201)
def create_wa_number(
    payload: WaNumberCreate,
    admin: TokenData = Depends(require_admin),
):
    """Registra un nuevo numero propio. Solo admin.

    waba_id_ref es obligatorio si existe al menos una WABA registrada —
    evita huerfanos que el webhook no podra resolver. Si aun no hay
    WABAs (primera instalacion pre-V034), se acepta sin FK.
    """
    from app.services import wa_numbers_service, wa_babas_service
    # Si ya hay WABAs, exigimos waba_id_ref
    existing_babas = wa_babas_service.list_all(only_active=False)
    if existing_babas and not payload.waba_id_ref:
        raise HTTPException(
            400,
            "Debes seleccionar una Cuenta Empresarial (WABA) para esta linea. "
            "Revisa Configuracion > WhatsApp > Cuentas Empresariales.",
        )
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO crm.wa_numbers
                        (phone_number_id, display_phone, display_name,
                         waba_id, waba_id_ref, is_default, activo)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                    RETURNING id, phone_number_id, display_phone, display_name,
                              waba_id, waba_id_ref, is_default, activo
                    """,
                    (
                        payload.phone_number_id,
                        payload.display_phone,
                        payload.display_name,
                        payload.waba_id,
                        payload.waba_id_ref,
                        payload.is_default,
                    ),
                )
                new_row = cur.fetchone()
                # Si es default, desmarcar cualquier otro
                if payload.is_default:
                    cur.execute(
                        "UPDATE crm.wa_numbers SET is_default = FALSE "
                        "WHERE is_default = TRUE AND id <> %s",
                        (new_row["id"],),
                    )
            conn.commit()
        wa_numbers_service.invalidate_cache()
        return dict(new_row)
    except psycopg2.IntegrityError as exc:
        raise HTTPException(409, "Ese phone_number_id ya esta registrado") from exc


@router.patch("/numbers/{number_id}")
def update_wa_number(
    number_id: int,
    payload: WaNumberUpdate,
    admin: TokenData = Depends(require_admin),
):
    """Actualiza display_name / activo / waba_id_ref / etc. Solo admin."""
    from app.services import wa_numbers_service, wa_babas_service
    fields = []
    values = []
    for key in ("display_phone", "display_name", "waba_id", "waba_id_ref", "activo"):
        val = getattr(payload, key)
        if val is not None:
            fields.append(f"{key} = %s")
            values.append(val)
    if not fields:
        raise HTTPException(400, "Nada que actualizar")
    fields.append("updated_at = NOW()")
    values.append(number_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.wa_numbers SET {', '.join(fields)} WHERE id = %s "
                f"RETURNING id, phone_number_id, display_phone, display_name, "
                f"         waba_id, waba_id_ref, is_default, activo",
                tuple(values),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "Numero no encontrado")
    wa_numbers_service.invalidate_cache()
    wa_babas_service.invalidate_cache()  # phone→baba lookup invalidado
    return dict(row)


@router.post("/numbers/{number_id}/set-default")
def set_default_wa_number(
    number_id: int,
    admin: TokenData = Depends(require_admin),
):
    """Marca el numero como default para envios sin contexto. Solo admin."""
    from app.services import wa_numbers_service
    ok = wa_numbers_service.set_default(number_id)
    if not ok:
        raise HTTPException(404, "Numero no encontrado")
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# BABAS — cuentas empresariales WhatsApp (multi-WABA, V034)
# ─────────────────────────────────────────────────────────────────────────────
# Una WABA agrupa uno o mas numeros y tiene sus propias credenciales
# (access_token, app_secret, webhook verify_token). Todos se almacenan
# cifrados en crm.wa_babas. La UI permite registrarlas sin tocar env vars.

class WaBabaCreate(BaseModel):
    waba_id:              str = Field(..., min_length=1, max_length=64,
                                      description="ID de la WhatsApp Business Account en Meta")
    display_name:         str = Field(..., min_length=1, max_length=100)
    access_token:         str = Field(..., min_length=10,
                                      description="Access Token permanente de Meta")
    app_secret:           str = Field("",
                                      description="App Secret (para validar firma webhook)")
    webhook_verify_token: str = Field("",
                                      description="Verify Token que registraste en Meta webhook")
    notes:                Optional[str] = None
    set_as_default:       bool = False


class WaBabaUpdate(BaseModel):
    display_name:         Optional[str] = None
    access_token:         Optional[str] = Field(
        None,
        description="Enviar solo si cambia. Vacio = borrar.",
    )
    app_secret:           Optional[str] = None
    webhook_verify_token: Optional[str] = None
    activo:               Optional[bool] = None
    notes:                Optional[str] = None


@router.get("/babas")
def list_wa_babas(
    only_active: bool = Query(False),
    current_user: TokenData = Depends(get_current_user),
):
    """Lista WABAs (sin plaintext de secretos). Todo usuario autenticado puede leer."""
    from app.services import wa_babas_service
    items = wa_babas_service.list_all(only_active=only_active)
    # Adjuntar cantidad de numeros por baba para la UI
    for b in items:
        b["numbers_count"] = wa_babas_service.count_numbers(b["id"])
    return {"items": items}


@router.post("/babas", status_code=201)
def create_wa_baba(
    payload: WaBabaCreate,
    admin: TokenData = Depends(require_admin),
):
    """Registra una WABA nueva con credenciales cifradas. Solo admin."""
    from app.services import wa_babas_service
    try:
        new_id = wa_babas_service.create(
            waba_id=payload.waba_id,
            display_name=payload.display_name,
            access_token=payload.access_token,
            app_secret=payload.app_secret or "",
            webhook_verify_token=payload.webhook_verify_token or "",
            notes=payload.notes,
            set_as_default=payload.set_as_default,
        )
    except psycopg2.IntegrityError as exc:
        raise HTTPException(409, "Ese waba_id ya esta registrado") from exc
    logger.info("wa_babas: admin=%s creo WABA id=%s name=%r",
                admin.user_id, new_id, payload.display_name)
    return wa_babas_service.get_by_id(new_id)


@router.patch("/babas/{baba_id}")
def update_wa_baba(
    baba_id: int,
    payload: WaBabaUpdate,
    admin: TokenData = Depends(require_admin),
):
    """Update parcial. Solo admin.

    Para los secretos:
      - campo ausente / null  → se preserva el valor actual
      - campo == ""           → se borra el secreto
      - valor no vacio        → se re-cifra y se reemplaza
    """
    from app.services import wa_babas_service
    ok = wa_babas_service.update(
        baba_id,
        display_name=payload.display_name,
        access_token=payload.access_token,
        app_secret=payload.app_secret,
        webhook_verify_token=payload.webhook_verify_token,
        activo=payload.activo,
        notes=payload.notes,
    )
    if not ok:
        raise HTTPException(404, "WABA no encontrada o nada que actualizar")
    logger.info("wa_babas: admin=%s actualizo WABA id=%s", admin.user_id, baba_id)
    return wa_babas_service.get_by_id(baba_id)


@router.post("/babas/{baba_id}/set-default")
def set_default_wa_baba(
    baba_id: int,
    admin: TokenData = Depends(require_admin),
):
    """Marca esta WABA como default (atomico — desmarca las demas). Solo admin."""
    from app.services import wa_babas_service
    ok = wa_babas_service.set_default(baba_id)
    if not ok:
        raise HTTPException(
            404,
            "WABA no encontrada o inactiva — activala antes de marcarla como default",
        )
    return {"ok": True}


@router.delete("/babas/{baba_id}", status_code=204)
def delete_wa_baba(
    baba_id: int,
    admin: TokenData = Depends(require_admin),
):
    """Elimina una WABA. Bloqueado si tiene numeros asociados (FK RESTRICT).

    El admin debe reasignar o eliminar los numeros antes. Solo admin.
    """
    from app.services import wa_babas_service
    count = wa_babas_service.count_numbers(baba_id)
    if count > 0:
        raise HTTPException(
            409,
            f"No se puede eliminar: esta WABA tiene {count} numero(s) asociado(s). "
            "Reasigna o elimina las lineas primero.",
        )
    ok = wa_babas_service.delete(baba_id)
    if not ok:
        raise HTTPException(404, "WABA no encontrada")
    logger.info("wa_babas: admin=%s elimino WABA id=%s", admin.user_id, baba_id)
    return None

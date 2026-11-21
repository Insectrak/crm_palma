"""Router del webhook nativo de Meta (Facebook & Instagram Lead Ads).

Endpoints:
  - GET  /api/integrations/meta/webhook    — handshake de suscripción.
  - POST /api/integrations/meta/webhook    — recepción de eventos leadgen.

Reglas operativas:
  - GET responde `hub.challenge` (text/plain) cuando `hub.verify_token` coincide
    con el `verify_token` guardado en credenciales (crm.integrations_credentials).
  - POST exige `X-Hub-Signature-256` válido contra el `app_secret` global.
    Si falla, responde 200 igual (Meta reintenta indefinidamente en 4xx/5xx)
    pero loggea un evento `error` y corta.
  - Ingesta real corre en BackgroundTasks para no bloquear la respuesta.
    Meta exige 200 OK en <20s; con BackgroundTasks el 200 es inmediato.

Diseño:
  - Router es transport: no hace HTTP ni parsing de dominio. Todo el work
    lo hace `services.integrations.meta_service`.
  - Nunca se loggea el app_secret ni el page_access_token. Eventos en
    `crm.integrations_events` referencian page_id y leadgen_id.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from psycopg2.extras import RealDictCursor

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.services.integrations import events_repo
from app.services.integrations.meta_service import (
    enrich_wa_campaign_by_ad_id,
    get_app_secret,
    get_verify_token,
    parse_leadgen_changes,
    process_leadgen_event,
    reprocess_skipped_leads,
    subscribe_page_to_webhook,
    verify_challenge_token,
    verify_signature,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrations/meta", tags=["Integraciones · Meta"])


# ─────────────────────────────────────────────────────────────────────────────
# GET — Handshake de suscripción
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/webhook")
def meta_webhook_verify(
    hub_mode:         Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge:    Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Challenge que Meta envía al suscribir el webhook.

    Responde el challenge en texto plano si el verify_token matchea con lo
    guardado en credenciales. Caso contrario, 403.
    """
    if hub_mode != "subscribe" or not hub_challenge:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    stored = get_verify_token()
    if not verify_challenge_token(hub_verify_token, stored):
        events_repo.log_event(
            provider="meta",
            event_type="webhook_verified",
            status="error",
            error_message="verify_token inválido o no configurado.",
        )
        return JSONResponse({"error": "forbidden"}, status_code=403)

    events_repo.log_event(
        provider="meta",
        event_type="webhook_verified",
        status="ok",
    )
    return PlainTextResponse(hub_challenge, status_code=200)


# ─────────────────────────────────────────────────────────────────────────────
# POST — Recepción de eventos
# ─────────────────────────────────────────────────────────────────────────────

async def _read_raw_body(request: Request) -> bytes:
    """Lee el body crudo (necesario para validar HMAC bit-a-bit)."""
    return await request.body()


def _handle_leadgen_change(change: dict) -> None:
    """Worker ejecutado en BackgroundTasks. Abre su propia conexión DB."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = process_leadgen_event(
                    cur,
                    leadgen_id=change["leadgen_id"],
                    page_id=change["page_id"],
                    form_id=change.get("form_id"),
                    ad_id=change.get("ad_id"),
                    adset_id=change.get("adset_id"),
                    campaign_id=change.get("campaign_id"),
                )
            conn.commit()
        logger.info(
            "meta leadgen processed: leadgen=%s page=%s result=%s",
            change["leadgen_id"], change["page_id"], result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("meta leadgen background error: %s", exc)
        events_repo.log_event(
            provider="meta",
            event_type="error",
            status="error",
            account_id=change.get("page_id"),
            external_id=change.get("leadgen_id"),
            error_message=f"background: {exc}",
        )


@router.post("/webhook")
async def meta_webhook_receive(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
):
    """Recibe eventos leagen. Verifica firma y encola procesamiento."""
    raw = await _read_raw_body(request)

    app_secret = get_app_secret()
    if not app_secret:
        events_repo.log_event(
            provider="meta",
            event_type="webhook_received",
            status="error",
            error_message="app_secret no configurado.",
        )
        # 200 para que Meta no reintente indefinidamente.
        return JSONResponse({"ok": False, "reason": "app_secret_missing"}, status_code=200)

    if not verify_signature(raw, x_hub_signature_256, app_secret):
        events_repo.log_event(
            provider="meta",
            event_type="webhook_received",
            status="error",
            error_message="firma HMAC inválida.",
        )
        # 403 sí: firma mala == intento potencialmente malicioso.
        return JSONResponse({"ok": False, "reason": "bad_signature"}, status_code=403)

    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        events_repo.log_event(
            provider="meta",
            event_type="webhook_received",
            status="error",
            error_message=f"JSON inválido: {exc}",
        )
        return JSONResponse({"ok": False, "reason": "bad_json"}, status_code=200)

    changes = parse_leadgen_changes(body)

    events_repo.log_event(
        provider="meta",
        event_type="webhook_received",
        status="ok",
        raw_payload={"changes": len(changes)},
    )

    for ch in changes:
        background.add_task(_handle_leadgen_change, ch)

    # Meta espera 200 rápido; el procesamiento real vive en background.
    return JSONResponse({"ok": True, "queued": len(changes)}, status_code=200)


# ─────────────────────────────────────────────────────────────────────────────
# Admin — suscribir página al webhook desde el CRM
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/accounts/{page_id}/subscribe")
def meta_subscribe_page(
    page_id: str = Path(..., min_length=1, max_length=120),
    _: TokenData = Depends(require_admin),
):
    """Dispara POST /{page_id}/subscribed_apps?subscribed_fields=leadgen
    usando el page_access_token guardado. Endpoint admin-only.

    Evita que el usuario tenga que ir al Graph API Explorer manualmente:
    el backend tiene el PAT encriptado y lo usa one-shot. El resultado se
    loggea en `crm.integrations_events` con event_type=`page_subscribe`.
    """
    result = subscribe_page_to_webhook(page_id)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Admin — listar wa_campaigns con estado de enrichment (diagnostico)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/wa-campaigns")
def meta_list_wa_campaigns(
    only_unenriched: bool = Query(False, description="Si True, solo las que tienen ad_name NULL."),
    limit: int = Query(50, ge=1, le=500),
    _: TokenData = Depends(require_admin),
):
    """Lista wa_campaigns con su estado de enrichment Meta. Util para
    diagnosticar por que el banner del chat sigue mostrando el headline
    crudo en vez del nombre real del ad de Ads Manager.

    Para cada fila devuelve:
      - id, name (display), ad_id
      - meta_ad_name, meta_adset_name, meta_campaign_name (de Graph API)
      - enriched_at, enrich_error
      - leads_count (cuantos leads tienen wa_campaign_id apuntando aqui)
    """
    where = "WHERE cam.ad_name IS NULL" if only_unenriched else ""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT cam.id,
                       cam.name,
                       cam.ad_id,
                       cam.ad_name           AS meta_ad_name,
                       cam.adset_name        AS meta_adset_name,
                       cam.meta_campaign_name,
                       cam.enriched_at,
                       cam.enrich_error,
                       cam.created_at,
                       (SELECT COUNT(*) FROM crm.leads l
                          WHERE l.wa_campaign_id = cam.id) AS leads_count
                  FROM crm.wa_campaigns cam
                  {where}
                  ORDER BY cam.created_at DESC
                  LIMIT %s
                """,
                (limit,),
            )
            return {"items": cur.fetchall()}


# ─────────────────────────────────────────────────────────────────────────────
# Admin — enrichment manual de jerarquia Meta para una wa_campaign (CTWA)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/wa-campaigns/{campaign_id}/enrich")
def meta_enrich_wa_campaign(
    campaign_id: int = Path(..., ge=1),
    force: bool = Query(True, description="Si True, ignora el cache (re-fetch a Graph)."),
    admin: TokenData = Depends(require_admin),
):
    """Fuerza el enrichment de ad_name / adset_name / meta_campaign_name para
    una fila de crm.wa_campaigns. Util cuando el usuario acaba de renombrar
    el anuncio/campana en Ads Manager y quiere que el CRM refleje el cambio.

    Requiere credencial `meta.ads_access_token` (System User Token con scope
    `ads_read`). Si no esta configurada, devuelve 400 con reason='no_token'.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT ad_id FROM crm.wa_campaigns WHERE id = %s",
                (campaign_id,),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse({"ok": False, "reason": "wa_campaign_not_found"}, status_code=404)
    ad_id = row["ad_id"]
    if not ad_id:
        return JSONResponse({"ok": False, "reason": "wa_campaign_has_no_ad_id"}, status_code=400)

    logger.info(
        "meta.enrich_wa_campaign id=%s ad_id=%s triggered_by=%s force=%s",
        campaign_id, ad_id, admin.email, force,
    )
    result = enrich_wa_campaign_by_ad_id(ad_id, force=force)
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Admin — diagnostico raw: pide a Graph TODOS los campos posibles del ad
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_RAW_GRAPH_FIELDS = (
    "id,name,status,effective_status,source_ad_id,created_time,updated_time,"
    "account_id,bid_amount,"
    "creative{id,name,body,title,object_type,effective_object_story_id,object_story_spec},"
    "campaign{id,name,objective,status,effective_status},"
    "adset{id,name,status,effective_status}"
)


@router.get("/wa-campaigns/{campaign_id}/raw-graph")
def meta_wa_campaign_raw_graph(
    campaign_id: int = Path(..., ge=1),
    fields: Optional[str] = Query(
        None,
        description=(
            "Override de fields a pedirle a Graph. Util para diagnosticar "
            "si el source_id es un page post (probar con "
            "'id,message,created_time,permalink_url,attachments') vs un ad."
        ),
    ),
    _: TokenData = Depends(require_admin),
):
    """Llama Graph API con un set ancho de fields y devuelve el JSON crudo.

    Solo para diagnostico: cuando el enrich devuelve solo `ad.name` y todo lo
    demas null, esto nos dice si el ad es boosted post (sin adset/campaign),
    si tiene `source_ad_id`, si el creative existe pero esta restringido, etc.

    Nunca incluye el access_token en la respuesta. Requiere admin.
    """
    import httpx
    from app.services.integrations.meta_service import get_ads_access_token

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT ad_id FROM crm.wa_campaigns WHERE id = %s",
                (campaign_id,),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse({"ok": False, "reason": "wa_campaign_not_found"}, status_code=404)
    ad_id = row["ad_id"]
    if not ad_id:
        return JSONResponse({"ok": False, "reason": "wa_campaign_has_no_ad_id"}, status_code=400)

    token = get_ads_access_token()
    if not token:
        return JSONResponse({"ok": False, "reason": "no_token"}, status_code=400)

    fields_used = (fields or _DEFAULT_RAW_GRAPH_FIELDS).strip()
    url = f"https://graph.facebook.com/v20.0/{ad_id}"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params={"access_token": token, "fields": fields_used})
        body = resp.json() if resp.content else {}
    except Exception as exc:  # noqa: BLE001 — endpoint diagnostico
        return JSONResponse(
            {"ok": False, "reason": "http_error", "error": str(exc)},
            status_code=502,
        )
    return JSONResponse({
        "ok":          resp.status_code == 200 and "error" not in body,
        "ad_id":       ad_id,
        "http_status": resp.status_code,
        "fields_used": fields_used,
        "raw":         body,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Admin — leads atribuidos a una wa_campaign (diagnostico)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/wa-campaigns/{campaign_id}/leads")
def meta_list_wa_campaign_leads(
    campaign_id: int = Path(..., ge=1),
    limit: int = Query(50, ge=1, le=500),
    _: TokenData = Depends(require_admin),
):
    """Lista los leads atribuidos a una wa_campaign con su estado actual.

    Util para diagnosticar por que un lead CTWA no aparece en la pagina Leads:
    puede estar con `activo=FALSE`, sin asesor, en estado terminal, o el
    role_filter del usuario lo esta filtrando. Devolvemos los datos crudos
    para que el admin pueda confirmar el motivo en una sola llamada.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT l.id,
                       l.nombres,
                       l.apellidos,
                       l.telefono,
                       l.estado_id,
                       el.nombre AS estado_nombre,
                       l.asesor_id,
                       COALESCE(u.advisor_name,
                                NULLIF(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')), ''),
                                u.email) AS asesor_nombre,
                       l.fuente_id,
                       f.nombre AS fuente_nombre,
                       l.activo,
                       l.wa_campaign_id,
                       l.wa_campaign_ad_id,
                       l.created_at,
                       l.updated_at
                  FROM crm.leads l
                  LEFT JOIN crm.estados_lead el ON el.id = l.estado_id
                  LEFT JOIN crm.fuentes      f  ON f.id  = l.fuente_id
                  LEFT JOIN auth.users       u  ON u.id  = l.asesor_id
                 WHERE l.wa_campaign_id = %s
                 ORDER BY l.created_at DESC
                 LIMIT %s
                """,
                (campaign_id, limit),
            )
            return {"items": cur.fetchall()}


@router.post("/reprocess-skipped")
def meta_reprocess_skipped(
    _: TokenData = Depends(require_admin),
):
    """Re-procesa todos los leads de Meta omitidos previamente por falta de teléfono."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            res = reprocess_skipped_leads(cur)
            conn.commit()
            return res

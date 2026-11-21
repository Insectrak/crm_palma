"""Resolución cacheada de nombres del catálogo de Meta.

El webhook de Lead Ads solo trae IDs (`campaign_id`, `form_id`, `ad_id`).
La UI y los reportes necesitan nombres legibles. Este módulo:

1. Consulta `crm.meta_catalog_cache` por (entity_type, entity_id).
2. Si no existe o está stale (>7 días), hace `GET /{id}?fields=name` al
   Graph API usando el `page_access_token` de la fan page.
3. Persiste el resultado (ok / not_found / error) para la próxima vez.

Diseño:
  - SRP: este módulo solo resuelve nombres. No toca leads ni interacciones.
  - Tolerante a fallos: si Graph API falla (permisos, red, 404), devuelve
    `None` y loggea — nunca rompe el flujo de ingesta.
  - Idempotente: `ON CONFLICT (entity_type, entity_id) DO UPDATE` para
    que múltiples webhooks paralelos del mismo ID no generen duplicados.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

import httpx

from app.database import get_db
from app.services.integrations import credentials_repo

logger = logging.getLogger(__name__)

META_GRAPH_VERSION = "v20.0"
META_GRAPH_BASE = f"https://graph.facebook.com/{META_GRAPH_VERSION}"

_HTTP_TIMEOUT = 5.0          # fetch rápido — corre en BackgroundTask, no bloquea el 200.
_STALE_AFTER_DAYS = 7        # refresca nombres cada semana (marketing puede renombrar).
_MAX_FETCH_RETRIES = 1       # 1 reintento ante 5xx; errores 4xx no se reintentan.


# ─────────────────────────────────────────────────────────────────────────────
# Cache (lectura / escritura)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_cached(cur, entity_type: str, entity_id: str) -> Optional[dict]:
    cur.execute(
        """
        SELECT name, fetch_status, fetched_at,
               EXTRACT(EPOCH FROM (NOW() - fetched_at))/86400 AS age_days
          FROM crm.meta_catalog_cache
         WHERE entity_type = %s AND entity_id = %s
        """,
        (entity_type, entity_id),
    )
    return cur.fetchone()


def _upsert_cache(
    cur,
    *,
    entity_type: str,
    entity_id: str,
    name: Optional[str],
    page_id: Optional[str],
    fetch_status: str,
    error_message: Optional[str] = None,
) -> None:
    cur.execute(
        """
        INSERT INTO crm.meta_catalog_cache
            (entity_type, entity_id, name, page_id, fetch_status, error_message, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (entity_type, entity_id) DO UPDATE
        SET name          = EXCLUDED.name,
            page_id       = COALESCE(EXCLUDED.page_id, crm.meta_catalog_cache.page_id),
            fetch_status  = EXCLUDED.fetch_status,
            error_message = EXCLUDED.error_message,
            fetched_at    = NOW()
        """,
        (entity_type, entity_id, name, page_id, fetch_status, error_message),
    )


def hydrate_from_provider(
    cur,
    *,
    entity_type: str,
    entity_id: Optional[str],
    name: Optional[str],
) -> bool:
    """V096.5 — Write-through cache para datos que vienen del payload del
    proveedor (Wedo, Meta nativo, TikTok, etc.).

    Cuando un proveedor envía `(campana, campaign_name)` o
    `(fuente_form_id, form_name)`, este helper persiste el par en
    `meta_catalog_cache` para que la UI y el webhook puedan resolver el
    nombre legible despues vía JOIN.

    Por que existe (vs `_upsert_cache` privado):
      - `_upsert_cache` es para el resolver del Graph API (con page_id,
        fetch_status='ok'/'not_found'/'error'). Forma parte del flujo
        async de fetch_and_resolve.
      - `hydrate_from_provider` es para callers que YA tienen el nombre
        a mano (ingest_lead_core, lead_recapture.handle_recontacto). No
        hace Graph API call, no necesita page_id.

    Best-effort: silencia errores (no debe romper el flujo de ingest).
    Devuelve True si hidrato algo, False si no aplicaba (id o name vacio)
    o si hubo error.
    """
    eid = (entity_id or "").strip()
    nm = (name or "").strip()
    if not eid or not nm:
        return False
    try:
        _upsert_cache(
            cur,
            entity_type=entity_type,
            entity_id=eid,
            name=nm,
            page_id=None,
            fetch_status="ok",
            error_message=None,
        )
        return True
    except Exception:  # noqa: BLE001 — write-through NUNCA rompe el caller
        logger.exception(
            "[meta_catalog] hydrate_from_provider fallo (type=%s id=%s)",
            entity_type, eid,
        )
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Graph API: GET /{id}?fields=name
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_name_from_graph(
    entity_id: str,
    access_token: str,
    *,
    client: Optional[httpx.Client] = None,
) -> tuple[Optional[str], str, Optional[str]]:
    """Devuelve (name, status, error_message).

    status ∈ {'ok', 'not_found', 'error'}.
    """
    url = f"{META_GRAPH_BASE}/{entity_id}"
    params = {"access_token": access_token, "fields": "name"}

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=_HTTP_TIMEOUT)
    try:
        for attempt in range(_MAX_FETCH_RETRIES + 1):
            try:
                resp = client.get(url, params=params)
            except httpx.HTTPError as exc:
                if attempt < _MAX_FETCH_RETRIES:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                return None, "error", f"http: {exc}"

            if resp.status_code == 200:
                data = resp.json() if resp.content else {}
                name = (data.get("name") or "").strip() or None
                return name, "ok", None

            if resp.status_code in (400, 403, 404):
                # 400 Object does not exist / 403 sin permisos / 404 — no reintentar.
                return None, "not_found", f"HTTP {resp.status_code}: {resp.text[:150]}"

            if resp.status_code >= 500 and attempt < _MAX_FETCH_RETRIES:
                time.sleep(0.3 * (attempt + 1))
                continue

            return None, "error", f"HTTP {resp.status_code}: {resp.text[:150]}"
        return None, "error", "retries_exhausted"
    finally:
        if own_client:
            client.close()


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────

def resolve_name(
    cur,
    *,
    entity_type: str,
    entity_id: Optional[str],
    page_id: Optional[str] = None,
    access_token: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> Optional[str]:
    """Devuelve el nombre legible del entity_id (campaign/form/ad/adset).

    Si está en cache y fresco → devuelve el nombre.
    Si no existe o está stale → fetch a Graph API (requiere page_id para
    resolver el page_access_token). Si no hay page_id o el fetch falla,
    devuelve None y marca el cache con el estado correspondiente.

    El caller puede pasar `access_token` ya resuelto para evitar una
    segunda consulta a `integrations_credentials` (y para que los tests
    no necesiten un pool de DB activo).
    """
    if not entity_id:
        return None
    entity_type = entity_type.strip().lower()
    if entity_type not in {"campaign", "form", "ad", "adset"}:
        return None

    try:
        cached = _fetch_cached(cur, entity_type, entity_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta_catalog: fallo leyendo cache %s=%s: %s",
                       entity_type, entity_id, exc)
        return None

    if cached:
        age = cached.get("age_days") or 0
        status = cached.get("fetch_status")
        if status == "ok" and age < _STALE_AFTER_DAYS:
            return cached.get("name")
        # 'not_found' no se reintenta — Meta ya dijo que no existe o no hay permisos.
        if status == "not_found":
            return None
        # 'ok' stale o 'error' previo → intentar refrescar abajo.

    # Necesitamos page_access_token para llamar Graph API.
    if not page_id:
        return cached.get("name") if cached else None

    if not access_token:
        try:
            access_token = credentials_repo.get_plaintext(
                "meta", "page_access_token", page_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("meta_catalog: fallo obteniendo token page=%s: %s",
                           page_id, exc)
            return cached.get("name") if cached else None
    if not access_token:
        return cached.get("name") if cached else None

    name, status, err = _fetch_name_from_graph(entity_id, access_token, client=client)
    try:
        _upsert_cache(
            cur,
            entity_type=entity_type,
            entity_id=entity_id,
            name=name,
            page_id=page_id,
            fetch_status=status,
            error_message=err,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta_catalog: fallo guardando cache %s=%s: %s",
                       entity_type, entity_id, exc)
    return name


def _empty_debug() -> dict:
    return {
        "http_status":         None,
        "body":                None,
        "error":               None,
        "graph_error_code":    None,
        "graph_error_message": None,
    }


def _call_graph_ad(
    client: httpx.Client,
    *,
    ad_id: str,
    access_token: str,
    fields: str,
) -> tuple[Optional[dict], dict]:
    """Una sola request HTTP al endpoint /{ad_id}. Devuelve (data, debug).

    Maneja retries para 5xx y errores de transporte. Para 4xx parsea el
    `error.code`/`error.message` de Graph y lo expone en debug — el caller
    decide si reintentar con fields distintos o rendirse.
    """
    debug = _empty_debug()
    url = f"{META_GRAPH_BASE}/{ad_id}"
    params = {"access_token": access_token, "fields": fields}

    resp = None
    for attempt in range(_MAX_FETCH_RETRIES + 1):
        try:
            resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            if attempt < _MAX_FETCH_RETRIES:
                time.sleep(0.3 * (attempt + 1))
                continue
            logger.warning("meta_catalog.ad_hierarchy http error ad=%s: %s", ad_id, exc)
            debug["error"] = f"http: {exc}"
            return None, debug

        if resp.status_code == 200:
            break
        if resp.status_code >= 500 and attempt < _MAX_FETCH_RETRIES:
            time.sleep(0.3 * (attempt + 1))
            continue

        logger.warning(
            "meta_catalog.ad_hierarchy HTTP %s ad=%s fields=%s body=%s",
            resp.status_code, ad_id, fields, resp.text[:150],
        )
        debug["http_status"] = resp.status_code
        debug["body"] = resp.text[:400] if resp.content else None
        try:
            err = (resp.json() or {}).get("error") or {}
            debug["graph_error_code"] = err.get("code")
            debug["graph_error_message"] = err.get("message")
        except (ValueError, AttributeError):
            pass
        return None, debug

    if resp is None or resp.status_code != 200:
        debug["http_status"] = resp.status_code if resp else None
        debug["error"] = "no_response"
        return None, debug

    debug["http_status"] = 200
    data = resp.json() if resp.content else {}
    return data, debug


def _is_nonexisting_field_error(debug: dict) -> bool:
    """Meta devuelve code=100 'Tried accessing nonexisting field (X)' cuando
    pides un campo que el ad no expone (ej: ads CTWA/boosted sin adset).
    En ese caso reintentar con menos fields rescata al menos el ad_name.
    """
    if debug.get("graph_error_code") != 100:
        return False
    msg = (debug.get("graph_error_message") or "").lower()
    return "nonexisting field" in msg or "nonexistent field" in msg


# Fields tiered. Tier 0 pide todo lo visual del creative que Meta expone:
#   - thumbnail_url: preview pequeño (~200px), disponible casi siempre incluso
#     para boosted posts. Es la fuente primaria del preview visual.
#   - image_url / video_id: solo aparecen para ads estructurados con media
#     directa. Informativos — permiten distinguir image vs video ads.
#   - object_type: 'SHARE' suele indicar boosted post reusando un page post;
#     otros valores son PHOTO, VIDEO, etc.
#   - effective_object_story_id: para boosted posts, el id del page post
#     original. Fallback para scrape via Page Graph API si falta thumbnail.
_FIELD_TIERS = (
    "name,adset{id,name},campaign{id,name},"
    "creative{id,body,title,thumbnail_url,image_url,video_id,object_type,effective_object_story_id}",
    "name,campaign{id,name},"
    "creative{id,body,title,thumbnail_url,image_url,video_id,object_type,effective_object_story_id}",
    "name,campaign{id,name},creative{id,body,title}",
    "name,campaign{id,name}",
    "name",
)


def _fetch_ad_hierarchy_raw(
    cur,
    *,
    ad_id: str,
    access_token: str,
    client: Optional[httpx.Client] = None,
) -> tuple[Optional[dict], dict]:
    """Hace la request a Graph API y devuelve (hierarchy, debug).

    Estrategia tiered: probar fields cada vez mas chicos, asi rescatamos lo
    maximo posible incluso para ads CTWA/boosted que no exponen adset o
    creative completo. Cada nivel se reintenta solo si el anterior fallo
    con `code=100 nonexisting field`.

      1. name + adset{id,name} + campaign{id,name} + creative{id,body,title}
      2. sin adset (ads CTWA tipicamente la rechazan)
      3. sin creative (algunos ads legacy)
      4. solo name

    debug siempre incluye:
        {"http_status", "body", "error", "graph_error_code",
         "graph_error_message", "fields_used", "tier"}

    El caller decide si exponerlo o ignorarlo.
    """
    if not ad_id or not access_token:
        debug = _empty_debug()
        debug["error"] = "missing_ad_id_or_token"
        return None, debug

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=_HTTP_TIMEOUT)
    try:
        data = None
        debug = _empty_debug()
        for tier_idx, fields in enumerate(_FIELD_TIERS):
            data, attempt_debug = _call_graph_ad(
                client,
                ad_id=ad_id,
                access_token=access_token,
                fields=fields,
            )
            # Conservamos siempre el debug del PRIMER intento (asi el admin ve
            # cual fue la causa raiz aunque haya fallback exitoso despues),
            # pero anotamos cual tier cerro el caso.
            if tier_idx == 0:
                debug = attempt_debug
            debug["fields_used"] = fields
            debug["tier"] = tier_idx
            if data is not None:
                if tier_idx > 0:
                    logger.info(
                        "meta_catalog.ad_hierarchy fallback ok ad=%s tier=%d fields=%r",
                        ad_id, tier_idx, fields,
                    )
                    debug["http_status"] = 200  # success final
                break
            # Solo reintentamos si fue code=100 'nonexisting field'.
            # Otros errores (auth, rate-limit, 5xx) no se arreglan con menos fields.
            if not _is_nonexisting_field_error(attempt_debug):
                break
            logger.info(
                "meta_catalog.ad_hierarchy tier=%d ad=%s failed (%s); trying smaller fields",
                tier_idx, ad_id, attempt_debug.get("graph_error_message"),
            )
    finally:
        if own_client:
            client.close()

    if data is None:
        return None, debug

    ad_name       = (data.get("name") or "").strip() or None
    adset         = data.get("adset") or {}
    adset_id      = str(adset.get("id") or "").strip() or None
    adset_name    = (adset.get("name") or "").strip() or None
    campaign      = data.get("campaign") or {}
    campaign_id   = str(campaign.get("id") or "").strip() or None
    campaign_name = (campaign.get("name") or "").strip() or None
    creative      = data.get("creative") or {}
    creative_body = (creative.get("body") or "").strip() or None
    creative_title = (creative.get("title") or "").strip() or None

    # V037: campos visuales del creative. Cada uno es opcional — los ads
    # legacy/restringidos pueden no exponer ninguno. El caller decide
    # si hay material suficiente para cachear un preview.
    creative_thumbnail_url = (creative.get("thumbnail_url") or "").strip() or None
    creative_image_url     = (creative.get("image_url") or "").strip() or None
    creative_video_id      = str(creative.get("video_id") or "").strip() or None
    creative_object_type   = (creative.get("object_type") or "").strip() or None
    creative_object_story_id = (
        str(creative.get("effective_object_story_id") or "").strip() or None
    )

    # Derivamos media_type de alto nivel para simplificar el UI:
    #   'video'  si hay video_id
    #   'image'  si hay image_url
    #   'post'   si solo hay object_story_id (boosted post sin media directa)
    #   'thumbnail' si solo tenemos thumbnail_url
    #   None     si no hay nada visual
    if creative_video_id:
        creative_media_type = "video"
    elif creative_image_url:
        creative_media_type = "image"
    elif creative_object_story_id:
        creative_media_type = "post"
    elif creative_thumbnail_url:
        creative_media_type = "thumbnail"
    else:
        creative_media_type = None

    # Persistir en cache — cada entity se cachea de forma independiente.
    for entity_type, entity_id, name in (
        ("ad",       ad_id,       ad_name),
        ("adset",    adset_id,    adset_name),
        ("campaign", campaign_id, campaign_name),
    ):
        if not entity_id:
            continue
        try:
            _upsert_cache(
                cur,
                entity_type=entity_type,
                entity_id=entity_id,
                name=name,
                page_id=None,
                fetch_status="ok" if name else "not_found",
                error_message=None if name else "graph returned empty name",
            )
        except Exception as exc:  # noqa: BLE001 — cache best-effort
            logger.warning(
                "meta_catalog.ad_hierarchy: fallo cacheando %s=%s: %s",
                entity_type, entity_id, exc,
            )

    return {
        "ad_name":        ad_name,
        "adset_id":       adset_id,
        "adset_name":     adset_name,
        "campaign_id":    campaign_id,
        "campaign_name":  campaign_name,
        "creative_body":  creative_body,
        "creative_title": creative_title,
        # V037: campos visuales del creative. Keys siempre presentes (None si vacio)
        # para que el caller pueda hacer .get() sin branching.
        "creative_thumbnail_url":   creative_thumbnail_url,
        "creative_image_url":       creative_image_url,
        "creative_video_id":        creative_video_id,
        "creative_object_type":     creative_object_type,
        "creative_object_story_id": creative_object_story_id,
        "creative_media_type":      creative_media_type,
    }, debug


def resolve_ad_hierarchy(
    cur,
    *,
    ad_id: str,
    access_token: str,
    client: Optional[httpx.Client] = None,
) -> Optional[dict]:
    """Resuelve la jerarquia completa de un anuncio Meta en una sola request.

    GET /{ad_id}?fields=name,adset{id,name},campaign{id,name}

    Uso primario: al recibir un referral CTWA (WhatsApp webhook) el unico dato
    de atribucion es el `source_id` = ad_id. Con esta llamada obtenemos el
    nombre real del ad + adset + campana configurados en Ads Manager, que NO
    viajan en el payload del webhook.

    Devuelve dict con:
        {"ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name"}
    o None si Graph API devolvio error.

    Ademas upsertea las 3 filas en crm.meta_catalog_cache para reuso futuro.

    Nota sobre el access_token: este endpoint requiere permiso `ads_read`.
    El `page_access_token` estandar NO lo tiene — hay que usar un System User
    Token o un token con el scope explicito. El caller es responsable de
    proveer el token correcto (lo levanta desde credentials_repo, key
    `ads_access_token`).
    """
    hierarchy, _debug = _fetch_ad_hierarchy_raw(
        cur, ad_id=ad_id, access_token=access_token, client=client,
    )
    return hierarchy


def resolve_ad_hierarchy_with_debug(
    cur,
    *,
    ad_id: str,
    access_token: str,
    client: Optional[httpx.Client] = None,
) -> tuple[Optional[dict], dict]:
    """Como `resolve_ad_hierarchy` pero ademas devuelve `debug` con HTTP status,
    body crudo y `error.code`/`error.message` de Graph API. Util para endpoints
    diagnosticos que necesitan exponer al admin POR QUE Meta rechaza el token
    (scope faltante, ad inexistente, token expirado, etc.).
    """
    return _fetch_ad_hierarchy_raw(
        cur, ad_id=ad_id, access_token=access_token, client=client,
    )


def refresh_names_batch(
    page_id: str,
    entries: Iterable[tuple[str, str]],
) -> dict:
    """Refresca nombres para una lista de (entity_type, entity_id).

    Abre su propia conexión. Útil para mantenimiento / scripts.
    Devuelve dict con contadores {ok, error, skipped}.
    """
    ok = err = skipped = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                for entity_type, entity_id in entries:
                    if not entity_id:
                        skipped += 1
                        continue
                    name = resolve_name(
                        cur,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        page_id=page_id,
                        client=client,
                    )
                    if name:
                        ok += 1
                    else:
                        err += 1
            conn.commit()
    return {"ok": ok, "error": err, "skipped": skipped}

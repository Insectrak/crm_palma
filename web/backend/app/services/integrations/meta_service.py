"""Driver de la integración con Meta (Facebook + Instagram Lead Ads).

Responsable de:
  - Verificar la firma HMAC-SHA256 de los webhooks (header X-Hub-Signature-256).
  - Verificar el challenge de suscripción (verify_token) contra lo almacenado.
  - Parsear el payload estándar de `leadgen` y encolar el fetch del detalle.
  - Obtener el detalle del lead desde Graph API usando el page_access_token.
  - Normalizar los campos de Meta (`field_data: [{name, values}]`) al
    `IngestPayload` que consume `ingest_lead_core`.
  - Orquestar el flujo completo (fetch → normalize → ingest → log event).

Clean Code / SOLID:
  - SRP: este módulo no conoce HTTP (routers) ni DB (lo ve solo por
    `credentials_repo` / `ingest_core` / `events_repo`).
  - Sin logs de secretos: jamás se imprime un token plano; solo fingerprints.
  - Timing-safe: todas las comparaciones de secretos usan
    `hmac.compare_digest` para evitar ataques por canal lateral.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone  # V068.7: needed for type hints _parse_meta_created_time
from typing import Any, Iterable, Optional

import httpx
from psycopg2.extras import Json

from app.database import get_db
from app.services.integrations import (
    credentials_repo,
    creative_media_service,
    events_repo,
    field_mappings_repo,
    meta_catalog,
)
from app.services.integrations.credentials_repo import GLOBAL_ACCOUNT
from app.services.integrations.ingest_core import (
    IngestError,
    IngestPayload,
    ingest_lead_core,
)

logger = logging.getLogger(__name__)

# Versión fijada de Graph API — los cambios de versión se hacen en bump
# explícito para controlar compatibilidad.
META_GRAPH_VERSION = "v20.0"
META_GRAPH_BASE = f"https://graph.facebook.com/{META_GRAPH_VERSION}"

# Timeout conservador: el webhook de Meta espera 200 OK en <20s. Como
# el fetch lo hacemos en background, este timeout aplica solo al fetch.
_HTTP_TIMEOUT = 10.0

# Máximo de intentos de fetch ante error transitorio (5xx / timeout).
_MAX_FETCH_RETRIES = 2

_FUENTE_DEFAULT = "facebook"


# ─────────────────────────────────────────────────────────────────────────────
# Verificación de firma y challenge
# ─────────────────────────────────────────────────────────────────────────────

def verify_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    app_secret: Optional[str],
) -> bool:
    """Valida `X-Hub-Signature-256: sha256=<hex>` contra el app_secret.

    Timing-safe vía `hmac.compare_digest`. Si falta header, secreto o
    formato no esperado → False.
    """
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False
    received = signature_header.split("=", 1)[1].strip().lower()
    if not received:
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def verify_challenge_token(received_token: Optional[str], stored_token: Optional[str]) -> bool:
    """Compara el `hub.verify_token` del GET de verificación. Timing-safe."""
    if not received_token or not stored_token:
        return False
    return hmac.compare_digest(received_token, stored_token)


# ─────────────────────────────────────────────────────────────────────────────
# Parsing del webhook
# ─────────────────────────────────────────────────────────────────────────────

def parse_leadgen_changes(body: dict) -> list[dict]:
    """Extrae entries de tipo `leadgen` del body estándar de Meta.

    Shape típico recibido:
    {
      "object": "page",
      "entry": [
        {
          "id": "<page_id>",
          "time": ...,
          "changes": [
            {
              "field": "leadgen",
              "value": {
                "leadgen_id": "...",
                "page_id": "...",
                "form_id": "...",
                "created_time": ...,
                "ad_id": "...",
                "adset_id": "...",
                "campaign_id": "..."
              }
            }
          ]
        }
      ]
    }

    Devuelve una lista plana con las keys: leadgen_id, page_id, form_id,
    ad_id, adset_id, campaign_id, created_time. Se descartan silenciosamente
    entradas sin leadgen_id o sin page_id.
    """
    out: list[dict] = []
    if not isinstance(body, dict):
        return out
    for entry in body.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        # page_id principal del entry (fallback si el value no lo trae)
        entry_page_id = str(entry.get("id") or "").strip()
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            if change.get("field") != "leadgen":
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            leadgen_id = str(value.get("leadgen_id") or "").strip()
            page_id = str(value.get("page_id") or entry_page_id or "").strip()
            if not leadgen_id or not page_id:
                continue
            out.append({
                "leadgen_id":   leadgen_id,
                "page_id":      page_id,
                "form_id":      str(value.get("form_id") or "").strip() or None,
                "ad_id":        str(value.get("ad_id") or "").strip() or None,
                "adset_id":     str(value.get("adset_id") or "").strip() or None,
                "campaign_id":  str(value.get("campaign_id") or "").strip() or None,
                "created_time": value.get("created_time"),
            })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Graph API: fetch del detalle del lead
# ─────────────────────────────────────────────────────────────────────────────

class MetaFetchError(Exception):
    """Error al consultar Graph API (HTTP, timeout, payload inesperado)."""


def fetch_lead_details(
    leadgen_id: str,
    page_access_token: str,
    *,
    client: Optional[httpx.Client] = None,
) -> dict:
    """GET /{leadgen_id}?fields=field_data,created_time,ad_id,... → dict.

    Parámetro `client` existe solo para inyección en tests.
    Hace hasta `_MAX_FETCH_RETRIES` reintentos con backoff ante 5xx / timeout.
    """
    if not leadgen_id or not page_access_token:
        raise MetaFetchError("leadgen_id o page_access_token vacío.")

    url = f"{META_GRAPH_BASE}/{leadgen_id}"
    params = {
        "access_token": page_access_token,
        "fields":       "id,created_time,field_data,form_id,ad_id,adset_id,campaign_id",
    }

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=_HTTP_TIMEOUT)
    try:
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_FETCH_RETRIES + 1):
            try:
                resp = client.get(url, params=params)
                if resp.status_code >= 500:
                    last_exc = MetaFetchError(f"Graph API 5xx: {resp.status_code}")
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    # 4xx no se reintenta — token inválido, id malo, etc.
                    raise MetaFetchError(
                        f"Graph API {resp.status_code}: {resp.text[:200]}"
                    )
                data = resp.json()
                if not isinstance(data, dict):
                    raise MetaFetchError("Graph API devolvió payload no-objeto.")
                return data
            except httpx.TimeoutException as exc:
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
            except httpx.HTTPError as exc:
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
        raise MetaFetchError(f"Fallo tras reintentos: {last_exc}")
    finally:
        if own_client:
            client.close()


# ─────────────────────────────────────────────────────────────────────────────
# Normalización de campos Meta → IngestPayload
_FIELD_TELEFONO = {
    "phone_number", "phone", "telephone", "telefono", "teléfono", "celular",
    "mobile", "mobile_phone",
    "whatsapp", "whatsapp_number", "whatsapp number", "whatsapp_phone",
    "whatsapp_phone_number", "numero_de_whatsapp", "número_de_whatsapp",
    "numero de whatsapp", "número de whatsapp", "wa_number", "num_whatsapp",
    "nro_whatsapp", "telefono_whatsapp", "teléfono_whatsapp", "phone_whatsapp",
}
_FIELD_TELEFONO_KEYWORDS = (
    "phone", "telefono", "teléfono", "tel_fono", "celular", "mobile", "movil", "móvil",
    "whatsapp", "wa", "wsp", "whastapp", "whatsaap", "contacto", "contact", "num_tel",
    "nro_tel", "numero_tel", "número_tel", "cell_phone", "celular_whatsapp"
)
_FIELD_EMAIL = {"email", "correo", "correo_electronico", "correo electrónico"}
_FIELD_FULL_NAME = {"full_name", "name", "nombre_completo", "nombre completo"}
_FIELD_FIRST_NAME = {"first_name", "nombre", "nombres"}
_FIELD_LAST_NAME = {"last_name", "apellido", "apellidos"}


def _is_phone_key(key: str) -> bool:
    k = key.lower().strip()
    if k in _FIELD_TELEFONO:
        return True
    return any(kw in k for kw in _FIELD_TELEFONO_KEYWORDS)


def _is_phone_value(val: str) -> bool:
    if not val:
        return False
    digits = [c for c in str(val) if c.isdigit()]
    return 7 <= len(digits) <= 15


def _field_first_value(entry: dict) -> Optional[str]:
    values = entry.get("values")
    if isinstance(values, list) and values:
        v = values[0]
        if v is None:
            return None
        return str(v).strip() or None
    return None


def _split_full_name(full: str) -> tuple[Optional[str], Optional[str]]:
    parts = [p for p in full.split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    # Convención en Perú: primer token = nombres, resto = apellidos.
    return parts[0], " ".join(parts[1:])


def _parse_meta_created_time(value: Optional[str]) -> Optional[datetime]:
    """V068.7 — Meta envia created_time en formato ISO 8601 con offset:
    '2024-09-15T14:32:18+0000'. Devuelve datetime UTC-aware o None."""
    if not value:
        return None
    try:
        s = str(value).strip()
        # Meta usa "+0000" sin colon; fromisoformat (Py 3.11+) lo acepta,
        # pero en 3.10- requiere "+00:00". Normalizamos.
        if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
            s = s[:-2] + ":" + s[-2:]
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return None


def normalize_field_data(
    field_data: Iterable[dict],
    *,
    fuente: str = _FUENTE_DEFAULT,
    campana: Optional[str] = None,
    fuente_externa_id: Optional[str] = None,
    fuente_form_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
    form_name: Optional[str] = None,
    external_created_at: Optional[datetime] = None,  # V068.7
) -> IngestPayload:
    """Convierte `field_data` de Meta (`[{name, values}]`) en IngestPayload.

    Soporta nombres de campo estándar, nombres custom (WhatsApp/Celular/Teléfono),
    coincidencia por palabras clave y fallback por extracción de dígitos.
    """
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    extras_pairs: list[tuple[str, str]] = []

    for entry in field_data or []:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("name")
        if not raw_name:
            continue
        name_key = str(raw_name).strip().lower()
        value = _field_first_value(entry)
        if value is None:
            continue

        if _is_phone_key(name_key) and not telefono:
            telefono = value
        elif name_key in _FIELD_EMAIL and not email:
            email = value
        elif name_key in _FIELD_FIRST_NAME and not nombres:
            nombres = value
        elif name_key in _FIELD_LAST_NAME and not apellidos:
            apellidos = value
        elif name_key in _FIELD_FULL_NAME and not nombres and not apellidos:
            nombres, apellidos = _split_full_name(value)
        else:
            extras_pairs.append((str(raw_name), str(value)))

    # Fallback inteligente: si no se capturó teléfono por clave, buscar en extras
    # cualquier campo cuyo valor contenga entre 7 y 15 dígitos.
    if not telefono and extras_pairs:
        remaining = []
        for raw_n, val in extras_pairs:
            if not telefono and _is_phone_value(val):
                telefono = val
            else:
                remaining.append(f"{raw_n}: {val}")
        observaciones = " | ".join(remaining) if remaining else None
    else:
        observaciones = " | ".join([f"{k}: {v}" for k, v in extras_pairs]) if extras_pairs else None

    return IngestPayload(
        fuente=fuente,
        telefono=telefono or "",
        nombres=nombres,
        apellidos=apellidos,
        email=email,
        campana=campana,
        fuente_externa_id=fuente_externa_id,
        external_created_at=external_created_at,  # V068.7
        observaciones=observaciones,
        fuente_form_id=fuente_form_id,
        campaign_name=campaign_name,
        form_name=form_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador: webhook → fetch → normalize → ingest_lead_core → log
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_page_access_token(page_id: str) -> Optional[str]:
    """Obtiene el page_access_token para una página específica."""
    return credentials_repo.get_plaintext("meta", "page_access_token", page_id)


def log_meta_interaction(
    cur,
    *,
    lead_id: int,
    leadgen_id: str,
    page_id: str,
    form_id: Optional[str],
    ad_id: Optional[str],
    adset_id: Optional[str],
    campaign_id: Optional[str],
    es_duplicado: bool,
    field_data: Optional[list] = None,
    fecha_interaccion: Optional[str] = None,
) -> bool:
    """Registra una interacción de Meta sobre el cursor abierto.

    Usa `ON CONFLICT (leadgen_id) DO NOTHING` para idempotencia: si Meta
    reintenta un webhook (ej. por timeout de nuestra respuesta), el segundo
    intento no crea fila duplicada.

    Devuelve True si insertó, False si el leadgen_id ya existía.
    """
    if not lead_id or not leadgen_id or not page_id:
        return False
    try:
        cur.execute(
            """
            INSERT INTO crm.lead_interacciones_meta
                (lead_id, leadgen_id, page_id, form_id, ad_id, adset_id,
                 campaign_id, es_duplicado, fecha_interaccion, raw_field_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    COALESCE(%s::timestamptz, NOW()), %s)
            ON CONFLICT (leadgen_id) DO NOTHING
            RETURNING id
            """,
            (
                lead_id, leadgen_id, page_id, form_id, ad_id, adset_id,
                campaign_id, es_duplicado, fecha_interaccion,
                Json(field_data) if field_data is not None else None,
            ),
        )
        inserted = cur.fetchone() is not None
        return inserted
    except Exception as exc:  # noqa: BLE001
        # La interacción es observabilidad — no debe tumbar la ingesta.
        logger.warning(
            "meta_service: no se pudo registrar interacción leadgen=%s lead_id=%s: %s",
            leadgen_id, lead_id, exc,
        )
        return False


def process_leadgen_event(
    cur,
    leadgen_id: str,
    page_id: str,
    *,
    form_id: Optional[str] = None,
    ad_id: Optional[str] = None,
    adset_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    fetch_client: Optional[httpx.Client] = None,
) -> dict:
    """Procesa un evento `leadgen` completo sobre un cursor abierto.

    El caller (router/BackgroundTasks) abre la conexión y hace commit.
    Devuelve dict con resultado. Nunca levanta; cualquier error se
    loggea como evento en `events_repo` y se refleja en el dict.
    """
    t0 = time.perf_counter()

    page_access_token = _resolve_page_access_token(page_id)
    if not page_access_token:
        events_repo.log_event(
            provider="meta",
            event_type="error",
            status="error",
            account_id=page_id,
            external_id=leadgen_id,
            error_message=f"Sin page_access_token para page_id={page_id}",
        )
        return {"ok": False, "reason": "missing_page_access_token", "page_id": page_id}

    # 1) Fetch
    try:
        data = fetch_lead_details(leadgen_id, page_access_token, client=fetch_client)
    except MetaFetchError as exc:
        events_repo.log_event(
            provider="meta",
            event_type="error",
            status="error",
            account_id=page_id,
            external_id=leadgen_id,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error_message=str(exc),
        )
        return {"ok": False, "reason": "fetch_failed", "error": str(exc)}

    field_data = data.get("field_data") or []
    # campaign_id / form_id pueden venir del webhook o del fetch — el fetch
    # suele ser más confiable.
    form_id = str(data.get("form_id") or form_id or "").strip() or None
    ad_id = str(data.get("ad_id") or ad_id or "").strip() or None
    adset_id = str(data.get("adset_id") or adset_id or "").strip() or None
    campaign_id = str(data.get("campaign_id") or campaign_id or "").strip() or None

    # `campana` en nuestro dominio es un string libre — preferimos
    # campaign_id (estable) pero completamos con ad_id si no hay campaña.
    campana = campaign_id or ad_id or form_id

    # Resolución best-effort de nombres legibles via meta_catalog (Graph API +
    # cache). Si falla, ingest sigue con IDs solos — la columna en /leads
    # mostrará el ID hasta que un próximo lead resuelva el nombre.
    campaign_name: Optional[str] = None
    form_name: Optional[str] = None
    try:
        if campaign_id:
            campaign_name = meta_catalog.resolve_name(
                cur, entity_type="campaign", entity_id=campaign_id,
                page_id=page_id, access_token=page_access_token,
                client=fetch_client,
            )
        if form_id:
            form_name = meta_catalog.resolve_name(
                cur, entity_type="form", entity_id=form_id,
                page_id=page_id, access_token=page_access_token,
                client=fetch_client,
            )
    except Exception as exc:  # noqa: BLE001 — no romper ingest por catálogo
        logger.warning(
            "meta_service: resolve_name fallido leadgen=%s campaign=%s form=%s err=%s",
            leadgen_id, campaign_id, form_id, exc,
        )

    payload = normalize_field_data(
        field_data,
        fuente=_FUENTE_DEFAULT,
        campana=campana,
        fuente_externa_id=leadgen_id,
        # V068.7 — el created_time real del lead en Meta. Habilita la
        # validacion de Backfill Protection (V068.4): si Meta nos expone
        # tarde un lead viejo, no se cuenta como reactivacion.
        external_created_at=_parse_meta_created_time(data.get("created_time")),
        fuente_form_id=form_id,
        campaign_name=campaign_name,
        form_name=form_name,
    )

    if not payload.telefono:
        events_repo.log_event(
            provider="meta",
            event_type="error",
            status="skipped",
            account_id=page_id,
            external_id=leadgen_id,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error_message="Lead sin teléfono — ignorado.",
            raw_payload={"field_data": field_data},
        )
        return {"ok": False, "reason": "missing_phone"}

    # 2) Ingest (dedupe, supervisor, insert)
    try:
        result = ingest_lead_core(cur, payload)
    except IngestError as exc:
        events_repo.log_event(
            provider="meta",
            event_type="error",
            status="error",
            account_id=page_id,
            external_id=leadgen_id,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error_message=f"{exc.status_code}: {exc.detail}",
        )
        return {"ok": False, "reason": "ingest_failed", "error": exc.detail}

    latency_ms = int((time.perf_counter() - t0) * 1000)
    lead_id = result.get("id")
    is_duplicated = bool(result.get("duplicated"))

    # Registrar la interacción de Meta — una fila por cada submit, incluso
    # si el lead ya existía. Habilita timeline de re-interés y atribución
    # multi-campaña. Idempotente por leadgen_id (ON CONFLICT DO NOTHING).
    log_meta_interaction(
        cur,
        lead_id=lead_id,
        leadgen_id=leadgen_id,
        page_id=page_id,
        form_id=form_id,
        ad_id=ad_id,
        adset_id=adset_id,
        campaign_id=campaign_id,
        es_duplicado=is_duplicated,
        field_data=field_data,
        fecha_interaccion=data.get("created_time"),
    )

    # Propagamos el form_id al lead (solo si aún no tenía uno) para que la
    # UI y los reportes puedan unir con el catálogo de nombres. El primer
    # submit gana: si el lead recontactó desde otro formulario, la
    # atribución rica queda en `lead_interacciones_meta`.
    if lead_id and form_id:
        try:
            cur.execute(
                """
                UPDATE crm.leads
                   SET fuente_form_id = %s
                 WHERE id = %s
                   AND (fuente_form_id IS NULL OR fuente_form_id = '')
                """,
                (form_id, lead_id),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "meta_service: fallo propagando form_id=%s al lead=%s: %s",
                form_id, lead_id, exc,
            )

    # Aplica los field mappings configurados por el admin (patrón estándar):
    # campos custom del formulario → propiedades custom o columnas nativas.
    # Si no hay reglas configuradas es un no-op (stats todo-0, sin escrituras).
    if lead_id:
        try:
            field_mappings_repo.apply_mappings(
                cur,
                lead_id=lead_id,
                provider="meta",
                form_id=form_id,
                raw_field_data=field_data,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "meta_service: fallo aplicando field_mappings lead=%s: %s",
                lead_id, exc,
            )

    # Refresca el cache de nombres (campaign/form/ad) contra Graph API si
    # aún no los tenemos o llevan >7 días sin refrescar. Corremos esto en
    # el mismo BackgroundTask; si Graph API falla no bloquea la ingesta.
    # Pasamos el access_token ya resuelto para evitar un segundo viaje a
    # `integrations_credentials` (y para que los tests no necesiten pool).
    for kind, ent_id in (("campaign", campaign_id), ("form", form_id),
                         ("ad", ad_id), ("adset", adset_id)):
        if not ent_id:
            continue
        try:
            meta_catalog.resolve_name(
                cur,
                entity_type=kind,
                entity_id=ent_id,
                page_id=page_id,
                access_token=page_access_token,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "meta_service: fallo resolviendo nombre %s=%s: %s",
                kind, ent_id, exc,
            )

    if is_duplicated:
        events_repo.log_event(
            provider="meta",
            event_type="lead_duplicated",
            status="ok",
            account_id=page_id,
            external_id=leadgen_id,
            lead_id=lead_id,
            latency_ms=latency_ms,
            raw_payload={
                "form_id":     form_id,
                "campaign_id": campaign_id,
                "ad_id":       ad_id,
                "adset_id":    adset_id,
            },
        )
        return {"ok": True, "duplicated": True, "lead_id": lead_id}

    events_repo.log_event(
        provider="meta",
        event_type="lead_created",
        status="ok",
        account_id=page_id,
        external_id=leadgen_id,
        lead_id=lead_id,
        latency_ms=latency_ms,
        raw_payload={
            "form_id":     form_id,
            "campaign_id": campaign_id,
            "ad_id":       ad_id,
            "adset_id":    adset_id,
        },
    )

    # V070.86 — Push notification al dueño del lead (asesor si fue auto-
    # asignado, supervisor si quedo en cola). Antes meta_service.py era el
    # unico caller de ingest_lead_core que NO disparaba push, asi que un
    # lead que entraba por Instagram/Facebook nunca avisaba al supervisor.
    # Pattern consistente con routers/ingest.py, tiktok_service.py, etc.
    # Best-effort: si el push falla, no rompe el flujo de ingest.
    try:
        from app.services.notification_service import notify_new_lead
        recipient = result.get("asesor_id") or result.get("supervisor_id")
        if recipient:
            full_name = (
                f"{result.get('nombres', '') or ''} "
                f"{result.get('apellidos', '') or ''}"
            ).strip() or "Lead sin nombre"
            fuente_label = "instagram" if "instagram" in (page_id or "").lower() else "facebook"
            # V070.91 — lead_id para deep-link en mobile al tap.
            notify_new_lead(recipient, full_name, fuente=fuente_label, lead_id=lead_id)
            logger.info(
                "[push] meta lead=%s -> %s (%s)",
                lead_id,
                "asesor" if result.get("asesor_id") else "supervisor (queda en cola)",
                str(recipient)[:8],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[push] meta notify fallo lead=%s: %s", lead_id, exc)

    return {
        "ok":            True,
        "duplicated":    False,
        "lead_id":       lead_id,
        "supervisor_id": result.get("supervisor_id"),
        "mode":          result.get("mode"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Suscripción de página al webhook (POST /PAGE_ID/subscribed_apps)
# ─────────────────────────────────────────────────────────────────────────────

def subscribe_page_to_webhook(page_id: str) -> dict:
    """Suscribe una fan page al campo `leadgen` de nuestra app.

    Usa el page_access_token ya guardado en `crm.integrations_credentials`
    para el page_id indicado. Devuelve `{"ok": True}` ante `{"success": true}`
    de Meta; en cualquier otro caso `{"ok": False, "reason": "...", ...}` y
    loggea el evento.

    El endpoint /PAGE_ID/subscribed_apps requiere un Page Access Token con
    `pages_manage_metadata`. El System User PAT guardado cumple ambos.
    """
    page_id = (page_id or "").strip()
    if not page_id:
        return {"ok": False, "reason": "page_id_vacio"}

    page_access_token = _resolve_page_access_token(page_id)
    if not page_access_token:
        events_repo.log_event(
            provider="meta",
            event_type="page_subscribe",
            status="error",
            account_id=page_id,
            error_message="No hay page_access_token guardado para esta página.",
        )
        return {"ok": False, "reason": "missing_page_access_token"}

    url = f"{META_GRAPH_BASE}/{page_id}/subscribed_apps"
    params = {
        "subscribed_fields": "leadgen",
        "access_token":      page_access_token,
    }

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(url, params=params)
    except httpx.HTTPError as exc:
        events_repo.log_event(
            provider="meta",
            event_type="page_subscribe",
            status="error",
            account_id=page_id,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error_message=f"HTTP error: {exc}",
        )
        return {"ok": False, "reason": "http_error", "error": str(exc)}

    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Meta responde 200 con {"success": true} en éxito; ante errores viene
    # {"error": {"message": "...", "code": N, "type": "OAuthException"}}.
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}

    if resp.status_code == 200 and isinstance(data, dict) and data.get("success"):
        events_repo.log_event(
            provider="meta",
            event_type="page_subscribe",
            status="ok",
            account_id=page_id,
            latency_ms=latency_ms,
            raw_payload={"subscribed_fields": "leadgen"},
        )
        return {"ok": True, "subscribed_fields": ["leadgen"]}

    # Error — extraemos el mensaje de Meta para mostrarlo en la UI.
    err = (data.get("error") if isinstance(data, dict) else None) or {}
    err_msg = err.get("message") or f"HTTP {resp.status_code}: {resp.text[:200]}"
    events_repo.log_event(
        provider="meta",
        event_type="page_subscribe",
        status="error",
        account_id=page_id,
        latency_ms=latency_ms,
        error_message=err_msg,
    )
    return {
        "ok":          False,
        "reason":      "meta_rejected",
        "status_code": resp.status_code,
        "error":       err_msg,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Acceso conveniente a credenciales globales (app_secret, verify_token)
# ─────────────────────────────────────────────────────────────────────────────

def get_app_secret() -> Optional[str]:
    return credentials_repo.get_plaintext("meta", "app_secret", GLOBAL_ACCOUNT)


def get_verify_token() -> Optional[str]:
    return credentials_repo.get_plaintext("meta", "verify_token", GLOBAL_ACCOUNT)


def get_ads_access_token() -> Optional[str]:
    return credentials_repo.get_plaintext("meta", "ads_access_token", GLOBAL_ACCOUNT)


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment de jerarquia Meta para CTWA (Click-to-WhatsApp).
# ─────────────────────────────────────────────────────────────────────────────
#
# Cuando llega un referral de CTWA al webhook de WhatsApp, lo unico que Meta
# nos da de atribucion es `source_id` (= Ad ID). Esta funcion resuelve los
# nombres reales del ad / adset / campaign con una sola llamada a Graph API
# y los persiste en crm.wa_campaigns. Se invoca desde BackgroundTask (webhook
# no se bloquea) y tambien desde un endpoint admin para re-enriquecer manual.
#
# Idempotente: si ya se enriquecio hace menos de _ENRICH_STALE_DAYS, no re-fetcha.

_ENRICH_STALE_DAYS = 14


def _load_wa_campaign_by_ad_id(cur, ad_id: str) -> Optional[dict]:
    # V070.64 — Acceso robusto al row: soporta cualquier cursor factory.
    # El caller puede usar default cursor (tuple) o RealDictCursor (dict);
    # esta funcion debe ser indiferente para evitar el bug de KeyError: 0
    # que ya nos costo 4 horas destrabar en lead_recapture.
    cur.execute(
        """
        SELECT id, name, ad_id, enriched_at,
               EXTRACT(EPOCH FROM (NOW() - enriched_at))/86400 AS age_days,
               creative_media_cached_at, creative_media_error
          FROM crm.wa_campaigns
         WHERE ad_id = %s
         LIMIT 1
        """,
        (ad_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    # Soporte dual: dict o tuple. El primer chequeo decide el modo.
    if isinstance(row, dict):
        return {
            "id":                       row["id"],
            "name":                     row["name"],
            "ad_id":                    row["ad_id"],
            "enriched_at":              row["enriched_at"],
            "age_days":                 row["age_days"],
            "creative_media_cached_at": row["creative_media_cached_at"],
            "creative_media_error":     row["creative_media_error"],
        }
    return {
        "id":                       row[0],
        "name":                     row[1],
        "ad_id":                    row[2],
        "enriched_at":              row[3],
        "age_days":                 row[4],
        "creative_media_cached_at": row[5],
        "creative_media_error":     row[6],
    }


def enrich_wa_campaign_by_ad_id(
    ad_id: str,
    *,
    force: bool = False,
    client: Optional[httpx.Client] = None,
) -> dict:
    """Resuelve jerarquia Meta y persiste nombres en crm.wa_campaigns.

    Se llama desde:
      - Webhook WhatsApp (BackgroundTask) al recibir un referral CTWA nuevo.
      - Endpoint admin /api/integrations/meta/wa-campaigns/{id}/enrich
        para forzar re-fetch cuando el usuario acaba de renombrar en Ads Manager.

    Devuelve un dict con shape:
      {"ok": bool, "reason": str?, "resolved": {ad_name, adset_name, campaign_name}?}

    Nunca levanta — los errores se persisten en crm.wa_campaigns.enrich_error y
    tambien se reportan en el dict. Es `background-task safe`.
    """
    ad_id = (ad_id or "").strip()
    if not ad_id:
        return {"ok": False, "reason": "missing_ad_id"}

    access_token = get_ads_access_token()
    if not access_token:
        _persist_enrich_error(ad_id, "no_token")
        return {"ok": False, "reason": "no_token"}

    with get_db() as conn:
        with conn.cursor() as cur:
            row = _load_wa_campaign_by_ad_id(cur, ad_id)
            if not row:
                return {"ok": False, "reason": "wa_campaign_not_found"}

            if not force and row["enriched_at"] and (row["age_days"] or 0) < _ENRICH_STALE_DAYS:
                # V037 self-heal: si la fila fue enriquecida antes de V037 y
                # todavia no tiene media cacheada NI un error registrado, no
                # la consideramos "fresca" — re-fetch una vez para capturar
                # los campos visuales del creative.
                needs_v037_backfill = (
                    row.get("creative_media_cached_at") is None
                    and row.get("creative_media_error") is None
                )
                if not needs_v037_backfill:
                    return {
                        "ok":       True,
                        "reason":   "fresh",
                        "resolved": None,
                        "cached":   True,
                    }
                logger.info(
                    "meta_service.enrich_ctwa ad=%s fresh but V037-missing — backfilling",
                    ad_id,
                )

            hierarchy, debug = meta_catalog.resolve_ad_hierarchy_with_debug(
                cur,
                ad_id=ad_id,
                access_token=access_token,
                client=client,
            )
            if not hierarchy:
                # Construimos un mensaje legible usando el codigo/mensaje real
                # de Graph API si vino, asi el admin sabe si es scope, token
                # expirado, ad inexistente, etc.
                graph_msg = debug.get("graph_error_message")
                graph_code = debug.get("graph_error_code")
                http_status = debug.get("http_status")
                if graph_msg:
                    enrich_err = f"graph[{graph_code}] HTTP {http_status}: {graph_msg}"[:500]
                elif debug.get("error"):
                    enrich_err = f"{debug['error']}"[:500]
                else:
                    enrich_err = f"graph_fetch_failed (HTTP {http_status})"
                cur.execute(
                    """
                    UPDATE crm.wa_campaigns
                       SET enrich_error = %s,
                           updated_at   = NOW()
                     WHERE ad_id = %s
                    """,
                    (enrich_err, ad_id),
                )
                conn.commit()
                return {
                    "ok":     False,
                    "reason": "graph_fetch_failed",
                    "debug":  debug,
                }

            # Actualiza name solo si sigue siendo el fallback auto-generado
            # ("Ad {id}") — respetamos el headline u overrides manuales.
            fallback_name = f"Ad {ad_id}"
            new_display_name = (
                hierarchy.get("ad_name")
                if (row["name"] == fallback_name and hierarchy.get("ad_name"))
                else None
            )

            cur.execute(
                """
                UPDATE crm.wa_campaigns
                   SET ad_name                  = %s,
                       adset_id                 = %s,
                       adset_name               = %s,
                       meta_campaign_id         = %s,
                       meta_campaign_name       = %s,
                       creative_body            = %s,
                       creative_title           = %s,
                       creative_media_type      = %s,
                       creative_thumbnail_url   = %s,
                       creative_image_url       = %s,
                       creative_video_id        = %s,
                       creative_object_story_id = %s,
                       enriched_at              = NOW(),
                       enrich_error             = NULL,
                       name                     = COALESCE(%s, name),
                       updated_at               = NOW()
                 WHERE ad_id = %s
                """,
                (
                    hierarchy["ad_name"],
                    hierarchy["adset_id"],
                    hierarchy["adset_name"],
                    hierarchy["campaign_id"],
                    hierarchy["campaign_name"],
                    hierarchy.get("creative_body"),
                    hierarchy.get("creative_title"),
                    hierarchy.get("creative_media_type"),
                    hierarchy.get("creative_thumbnail_url"),
                    hierarchy.get("creative_image_url"),
                    hierarchy.get("creative_video_id"),
                    hierarchy.get("creative_object_story_id"),
                    new_display_name,
                    ad_id,
                ),
            )
            conn.commit()

            logger.info(
                "meta_service.enrich_ctwa ad=%s resolved ad_name=%r adset=%r campaign=%r",
                ad_id,
                hierarchy["ad_name"], hierarchy["adset_name"], hierarchy["campaign_name"],
            )

            events_repo.log_event(
                provider="meta",
                event_type="ctwa_enrich",
                status="ok",
                account_id=GLOBAL_ACCOUNT,
                raw_payload={
                    "ad_id":         ad_id,
                    "ad_name":       hierarchy["ad_name"],
                    "adset_name":    hierarchy["adset_name"],
                    "campaign_name": hierarchy["campaign_name"],
                },
            )

    # V037: si Graph devolvio un thumbnail_url, lo descargamos y cacheamos
    # fuera del bloque DB para no retener la conexion. Best-effort — los
    # fallos se persisten como creative_media_error; la UI degrada gracefully.
    thumbnail_url = (hierarchy or {}).get("creative_thumbnail_url")
    if thumbnail_url and row.get("id"):
        try:
            creative_media_service.download_and_cache_thumbnail(
                row["id"], thumbnail_url,
            )
        except Exception as exc:  # noqa: BLE001 — defensivo
            logger.warning(
                "meta_service.creative_media_cache ad=%s id=%s: %s",
                ad_id, row["id"], exc,
            )

    return {"ok": True, "resolved": hierarchy, "cached": False}


def _persist_enrich_error(ad_id: str, reason: str) -> None:
    """Best-effort: escribe el motivo del fallo en wa_campaigns. No levanta."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE crm.wa_campaigns
                       SET enrich_error = %s,
                           updated_at   = NOW()
                     WHERE ad_id = %s
                    """,
                    (reason, ad_id),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta_service._persist_enrich_error ad=%s: %s", ad_id, exc)


def fetch_campaign_insights(
    fecha_desde: str,
    fecha_hasta: str,
    ad_account_id: str,
    access_token: str
) -> dict:
    """Extrae métricas reales agrupadas por campaña desde Meta Insights API.
    
    Returns:
        dict: Las métricas mapeadas, e.g.
        {
            "global": {"spend": 0.0, "impressions": 0, "clicks": 0},
            "campaigns": [
                {"name": "...", "spend": 0.0, "impressions": 0, "clicks": 0},
                ...
            ]
        }
    """
    ad_account_id = ad_account_id.strip()
    if ad_account_id.startswith("act="):
        ad_account_id = ad_account_id.replace("act=", "act_")
    elif not ad_account_id.startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    # Paginación y endpoints de Graph API
    url = f"{META_GRAPH_BASE}/{ad_account_id}/insights"
    params = {
        "access_token": access_token,
        "level": "campaign",
        "fields": "campaign_name,spend,impressions,inline_link_clicks,clicks,actions",
        "time_range": f'{{"since":"{fecha_desde}","until":"{fecha_hasta}"}}',
        "limit": 100
    }
    
    global_metrics = {"spend": 0.0, "impressions": 0, "clicks": 0, "results": 0}
    campaigns = []
    trend_data = []
    
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params)
            if resp.status_code != 200:
                logger.error("Meta Insights API error: %s", resp.text)
                return {"global": global_metrics, "campaigns": campaigns, "trend": trend_data}
            
            data = resp.json().get("data", [])
            logger.warning("RAW META INSIGHTS DATA: %s", resp.json())
            for row in data:
                c_spend = float(row.get("spend", 0.0))
                c_impressions = int(row.get("impressions", 0))
                # Algunos prefieren inline_link_clicks, usamos clicks genéricos o inline
                c_clicks = int(row.get("inline_link_clicks") or row.get("clicks") or 0)
                
                # Extraer Resultados (conversiones/leads/contactos/mensajes) con prioridades para evitar duplicaciones
                c_results = 0
                leads_onsite = 0
                leads_pixel = 0
                msg_started = 0
                registrations = 0
                contacts = 0
                
                for act in row.get("actions", []):
                    a_type = act.get("action_type", "")
                    a_val = int(act.get("value", 0))
                    
                    if a_type == "lead":
                        leads_pixel = a_val
                    elif a_type == "onsite_conversion.lead_grouped":
                        leads_onsite = a_val
                    elif a_type == "onsite_conversion.messaging_conversation_started_7d":
                        msg_started = a_val
                    elif a_type in ("complete_registration", "offsite_conversion.fb_pixel_complete_registration"):
                        registrations = a_val
                    elif a_type in ("contact", "offsite_conversion.fb_pixel_contact"):
                        contacts = a_val
                
                if leads_onsite > 0:
                    c_results = leads_onsite
                elif leads_pixel > 0:
                    c_results = leads_pixel
                elif msg_started > 0:
                    c_results = msg_started
                else:
                    c_results = max(registrations, contacts)
                
                c_cpm = round((c_spend / c_impressions) * 1000, 2) if c_impressions > 0 else 0.0
                c_cpr = round(c_spend / c_results, 2) if c_results > 0 else 0.0
                
                campaigns.append({
                    "name": row.get("campaign_name", "Sin campaña"),
                    "spend": c_spend,
                    "impressions": c_impressions,
                    "clicks": c_clicks,
                    "results": c_results,
                    "cpm": c_cpm,
                    "cpr": c_cpr
                })
                global_metrics["spend"] += c_spend
                global_metrics["impressions"] += c_impressions
                global_metrics["clicks"] += c_clicks
                global_metrics["results"] += c_results

            # Obtener tendencia diaria
            trend_url = f"{META_GRAPH_BASE}/{ad_account_id}/insights"
            trend_params = {
                "access_token": access_token,
                "level": "account",
                "fields": "spend,actions",
                "time_range": f'{{"since":"{fecha_desde}","until":"{fecha_hasta}"}}',
                "time_increment": 1,
                "limit": 100
            }
            resp_trend = client.get(trend_url, params=trend_params)
            if resp_trend.status_code == 200:
                logger.warning("RAW META TREND DATA: %s", resp_trend.json())
                for row in resp_trend.json().get("data", []):
                    day_spend = float(row.get("spend", 0.0))
                    day_results = 0
                    leads_onsite = 0
                    leads_pixel = 0
                    msg_started = 0
                    registrations = 0
                    contacts = 0
                    
                    for act in row.get("actions", []):
                        a_type = act.get("action_type", "")
                        a_val = int(act.get("value", 0))
                        
                        if a_type == "lead":
                            leads_pixel = a_val
                        elif a_type == "onsite_conversion.lead_grouped":
                            leads_onsite = a_val
                        elif a_type == "onsite_conversion.messaging_conversation_started_7d":
                            msg_started = a_val
                        elif a_type in ("complete_registration", "offsite_conversion.fb_pixel_complete_registration"):
                            registrations = a_val
                        elif a_type in ("contact", "offsite_conversion.fb_pixel_contact"):
                            contacts = a_val
                    
                    if leads_onsite > 0:
                        day_results = leads_onsite
                    elif leads_pixel > 0:
                        day_results = leads_pixel
                    elif msg_started > 0:
                        day_results = msg_started
                    else:
                        day_results = max(registrations, contacts)
                    
                    trend_data.append({
                        "fecha": row.get("date_start"),
                        "leads": day_results,
                        "conversions": day_results,
                        "spend": day_spend
                    })
                trend_data.sort(key=lambda x: x["fecha"])
                
    except Exception as exc:
        logger.warning("Error fetch_campaign_insights (Meta): %s", exc)
        
    return {"global": global_metrics, "campaigns": campaigns, "trend": trend_data}


def reprocess_skipped_leads(cur) -> dict:
    """Recupera los leads de Meta que fueron omitidos o fallaron anteriormente,
    los vuelve a procesar a través de normalize_field_data y los ingesta en crm.leads.
    """
    cur.execute(
        """
        SELECT DISTINCT external_id AS leadgen_id, account_id AS page_id
        FROM crm.integrations_events
        WHERE provider = 'meta'
          AND status IN ('skipped', 'error')
          AND external_id IS NOT NULL
          AND external_id != ''
        ORDER BY external_id
        """
    )
    rows = cur.fetchall()
    total_found = len(rows)
    reprocessed = 0
    success = 0
    errors = 0
    details = []

    for r in rows:
        leadgen_id = r["leadgen_id"]
        page_id = r["page_id"]
        if not leadgen_id or not page_id:
            continue
        reprocessed += 1
        res = process_leadgen_event(cur, leadgen_id=leadgen_id, page_id=page_id)
        if res.get("ok"):
            success += 1
            cur.execute(
                """
                UPDATE crm.integrations_events
                SET status = 'reprocessed'
                WHERE provider = 'meta'
                  AND external_id = %s
                  AND status IN ('skipped', 'error')
                """,
                (leadgen_id,),
            )
        else:
            errors += 1
        details.append({"leadgen_id": leadgen_id, "result": res})

    return {
        "ok": True,
        "total_skipped_found": total_found,
        "reprocessed": reprocessed,
        "success": success,
        "errors": errors,
        "details": details,
    }

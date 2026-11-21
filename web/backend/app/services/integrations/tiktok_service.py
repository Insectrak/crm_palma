"""Driver de la integración con TikTok Ads (Lead Generation).

TikTok no expone webhooks para Lead Gen; se consume vía polling al
Marketing API v1.3, que usa un flujo asíncrono task-based:

  1. POST /open_api/v1.3/page/get/         → lista de pages del advertiser
  2. POST /open_api/v1.3/page/lead/task/   → crea task de export por page
  3. POST /open_api/v1.3/page/lead/task/   → poll del status (mismo endpoint
                                              con task_id, backoff 2/4/8/16/32s)
  4. GET  /open_api/v1.3/page/lead/task/download/ → CSV (≤10MB) o ZIP (>10MB)

Este módulo:
  - Obtiene credenciales desde `credentials_repo` (access_token por advertiser,
    app_id/app_secret globales).
  - Recorre todas las pages activas del advertiser y agrega los leads.
  - Parsea el CSV (TikTok no expone JSON list — solo CSV/ZIP).
  - Normaliza cada lead al `IngestPayload` y delega en `ingest_lead_core`.
  - Loggea eventos en `integrations_events` y avanza el checkpoint.

Clean Code / SOLID:
  - SRP: no corre el scheduling (lo hace `scheduler.py`), no hace HTTP
    en routers, no conoce WhatsApp ni Meta.
  - DIP: el cliente httpx se puede inyectar (tests lo mockean).
  - Idempotencia: cada lead se envía al mismo `ingest_lead_core` con
    dedupe por teléfono — si se repite una ventana, no se duplican leads.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import httpx
from psycopg2.extras import RealDictCursor

from app.database import get_db
from app.services.integrations import (
    checkpoint_repo,
    credentials_repo,
    events_repo,
)
from app.services.integrations.ingest_core import (
    IngestError,
    IngestPayload,
    ingest_lead_core,
)

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"
# URL del portal de autorización OAuth (user-facing). TikTok lo llama
# "Authorization URL" en la documentación de Marketing API.
TIKTOK_AUTHORIZE_URL = "https://business-api.tiktok.com/portal/auth"
_HTTP_TIMEOUT = 15.0
_DEFAULT_PAGE_SIZE = 100

# Ventana de lookback default cuando no hay checkpoint previo —
# 48h es suficiente para el primer fetch sin tragar histórico masivo.
_DEFAULT_LOOKBACK_HOURS = 168  # 7 días — más tolerante a fallos de polling
_MAX_LOOKBACK_HOURS     = 90 * 24  # 90 días — tope para backfill manual

_FUENTE = "tiktok"


# ─────────────────────────────────────────────────────────────────────────────
# Cliente HTTP
# ─────────────────────────────────────────────────────────────────────────────

class TikTokAPIError(Exception):
    """Error al consumir el Marketing API de TikTok."""


_TASK_POLL_BACKOFF_SECONDS = (2, 3, 5, 8, 13, 21, 34)  # ~86s total — tope por page
_TASK_TERMINAL_OK = "SUCCEED"
_TASK_TERMINAL_FAIL = "FAILED"
_TASK_PENDING = ("CREATED", "RUNNING")


def _parse_tiktok_envelope(resp: Any) -> dict:
    """Valida el envelope estándar TikTok {code, message, data} y devuelve `data`.
    Levanta TikTokAPIError ante 4xx/5xx, code != 0, JSON inválido o data ausente.
    """
    if resp.status_code >= 500:
        raise TikTokAPIError(f"TikTok API 5xx: {resp.status_code}")
    if resp.status_code >= 400:
        raise TikTokAPIError(
            f"TikTok API {resp.status_code}: {resp.text[:200]}"
        )
    try:
        body = resp.json()
    except Exception as exc:
        raise TikTokAPIError(f"TikTok API: respuesta no-JSON ({exc})") from exc
    if not isinstance(body, dict):
        raise TikTokAPIError("TikTok API: respuesta no-objeto.")
    if body.get("code") not in (0, None):
        msg = body.get("message") or ""
        # 40001 con "does not grant ... permission" = scope insuficiente.
        # Apuntar al fix en lugar de propagar el error crudo: el admin
        # tiene que agregar el scope "Lead Generation/Pages" en el
        # TikTok Developer Portal y re-autorizar via OAuth.
        if body.get("code") == 40001 and "permission" in msg.lower():
            raise TikTokAPIError(
                f"Scope insuficiente: {msg}. "
                "Solucion: en TikTok Developer Portal agregar el scope "
                "'Lead Generation' (o 'Pages') a la App, guardar, y volver "
                "a 'Conectar con TikTok' para re-autorizar."
            )
        raise TikTokAPIError(
            f"TikTok API code={body.get('code')}: {msg}"
        )
    inner = body.get("data")
    return inner if isinstance(inner, dict) else {}


def _list_pages(
    advertiser_id: str,
    access_token: str,
    *,
    client: httpx.Client,
    pages_access_token: Optional[str] = None,
) -> list[str]:
    """Lista los page_id (Instant Forms) del advertiser.

    Itera la paginación hasta agotar resultados — en sandbox suele haber 1
    page; en producción puede haber decenas. Sin filtro por business_type:
    el endpoint task/ luego falla limpio si la page no es de Lead Gen.

    `pages_access_token` override: si la app que emitio el access_token
    normal no tiene scope para /page/get/, el admin puede guardar un token
    long-lived de otra app (con scope Pages) como `pages_access_token` en
    credentials_repo y este se usa solo para esta llamada.
    """
    url = f"{TIKTOK_API_BASE}/page/get/"
    headers = {"Access-Token": pages_access_token or access_token}
    page = 1
    page_size = 100
    out: list[str] = []
    while True:
        params = {
            "advertiser_id": advertiser_id,
            "page":          page,
            "page_size":     page_size,
        }
        resp = client.get(url, params=params, headers=headers)
        data = _parse_tiktok_envelope(resp)
        items = data.get("list") or []
        if not isinstance(items, list):
            break
        for item in items:
            pid = item.get("page_id") if isinstance(item, dict) else None
            if pid:
                out.append(str(pid))
        info = data.get("page_info") or {}
        total_pages = info.get("total_page") or info.get("total_pages") or 1
        if page >= int(total_pages or 1):
            break
        page += 1
    return out


def _create_lead_task(
    advertiser_id: str,
    page_id: str,
    access_token: str,
    *,
    client: httpx.Client,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> str:
    """Crea task de export. Devuelve task_id.

    Sin start_time/end_time, TikTok aplica lógica DELTA: solo entrega leads
    no descargados por tasks anteriores. Esto rompe re-fetch de leads viejos
    si otro sistema (ej. n8n) ya los exportó.

    Con start_time/end_time, TikTok IGNORA la lógica delta y entrega TODOS
    los leads del rango — útil para backfill manual desde admin endpoint.
    """
    url = f"{TIKTOK_API_BASE}/page/lead/task/"
    headers = {"Access-Token": access_token, "Content-Type": "application/json"}
    body: dict = {"advertiser_id": advertiser_id, "page_id": page_id}
    # TikTok Marketing API v1.3 espera strings en formato 'YYYY-MM-DD HH:MM:SS'
    # en UTC para start_time/end_time. NO es epoch seconds.
    # Ref: https://business-api.tiktok.com/portal/docs?id=1739566385256962
    if start_time is not None:
        body["start_time"] = start_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if end_time is not None:
        body["end_time"] = end_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    resp = client.post(url, json=body, headers=headers)
    data = _parse_tiktok_envelope(resp)
    task_id = data.get("task_id")
    if not task_id:
        raise TikTokAPIError(
            f"TikTok task/ sin task_id (page_id={page_id}). data={data}"
        )
    return str(task_id)


def _poll_lead_task(
    advertiser_id: str,
    task_id: str,
    access_token: str,
    *,
    client: httpx.Client,
    sleep: Any = time.sleep,
) -> str:
    """Polea el task hasta SUCCEED/FAILED o timeout. Devuelve el status final.

    `sleep` inyectable para tests (evita esperas reales). El backoff suma
    ~62s en el peor caso — más allá de eso devolvemos el último status sin
    explotar; el caller decide si reintenta en el próximo poll del scheduler.
    """
    url = f"{TIKTOK_API_BASE}/page/lead/task/"
    headers = {"Access-Token": access_token, "Content-Type": "application/json"}
    body = {"advertiser_id": advertiser_id, "task_id": task_id}
    last_status = ""
    for delay in _TASK_POLL_BACKOFF_SECONDS:
        sleep(delay)
        resp = client.post(url, json=body, headers=headers)
        data = _parse_tiktok_envelope(resp)
        last_status = str(data.get("status") or "").upper()
        if last_status == _TASK_TERMINAL_OK:
            return last_status
        if last_status == _TASK_TERMINAL_FAIL:
            return last_status
        if last_status not in _TASK_PENDING:
            # Estado desconocido — mejor cortar que loopear infinito.
            raise TikTokAPIError(
                f"TikTok task/ status inesperado: {last_status} (task={task_id})"
            )
    return last_status


def _download_lead_csv(
    advertiser_id: str,
    task_id: str,
    access_token: str,
    *,
    client: httpx.Client,
) -> str:
    """Descarga el CSV del task. Levanta si TikTok responde JSON (= error)
    o si el body parece ZIP (>10MB — caso excepcional en producción que
    requeriría unzip; por ahora lo reportamos y el admin baja manual)."""
    url = f"{TIKTOK_API_BASE}/page/lead/task/download/"
    headers = {"Access-Token": access_token}
    params = {"advertiser_id": advertiser_id, "task_id": task_id}
    resp = client.get(url, params=params, headers=headers)
    if resp.status_code >= 500:
        raise TikTokAPIError(f"TikTok download 5xx: {resp.status_code}")
    if resp.status_code >= 400:
        raise TikTokAPIError(
            f"TikTok download {resp.status_code}: {resp.text[:200]}"
        )
    text = resp.text or ""
    stripped = text.lstrip()
    # Caso error: TikTok devuelve JSON con code != 0 en lugar del CSV
    if stripped.startswith("{"):
        try:
            body = resp.json()
        except Exception:
            body = {}
        raise TikTokAPIError(
            f"TikTok download error: code={body.get('code')} message={body.get('message')}"
        )
    # Caso ZIP (>10MB) — magic bytes PK\x03\x04
    if text.startswith("PK\x03\x04"):
        raise TikTokAPIError(
            "TikTok download devolvio ZIP (>10MB) — caso no soportado todavia."
        )
    return text


def _parse_lead_csv(csv_text: str) -> list[dict]:
    """Convierte el CSV de TikTok en list[dict] con keys lowercased.

    TikTok devuelve cabeceras en el idioma del formulario ("Phone Number",
    "Telefono", etc.); las normalizamos a snake_case lowercase para que
    el normalize_tiktok_lead las matche con sus mapeos (_PHONE_KEYS, etc.).

    V068.6 — ROOT CAUSE FIX del bug de recontactos infinitos:
    TikTok exporta el CSV en UTF-8 CON BOM (Byte Order Mark). El primer
    header del CSV viene precedido por el caracter invisible '﻿' (BOM).
    `str.strip()` NO incluye '﻿' en su set default, asi que la key
    "lead_id" del CSV quedaba como "﻿lead_id" en el dict normalizado.

    Cuando `normalize_tiktok_lead` hacia `lead.get("lead_id")`, devolvia
    None porque la verdadera key era "﻿lead_id". Resultado:
    `fuente_externa_id = NULL` para TODOS los leads de TikTok.

    El n8n viejo lo manejaba explicitamente con `$json['﻿lead_id']`
    (escribia el BOM en el path). Aca lo strippeamos del header.

    Sin este fix, V068.1 (ampliar columnas), V068.2 (dedup por fext) y
    V068.4 (external_created_at) no servian para nada porque dependian
    de fext, que siempre venia None.
    """
    if not csv_text or not csv_text.strip():
        return []
    # V068.6 — strip BOM al inicio del texto Y de los headers individuales
    # (defense in depth: csv.DictReader puede o no consumir el BOM segun
    # version de Python).
    if csv_text.startswith("﻿"):
        csv_text = csv_text[1:]
    reader = csv.DictReader(io.StringIO(csv_text))
    out: list[dict] = []
    for row in reader:
        norm: dict = {}
        for k, v in row.items():
            if not k:
                continue
            # V068.6 — strip BOM + zero-width chars del nombre de la
            # columna antes de normalizar a snake_case.
            key = (
                k.replace("﻿", "")     # BOM
                 .replace("​", "")     # zero-width space
                 .replace("‌", "")     # zero-width non-joiner
                 .replace("‍", "")     # zero-width joiner
                 .strip()
                 .lower()
                 .replace(" ", "_")
            )
            if key:  # no insertar key vacia tras el strip
                norm[key] = v
        out.append(norm)
    return out


def fetch_leads(
    advertiser_id: str,
    access_token: str,
    *,
    since: Optional[datetime] = None,
    page_size: int = _DEFAULT_PAGE_SIZE,  # noqa: ARG001 - compat firma legacy
    client: Optional[httpx.Client] = None,
    sleep: Any = time.sleep,
    pages_access_token: Optional[str] = None,
    explicit_range: bool = False,
) -> list[dict]:
    """Trae todos los leads del advertiser usando el flujo task-based v1.3.

    Recorre todas las pages del advertiser, crea+polea+descarga un task por
    cada una y agrega los leads.

    Comportamiento del rango temporal (V068.1):
    - Si `explicit_range=True` (default desde V068.1 cuando se llama via
      poll_advertiser), el task se crea con start_time=since, end_time=now,
      y TikTok solo devuelve leads creados en esa ventana. Esto evita el
      bug observado en prod donde TikTok devolvia todo su set retenido
      (~30 dias) en cada poll, regenerando recontactos diarios.
    - Si `explicit_range=False`, el task se crea SIN start/end y TikTok
      aplica su logica delta interna — semantica menos predecible.

    NOTA: el codigo NO filtra client-side por timestamp del lead — antes
    el docstring lo afirmaba pero era falso. Si necesitas filtrar mas
    estrictamente, hacelo en el caller post-fetch.

    Mocking: pasar `client` con interfaz httpx (.get, .post, .close) y `sleep`
    como callable permite tests deterministicos sin red ni delays reales.
    """
    if not advertiser_id or not access_token:
        raise TikTokAPIError("advertiser_id o access_token vacíos.")

    if since is None:
        since = datetime.now(timezone.utc) - timedelta(hours=_DEFAULT_LOOKBACK_HOURS)

    own_client = client is None
    if own_client:
        # follow_redirects=True crítico: TikTok responde 307 en /page/lead/task/
        # y httpx NO sigue redirects por default en POST. Sin esto, vemos
        # respuestas vacías y skipeamos pages silenciosamente.
        client = httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    try:
        page_ids = _list_pages(
            advertiser_id, access_token,
            client=client, pages_access_token=pages_access_token,
        )
        if not page_ids:
            logger.info(
                "tiktok.fetch_leads advertiser=%s sin pages — "
                "el advertiser no tiene Instant Forms creadas.",
                advertiser_id,
            )
            return []

        # Cuando explicit_range=True, pasamos start_time/end_time a TikTok
        # para que ignore la lógica delta y entregue TODOS los leads del
        # rango (útil para backfill cuando otro sistema ya los exportó).
        # end_time defaulteamos a "ahora" para incluir lo más reciente.
        task_start = since if explicit_range else None
        task_end   = datetime.now(timezone.utc) if explicit_range else None

        all_leads: list[dict] = []
        # Log explícito en INFO al inicio para ver en EasyPanel logs cuántas
        # pages está intentando consultar y con qué rango.
        logger.info(
            "tiktok.fetch_leads start advertiser=%s pages=%d explicit_range=%s "
            "task_start=%s task_end=%s",
            advertiser_id, len(page_ids), task_start is not None,
            task_start, task_end,
        )
        for idx, page_id in enumerate(page_ids, start=1):
            try:
                task_id = _create_lead_task(
                    advertiser_id, page_id, access_token, client=client,
                    start_time=task_start, end_time=task_end,
                )
                logger.info(
                    "tiktok.fetch_leads page %d/%d page_id=%s task_id=%s creado",
                    idx, len(page_ids), page_id, task_id,
                )
                status = _poll_lead_task(
                    advertiser_id, task_id, access_token,
                    client=client, sleep=sleep,
                )
                logger.info(
                    "tiktok.fetch_leads page %d/%d page_id=%s task_id=%s status=%s",
                    idx, len(page_ids), page_id, task_id, status,
                )
            except TikTokAPIError as exc:
                logger.warning(
                    "tiktok.fetch_leads page=%s task error: %s", page_id, exc,
                )
                # Una page caida no bloquea las demás del mismo advertiser.
                continue

            if status != _TASK_TERMINAL_OK:
                logger.warning(
                    "tiktok.fetch_leads page=%s task no SUCCEED: status=%s — page skipeada",
                    page_id, status,
                )
                continue

            try:
                csv_text = _download_lead_csv(
                    advertiser_id, task_id, access_token, client=client,
                )
                leads = _parse_lead_csv(csv_text)
                logger.info(
                    "tiktok.fetch_leads page=%s csv_bytes=%d leads_parsed=%d",
                    page_id, len(csv_text), len(leads),
                )
            except TikTokAPIError as exc:
                logger.warning(
                    "tiktok.fetch_leads page=%s download error: %s", page_id, exc,
                )
                continue

            # Inyectamos page_id para trazabilidad downstream
            for lead in leads:
                lead.setdefault("page_id", page_id)
            all_leads.extend(leads)

        logger.info(
            "tiktok.fetch_leads done advertiser=%s total_leads=%d",
            advertiser_id, len(all_leads),
        )
        return all_leads
    except httpx.HTTPError as exc:
        raise TikTokAPIError(f"HTTP error: {exc}") from exc
    finally:
        if own_client:
            client.close()


# ─────────────────────────────────────────────────────────────────────────────
# OAuth 2.0 — authorize URL + auth_code → access_token
# ─────────────────────────────────────────────────────────────────────────────

def build_authorize_url(
    app_id: str,
    redirect_uri: str,
    state: str,
    *,
    rid: Optional[str] = None,
) -> str:
    """Arma la URL de autorización del portal TikTok Business.

    El admin la abre en su navegador, TikTok muestra el consentimiento y al
    aprobar redirige a `redirect_uri?auth_code=...&state=...`.

    `rid` (request-id opcional) TikTok lo usa para tracking en su lado; si el
    caller lo pasa se incluye, si no lo omitimos.
    """
    if not app_id:
        raise TikTokAPIError("app_id vacío — configurar antes de iniciar OAuth.")
    if not redirect_uri:
        raise TikTokAPIError("redirect_uri vacío.")
    if not state:
        raise TikTokAPIError("state vacío — requerido para CSRF.")

    params = {
        "app_id":       app_id,
        "redirect_uri": redirect_uri,
        "state":        state,
    }
    if rid:
        params["rid"] = rid
    # httpx.QueryParams encodea URL-safe sin depender de urllib.parse.
    return f"{TIKTOK_AUTHORIZE_URL}?{httpx.QueryParams(params)}"


def exchange_auth_code(
    app_id: str,
    app_secret: str,
    auth_code: str,
    *,
    client: Optional[httpx.Client] = None,
) -> dict:
    """Intercambia un `auth_code` por un `access_token` long-lived.

    Llama a `POST /oauth2/access_token/` con JSON body:
      {app_id, secret, auth_code}

    Devuelve el dict `data` de la respuesta de TikTok, que contiene al menos:
      - `access_token`  (str)
      - `advertiser_ids` (list[int|str])
      - `scope`         (list[int])
      - `token_expired_at` / `expire_in` (si aplica — TikTok no siempre lo manda)

    Levanta TikTokAPIError si algo falla (4xx, 5xx, code!=0, parse error).
    """
    if not app_id or not app_secret or not auth_code:
        raise TikTokAPIError("app_id, app_secret o auth_code vacíos.")

    url = f"{TIKTOK_API_BASE}/oauth2/access_token/"
    payload = {
        "app_id":    app_id,
        "secret":    app_secret,
        "auth_code": auth_code,
    }

    own_client = client is None
    if own_client:
        # follow_redirects=True crítico: TikTok responde 307 en /page/lead/task/
        # y httpx NO sigue redirects por default en POST. Sin esto, vemos
        # respuestas vacías y skipeamos pages silenciosamente.
        client = httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    try:
        resp = client.post(url, json=payload)
        if resp.status_code >= 500:
            raise TikTokAPIError(f"TikTok OAuth 5xx: {resp.status_code}")
        if resp.status_code >= 400:
            raise TikTokAPIError(
                f"TikTok OAuth {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise TikTokAPIError("Respuesta no-objeto.")
        if data.get("code") not in (0, None):
            raise TikTokAPIError(
                f"TikTok OAuth code={data.get('code')}: {data.get('message')}"
            )
        inner = data.get("data") or {}
        if not isinstance(inner, dict):
            raise TikTokAPIError("Formato inesperado: `data` no es objeto.")
        if not inner.get("access_token"):
            raise TikTokAPIError("Respuesta sin access_token.")
        return inner
    except httpx.HTTPError as exc:
        raise TikTokAPIError(f"HTTP error: {exc}") from exc
    finally:
        if own_client:
            client.close()


def summarize_oauth_result(oauth_result: Any) -> dict:
    """Resumen masked de la respuesta OAuth de TikTok, seguro para persistir
    en `integrations_events.raw_payload` y mostrar en el historial UI.

    Nunca expone el access_token en claro — solo un preview (6 prefijo + 4
    sufijo). Útil para diagnosticar por qué un callback falla sin acceso a
    los logs del backend (ej. faltan advertiser_ids, scope insuficiente, etc.).
    """
    if not isinstance(oauth_result, dict):
        return {"type": type(oauth_result).__name__}
    token = oauth_result.get("access_token") or ""
    if isinstance(token, str) and len(token) > 12:
        token_preview = f"{token[:6]}...{token[-4:]}"
    else:
        token_preview = f"len={len(token) if isinstance(token, str) else 'n/a'}"
    advertiser_ids = oauth_result.get("advertiser_ids")
    return {
        "keys":             sorted(oauth_result.keys()),
        "token_preview":    token_preview,
        "advertiser_ids":   advertiser_ids if isinstance(advertiser_ids, list) else str(advertiser_ids),
        "advertiser_count": len(advertiser_ids) if isinstance(advertiser_ids, list) else None,
        "scope":            oauth_result.get("scope"),
        "bc_id":            oauth_result.get("bc_id"),
        "token_expired_at": oauth_result.get("token_expired_at"),
        "expire_in":        oauth_result.get("expire_in"),
    }


def save_oauth_result(
    *,
    oauth_result: dict,
    updated_by: Optional[str] = None,
) -> list[str]:
    """Persiste el access_token recibido por OAuth en credentials_repo,
    una entrada por advertiser_id devuelto por TikTok.

    Devuelve la lista de advertiser_ids persistidos (como str). Los llamados
    al repo se hacen secuenciales y cada uno abre su propia transacción —
    si uno falla, los anteriores quedan guardados. Esto es deliberado: una
    conexión parcial es mejor que ninguna, y el log registra los advertisers
    que fallaron para reintentar manual.
    """
    access_token = oauth_result.get("access_token")
    if not access_token:
        raise TikTokAPIError("oauth_result sin access_token.")

    advertiser_ids = oauth_result.get("advertiser_ids") or []
    if not isinstance(advertiser_ids, (list, tuple)) or not advertiser_ids:
        # Enriquecemos el error con lo que SI vino — scope/bc_id/keys — para
        # que el admin vea en la UI si TikTok devolvio BC scope en vez de
        # advertiser scope, o si el app todavia no esta vinculado a un
        # advertiser en Business Center.
        summary = summarize_oauth_result(oauth_result)
        raise TikTokAPIError(
            "oauth_result sin advertiser_ids. "
            f"keys={summary['keys']} scope={summary['scope']} bc_id={summary['bc_id']}. "
            "Causa probable: el app no esta vinculado a ningun advertiser en TikTok Business Center."
        )

    saved: list[str] = []
    for adv in advertiser_ids:
        adv_id = str(adv).strip()
        if not adv_id:
            continue
        try:
            credentials_repo.upsert_credential(
                provider=_FUENTE,
                key="access_token",
                value=access_token,
                account_id=adv_id,
                updated_by=updated_by,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "tiktok.save_oauth_result advertiser=%s error=%s", adv_id, exc,
            )
            events_repo.log_event(
                provider=_FUENTE,
                event_type="oauth_error",
                status="error",
                account_id=adv_id,
                error_message=f"save_token: {exc}",
            )
            continue
        saved.append(adv_id)
        events_repo.log_event(
            provider=_FUENTE,
            event_type="oauth_connected",
            status="ok",
            account_id=adv_id,
            raw_payload={"by": updated_by},
        )
    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Normalización TikTok lead → IngestPayload
# ─────────────────────────────────────────────────────────────────────────────

# Mapeos ampliados para tolerar variantes del contrato (TikTok cambia
# nombres según locale y formulario).
_PHONE_KEYS = (
    "phone_number", "phone", "telephone", "telefono", "celular", "mobile",
    "numero_de_telefono", "número_de_teléfono", "numero_telefono", "número_teléfono",
    "numero_de_contacto", "número_de_contacto", "contacto", "tel", "cel",
    "whatsapp", "whatsapp_number", "whatsapp_phone", "whatsapp_phone_number",
    "numero_de_whatsapp", "número_de_whatsapp", "wa_number", "num_whatsapp",
    "nro_whatsapp", "telefono_whatsapp", "teléfono_whatsapp", "phone_whatsapp"
)
_EMAIL_KEYS = (
    "email", "correo", "correo_electronico", "correo_electrónico",
    "correo_de_contacto", "email_de_contacto"
)
_FULL_NAME_KEYS = (
    "full_name", "name", "nombre_completo", "nombre",
    "nombres_y_apellidos", "nombres_apellidos"
)
_FIRST_NAME_KEYS = ("first_name", "nombre", "nombres", "primer_nombre")
_LAST_NAME_KEYS = ("last_name", "apellido", "apellidos", "primer_apellido")



def _first_present(d: dict, keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if v:
            return str(v).strip() or None
    return None


def _split_full_name(full: str) -> tuple[Optional[str], Optional[str]]:
    parts = [p for p in (full or "").split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _form_fields_to_dict(form_fields: Iterable[Any]) -> dict:
    """Si TikTok devuelve campos custom como lista `[{name, value}]`,
    los plancha en un dict. Si ya es dict, lo devuelve tal cual."""
    if isinstance(form_fields, dict):
        return dict(form_fields)
    out: dict = {}
    if isinstance(form_fields, list):
        for item in form_fields:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("field_name")
            value = item.get("value") or item.get("field_value")
            if name and value is not None:
                out[str(name).strip().lower()] = str(value).strip()
    return out


def _parse_tiktok_datetime(value: Optional[str]) -> Optional[datetime]:
    """V068.4 — parsea el formato de fecha de TikTok CSV.
    TikTok manda strings tipo "2025-05-13 14:32:18 (UTC+00:00)" o ISO.
    Devuelve datetime UTC-aware o None si no se puede parsear."""
    if not value:
        return None
    try:
        s = str(value).strip()
        # Quitar el sufijo "(UTC...)" si esta presente — TikTok formato CSV
        if "(UTC" in s:
            s = s.split("(UTC")[0].strip()
        # ISO 8601 con o sin Z/offset
        s_norm = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s_norm)
        except ValueError:
            # Fallback al formato "YYYY-MM-DD HH:MM:SS"
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        # Si llega naive, asumimos UTC (TikTok siempre devuelve en UTC).
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return None


def normalize_tiktok_lead(
    lead: dict,
    *,
    campana: Optional[str] = None,
) -> tuple[IngestPayload, Optional[str]]:
    """Convierte un lead de TikTok al IngestPayload. Devuelve también el
    `external_id` del lead (para log y dedupe externo)."""
    lead = lead or {}
    # V068.1 — busqueda ampliada del identificador unico del lead. TikTok
    # varia la columna del CSV segun locale/formulario:
    #   "Lead ID"           -> lead_id
    #   "ID"                -> id
    #   "Form Lead ID"      -> form_lead_id
    #   "Submit ID"         -> submit_id
    #   "Response ID"       -> response_id
    #   "Form Response ID"  -> form_response_id
    #   "Submission ID"     -> submission_id
    # Antes solo se buscaban las 3 primeras, dejando fext=NULL para forms
    # cuya columna venia con otro nombre. Eso rompia la idempotencia
    # (uq_lead_recontactos_lead_fext de V052) y permitia recontactos
    # repetidos para el mismo cliente.
    external_id = _first_present(lead, (
        "lead_id", "id", "external_id",
        "form_lead_id", "submit_id", "submission_id",
        "response_id", "form_response_id",
    ))
    # V068.4 — captura del timestamp REAL del evento en TikTok (no cuando
    # nuestro poll lo descargó). Es la segunda fuente de verdad para
    # decidir si un nuevo touch es backfill (created_time anterior al lead)
    # o reactivacion real (created_time posterior).
    external_created_at = _parse_tiktok_datetime(
        lead.get("created_time")
        or lead.get("submit_time")
        or lead.get("submission_time")
    )

    # TikTok mete los datos del formulario en 'form_fields' o 'field_data'.
    merged: dict = {}
    merged.update(lead)
    merged.update(_form_fields_to_dict(lead.get("form_fields") or []))
    merged.update(_form_fields_to_dict(lead.get("field_data") or []))

    telefono = _first_present(merged, _PHONE_KEYS) or ""
    email    = _first_present(merged, _EMAIL_KEYS)
    nombres  = _first_present(merged, _FIRST_NAME_KEYS)
    apellidos = _first_present(merged, _LAST_NAME_KEYS)
    if not nombres and not apellidos:
        full = _first_present(merged, _FULL_NAME_KEYS)
        if full:
            nombres, apellidos = _split_full_name(full)

    # Campos de catálogo Meta que NO van a observaciones (se mapean a columnas
    # propias del lead o al cache de nombres legibles).
    catalog_keys = {
        "campaign_id", "campaign_name", "adgroup_id", "adgroup_name",
        "ad_id", "ad_name", "form_id", "form_name", "page_id",
    }

    # Campos restantes conocidos → observaciones
    known = set(_PHONE_KEYS + _EMAIL_KEYS + _FULL_NAME_KEYS + _FIRST_NAME_KEYS + _LAST_NAME_KEYS)
    extras: list[str] = []
    for k, v in merged.items():
        if k in known or k in catalog_keys:
            continue
        if k in ("form_fields", "field_data", "lead_id", "id", "external_id"):
            continue
        if v is None or v == "":
            continue
        if isinstance(v, (dict, list)):
            continue
        extras.append(f"{k}: {v}")

    # Catálogo Meta: campaign + form. Usamos los IDs como llaves de cache y
    # los nombres como hint para hidratar `meta_catalog_cache` desde ingest_core.
    campaign_id = (
        lead.get("campaign_id") or lead.get("ad_id") or lead.get("adgroup_id")
    )
    campana_out = campana or (str(campaign_id).strip() if campaign_id else None)
    campaign_name = (lead.get("campaign_name") or "").strip() or None
    form_id   = (str(lead.get("form_id") or "").strip()) or None
    form_name = (lead.get("form_name") or "").strip() or None

    return (
        IngestPayload(
            fuente=_FUENTE,
            telefono=telefono,
            nombres=nombres,
            apellidos=apellidos,
            email=email,
            campana=campana_out,
            fuente_externa_id=external_id,
            external_created_at=external_created_at,
            observaciones=" | ".join(extras) if extras else None,
            fuente_form_id=form_id,
            campaign_name=campaign_name,
            form_name=form_name,
        ),
        external_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador por advertiser
# ─────────────────────────────────────────────────────────────────────────────

def poll_advertiser(
    advertiser_id: str,
    *,
    fetch_client: Optional[httpx.Client] = None,
    lookback_hours: Optional[int] = None,
    since_override: Optional[datetime] = None,
    reset_checkpoint: bool = False,
    # V068.1 — default cambiado a True. Antes era False y dejaba que TikTok
    # aplicara su logica delta interna (sin start_time/end_time en el task).
    # En la practica TikTok respondia con todos los leads de su retencion
    # (~30 dias) en cada poll, regenerando recontactos diarios para los
    # mismos clientes. Con True, le pasamos la ventana explicita
    # [since, now] derivada del checkpoint — TikTok solo devuelve leads
    # nuevos del intervalo, no su set retenido completo.
    explicit_range: bool = True,
) -> dict:
    """Ejecuta una corrida completa para un advertiser.

    Maneja su propia conexión DB. Es seguro llamarlo en paralelo para
    advertisers distintos; dentro de un mismo advertiser, el checkpoint
    evita que dos corridas simultáneas pisen el cursor.

    Parámetros opcionales (para backfill manual desde admin endpoint):
      - lookback_hours:  ignora el checkpoint y trae leads desde now-N horas.
                         Tope: _MAX_LOOKBACK_HOURS (90 días).
      - since_override:  fecha exacta desde la que traer leads (UTC).
                         Tiene prioridad sobre lookback_hours.
      - reset_checkpoint: si True, marca el checkpoint en NULL para que
                          el próximo poll automático use lookback default.
    """
    t0 = time.perf_counter()
    provider = "tiktok"

    access_token = credentials_repo.get_plaintext(provider, "access_token", advertiser_id)
    if not access_token:
        events_repo.log_event(
            provider=provider,
            event_type="poll_error",
            status="error",
            account_id=advertiser_id,
            error_message="Sin access_token para advertiser.",
        )
        return {"ok": False, "reason": "missing_access_token", "advertiser_id": advertiser_id}

    # Override opcional para /page/get/ — ver CredentialKeySpec "pages_access_token".
    pages_access_token = credentials_repo.get_plaintext(
        provider, "pages_access_token", advertiser_id,
    )

    # Checkpoint previo
    checkpoint_repo.mark_run_start(provider, advertiser_id)
    prev = checkpoint_repo.get_checkpoint(provider, advertiser_id) or {}
    since: Optional[datetime] = prev.get("last_success_at")

    # Override manual del cursor — usado por endpoints admin (backfill).
    # Prioridad: since_override > lookback_hours > checkpoint > default
    if since_override is not None:
        since = since_override
    elif lookback_hours is not None:
        # Tope defensivo para evitar exports gigantes que tumben el polling.
        capped = max(1, min(int(lookback_hours), _MAX_LOOKBACK_HOURS))
        since = datetime.now(timezone.utc) - timedelta(hours=capped)

    try:
        leads = fetch_leads(
            advertiser_id=advertiser_id,
            access_token=access_token,
            since=since,
            client=fetch_client,
            pages_access_token=pages_access_token,
            explicit_range=explicit_range,
        )
    except TikTokAPIError as exc:
        checkpoint_repo.mark_run_error(provider, advertiser_id, str(exc))
        events_repo.log_event(
            provider=provider,
            event_type="poll_error",
            status="error",
            account_id=advertiser_id,
            error_message=str(exc),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        return {"ok": False, "reason": "fetch_failed", "error": str(exc)}

    created = 0
    duplicated = 0    # total (compat con metricas historicas)
    # V068.5 — breakdown granular: dentro de "duplicados", queremos saber
    # cuantos fueron skip puro (sin escribir nada) vs recontactos reales
    # (escribieron una fila en lead_recontactos). Asi el admin puede
    # auditar visualmente que el contador de "duplicados" no infla
    # recontactos espurios.
    skip_fext      = 0  # V068.2: mismo fext ya procesado (re-import)
    skip_same_day  = 0  # V068.3: same-day re-submission
    skip_backfill  = 0  # V068.4: external_created_at <= lead.created_at
    recontacto_real = 0  # handle_recontacto inserto una fila REAL
    skipped = 0
    errors = 0
    # Acumulamos leads creados por supervisor para mandar UN push batch al final
    # en vez de N pushes (especialmente importante en backfill donde pueden
    # entrar 100+ leads de una). Format: {supervisor_id: count}
    supervisor_counts: dict[str, int] = {}
    # V054.1: leads que se auto-asignaron a un asesor → push individual a
    # cada uno (su lead, su notif). Format: [{asesor_id, lead_name}, ...]
    asesor_pushes: list[dict] = []

    # Una sola conexión para todo el batch — minimiza overhead de pool.
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for raw in leads:
                payload, ext_id = normalize_tiktok_lead(raw)
                if not payload.telefono:
                    skipped += 1
                    events_repo.log_event(
                        provider=provider,
                        event_type="lead_duplicated" if False else "error",
                        status="skipped",
                        account_id=advertiser_id,
                        external_id=ext_id,
                        error_message="Lead sin teléfono.",
                    )
                    continue
                try:
                    result = ingest_lead_core(cur, payload)
                    conn.commit()
                except IngestError as exc:
                    errors += 1
                    conn.rollback()
                    events_repo.log_event(
                        provider=provider,
                        event_type="error",
                        status="error",
                        account_id=advertiser_id,
                        external_id=ext_id,
                        error_message=f"{exc.status_code}: {exc.detail}",
                    )
                    continue
                except Exception as exc:
                    errors += 1
                    conn.rollback()
                    logger.exception("tiktok.poll_advertiser fallo inesperado en lead: %s", exc)
                    events_repo.log_event(
                        provider=provider,
                        event_type="error",
                        status="error",
                        account_id=advertiser_id,
                        external_id=ext_id,
                        error_message=str(exc)[:500],
                    )
                    continue

                if result.get("duplicated"):
                    duplicated += 1
                    # V068.5 — clasificacion granular por reason / flag
                    reason = result.get("reason")
                    if reason == "fext_already_processed":
                        skip_fext += 1
                    elif reason == "same_day_resubmission":
                        skip_same_day += 1
                    elif result.get("recontacto"):
                        # handle_recontacto inserto realmente — distingue
                        # entre backfill_skip y recontacto real
                        if result.get("estrategia") == "backfill_skip":
                            skip_backfill += 1
                        else:
                            recontacto_real += 1
                    events_repo.log_event(
                        provider=provider,
                        event_type="lead_duplicated",
                        status="ok",
                        account_id=advertiser_id,
                        external_id=ext_id,
                        lead_id=result.get("id"),
                    )
                else:
                    created += 1
                    sup_id = result.get("supervisor_id")
                    asesor_id = result.get("asesor_id")
                    # Tracking dual: si auto-assign le dio asesor, va al
                    # asesor; sino se acumula al supervisor para batch.
                    if asesor_id:
                        asesor_pushes.append({
                            "asesor_id": asesor_id,
                            "lead_name": f"{result.get('nombres', '')} {result.get('apellidos') or ''}".strip(),
                            "lead_id":   result.get("id"),  # V070.91 para deep-link
                        })
                    elif sup_id:
                        supervisor_counts[sup_id] = supervisor_counts.get(sup_id, 0) + 1
                    events_repo.log_event(
                        provider=provider,
                        event_type="lead_created",
                        status="ok",
                        account_id=advertiser_id,
                        external_id=ext_id,
                        lead_id=result.get("id"),
                    )
        conn.commit()

    # Push notifications. Pattern:
    #  - Leads ya asignados a un asesor → push individual al asesor
    #    (asi cada uno recibe alerta por sus propios leads).
    #  - Leads en cola del supervisor → push agregado al supervisor con
    #    el total (evita spam si entran 50+ leads en una oleada).
    # Best-effort en ambos casos: fallos de FCM no rompen el ingest.
    try:
        from app.services.notification_service import notify_new_lead
        for push in asesor_pushes:
            try:
                # V070.91 — lead_id para deep-link al tap.
                notify_new_lead(
                    push["asesor_id"], push["lead_name"],
                    fuente="tiktok", lead_id=push.get("lead_id"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "tiktok push individual fallido asesor=%s: %s",
                    push["asesor_id"], exc,
                )
        if supervisor_counts:
            for sup_id, count in supervisor_counts.items():
                body = "1 lead nuevo desde TikTok" if count == 1 else f"{count} leads nuevos desde TikTok"
                # Push agregado al supervisor (varios leads en una oleada).
                # NO pasamos lead_id porque hay N leads. El tap llevara a la
                # lista de leads (fallback) en vez de a un detalle especifico.
                notify_new_lead(sup_id, body, fuente="tiktok")
        logger.info(
            "tiktok.poll_advertiser advertiser=%s push: %d asesor(es) + %d supervisor(es), total %d leads",
            advertiser_id, len(asesor_pushes), len(supervisor_counts), created,
        )
    except Exception as exc:  # noqa: BLE001 — push fallido no rompe ingest
        logger.warning(
            "tiktok.poll_advertiser advertiser=%s push fallido: %s",
            advertiser_id, exc,
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    checkpoint_repo.mark_run_success(
        provider=provider,
        account_id=advertiser_id,
        items=len(leads),
        cursor_at=datetime.now(timezone.utc),
    )
    events_repo.log_event(
        provider=provider,
        event_type="poll_success",
        status="ok",
        account_id=advertiser_id,
        latency_ms=latency_ms,
        raw_payload={
            "fetched":     len(leads),
            "created":     created,
            "duplicated":  duplicated,
            "skipped":     skipped,
            "errors":      errors,
            # V068.5 — breakdown del duplicated
            "skip_fext":         skip_fext,
            "skip_same_day":     skip_same_day,
            "skip_backfill":     skip_backfill,
            "recontacto_real":   recontacto_real,
        },
    )
    return {
        "ok":          True,
        "fetched":     len(leads),
        "created":     created,
        "duplicated":  duplicated,
        "skipped":     skipped,
        "errors":      errors,
        # V068.5 — breakdown granular del bucket "duplicated":
        #  - skip_fext       = fext ya procesado (re-import del polling)
        #  - skip_same_day   = telefono existe pero lead creado hoy
        #  - skip_backfill   = evento del proveedor anterior al lead
        #  - recontacto_real = cliente realmente volvio (fila nueva en
        #                      crm.lead_recontactos)
        "skip_fext":         skip_fext,
        "skip_same_day":     skip_same_day,
        "skip_backfill":     skip_backfill,
        "recontacto_real":   recontacto_real,
        "latency_ms":  latency_ms,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de descubrimiento de advertisers
# ─────────────────────────────────────────────────────────────────────────────

def list_configured_advertisers() -> list[str]:
    """Devuelve los account_id (advertiser_id) con access_token configurado."""
    items = credentials_repo.list_credentials("tiktok")
    return sorted({
        it["account_id"] for it in items
        if it["key"] == "access_token" and it.get("has_value")
    })


def get_polling_interval_minutes() -> int:
    """Lee `polling_interval_min` del registry, con defaults seguros."""
    raw = credentials_repo.get_plaintext("tiktok", "polling_interval_min")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 10
    return max(5, min(val, 60))


def fetch_campaign_insights(
    fecha_desde: str,
    fecha_hasta: str,
    advertiser_id: str,
    access_token: str
) -> dict:
    """Extrae métricas reales agrupadas por campaña desde TikTok Marketing API.
    
    Returns:
        dict: Las métricas mapeadas.
    """
    url = f"{TIKTOK_API_BASE}/report/integrated/get/"
    headers = {"Access-Token": access_token}
    
    import json
    params = {
        "advertiser_id": advertiser_id,
        "report_type": "BASIC",
        "data_level": "AUCTION_CAMPAIGN",
        "dimensions": json.dumps(["campaign_id"]),
        "metrics": json.dumps(["spend", "impressions", "clicks", "conversion"]),
        "start_date": fecha_desde,
        "end_date": fecha_hasta,
        "page_size": 100
    }
    
    global_metrics = {"spend": 0.0, "impressions": 0, "clicks": 0, "results": 0}
    campaigns = []
    trend_data = []
    
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.error("TikTok API error: %s", resp.text)
                return {"global": global_metrics, "campaigns": campaigns, "trend": trend_data}
                
            body = resp.json()
            if body.get("code") != 0:
                logger.error("TikTok API response error: %s", body)
                return {"global": global_metrics, "campaigns": campaigns, "trend": trend_data}
                
            data = body.get("data", {}).get("list", [])
            for row in data:
                metrics = row.get("metrics", {})
                dims = row.get("dimensions", {})
                
                c_spend = float(metrics.get("spend", 0.0))
                c_impressions = int(metrics.get("impressions", 0))
                c_clicks = int(metrics.get("clicks", 0))
                c_results = int(metrics.get("conversion", 0))
                
                c_cpm = round((c_spend / c_impressions) * 1000, 2) if c_impressions > 0 else 0.0
                c_cpr = round(c_spend / c_results, 2) if c_results > 0 else 0.0
                
                # Para simplificar, usamos el ID si no hay name, TikTok a veces expone el nombre junto con otras dimensiones.
                campaigns.append({
                    "name": dims.get("campaign_name") or str(dims.get("campaign_id", "Sin campaña")),
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

            # Obtener tendencia diaria para TikTok
            trend_params = {
                "advertiser_id": advertiser_id,
                "report_type": "BASIC",
                "data_level": "AUCTION_ADVERTISER",
                "dimensions": json.dumps(["stat_time_day"]),
                "metrics": json.dumps(["spend", "conversion"]),
                "start_date": fecha_desde,
                "end_date": fecha_hasta,
                "page_size": 100
            }
            resp_trend = client.get(url, params=trend_params, headers=headers)
            if resp_trend.status_code == 200:
                body_t = resp_trend.json()
                if body_t.get("code") == 0:
                    for row in body_t.get("data", {}).get("list", []):
                        metrics = row.get("metrics", {})
                        dims = row.get("dimensions", {})
                        day_results = int(metrics.get("conversion", 0))
                        day_date = dims.get("stat_time_day", "").split(" ")[0]
                        trend_data.append({
                            "fecha": day_date,
                            "leads": day_results,
                            "conversions": day_results,
                            "spend": float(metrics.get("spend", 0.0))
                        })
                    trend_data.sort(key=lambda x: x["fecha"])
                    
    except Exception as exc:
        logger.warning("Error fetch_campaign_insights (TikTok): %s", exc)
        
    return {"global": global_metrics, "campaigns": campaigns, "trend": trend_data}

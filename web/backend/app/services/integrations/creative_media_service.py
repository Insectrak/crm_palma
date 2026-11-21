"""Descarga y cachea los thumbnails/medios visuales de ads Meta (V037).

Problema:
  Graph API entrega URLs CDN (*.fbcdn.net) que caducan/requieren firma en
  horas. Si la UI depende de esas URLs en cada render, eventualmente se
  rompe. Ademas, servir desde *.fbcdn.net desde el frontend expone los
  parametros firmados del anunciante y cruza CORS.

Solucion:
  Cuando enriquecemos un wa_campaign resolvemos el creative y, si hay
  thumbnail_url, lo descargamos una sola vez al servidor y lo guardamos
  en crm.meta_creative_cache (BYTEA). El frontend siempre pide la imagen
  al backend (/api/whatsapp/campaigns/{id}/creative-thumbnail). Mismo
  patron que crm.wa_media_cache para medias de WhatsApp.

Seguridad (SSRF-safe):
  - Solo https.
  - Dominio restringido al CDN de Meta (fbcdn.net, cdninstagram.com).
  - Tamano maximo 5 MB (thumbnails son tipicamente <200 KB).
  - Content-Type debe empezar por image/*.
  - Timeout de 15 s.

No levanta: cualquier fallo se persiste como `creative_media_error` en
la campana y se loggea. Es safe para correr dentro de BackgroundTask.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx
import psycopg2

from app.database import get_db

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT_S = 15.0
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB — thumbnails real-world son <200KB.
_ALLOWED_HOST_SUFFIXES = (
    ".fbcdn.net",
    ".cdninstagram.com",
    ".facebook.com",
)


def _is_allowed_url(url: str) -> bool:
    """Whitelist estricta: solo https + dominios CDN de Meta."""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_HOST_SUFFIXES)


def _persist_media_error(wa_campaign_id: int, reason: str) -> None:
    reason_trimmed = (reason or "")[:200]
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE crm.wa_campaigns
                       SET creative_media_error     = %s,
                           creative_media_cached_at = NULL,
                           updated_at               = NOW()
                     WHERE id = %s
                    """,
                    (reason_trimmed, wa_campaign_id),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "creative_media_service._persist_media_error id=%s: %s",
            wa_campaign_id, exc,
        )


def _store_media(
    wa_campaign_id: int,
    *,
    media_kind: str,
    mime_type: str,
    data: bytes,
    source_url: str,
) -> None:
    """Upsert del binario en meta_creative_cache + flag cached_at en wa_campaigns."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crm.meta_creative_cache
                    (wa_campaign_id, media_kind, mime_type, size_bytes, data, source_url, cached_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (wa_campaign_id) DO UPDATE
                SET media_kind = EXCLUDED.media_kind,
                    mime_type  = EXCLUDED.mime_type,
                    size_bytes = EXCLUDED.size_bytes,
                    data       = EXCLUDED.data,
                    source_url = EXCLUDED.source_url,
                    cached_at  = NOW()
                """,
                (
                    wa_campaign_id,
                    media_kind,
                    mime_type,
                    len(data),
                    psycopg2.Binary(data),
                    source_url,
                ),
            )
            cur.execute(
                """
                UPDATE crm.wa_campaigns
                   SET creative_media_cached_at = NOW(),
                       creative_media_error     = NULL,
                       updated_at               = NOW()
                 WHERE id = %s
                """,
                (wa_campaign_id,),
            )
        conn.commit()


def download_and_cache_thumbnail(
    wa_campaign_id: int,
    thumbnail_url: Optional[str],
    *,
    client: Optional[httpx.Client] = None,
) -> dict:
    """Descarga el thumbnail del creative y lo cachea. Retorna {ok, reason?}.

    Idempotente: sobreescribe el cache si ya existia. Nunca levanta.
    """
    if not wa_campaign_id:
        return {"ok": False, "reason": "missing_wa_campaign_id"}
    url = (thumbnail_url or "").strip()
    if not url:
        _persist_media_error(wa_campaign_id, "graph_empty")
        return {"ok": False, "reason": "graph_empty"}
    if not _is_allowed_url(url):
        _persist_media_error(wa_campaign_id, "url_not_allowed")
        return {"ok": False, "reason": "url_not_allowed"}

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True)
    try:
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            reason = f"http_error:{type(exc).__name__}"
            _persist_media_error(wa_campaign_id, reason)
            logger.warning(
                "creative_media.download id=%s url_host=%s error=%s",
                wa_campaign_id, urlparse(url).hostname, exc,
            )
            return {"ok": False, "reason": reason}

        if resp.status_code != 200:
            reason = f"http_{resp.status_code}"
            _persist_media_error(wa_campaign_id, reason)
            logger.warning(
                "creative_media.download id=%s status=%s",
                wa_campaign_id, resp.status_code,
            )
            return {"ok": False, "reason": reason}

        mime = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not mime.startswith("image/"):
            _persist_media_error(wa_campaign_id, f"mime_invalid:{mime or 'none'}")
            return {"ok": False, "reason": "mime_invalid"}

        data = resp.content or b""
        if not data:
            _persist_media_error(wa_campaign_id, "empty_body")
            return {"ok": False, "reason": "empty_body"}
        if len(data) > _MAX_BYTES:
            _persist_media_error(wa_campaign_id, f"too_large:{len(data)}")
            return {"ok": False, "reason": "too_large"}

        try:
            _store_media(
                wa_campaign_id,
                media_kind="thumbnail",
                mime_type=mime,
                data=data,
                source_url=url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "creative_media.store id=%s error=%s",
                wa_campaign_id, exc,
            )
            _persist_media_error(wa_campaign_id, f"store_error:{type(exc).__name__}")
            return {"ok": False, "reason": "store_error"}

        logger.info(
            "creative_media.cached id=%s mime=%s bytes=%d",
            wa_campaign_id, mime, len(data),
        )
        return {"ok": True, "mime": mime, "size": len(data)}
    finally:
        if own_client:
            client.close()


def get_cached_thumbnail(wa_campaign_id: int) -> Optional[tuple[bytes, str]]:
    """Lee el binario cacheado. Retorna (data, mime) o None si no existe."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT data, mime_type
                  FROM crm.meta_creative_cache
                 WHERE wa_campaign_id = %s
                """,
                (wa_campaign_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return bytes(row[0]), row[1]

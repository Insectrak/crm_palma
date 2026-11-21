"""Router admin para TikTok Lead Gen.

TikTok no expone webhooks: la ingesta corre por polling cada N minutos en
`scheduler.py`. Este router agrega endpoints admin sobre esa base:

  - POST /api/integrations/tiktok/advertisers/{advertiser_id}/poll
        Ejecuta `tiktok_service.poll_advertiser(advertiser_id)` en el momento.
        Devuelve el resumen (fetched / created / duplicated / skipped / errors).

  - POST /api/integrations/tiktok/oauth/authorize
        Admin-only. Devuelve la URL del portal TikTok a la que el usuario
        debe ser redirigido para autorizar los advertisers. El `state` es un
        JWT corto firmado con SECRET_KEY — sin DB intermedia, sin race.

  - GET  /api/integrations/tiktok/oauth/callback
        Público (TikTok redirige el navegador acá sin Bearer). Valida el
        state JWT, intercambia `auth_code` por `access_token` contra
        `/oauth2/access_token/`, persiste token por advertiser_id en
        credentials_repo y redirige al CRM con ?connected=N.

Diseño:
  - Admin-only salvo callback (que exige state firmado).
  - El servicio ya emite eventos en `crm.integrations_events`; este router
    solo orquesta HTTP.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.config import settings
from app.services.integrations import (
    checkpoint_repo,
    credentials_repo,
    events_repo,
    tiktok_service,
)
from app.services.integrations.credentials_repo import GLOBAL_ACCOUNT
from app.services.integrations.tiktok_service import TikTokAPIError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrations/tiktok", tags=["Integraciones · TikTok"])


# ─────────────────────────────────────────────────────────────────────────────
# Poll manual (ya existente)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/advertisers/{advertiser_id}/poll")
def tiktok_manual_poll(
    advertiser_id: str = Path(..., min_length=1, max_length=120),
    lookback_hours: Optional[int] = Query(
        None, ge=1, le=90 * 24,
        description="Override de ventana de polling en horas (1-2160). Default: usa checkpoint o 168h.",
    ),
    since: Optional[str] = Query(
        None,
        description="Override exacto: fecha ISO (YYYY-MM-DD o YYYY-MM-DDTHH:MM:SSZ) desde la que traer leads. Tiene prioridad sobre lookback_hours.",
    ),
    admin: TokenData = Depends(require_admin),
):
    """Dispara un poll inmediato para el advertiser indicado.

    Query params opcionales (admin only):
      - lookback_hours: ignora el checkpoint y trae leads desde now-N horas.
                        Tope: 90 días (2160h).
      - since:          fecha exacta ISO desde la que traer (UTC).
                        Tiene prioridad sobre lookback_hours.

    Sin query params → comportamiento estándar (usa checkpoint o default 168h).

    Devuelve el mismo dict que el poll del scheduler:
      ok=True  → {fetched, created, duplicated, skipped, errors, latency_ms}
      ok=False → {reason, ...} (missing_access_token, fetch_failed, exception)
    """
    # Parse since (ISO date) si viene
    since_dt: Optional[datetime] = None
    if since:
        try:
            # Acepta YYYY-MM-DD o ISO con tiempo. Asume UTC si no hay tz.
            cleaned = since.strip().replace("Z", "+00:00")
            if "T" not in cleaned:
                cleaned = f"{cleaned}T00:00:00+00:00"
            since_dt = datetime.fromisoformat(cleaned)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de 'since' inválido: {since}. Usa YYYY-MM-DD o YYYY-MM-DDTHH:MM:SSZ",
            ) from exc

    logger.info(
        "tiktok.manual_poll advertiser_id=%s triggered_by=%s lookback_hours=%s since=%s",
        advertiser_id, admin.email, lookback_hours, since_dt,
    )
    try:
        result = tiktok_service.poll_advertiser(
            advertiser_id,
            lookback_hours=lookback_hours,
            since_override=since_dt,
        )
    except Exception as exc:                                # pragma: no cover - safety net
        logger.exception("tiktok.manual_poll crash advertiser_id=%s", advertiser_id)
        return JSONResponse(
            {"ok": False, "reason": "exception", "error": str(exc),
             "advertiser_id": advertiser_id},
            status_code=500,
        )
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Backfill: reset checkpoint + poll con ventana extendida en una operación
# ─────────────────────────────────────────────────────────────────────────────

class BackfillPayload(BaseModel):
    """Payload del backfill manual.

    Uno de los dos campos es obligatorio:
      - lookback_days: cantidad de días hacia atrás (1-90)
      - since:         fecha ISO YYYY-MM-DD (UTC)
    """
    lookback_days: Optional[int] = Field(None, ge=1, le=90, description="Días hacia atrás (1-90)")
    since: Optional[str]         = Field(None, description="Fecha ISO YYYY-MM-DD desde la que traer leads")


@router.post("/advertisers/{advertiser_id}/backfill")
def tiktok_backfill(
    advertiser_id: str = Path(..., min_length=1, max_length=120),
    payload: BackfillPayload = ...,
    admin: TokenData = Depends(require_admin),
):
    """Backfill manual: resetea el checkpoint y dispara poll con ventana extendida.

    Útil para:
      - Re-traer leads borrados accidentalmente
      - Primer poll de un advertiser recién registrado con histórico
      - Recuperar de outage prolongado del scheduler

    Body:
      { "lookback_days": 30 }       # últimos 30 días
      { "since": "2026-03-01" }     # desde el 1 de marzo (prioridad sobre lookback_days)

    Resetea last_success_at a NULL antes de correr — el próximo poll
    automático del scheduler usará el lookback default (168h).
    """
    if not payload.lookback_days and not payload.since:
        raise HTTPException(
            status_code=400,
            detail="Debes enviar 'lookback_days' o 'since' en el body.",
        )

    # Parse since si viene
    since_dt: Optional[datetime] = None
    if payload.since:
        try:
            cleaned = payload.since.strip().replace("Z", "+00:00")
            if "T" not in cleaned:
                cleaned = f"{cleaned}T00:00:00+00:00"
            since_dt = datetime.fromisoformat(cleaned)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400,
                detail="Formato de 'since' inválido. Usa YYYY-MM-DD",
            ) from exc

    # Resetea checkpoint primero — para que aunque el poll falle a medias,
    # el próximo automático no caiga al cursor viejo y skipee leads.
    reset_done = checkpoint_repo.reset_checkpoint("tiktok", advertiser_id)

    lookback_hours = payload.lookback_days * 24 if payload.lookback_days else None

    logger.info(
        "tiktok.backfill advertiser_id=%s triggered_by=%s lookback_days=%s "
        "since=%s checkpoint_reset=%s",
        advertiser_id, admin.email, payload.lookback_days, since_dt, reset_done,
    )

    try:
        # explicit_range=True fuerza a TikTok a entregar leads en el rango
        # exacto, ignorando su lógica delta interna (que skipea leads ya
        # exportados por tasks anteriores). Esto es lo que diferencia el
        # backfill admin del polling automático.
        result = tiktok_service.poll_advertiser(
            advertiser_id,
            lookback_hours=lookback_hours,
            since_override=since_dt,
            explicit_range=True,
        )
    except Exception as exc:                                # pragma: no cover
        logger.exception("tiktok.backfill crash advertiser_id=%s", advertiser_id)
        return JSONResponse(
            {"ok": False, "reason": "exception", "error": str(exc),
             "advertiser_id": advertiser_id, "checkpoint_reset": reset_done},
            status_code=500,
        )

    # Anota el reset en la respuesta — útil para debug
    result["checkpoint_reset"] = reset_done
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# OAuth — state firmado (JWT corto) sin DB intermedia
# ─────────────────────────────────────────────────────────────────────────────

_STATE_PURPOSE = "tiktok_oauth"
_STATE_TTL_SECONDS = 300  # 5 min — suficiente para que el admin apruebe

# herramienta premium al que redirigimos después del callback. Usamos una ruta relativa:
# si el frontend está montado sobre el mismo host, el navegador resuelve bien.
_UI_RETURN_PATH = "/integraciones?tab=tiktok"


def _issue_state_token(admin: TokenData) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":     admin.user_id,
        "email":   admin.email,
        "role":    admin.role,
        "purpose": _STATE_PURPOSE,
        "nonce":   secrets.token_urlsafe(16),
        "iat":     int(now.timestamp()),
        "exp":     int((now + timedelta(seconds=_STATE_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _verify_state_token(token: str) -> dict:
    """Valida el state JWT. Levanta HTTPException si inválido/expirado/mal-propósito."""
    if not token:
        raise HTTPException(400, "state ausente.")
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm],
        )
    except JWTError as exc:
        raise HTTPException(400, f"state inválido: {exc}") from exc
    if payload.get("purpose") != _STATE_PURPOSE:
        raise HTTPException(400, "state con propósito incorrecto.")
    if payload.get("role") != "admin":
        raise HTTPException(403, "state no corresponde a un admin.")
    return payload


def _get_redirect_uri(base_url: Optional[str] = None) -> str:
    """Redirect URI registrado en el app de TikTok.

    Permite override por credencial (provider=tiktok, key=oauth_redirect_uri)
    para casos donde el host difiere del registrado (ej. dev tunneling).
    Default = el endpoint oficial del CRM en producción.
    """
    override = credentials_repo.get_plaintext("tiktok", "oauth_redirect_uri")
    if override:
        return override
    # Default alineado con el Redirect URL cargado en el portal de TikTok.
    if not base_url:
        base_url = settings.get_public_base_url()
    return f"{base_url}/api/integrations/tiktok/oauth/callback"


class AuthorizeResponse(BaseModel):
    authorize_url: str = Field(..., description="URL del portal TikTok para autorizar.")
    state:         str = Field(..., description="JWT firmado (se valida en callback).")
    redirect_uri:  str = Field(..., description="Redirect URI registrado en el app.")


@router.post("/oauth/authorize", response_model=AuthorizeResponse)
def tiktok_oauth_authorize(
    request: Request,
    admin: TokenData = Depends(require_admin),
):
    """Arma y devuelve la URL a la que el admin debe ir para autorizar.

    El frontend recibe `authorize_url` y hace `window.open(url)` — TikTok
    se encarga de mostrar el consentimiento. El `state` retorna firmado; al
    recibir el callback lo validamos sin tabla intermedia.
    """
    app_id = credentials_repo.get_plaintext("tiktok", "app_id")
    if not app_id:
        raise HTTPException(400, "app_id de TikTok no configurado.")

    req_base = str(request.base_url).rstrip("/")
    # Si el request viene de un host público real, lo usamos.
    # De lo contrario (ej. dev local), recurrimos al public_base_url configurado.
    if "localhost" not in req_base and "127.0.0.1" not in req_base and "0.0.0.0" not in req_base:
        # En producción los proxies terminan SSL (Caddy/EasyPanel), convirtiendo
        # la petición interna a HTTP. Forzamos HTTPS para el callback de TikTok.
        if req_base.startswith("http://"):
            base_url = "https://" + req_base[7:]
        else:
            base_url = req_base
    else:
        base_url = settings.get_public_base_url()

    redirect_uri = _get_redirect_uri(base_url)
    state = _issue_state_token(admin)
    try:
        url = tiktok_service.build_authorize_url(
            app_id=app_id,
            redirect_uri=redirect_uri,
            state=state,
        )
    except TikTokAPIError as exc:
        raise HTTPException(400, str(exc)) from exc

    events_repo.log_event(
        provider="tiktok",
        event_type="oauth_authorize",
        status="ok",
        account_id=GLOBAL_ACCOUNT,
        raw_payload={"by": admin.email},
    )
    return AuthorizeResponse(
        authorize_url=url, state=state, redirect_uri=redirect_uri,
    )


@router.get("/oauth/callback")
def tiktok_oauth_callback(
    auth_code: Optional[str] = Query(None, alias="auth_code", max_length=2048),
    code:      Optional[str] = Query(None, max_length=2048),
    state:     Optional[str] = Query(None, max_length=2048),
    error:     Optional[str] = Query(None, max_length=120),
    error_description: Optional[str] = Query(None, alias="error_description", max_length=500),
):
    """Callback OAuth de TikTok.

    TikTok envía `auth_code` en algunas versiones y `code` en otras; aceptamos
    ambos. Si el usuario cancela, llega `error` + `error_description` en lugar
    de `auth_code` — se loggea y se redirige al UI con el mensaje.

    No usa `require_admin`: TikTok redirige el navegador sin cabecera Authorization.
    La autenticación del callback es el **state JWT** firmado por nosotros.
    """
    # 1. Manejo de error explícito de TikTok (usuario canceló, scope inválido, etc.)
    if error:
        events_repo.log_event(
            provider="tiktok",
            event_type="oauth_error",
            status="error",
            account_id=GLOBAL_ACCOUNT,
            error_message=f"{error}: {error_description or ''}",
        )
        return RedirectResponse(
            url=f"{_UI_RETURN_PATH}&oauth=error&reason={error}",
            status_code=303,
        )

    effective_code = auth_code or code
    if not effective_code:
        raise HTTPException(400, "auth_code o code requerido.")

    # 2. Validar state (el único factor de autenticación de este endpoint)
    state_payload = _verify_state_token(state or "")
    admin_email = state_payload.get("email")
    admin_user_id = state_payload.get("sub")

    # 3. Intercambiar auth_code por access_token
    app_id = credentials_repo.get_plaintext("tiktok", "app_id")
    app_secret = credentials_repo.get_plaintext("tiktok", "app_secret")
    if not app_id or not app_secret:
        events_repo.log_event(
            provider="tiktok",
            event_type="oauth_error",
            status="error",
            account_id=GLOBAL_ACCOUNT,
            error_message="app_id o app_secret no configurados en callback.",
        )
        return RedirectResponse(
            url=f"{_UI_RETURN_PATH}&oauth=error&reason=missing_app_credentials",
            status_code=303,
        )

    try:
        oauth_result = tiktok_service.exchange_auth_code(
            app_id=app_id,
            app_secret=app_secret,
            auth_code=effective_code,
        )
    except TikTokAPIError as exc:
        logger.warning("tiktok.oauth_callback exchange_failed: %s", exc)
        events_repo.log_event(
            provider="tiktok",
            event_type="oauth_error",
            status="error",
            account_id=GLOBAL_ACCOUNT,
            error_message=f"exchange_failed: {exc}",
        )
        return RedirectResponse(
            url=f"{_UI_RETURN_PATH}&oauth=error&reason=exchange_failed",
            status_code=303,
        )

    # 4. Persistir token por advertiser_id
    try:
        saved = tiktok_service.save_oauth_result(
            oauth_result=oauth_result,
            updated_by=admin_user_id,
        )
    except TikTokAPIError as exc:
        logger.warning("tiktok.oauth_callback save_failed: %s", exc)
        events_repo.log_event(
            provider="tiktok",
            event_type="oauth_error",
            status="error",
            account_id=GLOBAL_ACCOUNT,
            error_message=f"save_failed: {exc}",
            raw_payload=tiktok_service.summarize_oauth_result(oauth_result),
        )
        return RedirectResponse(
            url=f"{_UI_RETURN_PATH}&oauth=error&reason=save_failed",
            status_code=303,
        )

    logger.info(
        "tiktok.oauth_callback connected advertisers=%d by=%s",
        len(saved), admin_email,
    )
    return RedirectResponse(
        url=f"{_UI_RETURN_PATH}&oauth=ok&advertisers={len(saved)}",
        status_code=303,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Settings — cadencia del polling automatico
# ─────────────────────────────────────────────────────────────────────────────

class TikTokSettingsResponse(BaseModel):
    polling_interval_min: int = Field(..., description="Minutos entre ciclos del scheduler.")
    min: int = Field(5, description="Limite minimo permitido.")
    max: int = Field(60, description="Limite maximo permitido.")


class TikTokSettingsPayload(BaseModel):
    polling_interval_min: int = Field(..., ge=5, le=60, description="Minutos entre ciclos (5-60).")


@router.get("/settings", response_model=TikTokSettingsResponse)
def tiktok_get_settings(admin: TokenData = Depends(require_admin)):
    """Devuelve la cadencia actual del polling. Si nunca se seteo, usa
    el default del servicio (10 min). El scheduler relee este valor al
    cierre de cada ciclo, asi que no requiere reinicio.
    """
    return TikTokSettingsResponse(
        polling_interval_min=tiktok_service.get_polling_interval_minutes(),
    )


@router.patch("/settings", response_model=TikTokSettingsResponse)
def tiktok_patch_settings(
    payload: TikTokSettingsPayload,
    admin: TokenData = Depends(require_admin),
):
    """Cambia la cadencia del polling. Toma efecto en el siguiente ciclo
    (al maximo dentro del intervalo anterior). El cambio queda persistido
    en crm.integrations_credentials y sobrevive a reinicios.
    """
    try:
        credentials_repo.upsert_credential(
            provider="tiktok",
            key="polling_interval_min",
            value=str(payload.polling_interval_min),
            updated_by=admin.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("tiktok.patch_settings failed by=%s", admin.email)
        raise HTTPException(500, f"No se pudo guardar la cadencia: {exc}") from exc

    events_repo.log_event(
        provider="tiktok",
        event_type="settings_updated",
        status="ok",
        account_id=GLOBAL_ACCOUNT,
        raw_payload={"polling_interval_min": payload.polling_interval_min, "by": admin.email},
    )
    logger.info(
        "tiktok.patch_settings polling_interval_min=%d by=%s",
        payload.polling_interval_min, admin.email,
    )
    return TikTokSettingsResponse(
        polling_interval_min=tiktok_service.get_polling_interval_minutes(),
    )

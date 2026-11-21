"""
observability.py — inicialización de Sentry para error tracking.

V070.66 — Tras el bug de KeyError en lead_recapture que tomó 4h destrabar
porque estaba silenciado en logger.debug, agregamos un canal externo de
visibilidad. Sentry captura excepciones no-handled + warnings selectos y
los manda a un dashboard que el equipo puede consultar sin entrar a
EasyPanel a leer logs de Docker.

V070.99 — PII scrubbing comprehensivo + tags multi-tenant. patrón estándar:
  - Cada evento se enmascara con pii_utils antes de salir del proceso.
  - Tags estandar: tenant, api_client_id, user_id, environment, release.
  - Helper set_tenant_context() para que routers/middlewares seteen el
    contexto sin acoplarse a sentry_sdk directamente.

Diseño (SOLID / SRP):
  - Esta función SOLO inicializa Sentry. No la importan los routers
    (solo set_tenant_context si necesitan tagear).
  - Si SENTRY_DSN está vacío, NO hace nada (no impacta clientes sin
    Sentry configurado — ej. Doctor Muelita al arrancar).
  - Filtros para EXCLUIR:
      - Health checks (/health, /api/health, /metrics) — ruido sin valor
      - Request validation errors 422 (los manda FastAPI/Pydantic por
        diseño, no son bugs)
      - Excepciones de rate limit (esperadas)
  - PII scrubbing automatico en before_send (telefonos, emails, DNI,
    secretos en headers/body/extra/breadcrumbs).

Cada cliente del CRM puede usar su propio proyecto en Sentry:
  - Free tier: 5K eventos/mes por organización
  - Aislamiento por DSN → un cliente nunca ve errores del otro
"""
import logging
from typing import Any, Optional

from app.pii_utils import mask_phone, mask_email, mask_dni

logger = logging.getLogger(__name__)


# Excepciones que NO ameritan capturar en Sentry (ruido).
_IGNORED_STATUS_CODES = {422, 429}  # validation errors + rate limit

# Endpoints donde queremos descartar transacciones (ruido de health checks).
_IGNORED_TRANSACTIONS = {
    "/health",
    "/api/health",
    "/api/whatsapp/webhook",  # webhook con HMAC, lo audita el router
    "/metrics",                # prometheus scraper — ruido constante
}

# V070.99 — Claves que SIEMPRE se enmascaran en cualquier event/breadcrumb.
# Cubrimos request body, query params, form data, extras y context. Ley 29733 PE.
_PHONE_KEYS = frozenset({"telefono", "phone", "wa_phone", "to", "from", "msisdn",
                          "asesor_telefono", "celular"})
_EMAIL_KEYS = frozenset({"email", "correo", "user_email"})
_DNI_KEYS   = frozenset({"dni", "doc", "documento", "tipo_documento_numero"})
# Claves a borrar por completo (jamas deben salir del proceso).
_SECRET_KEYS = frozenset({"password", "password_hash", "secret", "api_key",
                          "x-api-key", "authorization", "token", "refresh_token",
                          "wa_webhook_secret", "fcm_service_account_b64",
                          "smtp_password", "database_url"})


def _scrub_value(key: str, value: Any) -> Any:
    """Enmascara value segun el key. Usado recursivamente."""
    if value is None:
        return None
    k_lower = str(key).lower()
    if k_lower in _SECRET_KEYS:
        return "[REDACTED]"
    if k_lower in _PHONE_KEYS and isinstance(value, str):
        return mask_phone(value)
    if k_lower in _EMAIL_KEYS and isinstance(value, str):
        return mask_email(value)
    if k_lower in _DNI_KEYS and isinstance(value, str):
        return mask_dni(value)
    return value


def _scrub_recursive(obj: Any, depth: int = 0) -> Any:
    """Recorre estructura nested aplicando _scrub_value. Cap a depth 8."""
    if depth > 8:
        return obj
    if isinstance(obj, dict):
        return {k: _scrub_recursive(_scrub_value(k, v), depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_recursive(v, depth + 1) for v in obj]
    return obj


def _before_send(event: dict, hint: dict) -> Optional[dict]:
    """Filtra eventos antes de mandarlos a Sentry.

    Devuelve None para descartar el evento. Devuelve el dict para mandarlo.
    """
    # 1. Descartar HTTPException con status code esperado (422/429)
    exc_info = hint.get("exc_info")
    if exc_info:
        exc_type, exc_value, _ = exc_info
        # FastAPI HTTPException tiene .status_code
        status = getattr(exc_value, "status_code", None)
        if status in _IGNORED_STATUS_CODES:
            return None

    # 2. Descartar transacciones de health/webhook
    transaction = event.get("transaction") or ""
    if transaction in _IGNORED_TRANSACTIONS:
        return None
    for path in _IGNORED_TRANSACTIONS:
        if transaction.endswith(path):
            return None

    # 3. V070.99 — PII scrubbing comprehensivo del evento completo.
    # Cubre request.data, request.query_string, extra, contexts, breadcrumbs.
    try:
        if "request" in event:
            req = event["request"]
            for field in ("data", "query_string", "headers", "cookies", "env"):
                if field in req:
                    req[field] = _scrub_recursive(req[field])
        if "extra" in event:
            event["extra"] = _scrub_recursive(event["extra"])
        if "contexts" in event:
            event["contexts"] = _scrub_recursive(event["contexts"])
        if "breadcrumbs" in event and isinstance(event["breadcrumbs"], dict):
            crumbs = event["breadcrumbs"].get("values") or []
            for crumb in crumbs:
                if isinstance(crumb, dict) and "data" in crumb:
                    crumb["data"] = _scrub_recursive(crumb["data"])
    except Exception as exc:  # noqa: BLE001
        # Si el scrubbing falla, preferimos dropear el evento a mandar PII.
        logger.warning("[observability] scrubbing fallo, descartando evento: %s", exc)
        return None

    return event


def set_tenant_context(
    tenant: Optional[str] = None,
    api_client_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_role: Optional[str] = None,
) -> None:
    """Setea tags/context multi-tenant en el scope actual de Sentry.

    Llamar desde middlewares o dependencias FastAPI que ya autenticaron
    el request. Si Sentry no esta inicializado, es no-op silencioso.

    Ejemplo:
        @app.middleware("http")
        async def tenant_tag_middleware(request, call_next):
            tenant = resolve_tenant_from_request(request)
            set_tenant_context(tenant=tenant)
            return await call_next(request)
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        scope = sentry_sdk.get_current_scope()
        if tenant:
            scope.set_tag("tenant", tenant)
        if api_client_id:
            scope.set_tag("api_client_id", api_client_id)
        if user_id:
            scope.set_user({"id": user_id, "role": user_role or "unknown"})
    except Exception:  # noqa: BLE001
        # Nunca romper el request por un fallo de tagging.
        pass


def init_sentry(
    dsn: str,
    environment: str = "production",
    traces_sample_rate: float = 0.0,
    release: Optional[str] = None,
) -> bool:
    """Inicializa Sentry si DSN está configurada. Devuelve True si OK.

    Llamar UNA vez al arranque (desde main.py antes de crear el FastAPI app).
    Si dsn está vacío, no hace nada (devuelve False).
    """
    if not dsn or not dsn.strip():
        logger.info("[observability] Sentry deshabilitado (sin DSN configurada)")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning(
            "[observability] sentry-sdk no instalada. "
            "Si quieres error tracking, agrega 'sentry-sdk[fastapi]' a requirements.txt"
        )
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            # 0.0 = solo errores, sin performance traces (más barato)
            traces_sample_rate=traces_sample_rate,
            # Captura errores no-handled + WARNING-level logs como breadcrumbs
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                StarletteIntegration(transaction_style="endpoint"),
                LoggingIntegration(
                    level=logging.INFO,        # breadcrumbs: INFO+
                    event_level=logging.ERROR, # eventos a Sentry: ERROR+
                ),
            ],
            before_send=_before_send,
            send_default_pii=False,  # NUNCA enviar PII por default (Ley 29733 PE)
        )
        logger.info(
            "[observability] Sentry inicializado (env=%s, release=%s, sample_rate=%.2f)",
            environment, release or "n/a", traces_sample_rate,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[observability] init_sentry falló: %s", exc, exc_info=True)
        return False

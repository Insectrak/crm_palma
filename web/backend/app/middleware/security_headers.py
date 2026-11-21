"""
Middleware de security headers HTTP.

Aplica un conjunto conservador de headers OWASP recomendados a todas las
respuestas. Pensado para una SPA + API en el mismo origen detrás de HTTPS
(EasyPanel).

Headers aplicados:
- Strict-Transport-Security  → fuerza HTTPS por 1 año en navegadores
- X-Content-Type-Options     → bloquea MIME sniffing
- X-Frame-Options            → previene clickjacking (deny iframes)
- Referrer-Policy            → no filtrar URLs internas a sitios externos
- Permissions-Policy         → desactiva APIs sensibles del navegador
- Content-Security-Policy    → mitiga XSS limitando orígenes de scripts/fetch
- Cross-Origin-Opener-Policy → aísla browsing context
- X-XSS-Protection           → legacy header (algunos navegadores antiguos)

La CSP es deliberadamente permisiva con `'unsafe-inline'` para estilos
porque Tailwind 4 inyecta CSS en runtime, y para scripts porque Vite emite
módulos con hashes que cambian en cada build. Se puede endurecer en una
fase 2 con nonces si hace falta.

V070.99 — CSP dinamica con whitelist de Sentry/GlitchTip:
  - Si VITE_SENTRY_DSN apunta a glitchtip.crm.local, agregamos ese
    host a connect-src para que el SDK frontend pueda enviar eventos.
  - worker-src incluye blob: porque Sentry Replay crea Web Workers en
    blobs para grabar la sesion en background sin bloquear el UI.
"""
import os
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


_PERMISSIONS = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)


def _extract_sentry_host() -> str:
    """Devuelve 'https://host' del DSN Sentry/GlitchTip frontend si esta
    configurado. Vacio si no hay DSN. Usado para whitelisting en CSP."""
    dsn = os.environ.get("VITE_SENTRY_DSN", "").strip()
    if not dsn:
        return ""
    try:
        parsed = urlparse(dsn)
        if parsed.scheme and parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _build_csp() -> str:
    """Construye CSP dinamica. Whitelist GlitchTip/Sentry si esta configurado."""
    sentry_host = _extract_sentry_host()
    # connect-src: agregar Sentry para que el SDK envie eventos via fetch.
    connect = "'self'"
    if sentry_host:
        connect += f" {sentry_host}"
    # worker-src: Sentry Replay crea Web Workers en blobs para grabacion async.
    # Si no se especifica worker-src, los navegadores caen a script-src — por
    # eso lo declaramos explicitamente y permitimos blob: solo para workers.
    return (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; "
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        f"connect-src {connect} https://cloudflareinsights.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'"
    )


# Cache de la CSP al import time. Si las env vars cambian en runtime, el
# valor queda con el snapshot del arranque del proceso (igual que Sentry).
_CSP = _build_csp()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inyecta headers de seguridad en cada respuesta HTTP."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers

        # No sobrescribir si ya vienen seteados (p.ej. desde un proxy)
        headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", _PERMISSIONS)
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("X-XSS-Protection", "0")  # OWASP recomienda 0 hoy
        headers.setdefault("Content-Security-Policy", _CSP)

        return response

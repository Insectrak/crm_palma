"""Middleware de API versioning.

V070.73 (Bundle API Versioning — ADR-0009).

Inyecta el header `X-Api-Version` en TODAS las respuestas HTTP que matcheen
un prefix `/api/*` o `/auth/*`. Esto permite a los consumers loguear y
detectar drift de version.

Convencion (ver `docs/API_VERSIONING.md`):

- `/api/v1/*`, `/api/v2/*` ... → `X-Api-Version: v1`, `v2`, ...
- `/api/*` (sin prefix de version) → `X-Api-Version: v0-stable`
- `/auth/*` → `X-Api-Version: v0-stable` (auth es legacy compatible)
- otros paths (raiz, /docs, /metrics, archivos estaticos) → no se toca

Cuando se introduzca deprecation de una version, este middleware
tambien puede inyectar `Deprecation: true` + `Sunset: <date>` segun
config (no implementado hoy — agregar cuando se haga el primer sunset).
"""
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Match /api/v1/, /api/v2/, ... (capturando el numero de version).
_VERSION_RE = re.compile(r"^/api/(v\d+)/")


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """Inyecta `X-Api-Version` en respuestas de la API."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path

        # Match explicito de version: /api/v1/, /api/v2/, ...
        match = _VERSION_RE.match(path)
        if match:
            response.headers.setdefault("X-Api-Version", match.group(1))
        elif path.startswith("/api/") or path.startswith("/auth/"):
            # API legacy sin prefix de version explicito = v0-stable.
            response.headers.setdefault("X-Api-Version", "v0-stable")
        # Otros paths (raiz, /docs, /openapi.json, /metrics, estaticos)
        # NO llevan el header — no son parte del contrato API publico.

        return response

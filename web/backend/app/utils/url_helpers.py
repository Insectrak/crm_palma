"""
url_helpers.py — utilidades para construir URLs públicas del CRM.

Centraliza la resolución del "base URL público" — el dominio canónico
que el cliente final ve cuando le llegan emails, links de invitación,
URL en docs de integración, etc. NO confundir con el host interno del
container (ej. `http://crm-backend:8002`) que devuelve
`request.base_url` cuando hay un proxy delante (EasyPanel/traefik).
"""
from __future__ import annotations

from fastapi import Request

from app.config import settings


def resolve_public_base_url(request: Request) -> str:
    """Devuelve el base URL público del CRM (sin trailing slash).

    Orden de precedencia:
      1) `settings.public_base_url` — el admin lo setea explícito con el
         dominio canónico del cliente (ej. https://crm.local).
         Es la fuente más confiable.
      2) Headers `X-Forwarded-Host` + `X-Forwarded-Proto` (proxies modernos
         como traefik los pasan; EasyPanel los pasa cuando está configurado
         correctamente).
      3) Primer origin no-localhost de `settings.allowed_origins` (CORS).
         Heurística razonable: si el dominio del CRM puede hacer requests
         CORS al backend, es porque ese dominio es el frontend público.
      4) `request.base_url` — último recurso. Detrás de un proxy puede
         devolver el host interno del container (inútil para URLs que
         viajan fuera del CRM).
    """
    # 1
    pub = (settings.public_base_url or "").strip().rstrip("/")
    if pub:
        return pub

    # 2
    fwd_host = (request.headers.get("x-forwarded-host") or "").strip()
    fwd_proto = (request.headers.get("x-forwarded-proto") or "https").strip()
    if fwd_host:
        fwd_host = fwd_host.split(",")[0].strip()
        return f"{fwd_proto}://{fwd_host}".rstrip("/")

    # 3
    for origin in (settings.allowed_origins or "").split(","):
        o = origin.strip().rstrip("/")
        if o and "localhost" not in o and "127.0.0.1" not in o:
            return o

    # 4
    return str(request.base_url).rstrip("/")

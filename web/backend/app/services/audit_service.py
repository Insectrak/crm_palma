"""
Servicio de auditoria para acciones sobre leads.

Responsabilidad:
  - Extraer metadata de la request (IP, user-agent) y delegar al repo.
  - Exponer funciones de alto nivel que los routers invocan en una linea
    sin pensar en como se persisten los datos.

Todos los metodos son fail-safe: si la escritura al audit log falla, NO se
propaga la excepcion al caller. El audit es una capa secundaria, nunca
debe romper una request legitima de un usuario.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Request

from app.auth.schemas import TokenData
from app.repositories import audit_repository


def _client_ip(request: Optional[Request]) -> Optional[str]:
    """Devuelve la IP real del cliente, respetando X-Forwarded-For si existe.

    En produccion el backend corre detras de Traefik/Easypanel, por lo que
    `request.client.host` seria la IP del proxy (util=cero). Preferimos el
    primer valor de X-Forwarded-For que es la IP real del usuario.
    """
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # Formato: "cliente, proxy1, proxy2" — nos quedamos con el primero.
        return xff.split(",")[0].strip()
    try:
        return request.client.host if request.client else None
    except Exception:
        return None


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    ua = request.headers.get("user-agent")
    # Truncar a 500 chars por si algun bot manda algo absurdamente largo.
    return ua[:500] if ua else None


# ---------------------------------------------------------------------------
# Funciones de alto nivel que usa el router
# ---------------------------------------------------------------------------


def record_list(
    *,
    user: TokenData,
    lead_count: int,
    filters: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    audit_repository.log_list(
        user_id=user.user_id,
        lead_count=lead_count,
        filters=filters,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )


def record_export(
    *,
    user: TokenData,
    lead_count: int,
    filters: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    audit_repository.log_export(
        user_id=user.user_id,
        lead_count=lead_count,
        filters=filters,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )


def record_detail(
    *,
    user: TokenData,
    lead_id: int,
    request: Optional[Request] = None,
) -> None:
    audit_repository.log_detail(
        user_id=user.user_id,
        lead_id=lead_id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )


def record_copy_attempt(
    *,
    user: TokenData,
    page: str,
    action_type: str,
    request: Optional[Request] = None,
) -> None:
    audit_repository.log_copy_attempt(
        user_id=user.user_id,
        page=page,
        action_type=action_type,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )

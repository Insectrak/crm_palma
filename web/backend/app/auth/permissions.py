"""
permissions.py — FastAPI dependency `check_permission(key)` (ADR-0011).

Patrón inspirado en producto hermano DoctorMuelita:
- Si el JWT trae `permissions._all == true` → bypass (rol admin/all).
- Si el JWT no trae `permissions` (token legacy pre-V078) → fallback al
  check por rol legacy: admin/supervisor/asesor con `Role.ADMIN` siempre
  pasa (mismo comportamiento de require_admin actual).
- Si trae `permissions` con la key concreta → permite si true, rechaza
  con 403 si false/missing.

Convención de keys: `resource.action` (flat, sin nested).
  Ejemplos: `leads.view`, `reportes.export`, `asignacion.manage`.

Uso en routers:
    @router.get("/reportes")
    def listar_reportes(user = Depends(check_permission("reportes.view"))):
        ...

Coexistencia con sistema legacy:
- Los routers actuales siguen usando `require_admin` / `require_supervisor_or_admin`.
- La migración a `check_permission` es progresiva (Strangler Pattern).
- Mientras tanto, ambos sistemas conviven sin breaking changes.
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status

from app.auth.jwt import get_current_user
from app.auth.schemas import TokenData
from app.constants import Role

logger = logging.getLogger(__name__)


def check_permission(permission_key: str, *legacy_roles: str):
    """Factory de FastAPI dependency. Exige que el usuario tenga el
    permiso `permission_key` (o sea admin/bypass o uno de los `legacy_roles`).

    Args:
        permission_key: Clave en formato 'resource.action' (ej. 'leads.view').
        *legacy_roles: Roles legacy adicionales que pasan sin necesitar el permiso
            granular. Sirve para endpoints compartidos entre admin (gestion via
            permiso) y supervisor (operacion historica por rol). Ej.
            `check_permission("usuarios.manage", "supervisor")` deja pasar al
            supervisor legacy sin que tenga `usuarios.manage` en su rol.

    Returns:
        Una funcion dependency apta para Depends(...).
    """
    def _check(current_user: TokenData = Depends(get_current_user)) -> TokenData:
        # 1. Fast path: rol legacy admin pasa siempre (compat con sistema actual).
        if current_user.role == Role.ADMIN.value:
            return current_user

        # 2. Roles legacy adicionales explicitos (ej. supervisor en endpoints
        #    compartidos como /users que admin maneja y supervisor consume).
        if legacy_roles and current_user.role in legacy_roles:
            return current_user

        perms = current_user.permissions or {}

        # 3. Flag `_all` en permissions → bypass total (rol custom con todos los permisos).
        if perms.get("_all") is True:
            return current_user

        # 4. Lookup directo de la key en el dict.
        if perms.get(permission_key) is True:
            return current_user

        # 4b. Chequear si alguno de los legacy_roles pasados es una permission key activa en perms
        if legacy_roles:
            for alt in legacy_roles:
                if perms.get(alt) is True:
                    return current_user

        # 5. Sin permiso → 403 con mensaje accionable.
        logger.info(
            "permission denied: user=%s role=%s key=%s",
            current_user.user_id, current_user.role, permission_key,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sin permiso '{permission_key}'",
        )

    return _check


def get_assignment_scope(user: TokenData) -> tuple[str, list[str]]:
    """Retorna (scope, allowed_user_ids) para asignación de leads.
    scope: 'global' | 'equipo' | 'personalizado' | 'none'
    allowed_user_ids: lista de UUID strings si scope == 'personalizado'
    """
    if not user:
        return "none", []
    if user.role in (Role.ADMIN.value, "admin"):
        return "global", []
    perms = user.permissions or {}
    if perms.get("_all") is True:
        return "global", []
    if not perms.get("asignacion.manage") and user.role not in (Role.SUPERVISOR.value, "supervisor"):
        return "none", []

    scope = perms.get("asignacion.scope")
    if not scope or scope not in ("global", "equipo", "personalizado"):
        scope = "equipo"

    allowed = perms.get("asignacion.allowed_users") or []
    if isinstance(allowed, list):
        allowed = [str(x) for x in allowed if x]
    else:
        allowed = []
    return scope, allowed


def has_permission(user: TokenData, permission_key: str) -> bool:
    """Helper síncrono para chequeos inline (NO es FastAPI dep).

    Útil cuando un endpoint expone una operación condicional según el
    permiso (ej. mostrar/ocultar un botón en la respuesta).
    """
    if user.role == Role.ADMIN.value:
        return True
    perms = user.permissions or {}
    if perms.get("_all") is True:
        return True
    return perms.get(permission_key) is True


def can_view_all_data(user: TokenData, scope: str = "leads") -> bool:
    """Retorna True si el usuario tiene visibilidad global de datos (ve todos los registros).

    Reglas de evaluación:
      1. Rol admin legacy -> True (ve todo siempre).
      2. Flag `_all` en permissions -> True.
      3. `data.view_all` en permissions -> True (master switch global).
      4. `{scope}.view_all` en permissions -> True (switch específico: leads, dashboards, reportes, agenda, chat).
      5. En cualquier otro caso -> False (el usuario solo verá sus propios datos asignados/equipo).
    """
    if not user:
        return False
    if user.role == Role.ADMIN.value or user.role == "admin":
        return True
    perms = user.permissions or {}
    if perms.get("_all") is True:
        return True
    if perms.get("data.view_all") is True:
        return True
    if perms.get(f"{scope}.view_all") is True:
        return True
    return False

"""
permission_audit_service.py — registra cambios sobre permisos y roles
(ADR-0011 Sprint 4, Ley 29733 PE).

Las funciones son fail-safe: si la escritura del audit falla NO propaga
la excepcion al caller. El audit es secundario, nunca debe romper una
operacion legitima del admin.

Acciones cubiertas:
- record_role_create
- record_role_update_perms (con diff before/after)
- record_role_update_meta (nombre/descripcion)
- record_role_delete
- record_user_role_change (admin asigna rol a usuario)

Lectura:
- list_recent(limit, offset, filtros) -> entradas del audit log + count
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import Request
from psycopg2.extras import Json, RealDictCursor

from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────

def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    try:
        return request.client.host if request.client else None
    except Exception:
        return None


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    ua = request.headers.get("user-agent")
    return ua[:500] if ua else None


def _insert(
    *,
    actor: TokenData,
    action: str,
    target_kind: str,
    target_id: str,
    target_label: Optional[str],
    before: Optional[dict],
    after: Optional[dict],
    request: Optional[Request],
) -> None:
    """Inserta una fila en auth.permission_audit_log. Fail-safe: cualquier
    error se logguea y se silencia (NO se propaga al caller)."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.permission_audit_log (
                        actor_user_id, actor_email, actor_role,
                        action, target_kind, target_id, target_label,
                        before_state, after_state,
                        ip_address, user_agent
                    ) VALUES (
                        %s::uuid, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s
                    )
                    """,
                    (
                        actor.user_id, actor.email, actor.role,
                        action, target_kind, target_id, target_label,
                        Json(before) if before is not None else None,
                        Json(after) if after is not None else None,
                        _client_ip(request), _user_agent(request),
                    ),
                )
    except Exception as exc:
        logger.warning(
            "permission_audit: insert fallo (silenciado) action=%s target=%s err=%s",
            action, target_id, exc,
        )


# ── Recorders por accion ──────────────────────────────────────────────────

def record_role_create(
    *,
    actor: TokenData,
    role: dict,
    request: Optional[Request] = None,
) -> None:
    _insert(
        actor=actor,
        action="role.create",
        target_kind="role",
        target_id=str(role["id"]),
        target_label=role.get("name"),
        before=None,
        after={
            "name": role.get("name"),
            "description": role.get("description"),
            "permissions": role.get("permissions") or {},
            "is_external": bool(role.get("is_external")),
        },
        request=request,
    )


def record_role_update_perms(
    *,
    actor: TokenData,
    role_id: int,
    role_name: str,
    before_perms: dict,
    after_perms: dict,
    request: Optional[Request] = None,
) -> None:
    """Solo registra si hubo cambio real en el dict de permisos."""
    if (before_perms or {}) == (after_perms or {}):
        return
    _insert(
        actor=actor,
        action="role.update_perms",
        target_kind="role",
        target_id=str(role_id),
        target_label=role_name,
        before={"permissions": before_perms or {}},
        after={"permissions": after_perms or {}},
        request=request,
    )


def record_role_update_meta(
    *,
    actor: TokenData,
    role_id: int,
    role_name: str,
    before: dict,
    after: dict,
    request: Optional[Request] = None,
) -> None:
    if before == after:
        return
    _insert(
        actor=actor,
        action="role.update_meta",
        target_kind="role",
        target_id=str(role_id),
        target_label=role_name,
        before=before,
        after=after,
        request=request,
    )


def record_role_delete(
    *,
    actor: TokenData,
    role_id: int,
    role_name: str,
    users_affected: int,
    request: Optional[Request] = None,
) -> None:
    _insert(
        actor=actor,
        action="role.delete",
        target_kind="role",
        target_id=str(role_id),
        target_label=role_name,
        before={"name": role_name},
        after={"users_affected": users_affected},
        request=request,
    )


def record_user_role_change(
    *,
    actor: TokenData,
    target_user_id: str,
    target_user_email: Optional[str],
    before_role_id: Optional[int],
    before_role_name: Optional[str],
    after_role_id: Optional[int],
    after_role_name: Optional[str],
    request: Optional[Request] = None,
) -> None:
    # Skip si nada cambio. Soporta los dos casos:
    #  a) cambio de role_id custom (rolees del catalogo auth.roles)
    #  b) cambio de role legacy text (admin/supervisor/asesor) cuando role_id
    #     viene None en ambos lados — comparamos por role_name entonces.
    if before_role_id == after_role_id and (before_role_name or "") == (after_role_name or ""):
        return
    _insert(
        actor=actor,
        action="user.role_change",
        target_kind="user",
        target_id=target_user_id,
        target_label=target_user_email,
        before={"role_id": before_role_id, "role_name": before_role_name},
        after={"role_id": after_role_id, "role_name": after_role_name},
        request=request,
    )


def record_user_active_change(
    *,
    actor: TokenData,
    target_user_id: str,
    target_user_email: Optional[str],
    before_active: bool,
    after_active: bool,
    request: Optional[Request] = None,
) -> None:
    """V088 — Registra deshabilitar / re-habilitar de un usuario.

    Cumplimiento Ley 29733 PE: la deshabilitación bloquea acceso a datos
    personales por parte del usuario afectado y por tanto califica como
    cambio de privilegios que merece traza.
    """
    if bool(before_active) == bool(after_active):
        return
    action = "user.activate" if after_active else "user.deactivate"
    _insert(
        actor=actor,
        action=action,
        target_kind="user",
        target_id=target_user_id,
        target_label=target_user_email,
        before={"is_active": bool(before_active)},
        after={"is_active": bool(after_active)},
        request=request,
    )


def record_user_login_blocked_change(
    *,
    actor: TokenData,
    target_user_id: str,
    target_user_email: Optional[str],
    before_blocked: bool,
    after_blocked: bool,
    request: Optional[Request] = None,
) -> None:
    """V094 — Registra bloqueo / desbloqueo del login de un usuario.

    Distinto de is_active: el usuario sigue visible en listas operacionales,
    solo se le impide entrar al CRM. Cumplimiento Ley 29733 PE igual que
    el activate/deactivate — merece traza porque corta acceso a datos.
    """
    if bool(before_blocked) == bool(after_blocked):
        return
    action = "user.login_block" if after_blocked else "user.login_unblock"
    _insert(
        actor=actor,
        action=action,
        target_kind="user",
        target_id=target_user_id,
        target_label=target_user_email,
        before={"login_blocked": bool(before_blocked)},
        after={"login_blocked": bool(after_blocked)},
        request=request,
    )


# ── Lectura ───────────────────────────────────────────────────────────────

def list_recent(
    *,
    limit: int = 50,
    offset: int = 0,
    actor_user_id: Optional[str] = None,
    target_kind: Optional[str] = None,
    target_id: Optional[str] = None,
    action: Optional[str] = None,
) -> dict[str, Any]:
    """Lista entradas del audit log filtradas. Devuelve {items, total}."""
    where = ["TRUE"]
    params: list = []
    if actor_user_id:
        where.append("actor_user_id = %s::uuid")
        params.append(actor_user_id)
    if target_kind:
        where.append("target_kind = %s")
        params.append(target_kind)
    if target_id:
        where.append("target_id = %s")
        params.append(target_id)
    if action:
        where.append("action = %s")
        params.append(action)
    where_sql = " AND ".join(where)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM auth.permission_audit_log WHERE {where_sql}",
                params,
            )
            total = cur.fetchone()["n"]
            cur.execute(
                f"""
                SELECT id, actor_user_id::text AS actor_user_id, actor_email, actor_role,
                       action, target_kind, target_id, target_label,
                       before_state, after_state,
                       ip_address, user_agent,
                       created_at
                  FROM auth.permission_audit_log
                 WHERE {where_sql}
                 ORDER BY created_at DESC
                 LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            items = cur.fetchall()
    for it in items:
        # Forzar JSON-serializable y timestamps ISO.
        if it.get("created_at") is not None:
            it["created_at"] = it["created_at"].isoformat()
    return {"items": items, "total": total}

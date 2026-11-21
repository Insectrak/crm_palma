"""
roles.py — endpoints CRUD del sistema de roles (ADR-0011).

Solo admin puede gestionar roles. Sprint 1 entrega:
  GET    /api/roles                  — lista roles + count usuarios
  POST   /api/roles                  — crea rol custom
  PATCH  /api/roles/{id}/permissions — actualiza JSONB permissions
  PATCH  /api/roles/{id}             — actualiza description / is_external
  DELETE /api/roles/{id}             — borra rol custom (rechaza built-in y en uso)
  PATCH  /api/roles/users/{user_id}  — asigna role_id a un usuario

Sprint 2 va a agregar check_permission factory; este router sigue
usando require_admin porque la gestión de roles es siempre admin.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.database import get_db
from app.services import permission_audit_service as audit
from app.services import roles_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/roles", tags=["Roles"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: Optional[str] = None
    permissions: dict = Field(default_factory=dict)
    is_external: bool = False


class RolePermissionsUpdate(BaseModel):
    permissions: dict


class RoleMetadataUpdate(BaseModel):
    description: Optional[str] = None
    is_external: Optional[bool] = None


class UserRoleAssign(BaseModel):
    role_id: Optional[int] = None  # None desvincula el rol custom


def _serialize(role: dict) -> dict:
    """Normaliza datetimes y campos para la respuesta JSON."""
    if not role:
        return role
    out = dict(role)
    for k in ("created_at", "updated_at"):
        if out.get(k):
            out[k] = out[k].isoformat()
    return out


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
def list_roles(_: TokenData = Depends(check_permission("roles.manage"))):
    """Lista todos los roles con count de usuarios asignados."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            rows = roles_service.list_roles_with_counts(cur)
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
def create_role(
    payload: RoleCreate,
    request: Request,
    actor: TokenData = Depends(check_permission("roles.manage")),
):
    """Crea un rol custom. Built-in son seed; el admin no los crea por API."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                role = roles_service.create_role(
                    cur,
                    name=payload.name,
                    description=payload.description,
                    permissions=payload.permissions,
                    is_external=payload.is_external,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        conn.commit()
    logger.info("Rol creado: id=%s name=%s", role["id"], role["name"])
    audit.record_role_create(actor=actor, role=role, request=request)
    return _serialize(role)


@router.patch("/{role_id}/permissions")
def update_permissions(
    role_id: int,
    payload: RolePermissionsUpdate,
    request: Request,
    actor: TokenData = Depends(check_permission("roles.manage")),
):
    """Actualiza el dict completo de permisos del rol. Sobrescribe el JSONB.

    V5.73.4 — Anti-self-harm: si el actor esta editando su propio rol y
    el payload lo deja sin `roles.manage`, rechazamos con 400. Sin esto,
    un admin que editaba su propio rol y por error desmarcaba 'Gestionar
    roles' quedaba atrapado: el siguiente request a /api/roles devolvia
    403, el handler del frontend lo interpretaba como sesion muerta y
    disparaba logout. Sintoma reportado: "cambie permisos en la app y se
    salio de la app y me mando a otra app".
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Snapshot del estado anterior para el audit.
            before = roles_service.get_role_by_id(cur, role_id)
            if not before:
                raise HTTPException(404, "Rol no encontrado.")

            # V5.73.4 — Anti-self-harm. Solo aplica si el actor tiene
            # role_id explicito Y coincide con el role_id que esta editando.
            # admin legacy (sin role_id, role='admin' string) NO entra aca
            # porque su bypass es por columna u.role, no por role_id.
            actor_role_id = getattr(actor, "role_id", None)
            if actor_role_id is not None and actor_role_id == role_id:
                perms_new = payload.permissions or {}
                has_all = perms_new.get("_all") is True
                has_manage = perms_new.get("roles.manage") is True
                if not has_all and not has_manage:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "No puedes quitarte el permiso 'Gestionar roles' a "
                            "ti mismo. Pide a otro administrador que haga el "
                            "cambio o mantén ese permiso activo."
                        ),
                    )

            role = roles_service.update_role_permissions(cur, role_id, payload.permissions)
        conn.commit()
    logger.info("Permisos actualizados rol=%s", role_id)
    audit.record_role_update_perms(
        actor=actor,
        role_id=role_id,
        role_name=role["name"],
        before_perms=before.get("permissions") or {},
        after_perms=role.get("permissions") or {},
        request=request,
    )
    return _serialize(role)


@router.patch("/{role_id}")
def update_metadata(
    role_id: int,
    payload: RoleMetadataUpdate,
    request: Request,
    actor: TokenData = Depends(check_permission("roles.manage")),
):
    """Actualiza description / is_external. NO permite renombrar (cambia identidad)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            before = roles_service.get_role_by_id(cur, role_id)
            if not before:
                raise HTTPException(404, "Rol no encontrado.")
            role = roles_service.update_role_metadata(
                cur,
                role_id,
                description=payload.description,
                is_external=payload.is_external,
            )
        conn.commit()
    audit.record_role_update_meta(
        actor=actor,
        role_id=role_id,
        role_name=role["name"],
        before={
            "description": before.get("description"),
            "is_external": bool(before.get("is_external")),
        },
        after={
            "description": role.get("description"),
            "is_external": bool(role.get("is_external")),
        },
        request=request,
    )
    return _serialize(role)


@router.delete("/{role_id}", status_code=200)
def delete_role(
    role_id: int,
    request: Request,
    actor: TokenData = Depends(check_permission("roles.manage")),
):
    """Borra un rol custom.

    ADR-0011 — Patron patrón estándar: el delete es transparente. Si el rol
    tiene usuarios asignados, el FK ON DELETE SET NULL los desvincula
    automaticamente (vuelven al rol legacy con permisos de asesor).
    Devolvemos `users_affected` para que el frontend muestre un mensaje
    claro tras el delete.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Snapshot del rol antes de borrar (para el audit).
            before = roles_service.get_role_by_id(cur, role_id)
            result, affected = roles_service.delete_role(cur, role_id)
        if result == "ok":
            conn.commit()
    if result == "not_found":
        raise HTTPException(404, "Rol no encontrado.")
    if result == "builtin":
        raise HTTPException(403, "No se puede borrar un rol built-in (admin/supervisor/asesor).")
    logger.info("Rol borrado: id=%s usuarios_afectados=%s", role_id, affected)
    if before:
        audit.record_role_delete(
            actor=actor,
            role_id=role_id,
            role_name=before.get("name") or f"role#{role_id}",
            users_affected=affected,
            request=request,
        )
    return {"ok": True, "id": role_id, "users_affected": affected}


@router.patch("/users/{user_id}")
def assign_to_user(
    user_id: str,
    payload: UserRoleAssign,
    request: Request,
    actor: TokenData = Depends(check_permission("roles.manage")),
):
    """Asigna un role_id custom al usuario. role_id=null desvincula
    (vuelve a comportamiento basado en role text legacy)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Capturar estado previo (rol viejo + email del usuario) para el audit.
            cur.execute(
                """
                SELECT u.email, u.role_id, r.name AS role_name
                  FROM auth.users u
                  LEFT JOIN auth.roles r ON r.id = u.role_id
                 WHERE u.id = %s::uuid
                """,
                (user_id,),
            )
            prev = cur.fetchone()
            try:
                ok = roles_service.assign_role_to_user(cur, user_id, payload.role_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if not ok:
                raise HTTPException(404, "Usuario no encontrado.")
            # Resolver nombre del rol nuevo (si payload.role_id != None).
            after_role_name = None
            if payload.role_id is not None:
                new_role = roles_service.get_role_by_id(cur, payload.role_id)
                if new_role:
                    after_role_name = new_role["name"]
        conn.commit()
    logger.info("Rol asignado: user=%s role_id=%s", user_id, payload.role_id)
    if prev:
        audit.record_user_role_change(
            actor=actor,
            target_user_id=user_id,
            target_user_email=prev.get("email"),
            before_role_id=prev.get("role_id"),
            before_role_name=prev.get("role_name"),
            after_role_id=payload.role_id,
            after_role_name=after_role_name,
            request=request,
        )
    return {"ok": True, "user_id": user_id, "role_id": payload.role_id}

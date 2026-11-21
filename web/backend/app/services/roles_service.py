"""
roles_service.py — sistema de roles + permisos granulares (ADR-0011).

Patrón inspirado en producto hermano DoctorMuelita:
- Tabla auth.roles con permissions JSONB flat ({"leads.view": true, ...})
- Roles built-in (admin/supervisor/asesor) no se pueden borrar
- Roles custom configurables desde la UI

Solo lookups + CRUD. La autorización vive en app.auth.permissions (Sprint 2).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


# ─── Lookups ───────────────────────────────────────────────────────────────

def get_role_by_id(cur, role_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT id, name, description, permissions, is_external, is_builtin,
               created_at, updated_at
          FROM auth.roles
         WHERE id = %s
        """,
        (role_id,),
    )
    return cur.fetchone()


def get_role_by_name(cur, name: str) -> Optional[dict]:
    cur.execute(
        """
        SELECT id, name, description, permissions, is_external, is_builtin
          FROM auth.roles
         WHERE name = %s
        """,
        (name,),
    )
    return cur.fetchone()


def list_roles_with_counts(cur) -> list[dict]:
    """Lista todos los roles + count de usuarios asignados a cada uno."""
    cur.execute(
        """
        SELECT r.id, r.name, r.description, r.permissions, r.is_external,
               r.is_builtin, r.created_at, r.updated_at,
               COUNT(u.id) AS user_count
          FROM auth.roles r
     LEFT JOIN auth.users u
            ON u.role_id = r.id AND u.is_active = TRUE
      GROUP BY r.id
      ORDER BY r.is_builtin DESC, r.name ASC
        """
    )
    return cur.fetchall()


def get_permissions_for_user(cur, user_id: str) -> dict:
    """Devuelve el dict de permisos efectivos del usuario (snapshot del rol
    al que está vinculado). Si el usuario no tiene role_id, devuelve {}.

    Para meter en el JWT al login."""
    cur.execute(
        """
        SELECT r.permissions, r.name, r.is_external
          FROM auth.users u
          JOIN auth.roles r ON r.id = u.role_id
         WHERE u.id = %s::uuid
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return {}
    return row.get("permissions") or {}


# ─── CRUD ──────────────────────────────────────────────────────────────────

def create_role(
    cur,
    *,
    name: str,
    description: Optional[str],
    permissions: dict,
    is_external: bool = False,
) -> dict:
    """Crea un rol custom. Lanza ValueError si el nombre ya existe."""
    name_norm = (name or "").strip()
    if not name_norm:
        raise ValueError("El nombre del rol es requerido.")
    if get_role_by_name(cur, name_norm):
        raise ValueError(f"Ya existe un rol con nombre '{name_norm}'.")
    cur.execute(
        """
        INSERT INTO auth.roles (name, description, permissions, is_external, is_builtin)
        VALUES (%s, %s, %s::jsonb, %s, FALSE)
        RETURNING id, name, description, permissions, is_external, is_builtin,
                  created_at, updated_at
        """,
        (name_norm, description, json.dumps(permissions or {}), is_external),
    )
    return cur.fetchone()


def update_role_permissions(cur, role_id: int, permissions: dict) -> Optional[dict]:
    """Actualiza solo el dict de permisos del rol. Devuelve el rol actualizado
    o None si no existe."""
    cur.execute(
        """
        UPDATE auth.roles
           SET permissions = %s::jsonb
         WHERE id = %s
        RETURNING id, name, description, permissions, is_external, is_builtin,
                  created_at, updated_at
        """,
        (json.dumps(permissions or {}), role_id),
    )
    return cur.fetchone()


def update_role_metadata(
    cur,
    role_id: int,
    *,
    description: Optional[str] = None,
    is_external: Optional[bool] = None,
) -> Optional[dict]:
    """Actualiza description / is_external del rol. Nombre y is_builtin NO
    se modifican por API (nombre cambia identidad, is_builtin protege seed)."""
    sets, params = [], []
    if description is not None:
        sets.append("description = %s")
        params.append(description)
    if is_external is not None:
        sets.append("is_external = %s")
        params.append(is_external)
    if not sets:
        return get_role_by_id(cur, role_id)
    params.append(role_id)
    cur.execute(
        f"""
        UPDATE auth.roles
           SET {", ".join(sets)}
         WHERE id = %s
        RETURNING id, name, description, permissions, is_external, is_builtin,
                  created_at, updated_at
        """,
        params,
    )
    return cur.fetchone()


def delete_role(cur, role_id: int) -> tuple[str, int]:
    """Borra un rol custom. Devuelve (codigo, usuarios_afectados):
       - ('ok', n)        → borrado, n usuarios quedaron con role_id=NULL
                            (mantienen role text legacy, vuelven a permisos
                            del rol base).
       - ('not_found', 0) → no existe.
       - ('builtin', 0)   → no se puede borrar (built-in).

    Patron patrón estándar: el delete de un rol custom es transparente — los
    usuarios afectados pierden los permisos custom y vuelven al
    comportamiento del rol legacy (asesor por default). Esto evita el
    flujo roto "tengo que reasignar 50 usuarios antes de poder limpiar
    este rol". El FK auth.users.role_id tiene ON DELETE SET NULL desde
    V078, asi que el cleanup es automatico a nivel DB.
    """
    role = get_role_by_id(cur, role_id)
    if not role:
        return "not_found", 0
    if role.get("is_builtin"):
        return "builtin", 0
    # Count antes del delete para reportar al frontend cuantos usuarios
    # quedaron desvinculados.
    cur.execute(
        "SELECT COUNT(*) AS n FROM auth.users WHERE role_id = %s AND is_active = TRUE",
        (role_id,),
    )
    affected = cur.fetchone()["n"]
    cur.execute("DELETE FROM auth.roles WHERE id = %s", (role_id,))
    return "ok", affected


def assign_role_to_user(cur, user_id: str, role_id: Optional[int]) -> bool:
    """Asigna un role_id a un usuario. role_id=None desvincula. Devuelve True
    si el usuario existe y se actualizó."""
    if role_id is not None and not get_role_by_id(cur, role_id):
        raise ValueError(f"Rol con id={role_id} no existe.")
    cur.execute(
        "UPDATE auth.users SET role_id = %s WHERE id = %s::uuid",
        (role_id, user_id),
    )
    return cur.rowcount > 0

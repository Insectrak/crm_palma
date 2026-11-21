"""
lead_sharing_service.py — Sharing Rules para roles custom (ADR-0012, Sprint 4).

Las reglas son DECLARATIVAS: el admin define un criterio (fuente, estado,
sede, calidad) y un rol al que se comparten los leads que matcheen ese
criterio. En runtime, cuando un usuario con `role_id` custom abre /leads,
el backend genera el WHERE SQL adicional con las reglas activas para
ese rol y lo une con `OR` al filtro base (los leads que él tenga
asignados).

Resultado: el usuario ve SUS leads + los que matchean las reglas
compartidas. Patrón CRMs profesionales.

Capacidad del filtro JSONB (todas las claves son opcionales):

    {
        "fuente_ids":      [1, 3],         -- WHERE l.fuente_id IN (1, 3)
        "estado_ids":      [2, 5, 7],      -- WHERE l.estado_id IN (...)
        "sede_ids":        ["uuid", ...],  -- WHERE l.sede_id IN (...)
        "api_client_ids":  ["uuid", ...]   -- WHERE l.api_client_id IN (...)
                                              (proveedores que entregaron el lead)
        "incluir_recontactos": true       -- Si true, api_client_ids hace UNION
                                              con leads que tuvieron recontacto de
                                              esos proveedores (V086 pattern).
                                              Default false (backwards-compat).
    }

Reglas:
- Lista vacía ([]) significa "ninguno" → desactiva la regla en runtime
  (evita compartir TODOS los leads por error si el admin borra todas
  las fuentes seleccionadas).
- Clave ausente o null significa "sin restricción en ese campo".
- Si TODAS las claves están ausentes o son listas vacías → la regla no
  comparte nada (defensa contra reglas mal configuradas).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


# ─── Helpers de filtro JSONB → SQL ─────────────────────────────────────────

def _build_rule_sql(filter_dict: dict) -> tuple[Optional[str], list]:
    """Traduce un filter_jsonb a un fragmento SQL parametrizado.

    Devuelve (where_fragment, params) o (None, []) si el filtro no tiene
    ninguna restricción activa (evita generar 'WHERE 1=1' que compartiría
    TODOS los leads — defensa contra config vacía).
    """
    if not filter_dict or not isinstance(filter_dict, dict):
        return None, []

    parts: list[str] = []
    params: list = []

    fuente_ids = filter_dict.get("fuente_ids")
    if isinstance(fuente_ids, list) and len(fuente_ids) > 0:
        placeholders = ",".join(["%s"] * len(fuente_ids))
        parts.append(f"l.fuente_id IN ({placeholders})")
        params.extend(int(x) for x in fuente_ids)

    estado_ids = filter_dict.get("estado_ids")
    if isinstance(estado_ids, list) and len(estado_ids) > 0:
        placeholders = ",".join(["%s"] * len(estado_ids))
        parts.append(f"l.estado_id IN ({placeholders})")
        params.extend(int(x) for x in estado_ids)

    sede_ids = filter_dict.get("sede_ids")
    if isinstance(sede_ids, list) and len(sede_ids) > 0:
        placeholders = ",".join(["%s::uuid"] * len(sede_ids))
        parts.append(f"l.sede_id IN ({placeholders})")
        params.extend(str(x) for x in sede_ids)

    # Proveedor: leads entregados por un api_client_id específico (sistema
    # multi-tenant — ej. Wedo, Meta, TikTok). Util para "Marketing solo ve
    # los leads que entregó Wedo via /api/ingest/leads".
    #
    # Si `incluir_recontactos=true`, además de leads donde el proveedor fue
    # el ORIGEN, incluimos leads donde el proveedor mandó al menos un
    # RECONTACTO (aunque el origen del lead sea otro). Caso de uso reportado
    # 2026-06-17: marketing quiere que un rol vea todos los leads que wedo
    # "tocó" — sea como origen, sea con recontactos sobre leads viejos de
    # otras fuentes. Patrón consistente con el filtro `tocado_por_api_client_id`
    # de V086 en la página de Leads.
    api_client_ids = filter_dict.get("api_client_ids")
    if isinstance(api_client_ids, list) and len(api_client_ids) > 0:
        placeholders = ",".join(["%s::uuid"] * len(api_client_ids))
        incluir_recontactos = bool(filter_dict.get("incluir_recontactos"))
        if incluir_recontactos:
            # UNION lógica: origen O recontacto. Los placeholders se repiten
            # porque se usan dos veces en la misma expresion.
            parts.append(
                f"(l.api_client_id IN ({placeholders}) "
                f"OR EXISTS (SELECT 1 FROM crm.lead_recontactos r "
                f"WHERE r.lead_id = l.id AND r.api_client_id IN ({placeholders})))"
            )
            uuids_str = [str(x) for x in api_client_ids]
            params.extend(uuids_str)  # primero IN(...) del lead
            params.extend(uuids_str)  # luego IN(...) del recontacto
        else:
            parts.append(f"l.api_client_id IN ({placeholders})")
            params.extend(str(x) for x in api_client_ids)

    if not parts:
        return None, []
    # AND interno: una regla con varios campos requiere que el lead matchee TODOS.
    return "(" + " AND ".join(parts) + ")", params


def build_shared_where_for_role(
    cur, role_id: int,
) -> tuple[Optional[str], list]:
    """Devuelve el WHERE adicional para extender el filtro de leads del
    usuario con las reglas activas de su `role_id`.

    Cada regla produce un fragmento `(...)`. Las reglas se unen con `OR`
    porque cada una representa un subset independiente que el rol puede
    ver.

    Si no hay reglas activas, devuelve (None, []).
    """
    cur.execute(
        """
        SELECT id, filter_jsonb
          FROM crm.lead_sharing_rules
         WHERE role_id = %s AND is_active = TRUE
        """,
        (role_id,),
    )
    rules = cur.fetchall()
    if not rules:
        return None, []

    fragments: list[str] = []
    params: list = []
    for r in rules:
        f = r.get("filter_jsonb") if isinstance(r, dict) else r[1]
        # psycopg2 ya devuelve dict para columnas JSONB
        if isinstance(f, str):
            try:
                f = json.loads(f)
            except Exception:  # noqa: BLE001
                f = {}
        frag, frag_params = _build_rule_sql(f or {})
        if frag is None:
            continue
        fragments.append(frag)
        params.extend(frag_params)

    if not fragments:
        return None, []
    return "(" + " OR ".join(fragments) + ")", params


# ─── CRUD ──────────────────────────────────────────────────────────────────

def list_rules(cur) -> list[dict]:
    """Lista todas las reglas con metadata útil para la UI admin."""
    cur.execute(
        """
        SELECT s.id, s.name, s.description, s.role_id, r.name AS role_name,
               s.filter_jsonb, s.can_view, s.can_edit, s.is_active,
               s.created_at, s.updated_at
          FROM crm.lead_sharing_rules s
          JOIN auth.roles r ON r.id = s.role_id
      ORDER BY s.is_active DESC, s.name ASC
        """
    )
    return cur.fetchall()


def get_rule(cur, rule_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT s.id, s.name, s.description, s.role_id, r.name AS role_name,
               s.filter_jsonb, s.can_view, s.can_edit, s.is_active,
               s.created_at, s.updated_at
          FROM crm.lead_sharing_rules s
          JOIN auth.roles r ON r.id = s.role_id
         WHERE s.id = %s
        """,
        (rule_id,),
    )
    return cur.fetchone()


def create_rule(
    cur,
    *,
    name: str,
    description: Optional[str],
    role_id: int,
    filter_jsonb: dict,
    can_view: bool = True,
    can_edit: bool = False,
    is_active: bool = True,
    created_by: Optional[str] = None,
) -> dict:
    name_norm = (name or "").strip()
    if not name_norm:
        raise ValueError("El nombre de la regla es requerido.")
    # Validar que el rol exista
    cur.execute("SELECT id, is_builtin FROM auth.roles WHERE id = %s", (role_id,))
    role = cur.fetchone()
    if not role:
        raise ValueError(f"Rol con id={role_id} no existe.")
    if role.get("is_builtin") if isinstance(role, dict) else role[1]:
        raise ValueError("No se pueden crear sharing rules para roles built-in (admin/supervisor/asesor).")

    cur.execute(
        """
        INSERT INTO crm.lead_sharing_rules
            (name, description, role_id, filter_jsonb, can_view, can_edit, is_active, created_by)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            name_norm,
            description,
            role_id,
            json.dumps(filter_jsonb or {}),
            can_view,
            can_edit,
            is_active,
            created_by,
        ),
    )
    new_id = cur.fetchone()
    new_id = new_id["id"] if isinstance(new_id, dict) else new_id[0]
    return get_rule(cur, new_id)


def update_rule(
    cur,
    rule_id: int,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    filter_jsonb: Optional[dict] = None,
    can_view: Optional[bool] = None,
    can_edit: Optional[bool] = None,
    is_active: Optional[bool] = None,
) -> Optional[dict]:
    sets, params = [], []
    if name is not None:
        sets.append("name = %s")
        params.append(name.strip())
    if description is not None:
        sets.append("description = %s")
        params.append(description)
    if filter_jsonb is not None:
        sets.append("filter_jsonb = %s::jsonb")
        params.append(json.dumps(filter_jsonb))
    if can_view is not None:
        sets.append("can_view = %s")
        params.append(can_view)
    if can_edit is not None:
        sets.append("can_edit = %s")
        params.append(can_edit)
    if is_active is not None:
        sets.append("is_active = %s")
        params.append(is_active)
    if not sets:
        return get_rule(cur, rule_id)
    params.append(rule_id)
    cur.execute(
        f"UPDATE crm.lead_sharing_rules SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    if cur.rowcount == 0:
        return None
    return get_rule(cur, rule_id)


def delete_rule(cur, rule_id: int) -> bool:
    cur.execute("DELETE FROM crm.lead_sharing_rules WHERE id = %s", (rule_id,))
    return cur.rowcount > 0

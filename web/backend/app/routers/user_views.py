"""
Router para vistas guardadas por usuario.

V063: cada usuario puede guardar combinaciones de filtros + sort + columnas
visibles + orden de columnas, con un nombre, icono y color. En vez de
re-aplicar filtros cada vez, un clic restaura toda la configuracion.

Tres niveles de visibilidad:
  - 'personal': solo el owner
  - 'team':     supervisor + sus asesores (team_supervisor_id obligatorio)
  - 'public':   todos los autenticados. Solo admin puede crearlas.

Patron: patrón premium / patrón premium / patrón premium.

Endpoints:
  - GET    /api/views?scope=leads      lista accesibles por el user
  - POST   /api/views                  crear (valida permisos por share_level)
  - PATCH  /api/views/{id}             actualizar (solo owner o admin)
  - DELETE /api/views/{id}             borrar  (solo owner o admin)
  - POST   /api/views/{id}/default     marcar como default (otra del mismo scope
                                       queda desmarcada)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/views", tags=["User Views"])


# ── Constantes ──────────────────────────────────────────────────────────────

VALID_SCOPES       = {"leads", "asignacion", "historicos"}
VALID_SHARE_LEVELS = {"personal", "team", "public"}


# ── Schemas ─────────────────────────────────────────────────────────────────

class ViewCreate(BaseModel):
    scope:               str
    name:                str = Field(..., min_length=1, max_length=120)
    icon:                Optional[str] = Field(None, max_length=40)
    color:               Optional[str] = Field(None, max_length=20)
    share_level:         str = "personal"
    team_supervisor_id:  Optional[str] = None
    is_default:          bool = False
    filters:             dict = Field(default_factory=dict)
    sort:                list = Field(default_factory=list)
    columns_order:       list = Field(default_factory=list)
    visible_columns:     list = Field(default_factory=list)


class ViewUpdate(BaseModel):
    name:                Optional[str] = Field(None, min_length=1, max_length=120)
    icon:                Optional[str] = Field(None, max_length=40)
    color:               Optional[str] = Field(None, max_length=20)
    share_level:         Optional[str] = None
    team_supervisor_id:  Optional[str] = None
    is_default:          Optional[bool] = None
    filters:             Optional[dict] = None
    sort:                Optional[list] = None
    columns_order:       Optional[list] = None
    visible_columns:     Optional[list] = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _serialize_view(row: dict) -> dict:
    """Convierte la fila DB a JSON friendly. JSONB ya viene como dict/list
    de psycopg2; solo casteamos UUIDs/timestamps a string."""
    return {
        "id":                  str(row["id"]),
        "user_id":             str(row["user_id"]),
        "owner_name":          row.get("owner_name"),
        "scope":               row["scope"],
        "name":                row["name"],
        "icon":                row.get("icon"),
        "color":               row.get("color"),
        "share_level":         row["share_level"],
        "team_supervisor_id":  str(row["team_supervisor_id"]) if row.get("team_supervisor_id") else None,
        "team_supervisor_name": row.get("team_supervisor_name"),
        "is_default":          bool(row["is_default"]),
        "filters":             row.get("filters") or {},
        "sort":                row.get("sort") or [],
        "columns_order":       row.get("columns_order") or [],
        "visible_columns":     row.get("visible_columns") or [],
        "created_at":          row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at":          row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _validate_share_permissions(
    cur,
    user: TokenData,
    share_level: str,
    team_supervisor_id: Optional[str],
):
    """Reglas:
      - 'personal': cualquiera. team_supervisor_id debe ser NULL.
      - 'team':     solo admin o el propio supervisor del equipo. team_supervisor_id obligatorio.
      - 'public':   solo admin.
    Lanza HTTPException si la combinacion no es permitida."""
    if share_level not in VALID_SHARE_LEVELS:
        raise HTTPException(400, f"share_level invalido. Permitidos: {sorted(VALID_SHARE_LEVELS)}")

    if share_level == "personal":
        if team_supervisor_id is not None:
            raise HTTPException(400, "Vistas personales no llevan team_supervisor_id.")
        return

    if share_level == "public":
        if user.role != Role.ADMIN:
            raise HTTPException(403, "Solo admin puede crear vistas publicas.")
        if team_supervisor_id is not None:
            raise HTTPException(400, "Vistas publicas no llevan team_supervisor_id.")
        return

    # share_level == 'team'
    if not team_supervisor_id:
        raise HTTPException(400, "Vistas de equipo requieren team_supervisor_id.")
    if user.role == Role.ADMIN:
        return
    if user.role == Role.SUPERVISOR and str(user.user_id) == str(team_supervisor_id):
        return
    raise HTTPException(403, "Solo el propio supervisor del equipo o admin pueden crear vistas de equipo.")


def _fetch_view_or_404(cur, view_id: str) -> dict:
    cur.execute(
        """
        SELECT v.*,
               u.first_name || ' ' || COALESCE(u.last_name, '') AS owner_name,
               s.first_name || ' ' || COALESCE(s.last_name, '') AS team_supervisor_name
        FROM crm.user_views v
        LEFT JOIN auth.users u ON u.id = v.user_id
        LEFT JOIN auth.users s ON s.id = v.team_supervisor_id
        WHERE v.id = %s::uuid
        """,
        (view_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Vista no encontrada")
    return row


def _can_modify(view_row: dict, user: TokenData) -> bool:
    """Solo el owner o admin puede editar/borrar."""
    if user.role == Role.ADMIN or (getattr(user, "role_id", None) is not None and not getattr(user, "role_is_external", False)):
        return True
    return str(view_row["user_id"]) == str(user.user_id)


def _clear_other_defaults(cur, user_id: str, scope: str, except_id: Optional[str] = None):
    """Garantiza unicidad de is_default por (user_id, scope) — desmarca las
    demas vistas del mismo scope para el mismo owner."""
    if except_id:
        cur.execute(
            """
            UPDATE crm.user_views
            SET is_default = FALSE
            WHERE user_id = %s::uuid AND scope = %s
              AND id <> %s::uuid AND is_default = TRUE
            """,
            (user_id, scope, except_id),
        )
    else:
        cur.execute(
            """
            UPDATE crm.user_views
            SET is_default = FALSE
            WHERE user_id = %s::uuid AND scope = %s AND is_default = TRUE
            """,
            (user_id, scope),
        )


# ── Endpoints ───────────────────────────────────────────────────────────────
# NOTA: V063 fase B instalaba vistas seed automaticas al primer GET. Removido
# en V066 — los users no entendian de donde salian. El boton "+ Vista" es
# suficiente para que la feature se descubra al usarla.

@router.get("")
def list_views(
    scope: str = Query(..., description="leads | asignacion | historicos"),
    user: TokenData = Depends(get_current_user),
):
    """Vistas visibles para el usuario en un scope:
      - propias (cualquier share_level)
      - de equipo donde el usuario participa (asesor o supervisor)
      - todas las publicas
    """
    if scope not in VALID_SCOPES:
        raise HTTPException(400, f"scope invalido. Permitidos: {sorted(VALID_SCOPES)}")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Construimos un UNION semantico via OR — psycopg2 maneja el cast
            # de uuids con el placeholder %s::uuid.
            cur.execute(
                """
                SELECT v.*,
                       (u.first_name || ' ' || COALESCE(u.last_name, '')) AS owner_name,
                       (s.first_name || ' ' || COALESCE(s.last_name, '')) AS team_supervisor_name
                FROM crm.user_views v
                LEFT JOIN auth.users u ON u.id = v.user_id
                LEFT JOIN auth.users s ON s.id = v.team_supervisor_id
                WHERE v.scope = %s
                  AND (
                        v.user_id = %s::uuid                                   -- personal del owner
                     OR v.share_level = 'public'                               -- publicas
                     OR (
                          v.share_level = 'team'
                          AND (
                                v.team_supervisor_id = %s::uuid                -- yo soy el supervisor del equipo
                             OR v.team_supervisor_id IN (
                                  SELECT supervisor_id
                                  FROM crm.equipos
                                  WHERE asesor_id = %s::uuid AND activo = TRUE -- soy asesor de ese equipo
                                )
                          )
                        )
                      )
                ORDER BY v.is_default DESC, v.share_level, v.name
                """,
                (scope, user.user_id, user.user_id, user.user_id),
            )
            rows = cur.fetchall()
    return [_serialize_view(r) for r in rows]


@router.post("", status_code=201)
def create_view(data: ViewCreate, user: TokenData = Depends(get_current_user)):
    if data.scope not in VALID_SCOPES:
        raise HTTPException(400, f"scope invalido. Permitidos: {sorted(VALID_SCOPES)}")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _validate_share_permissions(cur, user, data.share_level, data.team_supervisor_id)

            if data.is_default:
                _clear_other_defaults(cur, user.user_id, data.scope)

            cur.execute(
                """
                INSERT INTO crm.user_views (
                    user_id, scope, name, icon, color, share_level,
                    team_supervisor_id, is_default,
                    filters, sort, columns_order, visible_columns
                )
                VALUES (
                    %s::uuid, %s, %s, %s, %s, %s,
                    %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb
                )
                RETURNING *
                """,
                (
                    user.user_id, data.scope, data.name.strip(), data.icon, data.color, data.share_level,
                    data.team_supervisor_id, data.is_default,
                    json.dumps(data.filters), json.dumps(data.sort),
                    json.dumps(data.columns_order), json.dumps(data.visible_columns),
                ),
            )
            row = cur.fetchone()
            # Enriquecer con nombres para la respuesta
            cur.execute(
                """
                SELECT (u.first_name || ' ' || COALESCE(u.last_name, '')) AS owner_name,
                       (s.first_name || ' ' || COALESCE(s.last_name, '')) AS team_supervisor_name
                FROM auth.users u
                LEFT JOIN auth.users s ON s.id = %s::uuid
                WHERE u.id = %s::uuid
                """,
                (data.team_supervisor_id, user.user_id),
            )
            extra = cur.fetchone() or {}
            row["owner_name"] = extra.get("owner_name")
            row["team_supervisor_name"] = extra.get("team_supervisor_name")
        conn.commit()

    logger.info("[views] CREATED id=%s scope=%s share=%s by=%s",
                row["id"], data.scope, data.share_level, user.user_id)
    return _serialize_view(row)


@router.patch("/{view_id}")
def update_view(view_id: str, data: ViewUpdate, user: TokenData = Depends(get_current_user)):
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k in {"icon", "color", "team_supervisor_id"}}
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            existing = _fetch_view_or_404(cur, view_id)
            if not _can_modify(existing, user):
                raise HTTPException(403, "Solo el owner o admin puede modificar la vista.")

            # Si cambia share_level / team_supervisor_id, revalidamos permisos.
            new_share = fields.get("share_level", existing["share_level"])
            new_team  = fields.get("team_supervisor_id", existing["team_supervisor_id"])
            if "share_level" in fields or "team_supervisor_id" in fields:
                _validate_share_permissions(cur, user, new_share, str(new_team) if new_team else None)

            # Si quiere ser default, desmarcamos las demas del mismo owner+scope.
            if fields.get("is_default") is True:
                _clear_other_defaults(cur, existing["user_id"], existing["scope"], except_id=view_id)

            # SQL dinamico — castea cada campo segun su tipo.
            set_parts: list[str] = []
            params:    list[Any] = []
            JSONB_FIELDS = {"filters", "sort", "columns_order", "visible_columns"}
            for k, v in fields.items():
                if k in JSONB_FIELDS:
                    set_parts.append(f"{k} = %s::jsonb")
                    params.append(json.dumps(v) if v is not None else None)
                elif k == "team_supervisor_id":
                    set_parts.append("team_supervisor_id = %s::uuid")
                    params.append(v)
                else:
                    set_parts.append(f"{k} = %s")
                    params.append(v)
            params.append(view_id)

            cur.execute(
                f"UPDATE crm.user_views SET {', '.join(set_parts)} WHERE id = %s::uuid RETURNING *",
                params,
            )
            row = cur.fetchone()
            # Enriquecer
            cur.execute(
                """
                SELECT (u.first_name || ' ' || COALESCE(u.last_name, '')) AS owner_name,
                       (s.first_name || ' ' || COALESCE(s.last_name, '')) AS team_supervisor_name
                FROM auth.users u
                LEFT JOIN auth.users s ON s.id = %s::uuid
                WHERE u.id = %s::uuid
                """,
                (row.get("team_supervisor_id"), row["user_id"]),
            )
            extra = cur.fetchone() or {}
            row["owner_name"] = extra.get("owner_name")
            row["team_supervisor_name"] = extra.get("team_supervisor_name")
        conn.commit()

    logger.info("[views] UPDATED id=%s by=%s fields=%s", view_id, user.user_id, list(fields.keys()))
    return _serialize_view(row)


@router.delete("/{view_id}")
def delete_view(view_id: str, user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            existing = _fetch_view_or_404(cur, view_id)
            if not _can_modify(existing, user):
                raise HTTPException(403, "Solo el owner o admin puede eliminar la vista.")
            cur.execute("DELETE FROM crm.user_views WHERE id = %s::uuid", (view_id,))
        conn.commit()
    logger.warning("[views] DELETED id=%s by=%s", view_id, user.user_id)
    return {"ok": True}


@router.post("/{view_id}/default")
def set_default(view_id: str, user: TokenData = Depends(get_current_user)):
    """Marca esta vista como default del owner para su scope. Desmarca las
    demas del mismo scope. Solo el owner puede setear su propio default."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            existing = _fetch_view_or_404(cur, view_id)
            # Solo el propio user_id puede setear su default — admin no
            # decide la vista default de otros usuarios.
            if str(existing["user_id"]) != str(user.user_id):
                raise HTTPException(403, "Solo podes marcar como default tus propias vistas.")
            _clear_other_defaults(cur, user.user_id, existing["scope"], except_id=view_id)
            cur.execute(
                "UPDATE crm.user_views SET is_default = TRUE WHERE id = %s::uuid",
                (view_id,),
            )
        conn.commit()
    return {"ok": True}

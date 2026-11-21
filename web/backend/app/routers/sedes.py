"""
Router para crm.sedes (V065).

Sedes / ubicaciones de servicio del cliente del CRM. Atributo del lead,
no organizacion separada — un solo CRM gestiona leads de todas las
sedes; cada lead tiene un sede_id de destino.

Endpoints:
  - GET  /api/sedes/lookup   — cualquier rol autenticado (para dropdowns)
  - GET  /api/admin/sedes    — admin / supervisor (incluye inactivas + counts)
  - POST /api/admin/sedes    — admin
  - PATCH /api/admin/sedes/{id} — admin
  - DELETE /api/admin/sedes/{id} — admin (soft: marca activo=FALSE si tiene leads)

Filosofia SOLID:
  - SRP: este router solo gestiona el CRUD de sedes. La asignacion de
    sedes a leads vive en los routers de leads/ingest/public_forms.
  - OCP: agregar campos a la sede no requiere cambiar el filtro/lookup
    de leads — el sede_id es la unica dependencia.
  - DIP: los routers que necesiten "lista de sedes activas" consumen el
    lookup, no leen directo de la tabla.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)

# Router admin (CRUD)
admin_router = APIRouter(prefix="/api/admin/sedes", tags=["Admin / Sedes"])
# Router publico (lookup) — cualquier rol autenticado lo consume para
# poblar dropdowns y filtros. NO expone counts ni config sensible.
lookup_router = APIRouter(prefix="/api/sedes", tags=["Sedes (lookup)"])


# ── Schemas ──────────────────────────────────────────────────────────────

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$")


class SedeCreate(BaseModel):
    codigo:    str = Field(..., min_length=2, max_length=40)
    nombre:    str = Field(..., min_length=2, max_length=120)
    ciudad:    Optional[str] = Field(None, max_length=80)
    direccion: Optional[str] = Field(None, max_length=255)
    telefono:  Optional[str] = Field(None, max_length=40)
    color_hex: Optional[str] = Field(None, max_length=20)
    config:    Optional[dict] = None


class SedeUpdate(BaseModel):
    nombre:    Optional[str] = Field(None, min_length=2, max_length=120)
    ciudad:    Optional[str] = Field(None, max_length=80)
    direccion: Optional[str] = Field(None, max_length=255)
    telefono:  Optional[str] = Field(None, max_length=40)
    color_hex: Optional[str] = Field(None, max_length=20)
    activo:    Optional[bool] = None
    config:    Optional[dict] = None


# ── Helpers ──────────────────────────────────────────────────────────────

def _validate_codigo(codigo: str) -> str:
    s = (codigo or "").strip().lower()
    if not SLUG_RE.match(s):
        raise HTTPException(
            400,
            "Código inválido. Solo a-z, 0-9, '-', '_'. Min 2 caracteres, empieza y termina alfanumérico.",
        )
    return s


def _serialize(row: dict, include_admin_fields: bool = False) -> dict:
    out = {
        "id":         str(row["id"]),
        "codigo":     row["codigo"],
        "nombre":     row["nombre"],
        "ciudad":     row.get("ciudad"),
        "direccion":  row.get("direccion"),
        "telefono":   row.get("telefono"),
        "color_hex":  row.get("color_hex"),
        "activo":     bool(row["activo"]),
    }
    if include_admin_fields:
        out["config"]      = row.get("config") or {}
        out["leads_count"] = int(row.get("leads_count") or 0)
        out["created_at"]  = row["created_at"].isoformat() if row.get("created_at") else None
        out["updated_at"]  = row["updated_at"].isoformat() if row.get("updated_at") else None
    return out


# ── LOOKUP (cualquier rol autenticado) ───────────────────────────────────

@lookup_router.get("/lookup")
def lookup_sedes(
    only_active: bool = Query(True, description="True = solo sedes activas (default)"),
    _user: TokenData = Depends(get_current_user),
):
    """Lista de sedes para dropdowns / filtros. No expone config interna
    ni counts de leads — solo lo necesario para que el frontend muestre
    el selector."""
    where = "TRUE"
    if only_active:
        where = "activo = TRUE"
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, codigo, nombre, ciudad, direccion, telefono,
                       color_hex, activo
                FROM crm.sedes
                WHERE {where}
                ORDER BY activo DESC, nombre
                """
            )
            rows = cur.fetchall()
    return [_serialize(r) for r in rows]


# ── ADMIN (CRUD) ─────────────────────────────────────────────────────────

@admin_router.get("")
def list_sedes(_user: TokenData = Depends(check_permission("config.manage"))):
    """Lista completa con count de leads asociados por sede. Incluye
    inactivas. Visible a admin + supervisor (consultivo)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*)::int
                          FROM crm.leads l
                          WHERE l.sede_id = s.id AND l.activo = TRUE
                       ) AS leads_count
                FROM crm.sedes s
                ORDER BY s.activo DESC, s.nombre
                """
            )
            rows = cur.fetchall()
    return [_serialize(r, include_admin_fields=True) for r in rows]


@admin_router.post("", status_code=201)
def create_sede(data: SedeCreate, admin: TokenData = Depends(check_permission("config.manage"))):
    codigo = _validate_codigo(data.codigo)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM crm.sedes WHERE codigo = %s", (codigo,))
            if cur.fetchone():
                raise HTTPException(409, "Ya existe una sede con ese código.")
            cur.execute(
                """
                INSERT INTO crm.sedes
                    (codigo, nombre, ciudad, direccion, telefono, color_hex, config)
                VALUES (%s, %s, %s, %s, %s, COALESCE(%s, '#6366F1'), COALESCE(%s::jsonb, '{}'::jsonb))
                RETURNING *
                """,
                (
                    codigo, data.nombre.strip(),
                    data.ciudad, data.direccion, data.telefono,
                    data.color_hex,
                    None if data.config is None else __import__('json').dumps(data.config),
                ),
            )
            row = cur.fetchone()
            row["leads_count"] = 0
        conn.commit()
    logger.info("[sedes] CREATED codigo=%s nombre=%s by=%s", codigo, data.nombre, admin.user_id)
    return _serialize(row, include_admin_fields=True)


@admin_router.patch("/{sede_id}")
def update_sede(sede_id: str, data: SedeUpdate, admin: TokenData = Depends(check_permission("config.manage"))):
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar.")

    set_parts: list[str] = []
    params: list = []
    JSONB_FIELDS = {"config"}
    for k, v in fields.items():
        if k in JSONB_FIELDS:
            set_parts.append(f"{k} = %s::jsonb")
            params.append(None if v is None else __import__('json').dumps(v))
        else:
            set_parts.append(f"{k} = %s")
            params.append(v)
    params.append(sede_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.sedes SET {', '.join(set_parts)} WHERE id = %s::uuid RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Sede no encontrada.")
            cur.execute(
                "SELECT COUNT(*)::int AS n FROM crm.leads WHERE sede_id = %s::uuid AND activo = TRUE",
                (sede_id,),
            )
            row["leads_count"] = (cur.fetchone() or {}).get("n", 0)
        conn.commit()
    logger.info("[sedes] UPDATED id=%s by=%s fields=%s", sede_id, admin.user_id, list(fields.keys()))
    return _serialize(row, include_admin_fields=True)


@admin_router.delete("/{sede_id}")
def delete_sede(sede_id: str, admin: TokenData = Depends(check_permission("config.manage"))):
    """Soft delete: si tiene leads asociados, se marca activo=FALSE y
    queda visible solo en filtros legacy. Si no tiene leads, hard delete.

    Patron patrón estándar 'archive vs delete' — preserva trazabilidad
    historica (un lead con sede borrada pierde info no recuperable).
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*)::int AS n FROM crm.leads WHERE sede_id = %s::uuid",
                (sede_id,),
            )
            leads_count = (cur.fetchone() or {}).get("n", 0)
            if leads_count > 0:
                # Soft delete — preserva trazabilidad
                cur.execute(
                    "UPDATE crm.sedes SET activo = FALSE WHERE id = %s::uuid RETURNING id",
                    (sede_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(404, "Sede no encontrada.")
                action = "archived"
            else:
                # Hard delete — no hay datos asociados
                cur.execute(
                    "DELETE FROM crm.sedes WHERE id = %s::uuid RETURNING id",
                    (sede_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(404, "Sede no encontrada.")
                action = "deleted"
        conn.commit()
    logger.warning("[sedes] %s id=%s leads=%d by=%s",
                   action.upper(), sede_id, leads_count, admin.user_id)
    return {"ok": True, "action": action, "leads_count": leads_count}

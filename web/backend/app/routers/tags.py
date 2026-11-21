"""
Tags router — catalogo de etiquetas + asignacion N:M a leads.

Etiquetas complementan el estado del pipeline: el estado dice donde esta el
lead, la etiqueta como lo quiero agrupar o que necesita (Caliente, Requiere
visita, Lote 8, Pendiente info...). Ver V026_lead_tags.sql.

Endpoints:
    GET    /api/tags              — lista etiquetas activas (todos)
    POST   /api/tags              — crear (admin)
    PATCH  /api/tags/:id          — editar (admin)
    DELETE /api/tags/:id          — soft-delete (admin)
    POST   /api/tags/reorder      — reordenar (admin)

    POST   /api/leads/:id/tags          — asignar etiqueta al lead
    DELETE /api/leads/:id/tags/:tag_id  — quitar etiqueta del lead

Permisos lead-tag:
    - admin: cualquier lead
    - supervisor: leads de su equipo
    - asesor: solo sus leads
Reusa la misma politica que el resto de writes sobre crm.leads.
"""
from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, field_validator

from app.auth.jwt import get_current_user, require_admin
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db
from app.sql_utils import safe_set_clause

router = APIRouter(prefix="/api", tags=["Tags"])

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_TAG_COLUMNS = {"nombre", "color_hex", "descripcion", "orden"}


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class TagCreate(BaseModel):
    nombre: str
    color_hex: str = "#6366f1"
    descripcion: Optional[str] = None

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("El nombre es obligatorio")
        if len(v) > 64:
            raise ValueError("Máximo 64 caracteres")
        return v

    @field_validator("color_hex")
    @classmethod
    def _hex_valido(cls, v: str) -> str:
        if not _HEX_RE.match(v or ""):
            raise ValueError("Color inválido, usa formato #RRGGBB")
        return v


class TagUpdate(BaseModel):
    nombre: Optional[str] = None
    color_hex: Optional[str] = None
    descripcion: Optional[str] = None
    orden: Optional[int] = None

    @field_validator("nombre")
    @classmethod
    def _nombre_check(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("El nombre no puede quedar vacío")
        return v[:64]

    @field_validator("color_hex")
    @classmethod
    def _hex_check(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _HEX_RE.match(v):
            raise ValueError("Color inválido, usa formato #RRGGBB")
        return v


class ReorderRequest(BaseModel):
    ids: List[int]


class AssignTagBody(BaseModel):
    tag_id: int


# ─────────────────────────────────────────────────────────────────────────────
# Catalogo
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tags")
def list_tags(current_user: TokenData = Depends(get_current_user)):
    """Todas las etiquetas activas con conteo de leads asociados."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT t.id, t.nombre, t.color_hex, t.descripcion, t.orden,
                       COALESCE(lc.cnt, 0) AS leads_count
                FROM crm.tags t
                LEFT JOIN (
                    SELECT tag_id, COUNT(*) AS cnt
                    FROM crm.lead_tags
                    GROUP BY tag_id
                ) lc ON lc.tag_id = t.id
                WHERE t.activo = TRUE
                ORDER BY t.orden, t.nombre
                """
            )
            return cur.fetchall()


@router.post("/tags", status_code=201)
def create_tag(data: TagCreate, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(orden), 0) + 10 AS next FROM crm.tags")
            next_orden = cur.fetchone()["next"]
            try:
                cur.execute(
                    """
                    INSERT INTO crm.tags (nombre, color_hex, descripcion, orden)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (nombre) DO UPDATE
                        SET activo      = TRUE,
                            color_hex   = EXCLUDED.color_hex,
                            descripcion = EXCLUDED.descripcion,
                            updated_at  = NOW()
                    RETURNING id, nombre, color_hex, descripcion, orden
                    """,
                    (data.nombre, data.color_hex, data.descripcion, next_orden),
                )
                row = cur.fetchone()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"No se pudo crear: {exc}")
        conn.commit()
    return {**row, "leads_count": 0}


@router.patch("/tags/{tag_id}", status_code=200)
def update_tag(tag_id: int, data: TagUpdate, admin: TokenData = Depends(require_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")
    set_clause, set_params = safe_set_clause(fields, _TAG_COLUMNS)
    # Trigger updated_at manualmente — no hay trigger en la tabla
    set_clause = f"{set_clause}, updated_at = NOW()"
    params = set_params + [tag_id]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute(
                    f"""
                    UPDATE crm.tags SET {set_clause}
                    WHERE id = %s AND activo = TRUE
                    RETURNING id, nombre, color_hex, descripcion, orden
                    """,
                    params,
                )
                row = cur.fetchone()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"No se pudo actualizar: {exc}")
            if not row:
                raise HTTPException(status_code=404, detail="Etiqueta no encontrada")
        conn.commit()
    return row


@router.delete("/tags/{tag_id}", status_code=200)
def delete_tag(tag_id: int, admin: TokenData = Depends(require_admin)):
    """Soft-delete: activo=FALSE. Asociaciones lead_tags se mantienen pero
    dejan de mostrarse en el UI (filter activo=TRUE)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crm.tags SET activo = FALSE, updated_at = NOW() "
                "WHERE id = %s AND activo = TRUE RETURNING id",
                (tag_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Etiqueta no encontrada")
        conn.commit()
    return {"message": "Etiqueta desactivada"}


@router.post("/tags/reorder", status_code=200)
def reorder_tags(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    """Actualiza el orden (multiplos de 10) segun la lista de IDs."""
    with get_db() as conn:
        with conn.cursor() as cur:
            for i, tag_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.tags SET orden = %s, updated_at = NOW() WHERE id = %s",
                    ((i + 1) * 10, tag_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


# ─────────────────────────────────────────────────────────────────────────────
# Asignacion lead <-> tag
# ─────────────────────────────────────────────────────────────────────────────

def _assert_lead_access(cur, lead_id: int, user: TokenData) -> None:
    """Verifica que el user pueda tocar este lead. Lanza 403/404 si no."""
    cur.execute(
        "SELECT asesor_id FROM crm.leads WHERE id = %s AND activo = TRUE",
        (lead_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    if user.role == Role.ADMIN or (getattr(user, "role_id", None) is not None and not getattr(user, "role_is_external", False)):
        return

    asesor_id = row["asesor_id"] if isinstance(row, dict) else row[0]

    if user.role == Role.ASESOR:
        if not asesor_id or str(asesor_id) != str(user.user_id):
            raise HTTPException(status_code=403, detail="Sin acceso a este lead")
        return

    if user.role == Role.SUPERVISOR:
        # Supervisor: asesor_id debe ser el mismo supervisor o pertenecer a su equipo
        if asesor_id and str(asesor_id) == str(user.user_id):
            return
        cur.execute(
            """
            SELECT 1 FROM crm.equipos
            WHERE supervisor_id = %s::uuid
              AND asesor_id     = %s::uuid
              AND activo        = TRUE
            """,
            (user.user_id, str(asesor_id) if asesor_id else None),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=403, detail="Lead fuera de tu equipo")


@router.post("/leads/{lead_id}/tags", status_code=201)
def assign_tag_to_lead(
    lead_id: int,
    data: AssignTagBody,
    current_user: TokenData = Depends(get_current_user),
):
    """Asocia una etiqueta a un lead. Idempotente (ON CONFLICT DO NOTHING)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_lead_access(cur, lead_id, current_user)

            # Validar tag activo
            cur.execute(
                "SELECT id FROM crm.tags WHERE id = %s AND activo = TRUE",
                (data.tag_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Etiqueta no encontrada")

            cur.execute(
                """
                INSERT INTO crm.lead_tags (lead_id, tag_id, created_by_user)
                VALUES (%s, %s, %s::uuid)
                ON CONFLICT (lead_id, tag_id) DO NOTHING
                """,
                (lead_id, data.tag_id, current_user.user_id),
            )
        conn.commit()
    return {"message": "Etiqueta asignada", "lead_id": lead_id, "tag_id": data.tag_id}


@router.delete("/leads/{lead_id}/tags/{tag_id}", status_code=200)
def remove_tag_from_lead(
    lead_id: int,
    tag_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_lead_access(cur, lead_id, current_user)
            cur.execute(
                "DELETE FROM crm.lead_tags WHERE lead_id = %s AND tag_id = %s",
                (lead_id, tag_id),
            )
        conn.commit()
    return {"message": "Etiqueta removida"}


@router.get("/leads/{lead_id}/tags")
def get_lead_tags(
    lead_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Lista las etiquetas activas asociadas al lead."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_lead_access(cur, lead_id, current_user)
            cur.execute(
                """
                SELECT t.id, t.nombre, t.color_hex, t.descripcion
                FROM crm.lead_tags lt
                JOIN crm.tags t ON t.id = lt.tag_id
                WHERE lt.lead_id = %s AND t.activo = TRUE
                ORDER BY t.orden, t.nombre
                """,
                (lead_id,),
            )
            return cur.fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Asignacion conversation <-> tag (V038)
#
# Las tags se aplican a CONVERSACIONES (no solo leads). Esto permite
# categorizar inbound que no califica como lead (spam, soporte, postventa,
# pregunta tecnica). Cuando la conv se "promueve" a lead via "Tomar este
# chat", el trigger crm.fn_inherit_conv_tags_to_lead copia automaticamente
# las tags al lead — la herencia ocurre en DB, no en aplicacion.
# ─────────────────────────────────────────────────────────────────────────────

def _assert_conv_access(cur, conv_id: int, user: TokenData) -> Optional[int]:
    """Verifica que el user pueda tocar esta conv. Devuelve lead_id (o None).

    Misma logica de _assert_lead_access pero a nivel conversacion. Para
    conversaciones con lead_id asignado, deferimos a la regla del lead
    (mas estricta — el lead pertenece a un asesor, la conv puede no).
    Sin lead asignado: solo admin/supervisor pueden etiquetar (porque
    asesor no es responsable de la conv hasta tomarla).
    """
    cur.execute(
        "SELECT lead_id, asesor_id FROM crm.wa_conversations WHERE id = %s",
        (conv_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    lead_id = row["lead_id"] if isinstance(row, dict) else row[0]
    asesor_id = row["asesor_id"] if isinstance(row, dict) else row[1]

    if user.role == Role.ADMIN or (getattr(user, "role_id", None) is not None and not getattr(user, "role_is_external", False)):
        return lead_id

    if user.role == Role.ASESOR:
        # Asesor solo puede etiquetar conversaciones que YA tiene asignadas
        if not asesor_id or str(asesor_id) != str(user.user_id):
            raise HTTPException(status_code=403, detail="Sin acceso a esta conversación")
        return lead_id

    if user.role == Role.SUPERVISOR:
        if asesor_id and str(asesor_id) == str(user.user_id):
            return lead_id
        if not asesor_id:
            # Conv sin asesor todavia: supervisor puede etiquetarla
            # (workflow: triage antes de tomar/asignar)
            return lead_id
        cur.execute(
            """
            SELECT 1 FROM crm.equipos
            WHERE supervisor_id = %s::uuid
              AND asesor_id     = %s::uuid
              AND activo        = TRUE
            """,
            (user.user_id, str(asesor_id)),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=403, detail="Conversación fuera de tu equipo")
        return lead_id

    raise HTTPException(status_code=403, detail="Rol sin acceso a etiquetar conversaciones")


@router.post("/whatsapp/conversations/{conv_id}/tags", status_code=201)
def assign_tag_to_conversation(
    conv_id: int,
    data: AssignTagBody,
    current_user: TokenData = Depends(get_current_user),
):
    """Asocia una etiqueta a una conversacion. Idempotente.

    Si la conversacion ya tiene lead_id asignado, NO escribimos en lead_tags
    desde aca — el trigger ya copio las tags previas al crear el vinculo, y
    a partir de ese momento el flujo profesional es: nuevas tags se manejan
    en el lead via /api/leads/{id}/tags. Asi evitamos divergencia silenciosa.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_access(cur, conv_id, current_user)

            cur.execute(
                "SELECT id FROM crm.tags WHERE id = %s AND activo = TRUE",
                (data.tag_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Etiqueta no encontrada")

            cur.execute(
                """
                INSERT INTO crm.wa_conversation_tags
                    (conversation_id, tag_id, created_by_user)
                VALUES (%s, %s, %s::uuid)
                ON CONFLICT (conversation_id, tag_id) DO NOTHING
                """,
                (conv_id, data.tag_id, current_user.user_id),
            )
        conn.commit()
    return {"message": "Etiqueta asignada", "conversation_id": conv_id, "tag_id": data.tag_id}


@router.delete("/whatsapp/conversations/{conv_id}/tags/{tag_id}", status_code=200)
def remove_tag_from_conversation(
    conv_id: int,
    tag_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Quita la asociacion. NO elimina la etiqueta del lead heredado — eso
    es decision aparte (un asesor puede querer destaguear la conv archivada
    sin quitarle la etiqueta al lead activo)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_access(cur, conv_id, current_user)
            cur.execute(
                """
                DELETE FROM crm.wa_conversation_tags
                WHERE conversation_id = %s AND tag_id = %s
                """,
                (conv_id, tag_id),
            )
        conn.commit()
    return {"message": "Etiqueta removida"}


@router.get("/whatsapp/conversations/{conv_id}/tags")
def get_conversation_tags(
    conv_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Lista las etiquetas activas asociadas a la conversacion."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _assert_conv_access(cur, conv_id, current_user)
            cur.execute(
                """
                SELECT t.id, t.nombre, t.color_hex, t.descripcion
                FROM crm.wa_conversation_tags ct
                JOIN crm.tags t ON t.id = ct.tag_id
                WHERE ct.conversation_id = %s AND t.activo = TRUE
                ORDER BY t.orden, t.nombre
                """,
                (conv_id,),
            )
            return cur.fetchall()

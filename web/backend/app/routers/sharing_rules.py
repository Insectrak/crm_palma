"""
sharing_rules.py — endpoints CRUD de Sharing Rules (ADR-0012, Sprint 4).

Solo admin gestiona las reglas. Los usuarios afectados (con rol custom)
NO ven estos endpoints — los efectos de las reglas se aplican
transparentemente en /api/leads.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.database import get_db
from app.services import lead_sharing_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sharing-rules", tags=["Sharing Rules"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class SharingRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    role_id: int
    filter_jsonb: dict = Field(default_factory=dict)
    can_view: bool = True
    can_edit: bool = False
    is_active: bool = True


class SharingRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    filter_jsonb: Optional[dict] = None
    can_view: Optional[bool] = None
    can_edit: Optional[bool] = None
    is_active: Optional[bool] = None


def _serialize(rule: dict) -> dict:
    if not rule:
        return rule
    out = dict(rule)
    for k in ("created_at", "updated_at"):
        if out.get(k):
            out[k] = out[k].isoformat()
    return out


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
def list_rules(_: TokenData = Depends(check_permission("roles.manage"))):
    """Lista todas las sharing rules con role_name resuelto."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            rows = lead_sharing_service.list_rules(cur)
    return [_serialize(r) for r in rows]


@router.post("", status_code=201)
def create_rule(payload: SharingRuleCreate, admin: TokenData = Depends(check_permission("roles.manage"))):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                rule = lead_sharing_service.create_rule(
                    cur,
                    name=payload.name,
                    description=payload.description,
                    role_id=payload.role_id,
                    filter_jsonb=payload.filter_jsonb,
                    can_view=payload.can_view,
                    can_edit=payload.can_edit,
                    is_active=payload.is_active,
                    created_by=admin.user_id,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        conn.commit()
    logger.info("Sharing rule creada: id=%s name=%s role_id=%s", rule["id"], rule["name"], rule["role_id"])
    return _serialize(rule)


@router.patch("/{rule_id}")
def update_rule(rule_id: int, payload: SharingRuleUpdate, _: TokenData = Depends(check_permission("roles.manage"))):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            rule = lead_sharing_service.update_rule(
                cur,
                rule_id,
                name=payload.name,
                description=payload.description,
                filter_jsonb=payload.filter_jsonb,
                can_view=payload.can_view,
                can_edit=payload.can_edit,
                is_active=payload.is_active,
            )
            if not rule:
                raise HTTPException(404, "Sharing rule no encontrada.")
        conn.commit()
    return _serialize(rule)


@router.delete("/{rule_id}", status_code=200)
def delete_rule(rule_id: int, _: TokenData = Depends(check_permission("roles.manage"))):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ok = lead_sharing_service.delete_rule(cur, rule_id)
        if ok:
            conn.commit()
    if not ok:
        raise HTTPException(404, "Sharing rule no encontrada.")
    return {"ok": True, "id": rule_id}

"""
Router de asignación de supervisores por campaña de Meta y TikTok.

Permite a los administradores:
  - Listar campañas activas e inactivas sincronizadas desde Meta y TikTok.
  - Sincronizar en vivo campañas desde las APIs de Meta y TikTok.
  - Designar supervisores exclusivos por campaña.
  - Realizar asignaciones masivas de campañas.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.services import campaign_assignment_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/campaign-assignments", tags=["Leads Campañas · Asignación"])


# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class UpdateAssignmentPayload(BaseModel):
    supervisor_id: Optional[str] = Field(None, description="UUID del supervisor o null para rotación general (retrocompatibilidad)")
    supervisor_ids: Optional[List[str]] = Field(None, description="Lista de UUIDs de supervisores designados a la campaña")
    percentages: Optional[Dict[str, Optional[int]]] = Field(None, description="Mapeo de UUID supervisor -> porcentaje (0-100)")
    distribution_mode: Optional[str] = Field(None, description="'supervisor', 'equipo' o 'todos'")
    team_distribution_modes: Optional[Dict[str, Optional[str]]] = Field(None, description="Mapeo supervisor_id -> 'supervisor'|'equipo'|'todos'")
    team_member_percentages: Optional[Dict[str, Optional[Dict[str, Optional[int]]]]] = Field(None, description="Mapeo supervisor_id -> { member_id: % }")
    is_active: Optional[bool] = Field(None, description="Habilitar/deshabilitar regla exclusiva")


class BulkAssignPayload(BaseModel):
    assignment_ids: List[int] = Field(..., min_items=1, description="IDs de las campañas a actualizar")
    supervisor_id: Optional[str] = Field(None, description="UUID del supervisor o null para desasignar (retrocompatibilidad)")
    supervisor_ids: Optional[List[str]] = Field(None, description="Lista de UUIDs de supervisores a designar")
    percentages: Optional[Dict[str, Optional[int]]] = Field(None, description="Mapeo de UUID supervisor -> porcentaje (0-100)")
    distribution_mode: Optional[str] = Field(None, description="'supervisor', 'equipo' o 'todos'")
    team_distribution_modes: Optional[Dict[str, Optional[str]]] = None
    team_member_percentages: Optional[Dict[str, Optional[Dict[str, Optional[int]]]]] = None


class ManualCampaignPayload(BaseModel):
    provider: str = Field(..., description="meta o tiktok")
    campaign_id: str = Field(..., min_length=1, max_length=255)
    campaign_name: Optional[str] = Field(None, max_length=255)
    supervisor_id: Optional[str] = None
    supervisor_ids: Optional[List[str]] = Field(None, description="Lista de UUIDs de supervisores designados")
    percentages: Optional[Dict[str, Optional[int]]] = Field(None, description="Mapeo de UUID supervisor -> porcentaje (0-100)")
    distribution_mode: Optional[str] = Field("supervisor", description="'supervisor', 'equipo' o 'todos'")
    team_distribution_modes: Optional[Dict[str, Optional[str]]] = None
    team_member_percentages: Optional[Dict[str, Optional[Dict[str, Optional[int]]]]] = None
    is_active: bool = True
    status: str = Field("ACTIVE", description="ACTIVE o PAUSED")


# ── Endpoints (Admin Only) ───────────────────────────────────────────────────

@router.get("")
def list_campaigns(
    provider: Optional[str] = Query(None, description="meta, tiktok o all"),
    status: Optional[str] = Query(None, description="ACTIVE, PAUSED o all"),
    supervisor_id: Optional[str] = Query(None, description="UUID o 'unassigned'"),
    is_assigned: Optional[bool] = Query(None, description="true para asignadas, false para sin asignar"),
    search: Optional[str] = Query(None, description="Buscar por nombre o ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: TokenData = Depends(require_admin),
):
    """Lista campañas registradas con filtros, métricas y contadores para KPIs."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            result = campaign_assignment_service.list_campaign_assignments(
                cur,
                provider=provider,
                status_filter=status,
                supervisor_id=supervisor_id,
                search=search,
                is_assigned=is_assigned,
                limit=limit,
                offset=offset,
            )
            return result


@router.post("/sync")
def sync_campaigns(
    admin: TokenData = Depends(require_admin),
):
    """Dispara sincronización en vivo con Meta Graph API y TikTok Marketing API."""
    logger.info("Admin %s disparó sincronización de campañas de Meta y TikTok", admin.email)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            result = campaign_assignment_service.sync_all_campaigns(cur, admin_user_id=admin.user_id)
            conn.commit()
            return result


@router.get("/supervisors")
def get_supervisors(
    _: TokenData = Depends(require_admin),
):
    """Devuelve listado de supervisores y administradores activos disponibles para asignar."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            supervisors = campaign_assignment_service.list_eligible_supervisors(cur)
            return {"items": supervisors}


@router.put("/{assignment_id}")
def update_assignment(
    assignment_id: int = Path(..., ge=1),
    payload: UpdateAssignmentPayload = ...,
    admin: TokenData = Depends(require_admin),
):
    update_supervisor = (
        ("supervisor_id" in payload.__fields_set__)
        or ("supervisor_ids" in payload.__fields_set__)
        or ("percentages" in payload.__fields_set__)
        or ("team_distribution_modes" in payload.__fields_set__)
        or ("team_member_percentages" in payload.__fields_set__)
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            res = campaign_assignment_service.update_campaign_assignment(
                cur,
                assignment_id=assignment_id,
                supervisor_id=payload.supervisor_id,
                supervisor_ids=payload.supervisor_ids,
                percentages=payload.percentages,
                distribution_mode=payload.distribution_mode,
                team_distribution_modes=payload.team_distribution_modes,
                team_member_percentages=payload.team_member_percentages,
                is_active=payload.is_active,
                admin_user_id=admin.user_id,
                update_supervisor=update_supervisor,
            )
            if not res.get("ok"):
                raise HTTPException(status_code=400, detail=res.get("error", "Error actualizando campaña"))
            conn.commit()
            return res


@router.post("/bulk-assign")
def bulk_assign(
    payload: BulkAssignPayload = ...,
    admin: TokenData = Depends(require_admin),
):
    """Asigna uno o más supervisores y/o modo de reparto a un conjunto de campañas seleccionadas."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            res = campaign_assignment_service.bulk_assign_supervisors(
                cur,
                assignment_ids=payload.assignment_ids,
                supervisor_id=payload.supervisor_id,
                supervisor_ids=payload.supervisor_ids,
                percentages=payload.percentages,
                distribution_mode=payload.distribution_mode,
                team_distribution_modes=payload.team_distribution_modes,
                team_member_percentages=payload.team_member_percentages,
                admin_user_id=admin.user_id,
            )
            if not res.get("ok"):
                raise HTTPException(status_code=400, detail=res.get("error", "Error en asignación masiva"))
            conn.commit()
            return res


@router.post("")
def create_manual_campaign(
    payload: ManualCampaignPayload = ...,
    admin: TokenData = Depends(require_admin),
):
    """Registra manualmente una campaña o sobreescribe su configuración."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            res = campaign_assignment_service.create_or_upsert_campaign_assignment(
                cur,
                provider=payload.provider,
                campaign_id=payload.campaign_id,
                campaign_name=payload.campaign_name,
                supervisor_id=payload.supervisor_id,
                supervisor_ids=payload.supervisor_ids,
                percentages=payload.percentages,
                distribution_mode=payload.distribution_mode or "supervisor",
                team_distribution_modes=payload.team_distribution_modes,
                team_member_percentages=payload.team_member_percentages,
                is_active=payload.is_active,
                status=payload.status,
                admin_user_id=admin.user_id,
            )
            if not res.get("ok"):
                raise HTTPException(status_code=400, detail=res.get("error", "Error creando campaña"))
            conn.commit()
            return res


@router.delete("/{assignment_id}")
def delete_campaign(
    assignment_id: int = Path(..., ge=1),
    admin: TokenData = Depends(require_admin),
):
    """Elimina permanentemente una campaña o asignación registrada en el CRM."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            res = campaign_assignment_service.delete_campaign_assignment(cur, assignment_id)
            if not res.get("ok"):
                raise HTTPException(status_code=404, detail=res.get("error", "Campaña no encontrada"))
            conn.commit()
            return res


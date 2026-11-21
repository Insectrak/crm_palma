"""
lead_merge.py — V067 Fase 3: endpoints admin para fusionar duplicados.

Endpoints (todos admin-only):
  GET    /api/admin/leads/duplicates            clusters detectados por telefono
  GET    /api/admin/leads/merge/preview         diff lado a lado de dos leads
  POST   /api/admin/leads/{master_id}/merge     ejecuta la fusion

Permisos: solo admin (alineado con CRMs profesionales: el merge es
destructivo en la practica — se delega historial y el secondary queda
inactivo. No queremos que supervisores hagan merge sin control).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.services import lead_merge_service as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/leads", tags=["Admin / Merge duplicados"])


class MergeRequest(BaseModel):
    secondary_id:    int = Field(..., description="ID del lead que se absorberá en el master")
    chosen_owner_id: Optional[str] = Field(default=None, description="UUID del usuario que tendrá la autoridad del lead fusionado")
    field_decisions: Optional[dict[str, str]] = Field(
        default=None,
        description='Decisiones campo por campo: {"nombres": "master", "email": "secondary", ...}',
    )
    notes:           Optional[str] = Field(default=None, max_length=2000)


@router.get("/duplicates")
def list_duplicates(
    limit: int = Query(500, ge=1, le=2000),
    _admin: TokenData = Depends(require_admin),
):
    """Lista clusters de leads activos con el mismo telefono.

    Devuelve { clusters, total_clusters, total_clusters_global, total_capped, limit }.
    total_clusters_global = cantidad TOTAL de clusters (puede ser > limit).
    total_capped = TRUE si quedaron clusters fuera del LIMIT (el admin
    necesita subir limit para verlos todos).
    """
    result = svc.list_duplicate_clusters(limit=limit)
    return {
        "clusters":              result["clusters"],
        "total_clusters":        len(result["clusters"]),
        "total_clusters_global": result["total_clusters_global"],
        "total_capped":          result["total_capped"],
        "limit":                 result["limit"],
    }


@router.get("/merge/preview")
def merge_preview(
    master_id:    int = Query(..., ge=1),
    secondary_id: int = Query(..., ge=1),
    _admin: TokenData = Depends(require_admin),
):
    """Devuelve un diff lado a lado de dos leads para que el admin decida
    campo por campo qué se conserva antes de confirmar el merge."""
    return svc.preview_merge(master_id, secondary_id)


@router.post("/{master_id}/merge")
def execute_merge(
    master_id: int,
    req:      MergeRequest,
    admin:    TokenData = Depends(require_admin),
):
    """Ejecuta el merge. El secondary queda con merged_into=master_id,
    activo=FALSE; todo el historial se re-apunta al master; el evento se
    audita en crm.lead_merges con snapshot completo."""
    admin_name = " ".join(filter(None, [
        getattr(admin, "first_name", None),
        getattr(admin, "last_name", None),
    ])).strip() or getattr(admin, "email", None)

    return svc.merge_leads(
        master_id=master_id,
        secondary_id=req.secondary_id,
        chosen_owner_id=req.chosen_owner_id,
        field_decisions=req.field_decisions,
        notes=req.notes,
        admin_user_id=admin.user_id,
        admin_user_name=admin_name,
        admin_user_role=getattr(admin, "role", "admin"),
    )

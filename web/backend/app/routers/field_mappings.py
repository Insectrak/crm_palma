"""Endpoints admin para Field Mappings & Custom Properties.

Expone el panel patrón estándar para que marketing pueda:

  - Ver todas las "propiedades custom" del CRM (property definitions).
  - Crear/editar/desactivar propiedades tipadas (text, number, select…).
  - Ver campos de Meta Lead Ads que aún no están mapeados a ninguna
    propiedad/columna (detectados automáticamente desde raw_field_data).
  - Mapear cada campo a una columna nativa, a una propiedad custom, o
    marcarlo como "ignorado" para que no aparezca más en el panel.

Todo admin-only. Los endpoints de lectura de propiedades por lead
(lead/:id/properties) se sirven desde routers/leads.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.services.integrations import field_mappings_repo as fm_repo
from app.services.integrations.field_mappings_repo import (
    ALLOWED_COLUMN_TARGETS,
    ALLOWED_PROPERTY_TYPES,
    ALLOWED_TARGET_TYPES,
    FieldMappingError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrations/field-mappings", tags=["FieldMappings"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class PropertyDefinitionIn(BaseModel):
    property_key:  str = Field(..., min_length=1, max_length=80)
    display_name:  str = Field(..., min_length=1, max_length=120)
    property_type: str = "text"
    options:       Optional[list[str]] = None
    description:   Optional[str] = None
    category:      Optional[str] = None
    icon:          Optional[str] = None


class FormFieldMappingIn(BaseModel):
    provider:        str = "meta"
    form_id:         str = Field(..., min_length=1)
    meta_field_name: str = Field(..., min_length=1)
    target_type:     str
    target_key:      Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Metadata: opciones válidas para la UI
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/options")
def api_options(_: TokenData = Depends(check_permission("integraciones.manage"))):
    """Devuelve listas válidas para los dropdowns del panel."""
    return {
        "target_types":     sorted(ALLOWED_TARGET_TYPES),
        "property_types":   sorted(ALLOWED_PROPERTY_TYPES),
        "allowed_columns":  sorted(ALLOWED_COLUMN_TARGETS),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Property definitions
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/properties")
def api_list_properties(
    include_inactive: bool = Query(False),
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    return {"items": fm_repo.list_property_definitions(active_only=not include_inactive)}


@router.post("/properties")
def api_upsert_property(
    body: PropertyDefinitionIn,
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    try:
        row = fm_repo.upsert_property_definition(
            property_key=body.property_key,
            display_name=body.display_name,
            property_type=body.property_type,
            options=body.options,
            description=body.description,
            category=body.category,
            icon=body.icon,
            created_by=admin.email,
        )
    except FieldMappingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return row


@router.delete("/properties/{property_key}")
def api_delete_property(
    property_key: str,
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    try:
        deleted = fm_repo.delete_property_definition(property_key)
    except FieldMappingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    if not deleted:
        raise HTTPException(status_code=404, detail="Propiedad no encontrada.")
    return {"ok": True, "property_key": property_key}


@router.delete("/properties/{property_key}/values")
def api_delete_property_values(
    property_key: str,
    dry_run: bool = Query(False, description="Si es true, solo cuenta sin borrar."),
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Borra todos los valores guardados en lead_properties para una property.

    Operación destructiva e irreversible. Admin-only.
    Recomendado: llamar primero con dry_run=true para mostrar el impacto en UI.
    """
    try:
        result = fm_repo.delete_property_values(
            property_key=property_key,
            dry_run=dry_run,
            triggered_by=admin.email,
        )
    except FieldMappingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    logger.info(
        "field_mappings.delete_values endpoint property_key=%s dry_run=%s "
        "count=%d deleted=%d by=%s",
        property_key, dry_run, result["count"], result["deleted"], admin.email,
    )
    return {"ok": True, **result}


# ─────────────────────────────────────────────────────────────────────────────
# Form field mappings
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mappings")
def api_list_mappings(
    provider: Optional[str] = Query(None),
    form_id:  Optional[str] = Query(None),
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    return {"items": fm_repo.list_form_field_mappings(provider=provider, form_id=form_id)}


@router.post("/mappings")
def api_upsert_mapping(
    body: FormFieldMappingIn,
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    try:
        row = fm_repo.upsert_form_field_mapping(
            provider=body.provider,
            form_id=body.form_id,
            meta_field_name=body.meta_field_name,
            target_type=body.target_type,
            target_key=body.target_key,
            created_by=admin.email,
        )
    except FieldMappingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return row


@router.delete("/mappings/{mapping_id}")
def api_delete_mapping(
    mapping_id: int,
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    deleted = fm_repo.delete_form_field_mapping(mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mapping no encontrado.")
    return {"ok": True, "id": mapping_id}


# ─────────────────────────────────────────────────────────────────────────────
# Detección de campos sin mapear
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/unmapped")
def api_unmapped_fields(
    provider:  str = Query("meta"),
    days_back: int = Query(90, ge=1, le=365),
    limit:     int = Query(200, ge=1, le=1000),
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Campos detectados en raw_field_data que no tienen regla aún.

    Agrupados por (form_id, meta_field_name) con sample_value + count.
    Esta es la "to-do list" del admin de marketing.
    """
    items = fm_repo.detect_unmapped_fields(provider=provider, days_back=days_back, limit=limit)
    return {"items": items, "total": len(items)}


# ─────────────────────────────────────────────────────────────────────────────
# Backfill: reprocesa leads existentes bajo las reglas actuales (async)
# ─────────────────────────────────────────────────────────────────────────────
# POST /backfill → 202 + job_id. El trabajo corre en BackgroundTask.
# GET  /backfill/status/{job_id} → estado + totales (polling desde la UI).
# Concurrencia: pg_try_advisory_xact_lock evita dos backfills simultáneos.
# Persistencia: crm.field_mappings_backfill_jobs (multi-worker safe).
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/backfill", status_code=status.HTTP_202_ACCEPTED)
def api_backfill(
    background_tasks: BackgroundTasks,
    provider:  str = Query("meta"),
    days_back: int = Query(180, ge=1, le=730),
    limit:     int = Query(5000, ge=1, le=20000),
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Lanza un reproceso en background y devuelve el job_id para polling."""
    params = {"provider": provider, "days_back": days_back, "limit": limit}
    job_id = fm_repo.create_backfill_job(triggered_by=admin.email, params=params)
    logger.info(
        "field_mappings.backfill job=%s triggered_by=%s params=%s",
        job_id, admin.email, params,
    )
    background_tasks.add_task(fm_repo.run_backfill_job, job_id, params)
    return {
        "ok": True,
        "job_id": job_id,
        "status": "pending",
        "poll_url": f"/api/integrations/field-mappings/backfill/status/{job_id}",
    }


@router.get("/backfill/status/{job_id}")
def api_backfill_status(
    job_id: str,
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    job = fm_repo.get_backfill_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return job


@router.get("/backfill/recent")
def api_backfill_recent(
    limit: int = Query(10, ge=1, le=50),
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    """Últimos N jobs — útil para ver si alguien ya corrió uno hoy."""
    return {"items": fm_repo.list_recent_backfill_jobs(limit=limit)}

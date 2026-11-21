"""
Router de auditoria — escribe y consulta `crm.audit_lead_access`.

Endpoints:
  POST /api/audit/copy-attempt  — recibe reportes del frontend cuando se
                                  bloquea un Ctrl+C/Ctrl+X/click derecho.
  GET  /api/audit/lead-access   — consulta del log (solo admin). Para
                                  investigaciones: quien exporto que, cuando.

Notas:
  - El POST es best-effort: aunque falle por DB caida, retornamos 204 para
    no afectar al frontend. El watermark y el bloqueo del copy ya hicieron
    su trabajo; el log es solo evidencia forense.
  - El GET expone filtros conservadores (limit=500 max) para evitar
    downloads masivos del propio log.
"""
from __future__ import annotations

from typing import Optional
import logging

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user, require_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.services import audit_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["Audit"])


# ---------------------------------------------------------------------------
# POST /api/audit/copy-attempt
# ---------------------------------------------------------------------------

class CopyAttemptPayload(BaseModel):
    """Datos que envia el frontend cuando useCopyProtection bloquea un evento.

    - page   → 'leads' | 'asignacion' | otro identificador corto de pagina
    - action → 'copy' | 'cut' | 'contextmenu'
    """
    page: str = Field(..., max_length=32)
    action: str = Field(..., max_length=32)


@router.post("/copy-attempt", status_code=204)
def report_copy_attempt(
    payload: CopyAttemptPayload,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
):
    """Registra un intento de copia bloqueado por el frontend.

    Retorna 204 No Content incluso si el insert falla — el frontend ya no
    puede hacer nada con un error aqui, y romper la UX por un fallo de
    audit seria contraproducente.
    """
    audit_service.record_copy_attempt(
        user=current_user,
        page=payload.page,
        action_type=payload.action,
        request=request,
    )
    return None


# ---------------------------------------------------------------------------
# GET /api/audit/lead-access  — solo admin
# ---------------------------------------------------------------------------

@router.get("/lead-access")
def list_audit_log(
    user_id: Optional[str] = Query(None, description="Filtrar por usuario"),
    action: Optional[str] = Query(None, description="list|export|detail|copy_attempt"),
    fecha_desde: Optional[str] = Query(None, description="ISO date"),
    fecha_hasta: Optional[str] = Query(None, description="ISO date"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _current_user: TokenData = Depends(require_admin),
):
    """Consulta el log de auditoria (solo admin).

    Uso tipico:
      GET /api/audit/lead-access?action=export&fecha_desde=2026-04-01
      GET /api/audit/lead-access?user_id=<uuid>&limit=50
    """
    where: list[str] = ["1=1"]
    params: list = []

    if user_id:
        where.append("a.user_id = %s::uuid")
        params.append(user_id)
    if action:
        where.append("a.action = %s")
        params.append(action)
    if fecha_desde:
        where.append("a.created_at >= %s::date")
        params.append(fecha_desde)
    if fecha_hasta:
        # Inclusivo: "<= fecha_hasta 23:59" se implementa como "< dia siguiente"
        where.append("a.created_at < (%s::date + INTERVAL '1 day')")
        params.append(fecha_hasta)

    where_sql = " AND ".join(where)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    a.id,
                    a.user_id::text AS user_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                                              AS user_nombre,
                    u.email                   AS user_email,
                    a.action,
                    a.lead_count,
                    a.filters,
                    a.ip_address::text        AS ip_address,
                    a.user_agent,
                    a.created_at::text        AS created_at
                FROM crm.audit_lead_access a
                LEFT JOIN auth.users u ON u.id = a.user_id
                WHERE {where_sql}
                ORDER BY a.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.audit_lead_access a
                WHERE {where_sql}
                """,
                params,
            )
            total = cur.fetchone()["total"]

    return {"total": total, "items": rows}


# ---------------------------------------------------------------------------
# POST /api/audit/purge  — mantenimiento (solo admin)
# ---------------------------------------------------------------------------

@router.post("/purge")
def purge_old_logs(
    days: int = Query(90, ge=30, le=365),
    _current_user: TokenData = Depends(require_admin),
):
    """Elimina registros de auditoria mas viejos que N dias.

    Pensado para ejecutar manualmente o desde un cron (n8n, systemd timer).
    Retorna el numero de filas eliminadas. Minimo 30 dias (no permitimos
    borrar todo por accidente), maximo 365 (para poder limpiar logs muy
    viejos si la retencion aumenta).
    """
    from app.repositories import audit_repository
    deleted = audit_repository.purge_older_than(days)
    return {"deleted": deleted, "retention_days": days}

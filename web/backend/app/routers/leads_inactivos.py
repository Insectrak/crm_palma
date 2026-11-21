"""
Router exclusivo de administración para la gestión de leads inactivos / papelera.
Permite listar, buscar, filtrar por estado, reactivar (restaurar), cambiar estado
y eliminar definitivamente leads que fueron borrados lógicamente (activo = FALSE).
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, field_validator

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.services import audit_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads-inactivos", tags=["Leads Inactivos"])


class RestaurarLeadsRequest(BaseModel):
    ids: List[int]
    nuevo_estado_id: Optional[int] = None

    @field_validator("ids", mode="before")
    @classmethod
    def _validate_ids(cls, v):
        if isinstance(v, list):
            return [int(x) for x in v if str(x).isdigit()]
        return v


class CambiarEstadoRequest(BaseModel):
    estado_id: Optional[int] = None


class BulkCambiarEstadoRequest(BaseModel):
    ids: List[int]
    estado_id: Optional[int] = None

    @field_validator("ids", mode="before")
    @classmethod
    def _validate_ids(cls, v):
        if isinstance(v, list):
            return [int(x) for x in v if str(x).isdigit()]
        return v


class EliminarPermanenteRequest(BaseModel):
    ids: List[int]

    @field_validator("ids", mode="before")
    @classmethod
    def _validate_ids(cls, v):
        if isinstance(v, list):
            return [int(x) for x in v if str(x).isdigit()]
        return v


@router.get("")
def list_leads_inactivos(
    request: Request,
    search: Optional[str] = Query(None, description="Búsqueda por nombre, teléfono o email"),
    estado_id: Optional[int] = Query(None, description="ID del estado del lead"),
    subestado: Optional[str] = Query(None, description="Filtro por subestado / motivo / acción"),
    asesor_id: Optional[str] = Query(None, description="UUID del asesor asignado"),
    fuente_id: Optional[int] = Query(None, description="ID de la fuente del lead"),
    fecha_desde: Optional[str] = Query(None, description="Fecha de inactivación desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha de inactivación hasta (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: Optional[str] = Query("updated_at:desc", description="Campo y dirección de orden"),
    admin: TokenData = Depends(require_admin),
):
    """
    Lista todos los leads inactivos (activo = FALSE) con paginación y filtros.
    Exclusivo para administradores.
    """
    where_clauses = ["l.activo = FALSE"]
    params: list = []

    if estado_id is not None:
        where_clauses.append("l.estado_id = %s")
        params.append(estado_id)

    if subestado and subestado.strip():
        sub_val = subestado.strip()
        where_clauses.append(
            "("
            "l.motivo_perdida ILIKE %s OR "
            "l.motivo_perdida_otro ILIKE %s OR "
            "l.tipo_cierre ILIKE %s OR "
            "l.segunda_voz ILIKE %s OR "
            "l.accion_proxima_gestion ILIKE %s"
            ")"
        )
        p = f"%{sub_val}%"
        params.extend([p, p, p, p, p])

    if fuente_id is not None:
        where_clauses.append("l.fuente_id = %s")
        params.append(fuente_id)

    if asesor_id:
        where_clauses.append("l.asesor_id = %s::uuid")
        params.append(asesor_id)

    if fecha_desde:
        where_clauses.append("l.updated_at >= %s::date")
        params.append(fecha_desde)

    if fecha_hasta:
        where_clauses.append("l.updated_at <= (%s::date + INTERVAL '1 day')")
        params.append(fecha_hasta)

    if search and search.strip():
        q = f"%{search.strip()}%"
        where_clauses.append(
            "("
            "l.nombres ILIKE %s OR "
            "l.apellidos ILIKE %s OR "
            "TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) ILIKE %s OR "
            "l.telefono ILIKE %s OR "
            "l.email ILIKE %s"
            ")"
        )
        params.extend([q, q, q, q, q])

    where_sql = " AND ".join(where_clauses)

    # Orden seguro
    sort_field_map = {
        "updated_at": "l.updated_at",
        "created_at": "l.created_at",
        "nombre": "nombre_completo",
        "telefono": "l.telefono",
        "id": "l.id",
    }
    order_by = "l.updated_at DESC NULLS LAST, l.id DESC"
    if sort:
        parts = sort.split(":")
        field = parts[0].strip().lower()
        direction = "ASC" if len(parts) > 1 and parts[1].strip().lower() == "asc" else "DESC"
        if field in sort_field_map:
            order_by = f"{sort_field_map[field]} {direction} NULLS LAST, l.id DESC"

    query_params = params + [limit, offset]

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query principal
            cur.execute(
                f"""
                SELECT
                    l.id,
                    l.nombres,
                    l.apellidos,
                    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
                    l.telefono,
                    l.email,
                    l.estado_id,
                    e.nombre AS estado_nombre,
                    e.color_hex AS estado_color,
                    l.fuente_id,
                    f.nombre AS fuente_nombre,
                    l.campana,
                    l.asesor_id,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                    u.email AS asesor_email,
                    l.created_at AS fecha_ingreso,
                    l.updated_at AS fecha_inactivacion,
                    l.observaciones,
                    l.fecha_proxima_gestion::text AS fecha_proxima_gestion,
                    l.accion_proxima_gestion,
                    l.motivo_perdida,
                    l.motivo_perdida_otro,
                    l.tipo_cierre,
                    l.segunda_voz
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                LEFT JOIN auth.users u ON u.id = l.asesor_id
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                query_params,
            )
            rows = cur.fetchall()

            # Query count
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.leads l
                WHERE {where_sql}
                """,
                params,
            )
            total = cur.fetchone()["total"]

    return {"total": total, "items": rows}


@router.get("/stats")
def get_leads_inactivos_stats(
    admin: TokenData = Depends(require_admin),
):
    """
    Estadísticas resumidas de leads inactivos para KPIs y filtros en frontend.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Total inactivos
            cur.execute("SELECT COUNT(*) AS total FROM crm.leads WHERE activo = FALSE")
            total = cur.fetchone()["total"]

            # Inactivados últimos 30 días
            cur.execute(
                """
                SELECT COUNT(*) AS total_recientes
                FROM crm.leads
                WHERE activo = FALSE AND updated_at >= NOW() - INTERVAL '30 days'
                """
            )
            recientes = cur.fetchone()["total_recientes"]

            # Desglose por estado
            cur.execute(
                """
                SELECT
                    l.estado_id,
                    COALESCE(e.nombre, 'Sin estado') AS estado_nombre,
                    COALESCE(e.color_hex, '#6b7280') AS estado_color,
                    COUNT(*) AS count
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = FALSE
                GROUP BY l.estado_id, e.nombre, e.color_hex
                ORDER BY count DESC
                """
            )
            estados_breakdown = cur.fetchall()

    return {
        "total": total,
        "total_recientes": recientes,
        "por_estado": estados_breakdown,
    }


@router.post("/restaurar", status_code=200)
def restaurar_leads(
    data: RestaurarLeadsRequest,
    admin: TokenData = Depends(require_admin),
):
    """
    Restaura uno o varios leads marcándolos como activos (activo = TRUE).
    Opcionalmente permite asignarles un nuevo estado en el proceso.
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail="Debes proporcionar al menos un ID de lead.")

    with get_db() as conn:
        with conn.cursor() as cur:
            if data.nuevo_estado_id is not None:
                # Verificar que el estado destino exista
                cur.execute("SELECT id FROM crm.estados_lead WHERE id = %s", (data.nuevo_estado_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="El nuevo estado especificado no existe.")

                cur.execute(
                    """
                    UPDATE crm.leads
                    SET activo = TRUE, estado_id = %s, updated_at = NOW()
                    WHERE id = ANY(%s) AND activo = FALSE
                    RETURNING id
                    """,
                    (data.nuevo_estado_id, data.ids),
                )
            else:
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET activo = TRUE, updated_at = NOW()
                    WHERE id = ANY(%s) AND activo = FALSE
                    RETURNING id
                    """,
                    (data.ids,),
                )
            restaurados = [r[0] for r in cur.fetchall()]
        conn.commit()

    return {
        "message": f"Se restauraron {len(restaurados)} lead(s) exitosamente.",
        "restaurados": len(restaurados),
        "ids": restaurados,
    }


@router.patch("/{lead_id}/estado", status_code=200)
def cambiar_estado_lead_inactivo(
    lead_id: int,
    data: CambiarEstadoRequest,
    admin: TokenData = Depends(require_admin),
):
    """
    Cambia el estado de un lead inactivo directamente sin reactivarlo.
    Útil para desvincular estados que se desean borrar de la configuración.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if data.estado_id is not None:
                cur.execute("SELECT id, nombre FROM crm.estados_lead WHERE id = %s", (data.estado_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Estado no encontrado.")

            cur.execute(
                """
                UPDATE crm.leads
                SET estado_id = %s, updated_at = NOW()
                WHERE id = %s AND activo = FALSE
                RETURNING id, estado_id
                """,
                (data.estado_id, lead_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Lead inactivo no encontrado.")
        conn.commit()

    return {"message": "Estado actualizado", "lead_id": lead_id, "estado_id": data.estado_id}


@router.patch("/bulk-estado", status_code=200)
def bulk_cambiar_estado_leads_inactivos(
    data: BulkCambiarEstadoRequest,
    admin: TokenData = Depends(require_admin),
):
    """
    Cambia el estado de múltiples leads inactivos en bloque.
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail="Debes proporcionar al menos un ID de lead.")

    with get_db() as conn:
        with conn.cursor() as cur:
            if data.estado_id is not None:
                cur.execute("SELECT id FROM crm.estados_lead WHERE id = %s", (data.estado_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Estado no encontrado.")

            cur.execute(
                """
                UPDATE crm.leads
                SET estado_id = %s, updated_at = NOW()
                WHERE id = ANY(%s) AND activo = FALSE
                RETURNING id
                """,
                (data.estado_id, data.ids),
            )
            actualizados = [r[0] for r in cur.fetchall()]
        conn.commit()

    return {
        "message": f"Se actualizó el estado de {len(actualizados)} lead(s) inactivo(s).",
        "actualizados": len(actualizados),
        "ids": actualizados,
    }


@router.delete("/permanente", status_code=200)
def eliminar_leads_permanente(
    data: EliminarPermanenteRequest,
    admin: TokenData = Depends(require_admin),
):
    """
    Eliminación física definitiva (hard-delete) de leads inactivos.
    Esta acción borra permanentemente los registros seleccionados y sus dependencias.
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail="Debes proporcionar al menos un ID de lead.")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Primero limpiar registros relacionados con FK o dependencias
            cur.execute("DELETE FROM crm.contactos WHERE lead_id = ANY(%s)", (data.ids,))
            cur.execute("DELETE FROM crm.asignaciones_log WHERE lead_id = ANY(%s)", (data.ids,))
            cur.execute("DELETE FROM crm.llamadas WHERE lead_id = ANY(%s)", (data.ids,))
            cur.execute("DELETE FROM crm.lead_properties WHERE lead_id = ANY(%s)", (data.ids,))
            cur.execute(
                """
                DELETE FROM crm.leads
                WHERE id = ANY(%s) AND activo = FALSE
                RETURNING id
                """,
                (data.ids,),
            )
            eliminados = [r[0] for r in cur.fetchall()]
        conn.commit()

    return {
        "message": f"Se eliminaron permanentemente {len(eliminados)} lead(s).",
        "eliminados": len(eliminados),
        "ids": eliminados,
    }

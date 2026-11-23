"""
reportes_especiales.py — Router de Reportería Especial del CRM.

Primer Desarrollo:
  Consulta del total de leads recibidos por supervisor de forma histórica,
  garantizando que se contabilicen incluso aquellos que fueron movidos a otros
  destinos (Bolsa TMK, reasignados a otros asesores de su equipo o de otros equipos),
  desglosando con precisión:
    1. La Fuente (Meta/Facebook, TikTok, WhatsApp, Web, Formulario, etc.)
    2. El Origen (Campaña, Formulario, Anuncio, Proyecto, etc.)
    3. ¿En dónde están ahora? (Bolsa TMK, en su equipo, reasignados a otros, en cola, inactivos).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from app.auth.jwt import get_current_user
from app.auth.permissions import can_view_all_data
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reportes-especiales", tags=["Reportería Especial"])


def _check_access(current_user: TokenData) -> None:
    """Verifica que el usuario sea Admin."""
    if current_user.role != Role.ADMIN and not can_view_all_data(current_user, "reportes"):
        raise HTTPException(status_code=403, detail="Acceso denegado. Este reporte es exclusivo para administradores.")


def _get_allowed_supervisores_ids(cur, current_user: TokenData) -> list[str]:
    """Retorna la lista de todos los supervisores para consulta del administrador."""
    cur.execute(
        """
        SELECT id::text
        FROM auth.users
        WHERE role = 'supervisor'
        ORDER BY first_name, last_name
        """
    )
    return [r["id"] for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Catálogo de Supervisores Disponibles
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/supervisores")
def get_supervisores_disponibles(current_user: TokenData = Depends(get_current_user)):
    """Retorna la lista de supervisores a los que el usuario tiene permiso de consulta."""
    _check_access(current_user)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            allowed_ids = _get_allowed_supervisores_ids(cur, current_user)
            if not allowed_ids:
                return []

            cur.execute(
                """
                SELECT
                    u.id::text,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS nombre,
                    u.email,
                    u.is_active,
                    u.supervisor_jefe_id::text AS supervisor_jefe_id,
                    (SELECT COUNT(*)::int FROM crm.equipos eq WHERE eq.supervisor_id = u.id AND eq.activo = TRUE) AS asesores_activos
                FROM auth.users u
                WHERE u.id = ANY(%s::uuid[])
                ORDER BY u.is_active DESC, u.first_name, u.last_name
                """,
                (allowed_ids,),
            )
            return cur.fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Resumen y KPIs de Leads Históricos por Supervisor
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/leads-historicos-supervisor/resumen")
def get_resumen_leads_historicos_supervisor(
    supervisor_id: Optional[str] = Query(None, description="UUID del supervisor a consultar"),
    fecha_desde: Optional[str] = Query(None, description="YYYY-MM-DD fecha ingreso lead"),
    fecha_hasta: Optional[str] = Query(None, description="YYYY-MM-DD fecha ingreso lead"),
    fuente_id: Optional[int] = Query(None, description="ID de fuente original"),
    origen: Optional[str] = Query(None, description="Campaña / Origen"),
    ubicacion_actual: Optional[str] = Query(None, description="bolsa_tmk | mismo_equipo | otro_asesor | en_cola | inactivo"),
    estado_id: Optional[int] = Query(None, description="Estado comercial actual"),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Retorna métricas consolidadas, KPIs, desglose por fuente original, origen/campaña,
    ubicación actual (Bolsa TMK, asesor de su equipo, otro equipo, cola, inactivo)
    y estado del pipeline para los leads recibidos históricamente por un supervisor.
    """
    _check_access(current_user)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            allowed_ids = _get_allowed_supervisores_ids(cur, current_user)
            if not allowed_ids:
                raise HTTPException(status_code=403, detail="No tienes supervisores asignados para consultar.")

            # Si no se pasó supervisor_id, usar el propio o el primero disponible
            target_sup_id = supervisor_id or (current_user.user_id if str(current_user.user_id) in allowed_ids else allowed_ids[0])
            if str(target_sup_id) not in allowed_ids:
                raise HTTPException(status_code=403, detail="No tienes permiso para consultar este supervisor.")

            # Información del supervisor
            cur.execute(
                """
                SELECT id::text, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre, email
                FROM auth.users WHERE id = %s::uuid
                """,
                (target_sup_id,),
            )
            sup_info = cur.fetchone()

            # Construcción de filtros dinámicos sobre crm.leads l
            filters_where = ["1=1"]
            filter_params = []

            if fecha_desde:
                filters_where.append("l.created_at >= %s::timestamptz")
                filter_params.append(f"{fecha_desde} 00:00:00")
            if fecha_hasta:
                filters_where.append("l.created_at <= %s::timestamptz")
                filter_params.append(f"{fecha_hasta} 23:59:59.999999")
            if fuente_id:
                filters_where.append("COALESCE(l.fuente_pre_reciclaje_id, l.fuente_id) = %s")
                filter_params.append(fuente_id)
            if origen:
                filters_where.append("l.campana ILIKE %s")
                filter_params.append(f"%{origen.strip()}%")
            if estado_id:
                filters_where.append("l.estado_id = %s")
                filter_params.append(estado_id)

            filtro_adicional_sql = " AND ".join(filters_where)

            # Query maestra que clasifica la ubicación actual de cada lead histórico
            base_sql = f"""
            WITH target_supervisor AS (
                SELECT %s::uuid AS sup_id
            ),
            team_advisors AS (
                SELECT eq.asesor_id
                FROM crm.equipos eq
                WHERE eq.supervisor_id = (SELECT sup_id FROM target_supervisor)
                UNION
                SELECT (SELECT sup_id FROM target_supervisor)
            ),
            supervisor_leads_ids AS (
                SELECT DISTINCT l.id
                FROM crm.leads l
                WHERE (
                    l.supervisor_id = (SELECT sup_id FROM target_supervisor)
                    OR l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                    OR (l.previous_asesor_id IS NOT NULL AND l.previous_asesor_id IN (SELECT asesor_id FROM team_advisors))
                    OR EXISTS (
                        SELECT 1 FROM crm.assignment_log al
                        WHERE al.lead_id = l.id AND al.supervisor_id = (SELECT sup_id FROM target_supervisor)
                    )
                    OR EXISTS (
                        SELECT 1 FROM crm.asignaciones_log alog
                        WHERE alog.lead_id = l.id
                          AND (alog.asesor_anterior IN (SELECT asesor_id FROM team_advisors)
                               OR alog.asesor_nuevo IN (SELECT asesor_id FROM team_advisors))
                    )
                )
            ),
            classified_leads AS (
                SELECT
                    l.id,
                    l.nombres,
                    l.apellidos,
                    l.telefono,
                    l.email,
                    l.created_at,
                    l.activo,
                    l.campana,
                    l.fuente_form_id,
                    l.anuncio,
                    l.conjunto,
                    l.proyecto,
                    l.estado_id,
                    e.nombre AS estado_nombre,
                    e.color_hex AS estado_color,
                    e.es_final AS estado_es_final,
                    -- Fuentes
                    l.fuente_id AS fuente_actual_id,
                    f_curr.nombre AS fuente_actual_nombre,
                    COALESCE(l.fuente_pre_reciclaje_id, l.fuente_id) AS fuente_original_id,
                    COALESCE(f_orig.nombre, f_curr.nombre, 'Sin fuente') AS fuente_original_nombre,
                    -- Asesor actual
                    l.asesor_id AS asesor_actual_id,
                    TRIM(COALESCE(a_curr.first_name, '') || ' ' || COALESCE(a_curr.last_name, '')) AS asesor_actual_nombre,
                    -- Supervisor actual
                    COALESCE(l.supervisor_id, eq_curr.supervisor_id) AS supervisor_actual_id,
                    TRIM(COALESCE(s_curr.first_name, '') || ' ' || COALESCE(s_curr.last_name, '')) AS supervisor_actual_nombre,
                    -- Reciclaje / Bolsa TMK flags
                    (l.es_reciclado = TRUE
                     OR LOWER(COALESCE(f_curr.nombre, '')) LIKE '%%bolsa tmk%%'
                     OR LOWER(COALESCE(e.nombre, '')) LIKE '%%bolsa tmk%%'
                     OR l.origen_reciclaje IS NOT NULL) AS es_bolsa_tmk,
                    l.origen_reciclaje,
                    l.fecha_reciclaje,
                    -- Clasificación de ubicación actual
                    CASE
                        WHEN l.activo = FALSE THEN 'inactivo'
                        WHEN (l.es_reciclado = TRUE
                              OR LOWER(COALESCE(f_curr.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR LOWER(COALESCE(e.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR l.origen_reciclaje IS NOT NULL) THEN 'bolsa_tmk'
                        WHEN l.asesor_id IS NULL THEN 'en_cola'
                        WHEN l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                             OR COALESCE(l.supervisor_id, eq_curr.supervisor_id) = (SELECT sup_id FROM target_supervisor) THEN 'mismo_equipo'
                        ELSE 'otro_asesor'
                    END AS tipo_ubicacion,
                    CASE
                        WHEN l.activo = FALSE THEN 'Inactivo / Papelera'
                        WHEN (l.es_reciclado = TRUE
                              OR LOWER(COALESCE(f_curr.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR LOWER(COALESCE(e.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR l.origen_reciclaje IS NOT NULL) THEN 'Bolsa TMK'
                        WHEN l.asesor_id IS NULL THEN 'En cola (Sin Asesor)'
                        WHEN l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                             OR COALESCE(l.supervisor_id, eq_curr.supervisor_id) = (SELECT sup_id FROM target_supervisor)
                             THEN 'En su equipo'
                        ELSE 'Reasignado a otro equipo'
                    END AS ubicacion_label
                FROM supervisor_leads_ids sli
                JOIN crm.leads l ON l.id = sli.id
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes f_curr ON f_curr.id = l.fuente_id
                LEFT JOIN crm.fuentes f_orig ON f_orig.id = l.fuente_pre_reciclaje_id
                LEFT JOIN auth.users a_curr ON a_curr.id = l.asesor_id
                LEFT JOIN crm.equipos eq_curr ON eq_curr.asesor_id = l.asesor_id AND eq_curr.activo = TRUE
                LEFT JOIN auth.users s_curr ON s_curr.id = COALESCE(l.supervisor_id, eq_curr.supervisor_id)
                WHERE {filtro_adicional_sql}
            )
            """

            # 1. Conteo global y KPIs
            kpi_sql = f"""
            {base_sql}
            SELECT
                COUNT(*)::int AS total_recibidos,
                COUNT(CASE WHEN tipo_ubicacion = 'mismo_equipo' THEN 1 END)::int AS en_equipo_actual,
                COUNT(CASE WHEN tipo_ubicacion = 'bolsa_tmk' THEN 1 END)::int AS en_bolsa_tmk,
                COUNT(CASE WHEN tipo_ubicacion = 'otro_asesor' THEN 1 END)::int AS reasignados_otro_equipo,
                COUNT(CASE WHEN tipo_ubicacion = 'en_cola' THEN 1 END)::int AS en_cola,
                COUNT(CASE WHEN tipo_ubicacion = 'inactivo' THEN 1 END)::int AS inactivos,
                COUNT(CASE WHEN LOWER(estado_nombre) LIKE '%%matr%%' OR LOWER(estado_nombre) LIKE '%%ganad%%' OR LOWER(estado_nombre) LIKE '%%cierr%%' OR LOWER(estado_nombre) LIKE '%%reserv%%' OR LOWER(estado_nombre) LIKE '%%separac%%' OR LOWER(estado_nombre) LIKE '%%venta concretad%%' THEN 1 END)::int AS matriculados,
                COUNT(CASE WHEN LOWER(estado_nombre) LIKE '%%perdid%%' OR LOWER(estado_nombre) LIKE '%%desist%%' OR LOWER(estado_nombre) LIKE '%%no interesad%%' OR LOWER(estado_nombre) LIKE '%%descart%%' OR LOWER(estado_nombre) LIKE '%%no califica%%' THEN 1 END)::int AS perdidos
            FROM classified_leads;
            """
            cur.execute(kpi_sql, [target_sup_id] + filter_params)
            kpis = cur.fetchone() or {
                "total_recibidos": 0,
                "en_equipo_actual": 0,
                "en_bolsa_tmk": 0,
                "reasignados_otro_equipo": 0,
                "en_cola": 0,
                "inactivos": 0,
                "matriculados": 0,
                "perdidos": 0,
            }

            total = kpis["total_recibidos"] or 0

            # 2. Desglose por Fuente Original
            fuentes_sql = f"""
            {base_sql}
            SELECT
                fuente_original_id AS id,
                fuente_original_nombre AS nombre,
                COUNT(*)::int AS total
            FROM classified_leads
            GROUP BY fuente_original_id, fuente_original_nombre
            ORDER BY total DESC;
            """
            cur.execute(fuentes_sql, [target_sup_id] + filter_params)
            fuentes_raw = cur.fetchall()
            desglose_fuentes = [
                {
                    "id": f["id"],
                    "nombre": f["nombre"],
                    "total": f["total"],
                    "porcentaje": round((f["total"] / total * 100), 1) if total > 0 else 0,
                }
                for f in fuentes_raw
            ]

            # 3. Desglose por Origen / Campaña
            origen_sql = f"""
            {base_sql}
            SELECT
                COALESCE(NULLIF(TRIM(campana), ''), NULLIF(TRIM(fuente_form_id), ''), NULLIF(TRIM(anuncio), ''), 'Orgánico / Sin campaña') AS origen_nombre,
                COUNT(*)::int AS total
            FROM classified_leads
            GROUP BY origen_nombre
            ORDER BY total DESC
            LIMIT 15;
            """
            cur.execute(origen_sql, [target_sup_id] + filter_params)
            origenes_raw = cur.fetchall()
            desglose_origenes = [
                {
                    "nombre": o["origen_nombre"],
                    "total": o["total"],
                    "porcentaje": round((o["total"] / total * 100), 1) if total > 0 else 0,
                }
                for o in origenes_raw
            ]

            # 4. Desglose de "¿En Dónde Están Ahora?"
            ubicacion_sql = f"""
            {base_sql}
            SELECT
                tipo_ubicacion,
                ubicacion_label,
                COUNT(*)::int AS total
            FROM classified_leads
            GROUP BY tipo_ubicacion, ubicacion_label
            ORDER BY total DESC;
            """
            cur.execute(ubicacion_sql, [target_sup_id] + filter_params)
            ubicaciones_raw = cur.fetchall()
            desglose_ubicacion = [
                {
                    "key": u["tipo_ubicacion"],
                    "label": u["ubicacion_label"],
                    "total": u["total"],
                    "porcentaje": round((u["total"] / total * 100), 1) if total > 0 else 0,
                }
                for u in ubicaciones_raw
            ]

            # 5. Desglose por Asesor Actual en su equipo (para ver quién los tiene ahora)
            asesores_equipo_sql = f"""
            {base_sql}
            SELECT
                asesor_actual_id AS id,
                COALESCE(NULLIF(asesor_actual_nombre, ''), 'Sin asesor asignado') AS nombre,
                COUNT(*)::int AS total
            FROM classified_leads
            WHERE tipo_ubicacion = 'mismo_equipo'
            GROUP BY asesor_actual_id, asesor_actual_nombre
            ORDER BY total DESC;
            """
            cur.execute(asesores_equipo_sql, [target_sup_id] + filter_params)
            asesores_equipo = cur.fetchall()

            # 6. Desglose por Estado Pipeline Actual
            estados_sql = f"""
            {base_sql}
            SELECT
                estado_id AS id,
                COALESCE(estado_nombre, 'Sin estado') AS nombre,
                COALESCE(estado_color, '#64748b') AS color_hex,
                COUNT(*)::int AS total
            FROM classified_leads
            GROUP BY estado_id, estado_nombre, estado_color
            ORDER BY total DESC;
            """
            cur.execute(estados_sql, [target_sup_id] + filter_params)
            estados_raw = cur.fetchall()
            desglose_estados = [
                {
                    "id": e["id"],
                    "nombre": e["nombre"],
                    "color_hex": e["color_hex"],
                    "total": e["total"],
                    "porcentaje": round((e["total"] / total * 100), 1) if total > 0 else 0,
                }
                for e in estados_raw
            ]

            return {
                "supervisor": sup_info,
                "kpis": kpis,
                "desglose_fuentes": desglose_fuentes,
                "desglose_origenes": desglose_origenes,
                "desglose_ubicacion": desglose_ubicacion,
                "asesores_equipo": asesores_equipo,
                "desglose_estados": desglose_estados,
            }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Comparativa Global entre Supervisores (Admin / Jefatura)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/leads-historicos-supervisor/comparativa")
def get_comparativa_supervisores(
    fecha_desde: Optional[str] = Query(None, description="YYYY-MM-DD fecha ingreso lead"),
    fecha_hasta: Optional[str] = Query(None, description="YYYY-MM-DD fecha ingreso lead"),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Retorna una tabla comparativa con todos los supervisores disponibles,
    mostrando el total de leads recibidos históricamente y su distribución actual.
    """
    _check_access(current_user)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            allowed_ids = _get_allowed_supervisores_ids(cur, current_user)
            if not allowed_ids:
                return []

            date_conds = []
            date_params = []
            if fecha_desde:
                date_conds.append("l.created_at >= %s::timestamptz")
                date_params.append(f"{fecha_desde} 00:00:00")
            if fecha_hasta:
                date_conds.append("l.created_at <= %s::timestamptz")
                date_params.append(f"{fecha_hasta} 23:59:59.999999")
            date_sql = f"AND {' AND '.join(date_conds)}" if date_conds else ""

            cur.execute(
                f"""
                WITH supervisores_base AS (
                    SELECT
                        u.id AS sup_id,
                        TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS nombre,
                        u.email,
                        u.is_active
                    FROM auth.users u
                    WHERE u.id = ANY(%s::uuid[])
                )
                SELECT
                    sb.sup_id::text AS id,
                    sb.nombre,
                    sb.email,
                    sb.is_active,
                    COALESCE(m.total_recibidos, 0)::int AS total_recibidos,
                    COALESCE(m.en_equipo_actual, 0)::int AS en_equipo,
                    COALESCE(m.en_bolsa_tmk, 0)::int AS en_bolsa_tmk,
                    COALESCE(m.reasignados_otro_equipo, 0)::int AS reasignados_otro_equipo,
                    COALESCE(m.en_cola, 0)::int AS en_cola,
                    COALESCE(m.matriculados, 0)::int AS matriculados
                FROM supervisores_base sb
                CROSS JOIN LATERAL (
                    WITH team_advisors AS (
                        SELECT eq.asesor_id
                        FROM crm.equipos eq
                        WHERE eq.supervisor_id = sb.sup_id
                        UNION
                        SELECT sb.sup_id
                    ),
                    supervisor_leads_ids AS (
                        SELECT DISTINCT l.id
                        FROM crm.leads l
                        WHERE (
                            l.supervisor_id = sb.sup_id
                            OR l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                            OR (l.previous_asesor_id IS NOT NULL AND l.previous_asesor_id IN (SELECT asesor_id FROM team_advisors))
                            OR EXISTS (
                                SELECT 1 FROM crm.assignment_log al
                                WHERE al.lead_id = l.id AND al.supervisor_id = sb.sup_id
                            )
                            OR EXISTS (
                                SELECT 1 FROM crm.asignaciones_log alog
                                WHERE alog.lead_id = l.id
                                  AND (alog.asesor_anterior IN (SELECT asesor_id FROM team_advisors)
                                       OR alog.asesor_nuevo IN (SELECT asesor_id FROM team_advisors))
                            )
                        )
                    ),
                    classified_leads AS (
                        SELECT
                            l.id,
                            l.activo,
                            e.nombre AS estado_nombre,
                            CASE
                                WHEN l.activo = FALSE THEN 'inactivo'
                                WHEN (l.es_reciclado = TRUE
                                      OR LOWER(COALESCE(f_curr.nombre, '')) LIKE '%%bolsa tmk%%'
                                      OR LOWER(COALESCE(e.nombre, '')) LIKE '%%bolsa tmk%%'
                                      OR l.origen_reciclaje IS NOT NULL) THEN 'bolsa_tmk'
                                WHEN l.asesor_id IS NULL THEN 'en_cola'
                                WHEN l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                                     OR COALESCE(l.supervisor_id, eq_curr.supervisor_id) = sb.sup_id THEN 'mismo_equipo'
                                ELSE 'otro_asesor'
                            END AS tipo_ubicacion
                        FROM supervisor_leads_ids sli
                        JOIN crm.leads l ON l.id = sli.id
                        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                        LEFT JOIN crm.fuentes f_curr ON f_curr.id = l.fuente_id
                        LEFT JOIN crm.equipos eq_curr ON eq_curr.asesor_id = l.asesor_id AND eq_curr.activo = TRUE
                        WHERE 1=1 {date_sql}
                    )
                    SELECT
                        COUNT(*)::int AS total_recibidos,
                        COUNT(CASE WHEN tipo_ubicacion = 'mismo_equipo' THEN 1 END)::int AS en_equipo_actual,
                        COUNT(CASE WHEN tipo_ubicacion = 'bolsa_tmk' THEN 1 END)::int AS en_bolsa_tmk,
                        COUNT(CASE WHEN tipo_ubicacion = 'otro_asesor' THEN 1 END)::int AS reasignados_otro_equipo,
                        COUNT(CASE WHEN tipo_ubicacion = 'en_cola' THEN 1 END)::int AS en_cola,
                        COUNT(CASE WHEN LOWER(estado_nombre) LIKE '%%matr%%' OR LOWER(estado_nombre) LIKE '%%ganad%%' OR LOWER(estado_nombre) LIKE '%%cierr%%' OR LOWER(estado_nombre) LIKE '%%reserv%%' OR LOWER(estado_nombre) LIKE '%%separac%%' OR LOWER(estado_nombre) LIKE '%%venta concretad%%' THEN 1 END)::int AS matriculados
                    FROM classified_leads
                ) m
                ORDER BY total_recibidos DESC, sb.nombre;
                """,
                [allowed_ids] + date_params,
            )
            return cur.fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Detalle de Leads Paginado con Ubicación Actual
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/leads-historicos-supervisor/detalle")
def get_detalle_leads_historicos_supervisor(
    supervisor_id: Optional[str] = Query(None, description="UUID del supervisor"),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    fuente_id: Optional[int] = Query(None),
    origen: Optional[str] = Query(None),
    ubicacion_actual: Optional[str] = Query(None, description="bolsa_tmk | mismo_equipo | otro_asesor | en_cola | inactivo"),
    estado_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Retorna el listado tabular paginado de leads históricos para el supervisor con búsqueda
    y trazabilidad completa de su ubicación actual.
    """
    _check_access(current_user)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            allowed_ids = _get_allowed_supervisores_ids(cur, current_user)
            target_sup_id = supervisor_id or (current_user.user_id if str(current_user.user_id) in allowed_ids else allowed_ids[0])
            if str(target_sup_id) not in allowed_ids:
                raise HTTPException(status_code=403, detail="No autorizado para este supervisor.")

            filters_where = ["1=1"]
            filter_params = []

            if fecha_desde:
                filters_where.append("l.created_at >= %s::timestamptz")
                filter_params.append(f"{fecha_desde} 00:00:00")
            if fecha_hasta:
                filters_where.append("l.created_at <= %s::timestamptz")
                filter_params.append(f"{fecha_hasta} 23:59:59.999999")
            if fuente_id:
                filters_where.append("COALESCE(l.fuente_pre_reciclaje_id, l.fuente_id) = %s")
                filter_params.append(fuente_id)
            if origen:
                filters_where.append("l.campana ILIKE %s")
                filter_params.append(f"%{origen.strip()}%")
            if estado_id:
                filters_where.append("l.estado_id = %s")
                filter_params.append(estado_id)
            if search:
                s = f"%{search.strip()}%"
                filters_where.append(
                    "(l.nombres ILIKE %s OR l.apellidos ILIKE %s OR l.telefono ILIKE %s OR l.email ILIKE %s OR l.campana ILIKE %s)"
                )
                filter_params.extend([s, s, s, s, s])

            filtro_adicional_sql = " AND ".join(filters_where)

            # Filtro adicional por tipo_ubicacion si se solicitó
            ubicacion_clause = ""
            if ubicacion_actual:
                ubicacion_clause = f"AND tipo_ubicacion = '{ubicacion_actual}'"

            offset = (page - 1) * limit

            query_sql = f"""
            WITH target_supervisor AS (
                SELECT %s::uuid AS sup_id
            ),
            team_advisors AS (
                SELECT eq.asesor_id
                FROM crm.equipos eq
                WHERE eq.supervisor_id = (SELECT sup_id FROM target_supervisor)
                UNION
                SELECT (SELECT sup_id FROM target_supervisor)
            ),
            supervisor_leads_ids AS (
                SELECT DISTINCT l.id
                FROM crm.leads l
                WHERE (
                    l.supervisor_id = (SELECT sup_id FROM target_supervisor)
                    OR l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                    OR (l.previous_asesor_id IS NOT NULL AND l.previous_asesor_id IN (SELECT asesor_id FROM team_advisors))
                    OR EXISTS (
                        SELECT 1 FROM crm.assignment_log al
                        WHERE al.lead_id = l.id AND al.supervisor_id = (SELECT sup_id FROM target_supervisor)
                    )
                    OR EXISTS (
                        SELECT 1 FROM crm.asignaciones_log alog
                        WHERE alog.lead_id = l.id
                          AND (alog.asesor_anterior IN (SELECT asesor_id FROM team_advisors)
                               OR alog.asesor_nuevo IN (SELECT asesor_id FROM team_advisors))
                    )
                )
            ),
            classified_leads AS (
                SELECT
                    l.id,
                    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
                    l.telefono,
                    l.email,
                    l.created_at AS fecha_ingreso,
                    l.activo,
                    l.campana,
                    l.fuente_form_id,
                    l.anuncio,
                    COALESCE(NULLIF(TRIM(l.campana), ''), NULLIF(TRIM(l.fuente_form_id), ''), NULLIF(TRIM(l.anuncio), ''), 'Orgánico / Sin campaña') AS origen_nombre,
                    -- Fuente
                    COALESCE(l.fuente_pre_reciclaje_id, l.fuente_id) AS fuente_original_id,
                    COALESCE(f_orig.nombre, f_curr.nombre, 'Sin fuente') AS fuente_original_nombre,
                    f_curr.nombre AS fuente_actual_nombre,
                    -- Estado
                    l.estado_id,
                    e.nombre AS estado_nombre,
                    COALESCE(e.color_hex, '#64748b') AS estado_color,
                    -- Asesor actual
                    l.asesor_id AS asesor_actual_id,
                    TRIM(COALESCE(a_curr.first_name, '') || ' ' || COALESCE(a_curr.last_name, '')) AS asesor_actual_nombre,
                    -- Supervisor actual
                    COALESCE(l.supervisor_id, eq_curr.supervisor_id) AS supervisor_actual_id,
                    TRIM(COALESCE(s_curr.first_name, '') || ' ' || COALESCE(s_curr.last_name, '')) AS supervisor_actual_nombre,
                    -- TMK
                    (l.es_reciclado = TRUE
                     OR LOWER(COALESCE(f_curr.nombre, '')) LIKE '%%bolsa tmk%%'
                     OR LOWER(COALESCE(e.nombre, '')) LIKE '%%bolsa tmk%%'
                     OR l.origen_reciclaje IS NOT NULL) AS es_bolsa_tmk,
                    l.origen_reciclaje,
                    l.fecha_reciclaje,
                    -- Clasificación
                    CASE
                        WHEN l.activo = FALSE THEN 'inactivo'
                        WHEN (l.es_reciclado = TRUE
                              OR LOWER(COALESCE(f_curr.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR LOWER(COALESCE(e.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR l.origen_reciclaje IS NOT NULL) THEN 'bolsa_tmk'
                        WHEN l.asesor_id IS NULL THEN 'en_cola'
                        WHEN l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                             OR COALESCE(l.supervisor_id, eq_curr.supervisor_id) = (SELECT sup_id FROM target_supervisor) THEN 'mismo_equipo'
                        ELSE 'otro_asesor'
                    END AS tipo_ubicacion,
                    CASE
                        WHEN l.activo = FALSE THEN 'Inactivo / Papelera'
                        WHEN (l.es_reciclado = TRUE
                              OR LOWER(COALESCE(f_curr.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR LOWER(COALESCE(e.nombre, '')) LIKE '%%bolsa tmk%%'
                              OR l.origen_reciclaje IS NOT NULL) THEN 'Bolsa TMK'
                        WHEN l.asesor_id IS NULL THEN 'En cola (Sin Asesor)'
                        WHEN l.asesor_id IN (SELECT asesor_id FROM team_advisors)
                             OR COALESCE(l.supervisor_id, eq_curr.supervisor_id) = (SELECT sup_id FROM target_supervisor)
                             THEN 'En su equipo'
                        ELSE 'Reasignado a otro equipo'
                    END AS ubicacion_label
                FROM supervisor_leads_ids sli
                JOIN crm.leads l ON l.id = sli.id
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes f_curr ON f_curr.id = l.fuente_id
                LEFT JOIN crm.fuentes f_orig ON f_orig.id = l.fuente_pre_reciclaje_id
                LEFT JOIN auth.users a_curr ON a_curr.id = l.asesor_id
                LEFT JOIN crm.equipos eq_curr ON eq_curr.asesor_id = l.asesor_id AND eq_curr.activo = TRUE
                LEFT JOIN auth.users s_curr ON s_curr.id = COALESCE(l.supervisor_id, eq_curr.supervisor_id)
                WHERE {filtro_adicional_sql}
            )
            """

            count_sql = f"{query_sql} SELECT COUNT(*)::int AS total FROM classified_leads WHERE 1=1 {ubicacion_clause};"
            cur.execute(count_sql, [target_sup_id] + filter_params)
            total_count = cur.fetchone()["total"]

            data_sql = f"""
            {query_sql}
            SELECT * FROM classified_leads
            WHERE 1=1 {ubicacion_clause}
            ORDER BY fecha_ingreso DESC
            LIMIT %s OFFSET %s;
            """
            cur.execute(data_sql, [target_sup_id] + filter_params + [limit, offset])
            items = cur.fetchall()

            return {
                "items": items,
                "total": total_count,
                "page": page,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
            }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Exportación a CSV
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/leads-historicos-supervisor/exportar")
def exportar_leads_historicos_supervisor(
    supervisor_id: Optional[str] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    fuente_id: Optional[int] = Query(None),
    origen: Optional[str] = Query(None),
    ubicacion_actual: Optional[str] = Query(None),
    estado_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """Genera y descarga un archivo CSV con el detalle de los leads filtrados."""
    _check_access(current_user)

    # Obtenemos los leads sin paginar (con límite razonable de seguridad de 20,000 filas)
    detalle_res = get_detalle_leads_historicos_supervisor(
        supervisor_id=supervisor_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        fuente_id=fuente_id,
        origen=origen,
        ubicacion_actual=ubicacion_actual,
        estado_id=estado_id,
        search=search,
        page=1,
        limit=20000,
        current_user=current_user,
    )

    items = detalle_res.get("items", [])

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow([
        "ID Lead",
        "Nombre Completo",
        "Teléfono",
        "Email",
        "Fecha Ingreso",
        "Fuente Original",
        "Fuente Actual",
        "Origen / Campaña",
        "Ubicación Actual",
        "Asesor Actual",
        "Supervisor Actual",
        "Estado Actual",
        "Bolsa TMK",
        "Criterio Reciclaje",
        "Activo",
    ])

    for row in items:
        writer.writerow([
            row["id"],
            row["nombre_completo"],
            row["telefono"] or "",
            row["email"] or "",
            row["fecha_ingreso"].strftime("%Y-%m-%d %H:%M") if row["fecha_ingreso"] else "",
            row["fuente_original_nombre"],
            row["fuente_actual_nombre"],
            row["origen_nombre"],
            row["ubicacion_label"],
            row["asesor_actual_nombre"] or "Sin asesor",
            row["supervisor_actual_nombre"] or "Sin supervisor",
            row["estado_nombre"] or "",
            "Sí" if row["es_bolsa_tmk"] else "No",
            row["origen_reciclaje"] or "",
            "Sí" if row["activo"] else "No (Papelera)",
        ])

    output.seek(0)
    filename = f"leads_historicos_supervisor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

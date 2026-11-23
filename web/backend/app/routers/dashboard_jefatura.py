"""
dashboard_jefatura.py — Router de métricas unificadas y jerárquicas para Jefatura y Supervisores.

Métricas contempladas (diarias, semanales, mensuales o personalizadas):
  - Leads nuevos
  - SLA: gestionados en <= 15 min vs sin gestión en > 15 min
  - Seguimientos del día y seguimientos vencidos (por asesor)
  - Citas del día y atendidas
  - COD (Cierres de Operación / Compromiso)
  - Matrículas y Matrículas verificadas (con segunda voz)
  - Perdidos y desglose detallado por motivos de pérdida
  - Leads con más de 30 días sin avance
  - Filtros y jerarquías: Sede, Equipo, Supervisor y Asesor individual.
  - Gestión de permisos individuales para supervisores (controlado por admin).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from app.auth.jwt import get_current_user, require_admin, require_supervisor_or_admin
from app.auth.permissions import can_view_all_data
from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)
LIMA_TZ = ZoneInfo("America/Lima")

router = APIRouter(prefix="/api/dashboard/jefatura", tags=["Dashboard Jefatura"])


def _ensure_settings_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.app_settings (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )


def _get_supervisores_permitidos_ids(cur) -> list[str]:
    """Retorna la lista de UUIDs de supervisores autorizados a ver el panel."""
    _ensure_settings_table(cur)
    cur.execute("SELECT value FROM public.app_settings WHERE key = 'panel_jefatura_supervisores'")
    row = cur.fetchone()
    if not row or not row.get("value"):
        return []
    val = row["value"]
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, dict) and "supervisores_ids" in val:
        return [str(x) for x in val["supervisores_ids"]]
    return []


def _parse_period_dates(periodo: str, start_date_str: Optional[str], end_date_str: Optional[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    """Calcula rango de fechas [start, end] en timezone Lima según el período."""
    now = datetime.now(LIMA_TZ)
    today = now.date()

    if periodo == "dia":
        start_d = today
        end_d = today
    elif periodo == "semana":
        start_d = today - timedelta(days=today.weekday())  # Lunes de esta semana
        end_d = today
    elif periodo == "mes":
        start_d = today.replace(day=1)
        end_d = today
    elif periodo == "30dias":
        start_d = today - timedelta(days=30)
        end_d = today
    elif periodo == "custom" and start_date_str and end_date_str:
        start_d = date.fromisoformat(start_date_str)
        end_d = date.fromisoformat(end_date_str)
    elif periodo in ("todos", "historico"):
        return None, None
    else:
        # Default: mes actual
        start_d = today.replace(day=1)
        end_d = today

    start_dt = datetime.combine(start_d, datetime.min.time(), tzinfo=LIMA_TZ)
    end_dt = datetime.combine(end_d, datetime.max.time(), tzinfo=LIMA_TZ)
    return start_dt, end_dt


# ─── Endpoints de Permisos para Administradores ───────────────────────────

class PermisosSupervisoresRequest(BaseModel):
    supervisores_ids: list[str]


@router.get("/permisos")
def get_permisos_supervisores(current_user: TokenData = Depends(require_admin)):
    """Retorna lista de supervisores y su estado de autorización para el panel de jefatura."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            permitidos_ids = set(_get_supervisores_permitidos_ids(cur))

            cur.execute(
                """
                SELECT
                    u.id::text AS supervisor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre,
                    u.email,
                    u.is_active,
                    COUNT(DISTINCT eq.asesor_id) AS total_asesores_equipo
                FROM auth.users u
                LEFT JOIN crm.equipos eq ON eq.supervisor_id = u.id AND eq.activo = TRUE
                WHERE u.role = 'supervisor' AND u.is_active = TRUE
                GROUP BY u.id, u.first_name, u.last_name, u.email, u.is_active
                ORDER BY nombre ASC
                """
            )
            supervisores = cur.fetchall()

            result = []
            for s in supervisores:
                s_dict = dict(s)
                s_dict["permitido"] = s_dict["supervisor_id"] in permitidos_ids
                result.append(s_dict)

            return {
                "supervisores": result,
                "total_permitidos": len(permitidos_ids),
            }


@router.post("/permisos")
def save_permisos_supervisores(
    body: PermisosSupervisoresRequest,
    current_user: TokenData = Depends(require_admin),
):
    """Guarda la lista de supervisores autorizados a ver el panel."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_settings_table(cur)
            val_json = json.dumps({"supervisores_ids": body.supervisores_ids})
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('panel_jefatura_supervisores', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (val_json,),
            )
            conn.commit()

            logger.info("[Panel Jefatura] Permisos actualizados por admin %s: %d supervisores autorizados", current_user.user_id, len(body.supervisores_ids))
            return {
                "ok": True,
                "supervisores_ids": body.supervisores_ids,
                "message": f"Se autorizó a {len(body.supervisores_ids)} supervisores.",
            }


@router.get("/mi-acceso")
def get_mi_acceso_jefatura(current_user: TokenData = Depends(get_current_user)):
    """Verifica si el usuario actual tiene acceso al Panel de Jefatura."""
    if can_view_all_data(current_user, "dashboards"):
        return {"acceso": True, "motivo": "admin"}

    if current_user.role == "supervisor":
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                permitidos = _get_supervisores_permitidos_ids(cur)
                tiene_acceso = current_user.user_id in permitidos
                return {"acceso": tiene_acceso, "motivo": "supervisor_autorizado" if tiene_acceso else "supervisor_no_autorizado"}

    return {"acceso": False, "motivo": "rol_no_permitido"}


# ─── Endpoint Principal de Métricas del Dashboard ─────────────────────────

@router.get("/resumen")
def get_resumen_jefatura(
    periodo: str = Query("mes", pattern="^(dia|semana|mes|30dias|todos|historico|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sede_id: Optional[str] = None,
    supervisor_id: Optional[str] = None,
    asesor_id: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
):
    """Retorna todas las métricas consolidadas con desglose jerárquico y SLA."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar autorización
            if not can_view_all_data(current_user, "dashboards"):
                if current_user.role == "supervisor":
                    permitidos = _get_supervisores_permitidos_ids(cur)
                    if current_user.user_id not in permitidos:
                        raise HTTPException(status_code=403, detail="No tienes acceso al Panel de Jefatura. Solicita autorización al administrador.")
                else:
                    raise HTTPException(status_code=403, detail="Acceso denegado al Panel de Jefatura.")

            start_dt, end_dt = _parse_period_dates(periodo, start_date, end_date)

            where_conds = ["l.activo = TRUE"]
            params = []

            # Si es supervisor sin permiso global, acotar a su equipo o subordinados
            if not can_view_all_data(current_user, "dashboards") and current_user.role == "supervisor":
                where_conds.append(
                    """(
                        l.supervisor_id = %s::uuid
                        OR l.supervisor_id IN (SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE)
                        OR l.asesor_id IN (SELECT asesor_id FROM crm.equipos WHERE supervisor_id = %s::uuid AND activo = TRUE)
                    )"""
                )
                params.extend([current_user.user_id, current_user.user_id, current_user.user_id])

            # Filtros opcionales
            if sede_id:
                where_conds.append("l.sede_id = %s::uuid")
                params.append(sede_id)
            if supervisor_id:
                where_conds.append("COALESCE(l.supervisor_id, eq.supervisor_id) = %s::uuid")
                params.append(supervisor_id)
            if asesor_id:
                where_conds.append("l.asesor_id = %s::uuid")
                params.append(asesor_id)

            where_sql = " AND ".join(where_conds)

            # Condición de fecha de creación para Leads Nuevos y métricas en período
            if start_dt and end_dt:
                bl_date_filter_sql = "l.created_at >= %s AND l.created_at <= %s"
                leads_date_filter_sql = "l.created_at >= %s AND l.created_at <= %s"
                date_params = [start_dt, end_dt]
            else:
                bl_date_filter_sql = "TRUE"
                leads_date_filter_sql = "TRUE"
                date_params = []

            # Condición de seguimientos según período (incluye En negociacion / Visita a Proyecto de Palma)
            _seg_state_sql = "(estado_nombre ILIKE '%%seguim%%' OR TRANSLATE(LOWER(TRIM(estado_nombre)), 'áéíóúüñ', 'aeiouun') IN ('en negociacion', 'visita a proyecto'))"
            if periodo == "dia":
                seg_condition_sql = f"fecha_proxima_gestion::date = CURRENT_DATE OR (fecha_proxima_gestion IS NULL AND {_seg_state_sql})"
                seg_params = []
            elif start_dt and end_dt:
                seg_condition_sql = f"(fecha_proxima_gestion >= %s AND fecha_proxima_gestion <= %s) OR (fecha_proxima_gestion IS NULL AND {_seg_state_sql} AND en_periodo = TRUE)"
                seg_params = [start_dt, end_dt]
            else:
                seg_condition_sql = f"fecha_proxima_gestion IS NOT NULL OR {_seg_state_sql}"
                seg_params = []

            # Condición de citas según período
            if periodo == "dia":
                citas_date_filter_sql = "DATE(c.fecha_cita AT TIME ZONE 'America/Lima') = CURRENT_DATE"
                citas_date_params = []
            elif start_dt and end_dt:
                citas_date_filter_sql = "c.fecha_cita >= %s AND c.fecha_cita <= %s"
                citas_date_params = [start_dt, end_dt]
            else:
                citas_date_filter_sql = "TRUE"
                citas_date_params = []

            # ── 1. Resumen General ──────────────────────────────────────────
            sql_summary = f"""
            WITH todas_interacciones AS (
                SELECT lead_id, created_at FROM crm.contactos WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                UNION ALL
                SELECT lead_id, fecha_llamada AS created_at FROM crm.llamadas WHERE lead_id IS NOT NULL
            ),
            primer_contacto AS (
                SELECT lead_id, MIN(created_at) AS fecha_primer_contacto
                FROM todas_interacciones
                GROUP BY lead_id
            ),
            ultimo_contacto AS (
                SELECT lead_id, MAX(created_at) AS fecha_ultimo_contacto
                FROM todas_interacciones
                GROUP BY lead_id
            ),
            base_leads AS (
                SELECT
                    l.id,
                    l.created_at,
                    l.estado_id,
                    COALESCE(e.nombre, 'Sin Estado') AS estado_nombre,
                    l.asesor_id,
                    COALESCE(l.supervisor_id, eq.supervisor_id) AS supervisor_id,
                    l.sede_id,
                    l.sla_15m_cumplido,
                    l.motivo_perdida,
                    l.tipo_cierre,
                    l.segunda_voz,
                    l.fecha_proxima_gestion,
                    pc.fecha_primer_contacto,
                    uc.fecha_ultimo_contacto,
                    ({bl_date_filter_sql}) AS en_periodo
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                LEFT JOIN primer_contacto pc ON pc.lead_id = l.id
                LEFT JOIN ultimo_contacto uc ON uc.lead_id = l.id
                WHERE {where_sql}
            )
            SELECT
                -- Leads Nuevos en el período
                COUNT(*) FILTER (WHERE en_periodo = TRUE) AS leads_nuevos,

                -- SLA en el período: contactados en <= 15 min
                COUNT(*) FILTER (
                    WHERE en_periodo = TRUE
                      AND (
                          sla_15m_cumplido = TRUE
                          OR (fecha_primer_contacto IS NOT NULL AND fecha_primer_contacto <= created_at + INTERVAL '15 minutes')
                      )
                ) AS sla_gestionados_le_15m,

                -- SLA en el período: superaron 15 min sin contacto
                COUNT(*) FILTER (
                    WHERE en_periodo = TRUE
                      AND (
                          sla_15m_cumplido = FALSE
                          OR (fecha_primer_contacto IS NULL AND created_at <= NOW() - INTERVAL '15 minutes')
                          OR (fecha_primer_contacto IS NOT NULL AND fecha_primer_contacto > created_at + INTERVAL '15 minutes')
                      )
                ) AS sla_sin_gestion_gt_15m,

                -- Seguimientos programados
                COUNT(*) FILTER (
                    WHERE {seg_condition_sql}
                ) AS seguimientos_hoy,
                COUNT(*) FILTER (
                    WHERE fecha_proxima_gestion::date < CURRENT_DATE
                      AND {_seg_state_sql}
                ) AS seguimientos_vencidos,

                -- COD / Compromisos de Operación / Reservas en el período
                COUNT(*) FILTER (
                    WHERE en_periodo = TRUE
                      AND (
                          estado_nombre ILIKE '%%COD%%'
                       OR estado_nombre ILIKE '%%Compromiso%%'
                       OR estado_nombre ILIKE '%%Reserva%%'
                       OR estado_nombre ILIKE '%%Separac%%'
                      )
                ) AS cod_total,

                -- Ventas / Ganados en el período
                COUNT(*) FILTER (
                    WHERE en_periodo = TRUE
                      AND (
                          estado_nombre ILIKE '%%Matr%%'
                       OR estado_nombre ILIKE '%%Ganad%%'
                       OR estado_nombre ILIKE '%%Cierr%%'
                       OR estado_nombre ILIKE '%%Venta Concretad%%'
                      )
                ) AS matriculas_total,
                COUNT(*) FILTER (
                    WHERE en_periodo = TRUE
                      AND (
                          estado_nombre ILIKE '%%Matr%%'
                       OR estado_nombre ILIKE '%%Ganad%%'
                       OR estado_nombre ILIKE '%%Cierr%%'
                       OR estado_nombre ILIKE '%%Venta Concretad%%'
                      )
                      AND (
                          (segunda_voz IS NOT NULL AND TRIM(segunda_voz) != '')
                          OR tipo_cierre ILIKE '%%segunda voz%%'
                          OR tipo_cierre ILIKE '%%2da voz%%'
                          OR estado_nombre ILIKE '%%verificad%%'
                      )
                ) AS matriculas_verificadas,

                -- Perdidos / Descartados en el período
                COUNT(*) FILTER (
                    WHERE en_periodo = TRUE
                      AND (
                          estado_nombre ILIKE '%%Perdid%%'
                       OR estado_nombre ILIKE '%%Desist%%'
                       OR estado_nombre ILIKE '%%No inter%%'
                       OR estado_nombre ILIKE '%%Descart%%'
                      )
                ) AS perdidos_total,

                -- Estancados > 30 días sin avance (pipeline global)
                COUNT(*) FILTER (
                    WHERE estado_nombre NOT ILIKE '%%Matr%%'
                      AND estado_nombre NOT ILIKE '%%Ganad%%'
                      AND estado_nombre NOT ILIKE '%%Cierr%%'
                      AND estado_nombre NOT ILIKE '%%Venta Concretad%%'
                      AND estado_nombre NOT ILIKE '%%Perdid%%'
                      AND estado_nombre NOT ILIKE '%%Desist%%'
                      AND estado_nombre NOT ILIKE '%%No inter%%'
                      AND estado_nombre NOT ILIKE '%%Descart%%'
                      AND estado_nombre NOT ILIKE '%%Bolsa%%'
                      AND estado_nombre NOT ILIKE '%%Reciclaje%%'
                      AND COALESCE(fecha_ultimo_contacto, created_at) < NOW() - INTERVAL '30 days'
                ) AS estancados_30d
            FROM base_leads;
            """

            cur.execute(sql_summary, date_params + params + seg_params)
            summary_row = dict(cur.fetchone() or {})

            # ── 2. Desglose de Motivos de Pérdida ─────────────────────────────
            sql_motivos = f"""
            SELECT
                COALESCE(NULLIF(TRIM(l.motivo_perdida), ''), 'Sin motivo registrado') AS motivo,
                COUNT(*) AS total
            FROM crm.leads l
            LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
            LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
            WHERE {where_sql}
              AND {leads_date_filter_sql}
              AND (e.nombre ILIKE '%%Perdid%%' OR e.nombre ILIKE '%%Desist%%' OR e.nombre ILIKE '%%No inter%%' OR e.nombre ILIKE '%%Descart%%')
            GROUP BY 1
            ORDER BY total DESC
            LIMIT 8;
            """
            cur.execute(sql_motivos, params + date_params)
            motivos_perdida = [dict(r) for r in cur.fetchall()]

            # ── 3. Citas del Período y Atendidas (desde crm.contactos) ───────
            cur.execute("SAVEPOINT sp_citas_jefatura")
            citas_row = {"citas_hoy": 0, "citas_atendidas_hoy": 0}
            try:
                sql_citas = f"""
                SELECT
                    COUNT(*)::int AS citas_hoy,
                    COUNT(*) FILTER (
                        WHERE ce.codigo IN ('completada', 'asistio', 'realizada', 'atendida')
                    )::int AS citas_atendidas_hoy
                FROM crm.contactos c
                LEFT JOIN crm.leads l ON l.id = c.lead_id
                LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                WHERE c.fecha_cita IS NOT NULL
                  AND {citas_date_filter_sql}
                  AND {where_sql};
                """
                cur.execute(sql_citas, citas_date_params + params)
                citas_row = dict(cur.fetchone() or {"citas_hoy": 0, "citas_atendidas_hoy": 0})
                cur.execute("RELEASE SAVEPOINT sp_citas_jefatura")
            except Exception as e:
                logger.warning("[Dashboard Jefatura] Fallback citas: %s", e)
                cur.execute("ROLLBACK TO SAVEPOINT sp_citas_jefatura")

            # ── 4. Desglose por Asesor Individual (TODOS los asesores activos) ──
            _e_seg_sql = "(e.nombre ILIKE '%%seguim%%' OR TRANSLATE(LOWER(TRIM(e.nombre)), 'áéíóúüñ', 'aeiouun') IN ('en negociacion', 'visita a proyecto'))"
            if periodo == "dia":
                asesor_seg_filter_sql = f"l.fecha_proxima_gestion::date = CURRENT_DATE OR (l.fecha_proxima_gestion IS NULL AND {_e_seg_sql})"
                asesor_seg_params = []
            elif start_dt and end_dt:
                asesor_seg_filter_sql = f"(l.fecha_proxima_gestion >= %s AND l.fecha_proxima_gestion <= %s) OR (l.fecha_proxima_gestion IS NULL AND {_e_seg_sql} AND l.created_at >= %s AND l.created_at <= %s)"
                asesor_seg_params = [start_dt, end_dt, start_dt, end_dt]
            else:
                asesor_seg_filter_sql = f"l.fecha_proxima_gestion IS NOT NULL OR {_e_seg_sql}"
                asesor_seg_params = []

            sql_asesores = f"""
            SELECT
                u.id AS asesor_id,
                TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                u.email AS asesor_email,
                COUNT(l.id) FILTER (WHERE {leads_date_filter_sql}) AS leads_nuevos,
                COUNT(l.id) FILTER (
                    WHERE {leads_date_filter_sql}
                      AND (
                          l.sla_15m_cumplido = TRUE
                          OR EXISTS (
                              SELECT 1 FROM crm.contactos c
                              WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                                AND c.created_at <= l.created_at + INTERVAL '15 minutes'
                          )
                      )
                ) AS sla_cumplido_count,
                COUNT(l.id) FILTER (
                    WHERE {asesor_seg_filter_sql}
                ) AS seguimientos_hoy,
                COUNT(l.id) FILTER (
                    WHERE l.fecha_proxima_gestion::date < CURRENT_DATE
                      AND {_e_seg_sql}
                ) AS seguimientos_vencidos,
                COUNT(l.id) FILTER (
                    WHERE {leads_date_filter_sql}
                      AND (e.nombre ILIKE '%%Matr%%' OR e.nombre ILIKE '%%Ganad%%' OR e.nombre ILIKE '%%Cierr%%' OR e.nombre ILIKE '%%Venta Concretad%%')
                ) AS matriculas,
                COUNT(l.id) FILTER (
                    WHERE {leads_date_filter_sql}
                      AND (e.nombre ILIKE '%%Perdid%%' OR e.nombre ILIKE '%%Desist%%' OR e.nombre ILIKE '%%No inter%%' OR e.nombre ILIKE '%%Descart%%')
                ) AS perdidos
            FROM auth.users u
            LEFT JOIN crm.leads l ON l.asesor_id = u.id AND l.activo = TRUE
            LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
            WHERE u.role = 'asesor' AND u.is_active = TRUE
            GROUP BY u.id, u.first_name, u.last_name, u.email
            ORDER BY leads_nuevos DESC, matriculas DESC, asesor_nombre ASC;
            """
            cur.execute(sql_asesores, date_params + date_params + asesor_seg_params + date_params + date_params)
            kpis_asesores = [dict(r) for r in cur.fetchall()]

            # ── 5. Desglose por Sede ─────────────────────────────────────────
            cur.execute("SAVEPOINT sp_sedes_jefatura")
            sedes_breakdown = []
            try:
                sql_sedes = f"""
                SELECT
                    s.id AS sede_id,
                    s.nombre AS sede_nombre,
                    s.codigo AS sede_codigo,
                    s.color_hex,
                    COUNT(l.id) AS total_leads,
                    COUNT(l.id) FILTER (WHERE {leads_date_filter_sql}) AS leads_periodo,
                    COUNT(l.id) FILTER (
                        WHERE {leads_date_filter_sql}
                          AND (e.nombre ILIKE '%%Matr%%' OR e.nombre ILIKE '%%Ganad%%' OR e.nombre ILIKE '%%Cierr%%' OR e.nombre ILIKE '%%Venta Concretad%%')
                    ) AS matriculas
                FROM crm.sedes s
                LEFT JOIN crm.leads l ON l.sede_id = s.id AND l.activo = TRUE
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE s.activo = TRUE
                GROUP BY s.id, s.nombre, s.codigo, s.color_hex
                ORDER BY s.nombre ASC;
                """
                cur.execute(sql_sedes, date_params + date_params)
                sedes_breakdown = [dict(r) for r in cur.fetchall()]
                cur.execute("RELEASE SAVEPOINT sp_sedes_jefatura")
            except Exception as e:
                logger.warning("[Dashboard Jefatura] Fallback sedes: %s", e)
                cur.execute("ROLLBACK TO SAVEPOINT sp_sedes_jefatura")

            # ── 6. Desglose por Supervisor ───────────────────────────────────
            cur.execute("SAVEPOINT sp_supervisores_jefatura")
            supervisores_breakdown = []
            try:
                sql_supervisores = f"""
                SELECT
                    s.id AS supervisor_id,
                    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
                    s.email AS supervisor_email,
                    COUNT(DISTINCT eq.asesor_id) AS total_asesores,
                    COUNT(l.id) FILTER (WHERE {leads_date_filter_sql}) AS leads_periodo,
                    COUNT(l.id) FILTER (
                        WHERE {leads_date_filter_sql}
                          AND (e.nombre ILIKE '%%Matr%%' OR e.nombre ILIKE '%%Ganad%%' OR e.nombre ILIKE '%%Cierr%%' OR e.nombre ILIKE '%%Venta Concretad%%')
                    ) AS matriculas
                FROM auth.users s
                LEFT JOIN crm.equipos eq ON eq.supervisor_id = s.id AND eq.activo = TRUE
                LEFT JOIN crm.leads l ON (l.supervisor_id = s.id OR l.asesor_id = eq.asesor_id) AND l.activo = TRUE
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE s.role = 'supervisor' AND s.is_active = TRUE
                GROUP BY s.id, s.first_name, s.last_name, s.email
                ORDER BY supervisor_nombre ASC;
                """
                cur.execute(sql_supervisores, date_params + date_params)
                supervisores_breakdown = [dict(r) for r in cur.fetchall()]
                cur.execute("RELEASE SAVEPOINT sp_supervisores_jefatura")
            except Exception as e:
                logger.warning("[Dashboard Jefatura] Fallback supervisores: %s", e)
                cur.execute("ROLLBACK TO SAVEPOINT sp_supervisores_jefatura")

            # Cálculo de SLA %
            le_15 = summary_row.get("sla_gestionados_le_15m") or 0
            gt_15 = summary_row.get("sla_sin_gestion_gt_15m") or 0
            total_sla = le_15 + gt_15
            sla_pct = round((le_15 / total_sla) * 100.0, 1) if total_sla > 0 else 100.0

            return {
                "periodo": periodo,
                "rango": {
                    "start": start_dt.isoformat() if start_dt else None,
                    "end": end_dt.isoformat() if end_dt else None,
                },
                "metricas": {
                    "leads_nuevos": summary_row.get("leads_nuevos") or 0,
                    "sla": {
                        "gestionados_le_15m": le_15,
                        "sin_gestion_gt_15m": gt_15,
                        "cumplimiento_pct": sla_pct,
                    },
                    "seguimientos": {
                        "hoy": summary_row.get("seguimientos_hoy") or 0,
                        "vencidos": summary_row.get("seguimientos_vencidos") or 0,
                    },
                    "citas": {
                        "hoy": citas_row.get("citas_hoy") or 0,
                        "atendidas_hoy": citas_row.get("citas_atendidas_hoy") or 0,
                    },
                    "cod": summary_row.get("cod_total") or 0,
                    "matriculas": {
                        "total": summary_row.get("matriculas_total") or 0,
                        "verificadas": summary_row.get("matriculas_verificadas") or 0,
                    },
                    "perdidos": {
                        "total": summary_row.get("perdidos_total") or 0,
                        "desglose_motivos": motivos_perdida,
                    },
                    "estancados_30d": summary_row.get("estancados_30d") or 0,
                },
                "asesores": kpis_asesores,
                "sedes": sedes_breakdown,
                "supervisores": supervisores_breakdown,
            }

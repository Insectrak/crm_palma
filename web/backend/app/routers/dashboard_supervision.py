"""
dashboard_supervision.py — Router exclusivo para Administradores de Alta Dirección:
Dashboard de Supervisión y Control.

Funcionalidades:
1. Seguimiento de actividad comercial exhaustivo (tanto a nivel de equipo/supervisor como individual por asesor).
2. Visibilidad operativa inmediata:
   - Leads pendientes por atender (nuevos, sin gestión, críticos > 15m y > 2h).
   - Asesores sin actividad en el día o inactivos (> 2h).
   - Leads cruzados (duplicados entre asesores) o no gestionados (> 24h).
   - Avance diario y ritmo de llamadas telefónicas frente a meta comercial.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from app.auth.jwt import get_current_user
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db

logger = logging.getLogger(__name__)
LIMA_TZ = ZoneInfo("America/Lima")

router = APIRouter(prefix="/api/dashboard/supervision-control", tags=["Dashboard Supervisión y Control (Alta Dirección)"])


def _check_admin(current_user: TokenData) -> None:
    """Valida que el usuario sea estrictamente Admin."""
    if current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Acceso restringido: este módulo es de uso exclusivo para Administradores y Alta Dirección.",
        )


def _parse_period_range(
    periodo: str,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> tuple[Optional[datetime], Optional[datetime], int]:
    """Calcula inicio y fin en timezone de Lima según el período y la cantidad de días."""
    now = datetime.now(LIMA_TZ)
    today = now.date()

    if periodo in ("personalizado", "custom") and fecha_inicio and fecha_fin:
        try:
            start_d = date.fromisoformat(fecha_inicio)
            end_d = date.fromisoformat(fecha_fin)
            if start_d > end_d:
                start_d, end_d = end_d, start_d
        except ValueError:
            start_d = today
            end_d = today
    elif periodo == "hoy":
        start_d = today
        end_d = today
    elif periodo == "ayer":
        start_d = today - timedelta(days=1)
        end_d = today - timedelta(days=1)
    elif periodo == "semana":
        start_d = today - timedelta(days=today.weekday())  # Lunes
        end_d = today
    elif periodo == "mes":
        start_d = today.replace(day=1)
        end_d = today
    elif periodo == "30dias":
        start_d = today - timedelta(days=30)
        end_d = today
    else:  # default hoy
        start_d = today
        end_d = today

    start_dt = datetime.combine(start_d, datetime.min.time(), tzinfo=LIMA_TZ)
    end_dt = datetime.combine(end_d, datetime.max.time(), tzinfo=LIMA_TZ)
    dias_count = max((end_d - start_d).days + 1, 1)
    return start_dt, end_dt, dias_count


# Normalización de nombres de estado para clasificación agnóstica de acentos y mayúsculas
NORMALIZED_STATE_EXPR = "TRANSLATE(LOWER(TRIM(COALESCE(e.nombre, ''))), 'áéíóúüñ', 'aeiouun')"

# Estados excluidos de pendientes urgentes / alertas (terminales + números inválidos; sin '%' para evitar conflictos con psycopg2)
EXCLUDED_URGENT_STATE_SQL = f"""(
    COALESCE(e.es_final, FALSE) = TRUE
    OR {NORMALIZED_STATE_EXPR} ~ '(ganad|matricul|reserv|separac|venta concretad|cierr|inscrit|perdid|desist|descart|no interesad|equivocad|inexistent|errone|no existe|numero invalido|mal numero)'
)"""

EXCLUDED_INTERACTION_TYPES_SQL = "('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')"

CALL_MANUAL_TYPES_SQL = "('llamada', 'video llamada', 'videollamada')"
WHATSAPP_TYPE_SQL = "'whatsapp'"
CALL_OR_WA_TYPES_SQL = "('llamada', 'video llamada', 'videollamada', 'whatsapp')"


def _strict_contacto_call_wa_sql(alias: str = "c") -> str:
    """Filtra únicamente registros de llamada o WhatsApp reales (excluye notas, comentarios y citas/reprogramaciones)."""
    tipo_norm = f"TRANSLATE(LOWER(TRIM(COALESCE({alias}.tipo_contacto, ''))), 'áéíóúüñ', 'aeiouun')"
    return f"""(
        {tipo_norm} IN {CALL_OR_WA_TYPES_SQL}
        AND {alias}.fecha_cita IS NULL
        AND STRPOS(LOWER(COALESCE({alias}.resultado, '')), 'cita') = 0
    )"""

ESTADOS_GESTION_KEYS = (
    "no_contesta_123",
    "bolsa_reciclaje",
    "contactado",
    "oportunidad_futura",
    "en_seguimiento",
    "nuevas_citas",
)

ESTADOS_EXCLUIDOS_KEYS = (
    "nuevos",
    "equivocados_inexistentes",
    "matriculas",
    "perdidos",
    "citas_ya_existentes",
)


def _nota_sin_sufijos_es_cita_sql(expr: str) -> str:
    """Evalúa si una nota o valor de estado corresponde a Cita, ignorando sufijos como '(por Cita)' o '· Motivo: ...'."""
    norm_notas = f"TRANSLATE(LOWER(COALESCE({expr}, '')), 'áéíóúüñ', 'aeiouun')"
    sin_motivo = f"REGEXP_REPLACE({norm_notas}, '\\s*·\\s*.*$', '', 'g')"
    sin_origen = f"REGEXP_REPLACE({sin_motivo}, '\\s*\\(por [^)]*\\)\\s*', ' ', 'g')"
    return f"({sin_origen} ~ '(cita|agendad)')"


def _cambio_estado_cita_sql(alias: str) -> str:
    """Evalúa si una nota de cambio_estado corresponde al estado Cita, ignorando sufijos como '(por Cita)' o '· Motivo: ...'."""
    return _nota_sin_sufijos_es_cita_sql(f"{alias}.notas")


def _citas_ordenadas_cte_sql() -> str:
    """CTE que enumera cronológicamente todas las citas históricas de cada lead para identificar la primera cita."""
    cambio_cita_sql = _cambio_estado_cita_sql("c_prev")
    return f"""
        citas_ordenadas AS (
            SELECT
                c.id AS contacto_id,
                c.lead_id,
                c.asesor_id,
                c.created_at,
                COALESCE(ce.codigo, 'pendiente') AS cita_estado_codigo,
                ROW_NUMBER() OVER (
                    PARTITION BY c.lead_id
                    ORDER BY c.created_at ASC, c.id ASC
                ) AS cita_nro,
                EXISTS (
                    SELECT 1
                    FROM crm.contactos c_prev
                    WHERE c_prev.lead_id = c.lead_id
                      AND c_prev.tipo_contacto = 'cambio_estado'
                      AND c_prev.created_at < c.created_at
                      AND DATE(c_prev.created_at AT TIME ZONE 'America/Lima') < DATE(c.created_at AT TIME ZONE 'America/Lima')
                      AND {cambio_cita_sql}
                ) AS tuvo_estado_cita_dia_previo
            FROM crm.contactos c
            LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
            WHERE (
                c.fecha_cita IS NOT NULL
                OR STRPOS(LOWER(COALESCE(c.resultado, '')), 'cita') > 0
                OR LOWER(COALESCE(c.tipo_contacto, '')) = 'cita'
            )
        )
    """


def _lead_citas_resumen_cte_sql() -> str:
    """CTE que resume si cada lead obtuvo su primera cita en el período o tuvo cita previa/reprogramación. Requiere 3 params: (start_dt, end_dt, start_dt)."""
    return """
        lead_citas_resumen AS (
            SELECT
                co.lead_id,
                BOOL_OR(
                    co.created_at >= %s
                    AND co.created_at <= %s
                    AND co.cita_estado_codigo NOT IN ('cancelada', 'reprogramada')
                    AND co.cita_nro = 1
                    AND NOT co.tuvo_estado_cita_dia_previo
                ) AS es_primera_cita_periodo,
                BOOL_OR(
                    co.created_at < %s
                    OR co.cita_estado_codigo = 'reprogramada'
                    OR co.cita_nro > 1
                    OR co.tuvo_estado_cita_dia_previo
                ) AS tiene_cita_previa_o_reprog
            FROM citas_ordenadas co
            WHERE co.cita_estado_codigo <> 'cancelada'
            GROUP BY co.lead_id
        )
    """


def _clasificacion_operativa_case_sql(state_alias: str = "e", citas_alias: str = "lcr") -> str:
    """Clasifica cada lead activo de forma mutuamente excluyente según criterios de control operativo (incluidos vs excluidos)."""
    s = f"TRANSLATE(LOWER(TRIM(COALESCE({state_alias}.nombre, ''))), 'áéíóúüñ', 'aeiouun')"
    return f"""CASE
        WHEN {s} ~ '(equivocad|inexistent|errone|no existe|numero invalido|mal numero)' THEN 'equivocados_inexistentes'
        WHEN {s} ~ '(ganad|matricul|reserv|separac|venta concretad|cierr|inscrit)' THEN 'matriculas'
        WHEN {s} ~ '(perdid|desist|no interesad|descart)' THEN 'perdidos'
        WHEN COALESCE({citas_alias}.es_primera_cita_periodo, FALSE) = TRUE THEN 'nuevas_citas'
        WHEN {s} ~ '(cita|agendad|reprogram)' THEN 'citas_ya_existentes'
        WHEN ({s} = '' OR {s} ~ '^nuevo([[:space:]]|$)' OR {s} ~ '(sin gestionar|por contactar)') THEN 'nuevos'
        WHEN {s} ~ '(bolsa|reciclaje)' THEN 'bolsa_reciclaje'
        WHEN STRPOS({s}, 'no contesta') > 0 THEN 'no_contesta_123'
        WHEN {s} ~ 'contactad' THEN 'contactado'
        WHEN {s} ~ '(oportunidad|futura)' THEN 'oportunidad_futura'
        WHEN {s} ~ '(seguimiento|negociacion|calificad|visita)' THEN 'en_seguimiento'
        ELSE 'otros_excluidos'
    END"""


def _build_supervision_scope_filters(
    sede_id: Optional[str],
    supervisor_id: Optional[str],
    asesor_id: Optional[str],
) -> tuple[str, list]:
    """Construye la cláusula WHERE común para filtrar leads activos por sede, supervisor y asesor."""
    filters = ["l.activo = TRUE"]
    params: list = []
    if sede_id:
        filters.append("l.sede_id = %s::uuid")
        params.append(sede_id)
    if supervisor_id:
        filters.append("(l.supervisor_id = %s::uuid OR l.asesor_id = %s::uuid OR eq.supervisor_id = %s::uuid)")
        params.extend([supervisor_id, supervisor_id, supervisor_id])
    if asesor_id:
        filters.append("l.asesor_id = %s::uuid")
        params.append(asesor_id)
    return " AND ".join(filters), params


def _build_advisor_scope_filters(
    sede_id: Optional[str],
    supervisor_id: Optional[str],
    asesor_id: Optional[str],
) -> tuple[str, list]:
    """Construye la cláusula WHERE para filtrar asesores y supervisores activos según sede, supervisor y usuario."""
    filters = ["u.role IN ('asesor', 'supervisor')", "u.is_active = TRUE"]
    params: list = []
    if asesor_id:
        filters.append("u.id = %s::uuid")
        params.append(asesor_id)
    if supervisor_id:
        filters.append(
            "(u.id = %s::uuid OR EXISTS (SELECT 1 FROM crm.equipos eqf WHERE eqf.asesor_id = u.id AND eqf.supervisor_id = %s::uuid AND eqf.activo = TRUE))"
        )
        params.extend([supervisor_id, supervisor_id])
    if sede_id:
        filters.append(
            "EXISTS (SELECT 1 FROM crm.leads lsf WHERE lsf.asesor_id = u.id AND lsf.sede_id = %s::uuid AND lsf.activo = TRUE)"
        )
        params.append(sede_id)
    return " AND ".join(filters), params


def _build_llamadas_scope_filters(
    start_dt: datetime,
    end_dt: datetime,
    sede_id: Optional[str],
    supervisor_id: Optional[str],
    asesor_id: Optional[str],
) -> tuple[str, list]:
    """Construye WHERE y parámetros para filtrar llamadas en el período por sede, supervisor y asesor."""
    filters = ["ll.fecha_llamada >= %s", "ll.fecha_llamada <= %s"]
    params: list = [start_dt, end_dt]
    if asesor_id:
        filters.append("ll.asesor_id = %s::uuid")
        params.append(asesor_id)
    if supervisor_id:
        filters.append(
            "(ll.asesor_id = %s::uuid OR ll.asesor_id IN (SELECT asesor_id FROM crm.equipos WHERE supervisor_id = %s::uuid AND activo = TRUE))"
        )
        params.extend([supervisor_id, supervisor_id])
    if sede_id:
        filters.append(
            """(
                (ll.lead_id IS NOT NULL AND lll.sede_id = %s::uuid)
                OR (ll.lead_id IS NULL AND EXISTS (
                    SELECT 1 FROM crm.leads ls WHERE ls.asesor_id = ll.asesor_id AND ls.sede_id = %s::uuid AND ls.activo = TRUE
                ))
            )"""
        )
        params.extend([sede_id, sede_id])
    return " AND ".join(filters), params


def _build_contactos_scope_filters(
    start_dt: datetime,
    end_dt: datetime,
    sede_id: Optional[str],
    supervisor_id: Optional[str],
    asesor_id: Optional[str],
) -> tuple[str, list]:
    """Construye WHERE y parámetros para filtrar únicamente llamadas manuales y WhatsApp reales en el período."""
    filters = [
        "c.created_at >= %s",
        "c.created_at <= %s",
        _strict_contacto_call_wa_sql("c"),
        "c.lead_id IS NOT NULL",
        "lc_s.activo = TRUE",
    ]
    params: list = [start_dt, end_dt]
    if sede_id:
        filters.append("lc_s.sede_id = %s::uuid")
        params.append(sede_id)
    if supervisor_id:
        filters.append(
            "(lc_s.supervisor_id = %s::uuid OR COALESCE(c.asesor_id, lc_s.asesor_id) = %s::uuid OR eq_cs.supervisor_id = %s::uuid)"
        )
        params.extend([supervisor_id, supervisor_id, supervisor_id])
    if asesor_id:
        filters.append("COALESCE(c.asesor_id, lc_s.asesor_id) = %s::uuid")
        params.append(asesor_id)
    return " AND ".join(filters), params


def _classify_advisor_activity(
    llamadas_cant: int,
    contactos_cant: int,
    minutos_inactivo: Optional[int],
) -> tuple[str, bool]:
    """Clasifica el estado operativo de un asesor según sus gestiones en el período e inactividad."""
    gestiones = llamadas_cant + contactos_cant
    if gestiones > 0:
        return "activo", False
    alerta = minutos_inactivo is None or minutos_inactivo > 120
    return "sin_actividad", alerta


@router.get("/resumen")
def get_resumen_supervision_control(
    periodo: str = Query("hoy", pattern="^(hoy|ayer|semana|mes|30dias|personalizado|custom)$"),
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    sede_id: Optional[str] = None,
    supervisor_id: Optional[str] = None,
    asesor_id: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
):
    """
    Retorna la visión consolidada y detallada de supervisión y control operativo
    para la Alta Dirección.
    """
    _check_admin(current_user)
    start_dt, end_dt, dias_count = _parse_period_range(periodo, fecha_inicio, fecha_fin)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            lead_where, lead_params = _build_supervision_scope_filters(sede_id, supervisor_id, asesor_id)
            advisor_where, advisor_params = _build_advisor_scope_filters(sede_id, supervisor_id, asesor_id)
            llamadas_where_sql, llamadas_params = _build_llamadas_scope_filters(
                start_dt, end_dt, sede_id, supervisor_id, asesor_id
            )
            contactos_where_sql, contactos_params = _build_contactos_scope_filters(
                start_dt, end_dt, sede_id, supervisor_id, asesor_id
            )

            # ─────────────────────────────────────────────────────────────────
            # 1. Total de asesores activos en el alcance seleccionado
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                f"""
                SELECT
                    u.id::text AS asesor_id,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS nombre,
                    u.email,
                    u.role AS rol,
                    u.is_active,
                    COALESCE(s_lead.sede_nombre, 'Principal') AS sede_nombre,
                    s_lead.sede_id::text AS sede_id,
                    sup.id::text AS supervisor_id,
                    TRIM(COALESCE(sup.first_name, '') || ' ' || COALESCE(sup.last_name, '')) AS supervisor_nombre
                FROM auth.users u
                LEFT JOIN crm.equipos eq ON eq.asesor_id = u.id AND eq.activo = TRUE
                LEFT JOIN auth.users sup ON sup.id = eq.supervisor_id
                LEFT JOIN LATERAL (
                    SELECT l2.sede_id, s2.nombre AS sede_nombre
                    FROM crm.leads l2
                    JOIN crm.sedes s2 ON s2.id = l2.sede_id
                    WHERE l2.asesor_id = u.id AND l2.sede_id IS NOT NULL
                    LIMIT 1
                ) s_lead ON TRUE
                WHERE {advisor_where}
                ORDER BY u.first_name, u.last_name
                """,
                advisor_params,
            )
            asesores_rows = cur.fetchall()
            total_asesores = len(asesores_rows)

            # ─────────────────────────────────────────────────────────────────
            # 2. Leads Pendientes, Visibilidad Operativa y Control Operativo (Criterio Suma/Exclusión)
            # ─────────────────────────────────────────────────────────────────
            citas_cte = _citas_ordenadas_cte_sql()
            lead_citas_cte = _lead_citas_resumen_cte_sql()
            clasif_case = _clasificacion_operativa_case_sql("e", "lcr")
            no_pendiente_sql = f"({EXCLUDED_URGENT_STATE_SQL} OR {NORMALIZED_STATE_EXPR} ~ '(bolsa|reciclaje)')"

            cur.execute(
                f"""
                WITH interacciones AS (
                    SELECT lead_id, MIN(created_at) AS primer_contacto, MAX(created_at) AS ultimo_contacto
                    FROM (
                        SELECT lead_id, created_at
                        FROM crm.contactos
                        WHERE tipo_contacto NOT IN {EXCLUDED_INTERACTION_TYPES_SQL}
                        UNION ALL
                        SELECT lead_id, fecha_llamada AS created_at
                        FROM crm.llamadas
                        WHERE lead_id IS NOT NULL
                    ) _i
                    GROUP BY lead_id
                ),
                {citas_cte},
                {lead_citas_cte},
                leads_clasificados AS (
                    SELECT
                        l.id,
                        l.asesor_id,
                        l.created_at,
                        i.primer_contacto,
                        i.ultimo_contacto,
                        ({no_pendiente_sql}) AS es_excluido_pendiente,
                        ({clasif_case}) AS categoria_operativa
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                    LEFT JOIN interacciones i ON i.lead_id = l.id
                    LEFT JOIN lead_citas_resumen lcr ON lcr.lead_id = l.id
                    WHERE {lead_where}
                )
                SELECT
                    -- Métricas de urgencia y atención
                    COUNT(*) FILTER (
                        WHERE lc.primer_contacto IS NULL AND NOT lc.es_excluido_pendiente
                    ) AS pendientes_sin_contacto,
                    COUNT(*) FILTER (
                        WHERE lc.primer_contacto IS NULL
                          AND lc.created_at <= NOW() - INTERVAL '15 minutes'
                          AND NOT lc.es_excluido_pendiente
                    ) AS criticos_gt_15m,
                    COUNT(*) FILTER (
                        WHERE lc.primer_contacto IS NULL
                          AND lc.created_at <= NOW() - INTERVAL '2 hours'
                          AND NOT lc.es_excluido_pendiente
                    ) AS criticos_gt_2h,
                    COUNT(*) FILTER (WHERE lc.asesor_id IS NULL) AS sin_asesor_huerfanos,
                    COUNT(*) FILTER (
                        WHERE lc.asesor_id IS NOT NULL
                          AND COALESCE(lc.ultimo_contacto, lc.created_at) <= NOW() - INTERVAL '24 hours'
                          AND NOT lc.es_excluido_pendiente
                    ) AS no_gestionados_gt_24h,
                    COUNT(*) FILTER (WHERE lc.created_at >= %s AND lc.created_at <= %s) AS leads_nuevos_periodo,
                    COUNT(*) FILTER (
                        WHERE lc.created_at >= %s AND lc.created_at <= %s
                          AND lc.primer_contacto IS NOT NULL
                          AND lc.primer_contacto >= lc.created_at
                    ) AS leads_con_primer_contacto_periodo,
                    ROUND(
                        COALESCE(
                            AVG(EXTRACT(EPOCH FROM (lc.primer_contacto - lc.created_at)) / 60.0) FILTER (
                                WHERE lc.created_at >= %s AND lc.created_at <= %s
                                  AND lc.primer_contacto IS NOT NULL
                                  AND lc.primer_contacto >= lc.created_at
                            ),
                            0
                        )::numeric,
                        1
                    ) AS primer_contacto_promedio_min,
                    ROUND(
                        COALESCE(
                            PERCENTILE_CONT(0.5) WITHIN GROUP (
                                ORDER BY EXTRACT(EPOCH FROM (lc.primer_contacto - lc.created_at)) / 60.0
                            ) FILTER (
                                WHERE lc.created_at >= %s AND lc.created_at <= %s
                                  AND lc.primer_contacto IS NOT NULL
                                  AND lc.primer_contacto >= lc.created_at
                            ),
                            0
                        )::numeric,
                        1
                    ) AS primer_contacto_mediana_min,

                    -- Control operativo: desglose incluido (Leads en Gestión)
                    COUNT(*) AS total_leads_activos,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'no_contesta_123') AS gestion_no_contesta_123,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'bolsa_reciclaje') AS gestion_bolsa_reciclaje,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'contactado') AS gestion_contactado,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'oportunidad_futura') AS gestion_oportunidad_futura,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'en_seguimiento') AS gestion_en_seguimiento,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'nuevas_citas') AS gestion_nuevas_citas,

                    -- Control operativo: desglose excluido
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'nuevos') AS excluido_nuevos,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'equivocados_inexistentes') AS excluido_equivocados_inexistentes,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'matriculas') AS excluido_matriculas,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'perdidos') AS excluido_perdidos,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'citas_ya_existentes') AS excluido_citas_ya_existentes,
                    COUNT(*) FILTER (WHERE lc.categoria_operativa = 'otros_excluidos') AS excluido_otros
                FROM leads_clasificados lc
                """,
                [
                    start_dt,
                    end_dt,
                    start_dt,
                    *lead_params,
                    start_dt,
                    end_dt,
                    start_dt,
                    end_dt,
                    start_dt,
                    end_dt,
                    start_dt,
                    end_dt,
                ],
            )
            kpis_leads = cur.fetchone() or {}

            # 2b. Resumen de Citas en el Período (1ra vez vs Reprogramaciones / Previas)
            citas_scope_filters = ["l.activo = TRUE", "co.created_at >= %s", "co.created_at <= %s"]
            citas_scope_params: list = [start_dt, end_dt]
            if sede_id:
                citas_scope_filters.append("l.sede_id = %s::uuid")
                citas_scope_params.append(sede_id)
            if supervisor_id:
                citas_scope_filters.append(
                    "(l.supervisor_id = %s::uuid OR COALESCE(co.asesor_id, l.asesor_id) = %s::uuid OR eq.supervisor_id = %s::uuid)"
                )
                citas_scope_params.extend([supervisor_id, supervisor_id, supervisor_id])
            if asesor_id:
                citas_scope_filters.append("COALESCE(co.asesor_id, l.asesor_id) = %s::uuid")
                citas_scope_params.append(asesor_id)
            citas_scope_where = " AND ".join(citas_scope_filters)

            cur.execute(
                f"""
                WITH {citas_cte}
                SELECT
                    COUNT(DISTINCT co.lead_id) FILTER (
                        WHERE co.cita_estado_codigo NOT IN ('cancelada', 'reprogramada')
                          AND co.cita_nro = 1
                          AND NOT co.tuvo_estado_cita_dia_previo
                    ) AS agendados_primeras_citas,
                    COUNT(*) FILTER (
                        WHERE co.cita_estado_codigo <> 'cancelada'
                          AND NOT (
                              co.cita_estado_codigo NOT IN ('cancelada', 'reprogramada')
                              AND co.cita_nro = 1
                              AND NOT co.tuvo_estado_cita_dia_previo
                          )
                    ) AS citas_reprogramadas_previas,
                    COUNT(DISTINCT co.lead_id) FILTER (
                        WHERE co.cita_estado_codigo <> 'cancelada'
                          AND NOT (
                              co.cita_estado_codigo NOT IN ('cancelada', 'reprogramada')
                              AND co.cita_nro = 1
                              AND NOT co.tuvo_estado_cita_dia_previo
                          )
                    ) AS leads_con_reprogramacion_previa,
                    COUNT(*) FILTER (WHERE co.cita_estado_codigo = 'cancelada') AS citas_canceladas
                FROM citas_ordenadas co
                JOIN crm.leads l ON l.id = co.lead_id
                LEFT JOIN crm.equipos eq ON eq.asesor_id = COALESCE(co.asesor_id, l.asesor_id) AND eq.activo = TRUE
                WHERE {citas_scope_where}
                """,
                citas_scope_params,
            )
            citas_stats = cur.fetchone() or {}

            # ─────────────────────────────────────────────────────────────────
            # 3. Detección de Leads Cruzados / Duplicados entre Asesores
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                f"""
                WITH tel_clean AS (
                    SELECT
                        l.id,
                        l.sede_id,
                        l.supervisor_id,
                        l.asesor_id,
                        RIGHT(REGEXP_REPLACE(l.telefono, '[^0-9]', '', 'g'), 9) AS tel_norm
                    FROM crm.leads l
                    WHERE l.activo = TRUE
                      AND l.telefono IS NOT NULL
                      AND LENGTH(REGEXP_REPLACE(l.telefono, '[^0-9]', '', 'g')) >= 7
                ),
                cruzados AS (
                    SELECT tel_norm
                    FROM tel_clean
                    GROUP BY tel_norm
                    HAVING COUNT(DISTINCT asesor_id) > 1
                )
                SELECT
                    COUNT(DISTINCT l.id) AS total_leads_cruzados,
                    COUNT(DISTINCT cruzados.tel_norm) AS telefonos_cruzados
                FROM tel_clean l
                JOIN cruzados ON cruzados.tel_norm = l.tel_norm
                LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                WHERE {lead_where.replace('l.activo = TRUE AND ', '').replace('l.activo = TRUE', 'TRUE')}
                """,
                lead_params,
            )
            cruzados_stats = cur.fetchone() or {"total_leads_cruzados": 0, "telefonos_cruzados": 0}

            # ─────────────────────────────────────────────────────────────────
            # 4. Avance Diario: Intentos de Llamada vs Leads Únicos Contactados
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS total_llamadas,
                    COUNT(DISTINCT ll.lead_id) FILTER (WHERE ll.lead_id IS NOT NULL) AS leads_unicos_llamados,
                    COUNT(*) FILTER (WHERE ll.tipo = 'saliente') AS salientes,
                    COUNT(*) FILTER (WHERE ll.tipo = 'entrante') AS entrantes,
                    COUNT(*) FILTER (WHERE ll.tipo = 'perdida') AS perdidas,
                    COUNT(*) FILTER (WHERE ll.tipo = 'saliente' AND ll.duracion_segundos > 0) AS contestadas,
                    COALESCE(SUM(ll.duracion_segundos), 0)::int AS duracion_total_segundos,
                    COALESCE(AVG(ll.duracion_segundos) FILTER (WHERE ll.duracion_segundos > 0), 0)::int AS duracion_promedio_segundos,
                    COUNT(DISTINCT ll.asesor_id) AS asesores_con_llamadas
                FROM crm.llamadas ll
                LEFT JOIN crm.leads lll ON lll.id = ll.lead_id
                WHERE {llamadas_where_sql}
                """,
                llamadas_params,
            )
            kpis_llamadas = cur.fetchone() or {}

            cur.execute(
                f"""
                SELECT COUNT(DISTINCT lead_id) AS leads_unicos_contactados
                FROM (
                    SELECT ll.lead_id
                    FROM crm.llamadas ll
                    LEFT JOIN crm.leads lll ON lll.id = ll.lead_id
                    WHERE {llamadas_where_sql}
                      AND ll.lead_id IS NOT NULL
                    UNION
                    SELECT c.lead_id
                    FROM crm.contactos c
                    JOIN crm.leads lc_s ON lc_s.id = c.lead_id
                    LEFT JOIN crm.equipos eq_cs ON eq_cs.asesor_id = COALESCE(c.asesor_id, lc_s.asesor_id) AND eq_cs.activo = TRUE
                    WHERE {contactos_where_sql}
                ) _unicos
                """,
                [*llamadas_params, *contactos_params],
            )
            unicos_row = cur.fetchone() or {}

            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE TRANSLATE(LOWER(TRIM(COALESCE(c.tipo_contacto, ''))), 'áéíóúüñ', 'aeiouun') IN {CALL_MANUAL_TYPES_SQL}
                    ) AS llamadas_manuales_periodo,
                    COUNT(*) FILTER (
                        WHERE LOWER(TRIM(COALESCE(c.tipo_contacto, ''))) = {WHATSAPP_TYPE_SQL}
                    ) AS whatsapp_periodo
                FROM crm.contactos c
                JOIN crm.leads lc_s ON lc_s.id = c.lead_id
                LEFT JOIN crm.equipos eq_cs ON eq_cs.asesor_id = COALESCE(c.asesor_id, lc_s.asesor_id) AND eq_cs.activo = TRUE
                WHERE {contactos_where_sql}
                """,
                contactos_params,
            )
            contactos_call_wa_row = cur.fetchone() or {}

            # Meta diaria: 40 llamadas diarias por asesor activo por día del rango
            meta_diaria_equipo = total_asesores * 40 * dias_count
            llamadas_realizadas = kpis_llamadas.get("total_llamadas") or 0
            llamadas_manuales_total = contactos_call_wa_row.get("llamadas_manuales_periodo") or 0
            whatsapp_total = contactos_call_wa_row.get("whatsapp_periodo") or 0
            total_llamadas_incl_manuales = llamadas_realizadas + llamadas_manuales_total
            total_llamadas_y_wa = llamadas_realizadas + llamadas_manuales_total + whatsapp_total
            leads_unicos_llamados = kpis_llamadas.get("leads_unicos_llamados") or 0
            leads_unicos_contactados = unicos_row.get("leads_unicos_contactados") or 0
            pct_meta_llamadas = round((llamadas_realizadas / max(meta_diaria_equipo, 1)) * 100, 1)
            promedio_intentos_por_lead = (
                round(llamadas_realizadas / leads_unicos_contactados, 1)
                if leads_unicos_contactados > 0
                else 0.0
            )
            leads_nuevos_periodo = kpis_leads.get("leads_nuevos_periodo") or 0
            llamadas_promedio_por_lead = (
                round(total_llamadas_incl_manuales / leads_nuevos_periodo, 2)
                if leads_nuevos_periodo > 0
                else 0.0
            )

            # ─────────────────────────────────────────────────────────────────
            # 5. Distribución y Ritmo Horario de Llamadas
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                f"""
                SELECT
                    EXTRACT(HOUR FROM ll.fecha_llamada AT TIME ZONE 'America/Lima')::int AS hora,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE ll.duracion_segundos > 0) AS contestadas
                FROM crm.llamadas ll
                LEFT JOIN crm.leads lll ON lll.id = ll.lead_id
                WHERE {llamadas_where_sql}
                GROUP BY 1
                ORDER BY 1
                """,
                llamadas_params,
            )
            horario_rows = {r["hora"]: r for r in cur.fetchall()}
            distribucion_horaria = []
            for h in range(8, 21):  # 8am a 8pm
                hr_data = horario_rows.get(h, {"total": 0, "contestadas": 0})
                distribucion_horaria.append({
                    "hora_label": f"{h:02d}:00",
                    "hora": h,
                    "total": hr_data["total"],
                    "contestadas": hr_data["contestadas"],
                })

            # ─────────────────────────────────────────────────────────────────
            # 6. Actividad y Métricas Exhaustivas por Asesor Individual
            # ─────────────────────────────────────────────────────────────────
            sede_cita_filter_sql = " AND l.sede_id = %s::uuid" if sede_id else ""
            sede_lead_filter_sql = " AND l.sede_id = %s::uuid" if sede_id else ""
            sede_param_list = [sede_id] if sede_id else []

            cur.execute(
                f"""
                WITH actividad_asesor AS (
                    SELECT
                        ll.asesor_id,
                        COUNT(*) AS llamadas_periodo,
                        COUNT(DISTINCT ll.lead_id) FILTER (WHERE ll.lead_id IS NOT NULL) AS leads_unicos_llamados,
                        COUNT(*) FILTER (WHERE ll.tipo = 'saliente') AS llamadas_salientes,
                        COUNT(*) FILTER (WHERE ll.duracion_segundos > 0) AS llamadas_contestadas,
                        COALESCE(SUM(ll.duracion_segundos), 0)::int AS duracion_total_seg,
                        COALESCE(AVG(ll.duracion_segundos) FILTER (WHERE ll.duracion_segundos > 0), 0)::int AS duracion_promedio_seg
                    FROM crm.llamadas ll
                    LEFT JOIN crm.leads lll ON lll.id = ll.lead_id
                    WHERE {llamadas_where_sql}
                    GROUP BY ll.asesor_id
                ),
                contactos_asesor AS (
                    SELECT
                        COALESCE(c.asesor_id, lc_s.asesor_id) AS asesor_id,
                        COUNT(*) FILTER (
                            WHERE TRANSLATE(LOWER(TRIM(COALESCE(c.tipo_contacto, ''))), 'áéíóúüñ', 'aeiouun') IN {CALL_MANUAL_TYPES_SQL}
                        ) AS llamadas_manuales_periodo,
                        COUNT(*) FILTER (
                            WHERE LOWER(TRIM(COALESCE(c.tipo_contacto, ''))) = {WHATSAPP_TYPE_SQL}
                        ) AS whatsapp_periodo,
                        COUNT(*) AS contactos_periodo
                    FROM crm.contactos c
                    JOIN crm.leads lc_s ON lc_s.id = c.lead_id
                    LEFT JOIN crm.equipos eq_cs ON eq_cs.asesor_id = COALESCE(c.asesor_id, lc_s.asesor_id) AND eq_cs.activo = TRUE
                    WHERE {contactos_where_sql}
                    GROUP BY COALESCE(c.asesor_id, lc_s.asesor_id)
                ),
                leads_unicos_asesor AS (
                    SELECT
                        asesor_id,
                        COUNT(DISTINCT lead_id) AS leads_unicos_contactados
                    FROM (
                        SELECT ll.asesor_id, ll.lead_id
                        FROM crm.llamadas ll
                        LEFT JOIN crm.leads lll ON lll.id = ll.lead_id
                        WHERE {llamadas_where_sql}
                          AND ll.asesor_id IS NOT NULL
                          AND ll.lead_id IS NOT NULL
                        UNION
                        SELECT COALESCE(c.asesor_id, lc_s.asesor_id) AS asesor_id, c.lead_id
                        FROM crm.contactos c
                        JOIN crm.leads lc_s ON lc_s.id = c.lead_id
                        LEFT JOIN crm.equipos eq_cs ON eq_cs.asesor_id = COALESCE(c.asesor_id, lc_s.asesor_id) AND eq_cs.activo = TRUE
                        WHERE {contactos_where_sql}
                    ) _u_as
                    GROUP BY asesor_id
                ),
                ultima_accion AS (
                    SELECT asesor_id, MAX(ts) AS ultima_actividad_ts
                    FROM (
                        SELECT asesor_id, fecha_llamada AS ts FROM crm.llamadas
                        UNION ALL
                        SELECT asesor_id, created_at AS ts FROM crm.contactos c WHERE {_strict_contacto_call_wa_sql("c")}
                    ) _u
                    WHERE asesor_id IS NOT NULL
                    GROUP BY asesor_id
                ),
                {citas_cte},
                {lead_citas_cte},
                citas_asesor AS (
                    SELECT
                        COALESCE(co.asesor_id, l.asesor_id) AS asesor_id,
                        COUNT(DISTINCT co.lead_id) FILTER (
                            WHERE co.cita_estado_codigo NOT IN ('cancelada', 'reprogramada')
                              AND co.cita_nro = 1
                              AND NOT co.tuvo_estado_cita_dia_previo
                        ) AS agendados_primeras_citas,
                        COUNT(*) FILTER (
                            WHERE co.cita_estado_codigo <> 'cancelada'
                              AND NOT (
                                  co.cita_estado_codigo NOT IN ('cancelada', 'reprogramada')
                                  AND co.cita_nro = 1
                                  AND NOT co.tuvo_estado_cita_dia_previo
                              )
                        ) AS citas_reprogramadas_previas
                    FROM citas_ordenadas co
                    JOIN crm.leads l ON l.id = co.lead_id
                    WHERE l.activo = TRUE
                      AND co.created_at >= %s
                      AND co.created_at <= %s
                      {sede_cita_filter_sql}
                    GROUP BY COALESCE(co.asesor_id, l.asesor_id)
                ),
                leads_stats AS (
                    SELECT
                        l.asesor_id,
                        COUNT(*) FILTER (WHERE l.created_at >= %s AND l.created_at <= %s) AS leads_asignados_periodo,
                        COUNT(*) FILTER (
                            WHERE l.activo = TRUE
                              AND NOT {no_pendiente_sql}
                              AND NOT EXISTS (
                                  SELECT 1 FROM crm.contactos c
                                  WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN {EXCLUDED_INTERACTION_TYPES_SQL}
                              )
                              AND NOT EXISTS (
                                  SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id
                              )
                        ) AS leads_pendientes,
                        COUNT(*) FILTER (
                            WHERE l.activo = TRUE
                              AND NOT {no_pendiente_sql}
                              AND COALESCE(l.updated_at, l.created_at) <= NOW() - INTERVAL '24 hours'
                        ) AS no_gestionados_24h,
                        COUNT(*) FILTER (
                            WHERE l.created_at >= %s AND l.created_at <= %s
                              AND {NORMALIZED_STATE_EXPR} ~ '(ganad|matricul|reserv|separac|venta concretad|cierr|inscrit)'
                        ) AS matriculas_periodo,
                        COUNT(*) FILTER (
                            WHERE ({clasif_case}) IN {ESTADOS_GESTION_KEYS}
                        ) AS leads_en_gestion
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN lead_citas_resumen lcr ON lcr.lead_id = l.id
                    WHERE l.asesor_id IS NOT NULL
                      AND l.activo = TRUE
                      {sede_lead_filter_sql}
                    GROUP BY l.asesor_id
                )
                SELECT
                    u.id::text AS asesor_id,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                    u.email AS asesor_email,
                    u.role AS rol,
                    COALESCE(s_lead.sede_nombre, 'Principal') AS sede_nombre,
                    sup.id::text AS supervisor_id,
                    TRIM(COALESCE(sup.first_name, '') || ' ' || COALESCE(sup.last_name, '')) AS supervisor_nombre,
                    COALESCE(ls.leads_asignados_periodo, 0)::int AS leads_asignados_periodo,
                    COALESCE(ls.leads_pendientes, 0)::int AS leads_pendientes,
                    COALESCE(ls.no_gestionados_24h, 0)::int AS no_gestionados_24h,
                    COALESCE(ls.leads_en_gestion, 0)::int AS leads_en_gestion,
                    COALESCE(act.llamadas_periodo, 0)::int AS llamadas_periodo,
                    COALESCE(act.leads_unicos_llamados, 0)::int AS leads_unicos_llamados,
                    COALESCE(cp.llamadas_manuales_periodo, 0)::int AS llamadas_manuales_periodo,
                    COALESCE(cp.whatsapp_periodo, 0)::int AS whatsapp_periodo,
                    COALESCE(cp.contactos_periodo, 0)::int AS contactos_periodo,
                    (COALESCE(act.llamadas_periodo, 0) + COALESCE(cp.contactos_periodo, 0))::int AS gestiones_periodo,
                    COALESCE(lua.leads_unicos_contactados, 0)::int AS leads_unicos_contactados,
                    COALESCE(act.llamadas_salientes, 0)::int AS llamadas_salientes,
                    COALESCE(act.llamadas_contestadas, 0)::int AS llamadas_contestadas,
                    COALESCE(act.duracion_total_seg, 0)::int AS duracion_total_seg,
                    COALESCE(act.duracion_promedio_seg, 0)::int AS duracion_promedio_segundos,
                    ROUND(COALESCE(act.duracion_total_seg, 0) / 60.0, 1) AS minutos_llamadas,
                    COALESCE(ca.agendados_primeras_citas, 0)::int AS agendados_primeras_citas,
                    COALESCE(ca.citas_reprogramadas_previas, 0)::int AS citas_reprogramadas_previas,
                    COALESCE(ls.matriculas_periodo, 0)::int AS matriculas_periodo,
                    ua.ultima_actividad_ts
                FROM auth.users u
                LEFT JOIN crm.equipos eq ON eq.asesor_id = u.id AND eq.activo = TRUE
                LEFT JOIN auth.users sup ON sup.id = eq.supervisor_id
                LEFT JOIN LATERAL (
                    SELECT l2.sede_id, s2.nombre AS sede_nombre
                    FROM crm.leads l2
                    JOIN crm.sedes s2 ON s2.id = l2.sede_id
                    WHERE l2.asesor_id = u.id AND l2.sede_id IS NOT NULL
                    LIMIT 1
                ) s_lead ON TRUE
                LEFT JOIN actividad_asesor act ON act.asesor_id = u.id
                LEFT JOIN contactos_asesor cp ON cp.asesor_id = u.id
                LEFT JOIN leads_unicos_asesor lua ON lua.asesor_id = u.id
                LEFT JOIN ultima_accion ua ON ua.asesor_id = u.id
                LEFT JOIN citas_asesor ca ON ca.asesor_id = u.id
                LEFT JOIN leads_stats ls ON ls.asesor_id = u.id
                WHERE {advisor_where}
                ORDER BY (COALESCE(act.llamadas_periodo, 0) + COALESCE(cp.contactos_periodo, 0)) DESC,
                         ls.leads_asignados_periodo DESC NULLS LAST,
                         u.first_name ASC
                """,
                [
                    *llamadas_params,
                    *contactos_params,
                    *llamadas_params,
                    *contactos_params,
                    start_dt,
                    end_dt,
                    start_dt,
                    start_dt,
                    end_dt,
                    *sede_param_list,
                    start_dt,
                    end_dt,
                    start_dt,
                    end_dt,
                    *sede_param_list,
                    *advisor_params,
                ],
            )
            asesores_detalle = []
            ahora_dt = datetime.now(LIMA_TZ)
            asesores_activos_hoy_count = 0
            asesores_sin_actividad_count = 0
            asesores_inactivos_alerta_count = 0

            for r in cur.fetchall():
                row_dict = dict(r)
                llamadas_cant = row_dict.get("llamadas_periodo") or 0
                contactos_cant = row_dict.get("contactos_periodo") or 0
                ult_ts = row_dict.get("ultima_actividad_ts")

                minutos_inactivo = None
                if ult_ts:
                    if ult_ts.tzinfo is None:
                        ult_ts = ult_ts.replace(tzinfo=LIMA_TZ)
                    diff = ahora_dt - ult_ts
                    minutos_inactivo = max(0, int(diff.total_seconds() // 60))

                estado_actividad, en_alerta = _classify_advisor_activity(
                    llamadas_cant, contactos_cant, minutos_inactivo
                )
                if estado_actividad == "activo":
                    asesores_activos_hoy_count += 1
                else:
                    asesores_sin_actividad_count += 1
                    if en_alerta:
                        asesores_inactivos_alerta_count += 1

                row_dict["minutos_inactivo"] = minutos_inactivo
                row_dict["estado_actividad"] = estado_actividad
                llamadas_tot = (row_dict.get("llamadas_periodo") or 0) + (
                    row_dict.get("llamadas_manuales_periodo") or 0
                )
                leads_asig_per = row_dict.get("leads_asignados_periodo") or 0
                row_dict["llamadas_totales_periodo"] = llamadas_tot
                row_dict["llamadas_promedio_por_lead"] = (
                    round(llamadas_tot / leads_asig_per, 2) if leads_asig_per > 0 else 0.0
                )
                row_dict.setdefault("duracion_promedio_segundos", 0)
                asesores_detalle.append(row_dict)

            # ─────────────────────────────────────────────────────────────────
            # 7. Resumen de Actividad Comercial a Nivel Equipo (Supervisores)
            # ─────────────────────────────────────────────────────────────────
            equipos_where = ["sup.role = 'supervisor'", "sup.is_active = TRUE"]
            equipos_params: list = []
            if supervisor_id:
                equipos_where.append("sup.id = %s::uuid")
                equipos_params.append(supervisor_id)
            equipos_where_sql = " AND ".join(equipos_where)

            cur.execute(
                f"""
                SELECT
                    sup.id::text AS supervisor_id,
                    TRIM(COALESCE(sup.first_name, '') || ' ' || COALESCE(sup.last_name, '')) AS supervisor_nombre,
                    COUNT(DISTINCT CASE WHEN a.id IS NOT NULL THEN eq.asesor_id END) AS total_asesores
                FROM auth.users sup
                LEFT JOIN crm.equipos eq ON eq.supervisor_id = sup.id AND eq.activo = TRUE
                LEFT JOIN auth.users a ON a.id = eq.asesor_id AND a.is_active = TRUE
                WHERE {equipos_where_sql}
                GROUP BY sup.id, sup.first_name, sup.last_name
                ORDER BY supervisor_nombre
                """,
                equipos_params,
            )
            equipos_rows = cur.fetchall()
            equipos_desempeno = []
            for eq in equipos_rows:
                sup_id = eq["supervisor_id"]
                asesores_del_sup = [
                    a
                    for a in asesores_detalle
                    if (a.get("supervisor_id") and a.get("supervisor_id") == sup_id)
                    or a.get("asesor_id") == sup_id
                    or (not a.get("supervisor_id") and a.get("supervisor_nombre") == eq["supervisor_nombre"])
                ]
                if (asesor_id or sede_id) and not asesores_del_sup:
                    continue

                leads_asig = sum(a.get("leads_asignados_periodo", 0) for a in asesores_del_sup)
                leads_pend = sum(a.get("leads_pendientes", 0) for a in asesores_del_sup)
                ll_total = sum(a.get("llamadas_periodo", 0) for a in asesores_del_sup)
                ll_man = sum(a.get("llamadas_manuales_periodo", 0) for a in asesores_del_sup)
                wa_total = sum(a.get("whatsapp_periodo", 0) for a in asesores_del_sup)
                ll_cont = sum(a.get("llamadas_contestadas", 0) for a in asesores_del_sup)
                unicos_cont = sum(a.get("leads_unicos_contactados", 0) for a in asesores_del_sup)
                agendados_eq = sum(a.get("agendados_primeras_citas", 0) for a in asesores_del_sup)
                reprog_eq = sum(a.get("citas_reprogramadas_previas", 0) for a in asesores_del_sup)
                en_gestion_eq = sum(a.get("leads_en_gestion", 0) for a in asesores_del_sup)
                matr = sum(a.get("matriculas_periodo", 0) for a in asesores_del_sup)
                min_hablados = round(sum(float(a.get("minutos_llamadas", 0) or 0) for a in asesores_del_sup), 1)
                activos_eq = sum(1 for a in asesores_del_sup if a.get("estado_actividad") == "activo")
                sin_act_eq = sum(1 for a in asesores_del_sup if a.get("estado_actividad") == "sin_actividad")

                tasa_atencion = round(((leads_asig - leads_pend) / max(leads_asig, 1)) * 100, 1) if leads_asig > 0 else 100.0

                equipos_desempeno.append({
                    "supervisor_id": sup_id,
                    "supervisor_nombre": eq["supervisor_nombre"],
                    "total_asesores": len(asesores_del_sup) if (asesor_id or sede_id) else eq["total_asesores"],
                    "asesores_activos": activos_eq,
                    "asesores_sin_actividad": sin_act_eq,
                    "leads_asignados": leads_asig,
                    "leads_pendientes": leads_pend,
                    "leads_en_gestion": en_gestion_eq,
                    "tasa_atencion_pct": tasa_atencion,
                    "llamadas_total": ll_total,
                    "llamadas_manuales_total": ll_man,
                    "whatsapp_total": wa_total,
                    "llamadas_y_wa_total": ll_total + ll_man + wa_total,
                    "llamadas_contestadas": ll_cont,
                    "leads_unicos_contactados": unicos_cont,
                    "agendados_primeras_citas": agendados_eq,
                    "citas_reprogramadas_previas": reprog_eq,
                    "minutos_hablados": min_hablados,
                    "matriculas": matr,
                })

            # ─────────────────────────────────────────────────────────────────
            # 8. Muestra de Foco Crítico (Acción Inmediata para Dirección)
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                f"""
                SELECT
                    l.id,
                    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre,
                    l.telefono,
                    COALESCE(f.nombre, 'Redes Sociales') AS fuente_nombre,
                    l.created_at,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                    ROUND(EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 60)::int AS minutos_espera
                FROM crm.leads l
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                LEFT JOIN auth.users u ON u.id = l.asesor_id
                LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE {lead_where}
                  AND NOT {no_pendiente_sql}
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN {EXCLUDED_INTERACTION_TYPES_SQL}
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id
                  )
                ORDER BY l.created_at ASC
                LIMIT 10
                """,
                lead_params,
            )
            leads_urgentes = cur.fetchall()

            asesores_alerta = [
                a for a in asesores_detalle if a["estado_actividad"] == "sin_actividad"
            ]

            # ─────────────────────────────────────────────────────────────────
            # 9. Desempeño por Fuente (1er Contacto y Llamadas Promedio por Lead)
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                f"""
                WITH interacciones AS (
                    SELECT lead_id, MIN(created_at) AS primer_contacto
                    FROM (
                        SELECT lead_id, created_at
                        FROM crm.contactos
                        WHERE tipo_contacto NOT IN {EXCLUDED_INTERACTION_TYPES_SQL}
                        UNION ALL
                        SELECT lead_id, fecha_llamada AS created_at
                        FROM crm.llamadas
                        WHERE lead_id IS NOT NULL
                    ) _i
                    GROUP BY lead_id
                ),
                leads_periodo_fuente AS (
                    SELECT
                        COALESCE(l.fuente_id, 0) AS fuente_id,
                        COALESCE(f.nombre, 'Sin fuente') AS fuente_nombre,
                        COUNT(*)::int AS leads_periodo,
                        COUNT(*) FILTER (
                            WHERE i.primer_contacto IS NOT NULL
                              AND i.primer_contacto >= l.created_at
                        )::int AS con_primer_contacto,
                        AVG(EXTRACT(EPOCH FROM (i.primer_contacto - l.created_at)) / 60.0) FILTER (
                            WHERE i.primer_contacto IS NOT NULL
                              AND i.primer_contacto >= l.created_at
                        ) AS tiempo_promedio_min,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (
                            ORDER BY EXTRACT(EPOCH FROM (i.primer_contacto - l.created_at)) / 60.0
                        ) FILTER (
                            WHERE i.primer_contacto IS NOT NULL
                              AND i.primer_contacto >= l.created_at
                        ) AS tiempo_mediana_min
                    FROM crm.leads l
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                    LEFT JOIN interacciones i ON i.lead_id = l.id
                    WHERE {lead_where}
                      AND l.created_at >= %s
                      AND l.created_at <= %s
                    GROUP BY COALESCE(l.fuente_id, 0), COALESCE(f.nombre, 'Sin fuente')
                ),
                llamadas_app_fuente AS (
                    SELECT
                        COALESCE(lll.fuente_id, 0) AS fuente_id,
                        COALESCE(f.nombre, 'Sin fuente') AS fuente_nombre,
                        COUNT(*)::int AS llamadas_app
                    FROM crm.llamadas ll
                    LEFT JOIN crm.leads lll ON lll.id = ll.lead_id
                    LEFT JOIN crm.fuentes f ON f.id = lll.fuente_id
                    WHERE {llamadas_where_sql}
                      AND (ll.lead_id IS NULL OR COALESCE(lll.activo, TRUE) = TRUE)
                    GROUP BY COALESCE(lll.fuente_id, 0), COALESCE(f.nombre, 'Sin fuente')
                ),
                llamadas_man_fuente AS (
                    SELECT
                        COALESCE(lc_s.fuente_id, 0) AS fuente_id,
                        COALESCE(f.nombre, 'Sin fuente') AS fuente_nombre,
                        COUNT(*)::int AS llamadas_manuales
                    FROM crm.contactos c
                    JOIN crm.leads lc_s ON lc_s.id = c.lead_id
                    LEFT JOIN crm.fuentes f ON f.id = lc_s.fuente_id
                    LEFT JOIN crm.equipos eq_cs ON eq_cs.asesor_id = COALESCE(c.asesor_id, lc_s.asesor_id) AND eq_cs.activo = TRUE
                    WHERE {contactos_where_sql}
                      AND TRANSLATE(LOWER(TRIM(COALESCE(c.tipo_contacto, ''))), 'áéíóúüñ', 'aeiouun') IN {CALL_MANUAL_TYPES_SQL}
                    GROUP BY COALESCE(lc_s.fuente_id, 0), COALESCE(f.nombre, 'Sin fuente')
                )
                SELECT
                    COALESCE(lpf.fuente_id, laf.fuente_id, lmf.fuente_id) AS fuente_id,
                    COALESCE(lpf.fuente_nombre, laf.fuente_nombre, lmf.fuente_nombre, 'Sin fuente') AS fuente_nombre,
                    COALESCE(lpf.leads_periodo, 0)::int AS leads_periodo,
                    COALESCE(lpf.con_primer_contacto, 0)::int AS con_primer_contacto,
                    ROUND(COALESCE(lpf.tiempo_promedio_min, 0)::numeric, 1) AS tiempo_promedio_min,
                    ROUND(COALESCE(lpf.tiempo_mediana_min, 0)::numeric, 1) AS tiempo_mediana_min,
                    COALESCE(laf.llamadas_app, 0)::int AS llamadas_app,
                    COALESCE(lmf.llamadas_manuales, 0)::int AS llamadas_manuales
                FROM leads_periodo_fuente lpf
                FULL OUTER JOIN llamadas_app_fuente laf ON laf.fuente_id = lpf.fuente_id
                FULL OUTER JOIN llamadas_man_fuente lmf ON lmf.fuente_id = COALESCE(lpf.fuente_id, laf.fuente_id)
                ORDER BY COALESCE(lpf.leads_periodo, 0) DESC,
                         (COALESCE(laf.llamadas_app, 0) + COALESCE(lmf.llamadas_manuales, 0)) DESC,
                         fuente_nombre ASC
                """,
                [*lead_params, start_dt, end_dt, *llamadas_params, *contactos_params],
            )
            fuentes_desempeno = []
            for fr in cur.fetchall():
                f_leads = int(fr.get("leads_periodo") or 0)
                f_app = int(fr.get("llamadas_app") or 0)
                f_man = int(fr.get("llamadas_manuales") or 0)
                f_tot = f_app + f_man
                fuentes_desempeno.append({
                    "fuente_id": fr.get("fuente_id"),
                    "fuente_nombre": fr.get("fuente_nombre") or "Sin fuente",
                    "leads_periodo": f_leads,
                    "con_primer_contacto": int(fr.get("con_primer_contacto") or 0),
                    "tiempo_promedio_min": float(fr.get("tiempo_promedio_min") or 0.0),
                    "tiempo_mediana_min": float(fr.get("tiempo_mediana_min") or 0.0),
                    "llamadas_app": f_app,
                    "llamadas_manuales": f_man,
                    "llamadas_totales": f_tot,
                    "llamadas_promedio_por_lead": round(f_tot / f_leads, 2) if f_leads > 0 else 0.0,
                })

            # ─────────────────────────────────────────────────────────────────
            # 10. Leads Trasladados entre Bolsas (Reasignaciones entre asesores/equipos, sin Bolsa TMK)
            # ─────────────────────────────────────────────────────────────────
            traslados_filters = [
                "l.activo = TRUE",
                "al.created_at >= %s",
                "al.created_at <= %s",
                "al.asesor_anterior IS NOT NULL",
                "al.asesor_nuevo IS NOT NULL",
                "al.asesor_anterior <> al.asesor_nuevo",
                "STRPOS(LOWER(COALESCE(al.motivo, '')), 'tmk') = 0",
                "STRPOS(LOWER(COALESCE(al.motivo, '')), 'bolsa') = 0",
            ]
            traslados_params: list = [start_dt, end_dt]
            if sede_id:
                traslados_filters.append("l.sede_id = %s::uuid")
                traslados_params.append(sede_id)
            if supervisor_id:
                traslados_filters.append(
                    "(l.supervisor_id = %s::uuid OR eq_ant.supervisor_id = %s::uuid OR eq_nvo.supervisor_id = %s::uuid OR al.asesor_anterior = %s::uuid OR al.asesor_nuevo = %s::uuid)"
                )
                traslados_params.extend([supervisor_id] * 5)
            if asesor_id:
                traslados_filters.append("(al.asesor_anterior = %s::uuid OR al.asesor_nuevo = %s::uuid)")
                traslados_params.extend([asesor_id, asesor_id])
            traslados_where_sql = " AND ".join(traslados_filters)

            cur.execute(
                f"""
                SELECT
                    COUNT(*)::int AS total_traslados,
                    COUNT(DISTINCT al.lead_id)::int AS leads_unicos_trasladados,
                    COUNT(*) FILTER (
                        WHERE eq_ant.supervisor_id IS DISTINCT FROM eq_nvo.supervisor_id
                          AND (eq_ant.supervisor_id IS NOT NULL OR eq_nvo.supervisor_id IS NOT NULL)
                    )::int AS entre_equipos,
                    COUNT(*) FILTER (
                        WHERE NOT (
                            eq_ant.supervisor_id IS DISTINCT FROM eq_nvo.supervisor_id
                            AND (eq_ant.supervisor_id IS NOT NULL OR eq_nvo.supervisor_id IS NOT NULL)
                        )
                    )::int AS mismo_equipo
                FROM crm.asignaciones_log al
                JOIN crm.leads l ON l.id = al.lead_id
                LEFT JOIN crm.equipos eq_ant ON eq_ant.asesor_id = al.asesor_anterior AND eq_ant.activo = TRUE
                LEFT JOIN crm.equipos eq_nvo ON eq_nvo.asesor_id = al.asesor_nuevo AND eq_nvo.activo = TRUE
                WHERE {traslados_where_sql}
                """,
                traslados_params,
            )
            traslados_row = cur.fetchone() or {}

            # Totales de control operativo (Point 5)
            desglose_gestion = {
                "no_contesta_123": kpis_leads.get("gestion_no_contesta_123") or 0,
                "bolsa_reciclaje": kpis_leads.get("gestion_bolsa_reciclaje") or 0,
                "contactado": kpis_leads.get("gestion_contactado") or 0,
                "oportunidad_futura": kpis_leads.get("gestion_oportunidad_futura") or 0,
                "en_seguimiento": kpis_leads.get("gestion_en_seguimiento") or 0,
                "nuevas_citas": kpis_leads.get("gestion_nuevas_citas") or 0,
            }
            desglose_excluidos = {
                "nuevos": kpis_leads.get("excluido_nuevos") or 0,
                "equivocados_inexistentes": kpis_leads.get("excluido_equivocados_inexistentes") or 0,
                "matriculas": kpis_leads.get("excluido_matriculas") or 0,
                "perdidos": kpis_leads.get("excluido_perdidos") or 0,
                "citas_ya_existentes": kpis_leads.get("excluido_citas_ya_existentes") or 0,
                "otros": kpis_leads.get("excluido_otros") or 0,
            }
            total_leads_en_gestion = sum(desglose_gestion.values())
            total_leads_excluidos = sum(desglose_excluidos.values())

            agendados_primeras_citas = citas_stats.get("agendados_primeras_citas") or 0
            citas_reprogramadas_previas = citas_stats.get("citas_reprogramadas_previas") or 0
            leads_con_reprogramacion_previa = citas_stats.get("leads_con_reprogramacion_previa") or 0
            citas_canceladas = citas_stats.get("citas_canceladas") or 0

            return {
                "periodo": periodo,
                "rango_fechas": {
                    "desde": start_dt.isoformat() if start_dt else None,
                    "hasta": end_dt.isoformat() if end_dt else None,
                    "fecha_inicio": start_dt.strftime("%Y-%m-%d") if start_dt else None,
                    "fecha_fin": end_dt.strftime("%Y-%m-%d") if end_dt else None,
                    "dias": dias_count,
                },
                "kpis_operativos": {
                    "leads_pendientes_atender": {
                        "total_pendientes": kpis_leads.get("pendientes_sin_contacto") or 0,
                        "criticos_gt_15m": kpis_leads.get("criticos_gt_15m") or 0,
                        "criticos_gt_2h": kpis_leads.get("criticos_gt_2h") or 0,
                        "sin_asignar_huerfanos": kpis_leads.get("sin_asesor_huerfanos") or 0,
                        "leads_nuevos_periodo": kpis_leads.get("leads_nuevos_periodo") or 0,
                    },
                    "asesores_actividad": {
                        "total_asesores": total_asesores,
                        "activos_hoy": asesores_activos_hoy_count,
                        "sin_actividad_hoy": asesores_sin_actividad_count,
                        "inactivos_gt_2h": asesores_inactivos_alerta_count,
                    },
                    "leads_cruzados_no_gestionados": {
                        "no_gestionados_gt_24h": kpis_leads.get("no_gestionados_gt_24h") or 0,
                        "total_leads_cruzados": cruzados_stats.get("total_leads_cruzados") or 0,
                        "telefonos_cruzados": cruzados_stats.get("telefonos_cruzados") or 0,
                    },
                    "avance_llamadas": {
                        "total_llamadas": llamadas_realizadas,
                        "llamadas_manuales_periodo": llamadas_manuales_total,
                        "total_llamadas_incl_manuales": total_llamadas_incl_manuales,
                        "whatsapp_periodo": whatsapp_total,
                        "total_llamadas_y_wa": total_llamadas_y_wa,
                        "leads_unicos_llamados": leads_unicos_llamados,
                        "leads_unicos_contactados": leads_unicos_contactados,
                        "promedio_intentos_por_lead": promedio_intentos_por_lead,
                        "llamadas_promedio_por_lead": llamadas_promedio_por_lead,
                        "salientes": kpis_llamadas.get("salientes") or 0,
                        "entrantes": kpis_llamadas.get("entrantes") or 0,
                        "perdidas": kpis_llamadas.get("perdidas") or 0,
                        "contestadas": kpis_llamadas.get("contestadas") or 0,
                        "duracion_total_segundos": kpis_llamadas.get("duracion_total_segundos") or 0,
                        "duracion_promedio_segundos": kpis_llamadas.get("duracion_promedio_segundos") or 0,
                        "meta_diaria_estimada": meta_diaria_equipo,
                        "porcentaje_cumplimiento": pct_meta_llamadas,
                    },
                    "tiempo_primer_contacto": {
                        "leads_periodo": leads_nuevos_periodo,
                        "con_primer_contacto": int(kpis_leads.get("leads_con_primer_contacto_periodo") or 0),
                        "tiempo_promedio_min": float(kpis_leads.get("primer_contacto_promedio_min") or 0.0),
                        "tiempo_mediana_min": float(kpis_leads.get("primer_contacto_mediana_min") or 0.0),
                    },
                    "traslados_bolsas": {
                        "total_traslados": int(traslados_row.get("total_traslados") or 0),
                        "leads_unicos_trasladados": int(traslados_row.get("leads_unicos_trasladados") or 0),
                        "entre_equipos": int(traslados_row.get("entre_equipos") or 0),
                        "mismo_equipo": int(traslados_row.get("mismo_equipo") or 0),
                    },
                    "citas_resumen": {
                        "agendados_primeras_citas": agendados_primeras_citas,
                        "citas_reprogramadas_previas": citas_reprogramadas_previas,
                        "leads_con_reprogramacion_previa": leads_con_reprogramacion_previa,
                        "citas_canceladas": citas_canceladas,
                        "total_citas_activas_periodo": agendados_primeras_citas + citas_reprogramadas_previas,
                    },
                    "control_operativo": {
                        "total_leads_activos": kpis_leads.get("total_leads_activos") or 0,
                        "leads_en_gestion": total_leads_en_gestion,
                        "leads_excluidos": total_leads_excluidos,
                        "desglose_gestion": desglose_gestion,
                        "desglose_excluidos": desglose_excluidos,
                    },
                },
                "distribucion_horaria_llamadas": distribucion_horaria,
                "fuentes_desempeno": fuentes_desempeno,
                "equipos_desempeno": equipos_desempeno,
                "asesores_detalle": asesores_detalle,
                "foco_critico": {
                    "leads_urgentes": leads_urgentes,
                    "asesores_sin_actividad": asesores_alerta,
                },
            }


def _classify_cita_outcome(estado_id: Optional[int], estado_nombre: Optional[str]) -> str:
    """Clasifica el desenlace actual de un lead que pasó por cita: 'matricula' (ganado/reserva/cierre), 'perdido' u 'otro'."""
    norm = (estado_nombre or "").strip().lower()
    for src, dst in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        norm = norm.replace(src, dst)
    if any(k in norm for k in ("ganad", "matricul", "reserv", "separac", "venta concretad", "cierr", "inscrit")):
        return "matricula"
    if estado_id == 8 or any(k in norm for k in ("perdid", "desist", "descart", "no interesad")):
        return "perdido"
    return "otro"


def _pct(num: int, den: int) -> float:
    """Retorna porcentaje redondeado a 1 decimal, evitando división por cero."""
    return round((num / den) * 100, 1) if den > 0 else 0.0


@router.get("/seguimiento-citas")
def get_seguimiento_citas(
    periodo: str = Query("hoy", description="hoy | ayer | semana | mes | 30dias | custom"),
    fecha_inicio: Optional[str] = Query(None, description="YYYY-MM-DD si periodo=custom"),
    fecha_fin: Optional[str] = Query(None, description="YYYY-MM-DD si periodo=custom"),
    sede_id: Optional[str] = Query(None),
    supervisor_id: Optional[str] = Query(None),
    asesor_id: Optional[str] = Query(None),
    solo_periodo: bool = Query(True, description="Si es True, filtra por leads cuya cita o pase a estado Cita ocurrió dentro del rango"),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Seguimiento a Citas (Control y Supervisión):
    Cuenta y lista todos los leads activos que TIENEN actualmente el estado de citas
    o que TUVIERON el estado de citas en su historial (cambios de estado o citas registradas).
    """
    _check_admin(current_user)
    start_dt, end_dt, dias_count = _parse_period_range(periodo, fecha_inicio, fecha_fin)
    lead_where, lead_params = _build_supervision_scope_filters(sede_id, supervisor_id, asesor_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    to_regclass('crm.lead_historial_cambios') IS NOT NULL AS has_hist,
                    to_regclass('crm.cita_estados') IS NOT NULL AS has_cita_estados
                """
            )
            schema_flags = cur.fetchone() or {}
            has_hist = bool(schema_flags.get("has_hist"))
            has_ce = bool(schema_flags.get("has_cita_estados"))

            hist_nuevo_cita_sql = _nota_sin_sufijos_es_cita_sql("lhc.valor_nuevo")
            hist_ant_cita_sql = _nota_sin_sufijos_es_cita_sql("lhc.valor_anterior")
            hist_cte = (
                f"""
                hist_citas AS (
                    SELECT
                        lhc.lead_id,
                        MIN(lhc.created_at) AS primera_hist_cita_at,
                        BOOL_OR(lhc.created_at >= %s AND lhc.created_at <= %s) AS tuvo_hist_cita_en_periodo
                    FROM crm.lead_historial_cambios lhc
                    WHERE lhc.campo = 'estado_id'
                      AND ({hist_nuevo_cita_sql} OR {hist_ant_cita_sql})
                    GROUP BY lhc.lead_id
                ),
                """
                if has_hist
                else ""
            )
            hist_join = "LEFT JOIN hist_citas lh ON lh.lead_id = l.id" if has_hist else ""
            hist_cond = "OR lh.lead_id IS NOT NULL" if has_hist else ""
            hist_periodo_cond = "OR COALESCE(lh.tuvo_hist_cita_en_periodo, FALSE)" if has_hist else ""
            hist_null_cond = "AND lh.lead_id IS NULL" if has_hist else ""
            hist_primera_expr = (
                "LEAST(cc.primera_contacto_cita_at, lh.primera_hist_cita_at)"
                if has_hist
                else "cc.primera_contacto_cita_at"
            )

            ce_select = (
                "uc.cita_estado_codigo, uc.cita_estado_nombre, uc.cita_estado_color,"
                if has_ce
                else "NULL::text AS cita_estado_codigo, NULL::text AS cita_estado_nombre, NULL::text AS cita_estado_color,"
            )
            ce_lateral_select = (
                "ce.codigo AS cita_estado_codigo, ce.nombre AS cita_estado_nombre, ce.color_hex AS cita_estado_color"
                if has_ce
                else "NULL::text AS cita_estado_codigo, NULL::text AS cita_estado_nombre, NULL::text AS cita_estado_color"
            )
            ce_lateral_join = "LEFT JOIN crm.cita_estados ce ON ce.id = c2.cita_estado_id" if has_ce else ""
            cambio_cita_sql = _cambio_estado_cita_sql("ch")

            sql = f"""
                WITH contactos_citas AS (
                    SELECT
                        ch.lead_id,
                        MIN(ch.created_at) AS primera_contacto_cita_at,
                        MAX(ch.created_at) AS ultima_contacto_cita_at,
                        BOOL_OR(ch.created_at >= %s AND ch.created_at <= %s) AS tuvo_cita_contacto_en_periodo,
                        COUNT(*) FILTER (
                            WHERE ch.fecha_cita IS NOT NULL
                               OR STRPOS(LOWER(COALESCE(ch.resultado, '')), 'cita') > 0
                               OR LOWER(COALESCE(ch.tipo_contacto, '')) = 'cita'
                        )::int AS total_citas_registradas
                    FROM crm.contactos ch
                    WHERE (
                        (ch.tipo_contacto = 'cambio_estado' AND {cambio_cita_sql})
                        OR ch.fecha_cita IS NOT NULL
                        OR STRPOS(LOWER(COALESCE(ch.resultado, '')), 'cita') > 0
                        OR LOWER(COALESCE(ch.tipo_contacto, '')) = 'cita'
                    )
                    GROUP BY ch.lead_id
                ),
                {hist_cte}
                leads_cita_base AS (
                    SELECT
                        l.id,
                        TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre,
                        l.telefono,
                        l.created_at,
                        l.updated_at,
                        l.estado_id,
                        COALESCE(e.nombre, 'Sin estado') AS estado_nombre,
                        COALESCE(e.color_hex, '#64748B') AS estado_color,
                        COALESCE(e.es_final, FALSE) AS estado_es_final,
                        COALESCE(f.nombre, 'Sin fuente') AS fuente_nombre,
                        COALESCE(sed.nombre, 'Principal') AS sede_nombre,
                        l.asesor_id::text AS asesor_id,
                        TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                        COALESCE(l.supervisor_id, eq.supervisor_id)::text AS supervisor_id,
                        TRIM(COALESCE(sup.first_name, '') || ' ' || COALESCE(sup.last_name, '')) AS supervisor_nombre,
                        (TRANSLATE(LOWER(TRIM(COALESCE(e.nombre, ''))), 'áéíóúüñ', 'aeiouun') ~ '(cita|agendad)') AS estado_actual_es_cita,
                        (cc.lead_id IS NOT NULL {hist_cond}) AS tuvo_estado_cita_historial,
                        COALESCE(cc.total_citas_registradas, 0)::int AS total_citas_registradas,
                        COALESCE({hist_primera_expr}, l.created_at) AS primera_vez_cita_at,
                        (
                            COALESCE(cc.tuvo_cita_contacto_en_periodo, FALSE)
                            {hist_periodo_cond}
                            OR (
                                (TRANSLATE(LOWER(TRIM(COALESCE(e.nombre, ''))), 'áéíóúüñ', 'aeiouun') ~ '(cita|agendad)')
                                AND cc.lead_id IS NULL
                                {hist_null_cond}
                                AND l.created_at >= %s AND l.created_at <= %s
                            )
                        ) AS en_periodo,
                        uc.ultima_fecha_cita,
                        uc.tipo_cita,
                        {ce_select}
                        uc.notas_cita
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    LEFT JOIN crm.sedes sed ON sed.id = l.sede_id
                    LEFT JOIN auth.users u ON u.id = l.asesor_id
                    LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                    LEFT JOIN auth.users sup ON sup.id = COALESCE(l.supervisor_id, eq.supervisor_id)
                    LEFT JOIN contactos_citas cc ON cc.lead_id = l.id
                    {hist_join}
                    LEFT JOIN LATERAL (
                        SELECT
                            c2.fecha_cita AS ultima_fecha_cita,
                            c2.tipo_cita,
                            c2.notas AS notas_cita,
                            {ce_lateral_select}
                        FROM crm.contactos c2
                        {ce_lateral_join}
                        WHERE c2.lead_id = l.id
                          AND (
                              c2.fecha_cita IS NOT NULL
                              OR STRPOS(LOWER(COALESCE(c2.resultado, '')), 'cita') > 0
                              OR LOWER(COALESCE(c2.tipo_contacto, '')) = 'cita'
                          )
                        ORDER BY c2.fecha_cita DESC NULLS LAST, c2.created_at DESC, c2.id DESC
                        LIMIT 1
                    ) uc ON TRUE
                    WHERE {lead_where}
                      AND (
                          TRANSLATE(LOWER(TRIM(COALESCE(e.nombre, ''))), 'áéíóúüñ', 'aeiouun') ~ '(cita|agendad)'
                          OR cc.lead_id IS NOT NULL
                          {hist_cond}
                      )
                )
                SELECT *
                FROM leads_cita_base
                ORDER BY
                    estado_actual_es_cita DESC,
                    ultima_fecha_cita DESC NULLS LAST,
                    primera_vez_cita_at DESC NULLS LAST,
                    id DESC
            """

            params = [start_dt, end_dt]
            if has_hist:
                params.extend([start_dt, end_dt])
            params.extend([start_dt, end_dt, *lead_params])
            cur.execute(sql, params)
            all_rows = [dict(r) for r in cur.fetchall()]

    en_periodo_total = sum(1 for r in all_rows if r.get("en_periodo"))
    rows = [r for r in all_rows if r.get("en_periodo")] if solo_periodo else all_rows

    con_estado_cita_actual = 0
    tuvieron_estado_cita_antes = 0
    matriculas_desde_cita = 0
    perdidos_desde_cita = 0
    por_estado_actual_map: dict[str, dict] = {}
    por_estado_cita_map: dict[str, dict] = {}
    por_asesor_map: dict[str, dict] = {}
    por_fuente_map: dict[str, dict] = {}

    for r in rows:
        es_actual = bool(r.get("estado_actual_es_cita"))
        if es_actual:
            con_estado_cita_actual += 1
        else:
            tuvieron_estado_cita_antes += 1

        outcome = _classify_cita_outcome(r.get("estado_id"), r.get("estado_nombre"))
        if outcome == "matricula":
            matriculas_desde_cita += 1
        elif outcome == "perdido":
            perdidos_desde_cita += 1

        r["situacion_cita"] = "actual" if es_actual else "historico"
        r["desenlace_cita"] = outcome

        # Enriquecer con cohorte de ingreso y maduración (sin alterar SQL params)
        created_val = r.get("created_at")
        cita_ref_val = r.get("ultima_fecha_cita") or r.get("primera_vez_cita_at")
        cohorte_corte_dt = datetime.combine(
            start_dt.astimezone(LIMA_TZ).date().replace(day=1),
            datetime.min.time(),
            tzinfo=LIMA_TZ,
        )
        if hasattr(created_val, "astimezone"):
            created_lima = created_val.astimezone(LIMA_TZ) if created_val.tzinfo else created_val.replace(tzinfo=LIMA_TZ)
            r["cohorte_mes"] = created_lima.strftime("%Y-%m")
            r["es_mes_anterior"] = created_lima < cohorte_corte_dt
            if hasattr(cita_ref_val, "astimezone"):
                ref_lima = cita_ref_val.astimezone(LIMA_TZ) if cita_ref_val.tzinfo else cita_ref_val.replace(tzinfo=LIMA_TZ)
                r["dias_maduracion"] = max(round((ref_lima - created_lima).total_seconds() / 86400, 1), 0.0)
            else:
                r["dias_maduracion"] = None
        else:
            r["cohorte_mes"] = None
            r["es_mes_anterior"] = False
            r["dias_maduracion"] = None

        # Serializar timestamps a ISO string
        for ts_key in ("created_at", "updated_at", "primera_vez_cita_at", "ultima_fecha_cita"):
            val = r.get(ts_key)
            if hasattr(val, "isoformat"):
                r[ts_key] = val.isoformat()

        est_nombre = r.get("estado_nombre") or "Sin estado"
        est_color = r.get("estado_color") or "#64748B"
        if est_nombre not in por_estado_actual_map:
            por_estado_actual_map[est_nombre] = {
                "estado_nombre": est_nombre,
                "estado_color": est_color,
                "total": 0,
            }
        por_estado_actual_map[est_nombre]["total"] += 1

        cita_est_nombre = r.get("cita_estado_nombre") or "Sin registro de cita"
        cita_est_color = r.get("cita_estado_color") or "#94A3B8"
        cita_est_codigo = r.get("cita_estado_codigo") or "sin_registro"
        if cita_est_nombre not in por_estado_cita_map:
            por_estado_cita_map[cita_est_nombre] = {
                "codigo": cita_est_codigo,
                "nombre": cita_est_nombre,
                "color": cita_est_color,
                "total": 0,
            }
        por_estado_cita_map[cita_est_nombre]["total"] += 1

        a_key = r.get("asesor_id") or "sin_asignar"
        a_nombre = (r.get("asesor_nombre") or "").strip() or "Sin asignar"
        if a_key not in por_asesor_map:
            por_asesor_map[a_key] = {
                "asesor_id": r.get("asesor_id"),
                "asesor_nombre": a_nombre,
                "supervisor_nombre": (r.get("supervisor_nombre") or "").strip() or "Sin supervisor",
                "con_estado_actual": 0,
                "tuvieron_antes": 0,
                "matriculas": 0,
                "perdidos": 0,
                "total": 0,
            }
        por_asesor_map[a_key]["total"] += 1
        if es_actual:
            por_asesor_map[a_key]["con_estado_actual"] += 1
        else:
            por_asesor_map[a_key]["tuvieron_antes"] += 1
        if outcome == "matricula":
            por_asesor_map[a_key]["matriculas"] += 1
        elif outcome == "perdido":
            por_asesor_map[a_key]["perdidos"] += 1

        f_nombre = (r.get("fuente_nombre") or "").strip() or "Sin fuente"
        if f_nombre not in por_fuente_map:
            por_fuente_map[f_nombre] = {
                "fuente_nombre": f_nombre,
                "con_estado_actual": 0,
                "tuvieron_antes": 0,
                "matriculas": 0,
                "perdidos": 0,
                "total": 0,
            }
        por_fuente_map[f_nombre]["total"] += 1
        if es_actual:
            por_fuente_map[f_nombre]["con_estado_actual"] += 1
        else:
            por_fuente_map[f_nombre]["tuvieron_antes"] += 1
        if outcome == "matricula":
            por_fuente_map[f_nombre]["matriculas"] += 1
        elif outcome == "perdido":
            por_fuente_map[f_nombre]["perdidos"] += 1

    for group_map in (por_asesor_map, por_fuente_map):
        for item in group_map.values():
            item["pct_matricula"] = _pct(item["matriculas"], item["total"])
            item["pct_perdido"] = _pct(item["perdidos"], item["total"])

    por_estado_actual = sorted(por_estado_actual_map.values(), key=lambda x: -x["total"])
    por_estado_cita = sorted(por_estado_cita_map.values(), key=lambda x: -x["total"])
    por_asesor = sorted(por_asesor_map.values(), key=lambda x: (-x["total"], x["asesor_nombre"]))
    por_fuente = sorted(por_fuente_map.values(), key=lambda x: (-x["total"], x["fuente_nombre"]))

    return {
        "periodo": periodo,
        "solo_periodo": solo_periodo,
        "rango_fechas": {
            "fecha_inicio": start_dt.strftime("%Y-%m-%d") if start_dt else None,
            "fecha_fin": end_dt.strftime("%Y-%m-%d") if end_dt else None,
            "dias": dias_count,
        },
        "resumen": {
            "total_leads_citas": len(rows),
            "con_estado_cita_actual": con_estado_cita_actual,
            "tuvieron_estado_cita_antes": tuvieron_estado_cita_antes,
            "matriculas_desde_cita": matriculas_desde_cita,
            "perdidos_desde_cita": perdidos_desde_cita,
            "pct_cita_a_matricula": _pct(matriculas_desde_cita, len(rows)),
            "pct_cita_a_perdido": _pct(perdidos_desde_cita, len(rows)),
            "total_historico_sin_filtro_periodo": len(all_rows),
            "en_periodo": en_periodo_total,
        },
        "por_estado_actual": por_estado_actual,
        "por_estado_cita": por_estado_cita,
        "por_asesor": por_asesor,
        "por_fuente": por_fuente,
        "total_leads_listados": len(rows),
        "leads": rows[:500],
    }


def _classify_palma_outcome_detailed(estado_id: Optional[int], estado_nombre: Optional[str]) -> str:
    """Clasifica desenlace detallado: 'venta', 'separacion', 'perdido', 'visita', 'negociacion', 'cita', u 'otro'."""
    norm = (estado_nombre or "").strip().lower()
    for src, dst in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        norm = norm.replace(src, dst)
    if any(k in norm for k in ("ganad", "matricul", "venta concretad", "cierr", "inscrit")):
        return "venta"
    if any(k in norm for k in ("reserv", "separac")):
        return "separacion"
    if estado_id == 7 or estado_id == 8 or any(k in norm for k in ("perdid", "desist", "descart", "no interesad")):
        return "perdido"
    if "visita" in norm:
        return "visita"
    if "negociacion" in norm:
        return "negociacion"
    if any(k in norm for k in ("cita", "agendad")):
        return "cita"
    return "otro"


def _format_cohorte_label(ym: str) -> str:
    """Convierte 'YYYY-MM' a etiqueta legible ej. 'Set 2026'."""
    meses = ("", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic")
    try:
        y, m = ym.split("-")
        return f"{meses[int(m)]} {y}"
    except Exception:
        return ym or "Sin fecha"


@router.get("/evolucion-citas")
def get_evolucion_citas(
    periodo: str = Query("mes", description="hoy | ayer | semana | mes | 30dias | custom"),
    fecha_inicio: Optional[str] = Query(None, description="YYYY-MM-DD si periodo=custom"),
    fecha_fin: Optional[str] = Query(None, description="YYYY-MM-DD si periodo=custom"),
    sede_id: Optional[str] = Query(None),
    supervisor_id: Optional[str] = Query(None),
    asesor_id: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Evolución de Citas, Visitas y Recuperación de Cohortes (solo Admin):
    1. Cuantifica logros del período (citas/visitas, separaciones y ventas) diferenciando
       leads ingresados en el mes actual vs. recuperados de meses anteriores.
    2. Traza el embudo real de evolución de cita/visita (incluyendo tropiezos: reprogramada,
       no asistió, cancelada y recuperación posterior).
    3. Lista la cartera antigua interesada de meses anteriores con gestión activa en el período
       que aún no concreta cita/visita o cierre.
    """
    _check_admin(current_user)
    start_dt, end_dt, dias_count = _parse_period_range(periodo, fecha_inicio, fecha_fin)
    start_lima_date = start_dt.astimezone(LIMA_TZ).date()
    cohorte_corte_dt = datetime.combine(start_lima_date.replace(day=1), datetime.min.time(), tzinfo=LIMA_TZ)
    cohorte_corte_mes = cohorte_corte_dt.strftime("%Y-%m")

    lead_where, lead_params = _build_supervision_scope_filters(sede_id, supervisor_id, asesor_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    to_regclass('crm.lead_historial_cambios') IS NOT NULL AS has_hist,
                    to_regclass('crm.cita_estados') IS NOT NULL AS has_cita_estados,
                    to_regclass('crm.llamadas') IS NOT NULL AS has_llamadas
                """
            )
            schema_flags = cur.fetchone() or {}
            has_hist = bool(schema_flags.get("has_hist"))
            has_ce = bool(schema_flags.get("has_cita_estados"))
            has_llamadas = bool(schema_flags.get("has_llamadas"))

            def _cita_visita_nota_sql(expr: str) -> str:
                norm_n = f"TRANSLATE(LOWER(COALESCE({expr}, '')), 'áéíóúüñ', 'aeiouun')"
                sin_mot = f"REGEXP_REPLACE({norm_n}, '\\s*·\\s*.*$', '', 'g')"
                sin_orig = f"REGEXP_REPLACE({sin_mot}, '\\s*\\(por [^)]*\\)\\s*', ' ', 'g')"
                return f"({sin_orig} ~ '(cita|agendad|visita)')"

            def _positivo_nota_sql(expr: str) -> str:
                norm_n = f"TRANSLATE(LOWER(COALESCE({expr}, '')), 'áéíóúüñ', 'aeiouun')"
                sin_mot = f"REGEXP_REPLACE({norm_n}, '\\s*·\\s*.*$', '', 'g')"
                sin_orig = f"REGEXP_REPLACE({sin_mot}, '\\s*\\(por [^)]*\\)\\s*', ' ', 'g')"
                return f"({sin_orig} ~ '(ganad|matricul|reserv|separac|venta concretad|cierr|inscrit)')"

            cambio_cv_sql = _cita_visita_nota_sql("ch.notas")
            cambio_pos_sql = _positivo_nota_sql("ch.notas")

            ce_join = "LEFT JOIN crm.cita_estados ce ON ce.id = ch.cita_estado_id" if has_ce else ""
            ce_tropiezo_cond = "COALESCE(ce.codigo, '') IN ('reprogramada', 'no_asistio', 'cancelada')" if has_ce else "FALSE"
            ce_completada_cond = "COALESCE(ce.codigo, '') = 'completada'" if has_ce else "FALSE"
            ce_pendiente_cond = "COALESCE(ce.codigo, 'pendiente') = 'pendiente'" if has_ce else "TRUE"

            ce_lat_join = "LEFT JOIN crm.cita_estados ce2 ON ce2.id = c2.cita_estado_id" if has_ce else ""
            ce_lat_select = (
                "ce2.codigo AS ultima_cita_estado_codigo, ce2.nombre AS ultima_cita_estado_nombre, ce2.color_hex AS ultima_cita_estado_color"
                if has_ce
                else "NULL::text AS ultima_cita_estado_codigo, NULL::text AS ultima_cita_estado_nombre, NULL::text AS ultima_cita_estado_color"
            )

            hist_cte = ""
            hist_join = ""
            hist_params: list = []
            if has_hist:
                hist_cv_new = _cita_visita_nota_sql("lhc.valor_nuevo")
                hist_cv_old = _cita_visita_nota_sql("lhc.valor_anterior")
                hist_pos_new = _positivo_nota_sql("lhc.valor_nuevo")
                hist_trop_val = "TRANSLATE(LOWER(COALESCE(lhc.valor_nuevo, '')), 'áéíóúüñ', 'aeiouun') ~ '(reprogram|no asist|cancelad)'"
                hist_comp_val = "TRANSLATE(LOWER(COALESCE(lhc.valor_nuevo, '')), 'áéíóúüñ', 'aeiouun') ~ '(completad|realizad|asistio)'"
                hist_cte = f"""
                hist_evolucion AS (
                    SELECT
                        lhc.lead_id,
                        MIN(lhc.created_at) FILTER (WHERE lhc.campo = 'estado_id' AND ({hist_cv_new} OR {hist_cv_old})) AS primera_hist_cv_at,
                        BOOL_OR(
                            (lhc.campo = 'estado_id' AND {hist_cv_new} AND lhc.created_at >= %s AND lhc.created_at <= %s)
                            OR (lhc.campo IN ('cita_evento', 'cita_estado_id', 'fecha_cita') AND lhc.created_at >= %s AND lhc.created_at <= %s)
                        ) AS tuvo_hist_cv_periodo,
                        BOOL_OR(lhc.campo = 'estado_id' AND ({hist_cv_new} OR {hist_cv_old})) AS tuvo_hist_cv,
                        MAX(lhc.created_at) FILTER (WHERE lhc.campo = 'estado_id' AND {hist_pos_new}) AS ultima_hist_pos_at,
                        BOOL_OR(lhc.campo = 'estado_id' AND {hist_pos_new} AND lhc.created_at >= %s AND lhc.created_at <= %s) AS tuvo_hist_pos_periodo,
                        BOOL_OR(
                            (lhc.campo = 'cita_estado_id' AND {hist_trop_val})
                            OR lhc.campo = 'fecha_cita'
                        ) AS tuvo_hist_tropiezo,
                        BOOL_OR(lhc.campo = 'cita_estado_id' AND {hist_comp_val}) AS tuvo_hist_completada,
                        COUNT(*) FILTER (WHERE lhc.campo IN ('cita_estado_id', 'fecha_cita'))::int AS cambios_cita_hist
                    FROM crm.lead_historial_cambios lhc
                    WHERE lhc.campo IN ('estado_id', 'cita_evento', 'cita_estado_id', 'fecha_cita')
                    GROUP BY lhc.lead_id
                ),
                """
                hist_join = "LEFT JOIN hist_evolucion he ON he.lead_id = l.id"
                hist_params = [start_dt, end_dt, start_dt, end_dt, start_dt, end_dt]

            hist_select_cols = (
                """
                COALESCE(he.tuvo_hist_cv_periodo, FALSE) AS tuvo_hist_cv_periodo,
                COALESCE(he.tuvo_hist_cv, FALSE) AS tuvo_hist_cv,
                he.primera_hist_cv_at,
                he.ultima_hist_pos_at,
                COALESCE(he.tuvo_hist_pos_periodo, FALSE) AS tuvo_hist_pos_periodo,
                COALESCE(he.tuvo_hist_tropiezo, FALSE) AS tuvo_hist_tropiezo,
                COALESCE(he.tuvo_hist_completada, FALSE) AS tuvo_hist_completada,
                COALESCE(he.cambios_cita_hist, 0)::int AS cambios_cita_hist,
                """
                if has_hist
                else """
                FALSE AS tuvo_hist_cv_periodo,
                FALSE AS tuvo_hist_cv,
                NULL::timestamptz AS primera_hist_cv_at,
                NULL::timestamptz AS ultima_hist_pos_at,
                FALSE AS tuvo_hist_pos_periodo,
                FALSE AS tuvo_hist_tropiezo,
                FALSE AS tuvo_hist_completada,
                0::int AS cambios_cita_hist,
                """
            )

            hist_where_or = "OR COALESCE(he.tuvo_hist_cv, FALSE) OR he.ultima_hist_pos_at IS NOT NULL" if has_hist else ""
            hist_period_or = "OR tuvo_hist_cv_periodo" if has_hist else ""
            hist_pos_period_or = "OR tuvo_hist_pos_periodo" if has_hist else ""

            sql_evolucion = f"""
                WITH contactos_evol AS (
                    SELECT
                        ch.lead_id,
                        COUNT(*) FILTER (
                            WHERE ch.fecha_cita IS NOT NULL
                               OR STRPOS(LOWER(COALESCE(ch.resultado, '')), 'cita') > 0
                               OR LOWER(COALESCE(ch.tipo_contacto, '')) = 'cita'
                               OR STRPOS(LOWER(COALESCE(ch.tipo_cita, '')), 'visita') > 0
                        )::int AS total_citas_reg,
                        MIN(ch.created_at) FILTER (
                            WHERE ch.fecha_cita IS NOT NULL
                               OR STRPOS(LOWER(COALESCE(ch.resultado, '')), 'cita') > 0
                               OR LOWER(COALESCE(ch.tipo_contacto, '')) = 'cita'
                               OR STRPOS(LOWER(COALESCE(ch.tipo_cita, '')), 'visita') > 0
                               OR (ch.tipo_contacto = 'cambio_estado' AND {cambio_cv_sql})
                        ) AS primera_contacto_cv_at,
                        BOOL_OR(
                            (
                                ch.fecha_cita IS NOT NULL
                                OR STRPOS(LOWER(COALESCE(ch.resultado, '')), 'cita') > 0
                                OR LOWER(COALESCE(ch.tipo_contacto, '')) = 'cita'
                                OR STRPOS(LOWER(COALESCE(ch.tipo_cita, '')), 'visita') > 0
                                OR (ch.tipo_contacto = 'cambio_estado' AND {cambio_cv_sql})
                            )
                            AND ch.created_at >= %s AND ch.created_at <= %s
                        ) AS tuvo_contacto_cv_periodo,
                        BOOL_OR(
                            ch.fecha_cita IS NOT NULL
                            OR STRPOS(LOWER(COALESCE(ch.resultado, '')), 'cita') > 0
                            OR LOWER(COALESCE(ch.tipo_contacto, '')) = 'cita'
                            OR STRPOS(LOWER(COALESCE(ch.tipo_cita, '')), 'visita') > 0
                            OR (ch.tipo_contacto = 'cambio_estado' AND {cambio_cv_sql})
                        ) AS tuvo_contacto_cv,
                        BOOL_OR({ce_tropiezo_cond}) AS tuvo_ce_tropiezo,
                        BOOL_OR({ce_completada_cond}) AS tuvo_ce_completada,
                        BOOL_OR({ce_pendiente_cond} AND ch.fecha_cita IS NOT NULL) AS tuvo_ce_pendiente,
                        MAX(ch.created_at) FILTER (WHERE ch.tipo_contacto = 'cambio_estado' AND {cambio_pos_sql}) AS ultimo_cambio_pos_at,
                        BOOL_OR(
                            ch.tipo_contacto = 'cambio_estado'
                            AND {cambio_pos_sql}
                            AND ch.created_at >= %s AND ch.created_at <= %s
                        ) AS tuvo_cambio_pos_periodo,
                        COUNT(*) FILTER (
                            WHERE ch.tipo_contacto <> 'cambio_estado'
                              AND ch.created_at >= %s AND ch.created_at <= %s
                        )::int AS gestiones_contacto_periodo
                    FROM crm.contactos ch
                    {ce_join}
                    GROUP BY ch.lead_id
                ),
                {hist_cte}
                leads_base AS (
                    SELECT
                        l.id,
                        TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre,
                        l.telefono,
                        l.created_at,
                        l.updated_at,
                        l.estado_id,
                        COALESCE(e.nombre, 'Sin estado') AS estado_nombre,
                        COALESCE(e.color_hex, '#64748B') AS estado_color,
                        COALESCE(e.es_final, FALSE) AS estado_es_final,
                        COALESCE(f.nombre, 'Sin fuente') AS fuente_nombre,
                        COALESCE(sed.nombre, 'Principal') AS sede_nombre,
                        l.asesor_id::text AS asesor_id,
                        TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                        COALESCE(l.supervisor_id, eq.supervisor_id)::text AS supervisor_id,
                        TRIM(COALESCE(sup.first_name, '') || ' ' || COALESCE(sup.last_name, '')) AS supervisor_nombre,
                        COALESCE(ce.total_citas_reg, 0)::int AS total_citas_reg,
                        ce.primera_contacto_cv_at,
                        COALESCE(ce.tuvo_contacto_cv_periodo, FALSE) AS tuvo_contacto_cv_periodo,
                        COALESCE(ce.tuvo_contacto_cv, FALSE) AS tuvo_contacto_cv,
                        COALESCE(ce.tuvo_ce_tropiezo, FALSE) AS tuvo_ce_tropiezo,
                        COALESCE(ce.tuvo_ce_completada, FALSE) AS tuvo_ce_completada,
                        COALESCE(ce.tuvo_ce_pendiente, FALSE) AS tuvo_ce_pendiente,
                        ce.ultimo_cambio_pos_at,
                        COALESCE(ce.tuvo_cambio_pos_periodo, FALSE) AS tuvo_cambio_pos_periodo,
                        COALESCE(ce.gestiones_contacto_periodo, 0)::int AS gestiones_contacto_periodo,
                        {hist_select_cols}
                        uc.ultima_fecha_cita,
                        uc.tipo_cita,
                        uc.ultima_cita_estado_codigo,
                        uc.ultima_cita_estado_nombre,
                        uc.ultima_cita_estado_color
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    LEFT JOIN crm.sedes sed ON sed.id = l.sede_id
                    LEFT JOIN auth.users u ON u.id = l.asesor_id
                    LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                    LEFT JOIN auth.users sup ON sup.id = COALESCE(l.supervisor_id, eq.supervisor_id)
                    LEFT JOIN contactos_evol ce ON ce.lead_id = l.id
                    {hist_join}
                    LEFT JOIN LATERAL (
                        SELECT
                            c2.fecha_cita AS ultima_fecha_cita,
                            c2.tipo_cita,
                            {ce_lat_select}
                        FROM crm.contactos c2
                        {ce_lat_join}
                        WHERE c2.lead_id = l.id
                          AND (
                              c2.fecha_cita IS NOT NULL
                              OR STRPOS(LOWER(COALESCE(c2.resultado, '')), 'cita') > 0
                              OR LOWER(COALESCE(c2.tipo_contacto, '')) = 'cita'
                              OR STRPOS(LOWER(COALESCE(c2.tipo_cita, '')), 'visita') > 0
                          )
                        ORDER BY c2.fecha_cita DESC NULLS LAST, c2.created_at DESC, c2.id DESC
                        LIMIT 1
                    ) uc ON TRUE
                    WHERE {lead_where}
                      AND (
                          TRANSLATE(LOWER(TRIM(COALESCE(e.nombre, ''))), 'áéíóúüñ', 'aeiouun') ~ '(cita|agendad|visita|ganad|matricul|reserv|separac|venta concretad|cierr|inscrit)'
                          OR COALESCE(ce.tuvo_contacto_cv, FALSE)
                          {hist_where_or}
                      )
                )
                SELECT
                    *,
                    (
                        tuvo_contacto_cv_periodo
                        {hist_period_or}
                        OR (
                            TRANSLATE(LOWER(TRIM(COALESCE(estado_nombre, ''))), 'áéíóúüñ', 'aeiouun') ~ '(cita|agendad|visita)'
                            AND COALESCE(updated_at, created_at) >= %s
                            AND COALESCE(updated_at, created_at) <= %s
                        )
                    ) AS cita_visita_en_periodo,
                    (
                        TRANSLATE(LOWER(TRIM(COALESCE(estado_nombre, ''))), 'áéíóúüñ', 'aeiouun') ~ '(ganad|matricul|reserv|separac|venta concretad|cierr|inscrit)'
                        AND (
                            tuvo_cambio_pos_periodo
                            {hist_pos_period_or}
                            OR (
                                ultimo_cambio_pos_at IS NULL
                                AND COALESCE(updated_at, created_at) >= %s
                                AND COALESCE(updated_at, created_at) <= %s
                            )
                        )
                    ) AS cierre_en_periodo
                FROM leads_base
            """
            params_evol = [
                start_dt, end_dt,
                start_dt, end_dt,
                start_dt, end_dt,
                *hist_params,
                *lead_params,
                start_dt, end_dt,
                start_dt, end_dt,
            ]
            cur.execute(sql_evolucion, params_evol)
            evol_rows = [dict(r) for r in cur.fetchall()]

            # Query 2: Cartera antigua interesada (leads ingresados antes de cohorte_corte_dt,
            # activos y no terminales, con llamadas/contactos en el período o próxima gestión vigente)
            llamadas_cte = ""
            llamadas_join = ""
            llamadas_col = "0::int AS llamadas_periodo"
            llamadas_filter = "FALSE"
            llamadas_params: list = []
            if has_llamadas:
                llamadas_cte = """
                llamadas_antiguas AS (
                    SELECT
                        ll.lead_id,
                        COUNT(*)::int AS llamadas_periodo
                    FROM crm.llamadas ll
                    WHERE ll.lead_id IS NOT NULL
                      AND ll.fecha_llamada >= %s AND ll.fecha_llamada <= %s
                    GROUP BY ll.lead_id
                ),
                """
                llamadas_join = "LEFT JOIN llamadas_antiguas lla ON lla.lead_id = l.id"
                llamadas_col = "COALESCE(lla.llamadas_periodo, 0)::int AS llamadas_periodo"
                llamadas_filter = "COALESCE(lla.llamadas_periodo, 0) > 0"
                llamadas_params = [start_dt, end_dt]

            sql_cartera = f"""
                WITH contactos_antiguos AS (
                    SELECT
                        c.lead_id,
                        COUNT(*) FILTER (
                            WHERE c.tipo_contacto <> 'cambio_estado'
                              AND c.created_at >= %s AND c.created_at <= %s
                        )::int AS contactos_periodo,
                        MAX(c.created_at) FILTER (WHERE c.tipo_contacto <> 'cambio_estado') AS ultimo_contacto_at,
                        BOOL_OR(
                            c.fecha_cita IS NOT NULL
                            OR STRPOS(LOWER(COALESCE(c.resultado, '')), 'cita') > 0
                            OR LOWER(COALESCE(c.tipo_contacto, '')) = 'cita'
                        ) AS tuvo_intento_cita
                    FROM crm.contactos c
                    GROUP BY c.lead_id
                ),
                {llamadas_cte}
                cartera_base AS (
                    SELECT
                        l.id,
                        TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre,
                        l.telefono,
                        l.created_at,
                        l.fecha_proxima_gestion,
                        l.accion_proxima_gestion,
                        COALESCE(e.nombre, 'Sin estado') AS estado_nombre,
                        COALESCE(e.color_hex, '#64748B') AS estado_color,
                        COALESCE(f.nombre, 'Sin fuente') AS fuente_nombre,
                        l.asesor_id::text AS asesor_id,
                        TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                        TRIM(COALESCE(sup.first_name, '') || ' ' || COALESCE(sup.last_name, '')) AS supervisor_nombre,
                        COALESCE(ca.contactos_periodo, 0)::int AS contactos_periodo,
                        {llamadas_col},
                        ca.ultimo_contacto_at,
                        COALESCE(ca.tuvo_intento_cita, FALSE) AS tuvo_intento_cita
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    LEFT JOIN auth.users u ON u.id = l.asesor_id
                    LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                    LEFT JOIN auth.users sup ON sup.id = COALESCE(l.supervisor_id, eq.supervisor_id)
                    LEFT JOIN contactos_antiguos ca ON ca.lead_id = l.id
                    {llamadas_join}
                    WHERE {lead_where}
                      AND l.created_at < %s
                      AND COALESCE(e.es_final, FALSE) = FALSE
                      AND NOT ({NORMALIZED_STATE_EXPR} ~ '(ganad|matricul|reserv|separac|venta concretad|cierr|inscrit|perdid|desist|descart|no interesad|equivocad|inexistent|errone|no existe|bolsa|reciclaje)')
                      AND (
                          COALESCE(ca.contactos_periodo, 0) > 0
                          OR {llamadas_filter}
                          OR (
                              l.fecha_proxima_gestion IS NOT NULL
                              AND l.fecha_proxima_gestion >= %s
                              AND {NORMALIZED_STATE_EXPR} ~ '(negociacion|seguimiento|contactad|cita|visita|oportunidad)'
                          )
                      )
                )
                SELECT *
                FROM cartera_base
                ORDER BY
                    (contactos_periodo + llamadas_periodo) DESC,
                    ultimo_contacto_at DESC NULLS LAST,
                    created_at DESC
            """
            params_cartera = [
                start_dt, end_dt,
                *llamadas_params,
                *lead_params,
                cohorte_corte_dt,
                start_dt,
            ]
            cur.execute(sql_cartera, params_cartera)
            cartera_rows = [dict(r) for r in cur.fetchall()]

    # ── Procesamiento en Python ───────────────────────────────────────────
    def _to_lima(dt_val):
        if not hasattr(dt_val, "astimezone"):
            return None
        return dt_val.astimezone(LIMA_TZ) if dt_val.tzinfo else dt_val.replace(tzinfo=LIMA_TZ)

    def _median(nums: list[float]) -> Optional[float]:
        if not nums:
            return None
        s = sorted(nums)
        mid = len(s) // 2
        if len(s) % 2 == 1:
            return round(s[mid], 1)
        return round((s[mid - 1] + s[mid]) / 2, 1)

    citas_visitas_mismo_mes = 0
    citas_visitas_mes_anterior = 0
    separaciones_mismo_mes = 0
    separaciones_mes_anterior = 0
    ventas_mismo_mes = 0
    ventas_mes_anterior = 0

    maduracion_cita_dias: list[float] = []
    maduracion_cierre_dias: list[float] = []

    embudo_tot = {
        "total_flujo": 0,
        "agendadas": 0,
        "con_tropiezo": 0,
        "recuperadas_tropiezo": 0,
        "concretaron_cita_visita": 0,
        "separaciones": 0,
        "ventas": 0,
        "perdidos": 0,
    }

    cohortes_map: dict[str, dict] = {}
    asesores_map: dict[str, dict] = {}
    leads_recuperados: list[dict] = []
    leads_embudo: list[dict] = []

    def _ensure_asesor(row: dict) -> dict:
        key = row.get("asesor_id") or "sin_asignar"
        if key not in asesores_map:
            asesores_map[key] = {
                "asesor_id": row.get("asesor_id"),
                "asesor_nombre": (row.get("asesor_nombre") or "").strip() or "Sin asignar",
                "supervisor_nombre": (row.get("supervisor_nombre") or "").strip() or "Sin supervisor",
                "citas_mes_actual": 0,
                "citas_meses_anteriores": 0,
                "separaciones_mes_actual": 0,
                "separaciones_meses_anteriores": 0,
                "ventas_mes_actual": 0,
                "ventas_meses_anteriores": 0,
                "tropiezos": 0,
                "recuperadas_tropiezo": 0,
                "cartera_antigua_gestionada": 0,
                "maduracion_dias_sum": 0.0,
                "maduracion_dias_cnt": 0,
            }
        return asesores_map[key]

    def _ensure_cohorte(ym: str) -> dict:
        if ym not in cohortes_map:
            cohortes_map[ym] = {
                "cohorte_mes": ym,
                "cohorte_label": _format_cohorte_label(ym),
                "es_mes_anterior": ym < cohorte_corte_mes,
                "citas_visitas_periodo": 0,
                "separaciones_periodo": 0,
                "ventas_periodo": 0,
                "cartera_antigua_activa": 0,
                "tropiezos": 0,
                "recuperadas": 0,
            }
        return cohortes_map[ym]

    for r in evol_rows:
        created_lima = _to_lima(r.get("created_at"))
        cohorte_ym = created_lima.strftime("%Y-%m") if created_lima else "Sin fecha"
        es_mes_anterior = bool(created_lima and created_lima < cohorte_corte_dt)

        desenlace = _classify_palma_outcome_detailed(r.get("estado_id"), r.get("estado_nombre"))
        cita_en_periodo = bool(r.get("cita_visita_en_periodo"))
        cierre_en_periodo = bool(r.get("cierre_en_periodo"))

        tuvo_cv = bool(r.get("tuvo_contacto_cv") or r.get("tuvo_hist_cv") or desenlace in ("cita", "visita"))
        tuvo_tropiezo = bool(
            r.get("tuvo_ce_tropiezo")
            or r.get("tuvo_hist_tropiezo")
            or (r.get("total_citas_reg") or 0) >= 2
        )
        concretada = bool(
            r.get("tuvo_ce_completada")
            or r.get("tuvo_hist_completada")
            or desenlace in ("visita", "negociacion", "separacion", "venta")
        )
        recuperada = bool(tuvo_tropiezo and concretada)

        primera_cv_lima = _to_lima(r.get("primera_hist_cv_at") or r.get("primera_contacto_cv_at") or r.get("ultima_fecha_cita"))
        cierre_lima = _to_lima(r.get("ultima_hist_pos_at") or r.get("ultimo_cambio_pos_at") or r.get("updated_at"))

        dias_hasta_cita = None
        if created_lima and primera_cv_lima:
            dias_hasta_cita = max(round((primera_cv_lima - created_lima).total_seconds() / 86400, 1), 0.0)
        dias_hasta_cierre = None
        if created_lima and cierre_lima and desenlace in ("separacion", "venta"):
            dias_hasta_cierre = max(round((cierre_lima - created_lima).total_seconds() / 86400, 1), 0.0)

        # Logros en el período seleccionado
        if cita_en_periodo:
            if es_mes_anterior:
                citas_visitas_mes_anterior += 1
            else:
                citas_visitas_mismo_mes += 1
            if dias_hasta_cita is not None:
                maduracion_cita_dias.append(dias_hasta_cita)

        if cierre_en_periodo:
            if desenlace == "separacion":
                if es_mes_anterior:
                    separaciones_mes_anterior += 1
                else:
                    separaciones_mismo_mes += 1
            elif desenlace == "venta":
                if es_mes_anterior:
                    ventas_mes_anterior += 1
                else:
                    ventas_mismo_mes += 1
            if dias_hasta_cierre is not None:
                maduracion_cierre_dias.append(dias_hasta_cierre)

        # Embudo sobre universo que tuvo actividad de cita/visita o cierre en el período
        en_universo_periodo = cita_en_periodo or cierre_en_periodo
        if en_universo_periodo:
            embudo_tot["total_flujo"] += 1
            if tuvo_cv:
                embudo_tot["agendadas"] += 1
            if tuvo_tropiezo:
                embudo_tot["con_tropiezo"] += 1
            if recuperada:
                embudo_tot["recuperadas_tropiezo"] += 1
            if concretada:
                embudo_tot["concretaron_cita_visita"] += 1
            if desenlace == "separacion":
                embudo_tot["separaciones"] += 1
            elif desenlace == "venta":
                embudo_tot["ventas"] += 1
            elif desenlace == "perdido":
                embudo_tot["perdidos"] += 1

            coh = _ensure_cohorte(cohorte_ym)
            if cita_en_periodo:
                coh["citas_visitas_periodo"] += 1
            if cierre_en_periodo and desenlace == "separacion":
                coh["separaciones_periodo"] += 1
            if cierre_en_periodo and desenlace == "venta":
                coh["ventas_periodo"] += 1
            if tuvo_tropiezo:
                coh["tropiezos"] += 1
            if recuperada:
                coh["recuperadas"] += 1

            as_item = _ensure_asesor(r)
            if cita_en_periodo:
                if es_mes_anterior:
                    as_item["citas_meses_anteriores"] += 1
                else:
                    as_item["citas_mes_actual"] += 1
            if cierre_en_periodo and desenlace == "separacion":
                if es_mes_anterior:
                    as_item["separaciones_meses_anteriores"] += 1
                else:
                    as_item["separaciones_mes_actual"] += 1
            if cierre_en_periodo and desenlace == "venta":
                if es_mes_anterior:
                    as_item["ventas_meses_anteriores"] += 1
                else:
                    as_item["ventas_mes_actual"] += 1
            if tuvo_tropiezo:
                as_item["tropiezos"] += 1
            if recuperada:
                as_item["recuperadas_tropiezo"] += 1
            if dias_hasta_cierre is not None:
                as_item["maduracion_dias_sum"] += dias_hasta_cierre
                as_item["maduracion_dias_cnt"] += 1

            item_out = {
                "id": r.get("id"),
                "nombre": r.get("nombre"),
                "telefono": r.get("telefono"),
                "estado_nombre": r.get("estado_nombre"),
                "estado_color": r.get("estado_color"),
                "desenlace": desenlace,
                "fuente_nombre": r.get("fuente_nombre"),
                "sede_nombre": r.get("sede_nombre"),
                "asesor_id": r.get("asesor_id"),
                "asesor_nombre": (r.get("asesor_nombre") or "").strip() or "Sin asignar",
                "supervisor_nombre": (r.get("supervisor_nombre") or "").strip() or "Sin supervisor",
                "cohorte_mes": cohorte_ym,
                "cohorte_label": _format_cohorte_label(cohorte_ym),
                "es_mes_anterior": es_mes_anterior,
                "cita_visita_en_periodo": cita_en_periodo,
                "cierre_en_periodo": cierre_en_periodo,
                "tuvo_tropiezo": tuvo_tropiezo,
                "recuperada_tropiezo": recuperada,
                "concretada": concretada,
                "total_citas_reg": r.get("total_citas_reg") or 0,
                "cambios_cita_hist": r.get("cambios_cita_hist") or 0,
                "ultima_cita_estado_nombre": r.get("ultima_cita_estado_nombre"),
                "ultima_cita_estado_color": r.get("ultima_cita_estado_color"),
                "dias_hasta_cita": dias_hasta_cita,
                "dias_hasta_cierre": dias_hasta_cierre,
                "created_at": created_lima.isoformat() if created_lima else None,
                "ultima_fecha_cita": r["ultima_fecha_cita"].isoformat() if hasattr(r.get("ultima_fecha_cita"), "isoformat") else r.get("ultima_fecha_cita"),
            }
            leads_embudo.append(item_out)
            if es_mes_anterior:
                leads_recuperados.append(item_out)

    # Cartera antigua interesada
    cartera_con_gestion_reciente = 0
    cartera_con_intento_cita_fallido = 0
    leads_cartera_out: list[dict] = []
    now_lima = datetime.now(LIMA_TZ)

    for c_row in cartera_rows:
        created_lima = _to_lima(c_row.get("created_at"))
        cohorte_ym = created_lima.strftime("%Y-%m") if created_lima else "Sin fecha"
        dias_antig = max(round((now_lima - created_lima).total_seconds() / 86400, 1), 0.0) if created_lima else None

        coh = _ensure_cohorte(cohorte_ym)
        coh["cartera_antigua_activa"] += 1

        gestiones_rec = (c_row.get("contactos_periodo") or 0) + (c_row.get("llamadas_periodo") or 0)
        if gestiones_rec > 0:
            cartera_con_gestion_reciente += 1
            as_item = _ensure_asesor(c_row)
            as_item["cartera_antigua_gestionada"] += 1
        if c_row.get("tuvo_intento_cita"):
            cartera_con_intento_cita_fallido += 1

        leads_cartera_out.append({
            "id": c_row.get("id"),
            "nombre": c_row.get("nombre"),
            "telefono": c_row.get("telefono"),
            "estado_nombre": c_row.get("estado_nombre"),
            "estado_color": c_row.get("estado_color"),
            "fuente_nombre": c_row.get("fuente_nombre"),
            "asesor_id": c_row.get("asesor_id"),
            "asesor_nombre": (c_row.get("asesor_nombre") or "").strip() or "Sin asignar",
            "supervisor_nombre": (c_row.get("supervisor_nombre") or "").strip() or "Sin supervisor",
            "cohorte_mes": cohorte_ym,
            "cohorte_label": _format_cohorte_label(cohorte_ym),
            "dias_antiguedad": dias_antig,
            "contactos_periodo": c_row.get("contactos_periodo") or 0,
            "llamadas_periodo": c_row.get("llamadas_periodo") or 0,
            "gestiones_periodo": gestiones_rec,
            "tuvo_intento_cita": bool(c_row.get("tuvo_intento_cita")),
            "accion_proxima_gestion": c_row.get("accion_proxima_gestion"),
            "created_at": created_lima.isoformat() if created_lima else None,
            "fecha_proxima_gestion": c_row["fecha_proxima_gestion"].isoformat() if hasattr(c_row.get("fecha_proxima_gestion"), "isoformat") else c_row.get("fecha_proxima_gestion"),
            "ultimo_contacto_at": c_row["ultimo_contacto_at"].isoformat() if hasattr(c_row.get("ultimo_contacto_at"), "isoformat") else c_row.get("ultimo_contacto_at"),
        })

    por_cohorte_mes = sorted(
        cohortes_map.values(),
        key=lambda x: x["cohorte_mes"],
        reverse=True,
    )

    por_asesor = []
    for a in asesores_map.values():
        total_citas_a = a["citas_mes_actual"] + a["citas_meses_anteriores"]
        total_cierres_a = (
            a["separaciones_mes_actual"] + a["separaciones_meses_anteriores"]
            + a["ventas_mes_actual"] + a["ventas_meses_anteriores"]
        )
        cierres_recuperados_a = a["separaciones_meses_anteriores"] + a["ventas_meses_anteriores"]
        cnt_m = a.pop("maduracion_dias_cnt")
        sum_m = a.pop("maduracion_dias_sum")
        a["total_citas_periodo"] = total_citas_a
        a["total_cierres_periodo"] = total_cierres_a
        a["cierres_meses_anteriores"] = cierres_recuperados_a
        a["pct_recuperacion_tropiezo"] = _pct(a["recuperadas_tropiezo"], a["tropiezos"])
        a["pct_aporte_meses_anteriores"] = _pct(
            a["citas_meses_anteriores"] + cierres_recuperados_a,
            total_citas_a + total_cierres_a,
        )
        a["maduracion_promedio_dias"] = round(sum_m / cnt_m, 1) if cnt_m > 0 else None
        por_asesor.append(a)

    por_asesor.sort(
        key=lambda x: (
            -(x["cierres_meses_anteriores"] + x["citas_meses_anteriores"]),
            -x["total_cierres_periodo"],
            -x["total_citas_periodo"],
            x["asesor_nombre"],
        )
    )

    total_citas_periodo = citas_visitas_mismo_mes + citas_visitas_mes_anterior
    total_sep_periodo = separaciones_mismo_mes + separaciones_mes_anterior
    total_ventas_periodo = ventas_mismo_mes + ventas_mes_anterior
    total_cierres_periodo = total_sep_periodo + total_ventas_periodo
    total_cierres_mes_anterior = separaciones_mes_anterior + ventas_mes_anterior

    embudo_etapas = [
        {"codigo": "agendadas", "label": "Citas / Visitas en flujo", "total": embudo_tot["agendadas"], "color": "#6366F1"},
        {"codigo": "con_tropiezo", "label": "Tuvieron tropiezo (Reprog. / No asistió)", "total": embudo_tot["con_tropiezo"], "color": "#F59E0B"},
        {"codigo": "recuperadas", "label": "Recuperadas tras tropiezo", "total": embudo_tot["recuperadas_tropiezo"], "color": "#8B5CF6"},
        {"codigo": "concretadas", "label": "Concretaron Cita / Visita", "total": embudo_tot["concretaron_cita_visita"], "color": "#0EA5E9"},
        {"codigo": "separaciones", "label": "Separación / Reserva", "total": embudo_tot["separaciones"], "color": "#14B8A6"},
        {"codigo": "ventas", "label": "Venta Concretada", "total": embudo_tot["ventas"], "color": "#10B981"},
        {"codigo": "perdidos", "label": "Desistió / Perdido", "total": embudo_tot["perdidos"], "color": "#EF4444"},
    ]

    leads_recuperados.sort(
        key=lambda x: (
            0 if x["cierre_en_periodo"] else 1,
            -(x["dias_hasta_cierre"] or x["dias_hasta_cita"] or 0),
        )
    )

    return {
        "periodo": periodo,
        "cohorte_corte_mes": cohorte_corte_mes,
        "rango_fechas": {
            "fecha_inicio": start_dt.strftime("%Y-%m-%d") if start_dt else None,
            "fecha_fin": end_dt.strftime("%Y-%m-%d") if end_dt else None,
            "dias": dias_count,
        },
        "resumen": {
            "total_citas_visitas_periodo": total_citas_periodo,
            "citas_visitas_mismo_mes": citas_visitas_mismo_mes,
            "citas_visitas_mes_anterior": citas_visitas_mes_anterior,
            "pct_citas_mes_anterior": _pct(citas_visitas_mes_anterior, total_citas_periodo),
            "total_separaciones_periodo": total_sep_periodo,
            "separaciones_mismo_mes": separaciones_mismo_mes,
            "separaciones_mes_anterior": separaciones_mes_anterior,
            "total_ventas_periodo": total_ventas_periodo,
            "ventas_mismo_mes": ventas_mismo_mes,
            "ventas_mes_anterior": ventas_mes_anterior,
            "total_cierres_periodo": total_cierres_periodo,
            "cierres_mes_anterior": total_cierres_mes_anterior,
            "pct_cierres_mes_anterior": _pct(total_cierres_mes_anterior, total_cierres_periodo),
            "maduracion_cita_promedio_dias": round(sum(maduracion_cita_dias) / len(maduracion_cita_dias), 1) if maduracion_cita_dias else None,
            "maduracion_cita_mediana_dias": _median(maduracion_cita_dias),
            "maduracion_cierre_promedio_dias": round(sum(maduracion_cierre_dias) / len(maduracion_cierre_dias), 1) if maduracion_cierre_dias else None,
            "maduracion_cierre_mediana_dias": _median(maduracion_cierre_dias),
            "pct_recuperacion_tropiezo": _pct(embudo_tot["recuperadas_tropiezo"], embudo_tot["con_tropiezo"]),
            "cartera_antigua_total": len(leads_cartera_out),
            "cartera_antigua_con_gestion_reciente": cartera_con_gestion_reciente,
            "cartera_antigua_con_intento_cita": cartera_con_intento_cita_fallido,
        },
        "embudo": embudo_etapas,
        "por_cohorte_mes": por_cohorte_mes,
        "por_asesor": por_asesor,
        "leads_recuperados": leads_recuperados[:300],
        "leads_cartera_antigua": leads_cartera_out[:300],
        "leads_embudo": leads_embudo[:300],
    }

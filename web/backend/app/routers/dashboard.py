"""
Dashboard router — KPIs y métricas del CRM.
- GET /api/dashboard/resumen        — KPIs del usuario según su rol
- GET /api/dashboard/kpis-asesores  — detalle por asesor (supervisor/admin)
- GET /api/dashboard/pendientes     — leads que necesitan atención urgente
- GET /api/dashboard/catalogs       — fuentes y estados para filtros del frontend

V096 — endpoints time-windowed:
Los endpoints /resumen, /actividad-equipo, /referidos, /leads-por-fuente
y /funnel-conversion ahora aceptan ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD.
Default = últimos 7 días. Devuelven metricas del periodo + comparativa con
el periodo anterior equivalente. Las metricas snapshot (total_leads,
funnel-state) se mantienen sin filtrar; solo las metricas de FLOW responden
al rango.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor
from app.auth.jwt import get_current_user, require_supervisor_or_admin
from app.auth.permissions import can_view_all_data
from app.auth.schemas import TokenData
from app.database import get_db
from app.filters.lead_filters import role_filter
from app.utils.date_range import DateRange, parse_date_range

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/resumen")
def resumen(
    current_user: TokenData = Depends(get_current_user),
    date_range:   DateRange = Depends(parse_date_range),
):
    """KPIs del dashboard — mismos campos para todos los roles.

    Snapshot (no responden al filtro de fecha):
      total_leads, nuevos, contactados, calificados, en_negociacion,
      ganados, perdidos, no_interesados, tasa_conversion_pct
      (todos reflejan el estado CURRENT de la base completa).

    Flow del periodo (responden a ?start_date=&end_date=):
      period_metrics.leads_creados, contactos_realizados, ganados_periodo,
      tasa_conversion_periodo_pct
    + previous_period_metrics con los mismos campos para comparacion (
      computa el periodo anterior simetrico).

    Compat legacy: leads_hoy y leads_7dias se mantienen (no rompemos
    consumidores existentes — mobile, integraciones).

    El filtrado de leads por rol se aplica via role_filter():
      - admin:      todos los leads
      - supervisor: leads de su equipo
      - asesor:     solo sus leads
    """
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── 1. Snapshot (sin filtro de fecha) ───────────────────────────
            cur.execute(
                f"""
                SELECT
                    COUNT(*)                                       AS total_leads,
                    COUNT(*) FILTER (WHERE e.nombre = 'Nuevo')     AS nuevos,
                    COUNT(*) FILTER (WHERE e.nombre = 'Contactado') AS contactados,
                    COUNT(*) FILTER (WHERE e.nombre = 'Calificado') AS calificados,
                    COUNT(*) FILTER (WHERE UPPER(COALESCE(l.calidad, '')) = 'TIBIO') AS tibios,
                    COUNT(*) FILTER (WHERE UPPER(COALESCE(l.calidad, '')) = 'CALIENTE') AS calientes,
                    COUNT(*) FILTER (WHERE e.nombre = 'En negociación') AS en_negociacion,
                    COUNT(*) FILTER (WHERE e.nombre ILIKE '%%seguimiento%%') AS en_seguimiento,
                    COUNT(*) FILTER (WHERE e.nombre = 'Ganado')    AS ganados,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                              AS matriculas,
                    COUNT(*) FILTER (WHERE e.nombre = 'Perdido' OR e.nombre ILIKE '%%perdid%%') AS perdidos,
                    COUNT(*) FILTER (WHERE e.nombre = 'No interesado') AS no_interesados,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%cod%%'
                           OR e.nombre ILIKE '%%reserva%%'
                           OR e.nombre ILIKE '%%compromiso%%'
                    )                                              AS cod,
                    COUNT(*) FILTER (WHERE l.created_at >= CURRENT_DATE::timestamptz) AS leads_hoy,
                    COUNT(*) FILTER (WHERE l.created_at >= NOW() - INTERVAL '7 days') AS leads_7dias,
                    ROUND(
                        100.0 * COUNT(*) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) / NULLIF(COUNT(*),0),
                        2
                    )                                              AS tasa_conversion_pct
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND ({role_clause})
                """,
                role_params,
            )
            snapshot = dict(cur.fetchone() or {})

            # ── 2. Flow del periodo seleccionado ────────────────────────────
            # Cohorte = leads creados en [start, end]. Computa cuantos de
            # esos leads ya estan contactados, ganados, etc — eso da una
            # vista clara de "como va el periodo".
            cur.execute(
                f"""
                SELECT
                    COUNT(*)                                                       AS leads_creados,
                    COUNT(*) FILTER (WHERE lc.contactado IS NOT NULL)              AS leads_contactados,
                    COUNT(*) FILTER (WHERE e.nombre = 'Nuevo')                     AS nuevos,
                    COUNT(*) FILTER (WHERE e.nombre = 'Contactado')                AS contactados,
                    COUNT(*) FILTER (WHERE e.nombre = 'Calificado')                AS calificados,
                    COUNT(*) FILTER (WHERE UPPER(COALESCE(l.calidad, '')) = 'TIBIO') AS tibios,
                    COUNT(*) FILTER (WHERE UPPER(COALESCE(l.calidad, '')) = 'CALIENTE') AS calientes,
                    COUNT(*) FILTER (WHERE e.nombre = 'En negociación')            AS en_negociacion,
                    COUNT(*) FILTER (WHERE e.nombre ILIKE '%%seguimiento%%')       AS en_seguimiento,
                    COUNT(*) FILTER (WHERE e.nombre = 'Ganado')                    AS leads_ganados,
                    COUNT(*) FILTER (WHERE e.nombre = 'Ganado')                    AS ganados,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                                              AS matriculas,
                    COUNT(*) FILTER (
                        WHERE e.nombre = 'Perdido'
                           OR e.nombre ILIKE '%%perdid%%'
                           OR e.nombre = 'No interesado'
                           OR e.nombre ILIKE '%%no inter%%'
                    )                                                              AS perdidos,
                    COUNT(*) FILTER (
                        WHERE e.nombre IN ('Perdido','No interesado')
                           OR e.nombre ILIKE '%%perdid%%'
                    )                                                              AS leads_perdidos,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%cod%%'
                           OR e.nombre ILIKE '%%reserva%%'
                           OR e.nombre ILIKE '%%compromiso%%'
                    )                                                              AS cod,
                    ROUND(
                        100.0 * COUNT(*) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) / NULLIF(COUNT(*),0),
                        2
                    )                                                              AS tasa_conversion_pct
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN LATERAL (
                    SELECT 1 AS contactado
                    FROM crm.contactos c
                    WHERE c.lead_id = l.id
                      AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                    UNION ALL
                    SELECT 1 AS contactado
                    FROM crm.llamadas ll
                    WHERE ll.lead_id = l.id
                    LIMIT 1
                ) lc ON TRUE
                WHERE l.activo = TRUE
                  AND l.created_at >= %s
                  AND l.created_at <= %s
                  AND ({role_clause})
                """,
                [date_range.start, date_range.end] + role_params,
            )
            period = dict(cur.fetchone() or {})

            # ── 3. Mismas metricas para el periodo anterior (comparacion) ───
            cur.execute(
                f"""
                SELECT
                    COUNT(*)                                                       AS leads_creados,
                    COUNT(*) FILTER (WHERE lc.contactado IS NOT NULL)              AS leads_contactados,
                    COUNT(*) FILTER (WHERE e.nombre = 'Nuevo')                     AS nuevos,
                    COUNT(*) FILTER (WHERE e.nombre = 'Contactado')                AS contactados,
                    COUNT(*) FILTER (WHERE e.nombre = 'Calificado')                AS calificados,
                    COUNT(*) FILTER (WHERE UPPER(COALESCE(l.calidad, '')) = 'TIBIO') AS tibios,
                    COUNT(*) FILTER (WHERE UPPER(COALESCE(l.calidad, '')) = 'CALIENTE') AS calientes,
                    COUNT(*) FILTER (WHERE e.nombre = 'En negociación')            AS en_negociacion,
                    COUNT(*) FILTER (WHERE e.nombre ILIKE '%%seguimiento%%')       AS en_seguimiento,
                    COUNT(*) FILTER (WHERE e.nombre = 'Ganado')                    AS leads_ganados,
                    COUNT(*) FILTER (WHERE e.nombre = 'Ganado')                    AS ganados,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                                              AS matriculas,
                    COUNT(*) FILTER (
                        WHERE e.nombre = 'Perdido'
                           OR e.nombre ILIKE '%%perdid%%'
                           OR e.nombre = 'No interesado'
                           OR e.nombre ILIKE '%%no inter%%'
                    )                                                              AS perdidos,
                    COUNT(*) FILTER (
                        WHERE e.nombre IN ('Perdido','No interesado')
                           OR e.nombre ILIKE '%%perdid%%'
                    )                                                              AS leads_perdidos,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%cod%%'
                           OR e.nombre ILIKE '%%reserva%%'
                           OR e.nombre ILIKE '%%compromiso%%'
                    )                                                              AS cod,
                    ROUND(
                        100.0 * COUNT(*) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) / NULLIF(COUNT(*),0),
                        2
                    )                                                              AS tasa_conversion_pct
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN LATERAL (
                    SELECT 1 AS contactado
                    FROM crm.contactos c
                    WHERE c.lead_id = l.id
                      AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                    UNION ALL
                    SELECT 1 AS contactado
                    FROM crm.llamadas ll
                    WHERE ll.lead_id = l.id
                    LIMIT 1
                ) lc ON TRUE
                WHERE l.activo = TRUE
                  AND l.created_at >= %s
                  AND l.created_at <= %s
                  AND ({role_clause})
                """,
                [date_range.prev_start, date_range.prev_end] + role_params,
            )
            prev_period = dict(cur.fetchone() or {})

    snapshot["period_metrics"]          = period
    snapshot["previous_period_metrics"] = prev_period
    snapshot["period"]                  = date_range.as_dict()
    return snapshot


@router.get("/kpis-asesores")
def kpis_asesores(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if can_view_all_data(current_user, "dashboards"):
                cur.execute(
                    """
                    SELECT asesor_id::text, asesor_nombre, asesor_email,
                           supervisor_id::text, supervisor_nombre,
                           total_leads, leads_nuevo, leads_contactado,
                           leads_calificado, leads_en_negociacion,
                           leads_ganado, leads_perdido, leads_no_interesado,
                           leads_sin_contacto, leads_accion_vencida,
                           tasa_conversion_pct
                    FROM crm.vw_kpis_por_asesor
                    ORDER BY total_leads DESC
                    """
                )
            elif current_user.role == "supervisor":
                # Supervisor: solo sus asesores
                cur.execute(
                    """
                    SELECT asesor_id::text, asesor_nombre, asesor_email,
                           supervisor_id::text, supervisor_nombre,
                           total_leads, leads_nuevo, leads_contactado,
                           leads_calificado, leads_en_negociacion,
                           leads_ganado, leads_perdido, leads_no_interesado,
                           leads_sin_contacto, leads_accion_vencida,
                           tasa_conversion_pct
                    FROM crm.vw_kpis_por_asesor
                    WHERE supervisor_id = %s::uuid
                    ORDER BY total_leads DESC
                    """,
                    (current_user.user_id,),
                )
            else:
                # Asesor o rol custom sin dashboards.view_all: solo su propia fila
                cur.execute(
                    """
                    SELECT asesor_id::text, asesor_nombre, asesor_email,
                           supervisor_id::text, supervisor_nombre,
                           total_leads, leads_nuevo, leads_contactado,
                           leads_calificado, leads_en_negociacion,
                           leads_ganado, leads_perdido, leads_no_interesado,
                           leads_sin_contacto, leads_accion_vencida,
                           tasa_conversion_pct
                    FROM crm.vw_kpis_por_asesor
                    WHERE asesor_id = %s::uuid
                    ORDER BY total_leads DESC
                    """,
                    (current_user.user_id,),
                )
            return cur.fetchall()


@router.get("/pendientes")
def pendientes(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if can_view_all_data(current_user, "dashboards"):
                cur.execute(
                    """
                    SELECT id, nombre_completo, telefono, email,
                           estado_nombre, fuente_nombre,
                           asesor_id::text, asesor_nombre,
                           fecha_ingreso::text, fecha_ultimo_contacto::text,
                           fecha_proxima_accion::text,
                           ROUND(horas_sin_contacto::numeric, 1) AS horas_sin_contacto,
                           tipo_pendiente
                    FROM crm.vw_leads_pendientes
                    LIMIT 100
                    """
                )
            elif current_user.role == "supervisor":
                cur.execute(
                    """
                    SELECT v.id, v.nombre_completo, v.telefono, v.email,
                           v.estado_nombre, v.fuente_nombre,
                           v.asesor_id::text, v.asesor_nombre,
                           v.fecha_ingreso::text, v.fecha_ultimo_contacto::text,
                           v.fecha_proxima_accion::text,
                           ROUND(v.horas_sin_contacto::numeric, 1) AS horas_sin_contacto,
                           v.tipo_pendiente
                    FROM crm.vw_leads_pendientes v
                    WHERE (v.asesor_id IN (
                        SELECT asesor_id FROM crm.equipos
                        WHERE supervisor_id = %s::uuid AND activo = TRUE
                    ) OR v.asesor_id = %s::uuid)
                    LIMIT 100
                    """,
                    (current_user.user_id, current_user.user_id),
                )
            else:
                cur.execute(
                    """
                    SELECT v.id, v.nombre_completo, v.telefono, v.email,
                           v.estado_nombre, v.fuente_nombre,
                           v.asesor_id::text, v.asesor_nombre,
                           v.fecha_ingreso::text, v.fecha_ultimo_contacto::text,
                           v.fecha_proxima_accion::text,
                           ROUND(v.horas_sin_contacto::numeric, 1) AS horas_sin_contacto,
                           v.tipo_pendiente
                    FROM crm.vw_leads_pendientes v
                    WHERE v.asesor_id = %s::uuid
                    LIMIT 100
                    """,
                    (current_user.user_id,),
                )
            return cur.fetchall()


from app.filters.lead_filters import LeadFilters, lead_filters_query, apply_lead_filters
from app.repositories import leads_repository


@router.get("/referidos")
def referidos(
    current_user: TokenData = Depends(get_current_user),
    date_range:   DateRange = Depends(parse_date_range),
):
    """KPIs de referidos: total, mes actual, hoy, ganados + del periodo.

    Un lead se considera referido si su fuente es 'referido'
    o si tiene el campo `referido_por` no nulo (creados via "Nuevo Lead"
    pueden no tener fuente_id pero sí referido_por).

    V096 — incluye en_periodo + en_periodo_anterior para comparativa
    con el selector temporal del dashboard.
    """
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH ref AS (
                    SELECT l.id, l.created_at, l.estado_id, e.nombre AS estado
                    FROM crm.leads l
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.activo = TRUE
                      AND ({role_clause})
                      AND (
                          LOWER(COALESCE(f.nombre,'')) LIKE '%%referid%%'
                          OR (l.referido_por IS NOT NULL AND TRIM(l.referido_por) <> '')
                      )
                )
                SELECT
                    COUNT(*)                                                              AS total,
                    COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE)                    AS hoy,
                    COUNT(*) FILTER (WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)) AS mes,
                    COUNT(*) FILTER (WHERE estado = 'Ganado')                             AS ganados,
                    COUNT(*) FILTER (WHERE created_at >= %s AND created_at <= %s)         AS en_periodo,
                    COUNT(*) FILTER (WHERE created_at >= %s AND created_at <= %s)         AS en_periodo_anterior,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE estado = 'Ganado') / NULLIF(COUNT(*),0),
                        1
                    )                                                                     AS tasa_conversion_pct
                FROM ref
                """,
                role_params + [
                    date_range.start, date_range.end,
                    date_range.prev_start, date_range.prev_end,
                ],
            )
            return cur.fetchone() or {
                "total": 0, "hoy": 0, "mes": 0, "ganados": 0,
                "en_periodo": 0, "en_periodo_anterior": 0,
                "tasa_conversion_pct": 0,
            }


@router.get("/leads-por-estado")
def leads_por_estado(
    filters: LeadFilters = Depends(lead_filters_query),
    current_user: TokenData = Depends(get_current_user),
):
    """Distribución de leads por estado, respetando los mismos filtros que
    /api/leads para que los contadores de las pestañas coincidan con la
    tabla filtrada."""
    return leads_repository.count_by_estado(filters, current_user)


@router.get("/leads-por-fuente")
def leads_por_fuente(
    current_user: TokenData = Depends(get_current_user),
    date_range:   DateRange = Depends(parse_date_range),
):
    """Distribución de leads por fuente — cohorte del periodo seleccionado.

    V096 — filtra por leads ingresados en el rango. Antes era acumulativo
    historico; ahora es "leads que ENTRARON en el periodo, agrupados por
    fuente". Mas accionable para el manager.
    """
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT COALESCE(f.nombre, 'sin fuente') AS fuente, COUNT(l.id) AS count
                FROM crm.leads l
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                WHERE l.activo = TRUE
                  AND l.created_at >= %s
                  AND l.created_at <= %s
                  AND ({role_clause})
                GROUP BY f.nombre
                ORDER BY count DESC
                """,
                [date_range.start, date_range.end] + role_params,
            )
            return cur.fetchall()


@router.get("/tendencia")
def tendencia(
    dias: int = 30,
    current_user: TokenData = Depends(get_current_user),
):
    """Leads ingresados por día en los últimos N días."""
    role_clause, role_params = role_filter(current_user)
    # dias va después del role_clause en la query
    params = role_params + [dias]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT fecha::text, COUNT(*) AS count
                FROM (
                    SELECT l.created_at::date AS fecha
                    FROM crm.leads l
                    WHERE l.activo = TRUE
                      AND ({role_clause})
                      AND l.created_at >= NOW() - (%s || ' days')::INTERVAL
                ) sub
                GROUP BY fecha
                ORDER BY fecha
                """,
                params,
            )
            return cur.fetchall()


@router.get("/tendencia-semanal")
def tendencia_semanal(
    semanas: int = 12,
    current_user: TokenData = Depends(get_current_user),
):
    """V095.1 — Tendencia semanal (default 12 semanas).

    Dos series alineadas por semana ISO:
      - leads_nuevos:        ingresaron en esa semana
      - leads_contactados:   ingresaron en esa semana Y recibieron al menos
                             un contacto real (no 'cambio_estado')

    Anclamos la serie al lunes de cada semana (DATE_TRUNC week en Lima TZ).
    Patron CRM clase mundial (patrón estándar, patrón estándar): el primer widget visible
    debe transmitir movimiento — sin esto, el dashboard se siente estatico.

    Performance: O(N) por GROUP BY sobre los ultimos 12*7=84 dias. Indice
    en created_at hace que escale bien hasta cientos de miles de leads.
    """
    semanas = max(1, min(semanas, 52))
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH semanas_serie AS (
                    -- Genera N filas: hoy, hoy-7d, hoy-14d, ... -> lunes de cada una.
                    SELECT
                        DATE_TRUNC('week',
                            (NOW() AT TIME ZONE 'America/Lima')::date - (gs * 7)
                        )::date AS semana_inicio
                    FROM generate_series(0, %s - 1) AS gs
                ),
                leads_periodo AS (
                    SELECT
                        DATE_TRUNC('week',
                            (l.created_at AT TIME ZONE 'America/Lima')::date
                        )::date AS semana_inicio,
                        l.id,
                        (
                            EXISTS(
                                SELECT 1 FROM crm.contactos c
                                WHERE c.lead_id = l.id
                                  AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            ) OR EXISTS (
                                SELECT 1 FROM crm.llamadas ll
                                WHERE ll.lead_id = l.id
                            )
                        ) AS tuvo_contacto
                    FROM crm.leads l
                    WHERE l.activo = TRUE
                      AND (l.created_at AT TIME ZONE 'America/Lima')::date >=
                          DATE_TRUNC('week',
                            (NOW() AT TIME ZONE 'America/Lima')::date - ((%s - 1) * 7)
                          )::date
                      AND ({role_clause})
                )
                SELECT
                    s.semana_inicio::text AS semana,
                    COALESCE(COUNT(lp.id), 0)::int AS leads_nuevos,
                    COALESCE(COUNT(lp.id) FILTER (WHERE lp.tuvo_contacto), 0)::int
                                                     AS leads_contactados
                FROM semanas_serie s
                LEFT JOIN leads_periodo lp ON lp.semana_inicio = s.semana_inicio
                GROUP BY s.semana_inicio
                ORDER BY s.semana_inicio
                """,
                [semanas, semanas] + role_params,
            )
            rows = cur.fetchall()
    return {"semanas": rows}


@router.get("/sparklines")
def sparklines(
    current_user: TokenData = Depends(get_current_user),
    date_range:   DateRange = Depends(parse_date_range),
):
    """Series diarias para sparklines en las KPI cards (V096).

    Devuelve dos series alineadas por dia dentro del periodo seleccionado:
      - leads_creados:       cuantos leads ingresaron cada dia
      - contactos_realizados: cuantos contactos se hicieron cada dia

    Ambas con la misma estructura: [{date: 'YYYY-MM-DD', count: int}, ...].
    Los dias sin actividad NO aparecen (el frontend rellena con 0). Para
    periodos largos (>90 dias) la query sigue siendo O(N) por groupby de
    fecha — barato con indice en created_at.
    """
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT (l.created_at AT TIME ZONE 'America/Lima')::date::text AS date,
                       COUNT(*)::int AS count
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND l.created_at >= %s
                  AND l.created_at <= %s
                  AND ({role_clause})
                GROUP BY (l.created_at AT TIME ZONE 'America/Lima')::date
                ORDER BY date
                """,
                [date_range.start, date_range.end] + role_params,
            )
            leads_creados = cur.fetchall()

            cur.execute(
                f"""
                SELECT (c.created_at AT TIME ZONE 'America/Lima')::date::text AS date,
                       COUNT(*)::int AS count
                FROM crm.contactos c
                JOIN crm.leads l ON l.id = c.lead_id
                WHERE l.activo = TRUE
                  AND c.created_at >= %s
                  AND c.created_at <= %s
                  AND ({role_clause})
                GROUP BY (c.created_at AT TIME ZONE 'America/Lima')::date
                ORDER BY date
                """,
                [date_range.start, date_range.end] + role_params,
            )
            contactos = cur.fetchall()

    return {
        "leads_creados":       leads_creados,
        "contactos_realizados": contactos,
        "period":              date_range.as_dict(),
    }


@router.get("/leads-por-asesor")
def leads_por_asesor(
    current_user: TokenData = Depends(require_supervisor_or_admin),
    date_range: Optional[DateRange] = Depends(parse_date_range),
):
    """KPIs por asesor para el ranking Top Asesores del Dashboard — basado en matrículas."""
    role_clause, role_params = role_filter(current_user)

    date_filter = ""
    params = []
    if date_range and date_range.start and date_range.end:
        date_filter = "AND l.created_at >= %s AND l.created_at <= %s"
        params = [date_range.start, date_range.end]

    params = params + list(role_params)

    if current_user.role == "supervisor":
        user_filter = (
            "AND (u.id IN "
            "(SELECT asesor_id FROM crm.equipos WHERE supervisor_id = %s::uuid AND activo = TRUE) "
            "OR u.id = %s::uuid)"
        )
        sup_params = [current_user.user_id, current_user.user_id]
    else:
        user_filter = ""
        sup_params = []

    all_params = params + sup_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    u.id::text                                                         AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre_completo,
                    u.role                                                             AS rol,
                    COUNT(l.id)::int                                                   AS total_leads,
                    COUNT(l.id) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )::int                                                             AS matriculas,
                    COALESCE(ROUND(
                        100.0 * COUNT(l.id) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) / NULLIF(COUNT(l.id), 0), 1
                    ), 0)::float                                                       AS tasa_conversion
                FROM auth.users u
                LEFT JOIN crm.leads l
                    ON  l.asesor_id = u.id
                    AND l.activo = TRUE
                    {date_filter}
                    AND ({role_clause})
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE u.role IN ('asesor', 'supervisor')
                  AND u.is_active = TRUE
                  {user_filter}
                GROUP BY u.id, u.first_name, u.last_name, u.role
                HAVING COUNT(l.id) > 0
                ORDER BY matriculas DESC, tasa_conversion DESC, total_leads DESC
                """,
                all_params,
            )
            return cur.fetchall()


@router.get("/catalogs")
def catalogs(current_user: TokenData = Depends(get_current_user)):
    """Fuentes, estados y asesores para poblar filtros y formularios del frontend."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, nombre, color_hex, es_final, orden FROM crm.estados_lead ORDER BY orden")
            estados = cur.fetchall()

            cur.execute("SELECT id, nombre FROM crm.fuentes WHERE activo = TRUE ORDER BY nombre")
            fuentes = cur.fetchall()

            # Asesores disponibles según rol
            # Incluimos `role` para que el frontend pueda diferenciar
            # asesores de supervisores en el dropdown (badge "Supervisor").
            if current_user.role == "admin":
                cur.execute(
                    """
                    SELECT id::text, email, role,
                           TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre_completo
                    FROM auth.users
                    WHERE role IN ('asesor','supervisor') AND is_active = TRUE
                    ORDER BY role DESC, first_name
                    """
                )
            elif current_user.role == "supervisor":
                # Su equipo + el mismo + OTROS supervisores activos
                # (cross-derivation: opcion A).
                cur.execute(
                    """
                    SELECT u.id::text, u.email, u.role,
                           TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre_completo
                    FROM auth.users u
                    WHERE u.is_active = TRUE
                      AND (
                          u.id IN (
                              SELECT asesor_id FROM crm.equipos
                              WHERE supervisor_id = %s::uuid AND activo = TRUE
                          )
                          OR u.id = %s::uuid
                          OR (u.role = 'supervisor' AND u.id <> %s::uuid AND u.is_active = TRUE)
                      )
                    ORDER BY u.role DESC, u.first_name
                    """,
                    (current_user.user_id, current_user.user_id, current_user.user_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id::text, email, role,
                           TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre_completo
                    FROM auth.users WHERE id = %s::uuid
                    """,
                    (current_user.user_id,),
                )
            asesores = cur.fetchall()

    return {"estados": estados, "fuentes": fuentes, "asesores": asesores}


@router.get("/recontactos-summary")
def recontactos_summary(
    current_user: TokenData = Depends(get_current_user),
    date_range:   DateRange = Depends(parse_date_range),
):
    """V094 — Re-engagement workflow summary.

    Devuelve 3 metricas + sparkline para alimentar:
      - Banner "X recontactos sin atender" en /leads
      - Card "Recontactos" en /inicio (con comparativa periodo anterior)
      - Tab "Recontactos" en /leads (count en el badge)

    Campos:
      sin_atender         — leads con fecha_ultimo_recontacto en ultimas 48h
                            SIN ningun contacto posterior del asesor.
                            Snapshot urgente operacional, NO filtra por periodo.
      en_periodo          — recontactos en el rango del DateRange.
      en_periodo_anterior — mismo periodo previo, para comparativa %.
      daily               — serie diaria para sparkline en la KPI card.

    Cada metrica respeta role_filter — admin ve todo, supervisor su equipo,
    asesor solo sus leads (consistente con /api/leads-urgentes y /api/resumen).
    """
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── 1. Sin atender — breakdown por severidad (V094.1) ──────────
            # Patron patrón estándar "stalled deals" + patrón estándar "SLA escalation":
            #   amber: 0-48h  — "atender ahora"
            #   red:   >=48h  — "URGENTE, ya se debio haber atendido"
            # Sin cap superior — un lead sin atender por 30 dias todavia
            # cuenta como red. La banner UI muestra `mas_viejo_dias` para
            # comunicar "hace cuanto" la mas vieja espera.
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE l.fecha_ultimo_recontacto > NOW() - INTERVAL '48 hours'
                    )::int AS sin_atender_amber,
                    COUNT(*) FILTER (
                        WHERE l.fecha_ultimo_recontacto <= NOW() - INTERVAL '48 hours'
                    )::int AS sin_atender_red,
                    EXTRACT(DAY FROM (NOW() - MIN(l.fecha_ultimo_recontacto)))::int AS mas_viejo_dias
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND l.merged_into IS NULL
                  AND ({role_clause})
                  AND l.fecha_ultimo_recontacto IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM (
                        SELECT lead_id, created_at FROM crm.contactos WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                        UNION ALL
                        SELECT lead_id, fecha_llamada AS created_at FROM crm.llamadas WHERE lead_id IS NOT NULL
                      ) c
                      WHERE c.lead_id = l.id
                        AND c.created_at > l.fecha_ultimo_recontacto
                  )
                """,
                role_params,
            )
            breakdown = dict(cur.fetchone() or {})
            sin_atender_amber = breakdown.get("sin_atender_amber", 0) or 0
            sin_atender_red   = breakdown.get("sin_atender_red", 0) or 0
            mas_viejo_dias    = breakdown.get("mas_viejo_dias")
            # Backward compat: el campo `sin_atender` ahora es total (amber+red).
            # La UI del pill y el contador en el banner usan este total.
            sin_atender = sin_atender_amber + sin_atender_red

            # ── 2. en_periodo + previous_period (para card del dashboard) ────
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE l.fecha_ultimo_recontacto >= %s
                          AND l.fecha_ultimo_recontacto <= %s
                    )::int AS en_periodo,
                    COUNT(*) FILTER (
                        WHERE l.fecha_ultimo_recontacto >= %s
                          AND l.fecha_ultimo_recontacto <= %s
                    )::int AS en_periodo_anterior
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND ({role_clause})
                """,
                [
                    date_range.start, date_range.end,
                    date_range.prev_start, date_range.prev_end,
                ] + role_params,
            )
            periodo = dict(cur.fetchone() or {})

            # ── 3. serie diaria para sparkline ────────────────────────────────
            cur.execute(
                f"""
                SELECT (l.fecha_ultimo_recontacto AT TIME ZONE 'America/Lima')::date::text AS date,
                       COUNT(*)::int AS count
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND ({role_clause})
                  AND l.fecha_ultimo_recontacto >= %s
                  AND l.fecha_ultimo_recontacto <= %s
                GROUP BY (l.fecha_ultimo_recontacto AT TIME ZONE 'America/Lima')::date
                ORDER BY date
                """,
                # V095.10 — ORDEN CRITICO: psycopg2 mapea %s por POSICION en la SQL,
                # no por nombre. role_clause aparece ANTES de los range params en
                # el WHERE, asi que role_params va PRIMERO.
                # Bug previo: el orden invertido [start, end] + role_params funcionaba
                # solo para admin (role_params vacio); supervisor y asesor reventaban
                # con InvalidTextRepresentation al castear date a ::uuid -> 500 ->
                # dashboard mostraba "Error al cargar" para todos los no-admin.
                role_params + [date_range.start, date_range.end],
            )
            daily = cur.fetchall()

    return {
        "sin_atender":         sin_atender,         # total (amber + red) — compat
        "sin_atender_amber":   sin_atender_amber,   # V094.1 — 0-48h ("atender ahora")
        "sin_atender_red":     sin_atender_red,     # V094.1 — >=48h ("URGENTE")
        "mas_viejo_dias":      mas_viejo_dias,      # V094.1 — dias del recontacto mas viejo sin atender
        "en_periodo":          periodo.get("en_periodo", 0) or 0,
        "en_periodo_anterior": periodo.get("en_periodo_anterior", 0) or 0,
        "daily":               daily,
        "period":              date_range.as_dict(),
    }


@router.get("/cola-summary")
def cola_summary(current_user: TokenData = Depends(get_current_user)):
    """Resumen operacional de leads en cola de asignación: estancados vs pendientes."""
    role_clause, params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE (l.asesor_id IS NULL OR l.asesor_id IN (SELECT u_sup.id FROM auth.users u_sup WHERE u_sup.role = 'supervisor'))
                          AND (
                              (l.fecha_entrada_cola IS NOT NULL AND l.fecha_entrada_cola < NOW() - INTERVAL '24 hours')
                              OR (l.fecha_entrada_cola IS NULL AND l.created_at < NOW() - INTERVAL '24 hours')
                          )
                    )::int AS estancados,
                    COUNT(*) FILTER (
                        WHERE (l.asesor_id IS NULL OR l.asesor_id IN (SELECT u_sup.id FROM auth.users u_sup WHERE u_sup.role = 'supervisor'))
                          AND (
                              (l.fecha_entrada_cola IS NOT NULL AND l.fecha_entrada_cola >= NOW() - INTERVAL '24 hours')
                              OR (l.fecha_entrada_cola IS NULL AND l.created_at >= NOW() - INTERVAL '24 hours')
                          )
                    )::int AS pendientes,
                    COUNT(*) FILTER (
                        WHERE (l.asesor_id IS NULL OR l.asesor_id IN (SELECT u_sup.id FROM auth.users u_sup WHERE u_sup.role = 'supervisor'))
                    )::int AS total_cola
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND ({role_clause})
                """,
                params,
            )
            row = cur.fetchone() or {}
            return {
                "estancados": row.get("estancados") or 0,
                "pendientes": row.get("pendientes") or 0,
                "total_cola": row.get("total_cola") or 0,
            }


@router.get("/leads-urgentes")
def leads_urgentes(current_user: TokenData = Depends(get_current_user)):
    """Leads sin ningún contacto ni llamada registrada en más de 48 horas. Visible para todos los roles."""
    role_clause, params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND ({role_clause})
                  AND l.created_at < NOW() - INTERVAL '48 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                      UNION ALL
                      SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id
                  )
                """,
                params,
            )
            total = cur.fetchone()["total"]

            cur.execute(
                f"""
                SELECT
                    l.id::text,
                    TRIM(l.nombres || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
                    l.telefono,
                    COALESCE(
                        TRIM(u.first_name || ' ' || COALESCE(u.last_name, '')),
                        'Sin asignar'
                    ) AS asesor,
                    (EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 86400)::int AS dias_sin_contacto
                FROM crm.leads l
                LEFT JOIN auth.users u ON u.id = l.asesor_id
                WHERE l.activo = TRUE
                  AND ({role_clause})
                  AND l.created_at < NOW() - INTERVAL '48 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                      UNION ALL
                      SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id
                  )
                ORDER BY l.created_at ASC
                LIMIT 5
                """,
                params,
            )
            urgentes = cur.fetchall()

    return {"total": total, "leads": urgentes}


@router.get("/alertas-summary")
def alertas_summary(current_user: TokenData = Depends(get_current_user)):
    """Retorna conteos de alertas operacionales de llamadas pendientes: sin contacto >48h y SLA 15m vencido."""
    role_clause, params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE l.created_at < NOW() - INTERVAL '48 hours'
                          AND NOT EXISTS (
                              SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                              UNION ALL
                              SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id
                          )
                    )::int AS urgentes_48h,
                    COUNT(*) FILTER (
                        WHERE (
                            (l.sla_15m_cumplido = FALSE OR l.sla_15m_notificado_at IS NOT NULL)
                            OR (l.created_at < NOW() - INTERVAL '15 minutes' AND l.created_at > NOW() - INTERVAL '48 hours')
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            UNION ALL
                            SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id
                        )
                    )::int AS sla_15m,
                    COUNT(*) FILTER (
                        WHERE l.estado_id NOT IN (
                            SELECT id FROM crm.estados_lead WHERE nombre IN ('Ganado', 'Perdido', 'No interesado', 'Histórico', 'Historico')
                        )
                        AND (
                            (
                                UPPER(COALESCE(l.calidad, '')) = 'CALIENTE'
                                AND COALESCE((
                                    SELECT MAX(ts) FROM (
                                        SELECT created_at AS ts FROM crm.contactos WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                                        UNION ALL
                                        SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = l.id
                                    ) _all
                                ), l.created_at) < NOW() - INTERVAL '24 hours'
                            )
                            OR (
                                COALESCE((
                                    SELECT MAX(ts) FROM (
                                        SELECT created_at AS ts FROM crm.contactos WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                                        UNION ALL
                                        SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = l.id
                                    ) _all
                                ), l.created_at) < NOW() - INTERVAL '48 hours'
                            )
                        )
                    )::int AS pendientes_seguimiento
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND ({role_clause})
                """,
                params,
            )
            row = cur.fetchone() or {}
            return {
                "urgentes_48h": row.get("urgentes_48h", 0) or 0,
                "sla_15m": row.get("sla_15m", 0) or 0,
                "pendientes_seguimiento": row.get("pendientes_seguimiento", 0) or 0,
            }


@router.get("/gestion-summary")
def gestion_summary(
    filters: LeadFilters = Depends(lead_filters_query),
    current_user: TokenData = Depends(get_current_user),
):
    """Retorna conteos de próxima gestión: vencidas, sin fecha, hoy y al día.
    Respeta todos los filtros activos (estado_id, asesor_id, supervisor_id, etc.)
    excepto filtro_fecha_gestion, para mostrar los contadores completos en los pills.
    """
    filters_copy = filters.model_copy(update={"filtro_fecha_gestion": None})
    where, params = apply_lead_filters(filters_copy, current_user, include_estado=True)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE l.fecha_proxima_gestion IS NOT NULL AND l.fecha_proxima_gestion < NOW()
                    )::int AS vencidas,
                    COUNT(*) FILTER (
                        WHERE l.fecha_proxima_gestion IS NULL
                    )::int AS sin_fecha,
                    COUNT(*) FILTER (
                        WHERE (l.fecha_proxima_gestion AT TIME ZONE 'America/Lima')::date = (NOW() AT TIME ZONE 'America/Lima')::date
                    )::int AS hoy,
                    COUNT(*) FILTER (
                        WHERE l.fecha_proxima_gestion IS NOT NULL AND l.fecha_proxima_gestion >= NOW()
                    )::int AS al_dia,
                    COUNT(*)::int AS total
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND {where}
                """,
                params,
            )
            row = cur.fetchone() or {}
            return {
                "vencidas": row.get("vencidas", 0) or 0,
                "sin_fecha": row.get("sin_fecha", 0) or 0,
                "hoy": row.get("hoy", 0) or 0,
                "al_dia": row.get("al_dia", 0) or 0,
                "total": row.get("total", 0) or 0,
            }


@router.get("/citas-summary")
def citas_summary(
    filters: LeadFilters = Depends(lead_filters_query),
    current_user: TokenData = Depends(get_current_user),
):
    """Retorna conteos para subfiltros de citas agendadas:
    - Según fecha de cita: vencidas, sin fecha, hoy, al día.
    - Según atención: no atendidas (pendientes), atendidas, no asistió.
    Respeta todos los filtros activos (estado_id, asesor_id, supervisor_id, etc.)
    excepto filtro_fecha_cita y filtro_cita_atendida, para mostrar contadores estables en los pills.
    """
    filters_copy = filters.model_copy(update={
        "filtro_fecha_cita": None,
        "filtro_cita_atendida": None,
    })
    where, params = apply_lead_filters(filters_copy, current_user, include_estado=True)

    cita_fecha_expr = """COALESCE(
        (
            SELECT c.fecha_cita
            FROM crm.contactos c
            WHERE c.lead_id = l.id AND c.fecha_cita IS NOT NULL
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT 1
        ),
        l.fecha_proxima_gestion
    )"""

    cita_estado_expr = """(
        SELECT COALESCE(ce.codigo, 'pendiente')
        FROM crm.contactos c
        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
        WHERE c.lead_id = l.id AND c.fecha_cita IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    )"""

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE {cita_fecha_expr} IS NOT NULL AND {cita_fecha_expr} < NOW()
                    )::int AS vencidas,
                    COUNT(*) FILTER (
                        WHERE {cita_fecha_expr} IS NULL
                    )::int AS sin_fecha,
                    COUNT(*) FILTER (
                        WHERE ({cita_fecha_expr} AT TIME ZONE 'America/Lima')::date = (NOW() AT TIME ZONE 'America/Lima')::date
                    )::int AS hoy,
                    COUNT(*) FILTER (
                        WHERE {cita_fecha_expr} IS NOT NULL AND {cita_fecha_expr} >= NOW()
                    )::int AS al_dia,
                    COUNT(*) FILTER (
                        WHERE {cita_estado_expr} IN ('completada', 'asistio', 'realizada', 'atendida')
                    )::int AS atendidas,
                    COUNT(*) FILTER (
                        WHERE {cita_estado_expr} IS NULL
                           OR {cita_estado_expr} IN ('pendiente', 'reprogramada')
                           OR {cita_estado_expr} NOT IN ('completada', 'asistio', 'realizada', 'atendida', 'no_asistio', 'cancelada')
                    )::int AS no_atendidas,
                    COUNT(*) FILTER (
                        WHERE {cita_estado_expr} = 'no_asistio'
                    )::int AS no_asistio,
                    COUNT(*)::int AS total
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND {where}
                """,
                params,
            )
            row = cur.fetchone() or {}
            return {
                "vencidas": row.get("vencidas", 0) or 0,
                "sin_fecha": row.get("sin_fecha", 0) or 0,
                "hoy": row.get("hoy", 0) or 0,
                "al_dia": row.get("al_dia", 0) or 0,
                "atendidas": row.get("atendidas", 0) or 0,
                "no_atendidas": row.get("no_atendidas", 0) or 0,
                "no_asistio": row.get("no_asistio", 0) or 0,
                "total": row.get("total", 0) or 0,
            }


@router.get("/actividad-equipo")
def actividad_equipo(
    current_user: TokenData = Depends(require_supervisor_or_admin),
    date_range:   DateRange = Depends(parse_date_range),
):
    """Contactos realizados en el periodo seleccionado + citas hoy.

    Compat legacy: mantiene contactos_hoy/semana/mes para consumidores
    existentes. Agrega contactos_periodo + previous_period.contactos_periodo
    para el dashboard con selector temporal (V096).
    """
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE c.created_at >= CURRENT_DATE::timestamptz
                    ) AS contactos_hoy,
                    COUNT(*) FILTER (
                        WHERE c.created_at >= NOW() - INTERVAL '7 days'
                    ) AS contactos_semana,
                    COUNT(*) FILTER (
                        WHERE c.created_at >= DATE_TRUNC('month', NOW())
                    ) AS contactos_mes,
                    COUNT(*) FILTER (
                        WHERE c.resultado = 'cita_agendada'
                          AND c.fecha_cita >= CURRENT_DATE::timestamptz
                          AND c.fecha_cita  < (CURRENT_DATE + INTERVAL '1 day')::timestamptz
                    ) AS citas_hoy
                FROM crm.contactos c
                JOIN crm.leads l ON l.id = c.lead_id
                WHERE l.activo = TRUE
                  AND ({role_clause})
                """,
                role_params,
            )
            legacy = dict(cur.fetchone() or {})

            # Contactos + citas en el periodo seleccionado + periodo anterior.
            cur.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE c.created_at >= %s AND c.created_at <= %s
                    ) AS contactos_periodo,
                    COUNT(*) FILTER (
                        WHERE c.created_at >= %s AND c.created_at <= %s
                    ) AS contactos_periodo_anterior,
                    -- Citas en el periodo seleccionado
                    COUNT(*) FILTER (
                        WHERE (c.resultado ILIKE '%%cita%%' OR c.fecha_cita IS NOT NULL OR c.tipo_cita IS NOT NULL)
                          AND COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) >= %s
                          AND COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) <= %s
                    ) AS citas_periodo,
                    -- Citas en el periodo anterior (para comparativa)
                    COUNT(*) FILTER (
                        WHERE (c.resultado ILIKE '%%cita%%' OR c.fecha_cita IS NOT NULL OR c.tipo_cita IS NOT NULL)
                          AND COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) >= %s
                          AND COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) <= %s
                    ) AS citas_periodo_anterior,
                    -- Citas del mes actual entero (legacy compat)
                    COUNT(*) FILTER (
                        WHERE (c.resultado ILIKE '%%cita%%' OR c.fecha_cita IS NOT NULL OR c.tipo_cita IS NOT NULL)
                          AND (COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) AT TIME ZONE 'America/Lima')::date >= DATE_TRUNC('month', (NOW() AT TIME ZONE 'America/Lima'))::date
                          AND (COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) AT TIME ZONE 'America/Lima')::date <= (DATE_TRUNC('month', (NOW() AT TIME ZONE 'America/Lima')) + INTERVAL '1 month - 1 day')::date
                    ) AS citas_mes,
                    -- Citas del mes anterior entero (legacy compat)
                    COUNT(*) FILTER (
                        WHERE (c.resultado ILIKE '%%cita%%' OR c.fecha_cita IS NOT NULL OR c.tipo_cita IS NOT NULL)
                          AND (COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) AT TIME ZONE 'America/Lima')::date >= (DATE_TRUNC('month', (NOW() AT TIME ZONE 'America/Lima')) - INTERVAL '1 month')::date
                          AND (COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at) AT TIME ZONE 'America/Lima')::date < DATE_TRUNC('month', (NOW() AT TIME ZONE 'America/Lima'))::date
                    ) AS citas_mes_anterior
                FROM crm.contactos c
                JOIN crm.leads l ON l.id = c.lead_id
                WHERE l.activo = TRUE
                  AND ({role_clause})
                """,
                [
                    date_range.start, date_range.end,
                    date_range.prev_start, date_range.prev_end,
                    date_range.start, date_range.end,
                    date_range.prev_start, date_range.prev_end,
                ] + role_params,
            )
            periodo = dict(cur.fetchone() or {})

    legacy["contactos_periodo"]          = periodo.get("contactos_periodo", 0)
    legacy["contactos_periodo_anterior"] = periodo.get("contactos_periodo_anterior", 0)
    legacy["citas_periodo"]              = periodo.get("citas_periodo", 0)
    legacy["citas_periodo_anterior"]     = periodo.get("citas_periodo_anterior", 0)
    legacy["citas_mes"]                  = periodo.get("citas_mes", 0)
    legacy["citas_mes_anterior"]         = periodo.get("citas_mes_anterior", 0)
    legacy["period"]                     = date_range.as_dict()
    return legacy


@router.get("/funnel-conversion")
def funnel_conversion(
    current_user: TokenData = Depends(get_current_user),
    date_range:   DateRange = Depends(parse_date_range),
):
    """Funnel cohorte: leads ingresados en el periodo, agrupados por estado actual.

    V041.8 — funnel dinamico. Antes hardcodeaba los 5 estados clasicos
    (Nuevo, Contactado, Calificado, En negociación, Ganado) con WHERE IN.
    Si el admin agregaba un estado nuevo (Reserva, Pre-aprobado, etc.)
    desde Configuracion → Estados, no aparecia en el dashboard.

    V096 — agregado filtro por periodo (cohorte). Antes era acumulativo
    historico; ahora muestra "leads que INGRESARON en el periodo, donde
    estan AHORA". Patron patrón de analytics cohort funnel.

    Incluye TODOS los estados ordenados por `orden`, excluyendo solo los
    terminales negativos por nombre (Perdido / No interesado / Histórico).
    Cualquier estado positivo nuevo aparece automaticamente en la posicion
    que el admin le haya dado con el drag&drop.

    Tradeoff: si renombran "Perdido" se rompe la heuristica. Aceptable
    porque renombrar estados terminales es raro; si llega a pasar, la
    proxima iteracion puede agregar una columna `en_funnel BOOLEAN`."""
    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Traer todas las etapas del funnel (con o sin leads del periodo)
            cur.execute(
                f"""
                SELECT e.nombre AS estado, e.color_hex, e.orden,
                       COUNT(l.id) AS total
                FROM crm.estados_lead e
                LEFT JOIN crm.leads l
                  ON l.estado_id = e.id
                  AND l.activo = TRUE
                  AND l.created_at >= %s
                  AND l.created_at <= %s
                  AND ({role_clause})
                WHERE e.nombre NOT IN ('Perdido','No interesado','Histórico','Historico')
                GROUP BY e.nombre, e.color_hex, e.orden
                ORDER BY e.orden
                """,
                [date_range.start, date_range.end] + role_params,
            )
            etapas = cur.fetchall()

    result = []
    for i, etapa in enumerate(etapas):
        item = dict(etapa)
        prev_total = etapas[i - 1]["total"] if i > 0 else None
        item["tasa_desde_anterior"] = (
            round(etapa["total"] * 100.0 / prev_total, 1) if prev_total and prev_total > 0 else None
        )
        result.append(item)
    return result


# ╔════════════════════════════════════════════════════════════════════════╗
# ║ V064 — "Tu día" (efecto Zeigarnik)                                    ║
# ║                                                                        ║
# ║ Endpoint que devuelve el progreso del DIA del usuario + el siguiente  ║
# ║ lead recomendado para contactar. La UI lo muestra como una barra      ║
# ║ de progreso prominente "Tu día al 67%" — el cerebro humano mantiene   ║
# ║ activos los loops abiertos hasta cerrarlos (Bluma Zeigarnik, 1927).   ║
# ║                                                                        ║
# ║ Patron: LinkedIn "perfil 80%", Netflix autoplay, Duolingo streaks.    ║
# ║                                                                        ║
# ║ Filosofia anti-ansiedad:                                              ║
# ║   - Solo loops ACCIONABLES del dia (no acumula pendientes de ayer).   ║
# ║   - Reset diario natural via CURRENT_DATE.                            ║
# ║   - Celebrar el 100% en la UI.                                        ║
# ╚════════════════════════════════════════════════════════════════════════╝

@router.get("/mi-dia")
def mi_dia(
    exclude_lead_id: str | None = None,
    current_user: TokenData = Depends(get_current_user),
):
    """Progreso del dia + siguiente lead recomendado.

    Asesor: cuenta sus contactos hechos hoy + sus pendientes prioritarios
      (CALIENTES sin contacto en >24h o leads asignados activos sin contacto
       hace >48h).

    Supervisor/Admin: misma metrica pero sobre su scope (equipo / total).

    El siguiente lead recomendado solo considera leads en estado 'Nuevo',
    priorizando:
      1. Calidad CALIENTE
      2. Mayor tiempo sin contacto
      3. Lead mas antiguo (FIFO en empate)
    """
    role_clause, params = role_filter(current_user)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── 1. Contactos hechos HOY por este usuario ──────────────────
            # Solo contactos "reales" (excluyo cambios de estado / notas
            # automaticas que no son interaccion con el lead).
            cur.execute(
                """
                SELECT COUNT(*)::int AS contactos_hoy
                FROM (
                    SELECT id FROM crm.contactos
                    WHERE asesor_id = %s::uuid
                      AND DATE(created_at AT TIME ZONE 'America/Lima') = CURRENT_DATE
                      AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion', 'nota')
                    UNION ALL
                    SELECT id FROM crm.llamadas
                    WHERE asesor_id = %s::uuid
                      AND DATE(fecha_llamada AT TIME ZONE 'America/Lima') = CURRENT_DATE
                ) _contactos_hoy
                """,
                (current_user.user_id, current_user.user_id),
            )
            contactos_hoy = (cur.fetchone() or {}).get("contactos_hoy", 0)

            # ── 2. Pendientes prioritarios del dia ────────────────────────
            # Leads asignados al usuario (o visibles segun rol), activos,
            # en estados NO terminales, que cumplen alguna:
            #   a) calidad CALIENTE sin contacto en >24h
            #   b) cualquier calidad sin contacto en >48h
            cur.execute(
                f"""
                WITH lead_ultimo_contacto AS (
                    SELECT
                        l.id,
                        l.calidad,
                        l.created_at,
                        e.nombre AS estado_nombre,
                        COALESCE(
                            (SELECT MAX(ts) FROM (
                                SELECT created_at AS ts FROM crm.contactos
                                  WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                                UNION ALL
                                SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = l.id
                            ) _all),
                            l.created_at
                        ) AS ultimo_contacto
                    FROM crm.leads l
                    JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.activo = TRUE
                      AND ({role_clause})
                      AND e.nombre NOT IN ('Ganado', 'Perdido', 'No interesado', 'Histórico', 'Historico')
                )
                SELECT
                    COUNT(*) FILTER (
                        WHERE UPPER(COALESCE(calidad, '')) = 'CALIENTE'
                          AND ultimo_contacto < NOW() - INTERVAL '24 hours'
                    )::int AS calientes_urgentes,
                    COUNT(*) FILTER (
                        WHERE ultimo_contacto < NOW() - INTERVAL '48 hours'
                    )::int AS sin_contacto_48h,
                    COUNT(*) FILTER (
                        WHERE (
                            UPPER(COALESCE(calidad, '')) = 'CALIENTE'
                            AND ultimo_contacto < NOW() - INTERVAL '24 hours'
                        )
                        OR ultimo_contacto < NOW() - INTERVAL '48 hours'
                    )::int AS pendientes_hoy
                FROM lead_ultimo_contacto
                """,
                params,
            )
            row = cur.fetchone() or {}
            calientes_urgentes = row.get("calientes_urgentes", 0) or 0
            sin_contacto_48h   = row.get("sin_contacto_48h", 0) or 0
            pendientes_hoy     = row.get("pendientes_hoy", 0) or 0

            # ── 3. Citas confirmadas / pendientes para HOY ────────────────
            # V070.95 — Migrado de crm.eventos_calendario (tabla zombi, nunca
            # se creo en bootstrap ni migracion) a crm.contactos.fecha_cita
            # (modelo real desde V042). Antes este endpoint rompia con
            # 'relation crm.eventos_calendario does not exist' cada vez que
            # un asesor abria el Dashboard → 500 → KPIs citas en 0 + ruido
            # masivo en logs que enmascaraba otros bugs.
            #
            # Mapeo semantico:
            #   citas_hoy         = contactos con fecha_cita en HOY (Lima)
            #   citas_confirmadas = subset con cita_estado.codigo = 'completada'
            #                       (cita ya realizada exitosamente)
            #
            # Para asesor: solo SUS contactos (asesor_id). Para sup/admin:
            # toda la cola visible via role_clause sobre l.asesor_id.
            #
            # SAVEPOINT defensive: si en el futuro V042 no aplica en alguna
            # instalacion nueva, el endpoint no rompe — citas quedan en 0
            # y se loguea warning para diagnostico.
            cur.execute("SAVEPOINT sp_citas_hoy")
            try:
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*)::int AS citas_hoy,
                        COUNT(*) FILTER (
                            WHERE ce.codigo = 'completada'
                        )::int AS citas_confirmadas
                    FROM crm.contactos c
                    LEFT JOIN crm.leads l ON l.id = c.lead_id
                    LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                    WHERE c.fecha_cita IS NOT NULL
                      AND DATE(c.fecha_cita AT TIME ZONE 'America/Lima') = CURRENT_DATE
                      AND ({role_clause})
                    """,
                    params,
                )
                citas = cur.fetchone() or {}
                citas_hoy         = citas.get("citas_hoy", 0) or 0
                citas_confirmadas = citas.get("citas_confirmadas", 0) or 0
                cur.execute("RELEASE SAVEPOINT sp_citas_hoy")
            except Exception as exc:  # noqa: BLE001
                cur.execute("ROLLBACK TO SAVEPOINT sp_citas_hoy")
                logger.warning(
                    "mi_dia: query de citas_hoy fallo (%s) — fallback 0/0",
                    exc,
                )
                citas_hoy = 0
                citas_confirmadas = 0

            # ── 4. Siguiente lead recomendado ─────────────────────────────
            # Prioridad: CALIENTE > TIBIO > FRIO > sin_calidad
            # Dentro de cada bucket: mayor tiempo sin contacto > FIFO
            # exclude_lead_id permite excluir el lead que el user esta
            # viendo (usado por NextLeadFooter en LeadDetalle).
            next_params = list(params)
            exclude_clause = ""
            if exclude_lead_id:
                try:
                    exclude_val = int(exclude_lead_id)
                    exclude_clause = "AND l.id <> %s"
                    next_params.append(exclude_val)
                except (ValueError, TypeError):
                    pass
            cur.execute(
                f"""
                SELECT
                    l.id::text                                     AS id,
                    l.nombres,
                    l.apellidos,
                    l.telefono,
                    l.calidad                                      AS calidad_codigo,
                    e.nombre                                       AS estado_nombre,
                    e.color_hex                                    AS estado_color,
                    EXTRACT(EPOCH FROM (NOW() - COALESCE(
                        (SELECT MAX(ts) FROM (
                            SELECT created_at AS ts FROM crm.contactos
                              WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            UNION ALL
                            SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = l.id
                        ) _all),
                        l.created_at
                    ))) / 3600                                     AS horas_sin_contacto
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND ({role_clause})
                  AND LOWER(TRIM(e.nombre)) = 'nuevo'
                  {exclude_clause}
                ORDER BY
                    -- Calidad CALIENTE primero
                    CASE UPPER(COALESCE(l.calidad, '')) WHEN 'CALIENTE' THEN 0 WHEN 'TIBIO' THEN 1 WHEN 'FRIO' THEN 2 ELSE 3 END,
                    -- Mas tiempo sin contacto primero
                    COALESCE(
                        (SELECT MAX(ts) FROM (
                            SELECT created_at AS ts FROM crm.contactos
                              WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            UNION ALL
                            SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = l.id
                        ) _all),
                        l.created_at
                    ) ASC,
                    -- FIFO entre empates
                    l.created_at ASC
                LIMIT 1
                """,
                next_params,
            )
            next_lead_row = cur.fetchone()

    # ── 5. Calculo del progress_pct ──────────────────────────────────────
    # progreso = contactos_hoy / (contactos_hoy + pendientes_priorizados)
    # Si no hay ni contactos ni pendientes, mostramos 100% (dia limpio).
    total_loops = contactos_hoy + pendientes_hoy
    progress_pct = 100 if total_loops == 0 else round(100.0 * contactos_hoy / total_loops)

    # ── 6. Mensaje motivacional segun progreso ───────────────────────────
    if progress_pct >= 100:
        motivational = "¡Día completo! No tienes pendientes urgentes."
        emoji = "🎉"
    elif progress_pct >= 80:
        motivational = "Estás cerca, te faltan pocos."
        emoji = "💪"
    elif progress_pct >= 50:
        motivational = "Vas a mitad de camino."
        emoji = "🔥"
    elif progress_pct >= 20:
        motivational = "Empezaste bien, seguí así."
        emoji = "⚡"
    else:
        motivational = "Arrancá el día contactando."
        emoji = "🚀"

    next_lead = None
    if next_lead_row:
        next_lead = dict(next_lead_row)
        next_lead["horas_sin_contacto"] = (
            round(float(next_lead["horas_sin_contacto"] or 0), 1)
        )

    return {
        "date":               None,  # Se llena en frontend con local date
        "progress_pct":       progress_pct,
        "contactos_hoy":      contactos_hoy,
        "pendientes_hoy":     pendientes_hoy,
        "calientes_urgentes": calientes_urgentes,
        "sin_contacto_48h":   sin_contacto_48h,
        "citas_hoy":          citas_hoy,
        "citas_confirmadas":  citas_confirmadas,
        "next_recommended_lead": next_lead,
        "motivational":       motivational,
        "emoji":              emoji,
    }

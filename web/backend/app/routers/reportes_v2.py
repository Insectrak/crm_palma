"""
Reportes V2 — V070.103 — 5 reportes profesionales patrón estándar-class.

Cada endpoint:
  - Filtra por rol (admin todo, supervisor su equipo, asesor solo suyo)
  - Acepta rango de fechas opcional (default ultimos 30 dias)
  - Devuelve JSON estructurado consumible por mobile + web
  - Tiene SQL parametrizada (anti SQL injection)
  - Usa indices existentes (+ idx_contactos_created_at de V074)

Endpoints:
  GET /api/reportes/v2/eficiencia-llamadas   — duracion prom, % efectivas, por calidad
  GET /api/reportes/v2/leadtime              — tiempo asignacion->contacto + rangos
  GET /api/reportes/v2/funnel                — embudo dinamico + tasa por canal
  GET /api/reportes/v2/control               — leads no contactados + heatmap + campanas
  GET /api/reportes/v2/estrategico           — top asesores + fuga + tiempo muerto (admin)

Diseno SOLID:
  - SRP: cada endpoint resuelve UNA pregunta de negocio
  - DIP: usa role_filter() compartido del filters/ module
  - OCP: agregar un reporte nuevo es agregar un endpoint, no tocar existentes
"""
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from app.auth.jwt import get_current_user, require_supervisor_or_admin
from app.auth.permissions import has_permission, can_view_all_data
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reportes/v2", tags=["Reportes V2"])


# ════════════════════════════════════════════════════════════════════════════
# V070.109 — Catalog + Dashboards (D-lite, patron estandar de la industria)
# ════════════════════════════════════════════════════════════════════════════

# Catalogo de reportes con metadata. Mantenido en codigo (no en DB) porque
# los reportes son fijos — definidos por el dev, no por el usuario.
# Si en futuro queremos que el usuario cree reportes, migramos a tabla.
_REPORTS_CATALOG = [
    # ── Operativos (vistas crudas / listados) ────────────────────────
    {"key": "asesores",   "name": "Por Asesor",   "category": "operativos",
     "description": "KPIs por asesor: leads, contactados, conversion.",
     "icon": "users",     "roles": ["admin", "supervisor"],
     "path_web": "/reportes-operativos?tab=asesores"},
    {"key": "ranking",    "name": "Ranking",      "category": "operativos",
     "description": "Top asesores por tasa de conversion.",
     "icon": "trending-up", "roles": ["admin", "supervisor"],
     "path_web": "/reportes-operativos?tab=ranking"},
    {"key": "fuentes",    "name": "Por Fuente",   "category": "operativos",
     "description": "Distribucion de leads por fuente / canal.",
     "icon": "filter",    "roles": ["admin", "supervisor", "asesor"],
     "path_web": "/reportes-operativos?tab=fuentes"},
    # V095.9 — Por Campana al catalogo. El endpoint /api/reportes/campanas
    # ya existia (V1) con KPIs + tabla por campana. Antes no se podia
    # llegar a el desde el menu — ahora si.
    {"key": "campanas",   "name": "Por Campaña",  "category": "operativos",
     "description": "Performance por campaña: leads, contactados, calificados, ganados y tiempo a primer contacto.",
     "icon": "megaphone", "roles": ["admin", "supervisor"],
     "path_web": "/reportes-operativos?tab=campanas"},
    {"key": "citas",      "name": "Citas",        "category": "operativos",
     "description": "Citas programadas y su estado actual.",
     "icon": "calendar",  "roles": ["admin", "supervisor"],
     "path_web": "/reportes-operativos?tab=citas"},
    # ── Analytics (analisis calculados / insights) ───────────────────
    {"key": "llamadas",    "name": "Eficiencia Llamadas",  "category": "analytics",
     "description": "Duracion promedio, % efectivas (>2min) y por calidad.",
     "icon": "phone",     "roles": ["admin", "supervisor", "asesor"],
     "path_web": "/reportes-avanzados?tab=llamadas"},
    {"key": "leadtime",    "name": "Leadtime",             "category": "analytics",
     "description": "Velocidad de primer contacto + distribucion por rangos.",
     "icon": "clock",     "roles": ["admin", "supervisor", "asesor"],
     "path_web": "/reportes-avanzados?tab=leadtime"},
    {"key": "embudo",      "name": "Embudo de Conversion", "category": "analytics",
     "description": "Funnel dinamico + tasa de cierre por canal.",
     "icon": "git-merge", "roles": ["admin", "supervisor"],
     "path_web": "/reportes-avanzados?tab=funnel"},
    # V095.7 — los dos reportes nuevos de V095.4/5 faltaban en el catalogo,
    # por eso las cards de "Velocidad" y "Cohorts" no aparecian en /reportes.
    {"key": "velocidad",   "name": "Velocidad de etapas",  "category": "analytics",
     "description": "Stage aging: cuantos dias llevan los leads en cada etapa.",
     "icon": "gauge",     "roles": ["admin", "supervisor"],
     "path_web": "/reportes-avanzados?tab=velocity"},
    {"key": "cohorts",     "name": "Cohorts mensuales",    "category": "analytics",
     "description": "Heatmap: mes de ingreso x estado actual de los leads.",
     "icon": "grid",      "roles": ["admin", "supervisor"],
     "path_web": "/reportes-avanzados?tab=cohort"},
    {"key": "control",     "name": "Control Operativo",    "category": "analytics",
     "description": "Leads abandonados, heatmap y campanas.",
     "icon": "alert-triangle", "roles": ["admin", "supervisor"],
     "path_web": "/reportes-avanzados?tab=control"},
    {"key": "estrategico", "name": "Estrategico",           "category": "analytics",
     "description": "Top asesores, fuga, tiempo muerto y mejores horarios.",
     "icon": "star",      "roles": ["admin"],
     "path_web": "/reportes-avanzados?tab=estrategico"},
]


# Dashboards predefinidos: combinan queries de reportes existentes.
_DASHBOARDS_CATALOG = [
    {
        "id": "supervisor",
        "name": "Vista Supervisor",
        "description": "Operacion diaria del equipo: ranking, embudo y alertas.",
        "icon": "users",
        "roles": ["admin", "supervisor"],
        "components": [
            {"type": "kpi",      "source": "control",  "field": "leads_sin_contactar", "label": "Sin contactar 7d+", "tone": "danger"},
            {"type": "kpi",      "source": "funnel",   "field": "tasa_global_pct",      "label": "Tasa conversion", "tone": "success"},
            {"type": "ranking",  "source": "control",  "field": "ranking",              "label": "Ranking asesores"},
            {"type": "funnel",   "source": "funnel",   "field": "etapas_funnel",        "label": "Embudo del periodo"},
            {"type": "heatmap",  "source": "control",  "field": "heatmap",              "label": "Actividad dia x hora"},
        ],
    },
    {
        "id": "estrategico",
        "name": "Vista Estrategica",
        "description": "Insights de alto nivel para toma de decisiones.",
        "icon": "star",
        "roles": ["admin"],
        "components": [
            {"type": "top",       "source": "estrategico", "field": "top_asesores",    "label": "Top asesores del mes"},
            {"type": "fuga",      "source": "estrategico", "field": "leads_fuga",      "label": "Leads fuga (urgente)"},
            {"type": "horarios",  "source": "estrategico", "field": "mejores_horarios","label": "Mejores horarios"},
            {"type": "channels",  "source": "funnel",      "field": "por_canal",       "label": "Performance por canal"},
        ],
    },
]


@router.get("/catalog")
def reports_catalog(current_user: TokenData = Depends(get_current_user)):
    """Catalogo de reportes filtrado por rol del usuario.

    Devuelve solo los reportes que el rol actual puede consumir.
    """
    role = current_user.role
    has_custom = getattr(current_user, "role_id", None) is not None
    visible = [r for r in _REPORTS_CATALOG if role in r["roles"] or has_custom]
    return {
        "reports": visible,
        "categories": [
            {"key": "operativos", "name": "Operativos",
             "description": "Vistas crudas y listados del dia a dia."},
            {"key": "analytics",  "name": "Analytics",
             "description": "Analisis calculados con insights accionables."},
        ],
    }


@router.get("/dashboards-catalog")
def dashboards_catalog(current_user: TokenData = Depends(get_current_user)):
    """Catalogo de dashboards predefinidos filtrados por rol."""
    role = current_user.role
    has_custom = getattr(current_user, "role_id", None) is not None
    visible = [d for d in _DASHBOARDS_CATALOG if role in d["roles"] or has_custom]
    return {"dashboards": visible}


# ════════════════════════════════════════════════════════════════════════════
# Helpers compartidos
# ════════════════════════════════════════════════════════════════════════════

def _default_range(fecha_desde: Optional[str], fecha_hasta: Optional[str]) -> tuple[str, str]:
    """Default: ultimos 30 dias (inclusive hoy)."""
    hoy = date.today()
    return (
        fecha_desde or (hoy - timedelta(days=30)).isoformat(),
        fecha_hasta or hoy.isoformat(),
    )


def _role_clause_leads(user: TokenData, alias: str = "l") -> tuple[str, list]:
    """WHERE clause + params para filtrar leads visibles por rol.

    Devuelve (sql, params). Si admin o permiso reportes.view_all/data.view_all → "TRUE", [].
    Si supervisor, filtra por equipos/asignacion. Si asesor/custom sin permiso, filtra solo suyo.
    """
    if can_view_all_data(user, "reportes"):
        return "TRUE", []
    if user.role == Role.SUPERVISOR or user.role == "supervisor":
        return (
            "("
            f"{alias}.asesor_id = %s::uuid "
            f"OR ({alias}.asesor_id IS NULL AND {alias}.supervisor_id = %s::uuid) "
            f"OR {alias}.asesor_id IN ("
                "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
            ") "
            f"OR ({alias}.asesor_id IS NULL AND {alias}.supervisor_id IN ("
                "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
            ")) "
            f"OR {alias}.asesor_id IN ("
                "SELECT eq.asesor_id FROM crm.equipos eq "
                "WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN ("
                    "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
                ")) AND eq.activo = TRUE"
            ")"
            ")",
            [user.user_id, user.user_id, user.user_id, user.user_id, user.user_id, user.user_id],
        )
    return f"{alias}.asesor_id = %s::uuid", [user.user_id]


def _role_clause_users(user: TokenData, alias: str = "u") -> tuple[str, list]:
    """WHERE clause para filtrar USUARIOS visibles por rol.

    Util para queries que agrupan por asesor (ej: ranking, eficiencia).
    """
    if can_view_all_data(user, "reportes"):
        return "TRUE", []
    if user.role == Role.SUPERVISOR or user.role == "supervisor":
        return (
            "("
            f"{alias}.id = %s::uuid "
            f"OR {alias}.id IN ("
                "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
            ") "
            f"OR {alias}.id IN ("
                "SELECT eq.asesor_id FROM crm.equipos eq "
                "WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN ("
                    "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
                ")) AND eq.activo = TRUE"
            ")"
            ")",
            [user.user_id, user.user_id, user.user_id, user.user_id],
        )
    return f"{alias}.id = %s::uuid", [user.user_id]


# ════════════════════════════════════════════════════════════════════════════
# REPORTE 1 — Eficiencia de llamadas
# ════════════════════════════════════════════════════════════════════════════

@router.get("/eficiencia-llamadas")
def eficiencia_llamadas(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    asesor_id: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """Duracion promedio por asesor, % efectivas (>2min), % cortas (<30s),
    + breakdown por calidad de lead (FRIO/TIBIO/CALIENTE).

    Roles:
      - asesor: solo sus propias llamadas
      - supervisor: llamadas de su equipo
      - admin: todas
    """
    f_desde, f_hasta = _default_range(fecha_desde, fecha_hasta)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── Ranking por asesor ──────────────────────────────────────
            user_clause, user_params = _role_clause_users(current_user, alias="u")
            params = [f_desde, f_hasta] + user_params
            asesor_filter = ""
            if asesor_id:
                asesor_filter = "AND u.id = %s::uuid"
                params.append(asesor_id)

            cur.execute(
                f"""
                SELECT
                    u.id::text                                                   AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor,
                    COUNT(ll.id)                                                 AS total_llamadas,
                    COALESCE(ROUND(AVG(ll.duracion_segundos))::int, 0)           AS duracion_prom_seg,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE ll.duracion_segundos > 120)
                            / NULLIF(COUNT(*), 0), 1), 0)                        AS pct_efectivas,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE ll.duracion_segundos < 30
                            AND ll.tipo != 'perdida')
                            / NULLIF(COUNT(*), 0), 1), 0)                        AS pct_cortas,
                    COUNT(*) FILTER (WHERE ll.tipo = 'perdida')                  AS perdidas
                FROM auth.users u
                LEFT JOIN crm.llamadas ll ON ll.asesor_id = u.id
                    AND ll.fecha_llamada::date BETWEEN %s::date AND %s::date
                WHERE u.role = 'asesor' AND u.is_active = TRUE
                  AND {user_clause}
                  {asesor_filter}
                GROUP BY u.id, u.first_name, u.last_name
                HAVING COUNT(ll.id) > 0
                ORDER BY total_llamadas DESC
                LIMIT 100
                """,
                params,
            )
            por_asesor = cur.fetchall()

            # ── Distribucion por calidad (FRIO/TIBIO/CALIENTE) ─────────
            lead_clause, lead_params = _role_clause_leads(current_user, alias="l")
            cal_params = [f_desde, f_hasta] + lead_params
            cur.execute(
                f"""
                SELECT
                    COALESCE(l.calidad, 'SIN_CLASIFICAR')                        AS calidad,
                    COUNT(ll.id)                                                  AS llamadas,
                    COALESCE(ROUND(AVG(ll.duracion_segundos))::int, 0)            AS duracion_prom_seg,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE ll.duracion_segundos > 120)
                            / NULLIF(COUNT(*), 0), 1), 0)                         AS pct_efectivas
                FROM crm.llamadas ll
                JOIN crm.leads l ON l.id = ll.lead_id
                WHERE ll.fecha_llamada::date BETWEEN %s::date AND %s::date
                  AND {lead_clause}
                GROUP BY l.calidad
                ORDER BY CASE COALESCE(l.calidad, 'SIN_CLASIFICAR')
                            WHEN 'CALIENTE' THEN 1
                            WHEN 'TIBIO'    THEN 2
                            WHEN 'FRIO'     THEN 3
                            ELSE 4
                         END
                """,
                cal_params,
            )
            por_calidad = cur.fetchall()

            # ── KPIs globales ───────────────────────────────────────────
            total = sum(r["total_llamadas"] for r in por_asesor)
            ponderado_dur = (
                sum(r["duracion_prom_seg"] * r["total_llamadas"] for r in por_asesor) / total
                if total else 0
            )
            ponderado_efec = (
                sum(r["pct_efectivas"] * r["total_llamadas"] for r in por_asesor) / total
                if total else 0
            )
            ponderado_cor = (
                sum(r["pct_cortas"] * r["total_llamadas"] for r in por_asesor) / total
                if total else 0
            )

            return {
                "fecha_desde": f_desde,
                "fecha_hasta": f_hasta,
                "kpis": {
                    "total_llamadas":    total,
                    "duracion_prom_seg": round(ponderado_dur, 0),
                    "pct_efectivas":     round(ponderado_efec, 1),
                    "pct_cortas":        round(ponderado_cor, 1),
                },
                "por_asesor":  por_asesor,
                "por_calidad": por_calidad,
            }


# ════════════════════════════════════════════════════════════════════════════
# REPORTE 2 — Leadtime (velocidad de contacto)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/leadtime")
def leadtime(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """Tiempo desde asignacion del lead hasta el primer contacto.

    Distribucion en rangos (<5min, 5-30min, 30-60min, >60min).
    Intentos promedio por lead. Contactos por asesor.
    """
    f_desde, f_hasta = _default_range(fecha_desde, fecha_hasta)
    lead_clause, lead_params = _role_clause_leads(current_user, alias="l")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params = [f_desde, f_hasta] + lead_params
            cur.execute(
                f"""
                WITH primera_asig AS (
                    SELECT DISTINCT ON (lead_id)
                        lead_id, created_at AS fecha_asignacion
                    FROM crm.asignaciones_log
                    WHERE motivo = 'inicial'
                    ORDER BY lead_id, created_at ASC
                ),
                primer_contacto AS (
                    SELECT DISTINCT ON (lead_id)
                        lead_id, created_at AS fecha_primer_contacto, asesor_id
                    FROM crm.contactos
                    WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                    ORDER BY lead_id, created_at ASC
                )
                SELECT
                    u.id::text                                                       AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor,
                    COUNT(l.id)                                                       AS leads_asignados,
                    COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60)::numeric, 1), 0) AS minutos_prom,
                    -- V095.2 — P50 (mediana) y P90 son los SLA reales que usan
                    -- patrón estándar y patrón estándar. El promedio miente con outliers:
                    -- un solo asesor que tarda 8h infla el numero de todo el
                    -- equipo y oculta que la mediana es de 5 minutos.
                    COALESCE(ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                    ))::numeric, 1), 0)                                              AS minutos_p50,
                    COALESCE(ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                    ))::numeric, 1), 0)                                              AS minutos_p90,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60 < 5)   AS menos_5min,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                        BETWEEN 5 AND 30)                                             AS entre_5_30min,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                        BETWEEN 30 AND 60)                                            AS entre_30_60min,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60 > 60)  AS mas_60min,
                    COALESCE(ROUND(AVG(l.intentos_contacto)::numeric, 1), 0)          AS intentos_prom
                FROM crm.leads l
                JOIN primera_asig pa     ON pa.lead_id = l.id
                JOIN primer_contacto pc  ON pc.lead_id = l.id
                LEFT JOIN auth.users u   ON u.id = l.asesor_id
                WHERE l.activo = TRUE
                  AND l.created_at::date BETWEEN %s::date AND %s::date
                  AND {lead_clause}
                GROUP BY u.id, u.first_name, u.last_name
                ORDER BY minutos_p50 ASC
                """,
                params,
            )
            por_asesor = cur.fetchall()

            # ── Distribucion global de rangos ───────────────────────────
            global_params = [f_desde, f_hasta] + lead_params
            cur.execute(
                f"""
                WITH primera_asig AS (
                    SELECT DISTINCT ON (lead_id) lead_id, created_at AS fecha_asignacion
                    FROM crm.asignaciones_log WHERE motivo = 'inicial'
                    ORDER BY lead_id, created_at ASC
                ),
                primer_contacto AS (
                    SELECT DISTINCT ON (lead_id) lead_id, created_at AS fecha_primer_contacto
                    FROM crm.contactos WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                    ORDER BY lead_id, created_at ASC
                )
                SELECT
                    COUNT(*)                                                            AS total,
                    COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60)::numeric, 1), 0) AS minutos_prom_global,
                    -- V095.2 — globales para el semaforo SLA del header.
                    COALESCE(ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                    ))::numeric, 1), 0)                                                 AS minutos_p50_global,
                    COALESCE(ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                    ))::numeric, 1), 0)                                                 AS minutos_p90_global,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60 < 5)      AS menos_5min,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                        BETWEEN 5 AND 30)                                                AS entre_5_30min,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60
                        BETWEEN 30 AND 60)                                               AS entre_30_60min,
                    COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM
                        (pc.fecha_primer_contacto - pa.fecha_asignacion)) / 60 > 60)     AS mas_60min
                FROM crm.leads l
                JOIN primera_asig pa     ON pa.lead_id = l.id
                JOIN primer_contacto pc  ON pc.lead_id = l.id
                WHERE l.activo = TRUE
                  AND l.created_at::date BETWEEN %s::date AND %s::date
                  AND {lead_clause}
                """,
                global_params,
            )
            distribucion = cur.fetchone() or {
                "total": 0, "minutos_prom_global": 0,
                "minutos_p50_global": 0, "minutos_p90_global": 0,
                "menos_5min": 0, "entre_5_30min": 0, "entre_30_60min": 0, "mas_60min": 0,
            }

            return {
                "fecha_desde":  f_desde,
                "fecha_hasta":  f_hasta,
                "distribucion": distribucion,
                "por_asesor":   por_asesor,
            }


# ════════════════════════════════════════════════════════════════════════════
# REPORTE 3 — Funnel de conversion
# ════════════════════════════════════════════════════════════════════════════

@router.get("/funnel")
def funnel(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    fuente_id: Optional[int] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """Embudo completo dinamico: ordena estados por `orden` del catalogo.

    Excluye estados finales NEGATIVOS por nombre (Perdido, No interesado, Descartado)
    porque el flag `es_final` no diferencia ganados de perdidos.
    Calcula tasa de cierre por fuente.
    """
    f_desde, f_hasta = _default_range(fecha_desde, fecha_hasta)
    lead_clause, lead_params = _role_clause_leads(current_user, alias="l")
    estados_negativos = ['Perdido', 'No interesado', 'Descartado', 'No contesta']

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── Funnel: total por etapa ─────────────────────────────────
            params = [f_desde, f_hasta] + lead_params
            fuente_filter = ""
            if fuente_id is not None:
                fuente_filter = "AND l.fuente_id = %s"
                params.append(fuente_id)

            cur.execute(
                f"""
                SELECT
                    e.id, e.nombre, e.color_hex, e.orden, e.es_final,
                    COUNT(l.id)::int AS total
                FROM crm.estados_lead e
                LEFT JOIN crm.leads l
                    ON l.estado_id = e.id
                   AND l.activo = TRUE
                   AND l.created_at::date BETWEEN %s::date AND %s::date
                   AND {lead_clause}
                   {fuente_filter}
                GROUP BY e.id, e.nombre, e.color_hex, e.orden, e.es_final
                ORDER BY e.orden
                """,
                params,
            )
            etapas_raw = cur.fetchall()

            # Etapas positivas (incluidas en el funnel lineal)
            etapas_funnel = [
                e for e in etapas_raw if e["nombre"] not in estados_negativos
            ]
            # Etapas perdidas (en panel aparte)
            etapas_perdidas = [
                e for e in etapas_raw if e["nombre"] in estados_negativos
            ]
            total_perdidos = sum(e["total"] for e in etapas_perdidas)

            # Calcular tasa de conversion etapa N → N+1
            for i, etapa in enumerate(etapas_funnel):
                if i == 0:
                    etapa["tasa_conversion"] = 100.0
                else:
                    prev = etapas_funnel[i - 1]["total"] or 1
                    etapa["tasa_conversion"] = round(100.0 * etapa["total"] / prev, 1)

            # ── Tasa de cierre por fuente (Source ROI ampliado V095.3) ──
            # Patron CRMs profesionales: la "tasa de cierre" sola es enganosa.
            # Una fuente con 1000 leads y 4% cierre puede ser MEJOR que una
            # con 50 leads y 10% cierre, dependiendo del volumen absoluto y
            # de cuanto "respiran" en el funnel intermedio (contactados +
            # calificados). Por eso traemos 3 columnas:
            #   - tasa_contacto_pct: cuantos LLEGARON a tener al menos 1
            #     contacto real (no 'cambio_estado'). Mide calidad del lead.
            #   - tasa_calificacion_pct: cuantos llegaron a un estado de
            #     "calidad" — heuristica: estados con orden >= 3 que NO son
            #     finales negativos. Mide si la fuente trae interes real.
            #   - tasa_cierre_pct: cuantos ganados.
            neg_placeholders = ','.join(['%s'] * len(estados_negativos))
            cur.execute(
                f"""
                SELECT
                    COALESCE(f.nombre, 'Sin fuente')              AS fuente,
                    COUNT(l.id)::int                              AS total,
                    -- Contactados: lead con al menos 1 contacto real
                    COUNT(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM crm.contactos c
                            WHERE c.lead_id = l.id
                              AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                        ) OR EXISTS (
                            SELECT 1 FROM crm.llamadas ll
                            WHERE ll.lead_id = l.id
                        )
                    )::int                                        AS contactados,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1 FROM crm.contactos c
                            WHERE c.lead_id = l.id
                              AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                        ) OR EXISTS (
                            SELECT 1 FROM crm.llamadas ll
                            WHERE ll.lead_id = l.id
                        )
                    ) / NULLIF(COUNT(l.id), 0), 1), 0)::float     AS tasa_contacto_pct,
                    -- Calificados: estado con orden >= 3 y NO final negativo
                    COUNT(*) FILTER (
                        WHERE e.orden >= 3
                          AND e.nombre NOT IN ({neg_placeholders})
                    )::int                                        AS calificados,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (
                        WHERE e.orden >= 3
                          AND e.nombre NOT IN ({neg_placeholders})
                    ) / NULLIF(COUNT(l.id), 0), 1), 0)::float     AS tasa_calificacion_pct,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )::int                                        AS cerrados,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    ) / NULLIF(COUNT(l.id), 0), 1), 0)::float     AS tasa_cierre_pct
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes f      ON f.id = l.fuente_id
                WHERE l.activo = TRUE
                  AND l.created_at::date BETWEEN %s::date AND %s::date
                  AND {lead_clause}
                GROUP BY f.nombre
                ORDER BY total DESC
                LIMIT 50
                """,
                # neg_placeholders appears 2x in SELECT (calificados + tasa_calificacion)
                estados_negativos * 2 + [f_desde, f_hasta] + lead_params,
            )
            por_canal = cur.fetchall()

            # Tasa global del funnel
            total_in  = etapas_funnel[0]["total"] if etapas_funnel else 0
            total_out = etapas_funnel[-1]["total"] if etapas_funnel else 0
            tasa_global = round(100.0 * total_out / total_in, 2) if total_in else 0

            return {
                "fecha_desde":     f_desde,
                "fecha_hasta":     f_hasta,
                "fuente_id":       fuente_id,
                "etapas_funnel":   etapas_funnel,
                "total_perdidos":  total_perdidos,
                "tasa_global_pct": tasa_global,
                "por_canal":       por_canal,
            }


# ════════════════════════════════════════════════════════════════════════════
# REPORTE 4 — Control (operativo diario)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/control")
def control_dashboard(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    dias_sin_contacto: int = Query(7, ge=1, le=90),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Dashboard operativo: leads no contactados, ranking, heatmap, campanas."""
    f_desde, f_hasta = _default_range(fecha_desde, fecha_hasta)
    lead_clause, lead_params = _role_clause_leads(current_user, alias="l")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── Leads sin contactar por N dias ──────────────────────────
            cur.execute(
                f"""
                SELECT COUNT(*)::int AS leads_sin_contactar
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND l.created_at < NOW() - INTERVAL '{int(dias_sin_contacto)} days'
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c
                      WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                  )
                  AND {lead_clause}
                """,
                lead_params,
            )
            sin_contactar = cur.fetchone()["leads_sin_contactar"]

            # ── Ranking de asesores por matrículas / conversión ──────────
            user_clause, user_params = _role_clause_users(current_user, alias="u")
            cur.execute(
                f"""
                SELECT
                    u.id::text                                                       AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor,
                    COUNT(l.id)::int                                                  AS total_leads,
                    COUNT(*) FILTER (
                        WHERE (l.tipo_cierre IS NOT NULL AND TRIM(l.tipo_cierre) <> '')
                           OR e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )::int                                                           AS cerrados,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (
                        WHERE (l.tipo_cierre IS NOT NULL AND TRIM(l.tipo_cierre) <> '')
                           OR e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    ) / NULLIF(COUNT(l.id), 0), 1), 0)::float                        AS tasa_conversion_pct
                FROM auth.users u
                LEFT JOIN crm.leads l         ON l.asesor_id = u.id AND l.activo = TRUE
                    AND l.created_at::date BETWEEN %s::date AND %s::date
                LEFT JOIN crm.estados_lead e  ON e.id = l.estado_id
                WHERE u.role = 'asesor' AND u.is_active = TRUE AND {user_clause}
                GROUP BY u.id, u.first_name, u.last_name
                HAVING COUNT(l.id) > 0
                ORDER BY cerrados DESC, tasa_conversion_pct DESC, total_leads DESC
                LIMIT 50
                """,
                [f_desde, f_hasta] + user_params,
            )
            ranking = cur.fetchall()

            # ── Heatmap dia x hora (zona Lima) ──────────────────────────
            params_heat = [f_desde, f_hasta] + lead_params
            cur.execute(
                f"""
                SELECT
                    EXTRACT(DOW  FROM c.created_at AT TIME ZONE 'America/Lima')::int AS dia_semana,
                    EXTRACT(HOUR FROM c.created_at AT TIME ZONE 'America/Lima')::int AS hora,
                    COUNT(*)::int                                                     AS total
                FROM crm.contactos c
                JOIN crm.leads l ON l.id = c.lead_id
                WHERE c.created_at::date BETWEEN %s::date AND %s::date
                  AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                  AND {lead_clause}
                GROUP BY dia_semana, hora
                ORDER BY dia_semana, hora
                """,
                params_heat,
            )
            heatmap = cur.fetchall()

            # ── Performance por campana ─────────────────────────────────
            cur.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(TRIM(l.campana), ''), 'Sin campaña')             AS campana,
                    COUNT(l.id)::int                                                  AS total,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )::int                                                           AS cerrados,
                    COALESCE(ROUND(AVG(CASE l.calidad
                        WHEN 'CALIENTE' THEN 3
                        WHEN 'TIBIO'    THEN 2
                        WHEN 'FRIO'     THEN 1
                        ELSE 0 END)::numeric, 2), 0)::float                           AS calidad_score,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    ) / NULLIF(COUNT(l.id), 0), 1), 0)::float                        AS tasa_cierre_pct
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND l.created_at::date BETWEEN %s::date AND %s::date
                  AND {lead_clause}
                GROUP BY campana
                HAVING COUNT(l.id) >= 3   -- ignorar campanas sin volumen
                ORDER BY total DESC
                LIMIT 30
                """,
                [f_desde, f_hasta] + lead_params,
            )
            por_campana = cur.fetchall()

            return {
                "fecha_desde":          f_desde,
                "fecha_hasta":          f_hasta,
                "dias_sin_contacto":    dias_sin_contacto,
                "leads_sin_contactar":  sin_contactar,
                "ranking":              ranking,
                "heatmap":              heatmap,
                "por_campana":          por_campana,
            }


# ════════════════════════════════════════════════════════════════════════════
# REPORTE 5 — Estrategico (solo admin)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/estrategico")
def estrategico(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """Reporte estrategico: top asesores, fuga, tiempo muerto, mejores horarios.

    Solo accesible para admin (Carlos).
    """
    if current_user.role != Role.ADMIN and not (getattr(current_user, "role_id", None) is not None and (has_permission(current_user, "reportes.view") or has_permission(current_user, "dashboards.view"))):
        raise HTTPException(403, "Solo el administrador o roles con permiso de reportes pueden ver el reporte estrategico.")

    f_desde, f_hasta = _default_range(fecha_desde, fecha_hasta)
    estados_negativos = ['Perdido', 'No interesado', 'Descartado', 'No contesta']
    neg_ph = ','.join(['%s'] * len(estados_negativos))

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── Top asesores por cierre ─────────────────────────────────
            cur.execute(
                f"""
                SELECT
                    u.id::text                                                       AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor,
                    COUNT(l.id)::int                                                  AS total_leads,
                    COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )::int                                                           AS cerrados,
                    COALESCE(ROUND(100.0 * COUNT(*) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    ) / NULLIF(COUNT(l.id), 0), 1), 0)::float                        AS tasa_cierre_pct
                FROM auth.users u
                JOIN crm.leads l         ON l.asesor_id = u.id AND l.activo = TRUE
                    AND l.created_at::date BETWEEN %s::date AND %s::date
                LEFT JOIN crm.estados_lead e  ON e.id = l.estado_id
                WHERE u.role = 'asesor' AND u.is_active = TRUE
                GROUP BY u.id, u.first_name, u.last_name
                HAVING COUNT(l.id) > 0
                ORDER BY cerrados DESC, tasa_cierre_pct DESC
                LIMIT 10
                """,
                [f_desde, f_hasta],
            )
            top_asesores = cur.fetchall()

            # ── Leads fuga (nunca contactados) ─────────────────────────
            cur.execute(
                """
                SELECT
                    l.id::int                                                AS lead_id,
                    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre,
                    l.telefono,
                    COALESCE(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')),
                             'Sin asignar')                                   AS asesor,
                    COALESCE(f.nombre, 'Sin fuente')                          AS fuente,
                    l.created_at::date                                        AS ingresado,
                    EXTRACT(DAY FROM NOW() - l.created_at)::int               AS dias_antiguedad
                FROM crm.leads l
                LEFT JOIN auth.users u  ON u.id = l.asesor_id
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                WHERE l.activo = TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c
                      WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.llamadas ll
                      WHERE ll.lead_id = l.id
                  )
                ORDER BY l.created_at ASC
                LIMIT 100
                """
            )
            leads_fuga = cur.fetchall()

            # ── Tiempo muerto entre contactos (gaps) ────────────────────
            cur.execute(
                """
                WITH contactos_con_lag AS (
                    SELECT
                        c.asesor_id,
                        c.created_at,
                        LAG(c.created_at) OVER (PARTITION BY c.asesor_id ORDER BY c.created_at) AS anterior
                    FROM crm.contactos c
                    WHERE c.created_at::date BETWEEN %s::date AND %s::date
                      AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                )
                SELECT
                    u.id::text                                                       AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor,
                    COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM
                        (cl.created_at - cl.anterior)) / 3600)::numeric, 1), 0)::float AS horas_gap_prom,
                    COALESCE(MAX(EXTRACT(EPOCH FROM
                        (cl.created_at - cl.anterior)) / 3600)::numeric, 0)::float    AS gap_maximo_h,
                    COUNT(*)::int                                                     AS contactos_total
                FROM contactos_con_lag cl
                JOIN auth.users u ON u.id = cl.asesor_id
                WHERE cl.anterior IS NOT NULL
                GROUP BY u.id, u.first_name, u.last_name
                HAVING COUNT(*) > 5  -- minimo de muestra para que el promedio sea significativo
                ORDER BY horas_gap_prom DESC
                LIMIT 20
                """,
                [f_desde, f_hasta],
            )
            tiempo_muerto = cur.fetchall()

            # ── Mejores horarios (top 5) ───────────────────────────────
            cur.execute(
                f"""
                WITH contactos_horario AS (
                    SELECT
                        EXTRACT(DOW  FROM c.created_at AT TIME ZONE 'America/Lima')::int AS dia_semana,
                        EXTRACT(HOUR FROM c.created_at AT TIME ZONE 'America/Lima')::int AS hora,
                        c.lead_id,
                        CASE WHEN e.es_final = TRUE AND e.nombre NOT IN ({neg_ph})
                             THEN 1 ELSE 0 END AS es_cierre
                    FROM crm.contactos c
                    JOIN crm.leads l         ON l.id = c.lead_id
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE c.created_at::date BETWEEN %s::date AND %s::date
                      AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                )
                SELECT
                    dia_semana, hora,
                    COUNT(*)::int                                              AS total_contactos,
                    SUM(es_cierre)::int                                        AS cierres,
                    COALESCE(ROUND(100.0 * SUM(es_cierre)
                        / NULLIF(COUNT(*), 0), 1), 0)::float                   AS tasa_cierre_pct
                FROM contactos_horario
                GROUP BY dia_semana, hora
                HAVING COUNT(*) >= 5
                ORDER BY tasa_cierre_pct DESC, total_contactos DESC
                LIMIT 5
                """,
                estados_negativos + [f_desde, f_hasta],
            )
            mejores_horarios = cur.fetchall()

            return {
                "fecha_desde":       f_desde,
                "fecha_hasta":       f_hasta,
                "top_asesores":      top_asesores,
                "leads_fuga": {
                    "total": len(leads_fuga),
                    "muestra": leads_fuga[:20],  # solo primeros 20 para no inflar la respuesta
                },
                "tiempo_muerto":     tiempo_muerto,
                "mejores_horarios":  mejores_horarios,
            }


# ════════════════════════════════════════════════════════════════════════════
# REPORTE 6 — Stage Velocity (V095.4)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/stage-velocity")
def stage_velocity(
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """V095.4 — "Stage Aging" patrón estándar: dias promedio que llevan
    los leads ACTIVOS en su estado actual, agrupado por estado.

    Convierte el funnel de foto estatica a pelicula. Si "Calificado" tiene
    18 dias de antiguedad media y "Negociacion" 3 dias, el cuello de
    botella esta en Calificado. Decision accionable inmediata.

    No medimos "tiempo entre transiciones historicas" (eso requeriria una
    tabla dedicada de stage_history o parsing fragil del campo `notas`).
    El stage aging del estado actual cubre el 80% del valor con 20% del
    esfuerzo y datos confiables 100%.
    """
    lead_clause, lead_params = _role_clause_leads(current_user, alias="l")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    e.id, e.nombre, e.color_hex, e.orden, e.es_final,
                    COUNT(l.id)::int                                            AS total_leads,
                    COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM
                        (NOW() - l.updated_at)) / 86400)::numeric, 1), 0)       AS dias_promedio,
                    COALESCE(ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (NOW() - l.updated_at)) / 86400
                    ))::numeric, 1), 0)                                         AS dias_p50,
                    COALESCE(MAX(EXTRACT(EPOCH FROM
                        (NOW() - l.updated_at)) / 86400)::int, 0)               AS dias_max
                FROM crm.estados_lead e
                LEFT JOIN crm.leads l
                    ON l.estado_id = e.id
                   AND l.activo = TRUE
                   AND {lead_clause}
                WHERE e.es_final = FALSE OR e.nombre NOT IN
                    ('Perdido', 'No interesado', 'Descartado', 'No contesta')
                GROUP BY e.id, e.nombre, e.color_hex, e.orden, e.es_final
                ORDER BY e.orden
                """,
                lead_params,
            )
            etapas = cur.fetchall()
    return {"etapas": etapas}


# ════════════════════════════════════════════════════════════════════════════
# REPORTE 7 — Cohort heatmap mensual (V095.5)
# ════════════════════════════════════════════════════════════════════════════

@router.get("/cohort-mensual")
def cohort_mensual(
    meses: int = Query(6, ge=2, le=12),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """V095.5 — Cohort heatmap: filas = mes de ingreso, columnas = estado
    actual. Para una promotora inmobiliaria con ciclo de decision largo
    (semanas/meses), es la herramienta para saber si los leads viejos
    SIGUEN convirtiendo o ya estan muertos.

    patrón estándar y patrón estándar lo llaman "Cohort Analysis". Es un diferenciador
    real vs CRMs basicos — la respuesta a "los leads de marzo, donde estan
    hoy?" se contesta de un vistazo.

    Limites del default (6 meses): cubre ciclo tipico de promotora sin
    saturar la respuesta. El admin puede pedir hasta 12.
    """
    lead_clause, lead_params = _role_clause_leads(current_user, alias="l")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Catalogo de estados ordenado (lo usa el frontend para el header).
            cur.execute(
                """
                SELECT id, nombre, color_hex, orden, es_final
                FROM crm.estados_lead
                ORDER BY orden, id
                """
            )
            estados = cur.fetchall()

            # Cohort: leads agrupados por mes de ingreso x estado actual.
            cur.execute(
                f"""
                SELECT
                    DATE_TRUNC('month',
                        (l.created_at AT TIME ZONE 'America/Lima')::date
                    )::date                                       AS mes,
                    l.estado_id,
                    COUNT(*)::int                                  AS total
                FROM crm.leads l
                WHERE l.activo = TRUE
                  AND (l.created_at AT TIME ZONE 'America/Lima')::date >=
                      DATE_TRUNC('month',
                          (NOW() AT TIME ZONE 'America/Lima')::date - ((%s - 1) || ' months')::INTERVAL
                      )::date
                  AND {lead_clause}
                GROUP BY mes, l.estado_id
                ORDER BY mes DESC, l.estado_id
                """,
                [meses] + lead_params,
            )
            celdas = cur.fetchall()
            for c in celdas:
                # Serializamos fecha como YYYY-MM para que el frontend la use
                # como key sin reformat.
                c["mes"] = c["mes"].isoformat() if c["mes"] else None

    return {"estados": estados, "celdas": celdas}

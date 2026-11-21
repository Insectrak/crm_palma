"""
Reportes router — análisis por asesor y por plataforma con filtro de fechas.
- GET /api/reportes/por-asesor?fecha_desde=&fecha_hasta=
- GET /api/reportes/por-fuente?fecha_desde=&fecha_hasta=
- GET /api/reportes/tiempo-respuesta?fecha_desde=&fecha_hasta=
- GET /api/reportes/funnel?fecha_desde=&fecha_hasta=
- GET /api/reportes/estancados?dias=7
- GET /api/reportes/campanas?fecha_desde=&fecha_hasta=
- GET /api/reportes/actividad-diaria?fecha_desde=&fecha_hasta=
- GET /api/reportes/exportar?tipo=&fecha_desde=&fecha_hasta=
"""
import io
import logging
from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor
from app.auth.jwt import require_supervisor_or_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.filters.lead_filters import role_filter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reportes", tags=["Reportes"])


def _defaults(fecha_desde, fecha_hasta):
    hoy = date.today().isoformat()
    d = fecha_desde.strip() if isinstance(fecha_desde, str) and fecha_desde.strip() else (date.today() - timedelta(days=30)).isoformat()
    h = fecha_hasta.strip() if isinstance(fecha_hasta, str) and fecha_hasta.strip() else hoy
    return d, h


def _team_user_filter(supervisor_id: Optional[str], user_alias: str = "u") -> tuple[str, list]:
    """Filtra usuarios (asesores/supervisores) pertenecientes al equipo del supervisor_id."""
    if not supervisor_id or not isinstance(supervisor_id, str) or not supervisor_id.strip() or supervisor_id.strip().lower() == "all":
        return "", []
    sup_id = supervisor_id.strip()
    clause = (
        f"AND ("
        f"{user_alias}.id = %s::uuid OR "
        f"{user_alias}.id IN (SELECT eq.asesor_id FROM crm.equipos eq WHERE eq.supervisor_id = %s::uuid AND eq.activo = TRUE) OR "
        f"{user_alias}.id IN (SELECT l.asesor_id FROM crm.leads l WHERE l.supervisor_id = %s::uuid AND l.asesor_id IS NOT NULL AND (l.estado_id IN (SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%matr%%' OR nombre ILIKE '%%ganad%%' OR nombre ILIKE '%%cierr%%') OR l.tipo_cierre IS NOT NULL))"
        f")"
    )
    return clause, [sup_id, sup_id, sup_id]


def _team_lead_filter(supervisor_id: Optional[str], lead_alias: str = "l") -> tuple[str, list]:
    """Filtra leads pertenecientes al supervisor_id o a los miembros de su equipo."""
    if not supervisor_id or not isinstance(supervisor_id, str) or not supervisor_id.strip() or supervisor_id.strip().lower() == "all":
        return "", []
    sup_id = supervisor_id.strip()
    clause = (
        f"AND ("
        f"{lead_alias}.supervisor_id = %s::uuid OR "
        f"{lead_alias}.asesor_id = %s::uuid OR "
        f"{lead_alias}.asesor_id IN (SELECT eq.asesor_id FROM crm.equipos eq WHERE eq.supervisor_id = %s::uuid AND eq.activo = TRUE)"
        f")"
    )
    return clause, [sup_id, sup_id, sup_id]


def _build_fuente_lead_filter(
    fuente: Optional[str] = None,
    fuente_id: Optional[int] = None,
    fuente_excluida: Optional[str] = None,
    lead_alias: str = "l",
) -> tuple[str, list]:
    """Genera la cláusula SQL y parámetros para filtrar por fuente y/o excluir fuentes en el JOIN/WHERE de leads.
    Soporta:
      - fuente: nombre o ID de fuente a incluir, o 'sin fuente'
      - fuente_id: ID numérico directo
      - fuente_excluida: nombre o lista separada por comas de fuentes a excluir ('sin fuente', 'Meta', etc.)
    """
    clauses = []
    params = []

    # 1. Inclusión
    if isinstance(fuente_id, int):
        clauses.append(f"{lead_alias}.fuente_id = %s")
        params.append(fuente_id)
    elif isinstance(fuente, str) and fuente.strip() and fuente.strip().lower() != "all":
        f_norm = fuente.strip().lower()
        if f_norm == "sin fuente":
            clauses.append(f"{lead_alias}.fuente_id IS NULL")
        elif f_norm.isdigit():
            clauses.append(f"{lead_alias}.fuente_id = %s")
            params.append(int(f_norm))
        else:
            clauses.append(f"{lead_alias}.fuente_id IN (SELECT id FROM crm.fuentes WHERE LOWER(nombre) = %s)")
            params.append(f_norm)

    # 2. Exclusión (regla de excepción)
    if isinstance(fuente_excluida, str) and fuente_excluida.strip() and fuente_excluida.strip().lower() not in ("none", "all"):
        excluidas = [x.strip() for x in fuente_excluida.split(",") if x.strip()]
        for exc in excluidas:
            exc_norm = exc.lower()
            if exc_norm in ("sin fuente", "null", "none"):
                clauses.append(f"{lead_alias}.fuente_id IS NOT NULL")
            elif exc_norm.isdigit():
                clauses.append(f"({lead_alias}.fuente_id IS NULL OR {lead_alias}.fuente_id != %s)")
                params.append(int(exc_norm))
            else:
                clauses.append(
                    f"({lead_alias}.fuente_id IS NULL OR {lead_alias}.fuente_id NOT IN (SELECT id FROM crm.fuentes WHERE LOWER(nombre) = %s))"
                )
                params.append(exc_norm)

    if not clauses:
        return "", []

    sql_str = "AND " + " AND ".join(clauses)
    return sql_str, params


@router.get("/por-asesor")
def por_asesor(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo de supervisor"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    team_clause, team_params = _team_user_filter(supervisor_id, "u")

    if current_user.role == "supervisor":
        user_filter = (
            "AND ("
            "u.id IN (SELECT eq.asesor_id FROM crm.equipos eq "
            "         WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN ("
            "             SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'"
            "         )) AND eq.activo = TRUE) "
            "OR u.id = %s::uuid "
            "OR u.id IN (SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor') "
            "OR u.id IN (SELECT l.asesor_id FROM crm.leads l WHERE (l.supervisor_id = %s::uuid OR l.supervisor_id IN (SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor')) AND l.asesor_id IS NOT NULL AND (l.estado_id IN (SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%matr%%' OR nombre ILIKE '%%ganad%%' OR nombre ILIKE '%%cierr%%') OR l.tipo_cierre IS NOT NULL))"
            ")"
        )
        params = [
            f_desde, f_hasta,
            current_user.user_id, current_user.user_id,
            current_user.user_id, current_user.user_id,
            current_user.user_id, current_user.user_id,
        ] + team_params
    else:
        user_filter = ""
        params = [f_desde, f_hasta] + team_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    u.id::text AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                        AS nombre_completo,
                    u.role AS rol,
                    COUNT(l.id)                                               AS total_leads,
                    COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL)      AS leads_contactados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')        AS leads_calificados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación')    AS leads_en_negociacion,
                    COUNT(l.id) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                                         AS leads_ganados,
                    COUNT(l.id) FILTER (WHERE e.nombre IN ('No interesado','Perdido'))
                                                                              AS leads_perdidos,
                    COUNT(l.id) FILTER (WHERE lc.contactado IS NULL)          AS leads_sin_contactar,
                    ROUND(
                        COUNT(l.id) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) * 100.0
                        / NULLIF(COUNT(l.id), 0), 2
                    )                                                         AS tasa_conversion_pct,
                    ROUND(
                        COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL) * 100.0
                        / NULLIF(COUNT(l.id), 0), 1
                    )                                                         AS tasa_contactabilidad_pct
                FROM auth.users u
                LEFT JOIN crm.leads l
                    ON  l.asesor_id = u.id
                    AND l.activo = TRUE
                    AND l.created_at >= %s::timestamptz
                    AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
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
                WHERE u.role IN ('asesor','supervisor') AND u.is_active = TRUE
                {user_filter}
                {team_clause}
                GROUP BY u.id, u.first_name, u.last_name, u.role
                HAVING COUNT(l.id) > 0
                ORDER BY total_leads DESC
                """,
                params,
            )
            rows = cur.fetchall()

            if current_user.role == "supervisor":
                cur.execute(
                    """
                    SELECT COUNT(*) AS total FROM auth.users u
                    WHERE u.role IN ('asesor','supervisor') AND u.is_active = TRUE
                      AND (
                          u.id IN (SELECT eq.asesor_id FROM crm.equipos eq
                                   WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN (
                                       SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'
                                   )) AND eq.activo = TRUE)
                          OR u.id = %s::uuid
                          OR u.id IN (SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor')
                      )
                    """,
                    (current_user.user_id, current_user.user_id, current_user.user_id, current_user.user_id),
                )
            else:
                cur.execute(
                    "SELECT COUNT(*) AS total FROM auth.users WHERE role IN ('asesor','supervisor') AND is_active = TRUE"
                )
            asesores_activos = cur.fetchone()["total"]

    total_leads       = sum(r["total_leads"]       for r in rows)
    total_contactados = sum(r["leads_contactados"] for r in rows)
    total_ganados     = sum(r["leads_ganados"]     for r in rows)

    return {
        "rows": rows,
        "resumen": {
            "total_leads":       total_leads,
            "total_contactados": total_contactados,
            "total_ganados":     total_ganados,
            "tasa_conversion":   round(total_ganados * 100.0 / total_leads, 2) if total_leads else 0,
            "asesores_activos":  asesores_activos,
            "asesores_con_leads": len(rows),
        },
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }


@router.get("/por-fuente")
def por_fuente(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    asesor_id: str = Query(None, description="Filtrar métricas de fuentes por asesor"),
    supervisor_id: Optional[str] = Query(None, description="Filtrar métricas por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_lead_filter(supervisor_id, "l")

    asesor_clause = ""
    asesor_params = []
    if asesor_id and asesor_id.strip() and asesor_id.strip().lower() != "all":
        asesor_clause = "AND l.asesor_id = %s::uuid"
        asesor_params = [asesor_id.strip()]

    params = [f_desde, f_hasta] + role_params + asesor_params + team_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    COALESCE(f.nombre, 'sin fuente')                          AS fuente,
                    COUNT(l.id)                                               AS total_leads,
                    COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL)      AS leads_contactados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')        AS leads_calificados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación')    AS leads_en_negociacion,
                    COUNT(l.id) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                                         AS leads_ganados,
                    COUNT(l.id) FILTER (WHERE e.nombre IN ('No interesado','Perdido'))
                                                                              AS leads_perdidos,
                    ROUND(
                        COUNT(l.id) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) * 100.0
                        / NULLIF(COUNT(l.id), 0), 2
                    )                                                         AS tasa_conversion_pct,
                    ROUND(
                        COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL) * 100.0
                        / NULLIF(COUNT(l.id), 0), 1
                    )                                                         AS tasa_contactabilidad_pct
                FROM crm.leads l
                LEFT JOIN crm.fuentes      f ON f.id = l.fuente_id
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
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
                  AND l.created_at >= %s::timestamptz
                  AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                  AND ({role_clause})
                  {asesor_clause}
                  {team_clause}
                GROUP BY f.nombre
                HAVING COUNT(l.id) > 0
                ORDER BY total_leads DESC
                """,
                params,
            )
            rows = cur.fetchall()

    total_leads   = sum(r["total_leads"]   for r in rows)
    total_ganados = sum(r["leads_ganados"] for r in rows)

    return {
        "rows": rows,
        "resumen": {
            "total_leads":    total_leads,
            "total_ganados":  total_ganados,
            "fuentes_activas": len(rows),
            "mejor_fuente":   rows[0]["fuente"] if rows else None,
            "tasa_conversion": round(total_ganados * 100.0 / total_leads, 2) if total_leads else 0,
        },
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }


# =============================================================================
# REPORTE 1 — Tiempo de respuesta por asesor (SLA)
# Mide cuántas horas tarda cada asesor en hacer el primer contacto desde
# que le asignan el lead. Identifica quién cumple el SLA de 1 h y 24 h.
# =============================================================================
@router.get("/tiempo-respuesta")
def tiempo_respuesta(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    team_clause, team_params = _team_user_filter(supervisor_id, "u")

    if current_user.role == "supervisor":
        team_filter = (
            "AND ("
            "u.id IN (SELECT eq.asesor_id FROM crm.equipos eq "
            "         WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN ("
            "             SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'"
            "         )) AND eq.activo = TRUE) "
            "OR u.id = %s::uuid "
            "OR u.id IN (SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor')"
            ")"
        )
        params = [f_desde, f_hasta, current_user.user_id, current_user.user_id, current_user.user_id, current_user.user_id] + team_params
    else:
        team_filter = ""
        params = [f_desde, f_hasta] + team_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH asignados AS (
                    SELECT
                        l.id          AS lead_id,
                        l.asesor_id,
                        al.created_at AS fecha_asignacion
                    FROM crm.leads l
                    JOIN crm.asignaciones_log al
                        ON al.lead_id = l.id
                        AND al.asesor_nuevo = l.asesor_id
                    WHERE l.activo = TRUE
                      AND l.created_at >= %s::timestamptz
                      AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                ),
                primer_c AS (
                    SELECT lead_id, MIN(ts) AS fecha_primer_contacto FROM (
                        SELECT c.lead_id, c.created_at AS ts
                        FROM crm.contactos c
                        WHERE c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                        UNION ALL
                        SELECT ll.lead_id, ll.fecha_llamada AS ts
                        FROM crm.llamadas ll
                        WHERE ll.lead_id IS NOT NULL
                    ) _contacts
                    GROUP BY lead_id
                ),
                tiempos AS (
                    SELECT
                        a.asesor_id,
                        EXTRACT(EPOCH FROM (pc.fecha_primer_contacto - a.fecha_asignacion)) / 3600
                            AS horas_respuesta
                    FROM asignados a
                    JOIN primer_c pc ON pc.lead_id = a.lead_id
                    WHERE pc.fecha_primer_contacto > a.fecha_asignacion
                )
                SELECT
                    u.id::text AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                        AS nombre_completo,
                    COUNT(t.horas_respuesta)                           AS leads_con_contacto,
                    ROUND(AVG(t.horas_respuesta)::numeric, 1)          AS promedio_horas,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY t.horas_respuesta)::numeric, 1)       AS mediana_horas,
                    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (
                        ORDER BY t.horas_respuesta)::numeric, 1)       AS p90_horas,
                    COUNT(t.horas_respuesta) FILTER (
                        WHERE t.horas_respuesta <= 1)                  AS dentro_1h,
                    COUNT(t.horas_respuesta) FILTER (
                        WHERE t.horas_respuesta <= 24)                 AS dentro_24h,
                    ROUND(
                        COUNT(t.horas_respuesta) FILTER (WHERE t.horas_respuesta <= 1) * 100.0
                        / NULLIF(COUNT(t.horas_respuesta), 0), 1)      AS pct_dentro_1h,
                    ROUND(
                        COUNT(t.horas_respuesta) FILTER (WHERE t.horas_respuesta <= 24) * 100.0
                        / NULLIF(COUNT(t.horas_respuesta), 0), 1)      AS pct_dentro_24h
                FROM auth.users u
                LEFT JOIN tiempos t ON t.asesor_id = u.id
                WHERE u.role = 'asesor' AND u.is_active = TRUE
                {team_filter}
                {team_clause}
                GROUP BY u.id, u.first_name, u.last_name
                HAVING COUNT(t.horas_respuesta) > 0
                ORDER BY promedio_horas ASC NULLS LAST
                """,
                params,
            )
            rows = cur.fetchall()

    total_con_contacto = sum(r["leads_con_contacto"] for r in rows)
    dentro_1h  = sum(r["dentro_1h"]  for r in rows)
    dentro_24h = sum(r["dentro_24h"] for r in rows)

    return {
        "rows": rows,
        "resumen": {
            "total_con_contacto": total_con_contacto,
            "pct_equipo_1h":  round(dentro_1h  * 100.0 / total_con_contacto, 1) if total_con_contacto else 0,
            "pct_equipo_24h": round(dentro_24h * 100.0 / total_con_contacto, 1) if total_con_contacto else 0,
        },
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }


# =============================================================================
# REPORTE 2 — Embudo de conversión (funnel)
# Muestra cuántos leads hay en cada etapa del pipeline y el % de conversión
# entre etapas consecutivas. Señala visualmente el cuello de botella.
# =============================================================================
@router.get("/funnel")
def funnel(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_lead_filter(supervisor_id, "l")
    params = [f_desde, f_hasta] + role_params + team_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    e.id,
                    e.nombre    AS estado,
                    e.orden,
                    e.color_hex,
                    e.es_final,
                    COUNT(l.id) AS total
                FROM crm.estados_lead e
                LEFT JOIN crm.leads l
                    ON  l.estado_id = e.id
                    AND l.activo = TRUE
                    AND l.created_at >= %s::timestamptz
                    AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                    AND ({role_clause})
                    {team_clause}
                GROUP BY e.id, e.nombre, e.orden, e.color_hex, e.es_final
                ORDER BY e.orden
                """,
                params,
            )
            rows = cur.fetchall()

    total_general = sum(r["total"] for r in rows)

    etapas = []
    for i, row in enumerate(rows):
        prev_total = rows[i - 1]["total"] if i > 0 else None
        etapas.append({
            "estado":     row["estado"],
            "orden":      row["orden"],
            "color_hex":  row["color_hex"],
            "es_final":   row["es_final"],
            "total":      row["total"],
            "pct_total":  round(row["total"] * 100.0 / total_general, 1) if total_general else 0,
            "conversion_desde_anterior": (
                round(row["total"] * 100.0 / prev_total, 1)
                if prev_total and prev_total > 0 else None
            ),
        })

    return {
        "etapas": etapas,
        "resumen": {
            "total_leads": total_general,
            "ganados": next((e["total"] for e in etapas if e["estado"] == "Ganado"), 0),
            "perdidos": next((e["total"] for e in etapas if e["estado"] in ("Perdido", "No interesado")), 0),
        },
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }


# =============================================================================
# REPORTE 3 — Leads estancados
# Lista leads activos no terminales sin contacto real en los últimos N días,
# agrupados por asesor, ordenados por mayor inactividad primero.
# =============================================================================
@router.get("/estancados")
def estancados(
    dias: int = Query(7, ge=1, le=90),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_lead_filter(supervisor_id, "l")
    # Orden de placeholders en la query: 1) role_clause (N params), 2) team_params, 3) dias (1 param)
    params = role_params + team_params + [dias]

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH ultimo_c AS (
                    SELECT lead_id, MAX(ts) AS fecha_ultimo_contacto FROM (
                        SELECT c.lead_id, c.created_at AS ts
                        FROM crm.contactos c
                        WHERE c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                        UNION ALL
                        SELECT ll.lead_id, ll.fecha_llamada AS ts
                        FROM crm.llamadas ll
                        WHERE ll.lead_id IS NOT NULL
                    ) _contacts
                    GROUP BY lead_id
                )
                SELECT
                    l.id                                                       AS lead_id,
                    TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,''))
                                                                               AS nombre_lead,
                    l.telefono,
                    e.nombre                                                   AS estado,
                    e.color_hex,
                    COALESCE(f.nombre, 'sin fuente')                           AS fuente,
                    l.created_at::date                                         AS fecha_ingreso,
                    uc.fecha_ultimo_contacto::date                             AS fecha_ultimo_contacto,
                    COALESCE(
                        EXTRACT(EPOCH FROM (NOW() - uc.fecha_ultimo_contacto)) / 86400,
                        EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 86400
                    )::int                                                     AS dias_inactivo,
                    TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,''))
                                                                               AS asesor_nombre,
                    l.asesor_id::text                                          AS asesor_id
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                LEFT JOIN auth.users  a ON a.id = l.asesor_id
                LEFT JOIN ultimo_c   uc ON uc.lead_id = l.id
                WHERE l.activo = TRUE
                  AND e.es_final = FALSE
                  AND ({role_clause})
                  {team_clause}
                  AND (
                      uc.lead_id IS NULL
                      OR uc.fecha_ultimo_contacto < NOW() - (%s * INTERVAL '1 day')
                  )
                ORDER BY dias_inactivo DESC
                LIMIT 200
                """,
                params,
            )
            rows = cur.fetchall()

    by_asesor = {}
    for r in rows:
        key = r["asesor_nombre"] or "Sin asignar"
        by_asesor.setdefault(key, []).append(r)

    resumen_asesores = sorted(
        [{"asesor": k, "cantidad": len(v)} for k, v in by_asesor.items()],
        key=lambda x: -x["cantidad"],
    )

    return {
        "rows": rows,
        "resumen_por_asesor": resumen_asesores,
        "resumen": {
            "total_estancados": len(rows),
            "dias_umbral": dias,
        },
    }


# =============================================================================
# REPORTE 4 — Rendimiento de campañas
# Por campaña publicitaria: volumen de leads, tasas de avance en el funnel
# y tiempo promedio al primer contacto. Identifica campañas de calidad.
# =============================================================================
@router.get("/campanas")
def campanas(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    asesor_id: str = Query(None, description="Filtrar métricas de campañas por asesor"),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_lead_filter(supervisor_id, "l")

    asesor_clause = ""
    asesor_params = []
    has_asesor_filter = bool(asesor_id and asesor_id.strip() and asesor_id.strip().lower() != "all")
    if has_asesor_filter:
        asesor_clause = "AND l.asesor_id = %s::uuid"
        asesor_params = [asesor_id.strip()]

    params = [f_desde, f_hasta] + role_params + asesor_params + team_params
    min_leads_having = 1 if (has_asesor_filter or supervisor_id) else 5

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH primer_c AS (
                    SELECT lead_id, MIN(ts) AS fecha_primer_contacto FROM (
                        SELECT c.lead_id, c.created_at AS ts
                        FROM crm.contactos c
                        WHERE c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                        UNION ALL
                        SELECT ll.lead_id, ll.fecha_llamada AS ts
                        FROM crm.llamadas ll
                        WHERE ll.lead_id IS NOT NULL
                    ) _contacts
                    GROUP BY lead_id
                )
                SELECT
                    COALESCE(NULLIF(TRIM(l.campana), ''), 'Sin campaña') AS campana,
                    COALESCE(f.nombre, 'sin fuente')                     AS fuente,
                    COUNT(l.id)                                          AS total_leads,
                    COUNT(l.id) FILTER (WHERE pc.fecha_primer_contacto IS NOT NULL)
                                                                         AS leads_contactados,
                    COUNT(l.id) FILTER (WHERE e.nombre IN (
                        'Calificado','En negociación','Ganado'))          AS leads_calificados,
                    COUNT(l.id) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                                    AS leads_ganados,
                    COUNT(l.id) FILTER (WHERE e.nombre IN ('No interesado','Perdido'))
                                                                         AS leads_perdidos,
                    ROUND(
                        COUNT(l.id) FILTER (WHERE pc.fecha_primer_contacto IS NOT NULL) * 100.0
                        / NULLIF(COUNT(l.id), 0), 1)                     AS pct_contactados,
                    ROUND(
                        COUNT(l.id) FILTER (WHERE e.nombre IN (
                            'Calificado','En negociación','Ganado')
                            OR e.nombre ILIKE '%%matr%%') * 100.0
                        / NULLIF(COUNT(l.id), 0), 1)                     AS pct_calificados,
                    ROUND(
                        COUNT(l.id) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) * 100.0
                        / NULLIF(COUNT(l.id), 0), 2)                     AS pct_ganados,
                    ROUND(AVG(
                        EXTRACT(EPOCH FROM (pc.fecha_primer_contacto - l.created_at)) / 3600
                    )::numeric, 1)                                       AS horas_primer_contacto
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes      f ON f.id = l.fuente_id
                LEFT JOIN primer_c        pc ON pc.lead_id = l.id
                WHERE l.activo = TRUE
                  AND l.created_at >= %s::timestamptz
                  AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                  AND ({role_clause})
                  {asesor_clause}
                  {team_clause}
                GROUP BY COALESCE(NULLIF(TRIM(l.campana), ''), 'Sin campaña'), f.nombre
                HAVING COUNT(l.id) >= {min_leads_having}
                ORDER BY total_leads DESC
                LIMIT 50
                """,
                params,
            )
            rows = cur.fetchall()

    total_leads   = sum(r["total_leads"]   for r in rows)
    total_ganados = sum(r["leads_ganados"] for r in rows)

    return {
        "rows": rows,
        "resumen": {
            "total_campanas":  len(rows),
            "total_leads":     total_leads,
            "total_ganados":   total_ganados,
            "mejor_campana":   rows[0]["campana"] if rows else None,
        },
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }


# =============================================================================
# SPRINT 1 — Reporte de Llamadas (eficiencia)
# Promedio duración + % efectivas (>=2min) + % cortas (<30s) por asesor
# Tambien desagrega por calidad de lead (FRIO/TIBIO/CALIENTE) para ver
# si el asesor invierte mas tiempo en leads calientes que en frios.
# =============================================================================
@router.get("/llamadas")
def reporte_llamadas(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    fuente: Optional[str] = Query(None, description="Filtrar por fuente (nombre o ID o 'sin fuente')"),
    fuente_id: Optional[int] = Query(None, description="Filtrar por ID de fuente"),
    fuente_excluida: Optional[str] = Query(None, description="Excluir fuente(s)"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """KPI de llamadas por asesor — patron estandar Call Reports.

    Metrica clave: % efectivas (llamadas >= 120s) vs % cortas (< 30s).
    El benchmark del sector inmobiliario es ~40% efectivas, <20% cortas.
    Si un asesor tiene >40% cortas, hay un problema de calidad de pitch.
    """
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_user_filter(supervisor_id, "u")
    lead_team_clause, lead_team_params = _team_lead_filter(supervisor_id, "l")
    fuente_clause, fuente_params = _build_fuente_lead_filter(fuente=fuente, fuente_id=fuente_id, fuente_excluida=fuente_excluida, lead_alias="l")
    # Cada role_clause tiene 0 (admin) o 3 (supervisor) o 1 (asesor) params.
    params = [f_desde, f_hasta] + role_params + lead_team_params + fuente_params + [f_desde, f_hasta] + role_params + lead_team_params + fuente_params + team_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH all_llamadas AS (
                    -- Fuente 1: app movil (call log Android via crm.llamadas)
                    SELECT
                        ll.asesor_id,
                        ll.duracion_segundos,
                        ll.tipo,
                        ll.lead_id,
                        'app'::text AS fuente
                    FROM crm.llamadas ll
                    LEFT JOIN crm.leads l ON l.id = ll.lead_id
                    WHERE ll.fecha_llamada >= %s::timestamptz
                      AND ll.fecha_llamada <  (%s::date + INTERVAL '1 day')::timestamptz
                      AND (ll.lead_id IS NULL OR ({role_clause} {lead_team_clause}))
                      {fuente_clause}
                    UNION ALL
                    -- Fuente 2: registro manual desde la ficha del lead
                    SELECT
                        c.asesor_id,
                        COALESCE(c.duracion_minutos * 60, 0) AS duracion_segundos,
                        NULL::text AS tipo,
                        c.lead_id,
                        'manual'::text AS fuente
                    FROM crm.contactos c
                    LEFT JOIN crm.leads l ON l.id = c.lead_id
                    WHERE LOWER(c.tipo_contacto) = 'llamada'
                      AND c.created_at >= %s::timestamptz
                      AND c.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                      AND ({role_clause} {lead_team_clause})
                      {fuente_clause}
                )
                SELECT
                    u.id::text          AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                                        AS nombre_completo,
                    u.role              AS rol,
                    COUNT(al.asesor_id) AS total_llamadas,
                    COUNT(al.asesor_id) FILTER (WHERE al.duracion_segundos > 0)
                                        AS llamadas_con_duracion,
                    COUNT(al.asesor_id) FILTER (WHERE al.fuente = 'app')
                                        AS llamadas_app,
                    COUNT(al.asesor_id) FILTER (WHERE al.fuente = 'manual')
                                        AS llamadas_manual,
                    ROUND(AVG(NULLIF(al.duracion_segundos, 0))::numeric, 0)::int
                                        AS duracion_promedio_seg,
                    ROUND(AVG(NULLIF(al.duracion_segundos, 0)) FILTER (WHERE al.fuente = 'app')::numeric, 0)::int
                                        AS duracion_promedio_app_seg,
                    ROUND(AVG(NULLIF(al.duracion_segundos, 0)) FILTER (WHERE al.fuente = 'manual')::numeric, 0)::int
                                        AS duracion_promedio_manual_seg,
                    SUM(al.duracion_segundos)::int
                                        AS duracion_total_seg,
                    COUNT(al.asesor_id) FILTER (WHERE al.duracion_segundos >= 120)
                                        AS llamadas_efectivas,
                    COUNT(al.asesor_id) FILTER (WHERE al.duracion_segundos < 30 AND al.duracion_segundos > 0)
                                        AS llamadas_cortas,
                    COUNT(al.asesor_id) FILTER (WHERE al.duracion_segundos = 0 OR al.tipo = 'sin_respuesta')
                                        AS llamadas_sin_respuesta,
                    ROUND(
                        COUNT(al.asesor_id) FILTER (WHERE al.duracion_segundos >= 120) * 100.0
                        / NULLIF(COUNT(al.asesor_id), 0), 1
                    )                   AS pct_efectivas,
                    ROUND(
                        COUNT(al.asesor_id) FILTER (WHERE al.duracion_segundos < 30 AND al.duracion_segundos > 0) * 100.0
                        / NULLIF(COUNT(al.asesor_id), 0), 1
                    )                   AS pct_cortas
                FROM auth.users u
                LEFT JOIN all_llamadas al ON al.asesor_id = u.id
                WHERE u.role IN ('asesor', 'supervisor') AND u.is_active = TRUE
                {team_clause}
                GROUP BY u.id, u.first_name, u.last_name, u.role
                HAVING COUNT(al.asesor_id) > 0
                ORDER BY total_llamadas DESC
                """,
                params,
            )
            rows = cur.fetchall()

    # Segunda agregacion: por calidad de lead
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH llamadas_periodo AS (
                    SELECT
                        ll.duracion_segundos,
                        ll.tipo,
                        COALESCE(UPPER(l.calidad), 'SIN_CLASIFICAR') AS calidad_codigo
                    FROM crm.llamadas ll
                    LEFT JOIN crm.leads l ON l.id = ll.lead_id
                    WHERE ll.fecha_llamada >= %s::timestamptz
                      AND ll.fecha_llamada <  (%s::date + INTERVAL '1 day')::timestamptz
                      AND (ll.lead_id IS NULL OR ({role_clause} {lead_team_clause}))
                    UNION ALL
                    SELECT
                        COALESCE(c.duracion_minutos * 60, 0) AS duracion_segundos,
                        NULL::text AS tipo,
                        COALESCE(UPPER(l.calidad), 'SIN_CLASIFICAR') AS calidad_codigo
                    FROM crm.contactos c
                    LEFT JOIN crm.leads l ON l.id = c.lead_id
                    WHERE LOWER(c.tipo_contacto) = 'llamada'
                      AND c.created_at >= %s::timestamptz
                      AND c.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                      AND ({role_clause} {lead_team_clause})
                )
                SELECT
                    lp.calidad_codigo                    AS calidad,
                    COALESCE(cc.nombre, 'Sin clasificar') AS nombre,
                    COALESCE(cc.color_hex, '#94A3B8')    AS color_hex,
                    COUNT(*)                             AS total_llamadas,
                    ROUND(AVG(lp.duracion_segundos)::numeric, 0)::int
                                                         AS duracion_promedio_seg,
                    SUM(lp.duracion_segundos)::int       AS duracion_total_seg,
                    COUNT(*) FILTER (WHERE lp.duracion_segundos >= 120)
                                                         AS llamadas_efectivas,
                    COUNT(*) FILTER (WHERE lp.duracion_segundos < 30 AND lp.duracion_segundos > 0)
                                                         AS llamadas_cortas,
                    ROUND(
                        COUNT(*) FILTER (WHERE lp.duracion_segundos >= 120) * 100.0
                        / NULLIF(COUNT(*), 0), 1
                    )                                    AS pct_efectivas,
                    ROUND(
                        COUNT(*) FILTER (WHERE lp.duracion_segundos < 30 AND lp.duracion_segundos > 0) * 100.0
                        / NULLIF(COUNT(*), 0), 1
                    )                                    AS pct_cortas
                FROM llamadas_periodo lp
                LEFT JOIN crm.catalogo_calidad cc
                    ON UPPER(cc.codigo) = lp.calidad_codigo
                GROUP BY lp.calidad_codigo, cc.nombre, cc.color_hex, cc.orden
                ORDER BY COALESCE(cc.orden, 999), lp.calidad_codigo
                """,
                [f_desde, f_hasta] + role_params + lead_team_params + [f_desde, f_hasta] + role_params + lead_team_params,
            )
            calidad_rows = cur.fetchall()

    return {
        "asesores": [dict(r) for r in rows],
        "por_calidad": [dict(r) for r in calidad_rows],
        "periodo":  {"desde": f_desde, "hasta": f_hasta},
        "totales":  {
            "total_llamadas":      sum(r["total_llamadas"] or 0 for r in rows),
            "total_efectivas":     sum(r["llamadas_efectivas"] or 0 for r in rows),
            "total_cortas":        sum(r["llamadas_cortas"] or 0 for r in rows),
        },
    }


# =============================================================================
# SPRINT 1 — Reporte de Citas (V042 estados)
# Citas agendadas + tasa efectividad por asesor
# =============================================================================
@router.get("/citas")
def reporte_citas(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    fuente: Optional[str] = Query(None, description="Filtrar por fuente (nombre o ID o 'sin fuente')"),
    fuente_id: Optional[int] = Query(None, description="Filtrar por ID de fuente"),
    fuente_excluida: Optional[str] = Query(None, description="Excluir fuente(s)"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """KPI de citas por asesor con desglose por estado V042.

    tasa_efectividad = completadas / total citas.
    """
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_user_filter(supervisor_id, "u")
    fuente_clause, fuente_params = _build_fuente_lead_filter(fuente=fuente, fuente_id=fuente_id, fuente_excluida=fuente_excluida, lead_alias="l")
    params = [f_desde, f_hasta] + role_params + team_params + fuente_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    u.id::text          AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                                        AS nombre_completo,
                    COUNT(c.id)         AS total_citas,
                    COUNT(c.id) FILTER (WHERE ce.codigo = 'pendiente')    AS pendientes,
                    COUNT(c.id) FILTER (WHERE ce.codigo = 'completada')   AS completadas,
                    COUNT(c.id) FILTER (WHERE ce.codigo = 'reprogramada') AS reprogramadas,
                    COUNT(c.id) FILTER (WHERE ce.codigo = 'cancelada')    AS canceladas,
                    COUNT(c.id) FILTER (WHERE ce.codigo = 'no_asistio')   AS no_asistio,
                    ROUND(
                        COUNT(c.id) FILTER (WHERE ce.codigo = 'completada') * 100.0
                        / NULLIF(COUNT(c.id), 0), 1
                    )                   AS tasa_efectividad
                FROM auth.users u
                LEFT JOIN crm.contactos c
                    ON  c.asesor_id = u.id
                    AND c.fecha_cita IS NOT NULL
                    AND c.fecha_cita >= %s::timestamptz
                    AND c.fecha_cita <  (%s::date + INTERVAL '1 day')::timestamptz
                LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                LEFT JOIN crm.leads l ON l.id = c.lead_id
                WHERE u.role IN ('asesor','supervisor') AND u.is_active = TRUE
                  AND (c.id IS NULL OR ({role_clause}))
                  {team_clause}
                  {fuente_clause}
                GROUP BY u.id, u.first_name, u.last_name
                HAVING COUNT(c.id) > 0
                ORDER BY total_citas DESC
                """,
                params,
            )
            rows = cur.fetchall()

    return {
        "asesores": [dict(r) for r in rows],
        "periodo":  {"desde": f_desde, "hasta": f_hasta},
        "totales": {
            "total_citas":   sum(r["total_citas"] or 0 for r in rows),
            "completadas":   sum(r["completadas"] or 0 for r in rows),
            "no_asistio":    sum(r["no_asistio"] or 0 for r in rows),
            "canceladas":    sum(r["canceladas"] or 0 for r in rows),
        },
    }


# =============================================================================
# SPRINT 1 — Ranking asesores (top performers)
# =============================================================================
@router.get("/ranking")
def ranking_asesores(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    metrica:     str = Query("matriculas", description="matriculas | contactabilidad | conversion | citas | llamadas"),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    fuente:      Optional[str] = Query(None, description="Filtrar por fuente (nombre o ID o 'sin fuente')"),
    fuente_id:   Optional[int] = Query(None, description="Filtrar por ID de fuente"),
    fuente_excluida: Optional[str] = Query(None, description="Regla de excepción para excluir fuentes del ranking"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Ranking de asesores por metrica (por defecto: total de matrículas del período)."""
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    team_clause, team_params = _team_user_filter(supervisor_id, "u")
    fuente_clause, fuente_params = _build_fuente_lead_filter(fuente=fuente, fuente_id=fuente_id, fuente_excluida=fuente_excluida, lead_alias="l")

    if current_user.role == "supervisor":
        user_filter = (
            "AND ("
            "u.id IN (SELECT eq.asesor_id FROM crm.equipos eq "
            "         WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN ("
            "             SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'"
            "         )) AND eq.activo = TRUE) "
            "OR u.id = %s::uuid "
            "OR u.id IN (SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor')"
            ")"
        )
        sup_params = [current_user.user_id, current_user.user_id, current_user.user_id, current_user.user_id]
    else:
        user_filter = ""
        sup_params = []

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    u.id::text          AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                                        AS nombre_completo,
                    u.role              AS rol,
                    COUNT(l.id)                                                  AS total_leads,
                    COUNT(l.id) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                                            AS leads_ganados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')           AS leads_calificados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación')       AS leads_en_negociacion,
                    COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL)         AS leads_contactados,
                    COUNT(l.id) FILTER (WHERE lc.contactado IS NULL)             AS leads_sin_contactar,
                    ROUND(
                        COUNT(l.id) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) * 100.0
                        / NULLIF(COUNT(l.id), 0), 2
                    )                                                            AS tasa_conversion_pct,
                    ROUND(
                        COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL) * 100.0
                        / NULLIF(COUNT(l.id), 0), 1
                    )                                                            AS tasa_contactabilidad_pct
                FROM auth.users u
                LEFT JOIN crm.leads l
                    ON  l.asesor_id = u.id
                    AND l.activo = TRUE
                    AND l.created_at >= %s::timestamptz
                    AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                    {fuente_clause}
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
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
                WHERE u.role IN ('asesor','supervisor') AND u.is_active = TRUE
                {user_filter}
                {team_clause}
                GROUP BY u.id, u.first_name, u.last_name, u.role
                ORDER BY total_leads DESC
                """,
                [f_desde, f_hasta] + fuente_params + sup_params + team_params,
            )
            rows = [dict(r) for r in cur.fetchall()]

    # Llamadas merge para metrica='llamadas'
    if metrica == "llamadas":
        try:
            llamadas = reporte_llamadas(f_desde, f_hasta, supervisor_id, fuente=fuente, fuente_id=fuente_id, fuente_excluida=fuente_excluida, current_user=current_user).get("asesores", [])
            ll_map = {ll["asesor_id"]: ll for ll in llamadas}
            for r in rows:
                ll = ll_map.get(r.get("asesor_id"))
                r["total_llamadas"] = (ll or {}).get("total_llamadas", 0)
                r["pct_efectivas"]  = (ll or {}).get("pct_efectivas", 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ranking llamadas merge fallo: %s", exc)

    # Citas merge para metrica='citas'
    if metrica == "citas":
        try:
            citas = reporte_citas(f_desde, f_hasta, supervisor_id, fuente=fuente, fuente_id=fuente_id, fuente_excluida=fuente_excluida, current_user=current_user).get("asesores", [])
            c_map = {c["asesor_id"]: c for c in citas}
            for r in rows:
                c = c_map.get(r.get("asesor_id"))
                r["total_citas"] = (c or {}).get("total_citas", 0)
                r["citas_completadas"] = (c or {}).get("completadas", 0)
                r["citas_pendientes"] = (c or {}).get("pendientes", 0)
                r["tasa_efectividad_citas"] = (c or {}).get("tasa_efectividad", 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ranking citas merge fallo: %s", exc)
            for r in rows:
                r.setdefault("total_citas", 0)
                r.setdefault("citas_completadas", 0)

    # Ordenar segun metrica
    if metrica == "contactabilidad":
        rows = sorted(rows, key=lambda r: (-(r.get("tasa_contactabilidad_pct") or 0),
                                            -(r.get("leads_contactados", 0) or 0),
                                            -(r.get("total_leads", 0))))
    elif metrica == "citas":
        rows = sorted(rows, key=lambda r: (-(r.get("total_citas", 0) or 0),
                                            -(r.get("citas_completadas", 0) or 0),
                                            -(r.get("total_leads", 0))))
    elif metrica == "llamadas":
        rows = sorted(rows, key=lambda r: (-(r.get("total_llamadas", 0) or 0),
                                            -(r.get("total_leads", 0))))
    elif metrica == "conversion":
        rows = sorted(rows, key=lambda r: (-(r.get("tasa_conversion_pct") or 0),
                                            -(r.get("leads_ganados", 0) or 0),
                                            -(r.get("total_leads", 0))))
    else:  # matriculas (default)
        rows = sorted(rows, key=lambda r: (-(r.get("leads_ganados", 0) or 0),
                                            -(r.get("tasa_conversion_pct") or 0),
                                            -(r.get("total_leads", 0))))

    # Asignar posicion solo a asesores con actividad en el periodo
    posicion = 0
    for r in rows:
        if (r.get("total_leads") or 0) > 0 or (r.get("total_llamadas") or 0) > 0 or (r.get("total_citas") or 0) > 0:
            posicion += 1
            r["posicion"] = posicion
        else:
            r["posicion"] = None  # sin actividad

    return {
        "ranking": rows,
        "metrica": metrica,
        "fuente": fuente or (str(fuente_id) if fuente_id is not None else None),
        "fuente_excluida": fuente_excluida,
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }


# =============================================================================
# Ranking por equipo (V049) — agrupado por supervisor
# =============================================================================

@router.get("/ranking-equipos")
def ranking_equipos(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    metrica:     str = Query("matriculas", description="matriculas | contactabilidad | conversion | citas | llamadas"),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    fuente:      Optional[str] = Query(None, description="Filtrar por fuente (nombre o ID o 'sin fuente')"),
    fuente_id:   Optional[int] = Query(None, description="Filtrar por ID de fuente"),
    fuente_excluida: Optional[str] = Query(None, description="Regla de excepción para excluir fuentes del ranking"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Ranking agrupado por equipo (supervisor + sus asesores).

    Suma metricas de todo el equipo: total leads asignados a cualquier
    miembro (supervisor o asesor), ganados, calificados, etc.
    """
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    fuente_clause, fuente_params = _build_fuente_lead_filter(fuente=fuente, fuente_id=fuente_id, fuente_excluida=fuente_excluida, lead_alias="l")

    sup_filter = ""
    sup_params = []

    # Si current_user es supervisor, ve su propio equipo y equipos subordinados. Admin ve todos.
    if current_user.role == "supervisor":
        sup_filter += (
            "AND (sup.id = %s::uuid OR sup.id IN ("
            "    SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'"
            ")) "
        )
        sup_params.extend([current_user.user_id, current_user.user_id])

    if isinstance(supervisor_id, str) and supervisor_id.strip() and supervisor_id.strip().lower() != "all":
        sup_filter += "AND sup.id = %s::uuid "
        sup_params.append(supervisor_id.strip())

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH team_members AS (
                    -- Para cada supervisor, arma el array de UUIDs del equipo
                    -- (supervisor + asesores activos en crm.equipos).
                    SELECT
                        sup.id AS supervisor_id,
                        sup.first_name, sup.last_name, sup.email,
                        ARRAY[sup.id] || COALESCE(
                            ARRAY_AGG(eq.asesor_id) FILTER (WHERE eq.activo = TRUE),
                            ARRAY[]::uuid[]
                        ) AS team_ids,
                        COUNT(eq.asesor_id) FILTER (WHERE eq.activo = TRUE)::int AS num_asesores
                    FROM auth.users sup
                    LEFT JOIN crm.equipos eq ON eq.supervisor_id = sup.id
                    WHERE sup.role = 'supervisor' AND sup.is_active = TRUE
                    {sup_filter}
                    GROUP BY sup.id, sup.first_name, sup.last_name, sup.email
                )
                SELECT
                    tm.supervisor_id::text AS supervisor_id,
                    TRIM(COALESCE(tm.first_name,'') || ' ' || COALESCE(tm.last_name,'')) AS supervisor_nombre,
                    tm.email,
                    tm.num_asesores,
                    array_length(tm.team_ids, 1) AS team_size,
                    COUNT(l.id)                                                 AS total_leads,
                    COUNT(l.id) FILTER (
                        WHERE e.nombre ILIKE '%%matr%%'
                           OR e.nombre ILIKE '%%ganad%%'
                           OR e.nombre ILIKE '%%cierr%%'
                    )                                                           AS leads_ganados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')          AS leads_calificados,
                    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación')      AS leads_en_negociacion,
                    COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL)        AS leads_contactados,
                    COUNT(l.id) FILTER (WHERE lc.contactado IS NULL)            AS leads_sin_contactar,
                    ROUND(
                        COUNT(l.id) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                        ) * 100.0
                        / NULLIF(COUNT(l.id), 0), 2
                    )                                                           AS tasa_conversion_pct,
                    ROUND(
                        COUNT(l.id) FILTER (WHERE lc.contactado IS NOT NULL) * 100.0
                        / NULLIF(COUNT(l.id), 0), 1
                    )                                                           AS tasa_contactabilidad_pct
                FROM team_members tm
                LEFT JOIN crm.leads l
                    ON  l.asesor_id = ANY(tm.team_ids)
                    AND l.activo = TRUE
                    AND l.created_at >= %s::timestamptz
                    AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                    {fuente_clause}
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
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
                GROUP BY tm.supervisor_id, tm.first_name, tm.last_name, tm.email,
                         tm.num_asesores, tm.team_ids
                ORDER BY total_leads DESC
                """,
                sup_params + [f_desde, f_hasta] + fuente_params,
            )
            rows = [dict(r) for r in cur.fetchall()]

    # Ordenar segun metrica
    if metrica == "contactabilidad":
        rows = sorted(rows, key=lambda r: (-(r.get("tasa_contactabilidad_pct") or 0),
                                            -(r.get("leads_contactados", 0) or 0),
                                            -(r.get("total_leads", 0))))
    elif metrica == "llamadas":
        # Para llamadas: agregamos count desde crm.llamadas y crm.contactos por equipo
        try:
            fuente_al_join = f"JOIN crm.leads l ON l.id = al.lead_id {fuente_clause}" if fuente_clause else ""
            with get_db() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"""
                        WITH team_members AS (
                            SELECT
                                sup.id AS supervisor_id,
                                ARRAY[sup.id] || COALESCE(
                                    ARRAY_AGG(eq.asesor_id) FILTER (WHERE eq.activo = TRUE),
                                    ARRAY[]::uuid[]
                                ) AS team_ids
                            FROM auth.users sup
                            LEFT JOIN crm.equipos eq ON eq.supervisor_id = sup.id
                            WHERE sup.role = 'supervisor' AND sup.is_active = TRUE
                            GROUP BY sup.id
                        ),
                        all_llamadas AS (
                            SELECT ll.asesor_id, ll.lead_id
                            FROM crm.llamadas ll
                            WHERE ll.fecha_llamada >= %s::timestamptz
                              AND ll.fecha_llamada <  (%s::date + INTERVAL '1 day')::timestamptz
                            UNION ALL
                            SELECT c.asesor_id, c.lead_id
                            FROM crm.contactos c
                            WHERE LOWER(c.tipo_contacto) = 'llamada'
                              AND c.created_at >= %s::timestamptz
                              AND c.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                        )
                        SELECT tm.supervisor_id::text AS supervisor_id,
                               COUNT(al.asesor_id)::int AS total_llamadas
                        FROM team_members tm
                        LEFT JOIN all_llamadas al
                            ON al.asesor_id = ANY(tm.team_ids)
                        {fuente_al_join}
                        GROUP BY tm.supervisor_id
                        """,
                        [f_desde, f_hasta, f_desde, f_hasta] + fuente_params,
                    )
                    ll_map = {r["supervisor_id"]: r["total_llamadas"] for r in cur.fetchall()}
                    for r in rows:
                        r["total_llamadas"] = ll_map.get(r["supervisor_id"], 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ranking-equipos llamadas merge fallo: %s", exc)
            for r in rows:
                r.setdefault("total_llamadas", 0)
        rows = sorted(rows, key=lambda r: (-(r.get("total_llamadas", 0) or 0),
                                            -(r.get("total_leads", 0))))
    elif metrica == "citas":
        try:
            fuente_c_join = f"JOIN crm.leads l ON l.id = c.lead_id {fuente_clause}" if fuente_clause else ""
            with get_db() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"""
                        WITH team_members AS (
                            SELECT
                                sup.id AS supervisor_id,
                                ARRAY[sup.id] || COALESCE(
                                    ARRAY_AGG(eq.asesor_id) FILTER (WHERE eq.activo = TRUE),
                                    ARRAY[]::uuid[]
                                ) AS team_ids
                            FROM auth.users sup
                            LEFT JOIN crm.equipos eq ON eq.supervisor_id = sup.id
                            WHERE sup.role = 'supervisor' AND sup.is_active = TRUE
                            GROUP BY sup.id
                        )
                        SELECT tm.supervisor_id::text AS supervisor_id,
                               COUNT(c.id)::int AS total_citas,
                               COUNT(c.id) FILTER (WHERE ce.codigo = 'completada')::int AS citas_completadas
                        FROM team_members tm
                        LEFT JOIN crm.contactos c
                            ON c.asesor_id = ANY(tm.team_ids)
                            AND c.fecha_cita IS NOT NULL
                            AND c.fecha_cita >= %s::timestamptz
                            AND c.fecha_cita <  (%s::date + INTERVAL '1 day')::timestamptz
                        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                        {fuente_c_join}
                        GROUP BY tm.supervisor_id
                        """,
                        [f_desde, f_hasta] + fuente_params,
                    )
                    c_map = {r["supervisor_id"]: r for r in cur.fetchall()}
                    for r in rows:
                        c = c_map.get(r["supervisor_id"])
                        r["total_citas"] = (c or {}).get("total_citas", 0) if c else 0
                        r["citas_completadas"] = (c or {}).get("citas_completadas", 0) if c else 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("ranking-equipos citas merge fallo: %s", exc)
            for r in rows:
                r.setdefault("total_citas", 0)
                r.setdefault("citas_completadas", 0)
        rows = sorted(rows, key=lambda r: (-(r.get("total_citas", 0) or 0),
                                            -(r.get("citas_completadas", 0) or 0),
                                            -(r.get("total_leads", 0))))
    elif metrica == "conversion":
        rows = sorted(rows, key=lambda r: (-(r.get("tasa_conversion_pct") or 0),
                                            -(r.get("leads_ganados", 0) or 0),
                                            -(r.get("total_leads", 0))))
    else:  # matriculas default
        rows = sorted(rows, key=lambda r: (-(r.get("leads_ganados", 0) or 0),
                                            -(r.get("tasa_conversion_pct") or 0),
                                            -(r.get("total_leads", 0))))

    # Asignar posicion solo a equipos con actividad en el periodo
    posicion = 0
    for r in rows:
        if (r.get("total_leads") or 0) > 0 or (r.get("total_llamadas") or 0) > 0 or (r.get("total_citas") or 0) > 0:
            posicion += 1
            r["posicion"] = posicion
        else:
            r["posicion"] = None

    return {
        "ranking": rows,
        "metrica": metrica,
        "fuente": fuente or (str(fuente_id) if fuente_id is not None else None),
        "fuente_excluida": fuente_excluida,
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }


# =============================================================================
# SPRINT 2 — Leadtime: tiempo desde asignacion hasta primer contacto
# =============================================================================
@router.get("/leadtime")
def reporte_leadtime(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Velocidad de respuesta — KPI critico patrón estándar Speed-to-Lead."""
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_user_filter(supervisor_id, "u")
    lead_team_clause, lead_team_params = _team_lead_filter(supervisor_id, "l")
    params = [f_desde, f_hasta] + lead_team_params + role_params + team_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH leads_periodo AS (
                    SELECT
                        l.id, l.asesor_id, l.fecha_asignacion, l.created_at
                    FROM crm.leads l
                    WHERE l.activo = TRUE
                      AND l.created_at >= %s::timestamptz
                      AND l.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
                      {lead_team_clause}
                ),
                primer_contacto AS (
                    SELECT lead_id, MIN(ts) AS primer_ts FROM (
                        SELECT c.lead_id, c.created_at AS ts
                        FROM crm.contactos c
                        WHERE c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                          AND c.lead_id IN (SELECT id FROM leads_periodo)
                        UNION ALL
                        SELECT ll.lead_id, ll.fecha_llamada AS ts
                        FROM crm.llamadas ll
                        WHERE ll.lead_id IN (SELECT id FROM leads_periodo)
                    ) all_contacts
                    GROUP BY lead_id
                ),
                leadtime_calc AS (
                    SELECT
                        lp.id AS lead_id, lp.asesor_id,
                        CASE
                            WHEN pc.primer_ts IS NULL THEN NULL
                            WHEN COALESCE(lp.fecha_asignacion, lp.created_at) IS NULL THEN NULL
                            WHEN pc.primer_ts < COALESCE(lp.fecha_asignacion, lp.created_at) THEN NULL
                            ELSE EXTRACT(EPOCH FROM (pc.primer_ts - COALESCE(lp.fecha_asignacion, lp.created_at))) / 60.0
                        END AS leadtime_min_raw
                    FROM leads_periodo lp
                    LEFT JOIN primer_contacto pc ON pc.lead_id = lp.id
                ),
                leadtime_sane AS (
                    SELECT
                        lead_id, asesor_id,
                        CASE
                            WHEN leadtime_min_raw IS NULL THEN NULL
                            WHEN leadtime_min_raw < 0 THEN NULL
                            WHEN leadtime_min_raw > 525600 THEN NULL
                            ELSE leadtime_min_raw
                        END AS leadtime_min
                    FROM leadtime_calc
                )
                SELECT
                    u.id::text          AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                                        AS nombre_completo,
                    u.role              AS rol,
                    COUNT(lp.id)        AS total_leads,
                    COUNT(ls.leadtime_min) AS leads_contactados,
                    ROUND(AVG(ls.leadtime_min)::numeric, 1) AS tiempo_promedio_min,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ls.leadtime_min)::int AS mediana_min,
                    COUNT(ls.leadtime_min) FILTER (WHERE ls.leadtime_min < 5)                                      AS bucket_menos_5min,
                    COUNT(ls.leadtime_min) FILTER (WHERE ls.leadtime_min >= 5    AND ls.leadtime_min < 30)         AS bucket_5_30min,
                    COUNT(ls.leadtime_min) FILTER (WHERE ls.leadtime_min >= 30   AND ls.leadtime_min < 60)         AS bucket_30_60min,
                    COUNT(ls.leadtime_min) FILTER (WHERE ls.leadtime_min >= 60   AND ls.leadtime_min < 1440)       AS bucket_1h_24h,
                    COUNT(ls.leadtime_min) FILTER (WHERE ls.leadtime_min >= 1440)                                  AS bucket_mas_24h
                FROM auth.users u
                LEFT JOIN leads_periodo lp ON lp.asesor_id = u.id
                LEFT JOIN leadtime_sane ls ON ls.lead_id = lp.id
                WHERE u.role IN ('asesor','supervisor') AND u.is_active = TRUE
                  AND (lp.id IS NULL OR ({role_clause.replace('l.', 'lp.')}))
                  {team_clause}
                GROUP BY u.id, u.first_name, u.last_name, u.role
                HAVING COUNT(lp.id) > 0
                ORDER BY total_leads DESC
                """,
                params,
            )
            rows = cur.fetchall()
    return {"asesores": [dict(r) for r in rows], "periodo": {"desde": f_desde, "hasta": f_hasta}}


# =============================================================================
# SPRINT 2 — Heatmap dia / hora de mayor conversion
# =============================================================================
@router.get("/heatmap")
def reporte_heatmap(
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    metrica:     str = Query("contactos", description="contactos | ganados"),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Distribucion de actividad por dia-de-semana y hora-del-dia."""
    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_lead_filter(supervisor_id, "l")
    params = [f_desde, f_hasta] + role_params + team_params

    if metrica == "ganados":
        sql = f"""
            SELECT
                EXTRACT(DOW  FROM (al.created_at AT TIME ZONE 'America/Lima'))::int AS dia,
                EXTRACT(HOUR FROM (al.created_at AT TIME ZONE 'America/Lima'))::int AS hora,
                COUNT(*)::int AS valor
            FROM crm.contactos al
            JOIN crm.leads l ON l.id = al.lead_id
            JOIN crm.estados_lead e ON e.id = l.estado_id
            WHERE (e.nombre ILIKE '%%matr%%'
                   OR e.nombre ILIKE '%%ganad%%'
                   OR e.nombre ILIKE '%%cierr%%')
              AND al.created_at >= %s::timestamptz
              AND al.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
              AND ({role_clause})
              {team_clause}
            GROUP BY dia, hora
            ORDER BY dia, hora
        """
    else:
        sql = f"""
            SELECT
                EXTRACT(DOW  FROM (c.created_at AT TIME ZONE 'America/Lima'))::int AS dia,
                EXTRACT(HOUR FROM (c.created_at AT TIME ZONE 'America/Lima'))::int AS hora,
                COUNT(*)::int AS valor
            FROM crm.contactos c
            JOIN crm.leads l ON l.id = c.lead_id
            WHERE c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
              AND c.created_at >= %s::timestamptz
              AND c.created_at <  (%s::date + INTERVAL '1 day')::timestamptz
              AND ({role_clause})
              {team_clause}
            GROUP BY dia, hora
            ORDER BY dia, hora
        """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    matriz = [[0] * 24 for _ in range(7)]
    for r in rows:
        d, h = r["dia"], r["hora"]
        if 0 <= d < 7 and 0 <= h < 24:
            matriz[d][h] = r["valor"]
    return {
        "matriz":  matriz,
        "metrica": metrica,
        "periodo": {"desde": f_desde, "hasta": f_hasta},
        "max":     max((r["valor"] for r in rows), default=0),
        "total":   sum((r["valor"] or 0) for r in rows),
    }


# =============================================================================
# SPRINT 2 — Tiempo muerto: gaps de actividad por asesor
# =============================================================================
@router.get("/tiempo-muerto")
def reporte_tiempo_muerto(
    dias:   int = Query(7, description="Considerar leads activos sin actividad >= N dias"),
    supervisor_id: Optional[str] = Query(None, description="Filtrar por equipo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Identifica asesores con leads activos abandonados."""
    role_clause, role_params = role_filter(current_user)
    team_clause, team_params = _team_user_filter(supervisor_id, "u")
    params = [dias] + role_params + team_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH ultimo_contacto AS (
                    SELECT lead_id, MAX(created_at) AS last_ts
                    FROM crm.contactos
                    WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                    GROUP BY lead_id
                )
                SELECT
                    u.id::text  AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                                AS nombre_completo,
                    COUNT(l.id) AS leads_estancados,
                    ROUND(AVG(EXTRACT(EPOCH FROM (NOW() - COALESCE(uc.last_ts, l.created_at))) / 86400)::numeric, 1)
                                AS dias_promedio_inactivos,
                    MAX(EXTRACT(EPOCH FROM (NOW() - COALESCE(uc.last_ts, l.created_at))) / 86400)::int
                                AS max_dias_inactivos
                FROM auth.users u
                JOIN crm.leads l        ON l.asesor_id = u.id AND l.activo = TRUE
                JOIN crm.estados_lead e ON e.id = l.estado_id AND e.es_final = FALSE
                LEFT JOIN ultimo_contacto uc ON uc.lead_id = l.id
                WHERE u.role IN ('asesor','supervisor') AND u.is_active = TRUE
                  AND COALESCE(uc.last_ts, l.created_at) < NOW() - (%s || ' days')::interval
                  AND ({role_clause})
                  {team_clause}
                GROUP BY u.id, u.first_name, u.last_name
                HAVING COUNT(l.id) > 0
                ORDER BY leads_estancados DESC
                """,
                params,
            )
            rows = cur.fetchall()
    return {"asesores": [dict(r) for r in rows], "umbral_dias": dias}


# =============================================================================
# EXPORTAR — extendido para los 5 nuevos reportes
# =============================================================================
@router.get("/exportar")
def exportar(
    tipo: str = Query("asesores"),
    fecha_desde: str = Query(None),
    fecha_hasta: str = Query(None),
    dias: int = Query(7),
    asesor_id: str = Query(None, description="Filtrar reporte por asesor específico"),
    supervisor_id: str = Query(None, description="Filtrar reporte por equipo específico"),
    metrica: str = Query("matriculas", description="Métrica para el ranking"),
    role_filter: str = Query("asesor", description="Filtro de rol o agrupación para el ranking"),
    fuente: Optional[str] = Query(None, description="Filtrar por fuente en el ranking"),
    fuente_excluida: Optional[str] = Query(None, description="Regla de excepción para excluir fuentes en el ranking"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Exporta cualquier reporte a Excel (.xlsx)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    s_id = supervisor_id.strip() if isinstance(supervisor_id, str) and supervisor_id.strip() else None
    a_id = asesor_id.strip() if isinstance(asesor_id, str) and asesor_id.strip() else None
    f_val = fuente.strip() if isinstance(fuente, str) and fuente.strip() else None
    f_exc_val = fuente_excluida.strip() if isinstance(fuente_excluida, str) and fuente_excluida.strip() else None
    m_val = metrica.strip() if isinstance(metrica, str) and metrica.strip() else "matriculas"
    rf_val = role_filter.strip() if isinstance(role_filter, str) and role_filter.strip() else "asesor"

    if tipo == "ranking":
        if rf_val == "equipo":
            data    = ranking_equipos(f_desde, f_hasta, metrica=m_val, supervisor_id=s_id, fuente=f_val, fuente_excluida=f_exc_val, current_user=current_user)
            rows    = data.get("ranking", [])
            titulo  = f"Ranking Equipos ({m_val.capitalize()})"
            headers = ["Posición", "Equipo / Supervisor", "Asesores", "Total Leads", "Contactados",
                       "Calificados", "En negociación", "Matrículas", "Conv. %", "Contactabilidad %"]
            keys    = ["posicion", "supervisor_nombre", "num_asesores", "total_leads", "leads_contactados",
                       "leads_calificados", "leads_en_negociacion", "leads_ganados", "tasa_conversion_pct", "tasa_contactabilidad_pct"]
        else:
            data    = ranking_asesores(f_desde, f_hasta, metrica=m_val, supervisor_id=s_id, fuente=f_val, fuente_excluida=f_exc_val, current_user=current_user)
            rows    = data.get("ranking", [])
            if rf_val != "all":
                rows = [r for r in rows if (r.get("rol") or "asesor") == rf_val]
            titulo  = f"Ranking Asesores ({m_val.capitalize()})"
            headers = ["Posición", "Asesor", "Rol", "Total Leads", "Contactados",
                       "Calificados", "En negociación", "Matrículas", "Conv. %", "Contactabilidad %"]
            keys    = ["posicion", "nombre_completo", "rol", "total_leads", "leads_contactados",
                       "leads_calificados", "leads_en_negociacion", "leads_ganados", "tasa_conversion_pct", "tasa_contactabilidad_pct"]
    elif tipo == "asesores":
        data    = por_asesor(f_desde, f_hasta, s_id, current_user)
        rows    = data["rows"]
        titulo  = "Reporte por Asesor"
        headers = ["Asesor", "Total Leads", "Contactados", "Calificados",
                   "En negociación", "Matrículas", "Perdidos", "Sin contactar",
                   "Conv. %", "Contactabilidad %"]
        keys    = ["nombre_completo", "total_leads", "leads_contactados", "leads_calificados",
                   "leads_en_negociacion", "leads_ganados", "leads_perdidos", "leads_sin_contactar",
                   "tasa_conversion_pct", "tasa_contactabilidad_pct"]
    elif tipo == "tiempo_respuesta":
        data    = tiempo_respuesta(f_desde, f_hasta, supervisor_id, current_user)
        rows    = data["rows"]
        titulo  = "Tiempo de Respuesta por Asesor"
        headers = ["Asesor", "Leads con Contacto", "Promedio (h)", "Mediana (h)",
                   "P90 (h)", "Dentro 1h", "Dentro 24h", "% < 1h", "% < 24h"]
        keys    = ["nombre_completo", "leads_con_contacto", "promedio_horas", "mediana_horas",
                   "p90_horas", "dentro_1h", "dentro_24h", "pct_dentro_1h", "pct_dentro_24h"]
    elif tipo == "funnel":
        data    = funnel(f_desde, f_hasta, supervisor_id, current_user)
        rows    = data["etapas"]
        titulo  = "Embudo de Conversión"
        headers = ["Estado", "Total Leads", "% del Total", "Conversión desde anterior"]
        keys    = ["estado", "total", "pct_total", "conversion_desde_anterior"]
    elif tipo == "estancados":
        data    = estancados(dias, supervisor_id, current_user)
        rows    = data["rows"]
        titulo  = f"Leads Estancados (+{dias} días)"
        headers = ["Lead", "Teléfono", "Estado", "Fuente", "Fecha Ingreso",
                   "Último Contacto", "Días Inactivo", "Asesor"]
        keys    = ["nombre_lead", "telefono", "estado", "fuente", "fecha_ingreso",
                   "fecha_ultimo_contacto", "dias_inactivo", "asesor_nombre"]
    elif tipo == "campanas":
        data    = campanas(f_desde, f_hasta, asesor_id, supervisor_id, current_user)
        rows    = data["rows"]
        titulo  = "Rendimiento de Campañas"
        headers = ["Campaña", "Fuente", "Total Leads", "Contactados", "Calificados",
                   "Matrículas", "Perdidos", "% Contactados", "% Calificados", "% Matrículas",
                   "Horas 1er Contacto"]
        keys    = ["campana", "fuente", "total_leads", "leads_contactados", "leads_calificados",
                   "leads_ganados", "leads_perdidos", "pct_contactados", "pct_calificados",
                   "pct_ganados", "horas_primer_contacto"]
    else:
        data    = por_fuente(f_desde, f_hasta, asesor_id, supervisor_id, current_user)
        rows    = data["rows"]
        titulo  = "Reporte por Plataforma"
        headers = ["Plataforma", "Total Leads", "Contactados", "Calificados",
                   "En negociación", "Matrículas", "Perdidos", "Conv. %", "Contactabilidad %"]
        keys    = ["fuente", "total_leads", "leads_contactados", "leads_calificados",
                   "leads_en_negociacion", "leads_ganados", "leads_perdidos",
                   "tasa_conversion_pct", "tasa_contactabilidad_pct"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = titulo[:31]

    indigo = "4F46E5"
    light  = "F3F4F6"
    thin   = Border(
        left=Side(style="thin", color="E5E7EB"),
        right=Side(style="thin", color="E5E7EB"),
        bottom=Side(style="thin", color="E5E7EB"),
    )

    # V070.68 (Bundle B): nombre comercial dinamico desde brand_service.
    from app.services.brand_service import get_company_name
    company_label = get_company_name()

    n_cols = len(headers)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    t = ws.cell(row=1, column=1,
                value=f"{company_label} — {titulo} | {f_desde} al {f_hasta}")
    t.font      = Font(bold=True, size=12, color="FFFFFF")
    t.fill      = PatternFill("solid", fgColor=indigo)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n_cols)
    resumen = data.get("resumen", {})
    sub = (f"Total leads: {resumen.get('total_leads', resumen.get('total_estancados', len(rows)))}  |  "
           f"Período: {f_desde} al {f_hasta}")
    s = ws.cell(row=2, column=1, value=sub)
    s.font      = Font(size=9, color="6B7280")
    s.fill      = PatternFill("solid", fgColor="EEF2FF")
    s.alignment = Alignment(horizontal="center")

    for col, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=col, value=h)
        c.font      = Font(bold=True, size=10, color="374151")
        c.fill      = PatternFill("solid", fgColor=light)
        c.alignment = Alignment(horizontal="center" if col > 1 else "left")
        c.border    = thin

    for r_idx, row in enumerate(rows, 4):
        for col, key in enumerate(keys, 1):
            val = row.get(key)
            c = ws.cell(
                row=r_idx, column=col,
                value=float(val) if isinstance(val, (int, float)) and col > 1 else (str(val) if val is not None else ""),
            )
            c.alignment = Alignment(horizontal="right" if col > 1 else "left")
            c.border = thin
            if r_idx % 2 == 0:
                c.fill = PatternFill("solid", fgColor="F9FAFB")

    for col_cells in ws.iter_cols(min_row=3, max_row=3):
        col_letter = col_cells[0].column_letter
        max_len = max(
            (len(str(ws.cell(row=r, column=col_cells[0].column).value or ""))
             for r in range(3, len(rows) + 5)),
            default=8,
        )
        ws.column_dimensions[col_letter].width = min(max_len + 4, 32)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"reporte_{tipo}_{f_desde}_{f_hasta}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =============================================================================
# Modal de Detalle de Leads para Reportería
# Permite hacer clic en cualquier número de métrica y ver la lista completa
# =============================================================================

@router.get("/leads-detalle")
def leads_detalle(
    tipo_metrica: str = Query("total", description="Métrica: total, contactados, calificados, negociacion, matriculas, perdidos, sin_contactar"),
    asesor_id: Optional[str] = Query(None),
    supervisor_id: Optional[str] = Query(None),
    fuente: Optional[str] = Query(None),
    fuente_excluida: Optional[str] = Query(None, description="Excluir fuente(s)"),
    campana: Optional[str] = Query(None),
    estado_id: Optional[int] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(500, le=1000),
    offset: int = Query(0, ge=0),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    tipo_metrica = tipo_metrica if isinstance(tipo_metrica, str) else "total"
    asesor_id = asesor_id if isinstance(asesor_id, str) else None
    supervisor_id = supervisor_id if isinstance(supervisor_id, str) else None
    fuente = fuente if isinstance(fuente, str) else None
    fuente_excluida = fuente_excluida if isinstance(fuente_excluida, str) else None
    campana = campana if isinstance(campana, str) else None
    estado_id = estado_id if isinstance(estado_id, int) else None
    search = search if isinstance(search, str) else None
    limit = limit if isinstance(limit, int) else 500
    offset = offset if isinstance(offset, int) else 0

    f_desde, f_hasta = _defaults(fecha_desde, fecha_hasta)
    role_clause, role_params = role_filter(current_user)

    where_clauses = ["l.activo = TRUE", f"({role_clause})"]
    params = list(role_params)

    # Filtro fecha creación del lead (consistente con los reportes)
    where_clauses.append("l.created_at >= %s::timestamptz")
    where_clauses.append("l.created_at < (%s::date + INTERVAL '1 day')::timestamptz")
    params.extend([f_desde, f_hasta])

    if asesor_id and asesor_id.strip() and asesor_id.strip().lower() != "all":
        where_clauses.append("l.asesor_id = %s::uuid")
        params.append(asesor_id.strip())

    if supervisor_id and supervisor_id.strip() and supervisor_id.strip().lower() != "all":
        where_clauses.append(
            "(l.asesor_id IN (SELECT eq.asesor_id FROM crm.equipos eq WHERE eq.supervisor_id = %s::uuid AND eq.activo = TRUE) OR l.supervisor_id = %s::uuid)"
        )
        params.append(supervisor_id.strip())
        params.append(supervisor_id.strip())

    if fuente and fuente.strip() and fuente.strip().lower() != "all":
        f_norm = fuente.strip().lower()
        if f_norm == "sin fuente":
            where_clauses.append("(f.nombre IS NULL OR TRIM(f.nombre) = '')")
        else:
            where_clauses.append("LOWER(COALESCE(f.nombre, '')) = %s")
            params.append(f_norm)

    if fuente_excluida and isinstance(fuente_excluida, str) and fuente_excluida.strip() and fuente_excluida.strip().lower() not in ("none", "all"):
        for exc in [x.strip() for x in fuente_excluida.split(",") if x.strip()]:
            exc_norm = exc.lower()
            if exc_norm in ("sin fuente", "null", "none"):
                where_clauses.append("(f.nombre IS NOT NULL AND TRIM(f.nombre) != '')")
            elif exc_norm.isdigit():
                where_clauses.append("(l.fuente_id IS NULL OR l.fuente_id != %s)")
                params.append(int(exc_norm))
            else:
                where_clauses.append("(f.nombre IS NULL OR LOWER(COALESCE(f.nombre, '')) != %s)")
                params.append(exc_norm)

    if campana and campana.strip() and campana.strip().lower() != "all":
        c_norm = campana.strip().lower()
        if c_norm == "sin campaña":
            where_clauses.append("(l.campana IS NULL OR TRIM(l.campana) = '')")
        else:
            where_clauses.append("LOWER(COALESCE(l.campana, '')) = %s")
            params.append(c_norm)

    if estado_id is not None:
        where_clauses.append("l.estado_id = %s")
        params.append(estado_id)

    # Filtrar según tipo de métrica
    t_metrica = (tipo_metrica or "total").strip().lower()
    if t_metrica in ("matriculas", "matricula", "ganados", "ganado"):
        where_clauses.append("(e.nombre ILIKE '%%matr%%' OR e.nombre ILIKE '%%ganad%%' OR e.nombre ILIKE '%%cierr%%')")
    elif t_metrica in ("contactados", "contactado"):
        where_clauses.append(
            "(EXISTS (SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')) "
            "OR EXISTS (SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id))"
        )
    elif t_metrica in ("calificados", "calificado"):
        where_clauses.append("e.nombre = 'Calificado'")
    elif t_metrica in ("negociacion", "en_negociacion", "en negociacion"):
        where_clauses.append("e.nombre = 'En negociación'")
    elif t_metrica in ("perdidos", "perdido"):
        where_clauses.append("(e.nombre IN ('No interesado','Perdido') OR e.nombre ILIKE '%%perdid%%' OR e.nombre ILIKE '%%no interesado%%')")
    elif t_metrica in ("sin_contactar", "sin contactar", "nuevos", "nuevo"):
        where_clauses.append(
            "(NOT EXISTS (SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')) "
            "AND NOT EXISTS (SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id))"
        )

    # Filtro search interno en modal
    if search and search.strip():
        s_term = f"%{search.strip()}%"
        where_clauses.append(
            "(l.nombres ILIKE %s OR l.apellidos ILIKE %s OR l.telefono ILIKE %s OR l.email ILIKE %s OR l.dni ILIKE %s)"
        )
        params.extend([s_term, s_term, s_term, s_term, s_term])

    where_sql = " AND ".join(where_clauses)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            count_sql = f"""
                SELECT COUNT(l.id) AS total
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                WHERE {where_sql}
            """
            cur.execute(count_sql, params)
            total_count = cur.fetchone()["total"]

            items_sql = f"""
                SELECT
                    l.id,
                    l.nombres,
                    l.apellidos,
                    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
                    l.telefono,
                    l.email,
                    l.dni,
                    COALESCE(f.nombre, 'Sin fuente') AS origen,
                    l.campana,
                    l.calidad,
                    (
                        (SELECT COUNT(*) FROM crm.contactos c2 WHERE c2.lead_id = l.id AND c2.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion'))
                      + (SELECT COUNT(*) FROM crm.llamadas ll WHERE ll.lead_id = l.id)
                    )::int AS intentos_contacto,
                    l.tipo_cierre,
                    l.segunda_voz,
                    l.motivo_perdida,
                    l.motivo_perdida_otro,
                    l.created_at::text AS fecha_ingreso,
                    (
                        SELECT MAX(ts)::text FROM (
                            SELECT created_at AS ts FROM crm.contactos WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            UNION ALL
                            SELECT fecha_llamada AS ts FROM crm.llamadas WHERE lead_id = l.id
                        ) _last_c
                    ) AS fecha_ultimo_contacto,
                    l.estado_id,
                    e.nombre AS estado_nombre,
                    e.color_hex AS estado_color,
                    l.fuente_id,
                    COALESCE(f.nombre, 'Sin fuente') AS fuente_nombre,
                    l.asesor_id::text AS asesor_id,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                LEFT JOIN auth.users u ON u.id = l.asesor_id
                WHERE {where_sql}
                ORDER BY l.created_at DESC
                LIMIT %s OFFSET %s
            """
            cur.execute(items_sql, params + [limit, offset])
            items = cur.fetchall()

    return {
        "total": total_count,
        "items": items,
        "tipo_metrica": t_metrica,
        "periodo": {"desde": f_desde, "hasta": f_hasta},
    }

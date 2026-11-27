"""
estrategias_externas.py — Medición de efectividad de Estrategias / Fuentes Externas
(campañas cuyo origen NO proviene de redes sociales como TikTok, Meta/Facebook/Instagram, etc.):
- Resumen por fuente externa: total de leads, leads considerados, leads con cita y ventas concretadas.
- Desglose completo de leads por fuente con: estado, asesor, supervisor, fecha de creación,
  último contacto, última actividad, próxima acción y columna especial de consideración.
- Exportación a Excel (.xlsx).
"""
from __future__ import annotations

import io
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from app.auth.jwt import require_supervisor_or_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.filters.lead_filters import role_filter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/estrategias-externas", tags=["Estrategias Externas"])

# Fuentes consideradas de Redes Sociales / Mensajería Social (se excluyen de Estrategias Externas)
SOCIAL_CORE_NAMES = (
    "fb",
    "fb mensaje",
    "facebook",
    "facebook ads",
    "ig",
    "ig mensaje",
    "instagram",
    "instagram ads",
    "meta",
    "meta ads",
    "tiktok",
    "tt mensaje",
    "tiktok ads",
)

WHATSAPP_SOCIAL_NAMES = (
    "wa mensaje",
    "whatsapp",
    "whatsapp ads",
)

CONSIDERACION_LABELS = {
    "considerado_venta": ("Considerado · Venta concretada", True, "Lead con venta / cierre concretado."),
    "considerado_cita": ("Considerado · Con cita", True, "Lead que obtuvo al menos una cita válida o visita."),
    "considerado_gestion": ("Considerado · En gestión", True, "Lead válido en seguimiento comercial activo."),
    "considerado_nuevo": ("Considerado · Por contactar", True, "Lead nuevo activo pendiente de primer contacto."),
    "excluido_invalido": ("No considerado · Número inválido", False, "Número inexistente, equivocado o erróneo."),
    "excluido_perdido": ("No considerado · Perdido / No interesado", False, "Lead descartado o sin interés."),
    "excluido_bolsa": ("No considerado · Bolsa TMK / Reciclado", False, "Lead enviado a bolsa de reciclaje."),
    "excluido_inactivo": ("No considerado · Inactivo / Duplicado", False, "Lead desactivado o fusionado."),
}


def _norm_fuente_expr(alias_orig: str = "f_orig", alias_curr: str = "f_curr") -> str:
    return f"LOWER(TRIM(COALESCE({alias_orig}.nombre, {alias_curr}.nombre, '')))"


def _build_external_base_filters(
    *,
    current_user: TokenData,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    supervisor_id: Optional[str] = None,
    asesor_id: Optional[str] = None,
    incluir_whatsapp: bool = False,
    incluir_sin_fuente: bool = False,
    incluir_inactivos: bool = False,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if not incluir_inactivos:
        clauses.append("l.activo = TRUE AND l.merged_into IS NULL")

    role_clause, role_params = role_filter(current_user)
    clauses.append(f"({role_clause})")
    params.extend(role_params)

    # Excluir fuentes de redes sociales (Meta/FB/IG, TikTok y opcionalmente WhatsApp)
    excluded = list(SOCIAL_CORE_NAMES)
    if not incluir_whatsapp:
        excluded.extend(WHATSAPP_SOCIAL_NAMES)

    f_norm = _norm_fuente_expr("f_orig", "f_curr")
    if not incluir_sin_fuente:
        clauses.append("COALESCE(l.fuente_pre_reciclaje_id, l.fuente_id) IS NOT NULL")
        clauses.append(f"{f_norm} <> ''")

    clauses.append(f"NOT ({f_norm} = ANY(%s))")
    params.append(excluded)
    clauses.append(
        f"NOT ({f_norm} ~ '(tiktok|facebook|instagram|(^|[^a-z])meta([^a-z]|$))')"
    )
    if not incluir_whatsapp:
        clauses.append(f"NOT ({f_norm} ~ '(whatsapp|wa mensaje)')" )

    if fecha_desde:
        clauses.append("l.created_at >= %s::timestamptz")
        params.append(f"{fecha_desde.strip()} 00:00:00-05")
    if fecha_hasta:
        clauses.append("l.created_at <= %s::timestamptz")
        params.append(f"{fecha_hasta.strip()} 23:59:59.999999-05")
    if supervisor_id:
        clauses.append("(l.supervisor_id = %s::uuid OR eq.supervisor_id = %s::uuid)")
        params.extend([supervisor_id, supervisor_id])
    if asesor_id:
        clauses.append("l.asesor_id = %s::uuid")
        params.append(asesor_id)

    return " AND ".join(clauses), params


def _enriched_cte_sql(where_sql: str) -> str:
    """
    CTE reutilizable para medir citas, ventas, último contacto, última actividad,
    próxima acción y clasificación de qué leads se consideran.
    """
    norm_est = "TRANSLATE(LOWER(TRIM(COALESCE(e.nombre, ''))), 'áéíóúüñ', 'aeiouun')"
    return f"""
    citas_por_lead AS (
        SELECT
            c.lead_id,
            COUNT(*) FILTER (
                WHERE COALESCE(ce.codigo, 'pendiente') <> 'cancelada'
            )::int AS total_citas,
            MAX(COALESCE(c.fecha_cita, c.created_at)) FILTER (
                WHERE COALESCE(ce.codigo, 'pendiente') <> 'cancelada'
            ) AS ultima_cita_fecha,
            (
                ARRAY_AGG(COALESCE(ce.nombre, 'Pendiente') ORDER BY c.created_at DESC, c.id DESC)
                FILTER (WHERE COALESCE(ce.codigo, 'pendiente') <> 'cancelada')
            )[1] AS ultima_cita_estado,
            BOOL_OR(COALESCE(ce.codigo, 'pendiente') <> 'cancelada') AS tiene_registro_cita
        FROM crm.contactos c
        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
        WHERE c.fecha_cita IS NOT NULL
        GROUP BY c.lead_id
    ),
    cita_historial_estado AS (
        SELECT
            c.lead_id,
            TRUE AS tuvo_estado_cita_hist
        FROM crm.contactos c
        WHERE c.tipo_contacto = 'cambio_estado'
          AND TRANSLATE(LOWER(COALESCE(c.notas, '')), 'áéíóúüñ', 'aeiouun') ~ '(cita|visita a proyecto)'
        GROUP BY c.lead_id
    ),
    ultimo_contacto_agg AS (
        SELECT DISTINCT ON (lead_id)
            lead_id,
            ts AS ultimo_contacto_at,
            tipo AS ultimo_contacto_tipo,
            resultado AS ultimo_contacto_resultado
        FROM (
            SELECT
                c.lead_id,
                c.created_at AS ts,
                c.tipo_contacto AS tipo,
                COALESCE(c.resultado, LEFT(c.notas, 90)) AS resultado
            FROM crm.contactos c
            WHERE c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
            UNION ALL
            SELECT
                ll.lead_id,
                ll.fecha_llamada AS ts,
                'llamada'::text AS tipo,
                COALESCE(ll.resultado, 'Llamada') AS resultado
            FROM crm.llamadas ll
            WHERE ll.lead_id IS NOT NULL
        ) _uc
        ORDER BY lead_id, ts DESC
    ),
    ultima_actividad_agg AS (
        SELECT DISTINCT ON (lead_id)
            lead_id,
            ts AS ultima_actividad_at,
            detalle AS ultima_actividad_detalle
        FROM (
            SELECT
                c.lead_id,
                c.created_at AS ts,
                TRIM(CONCAT_WS(' · ', c.tipo_contacto, NULLIF(COALESCE(c.resultado, LEFT(c.notas, 80)), ''))) AS detalle
            FROM crm.contactos c
            UNION ALL
            SELECT
                ll.lead_id,
                ll.fecha_llamada AS ts,
                TRIM(CONCAT_WS(' · ', 'llamada', NULLIF(ll.resultado, ''))) AS detalle
            FROM crm.llamadas ll
            WHERE ll.lead_id IS NOT NULL
            UNION ALL
            SELECT
                al.lead_id,
                al.created_at AS ts,
                'reasignacion'::text AS detalle
            FROM crm.asignaciones_log al
            UNION ALL
            SELECT
                lr.lead_id,
                lr.created_at AS ts,
                'recontacto'::text AS detalle
            FROM crm.lead_recontactos lr
        ) _ua
        ORDER BY lead_id, ts DESC
    ),
    proxima_contacto_agg AS (
        SELECT DISTINCT ON (c.lead_id)
            c.lead_id,
            c.proxima_accion,
            c.fecha_proxima_accion
        FROM crm.contactos c
        WHERE c.proxima_accion IS NOT NULL OR c.fecha_proxima_accion IS NOT NULL
        ORDER BY c.lead_id, c.created_at DESC, c.id DESC
    ),
    cierres_vinculados AS (
        SELECT lead_id, COUNT(*)::int AS cierres_cnt
        FROM crm.cierres_lotes_registros
        WHERE activo = TRUE AND lead_id IS NOT NULL
        GROUP BY lead_id
    ),
    reservas_vinculadas AS (
        SELECT lead_id, COUNT(*)::int AS reservas_cnt
        FROM crm.separaciones_registros
        WHERE activo = TRUE AND lead_id IS NOT NULL
        GROUP BY lead_id
    ),
    base_leads AS (
        SELECT
            l.id,
            TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
            l.telefono,
            l.email,
            l.campana,
            l.proyecto,
            l.activo,
            l.merged_into,
            l.created_at AS fecha_creacion,
            l.updated_at,
            l.valor_venta,
            l.estado_id,
            COALESCE(e.nombre, 'Sin estado') AS estado_nombre,
            COALESCE(e.color_hex, '#64748b') AS estado_color,
            COALESCE(l.fuente_pre_reciclaje_id, l.fuente_id) AS fuente_efectiva_id,
            COALESCE(f_orig.nombre, f_curr.nombre, 'Sin fuente') AS fuente_nombre,
            l.asesor_id::text AS asesor_id,
            NULLIF(TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')), '') AS asesor_nombre,
            COALESCE(l.supervisor_id, eq.supervisor_id)::text AS supervisor_id,
            NULLIF(TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')), '') AS supervisor_nombre,

            -- Último contacto y última actividad
            uc.ultimo_contacto_at,
            uc.ultimo_contacto_tipo,
            uc.ultimo_contacto_resultado,
            COALESCE(GREATEST(ua.ultima_actividad_at, l.updated_at, l.created_at), l.created_at) AS ultima_actividad_at,
            COALESCE(ua.ultima_actividad_detalle, 'Registro de lead') AS ultima_actividad_detalle,

            -- Próxima acción (prioriza campos directos del lead, luego contactos, luego cita pendiente)
            COALESCE(
                NULLIF(TRIM(l.accion_proxima_gestion), ''),
                NULLIF(TRIM(pc.proxima_accion), ''),
                CASE WHEN cp.ultima_cita_fecha IS NOT NULL
                      AND COALESCE(cp.ultima_cita_estado, 'Pendiente') NOT IN ('Completada', 'Cancelada', 'No asistió')
                     THEN 'Cita programada (' || COALESCE(cp.ultima_cita_estado, 'Pendiente') || ')'
                     ELSE NULL END
            ) AS proxima_accion,
            COALESCE(
                l.fecha_proxima_gestion,
                pc.fecha_proxima_accion,
                CASE WHEN cp.ultima_cita_fecha IS NOT NULL
                      AND COALESCE(cp.ultima_cita_estado, 'Pendiente') NOT IN ('Completada', 'Cancelada', 'No asistió')
                     THEN cp.ultima_cita_fecha
                     ELSE NULL END
            ) AS fecha_proxima_accion,

            -- Métricas de efectividad: Cita y Venta concretada
            COALESCE(cp.total_citas, 0) AS total_citas,
            cp.ultima_cita_fecha,
            cp.ultima_cita_estado,
            (
                COALESCE(cp.tiene_registro_cita, FALSE)
                OR COALESCE(che.tuvo_estado_cita_hist, FALSE)
                OR {norm_est} ~ '(cita|agendad|visita a proyecto|reprogram)'
            ) AS tuvo_cita,
            (
                {norm_est} ~ '(ganad|matricul|venta concretad|cierr|inscrit)'
                OR COALESCE(l.valor_venta, 0) > 0
                OR COALESCE(cv.cierres_cnt, 0) > 0
            ) AS concreto_venta,
            (
                {norm_est} ~ '(reserv|separac)'
                OR COALESCE(rv.reservas_cnt, 0) > 0
            ) AS tiene_reserva,

            -- Columna especial: ¿Qué leads se consideran?
            CASE
                WHEN (l.activo = FALSE OR l.merged_into IS NOT NULL) THEN 'excluido_inactivo'
                WHEN {norm_est} ~ '(equivocad|inexistent|errone|no existe|numero invalido|mal numero)' THEN 'excluido_invalido'
                WHEN (
                    {norm_est} ~ '(ganad|matricul|venta concretad|cierr|inscrit)'
                    OR COALESCE(l.valor_venta, 0) > 0
                    OR COALESCE(cv.cierres_cnt, 0) > 0
                ) THEN 'considerado_venta'
                WHEN {norm_est} ~ '(perdid|desist|no interesad|descart)' THEN 'excluido_perdido'
                WHEN (
                    l.es_reciclado = TRUE
                    OR {norm_est} ~ '(bolsa|reciclaje)'
                ) THEN 'excluido_bolsa'
                WHEN (
                    COALESCE(cp.tiene_registro_cita, FALSE)
                    OR COALESCE(che.tuvo_estado_cita_hist, FALSE)
                    OR {norm_est} ~ '(cita|agendad|visita a proyecto|reprogram)'
                ) THEN 'considerado_cita'
                WHEN ({norm_est} = '' OR {norm_est} ~ '^nuevo([[:space:]]|$)' OR {norm_est} ~ '(sin gestionar|por contactar)') THEN 'considerado_nuevo'
                ELSE 'considerado_gestion'
            END AS consideracion_codigo
        FROM crm.leads l
        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
        LEFT JOIN crm.fuentes f_curr ON f_curr.id = l.fuente_id
        LEFT JOIN crm.fuentes f_orig ON f_orig.id = l.fuente_pre_reciclaje_id
        LEFT JOIN auth.users a ON a.id = l.asesor_id
        LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
        LEFT JOIN auth.users s ON s.id = COALESCE(l.supervisor_id, eq.supervisor_id)
        LEFT JOIN citas_por_lead cp ON cp.lead_id = l.id
        LEFT JOIN cita_historial_estado che ON che.lead_id = l.id
        LEFT JOIN ultimo_contacto_agg uc ON uc.lead_id = l.id
        LEFT JOIN ultima_actividad_agg ua ON ua.lead_id = l.id
        LEFT JOIN proxima_contacto_agg pc ON pc.lead_id = l.id
        LEFT JOIN cierres_vinculados cv ON cv.lead_id = l.id
        LEFT JOIN reservas_vinculadas rv ON rv.lead_id = l.id
        WHERE {where_sql}
    )
    """


def _annotate_lead_consideracion(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    cod = out.get("consideracion_codigo") or "considerado_gestion"
    label, es_cons, motivo = CONSIDERACION_LABELS.get(
        cod, ("Considerado · En gestión", True, "Lead válido considerado.")
    )
    out["consideracion_label"] = label
    out["es_considerado"] = es_cons
    out["consideracion_motivo"] = motivo
    if out.get("valor_venta") is not None:
        out["valor_venta"] = float(out["valor_venta"])
    for dt_k in ("fecha_creacion", "ultimo_contacto_at", "ultima_actividad_at", "fecha_proxima_accion", "ultima_cita_fecha"):
        if hasattr(out.get(dt_k), "isoformat"):
            out[dt_k] = out[dt_k].isoformat()
    return out


@router.get("/resumen")
def get_estrategias_externas_resumen(
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor_id: Optional[str] = Query(None),
    asesor_id: Optional[str] = Query(None),
    incluir_whatsapp: bool = Query(False),
    incluir_sin_fuente: bool = Query(False),
    incluir_inactivos: bool = Query(False),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """
    Resumen de efectividad por fuente externa (excluyendo redes sociales):
    leads totales, considerados, leads con cita, ventas concretadas y tasas de conversión.
    """
    where_sql, params = _build_external_base_filters(
        current_user=current_user,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        supervisor_id=supervisor_id,
        asesor_id=asesor_id,
        incluir_whatsapp=incluir_whatsapp,
        incluir_sin_fuente=incluir_sin_fuente,
        incluir_inactivos=incluir_inactivos,
    )
    cte_sql = _enriched_cte_sql(where_sql)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH {cte_sql}
                SELECT
                    COALESCE(fuente_efectiva_id, 0) AS fuente_id,
                    fuente_nombre,
                    COUNT(*)::int AS total_leads,
                    COUNT(*) FILTER (
                        WHERE consideracion_codigo LIKE 'considerado_%%'
                    )::int AS leads_considerados,
                    COUNT(*) FILTER (
                        WHERE consideracion_codigo NOT LIKE 'considerado_%%'
                    )::int AS leads_no_considerados,
                    COUNT(*) FILTER (WHERE tuvo_cita)::int AS con_cita,
                    COUNT(*) FILTER (WHERE concreto_venta)::int AS con_venta,
                    COUNT(*) FILTER (WHERE tiene_reserva)::int AS con_reserva,
                    COUNT(*) FILTER (WHERE ultimo_contacto_at IS NOT NULL)::int AS contactados,
                    COUNT(*) FILTER (WHERE consideracion_codigo = 'excluido_invalido')::int AS invalidos,
                    COUNT(*) FILTER (WHERE consideracion_codigo = 'excluido_perdido')::int AS perdidos,
                    COUNT(*) FILTER (WHERE consideracion_codigo = 'excluido_bolsa')::int AS en_bolsa,
                    MIN(fecha_creacion) AS primer_lead_at,
                    MAX(fecha_creacion) AS ultimo_lead_at
                FROM base_leads
                GROUP BY COALESCE(fuente_efectiva_id, 0), fuente_nombre
                ORDER BY COUNT(*) FILTER (WHERE concreto_venta) DESC,
                         COUNT(*) FILTER (WHERE tuvo_cita) DESC,
                         COUNT(*) DESC,
                         fuente_nombre ASC
                """,
                params,
            )
            fuentes_raw = [dict(r) for r in cur.fetchall()]

            # Catálogos auxiliares para filtros del frontend
            cur.execute(
                """
                SELECT id::text AS id, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre
                FROM auth.users WHERE role = 'supervisor' AND is_active = TRUE
                ORDER BY first_name, last_name
                """
            )
            supervisores = cur.fetchall()

            cur.execute(
                """
                SELECT id::text AS id, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre
                FROM auth.users WHERE role IN ('asesor', 'supervisor') AND is_active = TRUE
                ORDER BY first_name, last_name
                """
            )
            asesores = cur.fetchall()

            cur.execute("SELECT id, nombre, color_hex FROM crm.estados_lead ORDER BY orden")
            estados = cur.fetchall()

    fuentes_out: list[dict[str, Any]] = []
    tot_leads = 0
    tot_considerados = 0
    tot_no_considerados = 0
    tot_citas = 0
    tot_ventas = 0
    tot_reservas = 0

    for f in fuentes_raw:
        tl = f["total_leads"]
        lc = f["leads_considerados"]
        cc = f["con_cita"]
        cv = f["con_venta"]
        cr = f["con_reserva"]

        tot_leads += tl
        tot_considerados += lc
        tot_no_considerados += f["leads_no_considerados"]
        tot_citas += cc
        tot_ventas += cv
        tot_reservas += cr

        f["tasa_cita_pct"] = round((cc / tl) * 100, 1) if tl else 0.0
        f["tasa_cita_considerados_pct"] = round((cc / lc) * 100, 1) if lc else 0.0
        f["tasa_venta_pct"] = round((cv / tl) * 100, 1) if tl else 0.0
        f["tasa_venta_considerados_pct"] = round((cv / lc) * 100, 1) if lc else 0.0
        f["conversion_cita_venta_pct"] = round((cv / cc) * 100, 1) if cc else 0.0
        for dt_k in ("primer_lead_at", "ultimo_lead_at"):
            if hasattr(f.get(dt_k), "isoformat"):
                f[dt_k] = f[dt_k].isoformat()
        fuentes_out.append(f)

    return {
        "kpis": {
            "total_fuentes": len(fuentes_out),
            "total_leads": tot_leads,
            "leads_considerados": tot_considerados,
            "leads_no_considerados": tot_no_considerados,
            "con_cita": tot_citas,
            "con_venta": tot_ventas,
            "con_reserva": tot_reservas,
            "tasa_cita_pct": round((tot_citas / tot_leads) * 100, 1) if tot_leads else 0.0,
            "tasa_venta_pct": round((tot_ventas / tot_leads) * 100, 1) if tot_leads else 0.0,
            "tasa_venta_considerados_pct": round((tot_ventas / tot_considerados) * 100, 1) if tot_considerados else 0.0,
            "conversion_cita_venta_pct": round((tot_ventas / tot_citas) * 100, 1) if tot_citas else 0.0,
        },
        "fuentes": fuentes_out,
        "redes_excluidas": ["TikTok / tt mensaje", "Meta / Facebook / fb", "Instagram / ig"]
        + ([] if incluir_whatsapp else ["WhatsApp / wa mensaje"]),
        "criterios_consideracion": [
            {"codigo": k, "label": v[0], "es_considerado": v[1], "descripcion": v[2]}
            for k, v in CONSIDERACION_LABELS.items()
        ],
        "catalogos": {
            "supervisores": supervisores,
            "asesores": asesores,
            "estados": estados,
        },
    }


def _build_leads_post_filters(
    *,
    fuente_nombre: Optional[str] = None,
    estado_id: Optional[int] = None,
    consideracion: Optional[str] = None,
    solo_con_cita: bool = False,
    solo_con_venta: bool = False,
    search: Optional[str] = None,
) -> tuple[str, list[Any]]:
    post: list[str] = ["1=1"]
    post_params: list[Any] = []

    if fuente_nombre:
        post.append("LOWER(TRIM(fuente_nombre)) = LOWER(TRIM(%s))")
        post_params.append(fuente_nombre)
    if estado_id is not None:
        post.append("estado_id = %s")
        post_params.append(estado_id)
    if consideracion:
        c_norm = consideracion.strip().lower()
        if c_norm == "considerados":
            post.append("consideracion_codigo LIKE 'considerado_%%'")
        elif c_norm == "no_considerados":
            post.append("consideracion_codigo NOT LIKE 'considerado_%%'")
        else:
            post.append("consideracion_codigo = %s")
            post_params.append(c_norm)
    if solo_con_cita:
        post.append("tuvo_cita = TRUE")
    if solo_con_venta:
        post.append("concreto_venta = TRUE")
    if search and search.strip():
        q = f"%{search.strip()}%"
        post.append(
            "(nombre_completo ILIKE %s OR COALESCE(telefono, '') ILIKE %s OR "
            "COALESCE(campana, '') ILIKE %s OR COALESCE(fuente_nombre, '') ILIKE %s OR "
            "COALESCE(asesor_nombre, '') ILIKE %s OR COALESCE(supervisor_nombre, '') ILIKE %s)"
        )
        post_params.extend([q, q, q, q, q, q])

    return " AND ".join(post), post_params


@router.get("/leads")
def list_estrategias_externas_leads(
    fuente_nombre: Optional[str] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor_id: Optional[str] = Query(None),
    asesor_id: Optional[str] = Query(None),
    estado_id: Optional[int] = Query(None),
    consideracion: Optional[str] = Query(None, description="considerados | no_considerados | codigo"),
    solo_con_cita: bool = Query(False),
    solo_con_venta: bool = Query(False),
    incluir_whatsapp: bool = Query(False),
    incluir_sin_fuente: bool = Query(False),
    incluir_inactivos: bool = Query(False),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Desglose completo de leads de fuentes externas con todas sus métricas de gestión."""
    where_sql, base_params = _build_external_base_filters(
        current_user=current_user,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        supervisor_id=supervisor_id,
        asesor_id=asesor_id,
        incluir_whatsapp=incluir_whatsapp,
        incluir_sin_fuente=incluir_sin_fuente,
        incluir_inactivos=incluir_inactivos,
    )
    cte_sql = _enriched_cte_sql(where_sql)
    post_sql, post_params = _build_leads_post_filters(
        fuente_nombre=fuente_nombre,
        estado_id=estado_id,
        consideracion=consideracion,
        solo_con_cita=solo_con_cita,
        solo_con_venta=solo_con_venta,
        search=search,
    )

    offset = (page - 1) * limit
    all_params = base_params + post_params

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH {cte_sql}
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE consideracion_codigo LIKE 'considerado_%%')::int AS total_considerados,
                    COUNT(*) FILTER (WHERE tuvo_cita)::int AS total_con_cita,
                    COUNT(*) FILTER (WHERE concreto_venta)::int AS total_con_venta
                FROM base_leads
                WHERE {post_sql}
                """,
                all_params,
            )
            counts = cur.fetchone() or {}

            cur.execute(
                f"""
                WITH {cte_sql}
                SELECT *
                FROM base_leads
                WHERE {post_sql}
                ORDER BY fecha_creacion DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                all_params + [limit, offset],
            )
            items = [_annotate_lead_consideracion(r) for r in cur.fetchall()]

    total = counts.get("total", 0)
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, (total + limit - 1) // limit),
        "resumen_filtrado": {
            "total": total,
            "considerados": counts.get("total_considerados", 0),
            "con_cita": counts.get("total_con_cita", 0),
            "con_venta": counts.get("total_con_venta", 0),
        },
        "items": items,
    }


@router.get("/export")
def export_estrategias_externas_excel(
    fuente_nombre: Optional[str] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    supervisor_id: Optional[str] = Query(None),
    asesor_id: Optional[str] = Query(None),
    estado_id: Optional[int] = Query(None),
    consideracion: Optional[str] = Query(None),
    solo_con_cita: bool = Query(False),
    solo_con_venta: bool = Query(False),
    incluir_whatsapp: bool = Query(False),
    incluir_sin_fuente: bool = Query(False),
    incluir_inactivos: bool = Query(False),
    search: Optional[str] = Query(None),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Exporta a Excel (.xlsx) el resumen por fuente externa y el desglose completo de leads."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    res_data = get_estrategias_externas_resumen(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        supervisor_id=supervisor_id,
        asesor_id=asesor_id,
        incluir_whatsapp=incluir_whatsapp,
        incluir_sin_fuente=incluir_sin_fuente,
        incluir_inactivos=incluir_inactivos,
        current_user=current_user,
    )

    where_sql, base_params = _build_external_base_filters(
        current_user=current_user,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        supervisor_id=supervisor_id,
        asesor_id=asesor_id,
        incluir_whatsapp=incluir_whatsapp,
        incluir_sin_fuente=incluir_sin_fuente,
        incluir_inactivos=incluir_inactivos,
    )
    cte_sql = _enriched_cte_sql(where_sql)
    post_sql, post_params = _build_leads_post_filters(
        fuente_nombre=fuente_nombre,
        estado_id=estado_id,
        consideracion=consideracion,
        solo_con_cita=solo_con_cita,
        solo_con_venta=solo_con_venta,
        search=search,
    )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                WITH {cte_sql}
                SELECT *
                FROM base_leads
                WHERE {post_sql}
                ORDER BY fecha_creacion DESC, id DESC
                LIMIT 10000
                """,
                base_params + post_params,
            )
            leads_rows = [_annotate_lead_consideracion(r) for r in cur.fetchall()]

    wb = openpyxl.Workbook()
    hdr_fill = PatternFill(start_color="1F1D5C", end_color="1F1D5C", fill_type="solid")
    hdr_font = Font(color="FFFFFF", bold=True)

    ws1 = wb.active
    ws1.title = "Efectividad por Fuente"
    ws1.append([
        "Fuente Externa", "Total Leads", "Leads Considerados", "No Considerados",
        "Con Cita", "% Efect. Cita", "Ventas Concretadas", "% Efect. Venta",
        "% Cierre (Cita->Venta)", "Reservas",
    ])
    for c in ws1[1]:
        c.fill = hdr_fill
        c.font = hdr_font
    for f in res_data["fuentes"]:
        ws1.append([
            f["fuente_nombre"], f["total_leads"], f["leads_considerados"], f["leads_no_considerados"],
            f["con_cita"], f"{f['tasa_cita_pct']}%", f["con_venta"], f"{f['tasa_venta_pct']}%",
            f"{f['conversion_cita_venta_pct']}%", f["con_reserva"],
        ])

    ws2 = wb.create_sheet("Desglose de Leads")
    ws2.append([
        "ID", "Lead", "Teléfono", "Fuente Externa", "Campaña", "Estado",
        "Asesor", "Supervisor", "Fecha Creación", "Último Contacto",
        "Última Actividad", "Próxima Acción", "Fecha Próxima Acción",
        "Tuvo Cita", "Concretó Venta", "Qué Leads se Consideran", "Motivo Consideración",
    ])
    for c in ws2[1]:
        c.fill = hdr_fill
        c.font = hdr_font
    for r in leads_rows:
        ws2.append([
            r["id"], r["nombre_completo"], r.get("telefono") or "",
            r["fuente_nombre"], r.get("campana") or "", r["estado_nombre"],
            r.get("asesor_nombre") or "Sin asignar", r.get("supervisor_nombre") or "Sin supervisor",
            (r.get("fecha_creacion") or "")[:19].replace("T", " "),
            (r.get("ultimo_contacto_at") or "")[:19].replace("T", " "),
            f"{(r.get('ultima_actividad_at') or '')[:19].replace('T', ' ')} ({r.get('ultima_actividad_detalle') or ''})",
            r.get("proxima_accion") or "",
            (r.get("fecha_proxima_accion") or "")[:19].replace("T", " "),
            "Sí" if r["tuvo_cita"] else "No",
            "Sí" if r["concreto_venta"] else "No",
            r["consideracion_label"],
            r["consideracion_motivo"],
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="estrategias_externas.xlsx"'},
    )

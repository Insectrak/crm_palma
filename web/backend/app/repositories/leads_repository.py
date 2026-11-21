"""
Repositorio de leads — encapsula el acceso SQL a `crm.leads` y sus vistas.

Los routers solo orquestan: validan permisos, llaman al repo y devuelven
el JSON. Cualquier cambio de schema se hace en un único lugar.
"""
from typing import Optional
from psycopg2.extras import RealDictCursor
from app.auth.schemas import TokenData
from app.constants import KEEP_SUPERVISOR, MAX_BULK_REASSIGN
from app.database import get_db
from app.filters.lead_filters import LeadFilters, apply_lead_filters

# Tope defensivo: ninguna operación bulk debería tocar más leads que esto
# en una sola request. Evita locks largos y abuso desde el cliente.
# (Centralizado en app.constants y re-exportado aquí)


# Columnas que el listado del dashboard necesita. Centralizadas aquí para
# que el SELECT no se duplique entre endpoints.
_LIST_COLUMNS = """
    v.id, v.nombres, v.apellidos, v.nombre_completo,
    v.telefono, v.email, v.ciudad, v.trabajo,
    v.es_recontacto,
    (
        (SELECT COUNT(*) FROM crm.contactos c2 WHERE c2.lead_id = v.id AND c2.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion'))
      + (SELECT COUNT(*) FROM crm.llamadas  ll WHERE ll.lead_id = v.id)
    ) AS intentos_contacto,
    v.estado_id, v.estado_nombre, v.estado_color,
    v.fuente_id, v.fuente_nombre, v.fuente_externa_id, v.campana,
    -- Nombres legibles resueltos via cache de Graph API. Si no hay cache,
    -- se devuelve NULL y la UI cae al ID crudo (v.campana).
    mc_c.name AS campana_nombre,
    COALESCE(mc_f.name, l.anuncio) AS form_nombre,
    COALESCE(l.fuente_form_id, l.anuncio) AS form_id,
    l.anuncio, l.conjunto, l.observaciones,
    v.asesor_id::text, v.asesor_nombre,
    -- V041.2: rol del asesor para que el frontend distinga "supervisor que
    -- aun no delega" (renderiza como En cola · X) de "asesor real operando
    -- el lead" (renderiza como X). La view no expone el rol, asi que lo
    -- traemos con un subquery — barato porque auth.users es chica.
    (
        SELECT target.sup_id::text
        FROM (
            SELECT COALESCE(
                (SELECT eq.supervisor_id FROM crm.equipos eq WHERE eq.asesor_id = v.asesor_id AND eq.activo = TRUE LIMIT 1),
                v.supervisor_id,
                v.asesor_id
            ) AS sup_id
        ) target
        JOIN auth.users sup ON sup.id = target.sup_id
    ) AS supervisor_id,
    (
        SELECT TRIM(COALESCE(sup.first_name,'') || ' ' || COALESCE(sup.last_name,''))
        FROM (
            SELECT COALESCE(
                (SELECT eq.supervisor_id FROM crm.equipos eq WHERE eq.asesor_id = v.asesor_id AND eq.activo = TRUE LIMIT 1),
                v.supervisor_id,
                v.asesor_id
            ) AS sup_id
        ) target
        JOIN auth.users sup ON sup.id = target.sup_id
    ) AS supervisor_nombre,
    (
        SELECT TRIM(COALESCE(sup.first_name,'') || ' ' || COALESCE(sup.last_name,''))
        FROM (
            SELECT COALESCE(
                (SELECT eq.supervisor_id FROM crm.equipos eq WHERE eq.asesor_id = v.asesor_id AND eq.activo = TRUE LIMIT 1),
                v.supervisor_id,
                v.asesor_id
            ) AS sup_id
        ) target
        JOIN auth.users sup ON sup.id = target.sup_id
    ) AS supervisor_jefe_nombre,
    v.fecha_ingreso::text, v.updated_at::text,
    v.fecha_asignacion::text,
    -- V093: ultimo recontacto. La columna se llena cada vez que un lead
    -- duplicado vuelve a entrar (handle_recontacto). Frontend lo usa para
    -- mostrar "Recontactado hace X dias" + tint amarillo en la fila.
    v.fecha_ultimo_recontacto::text,
    v.fecha_entrada_cola::text, v.cola_estancada,
    (SELECT MIN(ts) FROM (
        SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
        UNION ALL SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = v.id
    ) _fp)::text AS fecha_primer_contacto,
    v.ultimo_tipo_contacto, v.ultimo_resultado,
    (SELECT MAX(ts) FROM (
        SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
        UNION ALL SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = v.id
    ) _uc)::text AS fecha_ultimo_contacto,
    (SELECT MAX(ts) FROM (
        SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id
        UNION ALL SELECT fecha_llamada AS ts FROM crm.llamadas WHERE lead_id = v.id
        UNION ALL SELECT created_at AS ts FROM crm.asignaciones_log WHERE lead_id = v.id
        UNION ALL SELECT created_at AS ts FROM crm.lead_recontactos WHERE lead_id = v.id
        UNION ALL SELECT COALESCE(l.updated_at, l.created_at) AS ts
    ) _all_act)::text AS ultima_actividad,
    v.fecha_proxima_accion::text,
    v.sin_contacto_reciente,
    ROUND(v.horas_desde_ingreso::numeric, 1) AS horas_desde_ingreso,
    EXISTS (
        SELECT 1 FROM crm.asignaciones_log al
        WHERE al.lead_id = l.id AND al.asesor_anterior IS NOT NULL
    ) AS is_reasignado,
    (
        CASE
            WHEN l.supervisor_id IS NOT NULL
                 AND (
                     l.estado_id IN (SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%matr%%' OR nombre ILIKE '%%ganad%%' OR nombre ILIKE '%%cierr%%')
                     OR l.tipo_cierre IS NOT NULL
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM crm.equipos eq
                     WHERE eq.asesor_id = v.asesor_id
                       AND eq.supervisor_id = l.supervisor_id
                       AND eq.activo = TRUE
                 )
            THEN TRUE
            ELSE FALSE
        END
    ) AS is_respaldo_supervision,
    -- V091 — Tracking de leads heredados tras una reasignación masiva.
    -- El frontend muestra un badge "Heredado de Fernando · hace 3 días"
    -- en la card si reassigned_at < 30 días.
    l.previous_asesor_id::text  AS previous_asesor_id,
    l.reassigned_at::text       AS reassigned_at,
    (
        SELECT TRIM(COALESCE(pa.first_name,'') || ' ' || COALESCE(pa.last_name,''))
        FROM auth.users pa
        WHERE pa.id = l.previous_asesor_id
    ) AS previous_asesor_nombre,
    -- V048: total de re-engagements del lead. NULL si la tabla no existe (V048
    -- no aplicada todavia). Usamos LEFT JOIN en el FROM para que el cost sea
    -- ~constante via el index idx_lead_recontactos_lead.
    COALESCE(rc.total_recontactos, 0) AS total_recontactos,
    -- V068.4: timestamp del ultimo recontacto para tooltip UI ("Ultimo: 14/05/26")
    rc.ultimo_recontacto_at,
    -- V050: calidad del lead (frio/tibio/caliente) — pedido comercial para que
    -- el reporte de eficiencia de llamadas refleje categoria. cc traduce el
    -- codigo a nombre + color visualizable. NULL si todavia no se clasifico.
    l.calidad           AS calidad_codigo,
    cc.nombre           AS calidad_nombre,
    cc.color_hex        AS calidad_color,
    -- V062: trazabilidad post-unlink del proveedor. Si el lead vino por API,
    -- pero el admin desvinculo el client, los snapshots viven aca.
    l.api_client_id::text       AS api_client_id,
    l.api_client_legacy_slug    AS api_client_legacy_slug,
    l.api_client_legacy_nombre  AS api_client_legacy_nombre,
    -- V065: sede de destino del lead (donde el cliente quiere ser atendido).
    -- LEFT JOIN para no romper si la sede fue archivada (soft delete).
    l.sede_id::text             AS sede_id,
    (SELECT codigo    FROM crm.sedes WHERE id = l.sede_id) AS sede_codigo,
    (SELECT nombre    FROM crm.sedes WHERE id = l.sede_id) AS sede_nombre,
    (SELECT color_hex FROM crm.sedes WHERE id = l.sede_id) AS sede_color,
    (
        SELECT TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
        FROM (
            SELECT asesor_id, created_at FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
            UNION ALL
            SELECT asesor_id, fecha_llamada FROM crm.llamadas WHERE lead_id = v.id
        ) uc
        JOIN auth.users u ON u.id = uc.asesor_id
        ORDER BY uc.created_at DESC
        LIMIT 1
    ) AS ultimo_asesor_contacto,
    (
        SELECT wn.display_name
        FROM crm.wa_conversations wc
        JOIN crm.wa_numbers wn ON wn.id = wc.wa_number_id
        WHERE wc.lead_id = l.id AND wc.wa_number_id IS NOT NULL
        ORDER BY wc.last_message_at DESC NULLS LAST
        LIMIT 1
    ) AS origen_wa_numero,
    -- V102 / V111: Campos específicos por estado
    l.fecha_proxima_gestion::text AS fecha_proxima_gestion,
    l.accion_proxima_gestion,
    l.motivo_perdida,
    l.motivo_perdida_otro,
    l.tipo_cierre,
    l.segunda_voz,
    -- Citas agendadas: última cita programada y estado de cita
    (
        SELECT c.fecha_cita::text
        FROM crm.contactos c
        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    ) AS fecha_cita,
    (
        SELECT c.tipo_cita
        FROM crm.contactos c
        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    ) AS tipo_cita,
    (
        SELECT c.cita_estado_id
        FROM crm.contactos c
        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    ) AS cita_estado_id,
    (
        SELECT ce.codigo
        FROM crm.contactos c
        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    ) AS cita_estado_codigo,
    (
        SELECT ce.nombre
        FROM crm.contactos c
        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    ) AS cita_estado_nombre,
    (
        SELECT ce.color_hex
        FROM crm.contactos c
        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    ) AS cita_estado_color,
    -- Reciclaje / Bolsa TMK
    l.es_reciclado,
    l.origen_reciclaje,
    l.fecha_reciclaje::text AS fecha_reciclaje,
    l.lote_reciclaje_id::text AS lote_reciclaje_id,
    -- Origen Históricos
    (
        EXISTS (
            SELECT 1 FROM crm_legacy.leads_historico lh
            WHERE lh.lead_crm_id = l.id
        )
        OR LOWER(COALESCE(v.fuente_nombre, '')) IN ('historico', 'histórico')
    ) AS es_historico,
    -- SLA y Alertas operacionales de llamada
    v.sla_15m_cumplido,
    v.sla_15m_notificado_at::text AS sla_15m_notificado_at,
    (
        l.created_at < NOW() - INTERVAL '48 hours'
        AND NOT EXISTS (
            SELECT 1 FROM crm.contactos c WHERE c.lead_id = v.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
            UNION ALL
            SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = v.id
        )
    ) AS is_urgente_48h,
    (
        (
            (l.sla_15m_cumplido = FALSE OR l.sla_15m_notificado_at IS NOT NULL)
            OR (l.created_at < NOW() - INTERVAL '15 minutes' AND l.created_at > NOW() - INTERVAL '48 hours')
        )
        AND NOT EXISTS (
            SELECT 1 FROM crm.contactos c WHERE c.lead_id = v.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
            UNION ALL
            SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = v.id
        )
    ) AS is_sla_15m_vencido,
    -- V124: Ficha Técnica
    l.ficha_tecnica,
    COALESCE(l.ficha_tecnica_completada, FALSE) AS ficha_tecnica_completada
"""

_EXPORT_COLUMNS = """
    v.nombre_completo, v.telefono, l.dni, v.email,
    v.estado_nombre, v.fuente_nombre,
    COALESCE(v.fuente_nombre, '—') AS origen,
    COALESCE(mc_c.name, v.campana) AS campana,
    v.campana AS campana_id,
    COALESCE(mc_f.name, l.anuncio) AS form_nombre,
    COALESCE(l.fuente_form_id, l.anuncio) AS form_id,
    (
        (SELECT COUNT(*) FROM crm.contactos c2 WHERE c2.lead_id = v.id AND c2.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion'))
      + (SELECT COUNT(*) FROM crm.llamadas  ll WHERE ll.lead_id = v.id)
    ) AS intentos_contacto,
    v.asesor_nombre,
    (
        SELECT TRIM(COALESCE(sup.first_name,'') || ' ' || COALESCE(sup.last_name,''))
        FROM (
            SELECT COALESCE(
                (SELECT eq.supervisor_id FROM crm.equipos eq WHERE eq.asesor_id = v.asesor_id AND eq.activo = TRUE LIMIT 1),
                v.supervisor_id,
                v.asesor_id
            ) AS sup_id
        ) target
        JOIN auth.users sup ON sup.id = target.sup_id
    ) AS supervisor_nombre,
    (
        SELECT TRIM(COALESCE(sup.first_name,'') || ' ' || COALESCE(sup.last_name,''))
        FROM (
            SELECT COALESCE(
                (SELECT eq.supervisor_id FROM crm.equipos eq WHERE eq.asesor_id = v.asesor_id AND eq.activo = TRUE LIMIT 1),
                v.supervisor_id,
                v.asesor_id
            ) AS sup_id
        ) target
        JOIN auth.users sup ON sup.id = target.sup_id
    ) AS supervisor_jefe_nombre,
    -- Fechas como timestamp NAIVE en hora Lima. Las columnas en DB son
    -- timestamptz; openpyxl no acepta datetimes con tzinfo, asi que las
    -- convertimos a hora local aqui — el router las escribe directo como
    -- celdas Excel datetime con formato propio.
    (v.fecha_ingreso         AT TIME ZONE 'America/Lima') AS fecha_ingreso,
    (v.fecha_asignacion      AT TIME ZONE 'America/Lima') AS fecha_asignacion,
    ((SELECT MIN(ts) FROM (
        SELECT created_at::timestamptz AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
        UNION ALL SELECT fecha_llamada::timestamptz FROM crm.llamadas WHERE lead_id = v.id
    ) _fp) AT TIME ZONE 'America/Lima') AS fecha_primer_contacto,
    ((SELECT MAX(ts) FROM (
        SELECT created_at::timestamptz AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
        UNION ALL SELECT fecha_llamada::timestamptz FROM crm.llamadas WHERE lead_id = v.id
    ) _uc) AT TIME ZONE 'America/Lima') AS fecha_ultimo_contacto,
    ((SELECT MAX(ts) FROM (
        SELECT created_at::timestamptz AS ts FROM crm.contactos WHERE lead_id = v.id
        UNION ALL SELECT fecha_llamada::timestamptz FROM crm.llamadas WHERE lead_id = v.id
        UNION ALL SELECT created_at::timestamptz FROM crm.asignaciones_log WHERE lead_id = v.id
        UNION ALL SELECT created_at::timestamptz FROM crm.lead_recontactos WHERE lead_id = v.id
        UNION ALL SELECT COALESCE(l.updated_at, l.created_at)::timestamptz AS ts
    ) _all_act) AT TIME ZONE 'America/Lima') AS ultima_actividad,
    v.ultimo_tipo_contacto, v.ultimo_resultado,
    l.ciudad, l.trabajo, l.referido_por, l.codigo_convenio, l.observaciones,
    -- V094 — Tipo del lead: "Nuevo" si nunca tuvo recontacto, "Recontacto"
    -- si la tabla crm.lead_recontactos tiene al menos una fila para él.
    -- Útil para que el analista del proveedor (Wedo) distinga en su pivot
    -- "lo que originamos nosotros" vs "lo que reactivamos sobre cartera vieja".
    CASE WHEN COALESCE(rc.total_recontactos, 0) > 0
         THEN 'Recontacto'
         ELSE 'Nuevo'
    END                                    AS tipo_lead,
    COALESCE(rc.total_recontactos, 0)      AS total_recontactos,
    (rc.ultimo_recontacto_at AT TIME ZONE 'America/Lima') AS ultimo_recontacto_at,
    -- V096.6 — Atribucion del ULTIMO recontacto. El lead row mantiene la
    -- atribucion ORIGINAL (Tiktok / Promo Mayo); estas columnas revelan
    -- desde donde vino el recontacto mas reciente (ej: WhatsApp / Camp.
    -- Reactivacion Premium). Sirve a Wedo y a Palma para distinguir
    -- "cliente original de X reactivado via Y" en sus pivots.
    ult_rc_f.nombre                                          AS ult_recontacto_fuente,
    COALESCE(ult_rc_mc_c.name, ult_rc.campana)               AS ult_recontacto_campana,
    COALESCE(ult_rc_mc_f.name, ult_rc.fuente_form_id)        AS ult_recontacto_form,
    ult_rc.anuncio                                           AS ult_recontacto_anuncio
"""


_SORT_FIELDS_MAP = {
    # whitelist: campo del query → expresion SQL.
    # Solo permitimos columnas que sabemos que existen y son indexables.
    "fecha_ingreso":         "v.fecha_ingreso",
    "fecha_asignacion":      "v.fecha_asignacion",
    "fecha_cita":            "(SELECT c.fecha_cita FROM crm.contactos c WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL ORDER BY c.created_at DESC, c.id DESC LIMIT 1)",
    "fecha_proxima_gestion": "l.fecha_proxima_gestion",
    "fecha_primer_contacto": "(SELECT MIN(ts) FROM (SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion') UNION ALL SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = v.id) _s)",
    "fecha_ultimo_contacto": "(SELECT MAX(ts) FROM (SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion') UNION ALL SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = v.id) _s2)",
    "ultima_actividad":      "(SELECT MAX(ts) FROM (SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id UNION ALL SELECT fecha_llamada AS ts FROM crm.llamadas WHERE lead_id = v.id UNION ALL SELECT created_at AS ts FROM crm.asignaciones_log WHERE lead_id = v.id UNION ALL SELECT created_at AS ts FROM crm.lead_recontactos WHERE lead_id = v.id UNION ALL SELECT COALESCE(l.updated_at, l.created_at) AS ts) _ua)",
    "updated_at":            "v.updated_at",
    "nombre_completo":       "v.nombre_completo",
    "estado_id":             "v.estado_id",
    "intentos_contacto":     "(SELECT COUNT(*) FROM crm.contactos c2 WHERE c2.lead_id = v.id AND c2.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion'))",
    # V094 — re-engagement workflow patron CRMs profesionales:
    # "Actividad reciente" = lo mas tarde que paso algo relevante con el lead.
    # GREATEST de: ultimo recontacto, ultimo contacto, asignacion, creacion.
    # COALESCE a 'epoch' para tratar NULLs como muy viejos (los empuja al
    # fondo en DESC). Esto hace que los leads recontactados burbujeen al
    # top de la lista AUTOMATICAMENTE, sin que el asesor tenga que filtrar.
    "actividad_reciente": (
        "GREATEST("
        "COALESCE(v.fecha_ultimo_recontacto, 'epoch'::timestamptz),"
        "COALESCE(v.fecha_ultimo_contacto,   'epoch'::timestamptz),"
        "COALESCE(v.fecha_asignacion,        'epoch'::timestamptz),"
        "COALESCE(v.fecha_ingreso,           'epoch'::timestamptz)"
        ")"
    ),
}


def _build_order_by(sort_param: str) -> str:
    """Convierte 'fecha_ingreso:desc,nombre_completo:asc' a una clausula
    ORDER BY segura via whitelist. Devuelve siempre una clausula valida.

    Determinismo (V070.6):
        Siempre se anade 'v.id DESC' como ultimo criterio de desempate. Sin
        este tie-breaker, dos leads con el mismo fecha_ingreso devuelven
        orden no-deterministico en PostgreSQL — la web podia mostrar
        Edwin primero y el mobile mostrar Victor primero el mismo segundo.
        Tambien rompe la paginacion: LIMIT/OFFSET sobre un order no estable
        puede repetir o saltar filas entre paginas. Patron estandar en
        APIs paginadas a escala (patrón estándar, servicio externo, patrón estándar REST).
    """
    parts = []
    if sort_param:
        for raw in sort_param.split(","):
            raw = raw.strip()
            if not raw:
                continue
            if ":" in raw:
                field, direction = raw.split(":", 1)
            else:
                field, direction = raw, "desc"
            field = field.strip()
            direction = direction.strip().lower()
            if direction not in ("asc", "desc"):
                direction = "desc"
            sql_expr = _SORT_FIELDS_MAP.get(field)
            if not sql_expr:
                continue   # ignora silenciosamente campos no permitidos
            # NULLS LAST para fechas evita que NULLs aparezcan primero en DESC
            parts.append(f"{sql_expr} {direction.upper()} NULLS LAST")
    if not parts:
        # V094 — default cambio a "actividad_reciente" (patron estandar):
        # los leads con recontacto/contacto/asignacion recientes burbujean
        # al top en vez de quedar ordenados por created_at puro. Esto evita
        # que un lead de enero 2024 reactivado quede invisible en posicion
        # 4823 de 5126. Si el cliente quiere el orden viejo, usa el SortMenu.
        parts.append(_SORT_FIELDS_MAP["actividad_reciente"] + " DESC NULLS LAST")
    # Tie-breaker estable — siempre va al final, garantiza orden total.
    parts.append("v.id DESC")
    return ", ".join(parts)


def find_paginated(
    filters: LeadFilters, user: TokenData, *, limit: int, offset: int,
    sort: str | None = None,
) -> tuple[list[dict], int]:
    """Devuelve (rows, total) para el listado paginado del dashboard.

    sort: string con formato 'campo:dir,campo:dir'. Ej:
          'fecha_ingreso:desc' (default si None)
          'nombre_completo:asc,fecha_ingreso:desc'
    """
    where, params = apply_lead_filters(filters, user)
    order_by = _build_order_by(sort)
    query_params = params + [limit, offset]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT {_LIST_COLUMNS}
                FROM crm.vw_leads_dashboard v
                JOIN crm.leads l ON l.id = v.id
                -- Resolución perezosa de nombres de catálogo Meta. Los IDs se
                -- guardan en `v.campana` / `l.fuente_form_id` y los nombres
                -- legibles los cachea `crm.meta_catalog_cache` (V030).
                LEFT JOIN crm.meta_catalog_cache mc_c
                  ON mc_c.entity_type = 'campaign'
                 AND mc_c.entity_id   = v.campana
                 AND mc_c.fetch_status = 'ok'
                LEFT JOIN crm.meta_catalog_cache mc_f
                  ON mc_f.entity_type = 'form'
                 AND mc_f.entity_id   = l.fuente_form_id
                 AND mc_f.fetch_status = 'ok'
                -- V048: count de re-engagements via LEFT JOIN LATERAL (idempotente
                -- ante la ausencia de la vista; si la tabla no existe, la query
                -- falla — pero el migrator garantiza V048 antes del traffic).
                LEFT JOIN crm.vw_leads_recontactos_count rc ON rc.lead_id = v.id
                -- V050: catalogo de calidad para mostrar nombre + color del badge.
                LEFT JOIN crm.catalogo_calidad cc ON UPPER(cc.codigo) = UPPER(l.calidad)
                WHERE {where}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                query_params,
            )
            rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.vw_leads_dashboard v
                JOIN crm.leads l ON l.id = v.id
                WHERE {where}
                """,
                params,
            )
            total = cur.fetchone()["total"]
    return rows, total


def find_for_export(
    filters: LeadFilters, user: TokenData, *, limit: int, offset: int
) -> list[dict]:
    """Filas con todas las columnas requeridas para el export Excel."""
    where, params = apply_lead_filters(filters, user)
    query_params = params + [limit, offset]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT {_EXPORT_COLUMNS}
                FROM crm.vw_leads_dashboard v
                JOIN crm.leads l ON l.id = v.id
                LEFT JOIN crm.meta_catalog_cache mc_c
                  ON mc_c.entity_type = 'campaign'
                 AND mc_c.entity_id   = v.campana
                 AND mc_c.fetch_status = 'ok'
                LEFT JOIN crm.meta_catalog_cache mc_f
                  ON mc_f.entity_type = 'form'
                 AND mc_f.entity_id   = l.fuente_form_id
                 AND mc_f.fetch_status = 'ok'
                -- V048: count de re-engagements via LEFT JOIN LATERAL (idempotente
                -- ante la ausencia de la vista; si la tabla no existe, la query
                -- falla — pero el migrator garantiza V048 antes del traffic).
                LEFT JOIN crm.vw_leads_recontactos_count rc ON rc.lead_id = v.id
                -- V096.6 — Ultima fila de lead_recontactos (LATERAL: 1 sola
                -- fila por lead, la mas reciente). 3 JOINs adicionales
                -- resuelven fuente_id -> nombre legible, campaign_id ->
                -- nombre via meta_catalog_cache, form_id -> idem.
                LEFT JOIN LATERAL (
                    SELECT r.fuente_id, r.campana, r.fuente_form_id, r.anuncio
                    FROM crm.lead_recontactos r
                    WHERE r.lead_id = v.id
                    ORDER BY r.created_at DESC
                    LIMIT 1
                ) ult_rc ON TRUE
                LEFT JOIN crm.fuentes ult_rc_f
                  ON ult_rc_f.id = ult_rc.fuente_id
                LEFT JOIN crm.meta_catalog_cache ult_rc_mc_c
                  ON ult_rc_mc_c.entity_type = 'campaign'
                 AND ult_rc_mc_c.entity_id   = ult_rc.campana
                LEFT JOIN crm.meta_catalog_cache ult_rc_mc_f
                  ON ult_rc_mc_f.entity_type = 'form'
                 AND ult_rc_mc_f.entity_id   = ult_rc.fuente_form_id
                -- V050: catalogo de calidad para mostrar nombre + color del badge.
                LEFT JOIN crm.catalogo_calidad cc ON UPPER(cc.codigo) = UPPER(l.calidad)
                WHERE {where}
                ORDER BY v.fecha_ingreso DESC
                LIMIT %s OFFSET %s
                """,
                query_params,
            )
            return cur.fetchall()


def count_by_estado(filters: LeadFilters, user: TokenData) -> list[dict]:
    """Distribución de leads por estado, respetando todos los filtros activos
    salvo el propio `estado_id` (para que el contador de cada pestaña tenga
    sentido)."""
    where, params = apply_lead_filters(filters, user, include_estado=False)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT e.id AS estado_id, e.nombre AS estado, e.color_hex,
                       COUNT(l.id) AS count
                FROM crm.estados_lead e
                LEFT JOIN crm.leads l
                  ON l.estado_id = e.id AND l.activo = TRUE AND {where}
                GROUP BY e.id, e.nombre, e.color_hex, e.orden
                ORDER BY e.orden
                """,
                params,
            )
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Asignación / reasignación con auditoría
# ---------------------------------------------------------------------------
# Estas funciones son la única vía por la que se debe modificar `asesor_id`.
# Cada cambio queda registrado en `crm.asignaciones_log` en la **misma
# transacción** que el UPDATE — atomicidad garantizada por get_db().
#
# El router/servicio es responsable de validar permisos antes de llamar.
# El repositorio asume que ya se autorizó la operación.
# ---------------------------------------------------------------------------


def find_assignments_history(lead_id: int) -> list[dict]:
    """Historial de asignaciones de un lead, ordenado del más reciente al
    más antiguo. Resuelve nombres tanto del asesor anterior como del nuevo
    y de quién hizo la asignación.

    No filtra por rol — el control de acceso lo hace el router antes de
    invocar (mismo patrón que `list_contactos`).
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    al.id,
                    al.created_at::text                                  AS fecha,
                    al.motivo,
                    al.asesor_anterior::text                             AS asesor_anterior_id,
                    TRIM(COALESCE(ua.first_name,'') || ' ' || COALESCE(ua.last_name,''))
                                                                         AS asesor_anterior_nombre,
                    al.asesor_nuevo::text                                AS asesor_nuevo_id,
                    TRIM(COALESCE(un.first_name,'') || ' ' || COALESCE(un.last_name,''))
                                                                         AS asesor_nuevo_nombre,
                    al.asignado_por::text                                AS asignado_por_id,
                    TRIM(COALESCE(up.first_name,'') || ' ' || COALESCE(up.last_name,''))
                                                                         AS asignado_por_nombre
                FROM crm.asignaciones_log al
                LEFT JOIN auth.users ua ON ua.id = al.asesor_anterior
                LEFT JOIN auth.users un ON un.id = al.asesor_nuevo
                LEFT JOIN auth.users up ON up.id = al.asignado_por
                WHERE al.lead_id = %s
                ORDER BY al.created_at DESC, al.id DESC
                """,
                (lead_id,),
            )
            return cur.fetchall()


def fetch_lead_for_assignment(lead_id: int) -> Optional[dict]:
    """Lee `id`, `asesor_id` actual y nombre del lead. None si no existe.

    Se usa en el camino individual para detectar el `asesor_anterior` y
    para construir el mensaje de notificación push.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id,
                       asesor_id::text AS asesor_id,
                       TRIM(COALESCE(nombres,'') || ' ' || COALESCE(apellidos,'')) AS lead_name
                FROM crm.leads
                WHERE id = %s AND activo = TRUE
                """,
                (lead_id,),
            )
            return cur.fetchone()


def reassign_one(
    *,
    lead_id: int,
    new_asesor_id: Optional[str],
    new_supervisor_id=None,
    performed_by: str,
    motivo: str,
) -> dict:
    """Reasigna un único lead y registra el cambio en `asignaciones_log`.

    Retorna `{"changed": bool, "previous_asesor_id": Optional[str], "lead_name": str}`.
    Si el lead ya estaba en el destino, no se loguea (idempotente) y
    `changed=False`.

    Parametros:
      - new_asesor_id: nuevo asesor (UUID str) o None para liberar.
      - new_supervisor_id: V040 — opcional, sentinel object significa
        "no tocar". Cuando se provee str, se actualiza junto con asesor_id
        para que un lead derivado a otro supervisor deje de aparecer en
        el listado del supervisor original.

    No valida permisos — el llamador (servicio) debe haberlo hecho.
    """
    # El servicio pasa un str (UUID), None (liberar / poner supervisor_id en NULL),
    # o un sentinel (KEEP_SUPERVISOR) que significa "no tocar la columna supervisor_id".
    update_sup = new_supervisor_id is not KEEP_SUPERVISOR
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Lock fila para evitar carreras con asignaciones concurrentes
            cur.execute(
                """
                SELECT asesor_id::text AS asesor_id,
                       TRIM(COALESCE(nombres,'') || ' ' || COALESCE(apellidos,'')) AS lead_name
                FROM crm.leads
                WHERE id = %s AND activo = TRUE
                FOR UPDATE
                """,
                (lead_id,),
            )
            row = cur.fetchone()
            if row is None:
                return {"changed": False, "previous_asesor_id": None, "lead_name": ""}

            previous = row["asesor_id"]
            lead_name = row["lead_name"]

            # No-op: ya está donde queremos. No tocamos updated_at ni log.
            if previous == new_asesor_id:
                return {
                    "changed": False,
                    "previous_asesor_id": previous,
                    "lead_name": lead_name,
                }

            # V035: al asignar un asesor real, el lead sale de la cola
            # (fecha_entrada_cola se limpia). Al liberar (new_asesor_id=NULL),
            # vuelve a cola → marcamos el momento.
            # V040: si el destino cambia de equipo (otro supervisor), también
            # actualizamos `supervisor_id` para que el supervisor de origen
            # deje de ver el lead vía role_filter.
            if update_sup:
                cur.execute(
                    """
                    UPDATE crm.leads
                       SET asesor_id          = %s::uuid,
                           supervisor_id      = %s::uuid,
                           fecha_entrada_cola = CASE
                               WHEN %s::uuid IS NULL THEN NOW()
                               ELSE NULL
                           END,
                           updated_at         = NOW()
                     WHERE id = %s
                    """,
                    (new_asesor_id, new_supervisor_id, new_asesor_id, lead_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE crm.leads
                       SET asesor_id          = %s::uuid,
                           fecha_entrada_cola = CASE
                               WHEN %s::uuid IS NULL THEN NOW()
                               ELSE NULL
                           END,
                           updated_at         = NOW()
                     WHERE id = %s
                    """,
                    (new_asesor_id, new_asesor_id, lead_id),
                )

            cur.execute(
                """
                INSERT INTO crm.asignaciones_log
                    (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s)
                """,
                (lead_id, previous, new_asesor_id, performed_by, motivo),
            )

            # Historial de cambios unificado (V126)
            try:
                from app.services import lead_history_service
                lead_history_service.record_reassignment(
                    cur,
                    lead_id=lead_id,
                    user=performed_by,
                    old_asesor_id=previous,
                    new_asesor_id=new_asesor_id,
                    motivo=motivo,
                )
            except Exception:
                pass

            # Propaga el cambio a la conversacion WhatsApp asociada (si existe)
            # asi el chat aparece en la bandeja del nuevo asesor sin que
            # nadie tenga que reasignarlo manualmente. Si no hay
            # wa_conversations no pasa nada (UPDATE 0 filas).
            cur.execute(
                """
                UPDATE crm.wa_conversations
                   SET asesor_id = %s::uuid
                 WHERE lead_id = %s
                """,
                (new_asesor_id, lead_id),
            )
        conn.commit()

    return {
        "changed": True,
        "previous_asesor_id": previous,
        "lead_name": lead_name,
    }


def reassign_bulk(
    *,
    lead_ids: list[int],
    new_asesor_id: Optional[str],
    new_supervisor_id=None,
    performed_by: str,
    motivo: str,
    role_clause: str,
    role_params: list,
) -> dict:
    """Reasigna múltiples leads en una sola transacción.

    El `role_clause`/`role_params` viene del filtro de rol del llamador y
    se aplica como salvaguarda final: aunque el servicio ya validó equipo,
    si un cliente envía IDs de leads que no le pertenecen, la query los
    descarta sin escribir nada — defensa en profundidad.

    Retorna `{"changed": int, "skipped": int, "lead_names": [str]}` donde
    `skipped` cuenta los que ya estaban en el destino o no pasaron el filtro
    de rol.
    """
    if not lead_ids:
        return {"changed": 0, "skipped": 0, "lead_names": []}
    if len(lead_ids) > MAX_BULK_REASSIGN:
        raise ValueError(f"Bulk supera el máximo permitido ({MAX_BULK_REASSIGN}).")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Bloquear filas afectadas y traer estado anterior. El filtro
            #    de rol descarta cualquier ID que no le corresponda al user.
            cur.execute(
                f"""
                SELECT id,
                       asesor_id::text AS asesor_id,
                       TRIM(COALESCE(nombres,'') || ' ' || COALESCE(apellidos,'')) AS lead_name
                FROM crm.leads l
                WHERE id = ANY(%s)
                  AND activo = TRUE
                  AND ({role_clause})
                ORDER BY id
                FOR UPDATE
                """,
                [lead_ids] + role_params,
            )
            rows = cur.fetchall()

            # IDs que efectivamente cambian de asesor (descarta no-ops)
            to_change = [r for r in rows if r["asesor_id"] != new_asesor_id]
            ids_to_change = [r["id"] for r in to_change]
            skipped = len(lead_ids) - len(ids_to_change)

            update_sup = new_supervisor_id is not KEEP_SUPERVISOR
            if ids_to_change:
                # V035: asignación vacía leads → vuelven a cola; asignación
                # real a asesor → salen de cola (fecha_entrada_cola NULL).
                # V040: si cambia de equipo, supervisor_id también se mueve.
                if update_sup:
                    cur.execute(
                        """
                        UPDATE crm.leads
                           SET asesor_id          = %s::uuid,
                               supervisor_id      = %s::uuid,
                               fecha_entrada_cola = CASE
                                   WHEN %s::uuid IS NULL THEN NOW()
                                   ELSE NULL
                               END,
                               updated_at         = NOW()
                         WHERE id = ANY(%s)
                        """,
                        (new_asesor_id, new_supervisor_id, new_asesor_id, ids_to_change),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE crm.leads
                           SET asesor_id          = %s::uuid,
                               fecha_entrada_cola = CASE
                                   WHEN %s::uuid IS NULL THEN NOW()
                                   ELSE NULL
                               END,
                               updated_at         = NOW()
                         WHERE id = ANY(%s)
                        """,
                        (new_asesor_id, new_asesor_id, ids_to_change),
                    )

                # INSERT masivo desde la lista (paramétrica, no string interpolation)
                args = [
                    (r["id"], r["asesor_id"], new_asesor_id, performed_by, motivo)
                    for r in to_change
                ]
                cur.executemany(
                    """
                    INSERT INTO crm.asignaciones_log
                        (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                    VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s)
                    """,
                    args,
                )

                # Historial de cambios unificado (V126)
                try:
                    from app.services import lead_history_service
                    for r in to_change:
                        lead_history_service.record_reassignment(
                            cur,
                            lead_id=r["id"],
                            user=performed_by,
                            old_asesor_id=r["asesor_id"],
                            new_asesor_id=new_asesor_id,
                            motivo=motivo,
                        )
                except Exception:
                    pass

                # Propaga el cambio a wa_conversations (mismo lote)
                cur.execute(
                    """
                    UPDATE crm.wa_conversations
                       SET asesor_id = %s::uuid
                     WHERE lead_id = ANY(%s)
                    """,
                    (new_asesor_id, ids_to_change),
                )
        conn.commit()

    return {
        "changed": len(ids_to_change),
        "skipped": skipped,
        "lead_names": [r["lead_name"] for r in to_change],
    }

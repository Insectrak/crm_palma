-- =============================================================================
-- Migración V004: Vistas del dashboard CRM
-- Fecha:       2026-04-03
-- Autor:       Brighton
-- Descripción: Vistas que abstraen las queries del dashboard y la API.
--              Todas usan OR REPLACE para ser re-ejecutables sin DROP previo.
--
-- VISTAS CREADAS:
--   crm.vw_leads_dashboard     → Lista de leads con último contacto y nombres
--   crm.vw_kpis_por_asesor     → KPIs: conteo de leads por estado por asesor
--   crm.vw_kpis_por_supervisor → KPIs: conteo de leads por estado por supervisor
--   crm.vw_leads_pendientes    → Leads activos sin contacto en las últimas 24 h
--
-- NOTA SOBRE FILTRADO POR ROL:
--   Las vistas retornan TODOS los registros. El filtrado por rol (admin/supervisor/asesor)
--   se hace en la capa de aplicación (FastAPI / build_lead_filter()).
--   Ver sección 5 de ARQUITECTURA_CRM.md.
--
-- TABLA DE USUARIOS: auth.users (UUID PK — sistema activo)
--   Columnas usadas: id (UUID), email, first_name, last_name, role, is_active
--   nombre_completo se construye como TRIM(first_name || ' ' || last_name)
--
-- PRECONDICIONES:
--   - Debe haberse ejecutado V001, V002 y V003.
--   - Las tablas crm.fuentes y crm.estados_lead deben tener datos (seed V000 o V005).
-- =============================================================================

BEGIN;

-- =============================================================================
-- Vista: crm.vw_leads_dashboard
-- Propósito: Vista principal del listado de leads.
-- Muestra cada lead con su estado actual, fuente, nombre del asesor y
-- datos del último contacto registrado.
-- Usada por: GET /api/leads, panel principal de Appsmith.
-- =============================================================================
CREATE OR REPLACE VIEW crm.vw_leads_dashboard AS
WITH ultimo_contacto AS (
    -- Obtener el último contacto de cada lead usando DISTINCT ON
    SELECT DISTINCT ON (lead_id)
        lead_id,
        id                   AS contacto_id,
        tipo_contacto        AS ultimo_tipo_contacto,
        resultado            AS ultimo_resultado,
        notas                AS ultimas_notas,
        fecha_proxima_accion,
        fecha_cita           AS proxima_cita,
        created_at           AS fecha_ultimo_contacto
    FROM crm.contactos
    ORDER BY lead_id, created_at DESC
)
SELECT
    -- Datos del lead
    l.id,
    l.nombres,
    l.apellidos,
    -- Nombre completo calculado (para display en el frontend)
    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
    l.telefono,
    l.email,
    l.ciudad,
    l.trabajo,
    l.es_recontacto,
    l.intentos_contacto,
    l.observaciones,
    l.datos_extra,
    l.hash_dedup,
    l.activo,
    l.created_at            AS fecha_ingreso,
    l.updated_at,

    -- Estado del lead
    l.estado_id,
    e.nombre                AS estado_nombre,
    e.color_hex             AS estado_color,
    e.es_final              AS estado_es_final,

    -- Fuente del lead
    l.fuente_id,
    f.nombre                AS fuente_nombre,
    l.fuente_externa_id,
    l.campana,

    -- Asesor asignado
    l.asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                 AS asesor_email,

    -- Supervisor del asesor (para filtros del supervisor)
    eq.supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,

    -- Último contacto
    uc.contacto_id,
    uc.ultimo_tipo_contacto,
    uc.ultimo_resultado,
    uc.ultimas_notas,
    uc.fecha_ultimo_contacto,
    uc.fecha_proxima_accion,
    uc.proxima_cita,

    -- Indicador de leads sin contacto reciente (útil para alertas)
    CASE
        WHEN uc.fecha_ultimo_contacto IS NULL THEN TRUE
        WHEN uc.fecha_ultimo_contacto < NOW() - INTERVAL '24 hours' THEN TRUE
        ELSE FALSE
    END                     AS sin_contacto_reciente,

    -- Tiempo desde el ingreso (en horas, para SLA)
    EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 3600 AS horas_desde_ingreso

FROM crm.leads l
LEFT JOIN crm.estados_lead   e  ON e.id  = l.estado_id
LEFT JOIN crm.fuentes        f  ON f.id  = l.fuente_id
LEFT JOIN auth.users         a  ON a.id  = l.asesor_id
LEFT JOIN crm.equipos        eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
LEFT JOIN auth.users         s  ON s.id  = eq.supervisor_id
LEFT JOIN ultimo_contacto    uc ON uc.lead_id = l.id
WHERE l.activo = TRUE;

COMMENT ON VIEW crm.vw_leads_dashboard IS
    'Vista principal del listado de leads con estado, fuente, asesor y último contacto. '
    'El filtrado por rol (admin/supervisor/asesor) se aplica en la capa de aplicación.';

-- =============================================================================
-- Vista: crm.vw_kpis_por_asesor
-- Propósito: KPIs de performance por asesor.
-- Muestra el conteo de leads en cada estado por asesor.
-- Usada por: GET /api/dashboard/leads-por-asesor, panel de supervisores.
-- =============================================================================
CREATE OR REPLACE VIEW crm.vw_kpis_por_asesor AS
SELECT
    a.id                    AS asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                 AS asesor_email,

    -- Supervisor del asesor
    eq.supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,

    -- Conteos por estado
    COUNT(l.id)             AS total_leads,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación') AS leads_en_negociacion,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Ganado')         AS leads_ganado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
    COUNT(l.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,

    -- Leads sin contactar todavía
    COUNT(l.id) FILTER (
        WHERE NOT EXISTS (
            SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id
        )
    )                       AS leads_sin_contacto,

    -- Leads con próxima acción vencida (fecha_proxima_accion < ahora)
    COUNT(DISTINCT co_vencido.lead_id) AS leads_accion_vencida,

    -- Tasa de conversión (Ganados / Total)
    CASE
        WHEN COUNT(l.id) = 0 THEN 0
        ELSE ROUND(
            100.0 * COUNT(l.id) FILTER (WHERE e.nombre = 'Ganado') / COUNT(l.id),
            2
        )
    END                     AS tasa_conversion_pct

FROM auth.users a
LEFT JOIN crm.equipos eq
    ON eq.asesor_id = a.id AND eq.activo = TRUE
LEFT JOIN auth.users s
    ON s.id = eq.supervisor_id
LEFT JOIN crm.leads l
    ON l.asesor_id = a.id AND l.activo = TRUE
LEFT JOIN crm.estados_lead e
    ON e.id = l.estado_id
LEFT JOIN LATERAL (
    -- Subconsulta lateral: leads de este asesor con próxima acción vencida
    SELECT DISTINCT c.lead_id
    FROM crm.contactos c
    JOIN crm.leads lv ON lv.id = c.lead_id
    WHERE lv.asesor_id = a.id
      AND c.fecha_proxima_accion < NOW()
      AND c.id = (
          SELECT id FROM crm.contactos
          WHERE lead_id = c.lead_id
          ORDER BY created_at DESC
          LIMIT 1
      )
) co_vencido ON TRUE
-- Solo usuarios con rol asesor
WHERE a.role = 'asesor'
  AND a.is_active = TRUE

GROUP BY
    a.id, a.first_name, a.last_name, a.email,
    eq.supervisor_id, s.first_name, s.last_name;

COMMENT ON VIEW crm.vw_kpis_por_asesor IS
    'KPIs de performance individual por asesor: conteo de leads por estado, '
    'tasa de conversión y leads con acción vencida.';

-- =============================================================================
-- Vista: crm.vw_kpis_por_supervisor
-- Propósito: KPIs agregados por supervisor (suma de todos sus asesores).
-- Usada por: GET /api/dashboard/resumen (rol=supervisor), panel de admin.
-- =============================================================================
CREATE OR REPLACE VIEW crm.vw_kpis_por_supervisor AS
SELECT
    s.id                    AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
    s.email                 AS supervisor_email,

    -- Conteo de asesores activos bajo este supervisor
    COUNT(DISTINCT eq.asesor_id)    AS total_asesores,

    -- Totales de leads de todos sus asesores
    COUNT(l.id)                     AS total_leads,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación') AS leads_en_negociacion,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Ganado')         AS leads_ganado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
    COUNT(l.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,

    -- Tasa de conversión del equipo
    CASE
        WHEN COUNT(l.id) = 0 THEN 0
        ELSE ROUND(
            100.0 * COUNT(l.id) FILTER (WHERE e.nombre = 'Ganado') / COUNT(l.id),
            2
        )
    END                     AS tasa_conversion_pct,

    -- Leads ingresados hoy
    COUNT(l.id) FILTER (
        WHERE l.created_at >= CURRENT_DATE::TIMESTAMPTZ
    )                       AS leads_hoy,

    -- Leads ingresados en los últimos 7 días
    COUNT(l.id) FILTER (
        WHERE l.created_at >= NOW() - INTERVAL '7 days'
    )                       AS leads_ultimos_7dias,

    -- Leads ingresados en los últimos 30 días
    COUNT(l.id) FILTER (
        WHERE l.created_at >= NOW() - INTERVAL '30 days'
    )                       AS leads_ultimos_30dias

FROM auth.users s
LEFT JOIN crm.equipos eq
    ON eq.supervisor_id = s.id AND eq.activo = TRUE
LEFT JOIN crm.leads l
    ON l.asesor_id = eq.asesor_id AND l.activo = TRUE
LEFT JOIN crm.estados_lead e
    ON e.id = l.estado_id
WHERE s.role = 'supervisor'
  AND s.is_active = TRUE

GROUP BY s.id, s.first_name, s.last_name, s.email;

COMMENT ON VIEW crm.vw_kpis_por_supervisor IS
    'KPIs agregados por supervisor: totales de leads de su equipo completo, '
    'tasa de conversión del equipo y distribución por estado.';

-- =============================================================================
-- Vista: crm.vw_leads_pendientes
-- Propósito: Leads activos que necesitan atención urgente:
--   - Sin ningún contacto registrado
--   - O cuyo último contacto fue hace más de 24 horas
-- Usada por: GET /api/dashboard/proximas-acciones, widget de alertas.
-- =============================================================================
CREATE OR REPLACE VIEW crm.vw_leads_pendientes AS
WITH ultimo_contacto AS (
    SELECT DISTINCT ON (lead_id)
        lead_id,
        created_at           AS fecha_ultimo_contacto,
        tipo_contacto        AS ultimo_tipo,
        resultado            AS ultimo_resultado,
        fecha_proxima_accion
    FROM crm.contactos
    ORDER BY lead_id, created_at DESC
)
SELECT
    l.id,
    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
    l.telefono,
    l.email,
    l.created_at             AS fecha_ingreso,

    -- Estado
    l.estado_id,
    e.nombre                 AS estado_nombre,

    -- Fuente
    f.nombre                 AS fuente_nombre,

    -- Asesor
    l.asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,

    -- Info del último contacto
    uc.fecha_ultimo_contacto,
    uc.ultimo_tipo,
    uc.ultimo_resultado,
    uc.fecha_proxima_accion,

    -- Horas sin contacto desde el ingreso o desde el último contacto
    CASE
        WHEN uc.fecha_ultimo_contacto IS NULL
        THEN EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 3600
        ELSE EXTRACT(EPOCH FROM (NOW() - uc.fecha_ultimo_contacto)) / 3600
    END                      AS horas_sin_contacto,

    -- Tipo de pendiente (para categorizar en el dashboard)
    CASE
        WHEN uc.fecha_ultimo_contacto IS NULL         THEN 'sin_contacto_inicial'
        WHEN uc.fecha_proxima_accion < NOW()           THEN 'accion_vencida'
        ELSE                                               'sin_contacto_reciente'
    END                      AS tipo_pendiente

FROM crm.leads l
LEFT JOIN crm.estados_lead   e  ON e.id = l.estado_id
LEFT JOIN crm.fuentes        f  ON f.id = l.fuente_id
LEFT JOIN auth.users         a  ON a.id = l.asesor_id
LEFT JOIN ultimo_contacto    uc ON uc.lead_id = l.id

WHERE
    l.activo = TRUE
    AND e.es_final = FALSE   -- excluir leads en estados terminales (Ganado, Perdido, etc.)
    AND (
        -- Sin ningún contacto registrado
        uc.lead_id IS NULL
        OR
        -- Último contacto hace más de 24 horas
        uc.fecha_ultimo_contacto < NOW() - INTERVAL '24 hours'
        OR
        -- Próxima acción vencida
        (uc.fecha_proxima_accion IS NOT NULL AND uc.fecha_proxima_accion < NOW())
    )
ORDER BY horas_sin_contacto DESC;

COMMENT ON VIEW crm.vw_leads_pendientes IS
    'Leads activos no terminales que llevan más de 24 h sin contacto '
    'o tienen una próxima acción vencida. Ordered por urgencia (horas sin contacto desc).';

COMMIT;

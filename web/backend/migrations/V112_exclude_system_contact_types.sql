-- ║ V112 — Excluir tipos de contacto de sistema / auditoría de vw_leads_dashboard ║
-- Propósito: Evitar que registros automáticos ('sistema', 'reasignacion', 'cambio_fuente', 'cambio_estado')
-- incrementen 'intentos_contacto' o distorsionen 'fecha_primer_contacto', 'fecha_ultimo_contacto' y 'ultimo_tipo_contacto'.

BEGIN;

DROP VIEW IF EXISTS crm.vw_leads_dashboard CASCADE;

CREATE OR REPLACE VIEW crm.vw_leads_dashboard AS
WITH todas_interacciones AS (
    SELECT
        id::bigint AS id,
        lead_id,
        asesor_id,
        tipo_contacto,
        resultado,
        notas,
        fecha_proxima_accion,
        fecha_cita,
        created_at
    FROM crm.contactos
    WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
    UNION ALL
    SELECT
        id::bigint AS id,
        lead_id,
        asesor_id,
        CASE tipo
            WHEN 'entrante' THEN 'llamada_entrante'
            WHEN 'saliente' THEN 'llamada_saliente'
            ELSE 'llamada'
        END AS tipo_contacto,
        CASE
            WHEN duracion_segundos > 0 THEN 'contesto'
            ELSE 'no_contesto'
        END AS resultado,
        NULL::text AS notas,
        NULL::timestamp without time zone AS fecha_proxima_accion,
        NULL::timestamp without time zone AS fecha_cita,
        fecha_llamada AS created_at
    FROM crm.llamadas
    WHERE lead_id IS NOT NULL
),
ultimo_contacto AS (
    SELECT DISTINCT ON (lead_id)
        lead_id,
        id                   AS contacto_id,
        tipo_contacto        AS ultimo_tipo_contacto,
        resultado            AS ultimo_resultado,
        notas                AS ultimas_notas,
        fecha_proxima_accion,
        fecha_cita           AS proxima_cita,
        created_at           AS fecha_ultimo_contacto
    FROM todas_interacciones
    ORDER BY lead_id, created_at DESC
),
contactos_count AS (
    SELECT lead_id, COUNT(*)::int AS total
    FROM todas_interacciones
    GROUP BY lead_id
),
primer_contacto AS (
    SELECT lead_id, MIN(created_at) AS fecha_primer_contacto
    FROM todas_interacciones
    GROUP BY lead_id
),
primera_asignacion AS (
    SELECT lead_id, MIN(ts) AS fecha_asignacion
    FROM (
        SELECT lead_id, created_at AS ts
        FROM crm.asignaciones_log
        UNION ALL
        SELECT lead_id, fecha AS ts
        FROM crm.assignment_log
        UNION ALL
        SELECT id AS lead_id, created_at AS ts
        FROM crm.leads
        WHERE asesor_id IS NOT NULL
    ) _all
    GROUP BY lead_id
)
SELECT
    l.id,
    l.nombres,
    l.apellidos,
    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
    l.telefono,
    l.email,
    l.ciudad,
    l.trabajo,
    l.es_recontacto,
    COALESCE(cc.total, 0)   AS intentos_contacto,
    l.observaciones,
    l.datos_extra,
    l.hash_dedup,
    l.activo,
    l.created_at            AS fecha_ingreso,
    l.updated_at,

    l.estado_id,
    e.nombre                AS estado_nombre,
    e.color_hex             AS estado_color,
    e.es_final              AS estado_es_final,

    l.fuente_id,
    f.nombre                AS fuente_nombre,
    l.fuente_externa_id,
    l.campana,

    l.asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                 AS asesor_email,

    COALESCE(l.supervisor_id, eq.supervisor_id)                       AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,

    uc.contacto_id,
    uc.ultimo_tipo_contacto,
    uc.ultimo_resultado,
    uc.ultimas_notas,
    uc.fecha_ultimo_contacto,
    uc.fecha_proxima_accion,
    uc.proxima_cita,

    CASE
        WHEN uc.fecha_ultimo_contacto IS NULL THEN TRUE
        WHEN uc.fecha_ultimo_contacto < NOW() - INTERVAL '24 hours' THEN TRUE
        ELSE FALSE
    END                     AS sin_contacto_reciente,

    EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 3600 AS horas_desde_ingreso,

    pa.fecha_asignacion,
    pc.fecha_primer_contacto,

    l.proyecto,
    l.estrategia,
    l.calidad,

    l.fecha_entrada_cola,
    CASE
        WHEN l.asesor_id IS NULL
         AND l.fecha_entrada_cola IS NOT NULL
         AND l.fecha_entrada_cola < NOW() - INTERVAL '24 hours'
        THEN TRUE
        ELSE FALSE
    END                     AS cola_estancada,

    -- V041
    l.dni,
    l.tipo_documento,
    -- V093
    l.fecha_ultimo_recontacto,

    -- V102: Campos específicos por estado
    l.fecha_proxima_gestion,
    l.motivo_perdida,
    l.motivo_perdida_otro,
    l.tipo_cierre,
    l.segunda_voz,

    -- V103: SLA, Prioridad y Reciclaje TMK
    l.sla_15m_cumplido,
    l.sla_15m_notificado_at,
    l.sla_24h_notificado_at,
    l.atencion_prioritaria,
    l.es_reciclado,
    l.fecha_reciclaje,
    l.origen_reciclaje,
    l.lote_reciclaje_id,
    l.sede_id,

    -- V104: Convenios
    l.codigo_convenio,

    -- V111: Oportunidad Futura
    l.accion_proxima_gestion

FROM crm.leads l
LEFT JOIN crm.estados_lead   e  ON e.id  = l.estado_id
LEFT JOIN crm.fuentes        f  ON f.id  = l.fuente_id
LEFT JOIN auth.users         a  ON a.id  = l.asesor_id
LEFT JOIN crm.equipos        eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
LEFT JOIN auth.users         s  ON s.id  = COALESCE(l.supervisor_id, eq.supervisor_id)
LEFT JOIN ultimo_contacto    uc ON uc.lead_id = l.id
LEFT JOIN contactos_count    cc ON cc.lead_id = l.id
LEFT JOIN primer_contacto    pc ON pc.lead_id = l.id
LEFT JOIN primera_asignacion pa ON pa.lead_id = l.id
WHERE l.activo = TRUE;

-- Actualizar la vista crm.vw_kpis_por_asesor excluyendo registros de sistema
DROP VIEW IF EXISTS crm.vw_kpis_por_asesor CASCADE;
CREATE OR REPLACE VIEW crm.vw_kpis_por_asesor AS
SELECT
    a.id                                                   AS asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                                                AS asesor_email,
    eq.supervisor_id                                       AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
    COUNT(l.id)                                            AS leads_totales,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
    COUNT(l.id) FILTER (
        WHERE e.nombre ILIKE '%%matr%%'
           OR e.nombre ILIKE '%%ganad%%'
           OR e.nombre ILIKE '%%cierr%%'
    )                                                      AS leads_ganado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
    COUNT(l.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,
    COUNT(l.id) FILTER (
        WHERE NOT EXISTS (
            SELECT 1 FROM crm.contactos c
            WHERE c.lead_id = l.id
              AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
        )
    )                                                      AS leads_sin_contacto,
    COUNT(DISTINCT co_vencido.lead_id)                     AS leads_accion_vencida,
    CASE
        WHEN COUNT(l.id) = 0 THEN 0
        ELSE ROUND(
            100.0 * COUNT(l.id) FILTER (
                WHERE e.nombre ILIKE '%%matr%%'
                   OR e.nombre ILIKE '%%ganad%%'
                   OR e.nombre ILIKE '%%cierr%%'
            ) / COUNT(l.id),
            2
        )
    END                                                    AS tasa_conversion_pct
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
    SELECT c.lead_id
    FROM crm.contactos c
    WHERE c.lead_id = l.id
      AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
      AND c.fecha_proxima_accion < NOW()
    ORDER BY c.created_at DESC
    LIMIT 1
) co_vencido ON co_vencido.lead_id = l.id
WHERE a.role IN ('asesor', 'supervisor')
  AND a.is_active = TRUE
GROUP BY a.id, a.first_name, a.last_name, a.email, eq.supervisor_id, s.first_name, s.last_name;

COMMIT;

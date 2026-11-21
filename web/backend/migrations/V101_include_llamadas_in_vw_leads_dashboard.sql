-- V101 — Incluir llamadas sincronizadas de la app móvil en vw_leads_dashboard
--
-- Problema:
--   La vista crm.vw_leads_dashboard (V093) solo consultaba crm.contactos para
--   calcular `fecha_ultimo_contacto`, `intentos_contacto` y `sin_contacto_reciente`.
--   Las llamadas sincronizadas desde la app móvil Android (en crm.llamadas)
--   no actualizaban el último contacto ni los intentos. Por lo tanto, un asesor
--   que llamaba al lead desde el celular seguía viendo el badge "Sin contacto • Xd"
--   y el lead seguía apareciendo en alertas de estancado/pendiente.
--
-- Solución:
--   Unificar crm.contactos (excluyendo 'cambio_estado') y crm.llamadas en
--   el CTE `todas_interacciones` para que tanto las llamadas móviles como los
--   contactos manuales cuenten de inmediato como interacción activa del lead.

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
    WHERE tipo_contacto != 'cambio_estado'
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
    l.fecha_ultimo_recontacto

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

COMMIT;

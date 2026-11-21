-- ║ V119 — Gestión Especial por Administración y Bypass de Automatización No Contesta ║
-- Propósito:
-- 1. Añadir columnas a crm.leads para indicar que el lead está bajo gestión especial
--    por administración, omitiendo transiciones automáticas a estados 'No contesta'
--    o pase a Bolsa de reciclaje.
-- 2. Registrar fecha/hora y usuario administrador que asumió la gestión especial.
-- 3. Actualizar la vista crm.vw_leads_dashboard para proyectar estos nuevos campos.

BEGIN;

-- 1. Agregar columnas a crm.leads
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS gestion_especial_admin BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS gestion_admin_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS gestion_admin_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

COMMENT ON COLUMN crm.leads.gestion_especial_admin IS 'Indica si el lead está en gestión especial por administración, omitiendo cambios automáticos de estado (ej. No contesta Día 1/2/3/Bolsa).';
COMMENT ON COLUMN crm.leads.gestion_admin_at        IS 'Fecha y hora en que la administración asumió la gestión especial del lead.';
COMMENT ON COLUMN crm.leads.gestion_admin_user_id   IS 'Usuario administrador que activó la gestión especial del lead.';

-- 2. Índice parcial para consultas eficientes de leads bajo gestión especial
CREATE INDEX IF NOT EXISTS idx_leads_gestion_especial_admin
    ON crm.leads (gestion_especial_admin)
    WHERE gestion_especial_admin = TRUE;

-- 3. Actualizar vista crm.vw_leads_dashboard
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
    l.accion_proxima_gestion,

    -- V119: Gestión Especial por Administración
    l.gestion_especial_admin,
    l.gestion_admin_at,
    l.gestion_admin_user_id

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

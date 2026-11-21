-- V124 — Ficha técnica / Cuestionario de descubrimiento comercial para leads
--
-- Requerimientos:
-- 1. Ficha técnica con cuestionario para el asesor encargado:
--    - Motivación: ¿Qué fue lo que más te llamó la atención de nuestra publicidad? / ¿Qué te animó a contactarnos?
--    - Beneficiario: ¿El interés por aprender inglés es para ti o para algún miembro de tu familia?
--    - Ubicación: ¿Te encuentras en Arequipa o en otra ciudad? ¿En qué distrito?
--    - Experiencia previa: ¿Anteriormente habías intentado estudiar inglés? ¿Dónde estudiaste? ¿Qué pasó? ¿Por qué crees que no lograste aprender?
--    - Necesidad actual: ¿Por qué es importante para ti aprender inglés hoy? ¿A qué te dedicas actualmente?
--    - Inicio: ¿Para cuándo te gustaría empezar?
-- 2. Campos opcionales (el asesor rellena después de creado el lead).
-- 3. Flag ficha_tecnica_completada con trigger de sincronización automática.
-- 4. Actualización de crm.vw_leads_dashboard proyectando ficha_tecnica y ficha_tecnica_completada.

BEGIN;

-- 1. Columnas en crm.leads
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS ficha_tecnica JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS ficha_tecnica_completada BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN crm.leads.ficha_tecnica IS 'Cuestionario de descubrimiento comercial: motivacion, beneficiario, ubicacion, experiencia_previa, necesidad_actual, inicio.';
COMMENT ON COLUMN crm.leads.ficha_tecnica_completada IS 'Indica si la ficha técnica tiene todas las preguntas obligatorias respondidas con texto no vacío.';

-- 2. Índice para consultas rápidas por estado de ficha
CREATE INDEX IF NOT EXISTS idx_leads_ficha_tecnica_completada ON crm.leads (ficha_tecnica_completada);

-- 3. Función validadora de completitud
CREATE OR REPLACE FUNCTION crm.fn_check_ficha_tecnica_completada(ft JSONB)
RETURNS BOOLEAN AS $$
BEGIN
    IF ft IS NULL THEN
        RETURN FALSE;
    END IF;
    RETURN (
        COALESCE(TRIM(ft->>'motivacion'), '') <> '' AND
        COALESCE(TRIM(ft->>'beneficiario'), '') <> '' AND
        COALESCE(TRIM(ft->>'ubicacion'), '') <> '' AND
        COALESCE(TRIM(ft->>'experiencia_previa'), '') <> '' AND
        COALESCE(TRIM(ft->>'necesidad_actual'), '') <> '' AND
        COALESCE(TRIM(ft->>'inicio'), '') <> ''
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 4. Trigger de sincronización automática en crm.leads
CREATE OR REPLACE FUNCTION crm.trg_leads_ficha_tecnica_sync()
RETURNS TRIGGER AS $$
BEGIN
    NEW.ficha_tecnica_completada := crm.fn_check_ficha_tecnica_completada(NEW.ficha_tecnica);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_leads_ficha_tecnica_sync ON crm.leads;
CREATE TRIGGER trg_leads_ficha_tecnica_sync
BEFORE INSERT OR UPDATE OF ficha_tecnica ON crm.leads
FOR EACH ROW
EXECUTE FUNCTION crm.trg_leads_ficha_tecnica_sync();

-- 5. Backfill inicial
UPDATE crm.leads
SET ficha_tecnica_completada = crm.fn_check_ficha_tecnica_completada(ficha_tecnica)
WHERE ficha_tecnica IS NOT NULL AND ficha_tecnica <> '{}'::jsonb;

-- 6. Actualizar la vista crm.vw_leads_dashboard
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
    l.gestion_admin_user_id,

    -- V124: Ficha Técnica
    l.ficha_tecnica,
    COALESCE(l.ficha_tecnica_completada, FALSE) AS ficha_tecnica_completada

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

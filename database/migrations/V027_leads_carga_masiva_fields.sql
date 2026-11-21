-- =============================================================================
-- V027 — Campos de carga masiva: proyecto, estrategia, calidad
-- =============================================================================
-- Incorpora los campos que la gerencia usa en su plantilla operativa:
--   FECHA, NOMBRE DEL CLIENTE, CELULAR, CORREO, CIUDAD, PROYECTO,
--   ESTRATEGIA, ESTADO (FRIO/TIBIO/CALIENTE), COMENTARIOS.
--
-- Campos ya existentes en crm.leads:
--   - nombres, apellidos, telefono, email, ciudad, observaciones, created_at
--
-- Campos nuevos que agrega esta migración:
--   - proyecto    TEXT         — proyecto inmobiliario (Palma Río, etc.)
--   - estrategia  TEXT         — estrategia comercial / campaña asociada
--   - calidad     TEXT + CHECK — temperatura del lead: FRIO | TIBIO | CALIENTE
--
-- También:
--   - Añade el índice sobre `calidad` para filtros rápidos en dashboards.
--   - Recrea crm.vw_leads_dashboard para exponer proyecto, estrategia y
--     calidad en el listado principal sin romper las columnas existentes.
-- =============================================================================

BEGIN;

-- ── Columnas nuevas ──────────────────────────────────────────────────────────

ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS proyecto   TEXT;
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS estrategia TEXT;
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS calidad    TEXT;

COMMENT ON COLUMN crm.leads.proyecto   IS
    'Proyecto inmobiliario del lead (Palma Rio, Palma del Rey, etc.).';
COMMENT ON COLUMN crm.leads.estrategia IS
    'Estrategia comercial o campaña asociada al lead (texto libre).';
COMMENT ON COLUMN crm.leads.calidad    IS
    'Temperatura del lead: FRIO | TIBIO | CALIENTE. NULL si aún no se clasificó.';

-- ── Constraint de calidad ────────────────────────────────────────────────────
-- IF NOT EXISTS no aplica para CHECK → lo agregamos defensivo con DO $$ ... $$.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'leads_calidad_chk'
    ) THEN
        ALTER TABLE crm.leads
            ADD CONSTRAINT leads_calidad_chk
            CHECK (calidad IS NULL OR calidad IN ('FRIO', 'TIBIO', 'CALIENTE'));
    END IF;
END$$;

-- ── Índices de filtrado ──────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_leads_calidad   ON crm.leads (calidad)   WHERE activo = TRUE;
CREATE INDEX IF NOT EXISTS idx_leads_proyecto  ON crm.leads (proyecto)  WHERE activo = TRUE;

-- ── Vista principal del dashboard: agregar proyecto/estrategia/calidad ───────
-- PostgreSQL no permite cambiar la firma de columnas existentes con
-- CREATE OR REPLACE VIEW, por eso solo anexamos al final (igual que V019).

CREATE OR REPLACE VIEW crm.vw_leads_dashboard AS
WITH ultimo_contacto AS (
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
),
contactos_count AS (
    SELECT lead_id, COUNT(*)::int AS total
    FROM crm.contactos
    GROUP BY lead_id
),
primer_contacto AS (
    SELECT lead_id, MIN(created_at) AS fecha_primer_contacto
    FROM crm.contactos
    GROUP BY lead_id
),
primera_asignacion AS (
    SELECT DISTINCT ON (lead_id)
        lead_id, created_at AS fecha_asignacion
    FROM crm.asignaciones_log
    ORDER BY lead_id, created_at ASC
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

    eq.supervisor_id,
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

    -- V027: campos de carga masiva (gerencia)
    l.proyecto,
    l.estrategia,
    l.calidad

FROM crm.leads l
LEFT JOIN crm.estados_lead   e  ON e.id  = l.estado_id
LEFT JOIN crm.fuentes        f  ON f.id  = l.fuente_id
LEFT JOIN auth.users         a  ON a.id  = l.asesor_id
LEFT JOIN crm.equipos        eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
LEFT JOIN auth.users         s  ON s.id  = eq.supervisor_id
LEFT JOIN ultimo_contacto    uc ON uc.lead_id = l.id
LEFT JOIN contactos_count    cc ON cc.lead_id = l.id
LEFT JOIN primer_contacto    pc ON pc.lead_id = l.id
LEFT JOIN primera_asignacion pa ON pa.lead_id = l.id
WHERE l.activo = TRUE;

COMMIT;

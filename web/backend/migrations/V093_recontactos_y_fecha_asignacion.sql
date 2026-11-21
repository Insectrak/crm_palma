-- =====================================================================
-- V093 — Visibilidad de recontactos + fix fecha_asignacion (UNION logs)
-- =====================================================================
--
-- Cambios:
-- 1. Nueva columna `crm.leads.fecha_ultimo_recontacto TIMESTAMPTZ` —
--    se actualiza cada vez que `handle_recontacto` registra un evento
--    en crm.lead_recontactos. UI lo usa para mostrar "Recontactado
--    hace X dias" en la lista de leads.
-- 2. View `crm.vw_leads_dashboard` actualizada:
--    a. `fecha_asignacion` ahora deriva de la UNION de TRES fuentes:
--       - crm.asignaciones_log     (legacy — reasignaciones manuales)
--       - crm.assignment_log       (nuevo — auto-assign via lead_routing)
--       - crm.leads.created_at IF asesor_id IS NOT NULL (formularios,
--         carga masiva, ingest que setea asesor directo)
--       Antes solo leia de asignaciones_log → leads de Wedo, formularios
--       y carga masiva aparecian sin fecha_asignacion. Bug confirmado
--       en captura del 2026-06-19.
--    b. Agregada columna `fecha_ultimo_recontacto` al final.
--
-- 3. Backfill: para leads que ya estan marcados es_recontacto=TRUE,
--    poblar fecha_ultimo_recontacto con el MAX(created_at) de sus
--    eventos en lead_recontactos (best-effort retroactivo).
--
-- Idempotente: CREATE OR REPLACE VIEW + ADD COLUMN IF NOT EXISTS.
-- =====================================================================

BEGIN;

-- ── 1. Columna nueva ────────────────────────────────────────────────────
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS fecha_ultimo_recontacto TIMESTAMPTZ;

COMMENT ON COLUMN crm.leads.fecha_ultimo_recontacto IS
    'Ultima vez que este lead fue recontactado (entro a crm.lead_recontactos). '
    'Distinto de fecha_asignacion (cuando fue asignado por primera vez) y de '
    'fecha_ultimo_contacto (cuando el asesor lo contacto por ultima vez). '
    'Sirve para que el asesor vea "este lead viejo volvio a interesarse hace 3 dias".';

-- Index parcial para que las queries "recontactos recientes" sean baratas.
CREATE INDEX IF NOT EXISTS idx_leads_fecha_ultimo_recontacto
    ON crm.leads (fecha_ultimo_recontacto DESC NULLS LAST)
    WHERE activo = TRUE;

-- ── 2. Backfill retroactivo (best-effort) ───────────────────────────────
-- Para leads con es_recontacto=TRUE pero sin fecha_ultimo_recontacto,
-- usar el MAX created_at de la tabla de eventos. Si tampoco tiene
-- eventos registrados, dejar NULL (fenomeno pre-V048 sin trazabilidad).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'crm' AND table_name = 'lead_recontactos'
    ) THEN
        UPDATE crm.leads l
        SET fecha_ultimo_recontacto = sub.ultima_fecha
        FROM (
            SELECT lead_id, MAX(created_at) AS ultima_fecha
            FROM crm.lead_recontactos
            GROUP BY lead_id
        ) sub
        WHERE l.id = sub.lead_id
          AND l.fecha_ultimo_recontacto IS NULL;
    END IF;
END $$;

-- ── 3. View actualizada ─────────────────────────────────────────────────
-- IMPORTANTE: CREATE OR REPLACE VIEW exige preservar nombres y orden
-- de columnas existentes. Solo agregar al final esta permitido. La logica
-- de `primera_asignacion` cambia internamente pero el campo
-- pa.fecha_asignacion mantiene el mismo tipo y posicion.
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
-- V093 — UNION de las 3 fuentes de asignacion + fallback al created_at
-- del lead si nacio con asesor (formularios publicos, carga masiva, etc).
-- Antes solo leia crm.asignaciones_log → bug: leads auto-asignados via
-- lead_routing.py (Wedo, ingest API) o creados con asesor directo
-- (formularios) aparecian con fecha_asignacion = NULL.
--
-- IMPORTANTE — nombres de columna distintos por tabla (historia legacy):
--   crm.asignaciones_log:  columna 'created_at'  (V035-era, default NOW)
--   crm.assignment_log:    columna 'fecha'       (V046, schema nuevo del
--                                                  motor de auto-asign)
--   crm.leads:             columna 'created_at'  (estandar)
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

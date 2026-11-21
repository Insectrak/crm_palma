-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V041 — Persistir tipo_documento en crm.leads                          ║
-- ║                                                                        ║
-- ║ PROBLEMA:                                                              ║
-- ║ El selector tipo_documento (DNI / CE / Pasaporte) vivia solo en el    ║
-- ║ frontend. Al editar un lead despues del refresh, el tipo se inferia   ║
-- ║ con una heuristica imperfecta (longitud + composicion del valor),     ║
-- ║ pero leads sin valor de documento siempre arrancaban en "DNI" aunque  ║
-- ║ el usuario lo hubiera creado con CE/Pasaporte. Para que la edicion    ║
-- ║ refleje fielmente lo que el usuario eligio, persistimos el tipo.      ║
-- ║                                                                        ║
-- ║ CAMBIOS:                                                               ║
-- ║   1. ADD COLUMN tipo_documento TEXT DEFAULT 'DNI' con CHECK constraint║
-- ║   2. Backfill heuristico para leads existentes:                       ║
-- ║       - dni con letras    → Pasaporte                                 ║
-- ║       - dni 9 digitos     → CE                                        ║
-- ║       - else (NULL/8/etc) → DNI                                       ║
-- ║   3. Refrescar vw_leads_dashboard incluyendo tipo_documento.          ║
-- ║                                                                        ║
-- ║ Patron CMMI: cambios trazables, default seguro, no rompe leads        ║
-- ║ historicos. La heuristica solo aplica al backfill — los leads nuevos  ║
-- ║ guardan exactamente lo que el usuario seleccione.                     ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1. Columna nueva ────────────────────────────────────────────────────────

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS tipo_documento TEXT DEFAULT 'DNI';

-- CHECK separado para que ADD COLUMN no falle si la columna ya existia.
-- DROP del constraint previo (si existe) + recrear para idempotencia.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'leads_tipo_documento_check'
    ) THEN
        ALTER TABLE crm.leads DROP CONSTRAINT leads_tipo_documento_check;
    END IF;
END$$;

ALTER TABLE crm.leads
    ADD CONSTRAINT leads_tipo_documento_check
    CHECK (tipo_documento IN ('DNI', 'CE', 'Pasaporte'));

COMMENT ON COLUMN crm.leads.tipo_documento IS
    'Tipo del codigo guardado en `dni`. Valores permitidos: DNI (peruano '
    'nacional, 8 digitos), CE (Carnet de Extranjeria, 9 digitos), Pasaporte '
    '(alfanumerico 6-12). Default DNI para retrocompatibilidad.';

-- ── 2. Backfill: inferir tipo desde el valor existente ──────────────────────

UPDATE crm.leads
SET tipo_documento = CASE
    WHEN dni IS NULL OR dni = '' THEN 'DNI'
    WHEN dni ~ '[A-Za-z]'         THEN 'Pasaporte'
    WHEN dni ~ '^[0-9]{9}$'       THEN 'CE'
    ELSE 'DNI'
END;

-- ── 3. Refrescar vw_leads_dashboard incluyendo tipo_documento ──────────────
-- Recreamos la view de V035 anadiendo `l.tipo_documento` al final. Postgres
-- exige que CREATE OR REPLACE VIEW preserve el orden y nombres existentes;
-- agregar columnas al final esta permitido sin DROP.

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
    l.tipo_documento

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

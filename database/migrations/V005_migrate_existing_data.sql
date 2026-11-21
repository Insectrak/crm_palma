-- =============================================================================
-- Migración V005: Importar datos de pdr_marketing → brighton_crm
-- Fecha:       2026-04-03
-- Autor:       Brighton
--
-- ADVERTENCIA: MIGRACIÓN MANUAL — ejecutar en orden estricto.
--
-- PREREQUISITOS (ejecutar antes de este script):
--   1. Ejecutar export_pdr_leads.sql en pdr_marketing → descargar leads_pdr.csv
--   2. Ejecutar export_pdr_contactos.sql en pdr_marketing → descargar contactos_pdr.csv
--   3. Crear staging_pdr schema (Paso 0 de este script)
--   4. Importar leads_pdr.csv a staging_pdr.leads (pgAdmin → Import/Export)
--   5. Importar contactos_pdr.csv a staging_pdr.contactos (pgAdmin → Import/Export)
--
-- CÓMO IMPORTAR CSV EN PGADMIN:
--   - Click derecho en la tabla staging_pdr.leads
--   - Import/Export Data → Import
--   - Seleccionar el CSV, marcar "Header", separador ","
--   - Repetir para staging_pdr.contactos
--
-- PASOS DE ESTE SCRIPT:
--   Paso 0: Crear schema y tablas staging
--   Paso 1: Crear usuarios en auth.users para los 13 asesores
--   Paso 2: Migrar leads de staging → crm.leads
--   Paso 3: Migrar contactos de staging → crm.contactos
--   Paso 4: Verificación final
-- =============================================================================

-- =============================================================================
-- PASO 0: Crear schema staging y tablas para importar los CSV
-- Ejecutar SOLO este paso primero, luego importar los CSV, luego continuar.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS staging_pdr;

CREATE TABLE IF NOT EXISTS staging_pdr.leads (
    src_id               BIGINT,
    fuente_externa_id    TEXT,
    plataforma           TEXT,
    campana              TEXT,
    created_at           TEXT,   -- TEXT para flexibilidad en import CSV
    nombres              TEXT,
    apellidos            TEXT,
    telefono             TEXT,
    email                TEXT,
    ciudad               TEXT,
    trabajo              TEXT,
    estado_crm           TEXT,
    estado_original      TEXT,
    es_recontacto        TEXT,   -- TEXT para flexibilidad en import CSV
    observaciones        TEXT,
    intentos_contacto    TEXT,
    me_asesor_id         TEXT,
    asesor_nombre        TEXT,
    asesor_schema        TEXT,
    asesor_telefono      TEXT
);

CREATE TABLE IF NOT EXISTS staging_pdr.contactos (
    asesor_schema        TEXT,
    codigo_lead          TEXT,
    tipo_contacto_lead   TEXT,
    seguimiento_lead     TEXT,
    fecha_contacto_lead  TEXT,   -- TEXT para flexibilidad en import CSV
    observaciones        TEXT,
    estado_contacto_lead TEXT,
    fecha_cita_lead      TEXT,   -- TEXT para flexibilidad en import CSV
    tipo_cita_lead       TEXT
);

-- ⚠️  DETENER AQUÍ — Importar los CSV antes de continuar ⚠️
-- Ver instrucciones de importación en el encabezado de este archivo.

-- =============================================================================
-- PASO 1: Crear usuarios en auth.users para los 13 asesores
-- Usa los datos de staging_pdr.leads para obtener nombre y schema de cada asesor.
-- Password temporal: 'CambiarClave2026!' — deben cambiarla en primer login.
-- =============================================================================

BEGIN;

DO $$
DECLARE
    rec    RECORD;
    v_user_id UUID;
    v_email   TEXT;
    v_schema  TEXT;   -- schema normalizado: siempre "asesorN"
BEGIN
    -- Iterar sobre cada asesor único encontrado en el staging
    FOR rec IN
        SELECT DISTINCT
            asesor_schema,
            asesor_nombre,
            asesor_telefono
        FROM staging_pdr.leads
        WHERE asesor_schema IS NOT NULL
          AND asesor_schema != ''
        ORDER BY asesor_schema
    LOOP
        -- Normalizar asesor_schema:
        --   Si es numérico ("1","2"...) → convertir a "asesor1","asesor2"...
        --   Si ya tiene prefijo "asesor" → usar tal cual
        v_schema := CASE
            WHEN asesor_schema ~ '^\d+$' THEN 'asesor' || rec.asesor_schema
            ELSE rec.asesor_schema
        END;

        -- Generar email: asesor1@palmadelrio.com
        v_email := v_schema || '@palmadelrio.com';

        -- Verificar si ya existe en auth.users por _deprecated_advisor_schema (schema normalizado)
        SELECT id INTO v_user_id
        FROM auth.users
        WHERE _deprecated_advisor_schema = v_schema
        LIMIT 1;

        IF v_user_id IS NULL THEN
            -- Crear el usuario asesor con contraseña temporal
            INSERT INTO auth.users (
                id,
                email,
                password_hash,
                first_name,
                last_name,
                role,
                is_active,
                telefono,
                _deprecated_advisor_schema,
                created_at,
                updated_at
            ) VALUES (
                uuid_generate_v1(),
                v_email,
                crypt('CambiarClave2026!', gen_salt('bf')),
                TRIM(SPLIT_PART(COALESCE(rec.asesor_nombre, v_schema), ' ', 1)),
                CASE
                    WHEN POSITION(' ' IN TRIM(COALESCE(rec.asesor_nombre, ''))) > 0
                    THEN TRIM(SUBSTRING(rec.asesor_nombre FROM POSITION(' ' IN TRIM(rec.asesor_nombre)) + 1))
                    ELSE ''
                END,
                'asesor',
                TRUE,
                rec.asesor_telefono,
                v_schema,
                NOW(),
                NOW()
            );

            RAISE NOTICE '[Paso 1] Usuario creado: % → % (schema_orig: %)',
                v_schema, v_email, rec.asesor_schema;
        ELSE
            RAISE NOTICE '[Paso 1] Ya existe usuario para % (schema_orig: %): omitido.',
                v_schema, rec.asesor_schema;
        END IF;
    END LOOP;
END;
$$;

COMMIT;

-- =============================================================================
-- PASO 2: Migrar leads de staging_pdr.leads → crm.leads
-- =============================================================================

BEGIN;

INSERT INTO crm.leads (
    id,
    fuente_id,
    estado_id,
    asesor_id,
    nombres,
    apellidos,
    telefono,
    email,
    ciudad,
    trabajo,
    es_recontacto,
    intentos_contacto,
    observaciones,
    campana,
    fuente_externa_id,
    hash_dedup,
    activo,
    created_at,
    updated_at
)
SELECT
    uuid_generate_v1()                          AS id,

    -- Fuente: buscar en crm.fuentes por nombre normalizado
    (SELECT f.id FROM crm.fuentes f
     WHERE f.nombre = s.plataforma LIMIT 1)     AS fuente_id,

    -- Estado: buscar en crm.estados_lead por nombre
    COALESCE(
        (SELECT e.id FROM crm.estados_lead e
         WHERE e.nombre = s.estado_crm LIMIT 1),
        (SELECT e.id FROM crm.estados_lead e
         WHERE e.nombre = 'Nuevo' LIMIT 1)
    )                                           AS estado_id,

    -- Asesor: buscar en auth.users por _deprecated_advisor_schema
    (SELECT u.id FROM auth.users u
     WHERE u._deprecated_advisor_schema = s.asesor_schema
     LIMIT 1)                                   AS asesor_id,

    NULLIF(TRIM(COALESCE(s.nombres, '')), '')   AS nombres,
    NULLIF(TRIM(COALESCE(s.apellidos, '')), '') AS apellidos,
    NULLIF(TRIM(COALESCE(s.telefono, '')), '')  AS telefono,
    NULLIF(TRIM(COALESCE(s.email, '')), '')     AS email,
    NULLIF(TRIM(COALESCE(s.ciudad, '')), '')    AS ciudad,
    NULLIF(TRIM(COALESCE(s.trabajo, '')), '')   AS trabajo,

    CASE WHEN UPPER(COALESCE(s.es_recontacto, 'false')) IN ('TRUE', 't', '1', 'YES', 'SI', 'SÍ')
         THEN TRUE ELSE FALSE END               AS es_recontacto,

    COALESCE(s.intentos_contacto::INTEGER, 0)  AS intentos_contacto,
    s.observaciones,
    s.campana,
    s.fuente_externa_id,

    -- Hash deduplicación: SHA256(telefono + fuente_externa_id)
    encode(
        digest(
            COALESCE(s.telefono, '') || '|' || COALESCE(s.fuente_externa_id, s.src_id::text),
            'sha256'
        ),
        'hex'
    )                                           AS hash_dedup,

    TRUE                                        AS activo,

    COALESCE(
        s.created_at::TIMESTAMPTZ,
        NOW()
    )                                           AS created_at,
    NOW()                                       AS updated_at

FROM staging_pdr.leads s
-- Evitar duplicados si se re-ejecuta el script
WHERE NOT EXISTS (
    SELECT 1 FROM crm.leads l
    WHERE l.fuente_externa_id = s.fuente_externa_id
      AND s.fuente_externa_id IS NOT NULL
);

DO $$ BEGIN
    RAISE NOTICE '[Paso 2] Leads migrados: %', (SELECT COUNT(*) FROM crm.leads);
END; $$;

COMMIT;

-- =============================================================================
-- PASO 3: Migrar contactos de staging_pdr.contactos → crm.contactos
-- =============================================================================

BEGIN;

INSERT INTO crm.contactos (
    id,
    lead_id,
    asesor_id,
    tipo_contacto,
    resultado,
    notas,
    fecha_cita,
    created_at,
    updated_at
)
SELECT
    uuid_generate_v1()                          AS id,

    -- Buscar lead por fuente_externa_id = codigo_lead en el asesor correcto
    (SELECT l.id FROM crm.leads l
     JOIN staging_pdr.leads sl ON sl.fuente_externa_id = l.fuente_externa_id
     WHERE sl.asesor_schema = c.asesor_schema
       AND l.fuente_externa_id = c.codigo_lead
     LIMIT 1)                                   AS lead_id,

    -- Asesor
    (SELECT u.id FROM auth.users u
     WHERE u._deprecated_advisor_schema = c.asesor_schema
     LIMIT 1)                                   AS asesor_id,

    COALESCE(c.tipo_contacto_lead, 'llamada')   AS tipo_contacto,
    COALESCE(c.seguimiento_lead, c.estado_contacto_lead) AS resultado,
    c.observaciones                             AS notas,

    CASE WHEN c.fecha_cita_lead IS NOT NULL AND c.fecha_cita_lead != ''
         THEN c.fecha_cita_lead::TIMESTAMP
         ELSE NULL
    END                                         AS fecha_cita,

    CASE WHEN c.fecha_contacto_lead IS NOT NULL AND c.fecha_contacto_lead != ''
         THEN c.fecha_contacto_lead::TIMESTAMP
         ELSE NOW()
    END                                         AS created_at,

    NOW()                                       AS updated_at

FROM staging_pdr.contactos c
-- Solo insertar contactos que tienen un lead correspondiente en crm.leads
WHERE EXISTS (
    SELECT 1 FROM crm.leads l
    WHERE l.fuente_externa_id = c.codigo_lead
);

DO $$ BEGIN
    RAISE NOTICE '[Paso 3] Contactos migrados: %', (SELECT COUNT(*) FROM crm.contactos);
END; $$;

COMMIT;

-- =============================================================================
-- PASO 4: Verificación final
-- =============================================================================

SELECT
    'crm.leads'    AS tabla,
    COUNT(*)       AS total,
    COUNT(CASE WHEN asesor_id IS NOT NULL THEN 1 END) AS con_asesor,
    COUNT(CASE WHEN asesor_id IS NULL     THEN 1 END) AS sin_asesor
FROM crm.leads
UNION ALL
SELECT
    'crm.contactos',
    COUNT(*),
    COUNT(CASE WHEN lead_id IS NOT NULL THEN 1 END),
    COUNT(CASE WHEN lead_id IS NULL     THEN 1 END)
FROM crm.contactos
UNION ALL
SELECT
    'auth.users (asesores)',
    COUNT(*),
    COUNT(CASE WHEN is_active = TRUE THEN 1 END),
    0
FROM auth.users
WHERE role = 'asesor';

-- =============================================================================
-- PASO 5 (OPCIONAL): Limpiar staging después de verificar
-- Solo ejecutar cuando estés seguro de que la migración es correcta.
-- =============================================================================
-- DROP SCHEMA staging_pdr CASCADE;

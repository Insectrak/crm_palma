-- =============================================================================
-- Migración V009_2: Tabla de registro automático de llamadas desde Android (Resolución de Colisión)
-- Fecha:       2026-06-24
-- Autor:       Antigravity
-- Descripción: Crea crm.llamadas (renombrado de V009 para evitar colisión de nombres en bootstrap)
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS crm.llamadas (
    id                BIGSERIAL    PRIMARY KEY,

    -- Vínculo con el CRM
    lead_id           INTEGER
                      REFERENCES crm.leads(id)
                      ON DELETE SET NULL,
    asesor_id         UUID         NOT NULL
                      REFERENCES auth.users(id)
                      ON DELETE RESTRICT,

    -- Datos de la llamada
    telefono          VARCHAR(30)  NOT NULL,
    duracion_segundos INTEGER      NOT NULL DEFAULT 0,
    tipo              VARCHAR(15)  NOT NULL
                      CHECK (tipo IN ('saliente', 'entrante', 'perdida')),
    fecha_llamada     TIMESTAMPTZ  NOT NULL,

    -- Identidad del registro en el dispositivo
    call_log_id       VARCHAR(100) NOT NULL,
    dispositivo_id    VARCHAR(150),

    -- Datos del contacto en agenda Android
    nombre_contacto   VARCHAR(200),

    -- Control de sincronización
    synced_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT llamadas_asesor_call_log_unico UNIQUE (asesor_id, call_log_id)
);

COMMENT ON TABLE  crm.llamadas                   IS 'Llamadas telefónicas sincronizadas desde la app Android de asesores.';
COMMENT ON COLUMN crm.llamadas.lead_id           IS 'FK a crm.leads. NULL si el teléfono no corresponde a ningún lead conocido.';
COMMENT ON COLUMN crm.llamadas.asesor_id         IS 'FK a auth.users. Asesor propietario del dispositivo Android que hizo la llamada.';
COMMENT ON COLUMN crm.llamadas.telefono          IS 'Número telefónico tal como lo registra el CallLog de Android, sin normalización forzada.';
COMMENT ON COLUMN crm.llamadas.duracion_segundos IS 'Duración efectiva en segundos. 0 para llamadas perdidas o no contestadas.';
COMMENT ON COLUMN crm.llamadas.tipo              IS 'Tipo de llamada: saliente, entrante, perdida.';
COMMENT ON COLUMN crm.llamadas.fecha_llamada     IS 'Timestamp real de la llamada según el reloj del dispositivo Android.';
COMMENT ON COLUMN crm.llamadas.call_log_id       IS '_id del CallLog de Android. Único por dispositivo.';
COMMENT ON COLUMN crm.llamadas.dispositivo_id    IS 'Identificador del dispositivo (ANDROID_ID).';
COMMENT ON COLUMN crm.llamadas.nombre_contacto   IS 'Nombre del contacto en la agenda del dispositivo.';
COMMENT ON COLUMN crm.llamadas.synced_at         IS 'Timestamp de recepción en el servidor.';

CREATE INDEX IF NOT EXISTS idx_llamadas_asesor_id
    ON crm.llamadas (asesor_id);

CREATE INDEX IF NOT EXISTS idx_llamadas_lead_id
    ON crm.llamadas (lead_id)
    WHERE lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_llamadas_fecha
    ON crm.llamadas (fecha_llamada DESC);

CREATE INDEX IF NOT EXISTS idx_llamadas_telefono
    ON crm.llamadas (telefono);

CREATE INDEX IF NOT EXISTS idx_llamadas_asesor_fecha
    ON crm.llamadas (asesor_id, fecha_llamada DESC);

DO $$
DECLARE
    v_tabla_existe   BOOLEAN;
    v_total_indices  INTEGER;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM   information_schema.tables
        WHERE  table_schema = 'crm'
          AND  table_name   = 'llamadas'
    ) INTO v_tabla_existe;

    SELECT COUNT(*)
    FROM   pg_indexes
    WHERE  schemaname = 'crm'
      AND  tablename  = 'llamadas'
    INTO v_total_indices;

    IF NOT v_tabla_existe THEN
        RAISE EXCEPTION 'V009_2: La tabla crm.llamadas NO fue creada correctamente.';
    END IF;
END;
$$;

COMMIT;

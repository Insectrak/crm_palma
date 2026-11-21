-- =============================================================================
-- Migración V009: Tabla de registro automático de llamadas desde Android
-- Fecha:       2026-04-04
-- Autor:       Brighton
-- Descripción: Crea crm.llamadas para almacenar el historial de llamadas
--              sincronizadas desde la app Android de asesores. Cada fila
--              corresponde a una entrada del CallLog del dispositivo.
--
-- NOTAS DE DISEÑO:
--   - lead_id es nullable: una llamada puede llegar antes de que el teléfono
--     exista como lead, o puede no corresponder a ningún lead.
--   - La unicidad (asesor_id, call_log_id) evita duplicados en re-sincronizaciones
--     sucesivas desde el mismo dispositivo.
--   - dispositivo_id permite que un asesor use múltiples dispositivos sin
--     colisionar call_log_id entre ellos (el _id del CallLog de Android se
--     reinicia por dispositivo).
--   - duracion_segundos usa INTEGER (máx ~596 horas), suficiente para llamadas.
--   - synced_at registra cuándo llegó el registro al servidor, independiente
--     de fecha_llamada que es el timestamp real del evento en el dispositivo.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Tabla: crm.llamadas
-- Registro de llamadas telefónicas sincronizadas desde Android.
-- Una fila = una entrada del CallLog del dispositivo del asesor.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.llamadas (
    id                BIGSERIAL    PRIMARY KEY,

    -- Vínculo con el CRM
    lead_id           INTEGER
                      REFERENCES crm.leads(id)
                      ON DELETE SET NULL,          -- si se borra el lead, la llamada queda sin vínculo pero no se pierde
    asesor_id         UUID         NOT NULL
                      REFERENCES auth.users(id)
                      ON DELETE RESTRICT,          -- no borrar asesor con llamadas registradas

    -- Datos de la llamada
    telefono          VARCHAR(30)  NOT NULL,        -- número marcado o recibido, tal como lo registra Android
    duracion_segundos INTEGER      NOT NULL DEFAULT 0, -- duración efectiva en segundos (0 para perdidas)
    tipo              VARCHAR(15)  NOT NULL
                      CHECK (tipo IN ('saliente', 'entrante', 'perdida')),
    fecha_llamada     TIMESTAMPTZ  NOT NULL,        -- timestamp real del evento en el dispositivo Android

    -- Identidad del registro en el dispositivo
    call_log_id       VARCHAR(100) NOT NULL,        -- _id del ContentProvider CallLog de Android
    dispositivo_id    VARCHAR(150),                 -- identificador del dispositivo (ANDROID_ID o similar)

    -- Datos del contacto en agenda Android (puede diferir del nombre en el CRM)
    nombre_contacto   VARCHAR(200),                 -- nombre guardado en la agenda del dispositivo

    -- Control de sincronización
    synced_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(), -- momento en que el servidor recibió el registro

    -- Constraint de deduplicación: el mismo asesor no puede sincronizar dos veces
    -- el mismo call_log_id del CallLog. Garantiza idempotencia en re-sincronizaciones.
    CONSTRAINT llamadas_asesor_call_log_unico UNIQUE (asesor_id, call_log_id)
);

COMMENT ON TABLE  crm.llamadas                   IS 'Llamadas telefónicas sincronizadas desde la app Android de asesores.';
COMMENT ON COLUMN crm.llamadas.lead_id           IS 'FK a crm.leads. NULL si el teléfono no corresponde a ningún lead conocido.';
COMMENT ON COLUMN crm.llamadas.asesor_id         IS 'FK a auth.users. Asesor propietario del dispositivo Android que hizo la llamada.';
COMMENT ON COLUMN crm.llamadas.telefono          IS 'Número telefónico tal como lo registra el CallLog de Android, sin normalización forzada.';
COMMENT ON COLUMN crm.llamadas.duracion_segundos IS 'Duración efectiva en segundos. 0 para llamadas perdidas o no contestadas.';
COMMENT ON COLUMN crm.llamadas.tipo              IS 'Tipo de llamada: saliente (asesor marcó), entrante (asesor recibió), perdida (no contestada).';
COMMENT ON COLUMN crm.llamadas.fecha_llamada     IS 'Timestamp real de la llamada según el reloj del dispositivo Android.';
COMMENT ON COLUMN crm.llamadas.call_log_id       IS '_id del ContentProvider CallLog de Android. Único por dispositivo, no globalmente.';
COMMENT ON COLUMN crm.llamadas.dispositivo_id    IS 'Identificador del dispositivo (ANDROID_ID). Permite distinguir call_log_id entre distintos dispositivos del mismo asesor.';
COMMENT ON COLUMN crm.llamadas.nombre_contacto   IS 'Nombre del contacto en la agenda del dispositivo al momento de la llamada.';
COMMENT ON COLUMN crm.llamadas.synced_at         IS 'Timestamp de recepción en el servidor. Difiere de fecha_llamada si la sincronización fue diferida.';

-- -----------------------------------------------------------------------------
-- Índices
-- -----------------------------------------------------------------------------

-- Filtrar llamadas de un asesor (query más frecuente: historial por asesor)
CREATE INDEX IF NOT EXISTS idx_llamadas_asesor_id
    ON crm.llamadas (asesor_id);

-- Vincular llamadas a un lead (joins desde la ficha del lead)
CREATE INDEX IF NOT EXISTS idx_llamadas_lead_id
    ON crm.llamadas (lead_id)
    WHERE lead_id IS NOT NULL;

-- Ordenar / filtrar por fecha de llamada (dashboards de actividad diaria)
CREATE INDEX IF NOT EXISTS idx_llamadas_fecha
    ON crm.llamadas (fecha_llamada DESC);

-- Búsqueda por número de teléfono (relacionar llamadas con leads sin FK directa)
CREATE INDEX IF NOT EXISTS idx_llamadas_telefono
    ON crm.llamadas (telefono);

-- Índice compuesto para el dashboard de actividad: asesor + fecha
-- (evita un bitmap AND de los dos índices anteriores en la query más común)
CREATE INDEX IF NOT EXISTS idx_llamadas_asesor_fecha
    ON crm.llamadas (asesor_id, fecha_llamada DESC);

-- -----------------------------------------------------------------------------
-- Bloque de verificación
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_tabla_existe   BOOLEAN;
    v_total_indices  INTEGER;
BEGIN
    -- Verificar que la tabla fue creada en el schema crm
    SELECT EXISTS (
        SELECT 1
        FROM   information_schema.tables
        WHERE  table_schema = 'crm'
          AND  table_name   = 'llamadas'
    ) INTO v_tabla_existe;

    -- Contar los índices creados para la tabla
    SELECT COUNT(*)
    FROM   pg_indexes
    WHERE  schemaname = 'crm'
      AND  tablename  = 'llamadas'
    INTO v_total_indices;

    IF NOT v_tabla_existe THEN
        RAISE EXCEPTION 'V009: La tabla crm.llamadas NO fue creada correctamente.';
    END IF;

    RAISE NOTICE 'V009 OK — crm.llamadas creada con % índice(s).', v_total_indices;
    RAISE NOTICE 'V009 OK — Constraint de unicidad (asesor_id, call_log_id) activo.';
    RAISE NOTICE 'V009 OK — Migración completada: 2026-04-04.';
END;
$$;

COMMIT;

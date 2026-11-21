-- =============================================================================
-- Migracion V018: Tabla crm.recordatorios_enviados
-- Fecha:       2026-04-09
-- Autor:       Brighton
-- Descripcion: Registra recordatorios de citas enviados por WhatsApp
--              para evitar duplicados. El workflow n8n consulta citas
--              proximas y solo envia si no existe registro aqui.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS crm.recordatorios_enviados (
    id            SERIAL      PRIMARY KEY,
    contacto_id   INTEGER     NOT NULL
                  REFERENCES crm.contactos(id)
                  ON DELETE CASCADE,
    tipo          TEXT        NOT NULL DEFAULT 'whatsapp_cita',
    enviado_a     TEXT,        -- telefono del asesor al que se envio
    enviado_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Evita enviar el mismo recordatorio dos veces
    CONSTRAINT recordatorios_contacto_tipo_unico UNIQUE (contacto_id, tipo)
);

COMMENT ON TABLE  crm.recordatorios_enviados IS
    'Registro de recordatorios enviados (WhatsApp, email, etc.) para evitar duplicados.';

CREATE INDEX IF NOT EXISTS idx_recordatorios_contacto_id
    ON crm.recordatorios_enviados (contacto_id);

CREATE INDEX IF NOT EXISTS idx_recordatorios_enviado_at
    ON crm.recordatorios_enviados (enviado_at DESC);

COMMIT;

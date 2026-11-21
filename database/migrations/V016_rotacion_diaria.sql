-- =============================================================================
-- V016 — Rotación diaria de leads entrantes (FB / TikTok / WhatsApp)
-- =============================================================================
-- Cada lead que llega via /api/ingest/leads se asigna a un supervisor
-- siguiendo round-robin diario compartido entre todas las fuentes.
-- El contador resetea automaticamente a medianoche America/Lima porque
-- la PK incluye `fecha` (primer lead del dia crea fila desde cero).
-- =============================================================================

BEGIN;

-- Columnas nuevas en auth.users
ALTER TABLE auth.users
    ADD COLUMN IF NOT EXISTS activo_rotacion BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN auth.users.activo_rotacion IS
    'Si FALSE, el supervisor queda temporalmente fuera del round-robin de '
    'ingesta (vacaciones, capacitacion). No afecta login ni otras funciones.';

-- Tabla de rotacion: una fila por (fecha, supervisor)
CREATE TABLE IF NOT EXISTS crm.rotacion_diaria (
    fecha         DATE        NOT NULL,
    supervisor_id UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    contador      INTEGER     NOT NULL DEFAULT 0,
    ultimo_lead_id INTEGER    NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fecha, supervisor_id)
);

COMMENT ON TABLE crm.rotacion_diaria IS
    'Contador diario de leads asignados por supervisor para round-robin en /api/ingest/leads. '
    'El reset diario es automatico gracias a la PK compuesta con fecha.';

CREATE INDEX IF NOT EXISTS idx_rotacion_diaria_fecha
    ON crm.rotacion_diaria (fecha DESC);

COMMIT;

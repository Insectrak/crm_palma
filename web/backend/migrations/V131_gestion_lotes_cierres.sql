-- =============================================================================
-- Migración V131: Gestión de Lotes — Tabla de Cierres + Soporte multi-módulo
--                 (Separaciones y Cierres) con Upload Excel y Sync Drive Git
-- =============================================================================

BEGIN;

-- 1. Etiquetar tablas existentes con columna `modulo` ('separaciones' | 'cierres')
ALTER TABLE crm.separaciones_drive_config
    ADD COLUMN IF NOT EXISTS modulo TEXT NOT NULL DEFAULT 'separaciones';

UPDATE crm.separaciones_drive_config
SET modulo = 'separaciones'
WHERE id = 1;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_separaciones_drive_config_modulo'
    ) THEN
        ALTER TABLE crm.separaciones_drive_config
            ADD CONSTRAINT uq_separaciones_drive_config_modulo UNIQUE (modulo);
    END IF;
END $$;

INSERT INTO crm.separaciones_drive_config (
    id, modulo, spreadsheet_id, gid, sheet_url
)
VALUES (
    2,
    'cierres',
    '1nuHne0EdIiSawpLCJQV3eOpRQ9PVsmnVSuT7EUJfCPg',
    '0',
    'https://docs.google.com/spreadsheets/d/1nuHne0EdIiSawpLCJQV3eOpRQ9PVsmnVSuT7EUJfCPg/edit?gid=0#gid=0'
)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE crm.separaciones_revisions
    ADD COLUMN IF NOT EXISTS modulo TEXT NOT NULL DEFAULT 'separaciones';

-- Permitir source 'excel_upload' en revisiones
ALTER TABLE crm.separaciones_revisions
    DROP CONSTRAINT IF EXISTS separaciones_revisions_source_check;

ALTER TABLE crm.separaciones_revisions
    ADD CONSTRAINT separaciones_revisions_source_check
    CHECK (source IN ('drive_sync', 'crm_manual', 'drive_initial', 'excel_upload'));

CREATE INDEX IF NOT EXISTS idx_separaciones_revisions_modulo_status
    ON crm.separaciones_revisions (modulo, status, created_at DESC);

ALTER TABLE crm.separaciones_audit_log
    ADD COLUMN IF NOT EXISTS modulo TEXT NOT NULL DEFAULT 'separaciones';

-- 2. Tabla dedicada para el Cuadro de Cierre de Ventas (PDR-FO-GC-17)
CREATE TABLE IF NOT EXISTS crm.cierres_lotes_registros (
    id                      BIGSERIAL PRIMARY KEY,
    anio                    INTEGER NOT NULL DEFAULT 2026,
    mes                     INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    mes_nombre              TEXT NOT NULL,
    orden_fila              INTEGER NOT NULL DEFAULT 0,
    sync_key                TEXT,
    asesor                  TEXT,
    proyecto                TEXT,
    lote                    TEXT,
    cliente_nombre          TEXT,
    distrito                TEXT,
    fecha_ingreso_inicial   TEXT,
    fecha_ingreso_date      DATE,
    monto_total             NUMERIC(14, 2),
    moneda                  TEXT NOT NULL DEFAULT 'SOLES',
    pct_inicial             NUMERIC(8, 4),
    pct_inicial_raw         TEXT,
    estrategia              TEXT,
    area                    TEXT,
    edad                    INTEGER,
    cantidad_inicial        NUMERIC(14, 2),
    tipo_cambio             NUMERIC(8, 4),
    observaciones           TEXT,
    origen                  TEXT NOT NULL DEFAULT 'crm' CHECK (origen IN ('drive', 'crm', 'excel')),
    lead_id                 INTEGER REFERENCES crm.leads(id) ON DELETE SET NULL,
    activo                  BOOLEAN NOT NULL DEFAULT TRUE,
    created_by              UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_by              UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- También permitir origen 'excel' en separaciones_registros
ALTER TABLE crm.separaciones_registros
    DROP CONSTRAINT IF EXISTS separaciones_registros_origen_check;

ALTER TABLE crm.separaciones_registros
    ADD CONSTRAINT separaciones_registros_origen_check
    CHECK (origen IN ('drive', 'crm', 'excel'));

ALTER TABLE crm.separaciones_audit_log
    ADD COLUMN IF NOT EXISTS cierre_id BIGINT REFERENCES crm.cierres_lotes_registros(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_cierres_lotes_periodo
    ON crm.cierres_lotes_registros (activo, anio DESC, mes DESC, orden_fila);

CREATE INDEX IF NOT EXISTS idx_cierres_lotes_sync_key
    ON crm.cierres_lotes_registros (sync_key)
    WHERE activo = TRUE AND sync_key IS NOT NULL;

COMMIT;

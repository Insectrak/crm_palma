-- =============================================================================
-- Migración V130: Módulo de Separaciones y Cierres + Sync/Versionado desde Drive
-- =============================================================================
-- Respalda en PostgreSQL toda la estructura de CIERRES PALMA y SEPARACIONES PALMA
-- (hasta ahora llevada en Google Sheets), permitiendo edición directa en el CRM,
-- detección de cambios en el Excel de Drive y aprobación/versionado estilo Git.

BEGIN;

CREATE TABLE IF NOT EXISTS crm.separaciones_registros (
    id                      BIGSERIAL PRIMARY KEY,
    tipo                    TEXT NOT NULL CHECK (tipo IN ('separacion', 'cierre')),
    anio                    INTEGER NOT NULL DEFAULT 2026,
    mes                     INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    mes_nombre              TEXT NOT NULL,
    orden_fila              INTEGER NOT NULL DEFAULT 0,
    sync_key                TEXT,
    asesor                  TEXT,
    proyecto                TEXT,
    lote                    TEXT,
    fecha_ingreso           TEXT,
    fecha_ingreso_date      DATE,
    fecha_vencimiento       TEXT,
    fecha_vencimiento_date  DATE,
    monto_raw               TEXT,
    monto_numerico          NUMERIC(14, 2),
    moneda                  TEXT NOT NULL DEFAULT 'PEN',
    estrategia              TEXT,
    estado                  TEXT,
    observaciones           TEXT,
    origen                  TEXT NOT NULL DEFAULT 'crm' CHECK (origen IN ('drive', 'crm')),
    lead_id                 INTEGER REFERENCES crm.leads(id) ON DELETE SET NULL,
    activo                  BOOLEAN NOT NULL DEFAULT TRUE,
    created_by              UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_by              UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_separaciones_registros_periodo
    ON crm.separaciones_registros (activo, anio DESC, mes DESC, tipo, orden_fila);

CREATE INDEX IF NOT EXISTS idx_separaciones_registros_sync_key
    ON crm.separaciones_registros (sync_key)
    WHERE activo = TRUE AND sync_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS crm.separaciones_drive_config (
    id                  INTEGER PRIMARY KEY,
    spreadsheet_id      TEXT NOT NULL,
    gid                 TEXT NOT NULL DEFAULT '0',
    sheet_url           TEXT NOT NULL,
    last_checked_at     TIMESTAMPTZ,
    last_seen_hash      TEXT,
    last_approved_hash  TEXT,
    last_check_status   TEXT,
    last_check_error    TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO crm.separaciones_drive_config (
    id, spreadsheet_id, gid, sheet_url
)
VALUES (
    1,
    '15ZbIPoJEWAajSUzjajE4350nT6XhjMSW1FqCBk_2Zew',
    '0',
    'https://docs.google.com/spreadsheets/d/15ZbIPoJEWAajSUzjajE4350nT6XhjMSW1FqCBk_2Zew/edit?gid=0#gid=0'
)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS crm.separaciones_revisions (
    id                  BIGSERIAL PRIMARY KEY,
    revision_number     INTEGER NOT NULL,
    source              TEXT NOT NULL CHECK (source IN ('drive_sync', 'crm_manual', 'drive_initial')),
    status              TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'applied')),
    drive_hash          TEXT,
    summary_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    diff_json           JSONB NOT NULL DEFAULT '[]'::jsonb,
    message             TEXT,
    created_by          UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_by_name     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_by         UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    reviewed_by_name    TEXT,
    reviewed_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_separaciones_revisions_status_created
    ON crm.separaciones_revisions (status, created_at DESC);

CREATE TABLE IF NOT EXISTS crm.separaciones_audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    registro_id         BIGINT REFERENCES crm.separaciones_registros(id) ON DELETE SET NULL,
    revision_id         BIGINT REFERENCES crm.separaciones_revisions(id) ON DELETE SET NULL,
    action              TEXT NOT NULL,
    campo               TEXT,
    valor_anterior      TEXT,
    valor_nuevo         TEXT,
    usuario_id          UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    usuario_nombre      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_separaciones_audit_registro
    ON crm.separaciones_audit_log (registro_id, created_at DESC);

COMMIT;

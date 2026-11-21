-- V014 — Historial de cargas masivas de leads
-- Registra cada importación realizada desde la UI de Carga Masiva.

CREATE TABLE IF NOT EXISTS crm.carga_masiva_historial (
    id              BIGSERIAL PRIMARY KEY,
    uploaded_by     UUID        NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    uploaded_by_nombre TEXT     NULL,
    filename        TEXT        NOT NULL,
    total_rows      INTEGER     NOT NULL DEFAULT 0,
    inserted        INTEGER     NOT NULL DEFAULT 0,
    duplicates      INTEGER     NOT NULL DEFAULT 0,
    errors          INTEGER     NOT NULL DEFAULT 0,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_carga_masiva_historial_uploaded_at
    ON crm.carga_masiva_historial (uploaded_at DESC);

CREATE INDEX IF NOT EXISTS idx_carga_masiva_historial_uploaded_by
    ON crm.carga_masiva_historial (uploaded_by);

-- V105 — Página de gestión de Históricos (solo Admin) y soporte de reasignación
--
-- Requerimientos:
-- 1. Agregar columna asesor_id en crm_legacy.leads_historico referenciando auth.users.
-- 2. Asegurar índices para fecha_ingreso y asesor_id en crm_legacy.leads_historico.

CREATE SCHEMA IF NOT EXISTS crm_legacy;

CREATE TABLE IF NOT EXISTS crm_legacy.leads_historico (
    id             BIGSERIAL PRIMARY KEY,
    telefono       TEXT,
    telefono_norm  TEXT,
    nombre         TEXT,
    email          TEXT,
    dni            TEXT,
    proyecto       TEXT,
    canal          TEXT,
    asesor_id      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    asesor_nombre  TEXT,
    estado         TEXT,
    seguimiento    TEXT,
    observaciones  TEXT,
    ciudad         TEXT,
    fecha_ingreso  DATE,
    origen_tabla   TEXT NOT NULL DEFAULT 'manual',
    migrado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Si la tabla ya existía, añadir columna asesor_id de forma segura
ALTER TABLE crm_legacy.leads_historico
    ADD COLUMN IF NOT EXISTS asesor_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE crm_legacy.leads_historico
    ADD COLUMN IF NOT EXISTS ciudad TEXT;

ALTER TABLE crm_legacy.leads_historico
    ADD COLUMN IF NOT EXISTS fecha_creacion DATE;

ALTER TABLE crm_legacy.leads_historico
    ADD COLUMN IF NOT EXISTS fecha_asignacion DATE;

ALTER TABLE crm_legacy.leads_historico
    ADD COLUMN IF NOT EXISTS fecha_ultimo_contacto DATE;

ALTER TABLE crm_legacy.leads_historico
    ADD COLUMN IF NOT EXISTS lead_crm_id INT REFERENCES crm.leads(id) ON DELETE SET NULL;

-- Índices optimizados
CREATE INDEX IF NOT EXISTS idx_leads_historico_tel_norm
    ON crm_legacy.leads_historico (telefono_norm);

CREATE INDEX IF NOT EXISTS idx_leads_historico_dni
    ON crm_legacy.leads_historico (dni);

CREATE INDEX IF NOT EXISTS idx_leads_historico_fecha_ingreso
    ON crm_legacy.leads_historico (fecha_ingreso DESC);

CREATE INDEX IF NOT EXISTS idx_leads_historico_fecha_creacion
    ON crm_legacy.leads_historico (fecha_creacion DESC);

CREATE INDEX IF NOT EXISTS idx_leads_historico_asesor_id
    ON crm_legacy.leads_historico (asesor_id);


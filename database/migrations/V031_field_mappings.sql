-- V031 — Field Mappings & Custom Properties (estilo HubSpot / Salesforce).
--
-- Contexto:
--   Hoy los formularios de Meta Lead Ads traen campos custom (ej.
--   "proyecto_interes", "presupuesto", "cuando_comprar") que caen como
--   texto libre en `crm.leads.observaciones`. Esto los hace ilegibles y
--   no-filtrables en reportes.
--
--   HubSpot y Salesforce resuelven esto con 3 capas:
--     1) Catálogo de "propiedades custom" tipadas creables por admin.
--     2) Mapeo visual: "form field X → propiedad Y" (o columna nativa).
--     3) Storage EAV de valores por registro, filtrable en reportes.
--
-- Diseño:
--   crm.property_definitions   — catálogo tipado (display, tipo, opciones).
--   crm.form_field_mappings    — regla "meta_field → target" por formulario.
--   crm.lead_properties        — EAV key/value por lead.
--
-- Se aplica también via bootstrap.ensure_field_mappings_schema().

-- ─────────────────────────────────────────────────────────────────────────
-- Catálogo de propiedades custom
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.property_definitions (
    id              BIGSERIAL PRIMARY KEY,
    property_key    TEXT        NOT NULL UNIQUE,
    display_name    TEXT        NOT NULL,
    property_type   TEXT        NOT NULL DEFAULT 'text'
                     CHECK (property_type IN ('text', 'number', 'date', 'boolean', 'select')),
    options         JSONB,              -- lista de opciones para type='select'
    description     TEXT,
    category        TEXT,               -- agrupador visual ("Comercial", "Personal"…)
    icon            TEXT,               -- nombre del icono lucide (opcional)
    is_system       BOOLEAN     NOT NULL DEFAULT FALSE,   -- built-in, no borrable
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_property_definitions_category
    ON crm.property_definitions (category) WHERE is_active = TRUE;

COMMENT ON TABLE  crm.property_definitions IS
    'Catálogo de propiedades custom de leads, estilo HubSpot properties. Los valores viven en crm.lead_properties.';
COMMENT ON COLUMN crm.property_definitions.property_key IS
    'Slug estable (snake_case). Se usa como key en crm.lead_properties.';

-- ─────────────────────────────────────────────────────────────────────────
-- Mapeo de campos de formularios externos → target (columna o propiedad)
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.form_field_mappings (
    id                BIGSERIAL PRIMARY KEY,
    provider          TEXT    NOT NULL DEFAULT 'meta',
    form_id           TEXT    NOT NULL,                  -- form_id exacto o '_any_' (wildcard)
    meta_field_name   TEXT    NOT NULL,                  -- lowercased
    target_type       TEXT    NOT NULL CHECK (target_type IN ('column', 'property', 'ignore')),
    target_key        TEXT,                              -- columna de crm.leads o property_key
    created_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_form_field_mapping UNIQUE (provider, form_id, meta_field_name),
    CONSTRAINT ck_form_field_mapping_target
        CHECK (
            (target_type = 'ignore'  AND target_key IS NULL) OR
            (target_type <> 'ignore' AND target_key IS NOT NULL AND length(btrim(target_key)) > 0)
        )
);

CREATE INDEX IF NOT EXISTS idx_form_field_mappings_lookup
    ON crm.form_field_mappings (provider, form_id, meta_field_name);

COMMENT ON TABLE  crm.form_field_mappings IS
    'Regla "meta_field_name → target" aplicada durante la ingesta. form_id=_any_ actúa como wildcard.';

-- ─────────────────────────────────────────────────────────────────────────
-- Storage EAV de valores custom por lead
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.lead_properties (
    id              BIGSERIAL PRIMARY KEY,
    lead_id         BIGINT      NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    property_key    TEXT        NOT NULL,
    property_value  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lead_property UNIQUE (lead_id, property_key)
);

CREATE INDEX IF NOT EXISTS idx_lead_properties_key_value
    ON crm.lead_properties (property_key, property_value);
CREATE INDEX IF NOT EXISTS idx_lead_properties_lead
    ON crm.lead_properties (lead_id);

COMMENT ON TABLE  crm.lead_properties IS
    'Valores de propiedades custom por lead. Un lead puede tener 0..N propiedades. Filtrable en reportes.';

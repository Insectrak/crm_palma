-- ============================================================================
-- V082 — Sharing Rules para roles custom (ADR-0012)
--
-- Patrón inspirado en Salesforce Sharing Rules / HubSpot Shared Views:
-- el admin define una regla "Los leads con fuente=X (o estado=Y, sede=Z)
-- se comparten con el rol R con permiso P". Cuando un usuario con rol custom
-- abre /leads, el backend extiende el WHERE de su filtro normal con las
-- reglas activas que matchean su rol — así ve un subset curado por el admin,
-- no solo los leads que tiene asignados.
--
-- Por qué este patrón en lugar de role_id directo en leads:
--   - Las reglas son DECLARATIVAS: el admin no asigna leads uno por uno,
--     define el criterio y se aplica en runtime a todos los leads que
--     matcheen (presentes y futuros). Igual que sharing rules de Salesforce.
--   - Si cambia el criterio (ej. "ahora marketing también ve Instagram"),
--     se edita la regla y aplica automáticamente sin tocar leads.
-- ============================================================================

CREATE TABLE IF NOT EXISTS crm.lead_sharing_rules (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    role_id       INTEGER NOT NULL REFERENCES auth.roles(id) ON DELETE CASCADE,
    -- Filtro JSONB con la convención del CRM:
    --   { "fuente_ids": [1, 2], "estado_ids": [3], "sede_ids": [], "calidad": ["alta", "media"] }
    -- Cada clave es una whitelist (IN). null/missing significa "sin restricción".
    -- Lista vacía significa "ninguno" (efectivamente desactiva ese filtro).
    -- El servicio traduce este JSONB a un WHERE SQL parametrizado.
    filter_jsonb  JSONB NOT NULL DEFAULT '{}'::jsonb,
    can_view      BOOLEAN NOT NULL DEFAULT TRUE,
    can_edit      BOOLEAN NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    UUID REFERENCES auth.users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_lead_sharing_rules_role_id ON crm.lead_sharing_rules (role_id);
CREATE INDEX IF NOT EXISTS ix_lead_sharing_rules_active ON crm.lead_sharing_rules (is_active);

-- Trigger updated_at idempotente
CREATE OR REPLACE FUNCTION crm.lead_sharing_rules_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_lead_sharing_rules_updated_at ON crm.lead_sharing_rules;
CREATE TRIGGER trg_lead_sharing_rules_updated_at
    BEFORE UPDATE ON crm.lead_sharing_rules
    FOR EACH ROW EXECUTE FUNCTION crm.lead_sharing_rules_set_updated_at();

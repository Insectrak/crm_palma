-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V067 — Sistema de deduplicacion world-class (Salesforce/HubSpot style) ║
-- ║                                                                        ║
-- ║ Patron HubSpot "Manage duplicates" + Salesforce "Duplicate Management":║
-- ║                                                                        ║
-- ║ 1) PREVENCION — el frontend chequea via /api/leads/check-duplicate     ║
-- ║    antes de submit. UI muestra warning "ya existe lead con este        ║
-- ║    telefono — [Ver lead] [Crear de todos modos]".                      ║
-- ║                                                                        ║
-- ║ 2) DEFENSA BACKEND — POST /api/leads devuelve 409 con info del         ║
-- ║    existente. Override explicito via ?allow_duplicate=true + reason.   ║
-- ║                                                                        ║
-- ║ 3) RECAPTURE — Forms publicos llaman a lead_recapture (igual que API). ║
-- ║                                                                        ║
-- ║ 4) MERGE TOOL — admin combina dos leads en uno preservando historial. ║
-- ║    secondary queda con merged_into=master_id, NO se borra (auditoria). ║
-- ║                                                                        ║
-- ║ Esta migracion solo agrega COLUMNAS y la TABLA de audit de merges.    ║
-- ║ La logica de routers/services llega en commits posteriores.            ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── crm.leads: tracking de override y merge ────────────────────────────

-- Si el lead se creo con override de duplicado (Salesforce "Save Anyway"),
-- guardamos la razon para audit. Default NULL = lead creado normalmente.
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS created_with_duplicate_override BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS duplicate_override_reason VARCHAR(255);

COMMENT ON COLUMN crm.leads.created_with_duplicate_override IS
    'V067: TRUE si el lead se creo manualmente aunque ya existia otro con el mismo telefono/email. Patron Salesforce "Allow user to save duplicate".';
COMMENT ON COLUMN crm.leads.duplicate_override_reason IS
    'V067: razon opcional que dio el user al crear con override (ej: "es la esposa, mismo telefono casa pero lead distinto").';

-- Cuando un lead se mergea como SECONDARY hacia un master, queda apuntando
-- al master. activo=FALSE para que el role_filter no lo devuelva en queries
-- normales, pero queda en DB para reportes historicos.
-- NOTA: crm.leads.id es SERIAL (INTEGER) — merged_into debe matchear el tipo.
-- Una version previa de V067 declaro UUID por error y la migracion fallaba
-- silenciosamente en el migrator (FK type mismatch), dejando todas las
-- columnas sin aplicar. Fix: usar INTEGER.
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS merged_into INTEGER REFERENCES crm.leads(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS merged_at TIMESTAMPTZ;

COMMENT ON COLUMN crm.leads.merged_into IS
    'V067: si este lead fue mergeado como secondary, apunta al master. NULL = lead independiente.';

-- Index para buscar todos los secondaries de un master (para mostrar historial)
CREATE INDEX IF NOT EXISTS idx_leads_merged_into
    ON crm.leads (merged_into)
    WHERE merged_into IS NOT NULL;

-- Index para acelerar el check-duplicate por telefono (dedupe es la query
-- mas frecuente del flujo de creacion manual).
CREATE INDEX IF NOT EXISTS idx_leads_telefono_activo
    ON crm.leads (telefono)
    WHERE activo = TRUE AND merged_into IS NULL;

-- Indice por email tambien (segundo eje del matching rule).
CREATE INDEX IF NOT EXISTS idx_leads_email_activo
    ON crm.leads (LOWER(email))
    WHERE email IS NOT NULL AND activo = TRUE AND merged_into IS NULL;


-- ── crm.lead_merges: audit log de fusiones ─────────────────────────────

CREATE TABLE IF NOT EXISTS crm.lead_merges (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    master_id       BIGINT       NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    secondary_id    BIGINT       NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    merged_by       UUID         NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    merged_by_name  VARCHAR(180),  -- snapshot del nombre por si el user se borra
    merged_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Decisiones campo por campo: qué se conservó del secondary, qué del master.
    -- Estructura: {"nombres": "master", "email": "secondary", ...}
    field_decisions JSONB        NOT NULL DEFAULT '{}'::jsonb,

    -- Conteos para reportes (cuanto se preservo al unir).
    contactos_migrated  INTEGER  NOT NULL DEFAULT 0,
    llamadas_migrated   INTEGER  NOT NULL DEFAULT 0,
    eventos_migrated    INTEGER  NOT NULL DEFAULT 0,

    -- Snapshot del secondary completo al momento de merge — por si el admin
    -- quiere revertir o auditar valores que no se conservaron.
    secondary_snapshot  JSONB    NOT NULL DEFAULT '{}'::jsonb,

    notes               TEXT     -- razon o nota libre del admin

    -- NOTA: NO usamos UNIQUE (master_id, secondary_id) porque en teoria
    -- podrias mergear el mismo par dos veces (caso muy edge: deshacer +
    -- volver a mergear). El audit log preserva ambos eventos.
);

COMMENT ON TABLE crm.lead_merges IS
    'V067: audit log de fusiones de leads duplicados. Cada fila = un merge ejecutado por admin.';

CREATE INDEX IF NOT EXISTS idx_lead_merges_master
    ON crm.lead_merges (master_id, merged_at DESC);
CREATE INDEX IF NOT EXISTS idx_lead_merges_secondary
    ON crm.lead_merges (secondary_id);

COMMIT;

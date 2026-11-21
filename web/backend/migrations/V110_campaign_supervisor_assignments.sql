-- ║ V110 — Asignación de supervisores por campaña publicitaria (Meta / TikTok) ║
-- ║ Permite extraer campañas activas e inactivas de Meta y TikTok y designar  ║
-- ║ un supervisor exclusivo para los leads de cada campaña.                   ║

CREATE TABLE IF NOT EXISTS crm.campaign_supervisor_assignments (
    id              BIGSERIAL PRIMARY KEY,
    provider        VARCHAR(30) NOT NULL CHECK (provider IN ('meta', 'tiktok', 'general')),
    campaign_id     VARCHAR(255) NOT NULL,
    campaign_name   VARCHAR(255),
    account_id      VARCHAR(255),
    status          VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
    objective       VARCHAR(100),
    supervisor_id   UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    CONSTRAINT uq_campaign_provider_id UNIQUE (provider, campaign_id)
);

CREATE INDEX IF NOT EXISTS idx_camp_assignments_sup
    ON crm.campaign_supervisor_assignments (supervisor_id)
    WHERE supervisor_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_camp_assignments_prov_stat
    ON crm.campaign_supervisor_assignments (provider, status);

CREATE INDEX IF NOT EXISTS idx_camp_assignments_name
    ON crm.campaign_supervisor_assignments (LOWER(campaign_name));

DROP TRIGGER IF EXISTS trg_campaign_supervisor_assignments_updated_at ON crm.campaign_supervisor_assignments;
CREATE TRIGGER trg_campaign_supervisor_assignments_updated_at
    BEFORE UPDATE ON crm.campaign_supervisor_assignments
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

COMMENT ON TABLE crm.campaign_supervisor_assignments IS
    'Mapeo de campañas de Meta y TikTok a supervisores designados para enrutamiento exclusivo de leads.';

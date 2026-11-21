-- ║ V114 — Multi-Supervisor y Reparto Equitativo por Campaña Publicitaria             ║
-- ║ Permite designar más de un supervisor por campaña de Meta/TikTok/General.       ║
-- ║ Modo 'supervisor': reparte equitativamente entre los supervisores designados.  ║
-- ║ Modo 'equipo': reparte equitativamente alternando entre equipos y miembros.     ║

CREATE TABLE IF NOT EXISTS crm.campaign_assigned_supervisors (
    id                  BIGSERIAL PRIMARY KEY,
    assignment_id       BIGINT NOT NULL REFERENCES crm.campaign_supervisor_assignments(id) ON DELETE CASCADE,
    supervisor_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    last_assigned_at    TIMESTAMPTZ DEFAULT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_campaign_assigned_supervisor UNIQUE (assignment_id, supervisor_id)
);

CREATE INDEX IF NOT EXISTS idx_camp_assigned_sups_assign
    ON crm.campaign_assigned_supervisors (assignment_id);

CREATE INDEX IF NOT EXISTS idx_camp_assigned_sups_sup
    ON crm.campaign_assigned_supervisors (supervisor_id);

CREATE INDEX IF NOT EXISTS idx_camp_assigned_sups_rot
    ON crm.campaign_assigned_supervisors (assignment_id, last_assigned_at NULLS FIRST);

-- Migración / Backfill de asignaciones existentes
INSERT INTO crm.campaign_assigned_supervisors (assignment_id, supervisor_id, created_at)
SELECT c.id, c.supervisor_id, NOW()
FROM crm.campaign_supervisor_assignments c
JOIN auth.users u ON u.id = c.supervisor_id
WHERE c.supervisor_id IS NOT NULL
ON CONFLICT (assignment_id, supervisor_id) DO NOTHING;

COMMENT ON TABLE crm.campaign_assigned_supervisors IS
    'Mapeo de múltiples supervisores designados por campaña y registro de último lead asignado para rotación equitativa.';

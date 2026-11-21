-- ║ V122 — Reparto Personalizado por Equipo y Modo "A Todos" (Supervisor + Equipo) ║
-- ║ 1. Añade soporte para el modo 'todos' en campañas publicitarias               ║
-- ║ 2. Permite configurar modo de reparto individualizado a cada equipo          ║
-- ║ 3. Permite configurar porcentajes de reparto para los integrantes del equipo  ║

ALTER TABLE crm.campaign_supervisor_assignments
    DROP CONSTRAINT IF EXISTS campaign_supervisor_assignments_distribution_mode_check,
    DROP CONSTRAINT IF EXISTS chk_campaign_distribution_mode;

ALTER TABLE crm.campaign_supervisor_assignments
    ADD CONSTRAINT chk_campaign_distribution_mode
    CHECK (distribution_mode IN ('supervisor', 'equipo', 'todos'));

ALTER TABLE crm.campaign_assigned_supervisors
    ADD COLUMN IF NOT EXISTS distribution_mode VARCHAR(30) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS member_percentages JSONB DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS member_counts JSONB DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS member_last_assigned JSONB DEFAULT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_cas_distribution_mode'
    ) THEN
        ALTER TABLE crm.campaign_assigned_supervisors
            ADD CONSTRAINT chk_cas_distribution_mode
            CHECK (distribution_mode IS NULL OR distribution_mode IN ('supervisor', 'equipo', 'todos'));
    END IF;
END $$;

COMMENT ON COLUMN crm.campaign_assigned_supervisors.distribution_mode IS
    'Modo de reparto específico para este equipo (supervisor, equipo, todos). NULL hereda el modo general de la campaña.';

COMMENT ON COLUMN crm.campaign_assigned_supervisors.member_percentages IS
    'Mapeo de UUID de integrante (asesor o supervisor) a porcentaje (0-100). NULL para rotación equitativa.';

COMMENT ON COLUMN crm.campaign_assigned_supervisors.member_counts IS
    'Contadores de leads asignados a cada integrante para Weighted Fair Queuing.';

COMMENT ON COLUMN crm.campaign_assigned_supervisors.member_last_assigned IS
    'Timestamps de última asignación por integrante del equipo.';

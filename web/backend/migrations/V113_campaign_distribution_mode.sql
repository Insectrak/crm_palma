-- ║ V113 — Modo de Asignación por Campaña: Directo al Supervisor vs Reparto en Equipo ║
-- ║ Añade la columna distribution_mode a crm.campaign_supervisor_assignments        ║
-- ║ 'supervisor': El lead se asigna directamente a la bandeja del supervisor.        ║
-- ║ 'equipo': El lead se reparte equitativamente entre los asesores de su equipo.    ║

ALTER TABLE crm.campaign_supervisor_assignments
    ADD COLUMN IF NOT EXISTS distribution_mode VARCHAR(30) NOT NULL DEFAULT 'supervisor';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_campaign_distribution_mode'
    ) THEN
        ALTER TABLE crm.campaign_supervisor_assignments
            ADD CONSTRAINT chk_campaign_distribution_mode
            CHECK (distribution_mode IN ('supervisor', 'equipo'));
    END IF;
END $$;

COMMENT ON COLUMN crm.campaign_supervisor_assignments.distribution_mode IS
    'Modo de entrega para leads de la campaña: supervisor (directo) o equipo (reparto round-robin entre asesores del supervisor).';

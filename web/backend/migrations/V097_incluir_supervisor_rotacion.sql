-- V097: Incluir supervisor en rotación de auto-asignación

ALTER TABLE crm.assignment_config
    ADD COLUMN IF NOT EXISTS incluir_supervisor_en_rotacion BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN crm.assignment_config.incluir_supervisor_en_rotacion IS
    'Si es TRUE, el supervisor se incluye como candidato en el round-robin del equipo junto a los asesores.';

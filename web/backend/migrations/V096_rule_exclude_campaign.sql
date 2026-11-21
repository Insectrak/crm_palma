-- ║ V096 — Patrón de Exclusión de Campaña y Fix VARCHAR en Reglas             ║

ALTER TABLE crm.lead_assignment_rules
ADD COLUMN IF NOT EXISTS campana_exclude_pattern VARCHAR(200);

-- V096.1 — Ampliar `asignar_a_tipo` de VARCHAR(20) a VARCHAR(50) para dar cabida
-- a 'asesor_round_robin_global' (25 caracteres).
ALTER TABLE crm.lead_assignment_rules
ALTER COLUMN asignar_a_tipo TYPE VARCHAR(50);

COMMENT ON COLUMN crm.lead_assignment_rules.campana_exclude_pattern IS
    'Patrón LIKE a excluir (ej. %presencial%). Si el lead coincide con este patrón, la regla NO aplica.';

-- ║ V121 — Reparto Personalizado por Porcentajes en Campañas Publicitarias     ║
-- ║ Permite definir porcentajes personalizados por supervisor/equipo          ║
-- ║ (ej. 10% a un equipo y 45%/45% a los otros) con conteo para rotación fair. ║

ALTER TABLE crm.campaign_assigned_supervisors
    ADD COLUMN IF NOT EXISTS porcentaje INT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS assigned_count INT NOT NULL DEFAULT 0;

COMMENT ON COLUMN crm.campaign_assigned_supervisors.porcentaje IS
    'Porcentaje asignado de leads (0-100). NULL indica reparto equitativo automático.';

COMMENT ON COLUMN crm.campaign_assigned_supervisors.assigned_count IS
    'Contador de leads asignados a este supervisor para cálculo ponderado de cuotas.';

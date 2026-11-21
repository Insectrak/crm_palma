-- V107 — Catálogo de fuentes: Agregar 'Historico'
-- Garantiza que los leads promovidos/reasignados desde crm_legacy.leads_historico tengan la fuente 'Historico'.

BEGIN;

CREATE TABLE IF NOT EXISTS crm.fuentes (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    activo  BOOLEAN DEFAULT TRUE
);

INSERT INTO crm.fuentes (nombre, activo) VALUES
    ('Historico', TRUE)
ON CONFLICT (nombre) DO UPDATE SET activo = TRUE;

-- Regularizar leads que fueron creados desde histórico y tienen lead_crm_id vinculado
UPDATE crm.leads
SET fuente_id = (SELECT id FROM crm.fuentes WHERE LOWER(nombre) IN ('historico', 'histórico') LIMIT 1),
    updated_at = NOW()
WHERE id IN (
    SELECT lead_crm_id FROM crm_legacy.leads_historico WHERE lead_crm_id IS NOT NULL
) AND (fuente_id IS NULL OR fuente_id NOT IN (
    SELECT id FROM crm.fuentes WHERE LOWER(nombre) IN ('historico', 'histórico')
));

COMMIT;

-- =============================================================================
-- Migración V008: Leads referidos + columna referido_por
-- Fecha:       2026-04-04
-- Autor:       Brighton
-- =============================================================================

BEGIN;

-- Campo para guardar quién refirió al lead
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS referido_por TEXT;
COMMENT ON COLUMN crm.leads.referido_por IS
    'Nombre/datos de la persona que refirió al lead (solo cuando fuente = referido).';

-- Fuente "referido" en el catálogo
INSERT INTO crm.fuentes (nombre, activo)
VALUES ('referido', TRUE)
ON CONFLICT (nombre) DO NOTHING;

COMMIT;

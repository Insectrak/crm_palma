-- =============================================================================
-- Migración V127: Mejoras al sistema de fusión de leads duplicados
-- Fecha:       2026-11-05
-- Descripción: Agrega soporte para:
--              1. Snapshot del lead master y registro de dueño con autoridad
--                 en crm.lead_merges.
--              2. Tracking de leads fusionados (has_merged_leads, merged_count)
--                 en crm.leads.
--              3. Columna datos_extra (JSONB) en crm.lead_historial_cambios
--                 para auditoría con metadatos estructurados (resumen de leads,
--                 dueño elegido, registros migrados).
-- =============================================================================

BEGIN;

-- 1. Ampliar crm.lead_merges con snapshot del master y dueño con autoridad
ALTER TABLE crm.lead_merges
    ADD COLUMN IF NOT EXISTS master_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS chosen_owner_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS chosen_owner_name VARCHAR(180);

COMMENT ON COLUMN crm.lead_merges.master_snapshot IS
    'V127: snapshot completo del lead master antes de la fusión para auditoría comparativa.';
COMMENT ON COLUMN crm.lead_merges.chosen_owner_id IS
    'V127: asesor/usuario elegido para regir y tener autoridad sobre el lead resultante.';
COMMENT ON COLUMN crm.lead_merges.chosen_owner_name IS
    'V127: snapshot del nombre del asesor/dueño con autoridad elegido al momento de la fusión.';

-- 2. Flags en crm.leads para identificar leads que han absorbido otros
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS has_merged_leads BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS merged_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN crm.leads.has_merged_leads IS
    'V127: TRUE si este lead ha sido el master de una o más fusiones de leads duplicados.';
COMMENT ON COLUMN crm.leads.merged_count IS
    'V127: cantidad de leads secundarios que han sido absorbidos en este lead.';

CREATE INDEX IF NOT EXISTS idx_leads_has_merged_leads
    ON crm.leads (has_merged_leads)
    WHERE has_merged_leads = TRUE;

-- 3. Columna datos_extra en crm.lead_historial_cambios para metadatos estructurados
ALTER TABLE crm.lead_historial_cambios
    ADD COLUMN IF NOT EXISTS datos_extra JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN crm.lead_historial_cambios.datos_extra IS
    'V127: metadatos estructurados para eventos especiales de auditoría (ej: resumen previo de leads fusionados).';

CREATE INDEX IF NOT EXISTS idx_lead_historial_cambios_origen
    ON crm.lead_historial_cambios (lead_id, origen);

COMMIT;


-- V106 — Añadir sede_id a crm.lotes_reciclaje si no existe
-- Permite vincular los lotes de reciclaje de Telemarketing a una sede específica.

BEGIN;

ALTER TABLE crm.lotes_reciclaje
    ADD COLUMN IF NOT EXISTS sede_id UUID REFERENCES crm.sedes(id) ON DELETE SET NULL;

COMMENT ON COLUMN crm.lotes_reciclaje.sede_id IS 'Sede filtrada al momento de generar el lote de reciclaje (opcional).';

COMMIT;

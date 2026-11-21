-- V108 — Detalle de Duplicados y Errores en Historial de Cargas Masivas
-- Permite almacenar la lista estructurada de leads duplicados y filas con error para consulta interactiva.

BEGIN;

-- 1. Agregar columnas jsonb a crm.carga_masiva_historial (Carga Masiva Estándar)
ALTER TABLE crm.carga_masiva_historial
    ADD COLUMN IF NOT EXISTS duplicates_details JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS error_details JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN crm.carga_masiva_historial.duplicates_details IS 'Array JSON con el detalle de filas duplicadas (en archivo o en CRM) de la carga.';
COMMENT ON COLUMN crm.carga_masiva_historial.error_details IS 'Array JSON con el detalle de filas con error de validación o inserción de la carga.';

-- 2. Agregar columnas jsonb a crm_legacy.cargas_historico_historial (Carga Masiva Históricos)
-- En fresh installs esta tabla se crea lazy desde /api/historicos (con estas columnas ya incluidas),
-- así que solo alteramos si la tabla ya existe.
DO $$
BEGIN
    IF to_regclass('crm_legacy.cargas_historico_historial') IS NOT NULL THEN
        ALTER TABLE crm_legacy.cargas_historico_historial
            ADD COLUMN IF NOT EXISTS duplicates_details JSONB DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS error_details JSONB DEFAULT '[]'::jsonb;

        COMMENT ON COLUMN crm_legacy.cargas_historico_historial.duplicates_details IS 'Array JSON con el detalle de filas duplicadas (en archivo, CRM o Histórico) de la carga.';
        COMMENT ON COLUMN crm_legacy.cargas_historico_historial.error_details IS 'Array JSON con el detalle de filas con error de la carga.';
    END IF;
END $$;

COMMIT;

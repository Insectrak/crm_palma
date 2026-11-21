-- ============================================================================
-- V091 — Tracking de leads heredados tras una reasignación masiva.
--
-- Caso de uso (pedido por el admin de Palma): cuando Fernando se va y sus
-- 47 leads pasan a la cola de Paola, ésta debe poder saber de quién venían
-- esos leads para conservar el contexto comercial sin tener que abrir el
-- audit log.
--
-- Patrón estándar de la industria (Salesforce "Lead History" / HubSpot
-- "Last Contact Owner"): la card del lead muestra un badge sutil
-- "Heredado de Fernando · hace 3 días" durante los primeros 30 días
-- después de la reasignación. Pasados los 30 días el badge desaparece
-- solo — el lead se considera "asimilado" por el nuevo dueño.
--
-- Columnas nuevas (todas nullable, backward-compat):
--   previous_asesor_id  → quién tenía el lead antes de la reasignación
--   reassigned_at       → timestamp de la reasignación
--
-- Multi-tenant safe: idempotente vía IF NOT EXISTS.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'crm' AND table_name = 'leads'
           AND column_name = 'previous_asesor_id'
    ) THEN
        ALTER TABLE crm.leads
            ADD COLUMN previous_asesor_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL;
        RAISE NOTICE '[V091] crm.leads.previous_asesor_id agregado';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'crm' AND table_name = 'leads'
           AND column_name = 'reassigned_at'
    ) THEN
        ALTER TABLE crm.leads
            ADD COLUMN reassigned_at TIMESTAMPTZ NULL;
        RAISE NOTICE '[V091] crm.leads.reassigned_at agregado';
    END IF;
END $$;

-- Índice parcial: solo para filas con reassigned_at no nulo. Sirve para
-- reportes tipo "leads heredados en los últimos 30 días por supervisor"
-- sin escanear toda la tabla.
CREATE INDEX IF NOT EXISTS ix_leads_reassigned_at
    ON crm.leads (reassigned_at DESC)
    WHERE reassigned_at IS NOT NULL;

-- =============================================================================
-- Migración V013: Columna origen en crm.contactos
-- Fecha:  2026-04-05
-- Autor:       Brighton
--
-- PROPÓSITO:
--   Agrega columna `origen` a crm.contactos para identificar de dónde vino
--   cada registro. Permite que la migración desde pdr_marketing sea idempotente
--   (se puede volver a correr sin duplicar datos).
--
-- VALORES POSIBLES:
--   'crm'            → creado desde el CRM directamente
--   'pdr_migration'  → migrado desde pdr_marketing en la migración inicial
-- =============================================================================

BEGIN;

ALTER TABLE crm.contactos
    ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'crm';

-- Marcar los contactos ya migrados (asesor_id NULL + fecha anterior a hoy)
-- como pdr_migration para que no se dupliquen en futuros re-runs
UPDATE crm.contactos
SET origen = 'pdr_migration'
WHERE asesor_id IS NULL
  AND created_at < NOW();

COMMIT;

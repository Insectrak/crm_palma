-- =============================================================================
-- Migración V010: Agregar canales digitales a crm.fuentes
-- Fecha:  2026-04-05
-- Autor:       Brighton
--
-- Objetivo:
--   1. Añadir los canales de captación reales usados en Palma Río.
--   2. Auto-mapear leads existentes cuyo campo `campana` coincida
--      exactamente con el nombre de la fuente (case-insensitive).
-- =============================================================================

BEGIN;

-- 1. Insertar (o reactivar) los canales de captación específicos
INSERT INTO crm.fuentes (nombre, activo) VALUES
    ('wa mensaje',  TRUE),   -- WhatsApp — lead que respondió a un mensaje
    ('fb mensaje',  TRUE),   -- Facebook — lead que respondió a un mensaje
    ('ig mensaje',  TRUE),   -- Instagram — lead que respondió a un mensaje
    ('tt mensaje',  TRUE),   -- TikTok — lead que respondió a un mensaje
    ('fb',          TRUE),   -- Facebook Lead Ads / orgánico
    ('ig',          TRUE)    -- Instagram Lead Ads / orgánico
ON CONFLICT (nombre) DO UPDATE
    SET activo = TRUE;

-- 2. Intentar mapear fuente_id en leads existentes donde campana coincida
--    con el nombre de alguna fuente (sin distinguir mayúsculas ni espacios extra)
UPDATE crm.leads l
SET
    fuente_id  = f.id,
    updated_at = NOW()
FROM crm.fuentes f
WHERE LOWER(TRIM(l.campana)) = LOWER(f.nombre)
  AND (l.fuente_id IS NULL OR l.fuente_id IS DISTINCT FROM f.id)
  AND l.activo = TRUE;

COMMIT;

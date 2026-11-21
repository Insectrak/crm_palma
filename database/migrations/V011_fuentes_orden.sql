-- =============================================================================
-- Migración V011: Columna orden en crm.fuentes
-- Fecha:  2026-04-05
-- Autor:       Brighton
-- =============================================================================

BEGIN;

ALTER TABLE crm.fuentes
    ADD COLUMN IF NOT EXISTS orden INT NOT NULL DEFAULT 0;

-- Asignar orden inicial según fila alfabética actual
UPDATE crm.fuentes f
SET orden = sub.rn
FROM (
    SELECT id, ROW_NUMBER() OVER (ORDER BY nombre) AS rn
    FROM crm.fuentes
    WHERE activo = TRUE
) sub
WHERE f.id = sub.id;

COMMIT;

-- V129 — Adecuación de Ficha Técnica al rubro inmobiliario (Palma del Río)
--
-- Reemplaza las preguntas de descubrimiento de academia de inglés por las 5
-- preguntas de perfilamiento inmobiliario:
--   1. tipo_lote:       ¿Qué tipo de lote estás buscando?
--   2. uso_lote:        ¿Este lote es para ti, para tu familia o por inversión?
--   3. ubicacion:       ¿En Arequipa o en qué departamento del Perú? (distrito)
--   4. otros_proyectos: ¿Estás cotizando otros proyectos inmobiliarios?
--   5. plazo_compra:    ¿Para cuándo quisieras adquirir tu lote?

BEGIN;

COMMENT ON COLUMN crm.leads.ficha_tecnica IS 'Cuestionario de perfilamiento inmobiliario: tipo_lote, uso_lote, ubicacion, otros_proyectos, plazo_compra.';

CREATE OR REPLACE FUNCTION crm.fn_check_ficha_tecnica_completada(ft JSONB)
RETURNS BOOLEAN AS $$
BEGIN
    IF ft IS NULL THEN
        RETURN FALSE;
    END IF;
    RETURN (
        COALESCE(TRIM(ft->>'tipo_lote'), '') <> '' AND
        COALESCE(TRIM(ft->>'uso_lote'), '') <> '' AND
        COALESCE(TRIM(ft->>'ubicacion'), '') <> '' AND
        COALESCE(TRIM(ft->>'otros_proyectos'), '') <> '' AND
        COALESCE(TRIM(ft->>'plazo_compra'), '') <> ''
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

UPDATE crm.leads
SET ficha_tecnica_completada = crm.fn_check_ficha_tecnica_completada(ficha_tecnica)
WHERE ficha_tecnica IS NOT NULL AND ficha_tecnica <> '{}'::jsonb;

COMMIT;

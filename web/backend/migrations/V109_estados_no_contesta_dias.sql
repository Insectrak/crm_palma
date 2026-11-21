-- V109 — Estados del embudo "No contesta" (Día 1, Día 2, Día 3 y Bolsa de Reciclaje)
-- Garantiza que existan los estados correspondientes a la regla de intentos telefónicos y WhatsApp.

BEGIN;

DO $$
DECLARE
    v_max_orden INTEGER;
BEGIN
    SELECT COALESCE(MAX(orden), 0) INTO v_max_orden FROM crm.estados_lead;

    -- 1. No contesta Día 1
    IF NOT EXISTS (SELECT 1 FROM crm.estados_lead WHERE nombre ILIKE 'No contesta D%a 1' OR nombre ILIKE 'No contesta 1') THEN
        v_max_orden := v_max_orden + 1;
        INSERT INTO crm.estados_lead (nombre, color_hex, es_final, orden)
        VALUES ('No contesta Día 1', '#f97316', FALSE, v_max_orden);
    END IF;

    -- 2. No contesta Día 2
    IF NOT EXISTS (SELECT 1 FROM crm.estados_lead WHERE nombre ILIKE 'No contesta D%a 2' OR nombre ILIKE 'No contesta 2') THEN
        v_max_orden := v_max_orden + 1;
        INSERT INTO crm.estados_lead (nombre, color_hex, es_final, orden)
        VALUES ('No contesta Día 2', '#ea580c', FALSE, v_max_orden);
    END IF;

    -- 3. No contesta Día 3
    IF NOT EXISTS (SELECT 1 FROM crm.estados_lead WHERE nombre ILIKE 'No contesta D%a 3' OR nombre ILIKE 'No contesta 3') THEN
        v_max_orden := v_max_orden + 1;
        INSERT INTO crm.estados_lead (nombre, color_hex, es_final, orden)
        VALUES ('No contesta Día 3', '#c2410c', FALSE, v_max_orden);
    END IF;

    -- 4. No contesta / Bolsa de reciclaje
    IF NOT EXISTS (
        SELECT 1 FROM crm.estados_lead 
        WHERE nombre ILIKE '%No contesta%Bolsa%reciclaje%'
           OR nombre ILIKE '%No contesta / Bolsa%'
           OR nombre ILIKE '%Bolsa TMK%'
    ) THEN
        v_max_orden := v_max_orden + 1;
        INSERT INTO crm.estados_lead (nombre, color_hex, es_final, orden)
        VALUES ('No contesta / Bolsa de reciclaje', '#6b7280', TRUE, v_max_orden);
    END IF;

END $$;

COMMIT;

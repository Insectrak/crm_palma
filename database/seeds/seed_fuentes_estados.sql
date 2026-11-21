-- =============================================================================
-- Seed: Catálogos de fuentes y estados del pipeline CRM
-- Archivo:     database/seeds/seed_fuentes_estados.sql
-- Fecha:       2026-04-03
-- Autor:       Brighton
-- Descripción: Datos iniciales requeridos para el funcionamiento del CRM.
--              Incluye el catálogo de fuentes y los estados del pipeline.
--              Este archivo es idempotente: se puede ejecutar múltiples veces.
--
-- PREREQUISITOS:
--   - V001_create_crm_schema.sql debe haberse ejecutado.
--   - V002_update_auth_roles.sql debe haberse ejecutado.
--
-- CATÁLOGOS:
--   crm.fuentes        — orígenes de captación de leads
--   crm.estados_lead   — estados del ciclo de vida de un lead
-- =============================================================================

BEGIN;

-- =============================================================================
-- Fuentes de leads
-- Estos valores deben coincidir con los strings que mandan los flujos n8n
-- al campo crm.leads.fuente_id (via JOIN por nombre).
-- =============================================================================

INSERT INTO crm.fuentes (nombre, activo) VALUES
    ('facebook',   TRUE),   -- Lead Ads de Facebook
    ('instagram',  TRUE),   -- Lead Ads de Instagram
    ('tiktok',     TRUE),   -- Lead Ads de TikTok
    ('excel',      TRUE),   -- Carga masiva desde archivo Excel
    ('manual',     TRUE),   -- Ingreso manual por asesor o admin
    ('web',        TRUE),   -- Formulario web embebido
    ('whatsapp',   TRUE)    -- Lead ingresado vía WhatsApp directamente
ON CONFLICT (nombre) DO UPDATE
    SET activo = EXCLUDED.activo;

COMMENT ON TABLE crm.fuentes IS
    'Catálogo de fuentes de captación. Seed inicial: facebook, instagram, tiktok, excel, manual, web, whatsapp.';

-- =============================================================================
-- Estados del pipeline de leads
-- El orden determina la posición en el kanban/embudo del frontend.
-- Los colores están alineados con el design system de React (Tailwind).
-- =============================================================================

INSERT INTO crm.estados_lead (nombre, orden, color_hex, es_final) VALUES
    ('Nuevo',           1, '#3b82f6', FALSE),  -- azul    — lead recién ingresado, sin gestionar
    ('Contactado',      2, '#f59e0b', FALSE),  -- ámbar   — se intentó o logró el primer contacto
    ('Calificado',      3, '#8b5cf6', FALSE),  -- violeta — se verificó que el lead tiene potencial
    ('En negociación',  4, '#ec4899', FALSE),  -- rosa    — en proceso activo de venta
    ('Ganado',          5, '#22c55e', TRUE),   -- verde   — ESTADO FINAL: lead convertido/matriculado
    ('Perdido',         6, '#ef4444', TRUE),   -- rojo    — ESTADO FINAL: oportunidad cerrada sin éxito
    ('No interesado',   7, '#6b7280', TRUE)    -- gris    — ESTADO FINAL: el lead rechazó el producto
ON CONFLICT (nombre) DO UPDATE
    SET
        orden     = EXCLUDED.orden,
        color_hex = EXCLUDED.color_hex,
        es_final  = EXCLUDED.es_final;

-- Verificar que el estado con id=1 sea 'Nuevo' (DEFAULT de crm.leads.estado_id)
-- Si la secuencia no empieza en 1, ajustar el DEFAULT en la tabla.
DO $$
DECLARE
    v_id_nuevo INTEGER;
BEGIN
    SELECT id INTO v_id_nuevo
    FROM crm.estados_lead
    WHERE nombre = 'Nuevo';

    IF v_id_nuevo IS NULL THEN
        RAISE EXCEPTION 'El estado "Nuevo" no se insertó correctamente en crm.estados_lead.';
    END IF;

    IF v_id_nuevo != 1 THEN
        RAISE WARNING
            'El estado "Nuevo" tiene id=% (se esperaba id=1). '
            'Actualizar el DEFAULT de crm.leads.estado_id a %.',
            v_id_nuevo, v_id_nuevo;
    ELSE
        RAISE NOTICE 'Estado "Nuevo" correctamente ubicado en id=1.';
    END IF;
END;
$$;

-- =============================================================================
-- Estado inicial del round-robin (fila global: fuente_id = NULL)
-- Se crea una sola fila que aplica a todas las fuentes.
-- El servicio de asignación (asignacion_service.py) usará SELECT FOR UPDATE sobre esta fila.
-- =============================================================================

INSERT INTO crm.round_robin_estado (fuente_id, ultimo_asesor_id)
VALUES (NULL, NULL)
ON CONFLICT (fuente_id) DO NOTHING;

COMMENT ON TABLE crm.round_robin_estado IS
    'Seed inicial: una fila global (fuente_id=NULL) para round-robin único entre asesores.';

COMMIT;

-- =============================================================================
-- Verificación rápida post-seed
-- =============================================================================

SELECT
    'fuentes'      AS catalogo,
    COUNT(*)       AS total_registros,
    STRING_AGG(nombre, ', ' ORDER BY id) AS valores
FROM crm.fuentes
UNION ALL
SELECT
    'estados_lead',
    COUNT(*),
    STRING_AGG(nombre || ' (' || color_hex || ')', ', ' ORDER BY orden)
FROM crm.estados_lead;

-- =============================================================================
-- V028 — Catálogo configurable de "calidad" (temperatura del lead)
-- =============================================================================
-- V027 dejó `calidad` como TEXT con un CHECK hardcoded (FRIO|TIBIO|CALIENTE).
-- Gerencia pidió que la lista sea configurable desde la UI y opcionalmente
-- obligatoria al momento de cargar leads masivamente.
--
-- Decisiones:
--   * Usamos la misma forma que los demás catálogos editables (estados_lead,
--     fuentes, campanas): tabla simple con `codigo` canónico para que el
--     dato persistido en `crm.leads.calidad` siga siendo legible sin JOIN.
--   * Validación por aplicación (soft FK) — el CHECK se elimina para que
--     agregar/renombrar un valor no requiera una nueva migración.
--   * Seeds preservan los 3 valores existentes (FRIO / TIBIO / CALIENTE) con
--     colores que matchean los badges ya definidos en LeadDetalle.jsx
--     (sky / amber / red).
-- =============================================================================

BEGIN;

-- ── Tabla de catálogo ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.catalogo_calidad (
    id          SERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,                 -- valor canónico guardado en leads.calidad
    nombre      TEXT NOT NULL,                        -- etiqueta visible (ES)
    color_hex   TEXT NOT NULL DEFAULT '#64748b',      -- slate-500 (neutral)
    orden       INT  NOT NULL DEFAULT 0,
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE  crm.catalogo_calidad IS
    'Temperatura del lead (FRIO/TIBIO/CALIENTE u otros valores que gerencia decida). Configurable desde UI.';
COMMENT ON COLUMN crm.catalogo_calidad.codigo IS
    'Valor persistido en crm.leads.calidad. Se guarda en UPPER para consistencia histórica.';

-- ── Seeds ─────────────────────────────────────────────────────────────────────
INSERT INTO crm.catalogo_calidad (codigo, nombre, color_hex, orden) VALUES
    ('FRIO',     'Frío',     '#38bdf8', 1),   -- sky-400
    ('TIBIO',    'Tibio',    '#f59e0b', 2),   -- amber-500
    ('CALIENTE', 'Caliente', '#ef4444', 3)    -- red-500
ON CONFLICT (codigo) DO NOTHING;

-- ── Eliminar CHECK rígido de V027 (si existe) ────────────────────────────────
-- A partir de ahora la validación la hace la capa de aplicación contra el
-- catálogo. El CHECK se vuelve una barrera que bloquea el catálogo editable.
ALTER TABLE crm.leads DROP CONSTRAINT IF EXISTS leads_calidad_chk;

COMMIT;

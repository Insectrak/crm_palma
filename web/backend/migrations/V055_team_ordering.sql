-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V055 — Round-robin secuencial por orden manual (estilo HubSpot)       ║
-- ║                                                                        ║
-- ║ Hasta hoy el motor V046 elegia al asesor con menor carga (load-       ║
-- ║ balanced). La gerencia comercial pidio una alternativa donde cada    ║
-- ║ supervisor pueda definir un ORDEN MANUAL dentro de su equipo y los   ║
-- ║ leads roten respetando esa jerarquia.                                 ║
-- ║                                                                        ║
-- ║ Patron: Salesforce Queue Round Robin / HubSpot Workflow Rotation.     ║
-- ║                                                                        ║
-- ║ ARQUITECTURA:                                                          ║
-- ║   1. crm.equipos.orden          — posicion 1..N por supervisor        ║
-- ║   2. crm.equipos.last_assigned_at — tracking del ultimo ganador       ║
-- ║   3. assignment_config.estrategia_default acepta 'round_robin_orden'  ║
-- ║                                                                        ║
-- ║ Retrocompatible: la estrategia 'round_robin_equipo' (por carga) se   ║
-- ║ mantiene como default. La nueva estrategia es opcional/configurable. ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─── 1) Schema: orden + tracking del ultimo asignado ──────────────────────

ALTER TABLE crm.equipos
    ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 0;

ALTER TABLE crm.equipos
    ADD COLUMN IF NOT EXISTS last_assigned_at TIMESTAMPTZ;

COMMENT ON COLUMN crm.equipos.orden IS
    'V055: Posicion del asesor dentro del equipo del supervisor (1..N). Define la jerarquia para round-robin secuencial. 0 = sin orden asignado todavia.';
COMMENT ON COLUMN crm.equipos.last_assigned_at IS
    'V055: Timestamp de la ultima asignacion automatica a este asesor. Lo usa _round_robin_orden para saber a quien le toca el siguiente lead.';

-- ─── 2) Inicializacion: orden alfabetico por nombre de asesor ────────────
-- Solo aplica donde orden = 0 (no pisamos valores ya configurados manualmente).

WITH ranked AS (
    SELECT
        eq.id,
        ROW_NUMBER() OVER (
            PARTITION BY eq.supervisor_id
            ORDER BY u.first_name NULLS LAST, u.last_name NULLS LAST, eq.asesor_id
        ) AS rn
    FROM crm.equipos eq
    JOIN auth.users u ON u.id = eq.asesor_id
    WHERE eq.activo = TRUE
)
UPDATE crm.equipos
SET orden = ranked.rn
FROM ranked
WHERE crm.equipos.id = ranked.id
  AND crm.equipos.orden = 0;

-- ─── 3) Indice: queries del round-robin secuencial ───────────────────────
-- Para SELECT ORDER BY orden donde supervisor + activo. Partial index
-- evita leads inactivos sin costo extra.

CREATE INDEX IF NOT EXISTS idx_equipos_orden_activos
    ON crm.equipos (supervisor_id, orden)
    WHERE activo = TRUE;

-- ─── 4) Estrategia round_robin_orden disponible en assignment_config ─────

ALTER TABLE crm.assignment_config
    DROP CONSTRAINT IF EXISTS assignment_config_estrategia_default_check;

ALTER TABLE crm.assignment_config
    ADD CONSTRAINT assignment_config_estrategia_default_check
    CHECK (estrategia_default IN ('round_robin_equipo', 'round_robin_orden', 'manual'));

-- ─── 5) Audit log: agregar campo 'orden_aplicado' para trazabilidad ──────
-- Permite ver "este lead se asigno por orden secuencial, posicion 2" en
-- el detalle del lead. Solo agregamos columna si no existe (idempotente).

ALTER TABLE crm.assignment_log
    ADD COLUMN IF NOT EXISTS orden_aplicado INTEGER;

COMMENT ON COLUMN crm.assignment_log.orden_aplicado IS
    'V055: Posicion en la jerarquia del equipo cuando se uso estrategia round_robin_orden. NULL para otras estrategias.';

COMMIT;

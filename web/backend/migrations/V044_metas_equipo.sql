-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V044 — Metas por Equipo (extension Sprint 3)                          ║
-- ║                                                                        ║
-- ║ Comercial pidio: ademas de metas individuales, poder definir metas    ║
-- ║ a nivel equipo (supervisor + todos sus asesores).                     ║
-- ║                                                                        ║
-- ║ Patron Salesforce / HubSpot: dos tipos de meta coexistiendo —         ║
-- ║   tipo='asesor' (default) → asesor_id es el UUID del asesor          ║
-- ║   tipo='equipo'           → asesor_id es el UUID del supervisor      ║
-- ║                                  cuyo equipo representa la meta.     ║
-- ║                                                                        ║
-- ║ Las metas de equipo NO reemplazan las individuales; se acumulan       ║
-- ║ por separado. El backend al calcular cumplimiento de tipo='equipo'   ║
-- ║ suma ventas/citas/llamadas de TODOS los miembros (supervisor +       ║
-- ║ asesores activos en crm.equipos).                                     ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- 1) Agregar columna tipo (default 'asesor' para backward compat)
ALTER TABLE crm.metas_mensuales
  ADD COLUMN IF NOT EXISTS tipo VARCHAR(10) NOT NULL DEFAULT 'asesor';

-- 2) Validar valores ('asesor' o 'equipo')
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'metas_mensuales_tipo_valido'
  ) THEN
    ALTER TABLE crm.metas_mensuales
      ADD CONSTRAINT metas_mensuales_tipo_valido
        CHECK (tipo IN ('asesor', 'equipo'));
  END IF;
END$$;

-- 3) Reemplazar UNIQUE (asesor_id, mes) por UNIQUE (asesor_id, mes, tipo)
--    para que el supervisor pueda tener su meta personal Y la del equipo.
ALTER TABLE crm.metas_mensuales
  DROP CONSTRAINT IF EXISTS metas_mensuales_uniq;

ALTER TABLE crm.metas_mensuales
  ADD CONSTRAINT metas_mensuales_uniq UNIQUE (asesor_id, mes, tipo);

CREATE INDEX IF NOT EXISTS idx_metas_mensuales_tipo
  ON crm.metas_mensuales (tipo, mes);

COMMENT ON COLUMN crm.metas_mensuales.tipo IS
  '''asesor'' = meta individual; ''equipo'' = meta del equipo del supervisor (asesor_id = supervisor_id).';

COMMIT;

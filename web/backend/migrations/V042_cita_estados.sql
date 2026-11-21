-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V042 — Estados de cita (configurables) para contactos con fecha_cita  ║
-- ║                                                                        ║
-- ║ MOTIVO:                                                                ║
-- ║ Hasta hoy, una cita agendada (`crm.contactos.fecha_cita IS NOT NULL`)  ║
-- ║ no tiene forma de marcarse como cumplida, reprogramada, cancelada ni   ║
-- ║ no asistio. El supervisor no podia ver si una cita fue efectiva ni     ║
-- ║ medir tasa de asistencia (KPI clave en ventas).                        ║
-- ║                                                                        ║
-- ║ DISENO:                                                                ║
-- ║ Patron Salesforce / HubSpot — un catalogo configurable de estados de  ║
-- ║ cita y un FK en contactos. El admin puede agregar / renombrar /        ║
-- ║ reordenar los estados desde Configuracion → Estados de cita.           ║
-- ║                                                                        ║
-- ║ SCHEMA:                                                                ║
-- ║   crm.cita_estados                                                    ║
-- ║     id, codigo, nombre, color_hex, orden, es_final, activo, ...       ║
-- ║   crm.contactos.cita_estado_id (nullable; solo cuando fecha_cita NOT NULL)║
-- ║                                                                        ║
-- ║ SEEDS por defecto (admin puede modificar):                             ║
-- ║   Pendiente       (azul,    default al crear cita)                    ║
-- ║   Completada      (verde,   final positivo)                           ║
-- ║   Reprogramada    (amber,   intermedio)                               ║
-- ║   Cancelada       (gris,    final neutro)                             ║
-- ║   No asistió      (rojo,    final negativo)                           ║
-- ║                                                                        ║
-- ║ BACKFILL: contactos existentes con fecha_cita reciben cita_estado_id  ║
-- ║ = Pendiente. La fecha de cita en el pasado podria ser Completada,    ║
-- ║ pero preferimos no asumir — el supervisor decide caso por caso.       ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1. Catalogo de estados de cita ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS crm.cita_estados (
    id         SERIAL      PRIMARY KEY,
    codigo     TEXT        NOT NULL UNIQUE,
    nombre     TEXT        NOT NULL UNIQUE,
    orden      INTEGER     NOT NULL UNIQUE,
    color_hex  TEXT        NOT NULL DEFAULT '#6B7280',
    es_final   BOOLEAN     NOT NULL DEFAULT FALSE,
    activo     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.cita_estados         IS 'Catalogo de estados de citas (Pendiente, Completada, Reprogramada, etc).';
COMMENT ON COLUMN crm.cita_estados.codigo  IS 'Slug estable (ej: pendiente, completada). Usado por la app para defaults.';
COMMENT ON COLUMN crm.cita_estados.es_final IS 'TRUE para terminales (cita ya no puede cambiar): Completada, Cancelada, No asistio.';

-- Seeds — admin puede luego reordenar / renombrar / desactivar
INSERT INTO crm.cita_estados (codigo, nombre, orden, color_hex, es_final) VALUES
    ('pendiente',    'Pendiente',    1, '#3B82F6', FALSE),
    ('completada',   'Completada',   2, '#10B981', TRUE),
    ('reprogramada', 'Reprogramada', 3, '#F59E0B', FALSE),
    ('cancelada',    'Cancelada',    4, '#6B7280', TRUE),
    ('no_asistio',   'No asistió',   5, '#EF4444', TRUE)
ON CONFLICT (codigo) DO NOTHING;

-- ── 2. FK en crm.contactos ──────────────────────────────────────────────────

ALTER TABLE crm.contactos
    ADD COLUMN IF NOT EXISTS cita_estado_id INTEGER
        REFERENCES crm.cita_estados(id)
        ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_contactos_cita_estado_id
    ON crm.contactos (cita_estado_id)
    WHERE fecha_cita IS NOT NULL;

COMMENT ON COLUMN crm.contactos.cita_estado_id IS
    'FK a crm.cita_estados. Solo aplica cuando fecha_cita IS NOT NULL. '
    'Default Pendiente al crear; el supervisor / asesor lo actualiza '
    'tras la cita.';

-- ── 3. Backfill: contactos con cita pero sin estado → Pendiente ─────────────

UPDATE crm.contactos
SET cita_estado_id = (SELECT id FROM crm.cita_estados WHERE codigo = 'pendiente')
WHERE fecha_cita IS NOT NULL
  AND cita_estado_id IS NULL;

COMMIT;

-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V047 — Cola de leads en espera de horario laboral                     ║
-- ║                                                                        ║
-- ║ Cuando estrategia_fuera_horario='cola_proximo_dia', los leads que     ║
-- ║ entran fuera del horario quedan en esta tabla. Un job programado      ║
-- ║ corre cada 15 min, revisa si volvió el horario y reintenta la         ║
-- ║ auto-asignación con el motor existente.                               ║
-- ║                                                                        ║
-- ║ Si el reintento tiene éxito → se borra la fila.                        ║
-- ║ Si falla → se reagenda en proximo_intento + 15 min, hasta 96 intentos ║
-- ║ (24 horas), después se descarta y queda al supervisor permanente.     ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

CREATE TABLE IF NOT EXISTS crm.assignment_pending (
    id              BIGSERIAL       PRIMARY KEY,
    lead_id         INTEGER         NOT NULL UNIQUE
                    REFERENCES crm.leads(id) ON DELETE CASCADE,
    supervisor_id   UUID            NOT NULL
                    REFERENCES auth.users(id) ON DELETE CASCADE,
    motivo          VARCHAR(40)     NOT NULL,                   -- 'fuera_horario' | 'sin_disponibles'
    intentos        INTEGER         NOT NULL DEFAULT 0,
    proximo_intento TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    ultimo_error    TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assignment_pending_proximo
    ON crm.assignment_pending (proximo_intento) WHERE intentos < 100;

CREATE INDEX IF NOT EXISTS idx_assignment_pending_motivo
    ON crm.assignment_pending (motivo);

COMMENT ON TABLE crm.assignment_pending IS
    'Cola de leads que el motor difirió por estar fuera de horario o sin disponibles. Un job los reintenta cada 15 min.';
COMMENT ON COLUMN crm.assignment_pending.proximo_intento IS
    'Cuándo reintentar. El job procesa solo filas con proximo_intento <= NOW().';

COMMIT;

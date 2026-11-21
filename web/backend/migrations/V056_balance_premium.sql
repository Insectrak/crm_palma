-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V056 — Balance premium: cap default + sin_contacto_48h + estrategias  ║
-- ║         estricta y balanceada + audit_log de jerarquia                 ║
-- ║                                                                        ║
-- ║ Tras la implementacion de V055 (round-robin por orden manual) la       ║
-- ║ gerencia comercial detecto 4 ajustes para que el motor sea robusto     ║
-- ║ y justo a largo plazo:                                                 ║
-- ║                                                                        ║
-- ║ 1) Cap default 50 -> 80 (50 saturaba con leads ya contactados por IA)  ║
-- ║                                                                        ║
-- ║ 2) capacity_definicion default 'todos_activos' -> 'sin_contacto_48h'   ║
-- ║    Asi un lead que llega ya contactado por IA externa (Wedo) NO        ║
-- ║    consume slot de capacity hasta que pasen 48h sin contacto humano.   ║
-- ║                                                                        ║
-- ║ 3) Dos nuevas estrategias:                                             ║
-- ║    - 'round_robin_orden_estricto': IGNORA cap siempre, solo respeta    ║
-- ║      horario/ausencia. Para supervisores que quieren control total.    ║
-- ║    - 'round_robin_balanceado': desempata por menor count en ultimos    ║
-- ║      7 dias. Compensa skips por LLENO/ausente del modo orden.          ║
-- ║                                                                        ║
-- ║ 4) Tabla crm.equipo_audit_log: traza quien reordeno la jerarquia,      ║
-- ║    cuando, y el snapshot del orden anterior/nuevo.                     ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─── 1) Cap default 50 -> 80 + capacity 'sin_contacto_48h' ────────────────
-- UPDATE solo si la fila singleton sigue con los defaults originales.
-- Si el admin ya los cambio manualmente, NO los pisamos.

UPDATE crm.assignment_config
SET max_leads_abiertos_default = 80
WHERE id = 1
  AND max_leads_abiertos_default = 50;

UPDATE crm.assignment_config
SET capacity_definicion = 'sin_contacto_48h'
WHERE id = 1
  AND capacity_definicion = 'todos_activos';


-- ─── 2) Extender CHECK constraint con 2 nuevas estrategias ────────────────

ALTER TABLE crm.assignment_config
    DROP CONSTRAINT IF EXISTS assignment_config_estrategia_default_check;

ALTER TABLE crm.assignment_config
    ADD CONSTRAINT assignment_config_estrategia_default_check
    CHECK (estrategia_default IN (
        'round_robin_equipo',           -- por carga (default original V046)
        'round_robin_orden',             -- por jerarquia manual (V055)
        'round_robin_orden_estricto',    -- V056: orden ignorando cap siempre
        'round_robin_balanceado',        -- V056: orden + desempate por menor 7d
        'manual'
    ));


-- ─── 3) Audit log de reordenamientos de jerarquia ─────────────────────────
-- Cada vez que un admin o supervisor reordena las posiciones del equipo,
-- guardamos: quien, cuando, equipo afectado, snapshot antes/despues.
-- Permite responder: "¿quien movio a Renato del 2 al 4?" o "¿desde cuando
-- Solanch esta en posicion 1?".

CREATE TABLE IF NOT EXISTS crm.equipo_audit_log (
    id              SERIAL          PRIMARY KEY,
    supervisor_id   UUID            NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    actor_id        UUID            NOT NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    actor_role      VARCHAR(20)     NOT NULL,
    accion          VARCHAR(40)     NOT NULL
                    CHECK (accion IN ('reorder', 'pausar_asesor', 'reanudar_asesor', 'reset_rotacion', 'agregar_asesor', 'quitar_asesor')),
    -- Snapshot del orden ANTES del cambio: [{user_id, nombre, orden, activo}, ...]
    orden_antes     JSONB,
    -- Snapshot del orden DESPUES del cambio
    orden_despues   JSONB,
    detalle         TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_equipo_audit_supervisor
    ON crm.equipo_audit_log (supervisor_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_equipo_audit_actor
    ON crm.equipo_audit_log (actor_id, created_at DESC);

COMMENT ON TABLE crm.equipo_audit_log IS
    'V056: Auditoria de cambios en la jerarquia de equipos (reordenamiento, pausa, reset rotacion). Trazabilidad para responder "quien hizo que cuando" en la rotacion de leads.';


-- ─── 4) Funcion: contar leads recibidos en ultimos 7 dias por asesor ──────
-- La estrategia 'round_robin_balanceado' usa esto para desempatar entre
-- candidatos: el que MENOS recibio en los ultimos 7 dias gana. Compensa
-- skips por LLENO/ausente que el modo orden no compensa.

CREATE OR REPLACE FUNCTION crm.count_leads_recibidos_7d(
    p_asesor_id UUID
) RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*)::int INTO v_count
    FROM crm.assignment_log al
    WHERE al.asignado_a_id = p_asesor_id
      AND al.fecha >= NOW() - INTERVAL '7 days';
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION crm.count_leads_recibidos_7d IS
    'V056: Cuenta leads asignados al asesor en los ultimos 7 dias (segun assignment_log). Lo usa la estrategia round_robin_balanceado para desempatar.';

COMMIT;

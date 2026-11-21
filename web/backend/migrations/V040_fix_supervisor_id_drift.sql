-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V040 — Backfill supervisor_id en leads cross-equipo                    ║
-- ║                                                                        ║
-- ║ PROBLEMA:                                                              ║
-- ║ Antes de V040 las funciones reassign_one / reassign_bulk del           ║
-- ║ repositorio actualizaban solo `asesor_id`, no `supervisor_id`. Cuando ║
-- ║ Paola (supervisor) reasignaba un lead a Diego (otro supervisor) o a   ║
-- ║ un asesor de otro equipo, el lead seguia visible en el listado de    ║
-- ║ Paola por la clausula `OR l.supervisor_id = self::uuid` del           ║
-- ║ role_filter. Cualquier lead reasignado cross-equipo en la base actual  ║
-- ║ tiene supervisor_id "stale" y necesita resincronizarse.                ║
-- ║                                                                        ║
-- ║ FIX (codigo): assignments_service._resolve_target_supervisor_id +     ║
-- ║   leads_repository.reassign_one/_bulk ahora actualizan ambos campos.  ║
-- ║                                                                        ║
-- ║ BACKFILL (este script):                                                ║
-- ║   - Lead con asesor_id = supervisor X    → supervisor_id = X          ║
-- ║   - Lead con asesor_id = asesor (equipo Y) → supervisor_id = Y        ║
-- ║   - Lead con asesor_id = asesor sin equipo → no se toca (defensivo). ║
-- ║   - Lead sin asesor_id (en cola)         → no se toca (V035 dueño).  ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1. Leads asignados directamente a un supervisor ────────────────────────
UPDATE crm.leads l
SET supervisor_id = l.asesor_id,
    updated_at    = NOW()
FROM auth.users u
WHERE u.id = l.asesor_id
  AND u.role = 'supervisor'
  AND l.supervisor_id IS DISTINCT FROM l.asesor_id
  AND l.activo = TRUE;

-- ── 2. Leads asignados a asesores reales (resolvemos supervisor via equipo) ─
UPDATE crm.leads l
SET supervisor_id = eq.supervisor_id,
    updated_at    = NOW()
FROM crm.equipos eq, auth.users u
WHERE u.id = l.asesor_id
  AND u.role = 'asesor'
  AND eq.asesor_id = l.asesor_id
  AND eq.activo = TRUE
  AND l.supervisor_id IS DISTINCT FROM eq.supervisor_id
  AND l.activo = TRUE;

COMMIT;

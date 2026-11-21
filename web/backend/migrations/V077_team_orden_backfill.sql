-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V077 — Backfill de crm.equipos.orden para equipos con orden=0         ║
-- ║                                                                        ║
-- ║ V055 introdujo crm.equipos.orden (DEFAULT 0) e inicializo el orden    ║
-- ║ alfabetico para los equipos que existian al momento de aplicarse.     ║
-- ║                                                                        ║
-- ║ Bug heredado: el endpoint POST /api/catalogs/equipos hace INSERT sin  ║
-- ║ setear orden, asi que TODOS los asesores agregados desde V055 hasta   ║
-- ║ ahora quedaron con orden=0. Esto rompe _pick_round_robin_orden que    ║
-- ║ degrada a sort por user_id (UUID) — los leads se concentran en el     ║
-- ║ asesor cuyo UUID gana el sort, no en el orden alfabetico que el       ║
-- ║ admin ve en la UI.                                                     ║
-- ║                                                                        ║
-- ║ Esta migracion ataca SOLO la data existente. El fix del INSERT vive   ║
-- ║ en catalogs.add_to_equipo. Issue #57.                                 ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- Re-aplicar la inicializacion de V055 sobre todas las filas con orden=0.
-- Mismo ROW_NUMBER por supervisor_id ordenado por nombre alfabetico.
-- Idempotente: si todos ya tienen orden correcto, no toca nada.

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

COMMIT;

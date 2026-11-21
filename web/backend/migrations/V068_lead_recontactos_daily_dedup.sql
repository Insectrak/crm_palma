-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V068 — Lead Recontactos: dedup por dia (no por 24h rolling)            ║
-- ║                                                                        ║
-- ║ Bug detectado en prod (2026-05-13): leads como Nefertiti tenian 7     ║
-- ║ recontactos en 7 dias consecutivos, todos con fuente_externa_id=NULL  ║
-- ║ y horas levemente distintas (13:26, 13:28, 13:32, 13:35, ...). El     ║
-- ║ cooldown anterior "24h rolling" NO los bloqueaba porque cada evento    ║
-- ║ llegaba mas de 24h exactos despues del anterior.                       ║
-- ║                                                                        ║
-- ║ Causa raiz operativa: un cron/poll (n8n) que re-importa los mismos    ║
-- ║ leads cada dia, sin pasar fuente_externa_id. El sistema crea un       ║
-- ║ recontacto por dia indefinidamente.                                   ║
-- ║                                                                        ║
-- ║ Solucion business-rule (paridad con HubSpot / Salesforce):            ║
-- ║   "Maximo 1 recontacto por (lead, fuente, dia) sin importar fext".    ║
-- ║                                                                        ║
-- ║ Razonamiento:                                                          ║
-- ║   - Si el mismo cliente cliquea el ad 5 veces el mismo dia = 1        ║
-- ║     reactivacion (no 5).                                              ║
-- ║   - Si vuelve manana = 1 mas (legitimo, son 2 dias).                  ║
-- ║   - Si un poll automatico reimporta el lead cada dia, el dia 2+ NO    ║
-- ║     debe contar — no son reactivaciones reales del cliente.           ║
-- ║                                                                        ║
-- ║ El reset de comportamiento en code vive en lead_recapture.py.         ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1) DEDUP RETROACTIVO ──────────────────────────────────────────────────
-- Por (lead_id, fuente_id, dia_lima) conservamos el id MAS BAJO (la primera
-- aparicion del dia). Las repeticiones del mismo dia se borran.
--
-- NOTA: usamos AT TIME ZONE 'America/Lima' para que "dia" refleje la fecha
-- comercial peruana, no UTC. Sin esto, eventos a las 19:00 PE (00:00 UTC
-- del dia siguiente) se contarian como otro dia.

DELETE FROM crm.lead_recontactos a
USING crm.lead_recontactos b
WHERE a.lead_id = b.lead_id
  AND COALESCE(a.fuente_id, -1) = COALESCE(b.fuente_id, -1)
  AND DATE(a.created_at AT TIME ZONE 'America/Lima')
      = DATE(b.created_at AT TIME ZONE 'America/Lima')
  AND a.id > b.id;

-- ── 2) Indice helper para chequeo rapido en lead_recapture.py ─────────────
-- Soporta el lookup "ya hay un recontacto hoy para (lead, fuente)?".
-- No usamos UNIQUE porque DATE(timestamptz) NO es IMMUTABLE en PostgreSQL
-- (depende del timezone del session). El bloqueo de duplicados a futuro
-- se hace en app/services/lead_recapture.py con un check SELECT antes del
-- INSERT — defense in depth + indice rapido.

CREATE INDEX IF NOT EXISTS idx_lead_recontactos_lead_fuente_day
    ON crm.lead_recontactos (lead_id, fuente_id, created_at DESC);

COMMENT ON INDEX crm.idx_lead_recontactos_lead_fuente_day IS
    'V068: acelera el check "ya hay recontacto hoy para (lead, fuente)" '
    'que reemplaza al cooldown rolling 24h. El bloqueo real esta en code.';

COMMIT;

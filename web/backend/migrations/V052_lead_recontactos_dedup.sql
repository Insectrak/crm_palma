-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V052 — Lead Recontactos Dedup (idempotency)                            ║
-- ║                                                                        ║
-- ║ Bug: TikTok / n8n estaba reentregando el MISMO lead duplicado decenas ║
-- ║ de veces (135 recontactos para un solo cliente). Cada reentrega       ║
-- ║ insertaba una fila nueva en crm.lead_recontactos sin ningun control   ║
-- ║ de idempotencia. El badge "↻ 135" en la UI no es realista — un       ║
-- ║ cliente no se reinteresa 135 veces, eso es ruido del flow.            ║
-- ║                                                                        ║
-- ║ Patron Salesforce / HubSpot:                                          ║
-- ║   - Si el provider envia el MISMO fuente_externa_id (ej. el lead_id   ║
-- ║     de TikTok), es UN evento, no N. Un re-engagement por external_id. ║
-- ║   - Si NO viene external_id (form manual), aplica cooldown: max 1     ║
-- ║     recontacto por (lead, fuente, dia).                               ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- 1) DEDUP RETROACTIVO de filas existentes
--    Por (lead_id, fuente_externa_id) cuando fext NO es NULL — conservamos
--    el id mas chico (la primera ingesta). Las demas se borran.
DELETE FROM crm.lead_recontactos a
USING crm.lead_recontactos b
WHERE a.lead_id = b.lead_id
  AND a.fuente_externa_id IS NOT NULL
  AND b.fuente_externa_id IS NOT NULL
  AND a.fuente_externa_id = b.fuente_externa_id
  AND a.id > b.id;

-- 2) Para los que NO tienen fuente_externa_id, dedup por (lead_id,
--    fuente_id, dia). Mismo dia + misma fuente = mismo evento operacional.
DELETE FROM crm.lead_recontactos a
USING crm.lead_recontactos b
WHERE a.lead_id = b.lead_id
  AND a.fuente_externa_id IS NULL
  AND b.fuente_externa_id IS NULL
  AND COALESCE(a.fuente_id, -1) = COALESCE(b.fuente_id, -1)
  AND DATE(a.created_at) = DATE(b.created_at)
  AND a.id > b.id;

-- 3) Indice unico parcial: previene futuros duplicados con external_id.
--    No bloquea NULLs (forms manuales pueden no traer external_id).
CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_recontactos_lead_fext
    ON crm.lead_recontactos (lead_id, fuente_externa_id)
    WHERE fuente_externa_id IS NOT NULL;

-- 4) Indice helper para el cooldown 24h por (lead, fuente)
--    No usamos DATE(created_at) en el indice porque DATE(timestamptz) NO
--    es IMMUTABLE (depende del timezone). El query usa created_at > NOW()
--    - INTERVAL '24h' que aprovecha este indice.
CREATE INDEX IF NOT EXISTS idx_lead_recontactos_dedup_cooldown
    ON crm.lead_recontactos (lead_id, fuente_id, created_at DESC)
    WHERE fuente_externa_id IS NULL;

COMMENT ON INDEX crm.uq_lead_recontactos_lead_fext IS
    'V052: Idempotency — un (lead_id, fuente_externa_id) NO puede existir mas de una vez.';
COMMENT ON INDEX crm.idx_lead_recontactos_dedup_cooldown IS
    'V052: Acelera el cooldown 24h por (lead, fuente) cuando no hay fext.';

COMMIT;

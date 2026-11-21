-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V033 — Dedupe wa_campaigns y UNIQUE en ad_id                           ║
-- ║                                                                        ║
-- ║ Bug: el INSERT del webhook usa `ON CONFLICT DO NOTHING` sin target,   ║
-- ║ lo que cae en el PK (`id` SERIAL) que nunca colisiona. Resultado:     ║
-- ║ cada referral CTWA del mismo ad_id crea una fila nueva en             ║
-- ║ crm.wa_campaigns. Visto en prod: 7 filas para `ad_id=12217042..`.     ║
-- ║                                                                        ║
-- ║ Esta migracion:                                                       ║
-- ║   1. Elige una fila sobreviviente por ad_id (la mas vieja con datos).║
-- ║   2. Repunta crm.leads.wa_campaign_id al sobreviviente.               ║
-- ║   3. Borra las filas duplicadas.                                      ║
-- ║   4. Agrega UNIQUE parcial en wa_campaigns(ad_id) WHERE ad_id NOT    ║
-- ║      NULL — soporta CTWA + manuales sin ad_id.                       ║
-- ║                                                                        ║
-- ║ Idempotente: re-ejecutar no rompe.                                    ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1) Identificar sobreviviente por ad_id ───────────────────────────────
-- Criterio: preferir filas enriquecidas (enriched_at NOT NULL), luego la mas vieja.
WITH ranked AS (
    SELECT id,
           ad_id,
           ROW_NUMBER() OVER (
               PARTITION BY ad_id
               ORDER BY (enriched_at IS NULL),  -- enriquecidas primero (FALSE < TRUE)
                        created_at ASC,
                        id ASC
           ) AS rn
      FROM crm.wa_campaigns
     WHERE ad_id IS NOT NULL
),
survivors AS (
    SELECT ad_id, id AS survivor_id
      FROM ranked
     WHERE rn = 1
),
losers AS (
    SELECT r.id AS loser_id, s.survivor_id
      FROM ranked r
      JOIN survivors s ON s.ad_id = r.ad_id
     WHERE r.rn > 1
)
-- ── 2) Repuntar leads ──────────────────────────────────────────────────
UPDATE crm.leads l
   SET wa_campaign_id = lo.survivor_id
  FROM losers lo
 WHERE l.wa_campaign_id = lo.loser_id;

-- ── 3) Borrar duplicados ───────────────────────────────────────────────
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY ad_id
               ORDER BY (enriched_at IS NULL),
                        created_at ASC,
                        id ASC
           ) AS rn
      FROM crm.wa_campaigns
     WHERE ad_id IS NOT NULL
)
DELETE FROM crm.wa_campaigns
 WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- ── 4) UNIQUE parcial en ad_id ─────────────────────────────────────────
-- Indice unico parcial: solo aplica cuando ad_id IS NOT NULL.
-- Esto permite que campanas manuales sin ad_id coexistan sin colisionar.
DROP INDEX IF EXISTS crm.idx_wa_campaigns_ad_id;  -- el viejo NO era UNIQUE

CREATE UNIQUE INDEX IF NOT EXISTS uq_wa_campaigns_ad_id
    ON crm.wa_campaigns (ad_id)
    WHERE ad_id IS NOT NULL;

COMMIT;

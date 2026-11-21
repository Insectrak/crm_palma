-- V032 — Enriquecimiento de nombres de jerarquia Meta en crm.wa_campaigns.
--
-- Contexto:
--   El webhook de WhatsApp envia `referral` con `source_id` (= ad_id) y, opcional,
--   `headline` / `body`. NUNCA trae los nombres reales del anuncio, adset o
--   campana que se configuraron en Ads Manager — solo el Ad ID numerico.
--
-- Solucion:
--   Columnas para cachear lo que obtenemos con un unico GET a Graph API:
--     GET /{ad_id}?fields=name,adset{id,name},campaign{id,name}
--   El enrichment corre en BackgroundTask del webhook CTWA (idempotente) y
--   tambien puede dispararse a mano desde admin (endpoint /wa-campaigns/{id}/enrich).
--
--   Se aplica tambien via bootstrap.ensure_wa_campaigns_enrichment_schema().

ALTER TABLE crm.wa_campaigns
    ADD COLUMN IF NOT EXISTS ad_name            TEXT,
    ADD COLUMN IF NOT EXISTS adset_id           VARCHAR(80),
    ADD COLUMN IF NOT EXISTS adset_name         TEXT,
    ADD COLUMN IF NOT EXISTS meta_campaign_id   VARCHAR(80),
    ADD COLUMN IF NOT EXISTS meta_campaign_name TEXT,
    ADD COLUMN IF NOT EXISTS enriched_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enrich_error       TEXT;

-- Indice para barrer las que no fueron enriquecidas aun (background retry).
CREATE INDEX IF NOT EXISTS idx_wa_campaigns_needs_enrichment
    ON crm.wa_campaigns (ad_id)
    WHERE enriched_at IS NULL AND ad_id IS NOT NULL;

COMMENT ON COLUMN crm.wa_campaigns.ad_name IS
    'Nombre del anuncio segun Meta Ads Manager. Se resuelve via Graph API.';
COMMENT ON COLUMN crm.wa_campaigns.meta_campaign_name IS
    'Nombre de la campana Meta (padre del adset). No confundir con crm.wa_campaigns.name, que es el label interno.';
COMMENT ON COLUMN crm.wa_campaigns.enriched_at IS
    'Timestamp de la ultima resolucion exitosa. NULL = nunca enriquecida.';
COMMENT ON COLUMN crm.wa_campaigns.enrich_error IS
    'Ultimo error al intentar resolver nombres (no_token | http_* | not_found). NULL cuando enriched_at es reciente.';

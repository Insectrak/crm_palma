-- V125 — Ampliar wa_ctwa_clid y campos CTWA a TEXT para soportar tokens largos de Meta Ads
--
-- Causa: Meta Cloud API envia ctwa_clid (Click-to-WhatsApp Click ID) de mas de 120 caracteres.
-- Al intentar actualizar en crm.leads.wa_ctwa_clid (VARCHAR(120)), PostgreSQL abortaba
-- la transaccion con StringDataRightTruncation: value too long for type character varying(120),
-- descartando el mensaje entrante y la creacion del lead.
--
-- Solucion:
-- 1. Cambiar crm.leads.wa_ctwa_clid a TEXT.
-- 2. Cambiar crm.leads.wa_campaign_ad_id a TEXT por seguridad.
-- 3. Cambiar crm.wa_campaigns.name y ad_id a TEXT para tolerar headlines e IDs largos.

BEGIN;

ALTER TABLE crm.leads
    ALTER COLUMN wa_ctwa_clid TYPE TEXT,
    ALTER COLUMN wa_campaign_ad_id TYPE TEXT;

ALTER TABLE crm.wa_campaigns
    ALTER COLUMN name TYPE TEXT,
    ALTER COLUMN ad_id TYPE TEXT;

COMMIT;


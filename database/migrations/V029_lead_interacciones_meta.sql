-- V029 — Atribución multi-campaña de Meta Lead Ads.
--
-- Contexto:
--   Hoy, cuando un mismo prospecto completa múltiples formularios de
--   distintas campañas/anuncios, el segundo y siguientes caen en el
--   dedupe por teléfono y se descartan en silencio. La info de atribución
--   (campaign_id, form_id, ad_id) del segundo lead se pierde.
--
-- Solución:
--   Tabla append-only que registra CADA interacción de Meta (leadgen_id
--   único), vinculada al lead del CRM. Permite:
--     * Timeline de re-interés por lead (el asesor ve cuántas veces
--       llenó formularios el prospecto y en qué campañas).
--     * Reportes de atribución multi-touch (qué campañas generan más
--       re-contactos).
--     * Idempotencia: UNIQUE en leadgen_id evita re-procesar el mismo
--       evento si Meta reintenta el webhook.
--
-- Se aplica también via bootstrap.ensure_lead_interacciones_meta_schema()
-- para despliegues idempotentes en EasyPanel.

CREATE TABLE IF NOT EXISTS crm.lead_interacciones_meta (
    id                 BIGSERIAL PRIMARY KEY,
    lead_id            INTEGER NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    leadgen_id         TEXT NOT NULL,
    page_id            TEXT NOT NULL,
    form_id            TEXT,
    ad_id              TEXT,
    adset_id           TEXT,
    campaign_id        TEXT,
    es_duplicado       BOOLEAN NOT NULL,   -- TRUE = re-interacción sobre lead existente
    fecha_interaccion  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_field_data     JSONB,              -- snapshot del field_data para auditoría
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lead_interacciones_meta_leadgen UNIQUE (leadgen_id)
);

-- Consulta principal: timeline por lead (la UI del detalle del lead
-- pedirá las interacciones ordenadas por fecha desc).
CREATE INDEX IF NOT EXISTS idx_interacciones_meta_lead_fecha
    ON crm.lead_interacciones_meta (lead_id, fecha_interaccion DESC);

-- Reportes de atribución por campaña.
CREATE INDEX IF NOT EXISTS idx_interacciones_meta_campaign
    ON crm.lead_interacciones_meta (campaign_id)
    WHERE campaign_id IS NOT NULL;

-- Reportes / debugging por formulario.
CREATE INDEX IF NOT EXISTS idx_interacciones_meta_form
    ON crm.lead_interacciones_meta (form_id)
    WHERE form_id IS NOT NULL;

COMMENT ON TABLE  crm.lead_interacciones_meta IS
    'Append-only: cada submit de Lead Ads de Meta por lead. Permite atribución multi-campaña y timeline de re-interés.';
COMMENT ON COLUMN crm.lead_interacciones_meta.es_duplicado IS
    'FALSE = el evento creó el lead. TRUE = ya existía lead con ese teléfono activo (re-interacción).';
COMMENT ON COLUMN crm.lead_interacciones_meta.leadgen_id IS
    'ID único del lead en Meta. UNIQUE evita re-procesar reintentos de webhook.';

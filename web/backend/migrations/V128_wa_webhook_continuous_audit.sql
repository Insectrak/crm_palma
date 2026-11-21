-- =============================================================================
-- Migración V128: Auditoría continua y forense de Webhooks de WhatsApp
-- Fecha:       2026-11-09
-- Descripción: Registra en tiempo real cada evento entrante de WhatsApp
--              (mensajes, status, referrals de Meta Ads / CTWA, creación o match de leads,
--              errores de payload), permitiendo conciliación exacta entre Meta Ads
--              y el CRM.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS crm.wa_webhook_events (
    id BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type VARCHAR(50) NOT NULL,            -- 'inbound_message', 'status_update', 'system'
    wa_phone VARCHAR(50),                        -- Teléfono E164 sin '+'
    wamid VARCHAR(255),                          -- WhatsApp Message ID
    phone_number_id VARCHAR(50),                 -- Recipient business phone id (Meta)
    display_phone_number VARCHAR(50),            -- Recipient display number
    contact_name VARCHAR(255),                   -- Sender profile name
    has_referral BOOLEAN NOT NULL DEFAULT FALSE, -- Vino con objeto referral (CTWA)
    referral_ad_id VARCHAR(100),                 -- Meta Ad ID (source_id)
    referral_headline VARCHAR(255),              -- Titular del anuncio
    referral_source_type VARCHAR(50),            -- 'ad' / etc.
    lead_id INT REFERENCES crm.leads(id) ON DELETE SET NULL,
    conversation_id INT REFERENCES crm.wa_conversations(id) ON DELETE SET NULL,
    outcome VARCHAR(50) NOT NULL,                -- 'lead_created', 'lead_matched', 'lead_matched_duplicate', 'lead_failed', 'message_received', 'duplicate_message', 'status_sent', 'status_delivered', 'status_read', 'status_failed', 'error'
    error_detail TEXT,                           -- Razón si falló o fue omitido
    metadata JSONB DEFAULT '{}'::jsonb,          -- Metadatos adicionales (asesor_id, campana, etc.)
    payload JSONB                                -- Objeto original recibido para auditoría forense
);

COMMENT ON TABLE crm.wa_webhook_events IS
    'V128: Auditoría continua y forense de webhooks de WhatsApp para conciliación Meta Ads vs CRM.';

CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_received ON crm.wa_webhook_events(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_phone ON crm.wa_webhook_events(wa_phone);
CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_wamid ON crm.wa_webhook_events(wamid);
CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_ad_id ON crm.wa_webhook_events(referral_ad_id) WHERE referral_ad_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_outcome ON crm.wa_webhook_events(outcome);
CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_has_referral ON crm.wa_webhook_events(has_referral) WHERE has_referral = TRUE;
CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_lead_id ON crm.wa_webhook_events(lead_id) WHERE lead_id IS NOT NULL;

-- Backfill histórico inicial desde crm.wa_messages si la tabla está vacía
INSERT INTO crm.wa_webhook_events (
    received_at, event_type, wa_phone, wamid,
    phone_number_id, display_phone_number, contact_name,
    has_referral, referral_ad_id, referral_headline, referral_source_type,
    lead_id, conversation_id, outcome, error_detail, metadata, payload
)
SELECT
    m.created_at AS received_at,
    CASE 
        WHEN m.direction = 'inbound' THEN 'inbound_message'
        ELSE 'outbound_message'
    END AS event_type,
    c.wa_phone,
    m.wa_message_id AS wamid,
    num.phone_number_id,
    num.display_phone AS display_phone_number,
    c.contact_name,
    (m.payload ? 'referral') AS has_referral,
    NULLIF(m.payload->'referral'->>'source_id', '') AS referral_ad_id,
    NULLIF(m.payload->'referral'->>'headline', '') AS referral_headline,
    NULLIF(m.payload->'referral'->>'source_type', '') AS referral_source_type,
    c.lead_id,
    c.id AS conversation_id,
    CASE
        WHEN m.payload ? 'referral' AND c.lead_id IS NOT NULL THEN 'lead_attributed'
        WHEN m.direction = 'inbound' THEN 'message_received'
        ELSE 'message_sent'
    END AS outcome,
    m.error_detail,
    jsonb_build_object(
        'historical_backfill', true,
        'msg_type', m.msg_type,
        'status', m.status
    ),
    m.payload
FROM crm.wa_messages m
JOIN crm.wa_conversations c ON c.id = m.conversation_id
LEFT JOIN crm.wa_numbers num ON num.id = m.wa_number_id
WHERE NOT EXISTS (SELECT 1 FROM crm.wa_webhook_events LIMIT 1)
ORDER BY m.id ASC;

COMMIT;


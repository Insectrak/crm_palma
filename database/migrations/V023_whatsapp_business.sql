-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V023 — WhatsApp Business Cloud API (POC)                              ║
-- ║                                                                        ║
-- ║ Tablas para integrar Meta Cloud API (oficial WhatsApp Business API):  ║
-- ║                                                                        ║
-- ║   1. crm.wa_conversations — una fila por numero (telefono remoto).    ║
-- ║      Guarda el estado de la ventana 24h y el lead asociado.           ║
-- ║                                                                        ║
-- ║   2. crm.wa_messages — un registro por mensaje (inbound/outbound).    ║
-- ║      Soporta texto, plantillas, interactivos, multimedia.             ║
-- ║                                                                        ║
-- ║   3. crm.wa_campaigns — campañas publicitarias (CTWA u offline).      ║
-- ║      Nombre, plataforma, ID de Meta, presupuesto.                     ║
-- ║                                                                        ║
-- ║   4. ALTER crm.leads — columnas de atribucion (campaign_id, ad_id,    ║
-- ║      headline, ctwa_clid) para trazabilidad de origen.                ║
-- ║                                                                        ║
-- ║ Todo IF NOT EXISTS / IDEMPOTENTE — seguro de re-ejecutar.             ║
-- ╚════════════════════════════════════════════════════════════════════════╝

-- ── 1) Campañas (atribucion) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.wa_campaigns (
    id            SERIAL       PRIMARY KEY,
    name          VARCHAR(200) NOT NULL,
    platform      VARCHAR(40)  NOT NULL DEFAULT 'facebook',
                  -- facebook | instagram | tiktok | google | qr | offline | other
    ad_id         VARCHAR(80),                  -- ID del anuncio en Meta (source_id)
    campaign_code VARCHAR(40),                  -- codigo usado en pre-filled msg [PROMO-ABR]
    start_date    DATE,
    end_date      DATE,
    budget        NUMERIC(12,2),
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT wa_campaigns_code_unico UNIQUE (campaign_code)
);

CREATE INDEX IF NOT EXISTS idx_wa_campaigns_ad_id
    ON crm.wa_campaigns (ad_id)
    WHERE ad_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_campaigns_active
    ON crm.wa_campaigns (active, created_at DESC);


-- ── 2) Conversaciones (una por numero remoto) ────────────────────────────
CREATE TABLE IF NOT EXISTS crm.wa_conversations (
    id                  BIGSERIAL    PRIMARY KEY,
    wa_phone            VARCHAR(30)  NOT NULL,     -- E164 sin "+"  ej: 51987654321
    lead_id             INTEGER
                        REFERENCES crm.leads(id)
                        ON DELETE SET NULL,
    asesor_id           UUID
                        REFERENCES auth.users(id)
                        ON DELETE SET NULL,
    contact_name        VARCHAR(200),              -- nombre que manda WhatsApp (profile.name)
    last_message_at     TIMESTAMPTZ,
    last_message_preview TEXT,
    unread_count        INTEGER      NOT NULL DEFAULT 0,
    window_expires_at   TIMESTAMPTZ,               -- 24h desde el ultimo msg del cliente
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT wa_conversations_phone_unico UNIQUE (wa_phone)
);

CREATE INDEX IF NOT EXISTS idx_wa_conversations_lead_id
    ON crm.wa_conversations (lead_id)
    WHERE lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_conversations_asesor_id
    ON crm.wa_conversations (asesor_id, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_wa_conversations_last_message
    ON crm.wa_conversations (last_message_at DESC NULLS LAST);


-- ── 3) Mensajes individuales ─────────────────────────────────────────────
--
-- NOTA DE ARQUITECTURA (2026-04):
-- El UNIQUE (wa_message_id) de abajo es el mecanismo actual de dedupe frente
-- a reintentos de webhooks de Meta (~7 dias de reintentos por mensaje).
-- Funciona bien a escala actual pero bloquea dos optimizaciones futuras:
--   1. Particionado BY RANGE (created_at) — PostgreSQL exige que la columna
--      de particion forme parte de todo UNIQUE, lo cual este constraint no
--      cumple (wa_message_id es global, no por ventana temporal).
--   2. Mover particiones frias a Volume cheap storage (EasyPanel) — requiere
--      tabla particionada primero.
-- Migracion profesional cuando llegue el momento: introducir una tabla
-- sidecar crm.wa_webhook_events (event_id PK + processed_at) al estilo
-- Stripe/Twilio/Segment, mover el dedupe alli, y recien entonces convertir
-- wa_messages a tabla particionada. Todo hot-swap, sin downtime.
CREATE TABLE IF NOT EXISTS crm.wa_messages (
    id              BIGSERIAL    PRIMARY KEY,
    conversation_id BIGINT       NOT NULL
                    REFERENCES crm.wa_conversations(id)
                    ON DELETE CASCADE,
    wa_message_id   VARCHAR(120),                  -- ID de Meta (wamid.XXX), nullable para outbound en cola
    direction       VARCHAR(10)  NOT NULL,         -- 'inbound' | 'outbound'
    msg_type        VARCHAR(30)  NOT NULL DEFAULT 'text',
                    -- text | template | interactive | image | audio | video | document | location
    content         TEXT,                          -- texto plano o caption
    payload         JSONB,                         -- payload completo (interactive, referral, media, etc.)
    status          VARCHAR(20)  NOT NULL DEFAULT 'received',
                    -- inbound: received
                    -- outbound: queued | sent | delivered | read | failed
    error_code      VARCHAR(40),
    error_detail    TEXT,
    sent_by_user_id UUID
                    REFERENCES auth.users(id)
                    ON DELETE SET NULL,
    timestamp       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT wa_messages_direction_chk CHECK (direction IN ('inbound','outbound')),
    CONSTRAINT wa_messages_wamid_unico   UNIQUE (wa_message_id)
);

CREATE INDEX IF NOT EXISTS idx_wa_messages_conversation
    ON crm.wa_messages (conversation_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_wa_messages_status
    ON crm.wa_messages (status)
    WHERE status IN ('queued','sent','failed');


-- ── 4) Atribucion en crm.leads ───────────────────────────────────────────
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS wa_campaign_id     INTEGER
        REFERENCES crm.wa_campaigns(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS wa_campaign_ad_id  VARCHAR(80),
    ADD COLUMN IF NOT EXISTS wa_campaign_headline TEXT,
    ADD COLUMN IF NOT EXISTS wa_ctwa_clid       VARCHAR(120),
    ADD COLUMN IF NOT EXISTS wa_referral_payload JSONB;

CREATE INDEX IF NOT EXISTS idx_leads_wa_campaign
    ON crm.leads (wa_campaign_id)
    WHERE wa_campaign_id IS NOT NULL;


-- ── 5) Trigger updated_at ────────────────────────────────────────────────
DROP TRIGGER IF EXISTS trg_wa_conversations_updated_at ON crm.wa_conversations;
CREATE TRIGGER trg_wa_conversations_updated_at
    BEFORE UPDATE ON crm.wa_conversations
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_wa_campaigns_updated_at ON crm.wa_campaigns;
CREATE TRIGGER trg_wa_campaigns_updated_at
    BEFORE UPDATE ON crm.wa_campaigns
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V024 — WhatsApp Classification (IA pipeline)                          ║
-- ║                                                                        ║
-- ║ Agrega columnas a crm.wa_conversations para almacenar la clasificacion ║
-- ║ que hace Ollama sobre el primer mensaje entrante:                      ║
-- ║                                                                        ║
-- ║   classification_status    — estado del pipeline (pending/...)         ║
-- ║   classification_category  — tipo de lead (cliente_potencial/spam/...) ║
-- ║   classification_confidence — score 0.0-1.0                            ║
-- ║   classification_interest  — tipo de interes (compra/alquiler/...)     ║
-- ║   classification_urgency   — prioridad (alta/media/baja)               ║
-- ║   classification_summary   — resumen corto del mensaje                 ║
-- ║   classification_raw       — respuesta cruda de Ollama (JSONB)         ║
-- ║   classification_attempts  — intentos (retry si falla)                 ║
-- ║   classified_at            — cuando se proceso                         ║
-- ║   classified_by_model      — que modelo se uso (qwen2.5:7b)            ║
-- ║                                                                        ║
-- ║ Todo idempotente — seguro de re-ejecutar.                             ║
-- ╚════════════════════════════════════════════════════════════════════════╝

ALTER TABLE crm.wa_conversations
    ADD COLUMN IF NOT EXISTS classification_status     VARCHAR(20) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS classification_category   VARCHAR(30),
    ADD COLUMN IF NOT EXISTS classification_confidence NUMERIC(3,2),
    ADD COLUMN IF NOT EXISTS classification_interest   VARCHAR(30),
    ADD COLUMN IF NOT EXISTS classification_urgency    VARCHAR(10),
    ADD COLUMN IF NOT EXISTS classification_summary    TEXT,
    ADD COLUMN IF NOT EXISTS classification_raw        JSONB,
    ADD COLUMN IF NOT EXISTS classification_attempts   INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS classified_at             TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS classified_by_model       VARCHAR(50);

-- Check constraints — valores validos
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'wa_conversations_class_status_chk'
    ) THEN
        ALTER TABLE crm.wa_conversations
            ADD CONSTRAINT wa_conversations_class_status_chk
            CHECK (classification_status IN (
                'pending','queued','classified','manual_review','archived','failed','skipped'
            ));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'wa_conversations_class_conf_chk'
    ) THEN
        ALTER TABLE crm.wa_conversations
            ADD CONSTRAINT wa_conversations_class_conf_chk
            CHECK (classification_confidence IS NULL
                   OR (classification_confidence >= 0 AND classification_confidence <= 1));
    END IF;
END $$;

-- Indices para filtrado en UI (bandejas por status)
CREATE INDEX IF NOT EXISTS idx_wa_conv_class_status
    ON crm.wa_conversations (classification_status, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_wa_conv_class_category
    ON crm.wa_conversations (classification_category)
    WHERE classification_category IS NOT NULL;

-- Retry queue: conversaciones en failed con attempts < 3 (para cron retry)
CREATE INDEX IF NOT EXISTS idx_wa_conv_class_retry
    ON crm.wa_conversations (classified_at NULLS FIRST)
    WHERE classification_status = 'failed' AND classification_attempts < 3;

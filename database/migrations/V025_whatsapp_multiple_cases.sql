-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V025 — WhatsApp Multiple Cases (un cliente, varios lotes en el tiempo) ║
-- ║                                                                        ║
-- ║ Modela el escenario inmobiliario: el mismo cliente vuelve a escribir   ║
-- ║ meses despues por un nuevo lote. Hasta V024 una conversacion (telefono)║
-- ║ tenia 1 sola atadura `lead_id` para siempre — el nuevo interes caia en ║
-- ║ la bandeja del asesor del caso viejo y la IA no reclasificaba.         ║
-- ║                                                                        ║
-- ║ Cambios:                                                               ║
-- ║   - Nueva tabla crm.wa_conversation_leads (N:M historico).             ║
-- ║     wa_conversations.lead_id sigue siendo el caso ACTIVO; el historial ║
-- ║     queda en esta tabla para que el chat muestre "Caso 1 / 2 / 3".     ║
-- ║   - Backfill: cada conversacion con lead_id se inserta como caso       ║
-- ║     activo (closed_at NULL).                                           ║
-- ║                                                                        ║
-- ║ Detras del modelo (no en este DDL):                                    ║
-- ║   - El webhook detecta lead terminal + inactividad y libera lead_id.   ║
-- ║   - wa_router_service crea lead nuevo via rotacion.                    ║
-- ║   - Cada link/unlink se loguea en wa_conversation_leads.               ║
-- ║                                                                        ║
-- ║ Idempotente — seguro de re-ejecutar.                                  ║
-- ╚════════════════════════════════════════════════════════════════════════╝

CREATE TABLE IF NOT EXISTS crm.wa_conversation_leads (
    id              BIGSERIAL    PRIMARY KEY,
    conversation_id BIGINT       NOT NULL
                    REFERENCES crm.wa_conversations(id)
                    ON DELETE CASCADE,
    lead_id         INTEGER      NOT NULL
                    REFERENCES crm.leads(id)
                    ON DELETE CASCADE,
    -- Cuando se creo este vinculo (apertura del caso)
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- Cuando dejo de ser el caso activo (NULL = vigente)
    closed_at       TIMESTAMPTZ,
    -- Origen del vinculo: para auditoria + diagnostico
    --   auto_classifier  → la IA clasifico el primer mensaje y creo el lead
    --   auto_terminal    → mensaje nuevo tras lead terminal + inactividad
    --   manual_user      → admin/supervisor/asesor uso "Nueva consulta"
    created_by      VARCHAR(20)  NOT NULL DEFAULT 'auto_classifier',
    -- Quien lo disparo (NULL si fue automatico)
    created_by_user UUID         REFERENCES auth.users(id) ON DELETE SET NULL,
    -- Texto libre — util para "Cliente pregunto por Lote 12 sector B"
    reason          TEXT,
    CONSTRAINT wa_conv_leads_unico       UNIQUE (conversation_id, lead_id),
    CONSTRAINT wa_conv_leads_origen_chk  CHECK (
        created_by IN ('auto_classifier', 'auto_terminal', 'manual_user')
    )
);

CREATE INDEX IF NOT EXISTS idx_wa_conv_leads_conv
    ON crm.wa_conversation_leads (conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wa_conv_leads_lead
    ON crm.wa_conversation_leads (lead_id);

-- Solo un caso activo (closed_at IS NULL) por conversacion
CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_conv_leads_active_unique
    ON crm.wa_conversation_leads (conversation_id)
    WHERE closed_at IS NULL;

-- Backfill: registramos como caso activo cada lead_id ya pegado a una
-- conversacion. ON CONFLICT DO NOTHING permite re-ejecutar la migracion.
INSERT INTO crm.wa_conversation_leads (conversation_id, lead_id, created_by)
SELECT id, lead_id, 'auto_classifier'
FROM crm.wa_conversations
WHERE lead_id IS NOT NULL
ON CONFLICT (conversation_id, lead_id) DO NOTHING;

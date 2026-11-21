-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V038 — Conversation Tags (etiquetas a nivel de conversación)          ║
-- ║                                                                        ║
-- ║ Motivacion: no toda conversacion es lead. Casos como soporte,         ║
-- ║ pregunta tecnica, spam, postventa o numero equivocado necesitan       ║
-- ║ categorizacion sin obligar a crear un lead inflando el embudo.        ║
-- ║                                                                        ║
-- ║ Modelo: las etiquetas viven en el catalogo crm.tags (V026). La        ║
-- ║ conversacion es la entidad raiz; el lead se "promueve" desde una      ║
-- ║ conversacion. Cuando eso pasa, las tags de la conversacion se         ║
-- ║ heredan automaticamente al lead via trigger. La direccion conv→lead   ║
-- ║ es one-way; tags agregadas directo al lead NO bajan a la conv.        ║
-- ║                                                                        ║
-- ║ Escalabilidad:                                                         ║
-- ║   - Composite PK (conversation_id, tag_id) bloquea duplicados a nivel ║
-- ║     de DB (no depende de la app).                                     ║
-- ║   - Indices en ambos lados para joins direccionales rapidos.          ║
-- ║   - Trigger AFTER UPDATE OF lead_id dispara solo cuando esa columna   ║
-- ║     cambia — Postgres lo evalua antes de invocar la funcion.          ║
-- ║   - ON CONFLICT DO NOTHING en la herencia: re-toma del mismo chat     ║
-- ║     no rompe ni duplica.                                              ║
-- ║                                                                        ║
-- ║ Idempotente — seguro de re-ejecutar.                                  ║
-- ╚════════════════════════════════════════════════════════════════════════╝

-- Relacion N:M conversation <-> tag
CREATE TABLE IF NOT EXISTS crm.wa_conversation_tags (
    conversation_id INTEGER     NOT NULL
                    REFERENCES crm.wa_conversations(id) ON DELETE CASCADE,
    tag_id          INTEGER     NOT NULL
                    REFERENCES crm.tags(id)             ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user UUID        REFERENCES auth.users(id) ON DELETE SET NULL,
    PRIMARY KEY (conversation_id, tag_id)
);

-- Indice tag → convs (para queries del tipo "que convs tienen tag X")
CREATE INDEX IF NOT EXISTS idx_wa_conversation_tags_tag
    ON crm.wa_conversation_tags (tag_id);

-- Indice conv → tags (para fetch del detalle de un chat)
CREATE INDEX IF NOT EXISTS idx_wa_conversation_tags_conv
    ON crm.wa_conversation_tags (conversation_id);

-- ── Trigger de herencia conversation → lead ──────────────────────────────
-- Se dispara cuando lead_id de una conversacion cambia (NULL → not-NULL,
-- o de un lead a otro). Copia las tags actuales de la conv al lead.
-- Idempotente: ON CONFLICT DO NOTHING. Las tags propias del lead no se tocan.
CREATE OR REPLACE FUNCTION crm.fn_inherit_conv_tags_to_lead()
RETURNS TRIGGER AS $$
BEGIN
    -- DISTINCT FROM maneja correctamente NULLs (NULL IS DISTINCT FROM 1 = TRUE)
    IF NEW.lead_id IS NOT NULL AND NEW.lead_id IS DISTINCT FROM OLD.lead_id THEN
        INSERT INTO crm.lead_tags (lead_id, tag_id, created_at, created_by_user)
        SELECT NEW.lead_id, ct.tag_id, ct.created_at, ct.created_by_user
        FROM crm.wa_conversation_tags ct
        WHERE ct.conversation_id = NEW.id
        ON CONFLICT (lead_id, tag_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop and recreate para que la migration sea idempotente cuando cambian
-- definiciones del trigger (ej. agregar columnas en el futuro).
DROP TRIGGER IF EXISTS trg_inherit_conv_tags_to_lead ON crm.wa_conversations;
CREATE TRIGGER trg_inherit_conv_tags_to_lead
AFTER UPDATE OF lead_id ON crm.wa_conversations
FOR EACH ROW
EXECUTE FUNCTION crm.fn_inherit_conv_tags_to_lead();

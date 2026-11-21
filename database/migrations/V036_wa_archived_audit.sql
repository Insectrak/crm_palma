-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V036 — Auditoria de archivo de conversaciones (estilo Salesforce)     ║
-- ║                                                                        ║
-- ║ Permite "descalificar" conversaciones que no son leads comerciales    ║
-- ║ (consultas generales, spam, duplicados) preservando trazabilidad.     ║
-- ║                                                                        ║
-- ║ Columnas:                                                              ║
-- ║   archived_reason  — enum corto (not_a_lead, spam, duplicate, other)  ║
-- ║   archived_notes   — nota libre del supervisor                        ║
-- ║   archived_by      — auth.users.id de quien archivo                   ║
-- ║   archived_at      — timestamp                                         ║
-- ║                                                                        ║
-- ║ El archivado lo hace el endpoint POST /conversations/{id}/archive.    ║
-- ║ classification_status pasa a 'archived' y estas columnas guardan el   ║
-- ║ contexto. List_conversations ya oculta archived del inbox por defecto.║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.wa_conversations
    ADD COLUMN IF NOT EXISTS archived_reason VARCHAR(32),
    ADD COLUMN IF NOT EXISTS archived_notes  TEXT,
    ADD COLUMN IF NOT EXISTS archived_by     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS archived_at     TIMESTAMPTZ;

COMMENT ON COLUMN crm.wa_conversations.archived_reason IS
    'Motivo de descalificacion: not_a_lead | spam | duplicate | no_response | other';

COMMENT ON COLUMN crm.wa_conversations.archived_by IS
    'Usuario (supervisor/admin) que archivo la conversacion.';

-- Guardrail: reason/by/at deben ser consistentes. Si el status es archived,
-- al menos archived_at debe estar seteado; si no esta archived, limpiamos.
CREATE INDEX IF NOT EXISTS idx_wa_conversations_archived_at
    ON crm.wa_conversations (archived_at)
    WHERE classification_status = 'archived';

COMMIT;

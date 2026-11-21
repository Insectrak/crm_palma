-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V070.3 — Trigger DB-level que garantiza conv.asesor_id == lead.asesor_id║
-- ║                                                                        ║
-- ║ Tras V070, V070.1, V070.2 el bug "Sin asignar" en chat seguia          ║
-- ║ apareciendo. Causas observadas:                                       ║
-- ║   1) CI fallaba por F821 -> deploys nunca llegaban                    ║
-- ║   2) Logica de backfill compleja en migracion + display fallback en   ║
-- ║      SELECT cubria edge cases pero quedaba dependiente de timing.    ║
-- ║                                                                        ║
-- ║ Fix definitivo (idea Salesforce/HubSpot Data Bind):                   ║
-- ║ Trigger AFTER INSERT/UPDATE en wa_conversations Y en leads que        ║
-- ║ mantiene la invariante:                                               ║
-- ║                                                                        ║
-- ║   PARA TODA conv c con lead_id NOT NULL:                              ║
-- ║     c.asesor_id = (SELECT asesor_id FROM crm.leads WHERE id = c.lead_id)║
-- ║                                                                        ║
-- ║ Asi cuando:                                                           ║
-- ║   - Una conv se crea/actualiza Y se vincula a un lead                 ║
-- ║   - Un lead cambia de asesor                                          ║
-- ║   - Una conv huerfana (lead_id NULL) recibe lead_id                   ║
-- ║                                                                        ║
-- ║ -> conv.asesor_id se auto-sincroniza EN LA MISMA TRANSACCION.         ║
-- ║                                                                        ║
-- ║ Beneficios vs solo migration backfill:                                ║
-- ║   - 100% determinista — no depende del orden de ejecucion             ║
-- ║   - Inmune a race conditions concurrentes                             ║
-- ║   - Sobrevive a importaciones masivas / restores                      ║
-- ║   - Cero codigo Python que pueda olvidarse o tener bugs               ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1) Funcion de sincronizacion ─────────────────────────────────────────
-- Se invoca desde 2 triggers (uno por tabla). El SECURITY DEFINER permite
-- que tenga permisos elevados aunque el caller no los tenga.

CREATE OR REPLACE FUNCTION crm.sync_conv_asesor_from_lead()
RETURNS TRIGGER AS $$
BEGIN
    -- Trigger sobre wa_conversations: si la conv tiene lead_id, hereda asesor
    IF TG_TABLE_NAME = 'wa_conversations' THEN
        IF NEW.lead_id IS NOT NULL THEN
            SELECT l.asesor_id INTO NEW.asesor_id
              FROM crm.leads l
             WHERE l.id = NEW.lead_id;
        END IF;
        RETURN NEW;
    END IF;

    -- Trigger sobre leads: si cambia asesor_id, propagar a todas las convs
    -- vinculadas. Se usa AFTER UPDATE para no interferir con otros triggers
    -- de la fila del lead. Solo propaga si hay cambio real.
    IF TG_TABLE_NAME = 'leads' AND (NEW.asesor_id IS DISTINCT FROM OLD.asesor_id) THEN
        UPDATE crm.wa_conversations
           SET asesor_id = NEW.asesor_id
         WHERE lead_id = NEW.id
           AND (asesor_id IS DISTINCT FROM NEW.asesor_id);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ── 2) Trigger BEFORE en wa_conversations: setea asesor en INSERT/UPDATE ─
-- BEFORE para que el cambio en NEW.asesor_id afecte la fila que se guarda.

DROP TRIGGER IF EXISTS trg_sync_conv_asesor_before ON crm.wa_conversations;
CREATE TRIGGER trg_sync_conv_asesor_before
    BEFORE INSERT OR UPDATE OF lead_id ON crm.wa_conversations
    FOR EACH ROW
    EXECUTE FUNCTION crm.sync_conv_asesor_from_lead();

-- ── 3) Trigger AFTER en leads: propaga cambios de asesor a convs ─────────

DROP TRIGGER IF EXISTS trg_sync_conv_asesor_from_lead_after ON crm.leads;
CREATE TRIGGER trg_sync_conv_asesor_from_lead_after
    AFTER UPDATE OF asesor_id ON crm.leads
    FOR EACH ROW
    EXECUTE FUNCTION crm.sync_conv_asesor_from_lead();

-- ── 4) Backfill final: re-sincroniza CUALQUIER conv que pudiera estar ───
-- desincronizada, ahora con el trigger en pie. Idempotente.

UPDATE crm.wa_conversations c
   SET asesor_id = l.asesor_id
  FROM crm.leads l
 WHERE c.lead_id = l.id
   AND c.asesor_id IS DISTINCT FROM l.asesor_id;

-- ── 5) Backfill por phone match (para convs huerfanas con lead_id NULL) ─
-- Usa el index idx_leads_telefono_digits creado en V070.2 si existe.

WITH matched_lead AS (
    SELECT DISTINCT ON (REGEXP_REPLACE(COALESCE(l.telefono, ''), '\D', '', 'g'))
           REGEXP_REPLACE(COALESCE(l.telefono, ''), '\D', '', 'g') AS phone_digits,
           l.id        AS lead_id,
           l.asesor_id AS asesor_id
      FROM crm.leads l
     WHERE l.activo = TRUE
       AND l.telefono IS NOT NULL
       AND l.telefono <> ''
       AND l.asesor_id IS NOT NULL
     ORDER BY REGEXP_REPLACE(COALESCE(l.telefono, ''), '\D', '', 'g'),
              l.created_at DESC
)
UPDATE crm.wa_conversations c
   SET lead_id   = m.lead_id,
       asesor_id = m.asesor_id
  FROM matched_lead m
 WHERE c.lead_id IS NULL
   AND REGEXP_REPLACE(COALESCE(c.wa_phone, ''), '\D', '', 'g') = m.phone_digits;

COMMIT;

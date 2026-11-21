-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V070.1 — Chat: backfill asesor para convs SIN lead_id (match por phone)║
-- ║                                                                        ║
-- ║ Extension de V070. La V070 backfilleo asesor solo cuando la conv ya    ║
-- ║ tenia c.lead_id linked. Pero hay convs que se crearon (via inbound o   ║
-- ║ via /conversations/open) con lead_id NULL aunque exista un lead con el ║
-- ║ MISMO telefono. Bug visible: el chat aparece "Sin asignar" aunque la   ║
-- ║ persona en /leads/{id} si tiene asesor.                                ║
-- ║                                                                        ║
-- ║ Fix: matchear wa_phone con crm.leads.telefono y heredar tanto el       ║
-- ║ lead_id como el asesor_id en una sola sentencia.                       ║
-- ║                                                                        ║
-- ║ Idempotente: las convs que ya tienen lead_id o asesor_id no se tocan.  ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- Match por wa_phone vs lead.telefono. Normalizamos ambos a digitos para
-- tolerar diferencias de formato (+51, espacios, parentesis, etc).
UPDATE crm.wa_conversations c
   SET lead_id    = matched.lead_id,
       asesor_id  = COALESCE(c.asesor_id, matched.asesor_id),
       updated_at = NOW()
  FROM (
        SELECT DISTINCT ON (REGEXP_REPLACE(COALESCE(l.telefono, ''), '\D', '', 'g'))
               REGEXP_REPLACE(COALESCE(l.telefono, ''), '\D', '', 'g') AS phone_digits,
               l.id        AS lead_id,
               l.asesor_id AS asesor_id
          FROM crm.leads l
         WHERE l.activo = TRUE
           AND l.telefono IS NOT NULL
           AND l.telefono <> ''
         ORDER BY REGEXP_REPLACE(COALESCE(l.telefono, ''), '\D', '', 'g'),
                  l.created_at DESC
        ) matched
 WHERE c.lead_id IS NULL
   AND REGEXP_REPLACE(COALESCE(c.wa_phone, ''), '\D', '', 'g') = matched.phone_digits
   AND matched.asesor_id IS NOT NULL;

COMMIT;

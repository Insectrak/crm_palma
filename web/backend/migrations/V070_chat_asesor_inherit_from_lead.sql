-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V070 — Chat: asesor heredado del lead cuando la conv no tiene uno     ║
-- ║                                                                        ║
-- ║ Bug reportado en prod (2026-05-13): leads con asesor asignado          ║
-- ║ (ej. Edwin Mayta -> Fabiola Gamero) aparecian como "Sin asignar"      ║
-- ║ en el chat de WhatsApp. Inconsistente con la lista de Leads y rompia  ║
-- ║ el flujo de coordinacion del equipo:                                  ║
-- ║   - Fabiola no veia el chat de Edwin en su bandeja                    ║
-- ║   - Otros asesores podian agarrar el chat por error                   ║
-- ║   - Reportes de carga por asesor no reflejaban actividad de WhatsApp  ║
-- ║                                                                        ║
-- ║ Causa: cuando un mensaje inbound llegaba y se vinculaba conv->lead,   ║
-- ║ se seteaba conv.lead_id pero NO se heredaba el asesor del lead.       ║
-- ║                                                                        ║
-- ║ Fix:                                                                   ║
-- ║   1) Backfill retroactivo (este SQL): set conv.asesor_id =            ║
-- ║      lead.asesor_id para todas las conv que tienen lead asociado     ║
-- ║      pero asesor NULL.                                                ║
-- ║   2) Codigo de runtime (whatsapp.py): cuando llega mensaje inbound,   ║
-- ║      el UPDATE de la conv incluye COALESCE(c.asesor_id, lead.asesor_id).║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── Backfill: heredar asesor del lead asociado ───────────────────────────
-- WHERE filtra solo las conv que efectivamente tienen un lead vinculado
-- Y donde el lead tiene asesor activo Y la conv esta huerfana de asesor.
-- Tambien actualizamos updated_at para que el frontend pueda detectar el
-- cambio si tiene cache local.

UPDATE crm.wa_conversations c
   SET asesor_id  = l.asesor_id,
       updated_at = NOW()
  FROM crm.leads l
 WHERE l.id = c.lead_id
   AND c.asesor_id IS NULL
   AND l.asesor_id IS NOT NULL;

-- Idempotente: si se re-ejecuta despues del primer run, el WHERE filtra
-- (c.asesor_id IS NULL) y no toca nada — ya tienen asesor.

COMMIT;

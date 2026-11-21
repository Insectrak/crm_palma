-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V085 — Agregar 'lead.recontacto' al CHECK de webhook_deliveries        ║
-- ║                                                                        ║
-- ║ Bug encontrado en lab brighton 2026-06-16: V084 agregó                ║
-- ║ EVENT_LEAD_RECONTACTO a webhook_service.ALL_EVENTS pero NO actualizó  ║
-- ║ el CHECK constraint de crm.webhook_deliveries.event_type.             ║
-- ║                                                                        ║
-- ║ Resultado: cuando enqueue_event hacía INSERT con event_type=          ║
-- ║ 'lead.recontacto', PostgreSQL rechazaba con error de constraint:      ║
-- ║   new row for relation "webhook_deliveries" violates check            ║
-- ║   constraint "webhook_deliveries_event_type_check"                    ║
-- ║ El except: del enqueue_event capturaba el error en silencio y         ║
-- ║ retornaba None. Por eso el proveedor nunca recibía push de            ║
-- ║ recontactos a pesar de tener el checkbox tildado.                     ║
-- ║                                                                        ║
-- ║ Idempotente: DROP CONSTRAINT IF EXISTS + ADD.                          ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.webhook_deliveries
    DROP CONSTRAINT IF EXISTS webhook_deliveries_event_type_check;

ALTER TABLE crm.webhook_deliveries
    ADD CONSTRAINT webhook_deliveries_event_type_check
    CHECK (event_type IN (
        'lead.received',
        'lead.assigned',
        'lead.reassigned',
        'lead.status_changed',
        'lead.recontacto'
    ));

COMMENT ON CONSTRAINT webhook_deliveries_event_type_check
    ON crm.webhook_deliveries IS
    'V085: catalogo cerrado de eventos webhook soportados. Editar requiere ALTER + actualizar webhook_service.ALL_EVENTS.';

COMMIT;

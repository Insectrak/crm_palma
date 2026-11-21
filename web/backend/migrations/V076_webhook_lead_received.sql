-- V076 — Nuevo evento de webhook `lead.received`.
--
-- Problema:
--   Hasta V058 los eventos eran lead.assigned / lead.reassigned /
--   lead.status_changed. Pero `lead.assigned` SOLO dispara cuando el lead
--   llega con asesor asignado al insertarse. Si entra al pool del
--   supervisor (sin asesor todavia), el proveedor externo NUNCA se
--   entera de que su lead llego al CRM hasta que un humano lo asigne.
--
--   Para proveedores que pagan por lead entregado (Wedo y similares),
--   esto es critico: necesitan confirmacion de que el lead fue recibido.
--
-- Solucion:
--   `lead.received` dispara siempre al crear el lead via ingest API
--   (independiente de si hay asesor asignado o no). El proveedor decide
--   si lo suscribe.
--
-- Idempotente: ALTER del CHECK constraint en webhook_deliveries.event_type.

BEGIN;

-- Drop CHECK viejo y re-crear con `lead.received` agregado.
-- ALTER ... DROP CONSTRAINT IF EXISTS no falla si nunca existio.
ALTER TABLE crm.webhook_deliveries
    DROP CONSTRAINT IF EXISTS webhook_deliveries_event_type_check;

ALTER TABLE crm.webhook_deliveries
    ADD CONSTRAINT webhook_deliveries_event_type_check
    CHECK (event_type IN (
        'lead.received',
        'lead.assigned',
        'lead.reassigned',
        'lead.status_changed'
    ));

COMMENT ON CONSTRAINT webhook_deliveries_event_type_check
    ON crm.webhook_deliveries IS
    'V076: catalogo cerrado de eventos webhook soportados. Editar requiere ALTER + actualizar webhook_service.ALL_EVENTS.';

COMMIT;

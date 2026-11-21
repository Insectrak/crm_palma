-- V075 — Buffer de notificaciones para coalescing (push aggregation).
--
-- Problema que resuelve:
--   Cuando entra un batch de leads (ej. Postman bulk de 50, o un dia
--   intenso de Meta/TikTok), el asesor recibe 50 push notifications
--   individuales con sonido cada una. UX horrible y patron anti-CRM.
--
-- Solucion (patron Slack/Gmail):
--   Cada notify_new_lead inserta una fila aqui en vez de enviar push
--   inmediato. Un worker corre cada 15s y decide:
--     - <3 leads para un asesor → push individual (1 por lead)
--     - >=3 leads para un asesor → 1 push agregada "Tienes 5 leads nuevos"
--   Excepcion: leads CALIENTE bypassean el buffer y se envian instantaneos
--   (velocidad > silencio para oportunidades hot).
--
-- Idempotente: CREATE TABLE IF NOT EXISTS. Indices con IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS crm.notification_buffer (
    id              BIGSERIAL    PRIMARY KEY,
    asesor_id       UUID         NOT NULL,
    lead_id         INTEGER      NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    lead_name       TEXT         NOT NULL DEFAULT '',
    fuente          TEXT         NOT NULL DEFAULT '',
    performed_by    UUID,
    enqueued_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    sent_at         TIMESTAMPTZ,
    batch_id        UUID,
    -- Modo de envio final: 'individual' (1 push) o 'batch' (push agregada).
    -- NULL mientras este pendiente, lo setea el worker al flushear.
    send_mode       TEXT
);

-- Idx para el query principal del worker: traer pendientes ordenados.
-- El predicate parcial (WHERE sent_at IS NULL) hace el indice mas chico
-- y rapido — solo indexa las pendientes, que en estado estable son pocas.
CREATE INDEX IF NOT EXISTS idx_notification_buffer_pending
    ON crm.notification_buffer (asesor_id, enqueued_at)
    WHERE sent_at IS NULL;

-- Idx para cleanup nocturno (DELETE de filas viejas ya enviadas).
CREATE INDEX IF NOT EXISTS idx_notification_buffer_sent_at
    ON crm.notification_buffer (sent_at)
    WHERE sent_at IS NOT NULL;

-- Anti-doble-envio: si por algun bug se intenta encolar 2 veces el mismo
-- lead para el mismo asesor mientras hay una pendiente, el unique parcial
-- lo previene. Una vez enviado (sent_at NOT NULL), el lead puede reentrar
-- al buffer si lo reasignan a otro asesor (caso valido).
CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_buffer_pending_lead
    ON crm.notification_buffer (asesor_id, lead_id)
    WHERE sent_at IS NULL;

COMMIT;

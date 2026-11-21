-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V058 — Outbound webhooks: notificar al proveedor cuando se asigna     ║
-- ║         o reasigna un lead                                              ║
-- ║                                                                        ║
-- ║ El proveedor (Wedo, agencias, etc.) entrega un lead via /api/ingest    ║
-- ║ y obtiene asesor_id en la respuesta. PERO si despues el supervisor    ║
-- ║ reasigna el lead a otro asesor, el proveedor no se entera.            ║
-- ║                                                                        ║
-- ║ Solucion: outbound webhooks (estilo Stripe / HubSpot CRM events):     ║
-- ║   1. Cada api_client puede registrar una webhook_url + secret         ║
-- ║   2. Cuando ocurre un evento suscripto, el CRM persiste un delivery  ║
-- ║      en webhook_deliveries con status='pending'.                      ║
-- ║   3. Un worker procesa los pendientes con retry exponencial:          ║
-- ║      1m -> 5m -> 30m -> 2h -> 12h (5 attempts, ~14h max).            ║
-- ║   4. Firma HMAC SHA-256 del payload con webhook_secret en header     ║
-- ║      X-Crm-Signature para que el proveedor verifique autenticidad.    ║
-- ║                                                                        ║
-- ║ Eventos soportados (extensible):                                       ║
-- ║   - lead.assigned        — primera asignacion de asesor              ║
-- ║   - lead.reassigned      — cambio de asesor (manual o automatico)    ║
-- ║   - lead.status_changed  — cambio de estado (Nuevo -> Contactado...)  ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─── 1) Config de webhook por api_client ──────────────────────────────────

ALTER TABLE crm.api_clients
    ADD COLUMN IF NOT EXISTS webhook_url       TEXT,
    ADD COLUMN IF NOT EXISTS webhook_secret    TEXT,
    ADD COLUMN IF NOT EXISTS webhook_events    TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS webhook_enabled   BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN crm.api_clients.webhook_url IS
    'V058: URL HTTPS del proveedor donde el CRM hace POST cuando ocurre un evento del lead. NULL = sin webhook.';
COMMENT ON COLUMN crm.api_clients.webhook_secret IS
    'V058: Secret aleatorio (32+ chars). El CRM firma el payload con HMAC-SHA256 y lo manda en X-Crm-Signature. El proveedor verifica.';
COMMENT ON COLUMN crm.api_clients.webhook_events IS
    'V058: Array de eventos suscriptos: lead.assigned, lead.reassigned, lead.status_changed. Vacio o NULL = nada.';
COMMENT ON COLUMN crm.api_clients.webhook_enabled IS
    'V058: Toggle para pausar deliveries sin perder la config (mantenimiento del proveedor, debugging, etc.).';


-- ─── 2) Tabla webhook_deliveries: cada intento de entrega ────────────────

CREATE TABLE IF NOT EXISTS crm.webhook_deliveries (
    id              BIGSERIAL       PRIMARY KEY,
    client_id       UUID            NOT NULL
                    REFERENCES crm.api_clients(id) ON DELETE CASCADE,
    lead_id         INTEGER         REFERENCES crm.leads(id) ON DELETE SET NULL,
    event_type      VARCHAR(40)     NOT NULL
                    CHECK (event_type IN (
                        'lead.assigned',
                        'lead.reassigned',
                        'lead.status_changed'
                    )),

    -- Payload firmado que se envia al proveedor
    payload         JSONB           NOT NULL,
    signature       TEXT,                                       -- HMAC-SHA256 hex (vacio hasta el primer attempt)

    -- Estado de la entrega
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'success', 'failed', 'retrying', 'dead')),
    attempt         INTEGER         NOT NULL DEFAULT 0,
    max_attempts    INTEGER         NOT NULL DEFAULT 5,
    next_retry_at   TIMESTAMPTZ,                                -- NULL = listo para procesar ahora

    -- Resultado del ultimo intento
    http_status     INTEGER,                                    -- 200, 4xx, 5xx, etc.
    response_body   TEXT,                                       -- truncado a 2k chars
    error_message   TEXT,                                       -- error de red / timeout

    -- Timestamps
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    last_attempt_at TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,                                -- success final
    duration_ms     INTEGER                                     -- tiempo del ultimo POST
);

-- Indice principal del worker: traer deliveries listos para procesar
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_pending
    ON crm.webhook_deliveries (next_retry_at, id)
    WHERE status IN ('pending', 'retrying');

-- Indice para UI de debugging por cliente
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_client_created
    ON crm.webhook_deliveries (client_id, created_at DESC);

-- Indice para drilldown desde un lead especifico
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_lead
    ON crm.webhook_deliveries (lead_id, created_at DESC)
    WHERE lead_id IS NOT NULL;

COMMENT ON TABLE crm.webhook_deliveries IS
    'V058: Cola de eventos salientes hacia api_clients con webhook configurado. Worker procesa pending/retrying con backoff exponencial.';
COMMENT ON COLUMN crm.webhook_deliveries.status IS
    'pending = nunca intentado; retrying = fallo y esperando proximo retry; success = entregado; failed = aun reintenta; dead = max_attempts agotado.';
COMMENT ON COLUMN crm.webhook_deliveries.signature IS
    'HMAC-SHA256 hex(payload_bytes) usando webhook_secret. Header X-Crm-Signature: sha256=<signature>.';

COMMIT;

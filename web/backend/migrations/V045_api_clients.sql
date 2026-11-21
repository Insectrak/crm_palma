-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V045 — API Clients (Multi-tenant ingest providers)                    ║
-- ║                                                                        ║
-- ║ Patron Salesforce Connected Apps / HubSpot Private Apps:              ║
-- ║ cada proveedor externo (agencia, partner, portal) tiene su propia     ║
-- ║ API key. Esto permite atribucion por proveedor, revocacion granular, ║
-- ║ rate limit individual, IP whitelist y audit trail completo.          ║
-- ║                                                                        ║
-- ║ HARDENING DE SEGURIDAD:                                               ║
-- ║   - Solo guardamos hash SHA-256 de la key (nunca la key en plano).   ║
-- ║   - api_key_prefix (8 chars) visible en logs sin comprometer secret. ║
-- ║   - fuente_id se asigna automaticamente (provider no puede mentir).  ║
-- ║   - api_client_id en cada lead = trazabilidad legal/comercial.       ║
-- ║   - api_client_logs guarda cada request (forensics).                 ║
-- ║   - api_client_idempotency previene duplicados por reintentos red.   ║
-- ║                                                                        ║
-- ║ FORMATO DE KEY (estilo Stripe / HubSpot):                             ║
-- ║   cli_<8charPrefix>_<32charSecret>                                   ║
-- ║   ej: cli_abcd1234_xY9KpL...                                         ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─── 1) Tabla principal: api_clients ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS crm.api_clients (
    id                      UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre                  VARCHAR(120)    NOT NULL,
    slug                    VARCHAR(60)     NOT NULL UNIQUE,
    api_key_hash            VARCHAR(64)     NOT NULL UNIQUE,    -- SHA-256 hex (64 chars)
    api_key_prefix          VARCHAR(20)     NOT NULL,           -- primeros 8 chars + 'cli_' = ~12-13 chars
    fuente_id               INTEGER         NOT NULL
                            REFERENCES crm.fuentes(id),
    activo                  BOOLEAN         NOT NULL DEFAULT TRUE,
    rate_limit_per_minute   INTEGER         NOT NULL DEFAULT 60
                            CHECK (rate_limit_per_minute > 0 AND rate_limit_per_minute <= 1000),
    ip_whitelist            TEXT[]                              DEFAULT NULL,   -- NULL = sin restriccion; array vacio = bloqueado
    contacto_email          VARCHAR(120),
    contacto_telefono       VARCHAR(40),
    notas                   TEXT,

    -- Metricas pre-agregadas (incrementales, evita full-scan en UI admin)
    total_leads             INTEGER         NOT NULL DEFAULT 0,
    leads_duplicados        INTEGER         NOT NULL DEFAULT 0,
    leads_rechazados        INTEGER         NOT NULL DEFAULT 0,
    ultimo_lead_at          TIMESTAMPTZ,

    expires_at              TIMESTAMPTZ,                        -- opcional: keys con caducidad
    revoked_at              TIMESTAMPTZ,                        -- soft revoke (key invalida + audit)

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_by              UUID            REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_clients_prefix
    ON crm.api_clients (api_key_prefix);

CREATE INDEX IF NOT EXISTS idx_api_clients_activo
    ON crm.api_clients (activo) WHERE activo = TRUE;

COMMENT ON TABLE crm.api_clients IS
    'Proveedores externos autorizados a ingestar leads. Una API key por proveedor para atribucion + revocacion individual.';
COMMENT ON COLUMN crm.api_clients.api_key_hash IS
    'SHA-256 hex de la key completa. Nunca guardamos la key en plano. Validacion con timing-safe compare.';
COMMENT ON COLUMN crm.api_clients.api_key_prefix IS
    'Primeros chars de la key (cli_xxxxxxxx). Visible en logs sin comprometer la key.';
COMMENT ON COLUMN crm.api_clients.fuente_id IS
    'Fuente FIJA asignada a leads de este proveedor. El provider NO puede sobrescribir esto en el body.';
COMMENT ON COLUMN crm.api_clients.ip_whitelist IS
    'Array de CIDRs/IPs permitidas. NULL = sin restriccion. Util para integraciones server-to-server.';


-- ─── 2) Trazabilidad: api_client_id en cada lead ───────────────────────────

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS api_client_id UUID
        REFERENCES crm.api_clients(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_leads_api_client
    ON crm.leads (api_client_id) WHERE api_client_id IS NOT NULL;

COMMENT ON COLUMN crm.leads.api_client_id IS
    'Si el lead vino por la API publica, ID del proveedor que lo envio. NULL = creado manual o por n8n con la key legacy.';


-- ─── 3) Audit log: cada request a /api/ingest/leads se loguea ──────────────

CREATE TABLE IF NOT EXISTS crm.api_client_logs (
    id              BIGSERIAL       PRIMARY KEY,
    api_client_id   UUID            REFERENCES crm.api_clients(id) ON DELETE SET NULL,
    api_key_prefix  VARCHAR(20),                                -- guardado por si el client_id se borra
    ip              INET,
    method          VARCHAR(10),
    path            VARCHAR(200),
    status_code     INTEGER,
    lead_id         INTEGER         REFERENCES crm.leads(id) ON DELETE SET NULL,
    duplicated      BOOLEAN         DEFAULT FALSE,
    error_msg       TEXT,
    idempotency_key VARCHAR(80),
    request_size    INTEGER,                                    -- bytes del body, para detectar abuso
    user_agent      VARCHAR(300),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_client_logs_client_time
    ON crm.api_client_logs (api_client_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_client_logs_ip_time
    ON crm.api_client_logs (ip, created_at DESC) WHERE ip IS NOT NULL;

COMMENT ON TABLE crm.api_client_logs IS
    'Audit trail de cada request a la API publica. Forensics, debugging, deteccion de abuso. TTL recomendado: 90 dias.';


-- ─── 4) Idempotency: Idempotency-Key dedup window de 24h ───────────────────

CREATE TABLE IF NOT EXISTS crm.api_client_idempotency (
    id              BIGSERIAL       PRIMARY KEY,
    api_client_id   UUID            NOT NULL REFERENCES crm.api_clients(id) ON DELETE CASCADE,
    idempotency_key VARCHAR(80)     NOT NULL,
    response_json   JSONB           NOT NULL,                   -- response cacheado
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT api_client_idempotency_uniq UNIQUE (api_client_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_api_client_idempotency_created
    ON crm.api_client_idempotency (created_at);

COMMENT ON TABLE crm.api_client_idempotency IS
    'Cache de respuestas por Idempotency-Key. TTL 24h: el job de limpieza borra registros viejos.';


-- ─── 5) Función helper: incrementar contadores atomicamente ───────────────

CREATE OR REPLACE FUNCTION crm.increment_api_client_metric(
    p_client_id UUID,
    p_total INTEGER DEFAULT 0,
    p_dup INTEGER DEFAULT 0,
    p_rej INTEGER DEFAULT 0
) RETURNS VOID AS $$
BEGIN
    UPDATE crm.api_clients
    SET total_leads      = total_leads + p_total,
        leads_duplicados = leads_duplicados + p_dup,
        leads_rechazados = leads_rechazados + p_rej,
        ultimo_lead_at   = CASE WHEN p_total > 0 THEN NOW() ELSE ultimo_lead_at END,
        updated_at       = NOW()
    WHERE id = p_client_id;
END;
$$ LANGUAGE plpgsql;

COMMIT;

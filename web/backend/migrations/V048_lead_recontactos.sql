-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V048 — Lead Re-engagement (Recapture pattern)                         ║
-- ║                                                                        ║
-- ║ Cuando un lead duplicado entra al CRM (mismo telefono ya existe),     ║
-- ║ antes simplemente se descartaba. Ahora:                                ║
-- ║                                                                        ║
-- ║   1. Se registra el recontacto en lead_recontactos (audit trail)      ║
-- ║   2. Si el asesor original sigue activo → se mantiene + push          ║
-- ║   3. Si el asesor original NO esta activo → se libera (routing)       ║
-- ║                                                                        ║
-- ║ Patron Salesforce 'Lead Recapture' / HubSpot 'Re-engagement'.         ║
-- ║ Premia el rapport ya construido sin perder la senal comercial de que ║
-- ║ el cliente volvio a interesarse.                                      ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

CREATE TABLE IF NOT EXISTS crm.lead_recontactos (
    id                  BIGSERIAL       PRIMARY KEY,
    lead_id             INTEGER         NOT NULL
                        REFERENCES crm.leads(id) ON DELETE CASCADE,
    -- De donde vino el lead esta vez (puede ser distinta a la fuente original)
    fuente_id           INTEGER         REFERENCES crm.fuentes(id) ON DELETE SET NULL,
    api_client_id       UUID            REFERENCES crm.api_clients(id) ON DELETE SET NULL,
    campana             TEXT,
    fuente_externa_id   TEXT,
    -- Snapshot del asesor en el momento del recontacto
    asesor_mantenido    UUID            REFERENCES auth.users(id) ON DELETE SET NULL,
    asesor_anterior     UUID            REFERENCES auth.users(id) ON DELETE SET NULL,
    estrategia          VARCHAR(40)     NOT NULL,
    -- 'mantener_asesor'    = el asesor original sigue activo y le contacto
    -- 'liberar_inactivo'   = el asesor original ya no esta (is_active=FALSE)
    -- 'liberar_sin_contacto'= asesor activo pero nunca lo contacto (RR normal)
    -- 'sin_asesor_original'= el lead no tenia asesor (caso raro)
    estado_lead_anterior VARCHAR(40),                       -- p.ej. 'Ganado', 'Perdido' al momento del recontacto
    estado_lead_nuevo    VARCHAR(40),                       -- si se reactivo
    notificado          BOOLEAN         NOT NULL DEFAULT FALSE,
    notificacion_enviada_at TIMESTAMPTZ,
    razon               TEXT,                                -- explicacion human-readable
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_recontactos_lead
    ON crm.lead_recontactos (lead_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lead_recontactos_asesor
    ON crm.lead_recontactos (asesor_mantenido, created_at DESC)
    WHERE asesor_mantenido IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lead_recontactos_fecha
    ON crm.lead_recontactos (created_at DESC);

COMMENT ON TABLE crm.lead_recontactos IS
    'Historial de recontactos: cada vez que un lead duplicado vuelve a entrar al CRM. Permite trazabilidad + visualizacion + analitica de re-engagement.';
COMMENT ON COLUMN crm.lead_recontactos.estrategia IS
    'Decision del motor: mantener_asesor | liberar_inactivo | liberar_sin_contacto | sin_asesor_original.';

-- Vista helper: cuantos recontactos por lead (denormalizado para listados)
CREATE OR REPLACE VIEW crm.vw_leads_recontactos_count AS
SELECT lead_id, COUNT(*)::int AS total_recontactos,
       MAX(created_at)        AS ultimo_recontacto_at
FROM crm.lead_recontactos
GROUP BY lead_id;

COMMIT;

-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V062 — Trazabilidad post-unlink del proveedor (legacy slug+nombre)    ║
-- ║                                                                        ║
-- ║ Antes: cuando admin ejecutaba 'Desvincular leads' del proveedor X,    ║
-- ║   crm.leads.api_client_id quedaba en NULL y se PERDIA toda la traza.  ║
-- ║   Era imposible saber despues 'estos leads vinieron originalmente de  ║
-- ║   Wedo aunque ya no este el cliente en api_clients'.                  ║
-- ║                                                                        ║
-- ║ Solucion: dos campos snapshot que se llenan al desvincular y          ║
-- ║   sobreviven incluso si se borra el api_client:                       ║
-- ║     - api_client_legacy_slug:    'wedo' (slug original)               ║
-- ║     - api_client_legacy_nombre:  'Wedo' (nombre legible original)     ║
-- ║                                                                        ║
-- ║ Patron Salesforce 'archived owner' / HubSpot 'historical attribution'.║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS api_client_legacy_slug   VARCHAR(60),
    ADD COLUMN IF NOT EXISTS api_client_legacy_nombre VARCHAR(120);

COMMENT ON COLUMN crm.leads.api_client_legacy_slug IS
    'V062: Slug del proveedor que entrego este lead originalmente, snapshotado al desvincular (api_client_id -> NULL). Sobrevive al borrado del proveedor — sirve para reportes historicos de atribucion comercial.';
COMMENT ON COLUMN crm.leads.api_client_legacy_nombre IS
    'V062: Nombre legible del proveedor original (ej: "Wedo"). Snapshot al unlink, no se actualiza si el cliente cambia despues su nombre.';

-- Indice parcial para reportes "leads que vinieron de Wedo" (historico)
CREATE INDEX IF NOT EXISTS idx_leads_legacy_slug
    ON crm.leads (api_client_legacy_slug)
    WHERE api_client_legacy_slug IS NOT NULL AND activo = TRUE;

COMMIT;

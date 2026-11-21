-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V053 — Campos adicionales para integracion con proveedores IA          ║
-- ║                                                                        ║
-- ║ Habilita que proveedores externos (We Do, similares) entreguen leads  ║
-- ║ pre-calificados con la jerarquia completa de Meta Ads + transcripcion ║
-- ║ de la conversacion con la IA del proveedor.                           ║
-- ║                                                                        ║
-- ║ Columnas nuevas en crm.leads (todas opcionales, retrocompatibles):    ║
-- ║   - anuncio    : nivel Ad de Meta (anuncio especifico que vio el lead)║
-- ║   - conjunto   : nivel Ad Set de Meta (agrupacion segmentada)         ║
-- ║   - resumen_ia : transcripcion / resumen de conversacion previa       ║
-- ║                                                                        ║
-- ║ Indices parciales sobre anuncio y conjunto para reportes de attribution║
-- ║ de marketing sin scan completo.                                       ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS anuncio    TEXT,
    ADD COLUMN IF NOT EXISTS conjunto   TEXT,
    ADD COLUMN IF NOT EXISTS resumen_ia TEXT;

CREATE INDEX IF NOT EXISTS idx_leads_anuncio
    ON crm.leads (anuncio)
    WHERE anuncio IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_conjunto
    ON crm.leads (conjunto)
    WHERE conjunto IS NOT NULL;

COMMENT ON COLUMN crm.leads.anuncio IS
    'V053: Nivel Ad de Meta Ads — nombre del anuncio especifico que el cliente vio (ej. "LEAD AD - FACHADA").';
COMMENT ON COLUMN crm.leads.conjunto IS
    'V053: Nivel Ad Set de Meta Ads — agrupacion de anuncios con segmentacion comun (audiencia, geo, etc).';
COMMENT ON COLUMN crm.leads.resumen_ia IS
    'V053: Resumen / transcripcion de la conversacion previa con la IA del proveedor externo, si aplica.';

COMMIT;

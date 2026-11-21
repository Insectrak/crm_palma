-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V084 — Atribución Meta-level por recontacto                           ║
-- ║                                                                        ║
-- ║ Problema reportado por proveedor: cuando un lead que ya existe (ej.   ║
-- ║ entró hace 1 año por Google) vuelve a interactuar con una campaña    ║
-- ║ NUEVA de Meta (con anuncio + ad set específicos), esa atribución    ║
-- ║ del recontacto se perdía: el ingest solo persistía `campana` y      ║
-- ║ descartaba `anuncio`, `conjunto`, `fuente_form_id` del payload.       ║
-- ║                                                                        ║
-- ║ Resultado: imposible analizar qué campaña/ad/adset está reactivando  ║
-- ║ leads viejos. Sin esta data el equipo de marketing no puede medir    ║
-- ║ ROI de retargeting sobre la base existente.                           ║
-- ║                                                                        ║
-- ║ Patrón Salesforce/HubSpot: la atribución del lead original (`crm.   ║
-- ║ leads.campana/anuncio/conjunto`) se respeta y NO se pisa. Cada       ║
-- ║ recontacto guarda SU propia atribución en `crm.lead_recontactos`.    ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.lead_recontactos
    ADD COLUMN IF NOT EXISTS anuncio        TEXT,
    ADD COLUMN IF NOT EXISTS conjunto       TEXT,
    ADD COLUMN IF NOT EXISTS fuente_form_id TEXT;

COMMENT ON COLUMN crm.lead_recontactos.anuncio IS
    'Nivel Ad de Meta del recontacto (ej. nombre o id del anuncio). NULL si el proveedor no lo declara.';
COMMENT ON COLUMN crm.lead_recontactos.conjunto IS
    'Nivel Ad Set de Meta del recontacto. NULL si el proveedor no lo declara.';
COMMENT ON COLUMN crm.lead_recontactos.fuente_form_id IS
    'Form ID de Meta del recontacto. Permite JOIN contra meta_catalog_cache para nombre legible.';

COMMIT;

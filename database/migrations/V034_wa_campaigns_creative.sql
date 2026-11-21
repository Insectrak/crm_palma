-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V034 — Creative body/title en crm.wa_campaigns                         ║
-- ║                                                                        ║
-- ║ El ad CTWA tiene DOS textos distintos que necesitamos diferenciar:    ║
-- ║   - ad.name             → nombre interno del ad en Ads Manager        ║
-- ║                            (ej: 'TEST-CRM-AD-MENSAJE-01')             ║
-- ║   - ad.creative.body    → cuerpo del post / copy publicitario         ║
-- ║                            (ej: 'Gestiona tus PDF bien y...')         ║
-- ║                                                                        ║
-- ║ Antes confundiamos uno con otro porque solo guardabamos `ad_name`.    ║
-- ║ Estas columnas permiten que el banner del chat muestre el copy real   ║
-- ║ del anuncio (lo que vio el cliente cuando hizo click) sin confundir   ║
-- ║ con el nombre interno operativo.                                      ║
-- ╚════════════════════════════════════════════════════════════════════════╝

ALTER TABLE crm.wa_campaigns
    ADD COLUMN IF NOT EXISTS creative_body  TEXT,
    ADD COLUMN IF NOT EXISTS creative_title TEXT;

COMMENT ON COLUMN crm.wa_campaigns.creative_body IS
    'Cuerpo del post / copy publicitario (ad.creative.body de Graph API). Es lo que vio el cliente.';
COMMENT ON COLUMN crm.wa_campaigns.creative_title IS
    'Titulo del creative (ad.creative.title de Graph API). Suele ser corto.';

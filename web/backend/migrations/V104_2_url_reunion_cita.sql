-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V104 — URL de Reunión Virtual en Citas (Meet, Zoom, etc.)             ║
-- ║                                                                        ║
-- ║ MOTIVO:                                                                ║
-- ║ Permitir almacenar y consultar el enlace de videollamada (Google Meet,  ║
-- ║ Zoom, Teams, etc.) cuando una cita tiene modalidad virtual.            ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.contactos
    ADD COLUMN IF NOT EXISTS url_reunion TEXT;

COMMENT ON COLUMN crm.contactos.url_reunion IS 'URL de la reunión virtual (Meet, Zoom, Teams, etc.) cuando la cita es virtual.';

COMMIT;

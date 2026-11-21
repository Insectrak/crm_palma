-- V073 — Override personal del bypass de quiet_hours para eventos URGENT.
--
-- Patron Salesforce Mobile DND ("Allowed Senders / Allowed Types").
-- En V070.87 se marcaron lead_created y wa_message_inbound como URGENT
-- (bypassean quiet_hours globalmente). Esta migracion permite que cada
-- usuario revierta ese bypass para los eventos que prefiera.
--
-- Semantica del campo `urgent_events_disabled`:
--   - Array de event_types que estan en URGENT_EVENTS pero que el usuario
--     decidio QUE SI respeten su quiet_hours personal.
--   - Default []: comportamiento global (todos los URGENT bypassean).
--   - Ejemplo: ["lead_created"] → el user respeta quiet_hours para leads
--     nuevos (no le llegan push de madrugada), pero sigue recibiendo
--     wa_message_inbound aunque este en silencio.
--
-- NO permite el sentido inverso (marcar como urgent un evento que no lo
-- es globalmente) — eso seria feature futura. La asimetria es deliberada:
-- evitamos que un user se asigne pushes urgent sobre eventos que el admin
-- considera no-criticos.

ALTER TABLE auth.user_notification_prefs
    ADD COLUMN IF NOT EXISTS urgent_events_disabled JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN auth.user_notification_prefs.urgent_events_disabled IS
'V073: Array JSON de event_types que el user pidio que respeten su quiet_hours, aunque sean URGENT globalmente (Salesforce DND-style override). Default [] = comportamiento global (todos los URGENT bypassean quiet_hours).';

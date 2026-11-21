-- V071 — Preferencias de notificaciones por usuario.
--
-- Cada asesor puede personalizar sus push notifications (paridad
-- Salesforce/HubSpot Notification Preferences per-user):
--   - push_enabled: kill switch general (por defecto TRUE)
--   - quiet_hours_*: override del rango global. NULL = usa el global.
--   - events_disabled: lista de event_types donde el user no quiere push.
--
-- Tabla idempotente: re-run no falla. FK a auth.users con CASCADE para
-- limpieza automatica si el usuario se elimina.

CREATE TABLE IF NOT EXISTS auth.user_notification_prefs (
    user_id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    push_enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    quiet_hours_enabled  BOOLEAN,          -- NULL = usar el global
    quiet_hours_start    VARCHAR(5),       -- HH:MM, NULL = usar el global
    quiet_hours_end      VARCHAR(5),       -- HH:MM, NULL = usar el global
    events_disabled      JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Comentarios para auto-doc en pgAdmin / DBeaver.
COMMENT ON TABLE  auth.user_notification_prefs IS 'Preferencias de push por usuario (override del global app_settings.notifications_config).';
COMMENT ON COLUMN auth.user_notification_prefs.push_enabled        IS 'Kill switch general. Si FALSE, ningun push se envia a este user.';
COMMENT ON COLUMN auth.user_notification_prefs.quiet_hours_enabled IS 'NULL = usar el toggle global. TRUE/FALSE = override personal.';
COMMENT ON COLUMN auth.user_notification_prefs.quiet_hours_start   IS 'HH:MM hora Lima. NULL = usar el global.';
COMMENT ON COLUMN auth.user_notification_prefs.quiet_hours_end     IS 'HH:MM hora Lima. NULL = usar el global.';
COMMENT ON COLUMN auth.user_notification_prefs.events_disabled     IS 'Array JSON de event_types donde el user no quiere push (ej: ["lead_reassigned"]).';

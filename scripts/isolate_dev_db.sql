-- ============================================================================
-- isolate_dev_db.sql
-- Aísla una copia local de producción de cualquier integración saliente real
-- (webhooks a terceros, SMTP/correos, Push FCM, credenciales externas, WhatsApp).
-- Ejecutar SOLO en entornos locales/dev después de restaurar un dump.
-- ============================================================================

BEGIN;

-- 1. Cortar todos los webhooks salientes de api_clients (ej. wedo)
UPDATE crm.api_clients
SET webhook_enabled = FALSE,
    webhook_url     = NULL
WHERE webhook_enabled = TRUE
   OR webhook_url IS NOT NULL;

UPDATE crm.webhook_deliveries
SET status = 'dead'
WHERE status IN ('pending', 'retrying');

-- 2. Desactivar Push Notifications (FCM) y limpiar tokens de dispositivos reales
UPDATE public.app_settings
SET value      = '{"enabled": false}'::jsonb,
    updated_at = NOW()
WHERE key = 'fcm_credentials';

TRUNCATE TABLE auth.user_fcm_tokens;

-- 3. Limpiar configuración SMTP para impedir envío de correos reales
DELETE FROM public.app_settings
WHERE key = 'smtp_config';

-- 4. Limpiar credenciales externas (TikTok / Meta / WhatsApp) si existieran
TRUNCATE TABLE crm.integrations_credentials;
UPDATE crm.wa_babas SET activo = FALSE WHERE activo = TRUE;
UPDATE crm.wa_numbers SET activo = FALSE WHERE activo = TRUE;

COMMIT;

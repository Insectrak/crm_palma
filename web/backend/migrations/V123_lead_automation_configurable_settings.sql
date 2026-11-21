-- ║ V123 — Configuración Dinámica de Automatizaciones de Estados ║
-- Propósito:
-- Permite que las automatizaciones de estados no dependan de reglas ni nombres
-- fijos hardcodeados, sino de la configuración administrable en public.app_settings.
-- Por defecto se inicia DESHABILITADO (enabled: false) a petición de administración.

BEGIN;

CREATE TABLE IF NOT EXISTS public.app_settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Si no existe la configuración, insertar valor inicial deshabilitado (enabled = false)
INSERT INTO public.app_settings (key, value, updated_at)
VALUES (
    'lead_automation_config',
    jsonb_build_object(
        'enabled', FALSE,
        'reglas_intentos', jsonb_build_array(),
        'reglas_tiempo', jsonb_build_array(),
        'excluir_contacto_efectivo', TRUE,
        'respetar_gestion_admin', TRUE
    ),
    NOW()
)
ON CONFLICT (key) DO NOTHING;

COMMIT;

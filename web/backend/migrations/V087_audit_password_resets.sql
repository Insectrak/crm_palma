-- ============================================================================
-- V087 — Audit log de envíos de correo de restablecimiento de contraseña
--
-- Cumplimiento Ley 29733 PE (Protección de Datos Personales): registrar quién
-- inició el flujo de reseteo de credenciales sobre cada usuario, desde qué IP
-- y cuándo. Permite responder ante una solicitud ARCO o investigar abusos
-- de la función de admin (ej. admin malicioso intentando tomar cuentas).
--
-- Diseño:
--   - target_user_email + actor_email denormalizados → el registro sobrevive
--     si después se eliminan los usuarios (clave para forensia).
--   - email_sent boolean → registra si el SMTP aceptó el envío. Si False,
--     queda evidencia de intentos fallidos (útil para diagnosticar problemas
--     de configuración SMTP que se reportan después).
--   - smtp_error TEXT NULL → si email_sent=False, guarda el motivo (truncado
--     a 500 chars) para diagnóstico sin necesidad de revisar logs.
--   - ip_address + user_agent → forensia regulatoria.
--
-- Multi-tenant safe: no asume nada del cliente. Se replica idéntica por tenant.
-- ============================================================================

CREATE TABLE IF NOT EXISTS auth.audit_password_resets (
    id                  BIGSERIAL PRIMARY KEY,

    -- A quién se le envió el reset (denormalizado)
    target_user_id      UUID,
    target_user_email   VARCHAR(120),

    -- Quién pidió el envío (admin que apretó el botón)
    actor_user_id       UUID,
    actor_email         VARCHAR(120),

    -- Resultado del envío
    email_sent          BOOLEAN NOT NULL DEFAULT FALSE,
    smtp_error          VARCHAR(500),

    -- Forensia
    ip_address          VARCHAR(45),
    user_agent          TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para queries típicas:
--   "todos los resets pedidos en la última semana"
CREATE INDEX IF NOT EXISTS ix_audit_pw_resets_created_at
    ON auth.audit_password_resets (created_at DESC);

--   "todos los resets pedidos para este usuario" (forensia ARCO)
CREATE INDEX IF NOT EXISTS ix_audit_pw_resets_target
    ON auth.audit_password_resets (target_user_id, created_at DESC);

--   "todos los resets que pidió este admin"
CREATE INDEX IF NOT EXISTS ix_audit_pw_resets_actor
    ON auth.audit_password_resets (actor_user_id, created_at DESC);

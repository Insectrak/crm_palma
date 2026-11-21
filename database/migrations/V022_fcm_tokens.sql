-- V022_fcm_tokens.sql — Tabla para almacenar tokens FCM por dispositivo
-- Permite push instantaneo via Firebase Cloud Messaging

CREATE TABLE IF NOT EXISTS auth.user_fcm_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    fcm_token   TEXT NOT NULL,
    device_info TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(fcm_token)  -- un token pertenece a un solo dispositivo
);

CREATE INDEX IF NOT EXISTS idx_fcm_tokens_user_id
    ON auth.user_fcm_tokens(user_id);

COMMENT ON TABLE auth.user_fcm_tokens IS
    'Tokens FCM por usuario/dispositivo para push instantaneo';

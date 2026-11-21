-- Migration 07: Invitations table for email-based user registration
-- Schema: auth (junto a auth.users — sistema activo)
-- Tabla: auth.invitations
-- El campo invited_by referencia auth.users.id (UUID) para trazabilidad completa.

CREATE TABLE IF NOT EXISTS auth.invitations (
    id          SERIAL      PRIMARY KEY,
    email       TEXT        NOT NULL,
    role        TEXT        NOT NULL DEFAULT 'asesor',  -- rol que tendrá el nuevo usuario
    token       TEXT        NOT NULL UNIQUE,
    invited_by  UUID        NOT NULL                    -- FK a auth.users.id del admin que invitó
                REFERENCES auth.users(id)
                ON DELETE RESTRICT,
    expires_at  TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,                            -- NULL = pendiente
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT invitations_role_check CHECK (
        role IN ('admin', 'supervisor', 'asesor')
    )
);

COMMENT ON TABLE  auth.invitations              IS 'Invitaciones para registro de nuevos usuarios vía email.';
COMMENT ON COLUMN auth.invitations.role         IS 'Rol asignado al usuario al aceptar la invitación: admin, supervisor, asesor.';
COMMENT ON COLUMN auth.invitations.invited_by   IS 'FK a auth.users.id. El admin que generó la invitación.';
COMMENT ON COLUMN auth.invitations.accepted_at  IS 'NULL = invitación pendiente. Fecha de aceptación cuando el usuario registra su cuenta.';

CREATE INDEX IF NOT EXISTS idx_invitations_token
    ON auth.invitations (token) WHERE accepted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_invitations_email
    ON auth.invitations (email);

CREATE INDEX IF NOT EXISTS idx_invitations_invited_by
    ON auth.invitations (invited_by);

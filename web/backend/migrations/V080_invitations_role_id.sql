-- ============================================================================
-- V080 — Soporte de role_id en invitaciones (ADR-0011 follow-up)
--
-- El flujo "Invitar a un usuario" del CRM usa auth.invitations. Hasta V078
-- la tabla solo tenía `role` text con CHECK constraint a 3 valores legacy
-- (admin/supervisor/asesor). Para soportar invitaciones con rol custom
-- (marketing, proveedor_externo, etc) sin perder los flujos legacy:
--
--   1. Drop del CHECK constraint estricto (lo movemos a validación de código,
--      con coexistencia legacy + custom).
--   2. Agregar columna role_id NULL → FK a auth.roles. Cuando viene seteada,
--      al aceptar la invitación se asigna también role_id al usuario.
--
-- Idempotente: tabla puede no existir todavía (la crea POST /auth/invite),
-- el ALTER usa IF EXISTS.
-- ============================================================================

-- 1. Quitar el CHECK constraint estricto (si existe)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.constraint_column_usage
        WHERE table_schema = 'auth'
          AND table_name = 'invitations'
          AND constraint_name = 'invitations_role_check'
    ) THEN
        ALTER TABLE auth.invitations DROP CONSTRAINT invitations_role_check;
    END IF;
END $$;

-- 2. Agregar role_id si la tabla ya existe (la crea idempotentemente el
--    endpoint /auth/invite, así que si todavía no se invitó a nadie en este
--    deploy no existe — el bloque DO no hace nada).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'invitations'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'invitations' AND column_name = 'role_id'
    ) THEN
        ALTER TABLE auth.invitations
            ADD COLUMN role_id INTEGER NULL REFERENCES auth.roles(id) ON DELETE SET NULL;
        CREATE INDEX ix_invitations_role_id ON auth.invitations (role_id);
    END IF;
END $$;

-- ============================================================================
-- V078 — Sistema de roles + permisos granulares (ADR-0011)
--
-- Reusa el patrón validado en el producto hermano DoctorMuelita:
--   - Tabla auth.roles con columna `permissions` JSONB
--   - Permission keys flat: 'leads.view', 'reportes.export', etc.
--   - auth.users.role_id (FK opcional, NULL = usa rol legacy)
--   - Admin sigue siendo bypass (compat con sistema actual)
--
-- Coexiste con `auth.users.role` (TEXT) sin tocarlo — Strangler Pattern.
-- ============================================================================

-- ── 1. Tabla auth.roles ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS auth.roles (
    id            SERIAL PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,
    description   TEXT,
    permissions   JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_external   BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE = scope por api_client_id
    is_builtin    BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE = no se puede borrar
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_roles_name ON auth.roles (name);

-- Trigger para mantener updated_at
CREATE OR REPLACE FUNCTION auth.roles_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_roles_updated_at ON auth.roles;
CREATE TRIGGER trg_roles_updated_at
    BEFORE UPDATE ON auth.roles
    FOR EACH ROW EXECUTE FUNCTION auth.roles_set_updated_at();

-- ── 2. auth.users.role_id (FK opcional) ─────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'users' AND column_name = 'role_id'
    ) THEN
        ALTER TABLE auth.users
            ADD COLUMN role_id INTEGER NULL REFERENCES auth.roles(id) ON DELETE SET NULL;
        CREATE INDEX ix_users_role_id ON auth.users (role_id);
    END IF;
END $$;

-- auth.users.api_client_id (para roles externos tipo proveedor)
-- Reusa el concepto de crm.api_clients (V045): un usuario externo puede
-- estar linkeado a un proveedor y solo ver sus propios leads.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'auth' AND table_name = 'users' AND column_name = 'api_client_id'
    ) THEN
        ALTER TABLE auth.users
            ADD COLUMN api_client_id UUID NULL;
        -- FK al api_client si la tabla existe (V045+). Sin error si no existe.
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'crm' AND table_name = 'api_clients'
        ) THEN
            ALTER TABLE auth.users
                ADD CONSTRAINT fk_users_api_client
                FOREIGN KEY (api_client_id) REFERENCES crm.api_clients(id) ON DELETE SET NULL;
        END IF;
        CREATE INDEX ix_users_api_client_id ON auth.users (api_client_id);
    END IF;
END $$;

-- ── 3. Seed de roles built-in (matchea comportamiento ACTUAL) ───────────────

-- Admin: bypass total via flag _all
INSERT INTO auth.roles (name, description, permissions, is_builtin)
VALUES (
    'admin',
    'Administrador con acceso total al CRM',
    '{"_all": true}'::jsonb,
    TRUE
)
ON CONFLICT (name) DO NOTHING;

-- Supervisor: ve su equipo + módulos mgmt
INSERT INTO auth.roles (name, description, permissions, is_builtin)
VALUES (
    'supervisor',
    'Supervisor de equipo comercial',
    jsonb_build_object(
        'leads.view',         true,
        'leads.edit',         true,
        'leads.create',       true,
        'agenda.view',        true,
        'agenda.edit',        true,
        'chat.view',          true,
        'llamadas.view',      true,
        'carga_masiva.use',   true,
        'asignacion.manage',  true,
        'formularios.manage', true,
        'reportes.view',      true,
        'reportes.export',    true,
        'dashboards.view',    true,
        'metas.view',         true,
        'historicos.view',    true
    ),
    TRUE
)
ON CONFLICT (name) DO NOTHING;

-- Asesor: operación diaria
INSERT INTO auth.roles (name, description, permissions, is_builtin)
VALUES (
    'asesor',
    'Asesor comercial (ve solo sus leads)',
    jsonb_build_object(
        'leads.view',         true,
        'leads.edit',         true,
        'leads.create',       true,
        'agenda.view',        true,
        'agenda.edit',        true,
        'chat.view',          true,
        'llamadas.view',      true,
        'carga_masiva.use',   true,
        'reportes.view',      true
    ),
    TRUE
)
ON CONFLICT (name) DO NOTHING;

-- ── 4. Backfill: vincular usuarios existentes con su rol built-in ───────────

UPDATE auth.users u
   SET role_id = r.id
  FROM auth.roles r
 WHERE u.role_id IS NULL
   AND r.is_builtin = TRUE
   AND r.name = u.role;

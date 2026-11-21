-- ║ V095 — Jerarquía de Supervisores: supervisor_jefe_id                    ║
-- ║ Permite que un supervisor de equipo tenga asignado un supervisor jefe   ║
-- ║ (supervisor_jefe_id UUID REFERENCES auth.users(id)).                    ║

ALTER TABLE auth.users
ADD COLUMN IF NOT EXISTS supervisor_jefe_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_users_supervisor_jefe_id
    ON auth.users (supervisor_jefe_id) WHERE supervisor_jefe_id IS NOT NULL;

COMMENT ON COLUMN auth.users.supervisor_jefe_id IS
    'ID del Supervisor Jefe al que pertenece este supervisor de equipo.';

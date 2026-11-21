-- ============================================================================
-- V083 — Audit log de cambios sobre permisos y roles (ADR-0011 Sprint 4)
--
-- Necesario para cumplimiento Ley 29733 (Protección de Datos Personales PE):
-- registrar quién cambió permisos sobre datos personales y cuándo.
--
-- Acciones capturadas:
--   role.create           — admin creó rol custom
--   role.update_perms     — admin modificó permisos de un rol
--   role.update_meta      — admin renombró/cambió descripción
--   role.delete           — admin eliminó rol custom
--   user.role_change      — admin asignó/cambió el role_id de un usuario
--   user.permissions_set  — (futuro) asignación directa de permisos a usuario
--
-- before_state/after_state son JSONB para flexibilidad. Para role.update_perms
-- guardan el dict de permisos antes/después; para user.role_change guardan
-- {role_id, role_name} antes/después.
--
-- Diseño:
--   - actor_email denormalizado: si borramos al admin que hizo el cambio, el
--     audit log SIGUE legible (clave para forensia).
--   - target_label denormalizado igual.
--   - ip_address + user_agent para forensia regulatoria.
-- ============================================================================

CREATE TABLE IF NOT EXISTS auth.permission_audit_log (
    id              BIGSERIAL PRIMARY KEY,

    -- Quien hizo el cambio (denormalizado para sobrevivir a deletes)
    actor_user_id   UUID,
    actor_email     VARCHAR(120),
    actor_role      VARCHAR(40),

    -- Qué acción
    action          VARCHAR(40) NOT NULL,

    -- Sobre qué objeto (rol o usuario)
    target_kind     VARCHAR(20) NOT NULL,           -- 'role' | 'user'
    target_id       VARCHAR(80) NOT NULL,           -- role_id (int) o user_id (uuid) como text
    target_label    VARCHAR(160),                   -- nombre del rol o email del user

    -- Estado antes/después (diff inspectable)
    before_state    JSONB,
    after_state     JSONB,

    -- Forensia
    ip_address      VARCHAR(45),
    user_agent      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para queries típicas:
--   "todo lo que pasó en la última semana"
CREATE INDEX IF NOT EXISTS ix_perm_audit_created_at
    ON auth.permission_audit_log (created_at DESC);

--   "todo lo que hizo el admin X"
CREATE INDEX IF NOT EXISTS ix_perm_audit_actor
    ON auth.permission_audit_log (actor_user_id, created_at DESC);

--   "todos los cambios sobre este rol/usuario"
CREATE INDEX IF NOT EXISTS ix_perm_audit_target
    ON auth.permission_audit_log (target_kind, target_id, created_at DESC);

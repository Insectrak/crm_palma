-- =====================================================================
-- V094 — Bloqueo de login independiente del soft-disable
-- =====================================================================
--
-- Problema: hasta V088, la unica forma de impedir que un usuario
-- iniciara sesion era marcarlo `is_active = FALSE`. Pero `is_active`
-- es la misma columna que filtra TODAS las listas operacionales
-- (rotacion, asignacion, dropdowns, dashboards, equipos). Resultado:
-- bloquear acceso lo sacaba tambien de las listas, lo cual no siempre
-- es lo que el admin quiere (ej: supervisor de vacaciones que sigue
-- visible para sus asesores, pero no debe entrar al CRM).
--
-- Solucion: columna nueva `login_blocked BOOLEAN` independiente. El
-- login chequea AMBAS (`is_active=TRUE AND login_blocked=FALSE`), pero
-- las queries operacionales siguen filtrando solo por `is_active`. Asi:
--
--   is_active=TRUE  + login_blocked=FALSE → usuario normal
--   is_active=TRUE  + login_blocked=TRUE  → visible en listas, sin login
--   is_active=FALSE + login_blocked=*     → deshabilitado total
--
-- Idempotente: ADD COLUMN IF NOT EXISTS + index parcial.
-- =====================================================================

BEGIN;

ALTER TABLE auth.users
    ADD COLUMN IF NOT EXISTS login_blocked BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN auth.users.login_blocked IS
    'Si TRUE, el usuario no puede iniciar sesion pero SIGUE visible en '
    'todas las listas operacionales (rotacion, asignacion, equipos, '
    'dashboards). Independiente de is_active. Usar para freeze rapido '
    'sin sacar al usuario del workflow del equipo.';

-- Index parcial: solo nos interesa enumerar los bloqueados (cardinalidad
-- baja). El login no usa este index — busca por email/id.
CREATE INDEX IF NOT EXISTS idx_users_login_blocked
    ON auth.users (login_blocked)
    WHERE login_blocked = TRUE;

COMMIT;

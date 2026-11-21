-- =============================================================================
-- Migración V002: Actualización de roles en auth.users
-- Fecha:       2026-04-03
-- Autor:       Brighton
-- Descripción: Extiende el sistema de roles para el CRM.
--              - Nuevos roles: 'admin', 'supervisor', 'asesor'
--              - Elimina el CHECK constraint anterior de role
--              - Agrega campo 'telefono' para contacto directo de usuarios.
--              - Depreca advisor_schema (renombra con prefijo _deprecated_)
--
-- PRECONDICIONES:
--   - Debe haberse ejecutado V001 (schema crm).
--   - La extensión pgcrypto debe estar disponible (para crypt/gen_salt en V005).
--   - Revisar sección "Plan de Migración" en ARQUITECTURA_CRM.md antes de ejecutar
--     en producción, especialmente el mapeo de roles existentes.
--
-- TABLA TARGET: auth.users (UUID PK — sistema de usuarios activo)
--
-- ROLES ANTERIORES → NUEVOS ROLES:
--   'user'      → 'asesor'
--   'moderator' → 'supervisor'
--   'admin'     → sin cambio
-- =============================================================================

BEGIN;

-- Asegurar que pgcrypto esté disponible (necesario para crypt/gen_salt en V005)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- Paso 1: Agregar columna telefono si no existe
-- Permite contactar directamente al supervisor o asesor para notificaciones.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'auth'
          AND table_name   = 'users'
          AND column_name  = 'telefono'
    ) THEN
        ALTER TABLE auth.users
            ADD COLUMN telefono VARCHAR(20);

        COMMENT ON COLUMN auth.users.telefono IS
            'Número de celular del usuario para notificaciones WhatsApp/SMS.';

        RAISE NOTICE '[Paso 1] Columna telefono agregada a auth.users.';
    ELSE
        RAISE NOTICE '[Paso 1] Columna telefono ya existe en auth.users — omitido.';
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Paso 2: Deprecar advisor_schema (ya no se necesitan schemas por asesor)
-- NO se elimina la columna — se renombra con prefijo _deprecated_ para
-- preservar los datos de referencia durante el período de transición.
-- Eliminar físicamente después de 90 días sin incidentes (2026-07-03).
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'auth'
          AND table_name   = 'users'
          AND column_name  = 'advisor_schema'
    ) THEN
        ALTER TABLE auth.users
            RENAME COLUMN advisor_schema TO _deprecated_advisor_schema;

        COMMENT ON COLUMN auth.users._deprecated_advisor_schema IS
            'DEPRECADO 2026-04-03: Schema por asesor eliminado en favor del schema crm centralizado. '
            'Eliminar esta columna después del 2026-07-03 si no hay incidentes.';

        RAISE NOTICE '[Paso 2] advisor_schema renombrado a _deprecated_advisor_schema en auth.users.';
    ELSE
        RAISE NOTICE '[Paso 2] advisor_schema no existe (ya fue renombrado o nunca existió) — omitido.';
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Paso 3: Eliminar el CHECK constraint de roles antiguo
-- Busca dinámicamente cualquier constraint CHECK sobre la columna role
-- y lo elimina. Idempotente: si no encuentra nada, solo emite NOTICE.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_constraint_name TEXT;
BEGIN
    -- Buscar el nombre del constraint de role en auth.users
    SELECT tc.constraint_name
    INTO   v_constraint_name
    FROM   information_schema.table_constraints tc
    JOIN   information_schema.constraint_column_usage ccu
           ON ccu.constraint_name = tc.constraint_name
          AND ccu.table_schema    = tc.table_schema
    WHERE  tc.table_schema    = 'auth'
      AND  tc.table_name      = 'users'
      AND  tc.constraint_type = 'CHECK'
      AND  ccu.column_name    = 'role'
    LIMIT 1;

    IF v_constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE auth.users DROP CONSTRAINT %I',
            v_constraint_name
        );
        RAISE NOTICE '[Paso 3] Constraint % eliminado de auth.users', v_constraint_name;
    ELSE
        RAISE NOTICE '[Paso 3] No se encontró constraint CHECK de role en auth.users — omitido.';
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Paso 4: Mapeo de roles existentes (REVISAR CON CLIENTE ANTES DE EJECUTAR)
-- Los roles actuales en auth.users son: 'admin', 'user', 'moderator'
-- El mapeo al nuevo sistema CRM es:
--   'user'      → 'asesor'
--   'moderator' → 'supervisor'
--   'admin'     → sin cambio
-- IMPORTANTE: Este bloque emite RAISE WARNING si hay roles desconocidos.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_count_user       INTEGER;
    v_count_moderator  INTEGER;
    v_count_invalido   INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count_user
    FROM auth.users
    WHERE role = 'user';

    SELECT COUNT(*) INTO v_count_moderator
    FROM auth.users
    WHERE role = 'moderator';

    -- Roles que no son ninguno de los conocidos (ni los que vamos a migrar)
    SELECT COUNT(*) INTO v_count_invalido
    FROM auth.users
    WHERE role NOT IN ('admin', 'supervisor', 'asesor', 'user', 'moderator');

    IF v_count_invalido > 0 THEN
        RAISE WARNING
            '[Paso 4] Se encontraron % usuarios con roles no reconocidos. '
            'Revisar antes de aplicar el nuevo constraint.',
            v_count_invalido;
    END IF;

    IF v_count_user > 0 THEN
        UPDATE auth.users
        SET role = 'asesor'
        WHERE role = 'user';
        RAISE NOTICE '[Paso 4] % usuarios migrados de "user" a "asesor"', v_count_user;
    END IF;

    IF v_count_moderator > 0 THEN
        UPDATE auth.users
        SET role = 'supervisor'
        WHERE role = 'moderator';
        RAISE NOTICE '[Paso 4] % usuarios migrados de "moderator" a "supervisor"', v_count_moderator;
    END IF;

    IF v_count_user = 0 AND v_count_moderator = 0 THEN
        RAISE NOTICE '[Paso 4] No hay roles que migrar. Todos los usuarios ya tienen roles válidos.';
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Paso 5: Agregar el nuevo CHECK constraint de roles CRM
-- Roles válidos: 'admin' | 'supervisor' | 'asesor'
-- Se usa DO $$ para verificar que no exista antes de agregarlo (idempotente).
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema    = 'auth'
          AND table_name      = 'users'
          AND constraint_name = 'users_role_crm_check'
    ) THEN
        ALTER TABLE auth.users
            ADD CONSTRAINT users_role_crm_check
            CHECK (role IN ('admin', 'supervisor', 'asesor'));

        RAISE NOTICE '[Paso 5] Constraint users_role_crm_check agregado a auth.users.';
    ELSE
        RAISE NOTICE '[Paso 5] Constraint users_role_crm_check ya existe — omitido.';
    END IF;
END;
$$;

COMMENT ON COLUMN auth.users.role IS
    'Rol del usuario en el CRM. '
    'admin: acceso total. supervisor: ve sus asesores y sus leads. asesor: solo sus propios leads.';

-- -----------------------------------------------------------------------------
-- Paso 6: Actualizar el DEFAULT del campo role al nuevo sistema
-- Se usa DO $$ para ser idempotente aunque el DEFAULT ya esté seteado.
-- -----------------------------------------------------------------------------
ALTER TABLE auth.users
    ALTER COLUMN role SET DEFAULT 'asesor';

DO $$ BEGIN RAISE NOTICE '[Paso 6] DEFAULT de role en auth.users seteado a "asesor".'; END; $$;

COMMIT;

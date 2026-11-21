-- ============================================================================
-- V089 — Permiso `notificaciones.manage_own` en built-in supervisor + asesor.
--
-- Contexto: el admin de Palma pidió poder revocar el acceso de los asesores a
-- "Mi cuenta → Mis notificaciones" para garantizar que SIEMPRE reciban push
-- (que no puedan apagar el kill switch personal).
--
-- Diseño: agregamos el permiso `notificaciones.manage_own` con default TRUE
-- en los roles built-in supervisor y asesor → backward compat total. Para
-- aplicar el bloqueo, el admin desmarca el checkbox en
-- /configuracion?tab=roles → asesor.
--
-- Admin: no necesita el flag — su rol legacy 'admin' bypasea TODOS los
-- chequeos via Role.ADMIN en backend (ver auth/permissions.py).
--
-- Multi-tenant safe: idempotente. Si el permiso ya existe en el JSONB,
-- el `||` no lo sobreescribe (en PostgreSQL `a || b` con keys en común,
-- gana el lado derecho — usamos COALESCE para preservar la decisión
-- previa del admin si ya jugó con el flag).
-- ============================================================================

DO $$
BEGIN
    -- supervisor
    UPDATE auth.roles
       SET permissions = permissions || jsonb_build_object(
               'notificaciones.manage_own', TRUE
           )
     WHERE name = 'supervisor'
       AND is_builtin = TRUE
       AND NOT (permissions ? 'notificaciones.manage_own');

    -- asesor
    UPDATE auth.roles
       SET permissions = permissions || jsonb_build_object(
               'notificaciones.manage_own', TRUE
           )
     WHERE name = 'asesor'
       AND is_builtin = TRUE
       AND NOT (permissions ? 'notificaciones.manage_own');

    RAISE NOTICE '[V089] notificaciones.manage_own agregado a built-in supervisor + asesor (skip si ya estaba).';
END $$;

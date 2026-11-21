-- ============================================================================
-- V081 — Remove `proveedor_externo` rol seed (ADR-0011 Amendment 2026-06-15)
--
-- El "Caso 1 — Proveedor externo de leads" del ADR-0011 quedó descartado:
-- los proveedores ya tienen feedback vía la respuesta del endpoint de ingest +
-- sus propios dashboards externos. Un portal dedicado en el CRM agregaba
-- superficie de seguridad (filtrado por api_client_id en todos los queries,
-- auth externa, vector de fuga de datos del cliente final) sin demanda real
-- validada.
--
-- Esta migración:
--   1. Borra el rol seed `proveedor_externo` (creado por V079).
--   2. NO se elimina el flag `auth.roles.is_external` del schema — se conserva
--      por si vuelve la necesidad en el futuro. Pero queda sin uso activo.
--   3. Solo borra si nadie tiene `role_id` apuntando a `proveedor_externo`
--      (defensa contra borrar accidental si en lab/prod alguien ya lo asignó).
-- ============================================================================

DO $$
DECLARE
    pe_id INTEGER;
    pe_users INTEGER;
BEGIN
    SELECT id INTO pe_id FROM auth.roles WHERE name = 'proveedor_externo';
    IF pe_id IS NULL THEN
        -- Ya no existe (deploy nuevo donde V079 fue parchada antes de aplicarse).
        RETURN;
    END IF;

    SELECT COUNT(*) INTO pe_users FROM auth.users WHERE role_id = pe_id;
    IF pe_users > 0 THEN
        RAISE NOTICE 'Rol proveedor_externo tiene % usuarios asignados — NO se borra. Reasigna antes.', pe_users;
        RETURN;
    END IF;

    DELETE FROM auth.roles WHERE id = pe_id;
    RAISE NOTICE 'Rol proveedor_externo eliminado (V081).';
END $$;

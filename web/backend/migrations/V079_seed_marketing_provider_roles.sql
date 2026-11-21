-- ============================================================================
-- V079 — Seed de roles de casos de uso típicos (ADR-0011, Sprint 3)
--
-- Crea dos roles custom pre-configurados con sus permisos típicos:
--
--   1. `marketing` — Solo Reportes / Dashboards / Históricos. NO ve leads
--      ni edita nada. Caso de uso real del cliente Palma del Río: el
--      equipo de marketing necesita ver métricas de campañas sin tocar
--      operación comercial.
--
--   2. `proveedor_externo` — Solo ve el portal donde se listan los leads
--      que ese proveedor entregó vía /api/ingest/leads. Marcado como
--      `is_external = TRUE` para activar el filtrado por api_client_id
--      del usuario. Los usuarios con este rol DEBEN tener
--      auth.users.api_client_id seteado o se les bloquea el login.
--
-- Estos roles son `is_builtin = FALSE` — el admin puede editarles los
-- permisos o eliminarlos desde la UI /configuracion/roles.
-- ============================================================================

INSERT INTO auth.roles (name, description, permissions, is_external, is_builtin)
VALUES (
    'marketing',
    'Equipo de marketing — solo lectura de reportes y métricas. No accede a leads ni operación comercial.',
    jsonb_build_object(
        'reportes.view',    true,
        'reportes.export',  true,
        'dashboards.view',  true,
        'historicos.view',  true,
        'metas.view',       true
    ),
    FALSE,  -- no es externo (es equipo interno)
    FALSE   -- no es built-in (admin puede borrarlo)
)
ON CONFLICT (name) DO NOTHING;

INSERT INTO auth.roles (name, description, permissions, is_external, is_builtin)
VALUES (
    'proveedor_externo',
    'Proveedor externo de leads — solo ve los leads que entregó vía API.',
    jsonb_build_object(
        'portal_proveedor.view', true
    ),
    TRUE,   -- externo: requiere api_client_id en el usuario
    FALSE   -- no es built-in (admin puede borrarlo)
)
ON CONFLICT (name) DO NOTHING;

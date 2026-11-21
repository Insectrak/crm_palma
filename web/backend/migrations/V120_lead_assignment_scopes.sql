-- ============================================================================
-- V120 — Modalidades de alcance para asignación de leads (ADR-0011)
--
-- Documenta y respalda los 3 modos de asignación granular en auth.roles:
--   1. Global: 'asignacion.scope': 'global' (asigna a cualquier asesor o supervisor como admin)
--   2. Equipo: 'asignacion.scope': 'equipo' (encapsulado a miembros de su equipo actual: supervisor y asesores)
--   3. Personalizado: 'asignacion.scope': 'personalizado' con 'asignacion.allowed_users': ['uuid', ...]
-- ============================================================================

-- Backfill: asegurar que el rol built-in supervisor tenga scope explícito 'equipo' si no lo tiene
UPDATE auth.roles
   SET permissions = jsonb_set(
       permissions,
       '{asignacion.scope}',
       '"equipo"'::jsonb,
       true
   )
 WHERE name = 'supervisor'
   AND (permissions->>'asignacion.scope') IS NULL
   AND (permissions->>'asignacion.manage')::boolean IS TRUE;

COMMENT ON COLUMN auth.roles.permissions IS
'Permisos granulares del rol en formato JSONB. Soporta:
- leads.view, leads.edit, etc.
- asignacion.manage (boolean)
- asignacion.scope ("global" | "equipo" | "personalizado")
- asignacion.allowed_users (array de UUIDs para modo personalizado)';

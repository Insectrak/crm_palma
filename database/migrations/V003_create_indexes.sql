-- =============================================================================
-- Migración V003: Índices adicionales y compuestos para el schema CRM
-- Fecha:       2026-04-03
-- Autor:       Brighton
-- Descripción: Índices adicionales orientados a los patrones de query del
--              dashboard, la API de leads y los reportes de supervisores.
--              Los índices básicos ya se crearon en V001. Esta migración agrega
--              los compuestos y de cobertura que sirven a las vistas y endpoints
--              más críticos.
--
-- ESTRATEGIA DE ÍNDICES:
--   - B-tree: igualdad, rangos, ORDER BY en columnas escalares
--   - GIN:    JSONB (datos_extra, errores_detalle), búsqueda de texto en arrays
--   - Partial: índices con WHERE para filtrar filas inactivas/ya procesadas
--              → reducen tamaño del índice y mejoran el cache hit rate
--
-- PRECONDICIONES:
--   - Debe haberse ejecutado V001 y V002.
-- =============================================================================

BEGIN;

-- =============================================================================
-- ÍNDICES SOBRE crm.leads
-- =============================================================================

-- Búsqueda de leads sin asignar (cola de asignación round-robin)
CREATE INDEX IF NOT EXISTS idx_leads_sin_asignar
    ON crm.leads (created_at DESC)
    WHERE asesor_id IS NULL AND activo = TRUE;

COMMENT ON INDEX crm.idx_leads_sin_asignar IS
    'Leads activos sin asesor asignado, ordenados por fecha de ingreso. '
    'Usado por el servicio de asignación round-robin.';

-- Búsqueda de leads por fuente + estado (filtro más común en el dashboard)
CREATE INDEX IF NOT EXISTS idx_leads_fuente_estado
    ON crm.leads (fuente_id, estado_id)
    WHERE activo = TRUE;

COMMENT ON INDEX crm.idx_leads_fuente_estado IS
    'Filtro combinado por fuente y estado. Soporta el widget "leads por fuente/estado" del dashboard.';

-- Soporte para el endpoint de búsqueda GET /api/leads?q=...
-- Búsqueda parcial por nombre: usar pg_trgm para ILIKE eficiente
-- Nota: requiere la extensión pg_trgm (CREATE EXTENSION IF NOT EXISTS pg_trgm)
DO $$
BEGIN
    -- Crear extensión si no existe (requiere superuser en la primera vez)
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE WARNING
            'No se pudo crear pg_trgm: permisos insuficientes. '
            'Ejecutar como superuser: CREATE EXTENSION pg_trgm;';
END;
$$;

CREATE INDEX IF NOT EXISTS idx_leads_nombres_trgm
    ON crm.leads USING GIN (nombres gin_trgm_ops)
    WHERE nombres IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_telefono_trgm
    ON crm.leads USING GIN (telefono gin_trgm_ops)
    WHERE telefono IS NOT NULL;

COMMENT ON INDEX crm.idx_leads_nombres_trgm IS
    'Índice trigram para búsqueda ILIKE en el campo nombres. Requiere pg_trgm.';

COMMENT ON INDEX crm.idx_leads_telefono_trgm IS
    'Índice trigram para búsqueda ILIKE en el campo telefono. Requiere pg_trgm.';

-- Índice para el endpoint GET /api/leads filtrado por fecha_desde/fecha_hasta
CREATE INDEX IF NOT EXISTS idx_leads_created_at_asesor
    ON crm.leads (created_at DESC, asesor_id)
    WHERE activo = TRUE;

COMMENT ON INDEX crm.idx_leads_created_at_asesor IS
    'Soporta listado paginado de leads por asesor ordenado por fecha. '
    'Cubre el caso más común: asesor ve sus propios leads recientes.';

-- Índice para el cálculo de KPIs: cuántos leads en cada estado por asesor
-- (soporta la vista vw_kpis_por_asesor)
CREATE INDEX IF NOT EXISTS idx_leads_asesor_estado_activo
    ON crm.leads (asesor_id, estado_id)
    INCLUDE (id, created_at)
    WHERE activo = TRUE;

COMMENT ON INDEX crm.idx_leads_asesor_estado_activo IS
    'Covering index para KPIs por asesor. INCLUDE evita heap fetch al calcular conteos.';

-- Índice para el cálculo de KPIs de supervisores
-- (soporta la vista vw_kpis_por_supervisor)
-- El supervisor necesita ver todos los leads de sus asesores → join con crm.equipos
-- Este índice acelera el JOIN equipos → leads
CREATE INDEX IF NOT EXISTS idx_leads_asesor_id_created
    ON crm.leads (asesor_id, created_at DESC)
    WHERE activo = TRUE;

COMMENT ON INDEX crm.idx_leads_asesor_id_created IS
    'Acelera el join crm.equipos → crm.leads para reportes de supervisores.';

-- =============================================================================
-- ÍNDICES SOBRE crm.contactos
-- =============================================================================

-- Índice para "próximas acciones de hoy" (dashboard del asesor)
-- Partial index: solo filas con fecha_proxima_accion en el futuro reciente
CREATE INDEX IF NOT EXISTS idx_contactos_proximas_hoy
    ON crm.contactos (asesor_id, fecha_proxima_accion)
    WHERE fecha_proxima_accion IS NOT NULL;

COMMENT ON INDEX crm.idx_contactos_proximas_hoy IS
    'Soporta el widget "Próximas acciones" del dashboard. '
    'Usado en: GET /api/dashboard/proximas-acciones';

-- Índice para obtener el último contacto de cada lead (usado en vw_leads_dashboard)
-- El ORDER BY lead_id, created_at DESC + DISTINCT ON(lead_id) se beneficia de esto
CREATE INDEX IF NOT EXISTS idx_contactos_lead_created_desc
    ON crm.contactos (lead_id, created_at DESC);

COMMENT ON INDEX crm.idx_contactos_lead_created_desc IS
    'Soporta el DISTINCT ON(lead_id) ORDER BY created_at DESC de la vista vw_leads_dashboard.';

-- Índice para buscar citas agendadas en un rango de fechas
CREATE INDEX IF NOT EXISTS idx_contactos_fecha_cita_rango
    ON crm.contactos (fecha_cita DESC)
    WHERE fecha_cita IS NOT NULL;

COMMENT ON INDEX crm.idx_contactos_fecha_cita_rango IS
    'Consultas de citas agendadas en un período. Partial index: excluye filas sin cita.';

-- =============================================================================
-- ÍNDICES SOBRE crm.equipos
-- =============================================================================

-- Índice para obtener los asesores de un supervisor (query en build_lead_filter)
-- Ya existe idx_equipos_supervisor_id, pero agregamos partial para solo activos
CREATE INDEX IF NOT EXISTS idx_equipos_supervisor_activo
    ON crm.equipos (supervisor_id)
    WHERE activo = TRUE;

COMMENT ON INDEX crm.idx_equipos_supervisor_activo IS
    'Usado en build_lead_filter(role=supervisor): obtiene asesores activos del supervisor.';

-- =============================================================================
-- ÍNDICES SOBRE crm.leads_raw_facebook y crm.leads_raw_tiktok
-- =============================================================================

-- Deduplicación por teléfono en raw (antes de migrar a crm.leads)
CREATE INDEX IF NOT EXISTS idx_leads_raw_fb_phone
    ON crm.leads_raw_facebook (phone)
    WHERE phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_raw_tt_phone
    ON crm.leads_raw_tiktok (phone)
    WHERE phone IS NOT NULL;

-- Índice por campaign para análisis de rendimiento de campañas
CREATE INDEX IF NOT EXISTS idx_leads_raw_fb_campaign
    ON crm.leads_raw_facebook (campaign_name)
    WHERE campaign_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_raw_tt_campaign
    ON crm.leads_raw_tiktok (campaign_name)
    WHERE campaign_name IS NOT NULL;

-- =============================================================================
-- ÍNDICES SOBRE crm.asignaciones_log
-- =============================================================================

-- Historial de asignaciones de un asesor (para calcular carga histórica)
CREATE INDEX IF NOT EXISTS idx_asig_log_asesor_nuevo_fecha
    ON crm.asignaciones_log (asesor_nuevo, created_at DESC)
    WHERE asesor_nuevo IS NOT NULL;

COMMENT ON INDEX crm.idx_asig_log_asesor_nuevo_fecha IS
    'Calcula la carga histórica de asignaciones por asesor en un período.';

-- =============================================================================
-- ÍNDICES SOBRE crm.auditoria
-- =============================================================================

-- Consulta de auditoría: todos los cambios de un registro específico
-- (ya cubierto por idx_auditoria_tabla_registro en V001, este agrega fecha)
CREATE INDEX IF NOT EXISTS idx_auditoria_tabla_registro_fecha
    ON crm.auditoria (tabla, registro_id, created_at DESC);

COMMENT ON INDEX crm.idx_auditoria_tabla_registro_fecha IS
    'Historial de cambios de un registro ordenado por fecha descendente.';

COMMIT;

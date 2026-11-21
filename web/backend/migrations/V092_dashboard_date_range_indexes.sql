-- =====================================================================
-- V092 — Indexes para dashboard con filtro temporal (V096 feature flag)
-- =====================================================================
-- El dashboard.py V096 agrega filtros por rango de fechas en /resumen,
-- /actividad-equipo, /referidos, /leads-por-fuente, /funnel-conversion
-- y /sparklines. Todas las queries hacen:
--     WHERE l.created_at >= %s AND l.created_at <= %s
--     WHERE c.created_at >= %s AND c.created_at <= %s
-- Sin indices, full table scan en cada request. Con 5k leads de Palma hoy
-- el impacto es chico, pero a escala (50k+ leads) se vuelve O(N) costoso.
--
-- Idempotente — CREATE INDEX IF NOT EXISTS no rompe si ya existe.
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_leads_created_at
    ON crm.leads (created_at);

CREATE INDEX IF NOT EXISTS idx_contactos_created_at
    ON crm.contactos (created_at);

-- Index parcial para queries de leads activos por fecha (caso comun)
-- WHERE l.activo = TRUE AND l.created_at >= ... — el indice parcial
-- evita indexar leads inactivos que nunca aparecen en el dashboard.
CREATE INDEX IF NOT EXISTS idx_leads_activos_created_at
    ON crm.leads (created_at)
    WHERE activo = TRUE;

-- V074 — Indice para acelerar heatmaps dia x hora sobre crm.contactos.
--
-- Reportes V070.103 necesitan agregar contactos por dia de semana y hora
-- del dia (heatmap de actividad). Sin este indice, la query escanea toda
-- la tabla cuando el periodo es largo (>90 dias).
--
-- Idempotente. Zero downtime: CONCURRENTLY no es necesario en 5K filas.

CREATE INDEX IF NOT EXISTS idx_contactos_created_at
    ON crm.contactos (created_at DESC);

COMMENT ON INDEX crm.idx_contactos_created_at IS
    'V074 (2026-05-18) — soporte queries de reportes con agregacion temporal';

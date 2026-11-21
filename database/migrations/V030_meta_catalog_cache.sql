-- V030 — Cache de nombres del catálogo Meta (campañas, formularios, ads).
--
-- Contexto:
--   Cuando Meta envía un webhook leadgen, trae `campaign_id`, `form_id`,
--   `ad_id` pero nunca los nombres. Hoy la UI muestra el ID crudo
--   (ej. "741668672274795") en la columna Campaña de Leads — es ilegible
--   para los asesores aunque sirva para reportes de marketing.
--
-- Solución:
--   Tabla de cache append-update con (entity_type, entity_id) como UNIQUE.
--   Cuando llega un webhook con un ID que no conocemos (o lleva >7 días
--   sin refrescar), el backend hace GET /{id}?fields=name contra Graph API
--   y guarda el nombre. La UI y los reportes hacen LEFT JOIN para obtener
--   `campana_nombre` / `form_nombre` sin mutar `crm.leads`.
--
-- Se aplica también via bootstrap.ensure_meta_catalog_cache_schema().

CREATE TABLE IF NOT EXISTS crm.meta_catalog_cache (
    id            BIGSERIAL PRIMARY KEY,
    entity_type   TEXT NOT NULL CHECK (entity_type IN ('campaign', 'form', 'ad', 'adset')),
    entity_id     TEXT NOT NULL,
    name          TEXT,
    page_id       TEXT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetch_status  TEXT NOT NULL DEFAULT 'ok'
                  CHECK (fetch_status IN ('ok', 'error', 'not_found')),
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_meta_catalog_entity UNIQUE (entity_type, entity_id)
);

-- Lookup principal: resolver nombre por (tipo, id). El UNIQUE ya cubre el índice.

-- Barrido de registros "viejos" para re-fetch en background.
CREATE INDEX IF NOT EXISTS idx_meta_catalog_cache_fetched
    ON crm.meta_catalog_cache (fetched_at);

COMMENT ON TABLE  crm.meta_catalog_cache IS
    'Cache de nombres del Graph API de Meta (campañas, formularios, ads). Se refresca perezosamente al recibir webhooks.';
COMMENT ON COLUMN crm.meta_catalog_cache.fetch_status IS
    'ok = nombre resuelto. error = Graph API falló (reintentar). not_found = Meta devolvió 404/permiso (no reintentar).';

-- V037 — Creative media (imagen/video/thumbnail) del ad para mostrar preview en el chat.
--
-- Contexto:
--   El webhook de CTWA nos da el `ad_id`. En V032/V034 ya resolviamos el
--   ad/adset/campaign/copy. Faltaba lo mas visual: la imagen o thumbnail
--   del creative que el cliente vio antes de iniciar el chat.
--
--   Meta Graph devuelve en creative:
--     - thumbnail_url        (preview pequeño, ~200px — universal, casi siempre presente)
--     - image_url            (imagen full res para ads estaticos)
--     - video_id             (id del video para ads de video — el thumbnail sirve como poster)
--     - object_type          (IMAGE | VIDEO | CAROUSEL | SHARE | etc.)
--     - effective_object_story_id  (para boosted posts: el post original de la fan page)
--
--   Esas URLs de CDN de Meta (*.fbcdn.net) expiran / requieren firma. En vez
--   de depender de ellas en cada render, descargamos una sola vez y cacheamos
--   el binario en crm.meta_creative_cache (mismo patron que wa_media_cache).
--
-- Campos nuevos en wa_campaigns:
--   creative_media_type       — 'image' | 'video' | 'carousel' | 'post' | NULL
--   creative_thumbnail_url    — URL original de Graph al momento del fetch (informativa)
--   creative_image_url        — URL full-res (solo image ads)
--   creative_video_id         — video_id (solo video ads)
--   creative_object_story_id  — para boosted posts, el id del post de la fan page
--   creative_media_cached_at  — timestamp de la ultima descarga exitosa (NULL = no cacheado)
--   creative_media_error      — ultimo error al intentar resolver/descargar (null si ok)

ALTER TABLE crm.wa_campaigns
    ADD COLUMN IF NOT EXISTS creative_media_type       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS creative_thumbnail_url    TEXT,
    ADD COLUMN IF NOT EXISTS creative_image_url        TEXT,
    ADD COLUMN IF NOT EXISTS creative_video_id         VARCHAR(80),
    ADD COLUMN IF NOT EXISTS creative_object_story_id  VARCHAR(120),
    ADD COLUMN IF NOT EXISTS creative_media_cached_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS creative_media_error      TEXT;

COMMENT ON COLUMN crm.wa_campaigns.creative_media_type IS
    'Tipo de creative derivado de Graph: image | video | carousel | post (boosted) | NULL.';
COMMENT ON COLUMN crm.wa_campaigns.creative_thumbnail_url IS
    'URL del thumbnail segun Graph al momento del ultimo fetch. Informativa — servir desde el cache binario.';
COMMENT ON COLUMN crm.wa_campaigns.creative_media_cached_at IS
    'Timestamp de la ultima descarga exitosa del thumbnail al cache local. NULL = nunca cacheado.';
COMMENT ON COLUMN crm.wa_campaigns.creative_media_error IS
    'Ultimo error al intentar resolver/descargar la media (graph_empty | http_* | mime_invalid | too_large). NULL cuando cacheado ok.';

-- Tabla de cache del binario del thumbnail del creative.
--
-- Keyed por wa_campaign_id (1:1 con wa_campaigns, una fila por ad enriquecido).
-- Similar a crm.wa_media_cache pero separada porque:
--   a) identificador distinto (wa_campaign_id, no media_id de WA);
--   b) source distinto (ads CDN vs WhatsApp Media API);
--   c) politicas de invalidacion potencialmente diferentes (ad editado = refresh).
CREATE TABLE IF NOT EXISTS crm.meta_creative_cache (
    wa_campaign_id  BIGINT PRIMARY KEY
        REFERENCES crm.wa_campaigns(id) ON DELETE CASCADE,
    media_kind      VARCHAR(20) NOT NULL,    -- 'thumbnail' (V037); reservado para 'image'/'video' full
    mime_type       TEXT        NOT NULL,
    size_bytes      BIGINT,
    data            BYTEA       NOT NULL,
    source_url      TEXT,                    -- URL original al momento de descarga
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meta_creative_cache_cached_at
    ON crm.meta_creative_cache (cached_at DESC);

COMMENT ON TABLE  crm.meta_creative_cache IS
    'Cache binaria de los thumbnails/medios de ads Meta. 1:1 con wa_campaigns.';
COMMENT ON COLUMN crm.meta_creative_cache.media_kind IS
    'Tipo del binario almacenado: thumbnail (default V037). Permite extender a image_full/video en el futuro.';

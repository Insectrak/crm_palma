-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V026 — Lead Tags (etiquetas para gestion operativa de leads)          ║
-- ║                                                                        ║
-- ║ Catalogo de etiquetas editables + tabla N:M lead_tags. Pensadas como  ║
-- ║ marcadores de workflow que complementan el estado del pipeline:        ║
-- ║   estado     = donde esta el lead en el embudo (Nuevo, En contacto…)  ║
-- ║   etiqueta   = que necesita o como lo agrupo (Lote 8, Requiere visita, ║
-- ║                Caliente, Pendiente info…)                              ║
-- ║                                                                        ║
-- ║ Multi-etiqueta: un lead puede tener varias. Soft-delete en el catalogo.║
-- ║ Si se borra una etiqueta (tags.activo=FALSE), las asociaciones quedan ║
-- ║ — el UI las filtra. Hard-delete CASCADE para mantener integridad.      ║
-- ║                                                                        ║
-- ║ Idempotente — seguro de re-ejecutar.                                   ║
-- ╚════════════════════════════════════════════════════════════════════════╝

CREATE TABLE IF NOT EXISTS crm.tags (
    id          SERIAL       PRIMARY KEY,
    nombre      VARCHAR(64)  NOT NULL,
    color_hex   VARCHAR(9)   NOT NULL DEFAULT '#6366f1',
    descripcion TEXT,
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    orden       INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT tags_nombre_unique UNIQUE (nombre)
);

CREATE INDEX IF NOT EXISTS idx_tags_activo_orden
    ON crm.tags (activo, orden, nombre);

-- Relacion N:M lead <-> tag
CREATE TABLE IF NOT EXISTS crm.lead_tags (
    lead_id         INTEGER      NOT NULL
                    REFERENCES crm.leads(id) ON DELETE CASCADE,
    tag_id          INTEGER      NOT NULL
                    REFERENCES crm.tags(id)  ON DELETE CASCADE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by_user UUID         REFERENCES auth.users(id) ON DELETE SET NULL,
    PRIMARY KEY (lead_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_lead_tags_tag
    ON crm.lead_tags (tag_id);

CREATE INDEX IF NOT EXISTS idx_lead_tags_lead
    ON crm.lead_tags (lead_id);

-- Seed minimo — etiquetas utiles para arrancar. Re-ejecutar no duplica.
INSERT INTO crm.tags (nombre, color_hex, descripcion, orden) VALUES
    ('Caliente',         '#ef4444', 'Alta probabilidad de cierre',            10),
    ('Tibio',            '#f59e0b', 'Interes moderado, seguir trabajando',    20),
    ('Frio',             '#3b82f6', 'Bajo engagement, cadencia espaciada',    30),
    ('Requiere visita',  '#8b5cf6', 'Pidio ver lote en persona',              40),
    ('Pendiente info',   '#14b8a6', 'Esperando que enviemos precio/plano',    50),
    ('Agendado',         '#22c55e', 'Cita confirmada',                        60)
ON CONFLICT (nombre) DO NOTHING;

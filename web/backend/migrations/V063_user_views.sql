-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V063 — Vistas guardadas por usuario (saved views)                      ║
-- ║                                                                        ║
-- ║ Cada usuario puede guardar combinaciones de:                          ║
-- ║   - Filtros activos                                                    ║
-- ║   - Sort                                                               ║
-- ║   - Columnas visibles                                                  ║
-- ║   - Orden de columnas                                                  ║
-- ║                                                                        ║
-- ║ y darles un nombre, icono y color. En vez de re-aplicar 5 filtros     ║
-- ║ cada vez (proveedor + estado + calidad + fecha + supervisor), un      ║
-- ║ clic restaura todo.                                                    ║
-- ║                                                                        ║
-- ║ Tres niveles de visibilidad:                                          ║
-- ║   - 'personal':  solo el owner ve la vista                            ║
-- ║   - 'team':      el supervisor que la creo + sus asesores (via        ║
-- ║                  team_supervisor_id). Util para "Cola del equipo".    ║
-- ║   - 'public':    todos los usuarios autenticados ven la vista. Solo   ║
-- ║                  admin puede crear/promover a publica.                ║
-- ║                                                                        ║
-- ║ Patron Airtable / Notion / NocoDB.                                    ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

CREATE TABLE IF NOT EXISTS crm.user_views (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    scope               VARCHAR(20)  NOT NULL,
    name                VARCHAR(120) NOT NULL,
    icon                VARCHAR(40),
    color               VARCHAR(20),
    share_level         VARCHAR(20)  NOT NULL DEFAULT 'personal',
    team_supervisor_id  UUID         REFERENCES auth.users(id) ON DELETE SET NULL,
    is_default          BOOLEAN      NOT NULL DEFAULT FALSE,
    filters             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    sort                JSONB        NOT NULL DEFAULT '[]'::jsonb,
    columns_order       JSONB        NOT NULL DEFAULT '[]'::jsonb,
    visible_columns     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT user_views_scope_chk
        CHECK (scope IN ('leads', 'asignacion', 'historicos')),
    CONSTRAINT user_views_share_chk
        CHECK (share_level IN ('personal', 'team', 'public')),
    -- Si es de equipo, debe apuntar a un supervisor. Si no es de equipo,
    -- team_supervisor_id queda NULL.
    CONSTRAINT user_views_team_ref_chk
        CHECK (
            (share_level = 'team' AND team_supervisor_id IS NOT NULL)
            OR (share_level <> 'team' AND team_supervisor_id IS NULL)
        )
);

COMMENT ON TABLE crm.user_views IS
    'V063: vistas guardadas (filtros + sort + columnas) por usuario, con 3 niveles de visibilidad (personal/team/public). Patron Airtable/Notion.';
COMMENT ON COLUMN crm.user_views.scope IS
    'Que tabla aplica la vista: leads | asignacion | historicos. Una vista solo es valida dentro de su scope.';
COMMENT ON COLUMN crm.user_views.share_level IS
    'personal: solo owner. team: supervisor + sus asesores (team_supervisor_id obligatorio). public: todos (solo admin puede crear).';
COMMENT ON COLUMN crm.user_views.is_default IS
    'Si esta vista se carga automaticamente al entrar al scope. Maximo una por usuario+scope, validado en backend (no via constraint, para no romper bulk operations).';

-- Lookup principal: listar vistas accesibles por un usuario en un scope.
CREATE INDEX IF NOT EXISTS idx_user_views_owner_scope
    ON crm.user_views (user_id, scope);

-- Lookup de vistas compartidas (las que ve gente que no es el owner):
-- team views del supervisor X, todas las publicas.
CREATE INDEX IF NOT EXISTS idx_user_views_shared
    ON crm.user_views (scope, share_level)
    WHERE share_level IN ('team', 'public');

-- Lookup de vistas de un equipo especifico.
CREATE INDEX IF NOT EXISTS idx_user_views_team_supervisor
    ON crm.user_views (team_supervisor_id, scope)
    WHERE share_level = 'team';

-- Trigger generico para updated_at — reusamos el handler ya existente si lo
-- hay; si no, lo creamos in-place.
CREATE OR REPLACE FUNCTION crm.touch_user_views_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_views_updated_at ON crm.user_views;
CREATE TRIGGER trg_user_views_updated_at
    BEFORE UPDATE ON crm.user_views
    FOR EACH ROW
    EXECUTE FUNCTION crm.touch_user_views_updated_at();

COMMIT;

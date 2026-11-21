-- =============================================================================
-- Migracion V020: Tabla crm.audit_lead_access
-- Fecha:       2026-04-11
-- Autor:       Brighton
-- Descripcion: Registro de auditoria sobre acciones con informacion sensible
--              en la seccion de Leads y Asignacion del CRM. Requerido por la
--              gerencia (abril 2026) para prevenir e investigar fuga de datos.
--
--              Cada accion (listar, ver detalle, exportar, intentar copiar)
--              queda registrada con: quien, cuando, desde donde, cuantos
--              registros vio y con que filtros. Retencion: 90 dias calientes
--              (limpieza manual o via cron nocturno).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS crm.audit_lead_access (
    id            BIGSERIAL    PRIMARY KEY,
    user_id       UUID         NOT NULL
                  REFERENCES auth.users(id)
                  ON DELETE CASCADE,
    -- Accion auditada. Valores canonicos usados por el backend:
    --   'list'          — listado paginado (GET /api/leads)
    --   'export'        — descarga Excel (GET /api/leads/exportar)
    --   'detail'        — ver ficha individual (GET /api/leads/{id})
    --   'copy_attempt'  — intento bloqueado de copiar desde el frontend
    action        TEXT         NOT NULL,
    -- Numero de leads expuestos por la accion. En 'list' y 'export' es el
    -- conteo real de filas devueltas. En 'detail' siempre 1. En 'copy_attempt'
    -- queda NULL.
    lead_count    INTEGER,
    -- Filtros o metadata de la accion. Para 'copy_attempt' aqui guardamos
    -- {"page": "leads", "action": "copy"} del payload del frontend.
    filters       JSONB,
    ip_address    INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.audit_lead_access IS
    'Auditoria de accesos a informacion sensible de leads. Retencion recomendada: 90 dias.';
COMMENT ON COLUMN crm.audit_lead_access.action IS
    'Tipo de accion: list | export | detail | copy_attempt';
COMMENT ON COLUMN crm.audit_lead_access.lead_count IS
    'Numero de leads expuestos (NULL para copy_attempt)';
COMMENT ON COLUMN crm.audit_lead_access.filters IS
    'JSONB con filtros aplicados o metadata del evento';

-- Indice principal: investigaciones se hacen por usuario + ventana temporal.
CREATE INDEX IF NOT EXISTS idx_audit_lead_access_user_created
    ON crm.audit_lead_access (user_id, created_at DESC);

-- Indice secundario: busqueda por accion (ej: "dame todos los exports de
-- la ultima semana sin importar el usuario").
CREATE INDEX IF NOT EXISTS idx_audit_lead_access_action_created
    ON crm.audit_lead_access (action, created_at DESC);

-- Indice de retencion: el cron de limpieza barre por created_at.
CREATE INDEX IF NOT EXISTS idx_audit_lead_access_created
    ON crm.audit_lead_access (created_at);

COMMIT;

-- =============================================================================
-- Verificacion post-migracion
-- =============================================================================
-- \d crm.audit_lead_access
-- SELECT count(*) FROM crm.audit_lead_access;  -- 0 al principio
-- =============================================================================

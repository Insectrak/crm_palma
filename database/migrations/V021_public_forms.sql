-- =============================================================================
-- Migración V021: Formularios públicos de captura de leads
-- Fecha:       2026-04-11
-- Autor:       Brighton
-- Descripción: Crea la infraestructura para que admin/supervisores generen
--              formularios públicos con URL compartible. Los leads capturados
--              por estos forms quedan asignados automáticamente al creador.
--
-- Caso de uso:
--   - Paola (supervisor) crea un form antes de un evento en una empresa.
--   - Comparte el link/QR a los asistentes.
--   - Los asistentes llenan el form SIN loguearse al CRM.
--   - Cada lead queda asignado a Paola, con fuente + campaña del evento.
--   - Paola después los redistribuye con la página de Asignación existente.
--
-- Diseño:
--   - config JSONB permite evolución sin cambios de schema (campos, labels,
--     required flags, mensaje de éxito).
--   - slug único en URL → publicable y cacheable.
--   - origen_form_id en crm.leads permite analítica por form sin joins caros.
--   - Idempotente: CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Tabla: crm.public_forms
-- Un formulario público configurable para capturar leads desde un link.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.public_forms (
    id               UUID         PRIMARY KEY DEFAULT uuid_generate_v1(),

    -- Slug único en URL pública: /f/:slug
    slug             VARCHAR(80)  NOT NULL,
    titulo           VARCHAR(120) NOT NULL,
    descripcion      TEXT,

    -- Metadata del evento — se copia a cada lead capturado
    nombre_evento    VARCHAR(200),
    empresa          VARCHAR(200),
    fuente_id        INTEGER
                     REFERENCES crm.fuentes(id)
                     ON DELETE SET NULL,
    campana          VARCHAR(200),

    -- Asignación automática: quien creó el form recibe los leads.
    -- Solo admin/supervisor pueden ser asignados (enforced en el service).
    asignado_a       UUID         NOT NULL
                     REFERENCES auth.users(id)
                     ON DELETE RESTRICT,
    created_by       UUID         NOT NULL
                     REFERENCES auth.users(id)
                     ON DELETE RESTRICT,

    -- Configuración del formulario: qué campos mostrar, labels, required.
    -- Shape esperado:
    -- {
    --   "campos": [
    --     {"key": "nombres", "label": "Nombre", "required": true, "type": "text"},
    --     ...
    --   ],
    --   "mensaje_exito": "¡Gracias! Te contactaremos pronto.",
    --   "redirect_url": null
    -- }
    config           JSONB        NOT NULL DEFAULT '{}'::jsonb,

    -- Controles de vigencia y abuso
    activo           BOOLEAN      NOT NULL DEFAULT TRUE,
    expires_at       TIMESTAMPTZ,
    max_submissions  INTEGER,               -- NULL = ilimitado
    submission_count INTEGER      NOT NULL DEFAULT 0,

    -- Auditoría
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT public_forms_slug_unico       UNIQUE (slug),
    CONSTRAINT public_forms_slug_formato     CHECK (slug ~ '^[a-z0-9][a-z0-9-]{2,79}$'),
    CONSTRAINT public_forms_max_subs_positivo CHECK (max_submissions IS NULL OR max_submissions > 0),
    CONSTRAINT public_forms_submission_count_positivo CHECK (submission_count >= 0)
);

COMMENT ON TABLE  crm.public_forms                    IS 'Formularios públicos para captura de leads desde eventos/campañas.';
COMMENT ON COLUMN crm.public_forms.slug               IS 'Identificador en URL pública /f/:slug. Único, minúsculas, con guiones.';
COMMENT ON COLUMN crm.public_forms.asignado_a         IS 'Usuario (admin/supervisor) que recibe los leads capturados por este form.';
COMMENT ON COLUMN crm.public_forms.created_by         IS 'Usuario que creó el form. Normalmente = asignado_a (se puede diferenciar en el futuro).';
COMMENT ON COLUMN crm.public_forms.config             IS 'JSONB con la configuración visual del form: campos, labels, required, mensaje de éxito.';
COMMENT ON COLUMN crm.public_forms.max_submissions    IS 'Cap opcional de submissions totales del form. NULL = ilimitado.';
COMMENT ON COLUMN crm.public_forms.submission_count   IS 'Contador incrementado en cada submit exitoso. Usado para enforce de max_submissions.';

-- -----------------------------------------------------------------------------
-- Índices — optimizados para los queries esperados:
--   a) Lookup por slug (GET público /f/:slug)    → único, ya indexado por constraint
--   b) Lista de forms por creador (página privada) → parcial sobre activo
--   c) Lookup por asignado_a (para auditoría)      → parcial sobre activo
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_public_forms_created_by_activo
    ON crm.public_forms (created_by, created_at DESC)
    WHERE activo = TRUE;

CREATE INDEX IF NOT EXISTS idx_public_forms_asignado_a_activo
    ON crm.public_forms (asignado_a, created_at DESC)
    WHERE activo = TRUE;

-- Trigger updated_at — reusa la función ya creada en V001.
DROP TRIGGER IF EXISTS trg_public_forms_updated_at ON crm.public_forms;
CREATE TRIGGER trg_public_forms_updated_at
    BEFORE UPDATE ON crm.public_forms
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- Tabla: crm.public_form_submissions
-- Log inmutable de cada submission exitosa. Permite rate limit por IP + análisis
-- histórico + trazabilidad del origen del lead.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.public_form_submissions (
    id          BIGSERIAL    PRIMARY KEY,
    form_id     UUID         NOT NULL
                REFERENCES crm.public_forms(id)
                ON DELETE CASCADE,
    lead_id     INTEGER
                REFERENCES crm.leads(id)
                ON DELETE SET NULL,  -- si se borra el lead, conservamos el submission para análisis
    ip_address  INET,
    user_agent  TEXT,
    payload     JSONB,               -- snapshot de lo que envió el usuario (sin PII duplicada)
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.public_form_submissions IS 'Log de submissions exitosas para auditoría, rate limit por IP y analítica por form.';
COMMENT ON COLUMN crm.public_form_submissions.lead_id IS 'FK al lead creado. NULL si el lead fue borrado posteriormente.';
COMMENT ON COLUMN crm.public_form_submissions.payload IS 'Snapshot de los campos enviados, para auditoría.';

CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id
    ON crm.public_form_submissions (form_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_form_submissions_ip_time
    ON crm.public_form_submissions (ip_address, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_form_submissions_lead_id
    ON crm.public_form_submissions (lead_id)
    WHERE lead_id IS NOT NULL;


-- -----------------------------------------------------------------------------
-- Extensión: vincular crm.leads al form de origen.
-- Permite queries como: "¿cuántos leads capturó el form X en el último mes?"
-- sin hacer JOIN contra public_form_submissions.
-- -----------------------------------------------------------------------------
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS origen_form_id UUID
        REFERENCES crm.public_forms(id)
        ON DELETE SET NULL;

COMMENT ON COLUMN crm.leads.origen_form_id IS
    'FK a crm.public_forms cuando el lead fue capturado por un formulario público.';

CREATE INDEX IF NOT EXISTS idx_leads_origen_form_id
    ON crm.leads (origen_form_id)
    WHERE origen_form_id IS NOT NULL;


COMMIT;

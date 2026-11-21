-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V065 — Sedes / Ubicaciones de servicio                                 ║
-- ║                                                                        ║
-- ║ Un cliente del CRM puede tener varias sedes (Palma del Río con        ║
-- ║ proyectos en Lima y Arequipa; Doctor Muelita con clinicas Centro y    ║
-- ║ Sur). Los leads se gestionan CENTRALIZADO desde un solo CRM, pero    ║
-- ║ cada lead tiene una sede de destino (donde el cliente quiere ser     ║
-- ║ atendido / donde esta el proyecto que le interesa).                  ║
-- ║                                                                        ║
-- ║ Decisiones de diseño (V065):                                          ║
-- ║   - sede_id es un ATRIBUTO del lead, no una organizacion separada.   ║
-- ║   - Asesores ven todos los leads independiente de la sede; pueden    ║
-- ║     filtrar o crear vistas guardadas (V063) que filtren por sede.    ║
-- ║   - role_filter NO se altera — sede es un eje de filtrado opcional,  ║
-- ║     no una capa de permisos.                                          ║
-- ║   - Columnas sede_id NULLABLE en todas las tablas → migracion         ║
-- ║     no-breaking; los leads existentes siguen funcionando sin tocar.   ║
-- ║                                                                        ║
-- ║ Si en el futuro un cliente requiere SEPARACION OPERATIVA (equipo de  ║
-- ║ Lima solo gestiona Lima), se agrega una tabla crm.usuarios_sedes     ║
-- ║ N:N encima sin tocar este schema (OCP).                              ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

CREATE TABLE IF NOT EXISTS crm.sedes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo      VARCHAR(40)  NOT NULL,
    nombre      VARCHAR(120) NOT NULL,
    ciudad      VARCHAR(80),
    direccion   VARCHAR(255),
    telefono    VARCHAR(40),
    color_hex   TEXT         NOT NULL DEFAULT '#6366F1',
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    -- Config libre por sede: horario, branding override, etc. Mantiene la
    -- tabla estable mientras agregamos features sin nuevas migraciones.
    config      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Slug único, case-insensitive. Permite usarse en URLs y payloads
    -- de API ingest (?sede=lima) sin colisiones.
    CONSTRAINT sedes_codigo_unique UNIQUE (codigo),
    CONSTRAINT sedes_codigo_chk    CHECK (codigo ~ '^[a-z0-9][a-z0-9_-]*[a-z0-9]$')
);

COMMENT ON TABLE crm.sedes IS
    'V065: sedes / ubicaciones de servicio del cliente. Atributo del lead, no organización separada.';
COMMENT ON COLUMN crm.sedes.codigo IS
    'Slug case-insensitive usado en payloads de API ingest y URLs. a-z 0-9 _-, min 2 chars.';

-- Trigger updated_at — reusamos el patrón de touch_user_views_updated_at
CREATE OR REPLACE FUNCTION crm.touch_sedes_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sedes_updated_at ON crm.sedes;
CREATE TRIGGER trg_sedes_updated_at
    BEFORE UPDATE ON crm.sedes
    FOR EACH ROW
    EXECUTE FUNCTION crm.touch_sedes_updated_at();


-- ── Vinculacion en entidades del CRM ────────────────────────────────────

-- crm.leads: el atributo principal — a qué sede pertenece este lead.
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS sede_id UUID REFERENCES crm.sedes(id) ON DELETE SET NULL;

COMMENT ON COLUMN crm.leads.sede_id IS
    'V065: sede de destino del lead. NULL = sin asignar (clientes con una sola sede no lo usan).';

-- Indice parcial para filtros tipo "leads de Lima" / reportes por sede.
CREATE INDEX IF NOT EXISTS idx_leads_sede
    ON crm.leads (sede_id)
    WHERE sede_id IS NOT NULL AND activo = TRUE;

-- crm.api_clients: una API key puede tener sede default — todos los
-- leads que entren por esa key heredan la sede salvo override en el payload.
ALTER TABLE crm.api_clients
    ADD COLUMN IF NOT EXISTS sede_id_default UUID REFERENCES crm.sedes(id) ON DELETE SET NULL;

COMMENT ON COLUMN crm.api_clients.sede_id_default IS
    'V065: si se setea, los leads ingestados via esta key reciben este sede_id salvo que el payload traiga "sede" o "sede_codigo" explicito.';

-- crm.public_forms: cada formulario publico apunta a una sede por default.
-- Si el form tiene un campo "sede" expuesto al usuario, el frontend del
-- form override este valor por la respuesta del cliente.
ALTER TABLE crm.public_forms
    ADD COLUMN IF NOT EXISTS sede_id_default UUID REFERENCES crm.sedes(id) ON DELETE SET NULL;

COMMENT ON COLUMN crm.public_forms.sede_id_default IS
    'V065: sede asignada a los leads que entran por este formulario publico. NULL = el form no asigna sede.';

COMMIT;

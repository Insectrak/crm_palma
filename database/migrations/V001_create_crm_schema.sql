-- =============================================================================
-- Migración V001: Creación del schema CRM centralizado
-- Fecha:       2026-04-03
-- Autor:       Brighton
-- Descripción: Crea el schema `crm` con todas las tablas centralizadas para
--              gestión de leads, reemplazando el diseño de schemas por asesor.
--
-- NOTAS DE DISEÑO:
--   - Las FKs apuntan a auth.users(id) que es UUID.
--   - Se elige filtros de aplicación (FastAPI) sobre RLS de PostgreSQL.
--     Ver ARQUITECTURA_CRM.md sección 3 para la justificación.
--   - hash_dedup = SHA256(telefono + fuente_externa_id) para evitar duplicados
--     entre plataformas. Se usa encode(sha256(...::bytea), 'hex').
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Crear schema crm
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS crm;

COMMENT ON SCHEMA crm IS
    'Schema centralizado de CRM: leads, contactos, equipos, auditoría. '
    'Reemplaza los schemas individuales por asesor (asesor1, asesor2...).';

-- -----------------------------------------------------------------------------
-- Tabla: crm.fuentes
-- Catálogo de fuentes de origen de leads. Permite agregar nuevas fuentes
-- sin modificar código ni constraints.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.fuentes (
    id         SERIAL      PRIMARY KEY,
    nombre     TEXT        NOT NULL,   -- 'facebook' | 'instagram' | 'tiktok' | 'excel' | 'manual' | 'web' | 'whatsapp'
    activo     BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fuentes_nombre_unico UNIQUE (nombre)
);

COMMENT ON TABLE  crm.fuentes            IS 'Catálogo de fuentes de captación de leads.';
COMMENT ON COLUMN crm.fuentes.nombre     IS 'Clave de la fuente: facebook, instagram, tiktok, excel, manual, web, whatsapp.';
COMMENT ON COLUMN crm.fuentes.activo     IS 'Si FALSE, la fuente ya no acepta nuevos leads.';

-- -----------------------------------------------------------------------------
-- Tabla: crm.estados_lead
-- Catálogo del pipeline de estados de un lead. Contiene orden visual y
-- color para el frontend kanban/dashboard.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.estados_lead (
    id         SERIAL      PRIMARY KEY,
    nombre     TEXT        NOT NULL,   -- nombre legible del estado
    orden      INTEGER     NOT NULL,   -- para ordenar el pipeline visualmente
    color_hex  TEXT,                   -- color para el frontend (ej: '#22c55e')
    es_final   BOOLEAN     NOT NULL DEFAULT FALSE,  -- indica estado terminal
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT estados_lead_nombre_unico  UNIQUE (nombre),
    CONSTRAINT estados_lead_orden_unico   UNIQUE (orden)
);

COMMENT ON TABLE  crm.estados_lead          IS 'Catálogo de estados del pipeline de un lead.';
COMMENT ON COLUMN crm.estados_lead.orden    IS 'Posición en el pipeline visual. Único por estado.';
COMMENT ON COLUMN crm.estados_lead.color_hex IS 'Color hexadecimal para renderizado en el frontend (#rrggbb).';
COMMENT ON COLUMN crm.estados_lead.es_final IS 'TRUE para estados terminales (Ganado, Perdido, No interesado).';

-- -----------------------------------------------------------------------------
-- Tabla: crm.equipos
-- Relación supervisor → asesor. Un asesor pertenece a exactamente un
-- supervisor activo (constraint UNIQUE sobre asesor_id).
-- Los IDs referencian auth.users (el sistema de usuarios activo).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.equipos (
    id            SERIAL      PRIMARY KEY,
    supervisor_id UUID        NOT NULL
                              REFERENCES auth.users(id)
                              ON DELETE RESTRICT,   -- no borrar supervisor con asesores asignados
    asesor_id     UUID        NOT NULL
                              REFERENCES auth.users(id)
                              ON DELETE CASCADE,    -- si se borra el asesor, se elimina la relación
    activo        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Un asesor activo pertenece a un solo supervisor a la vez
    CONSTRAINT equipos_asesor_unico UNIQUE (asesor_id)
);

COMMENT ON TABLE  crm.equipos              IS 'Relación supervisor-asesor. Un asesor tiene un solo supervisor.';
COMMENT ON COLUMN crm.equipos.supervisor_id IS 'FK a auth.users. El usuario debe tener role=supervisor.';
COMMENT ON COLUMN crm.equipos.asesor_id     IS 'FK a auth.users. El usuario debe tener role=asesor.';
COMMENT ON COLUMN crm.equipos.activo        IS 'FALSE para relaciones históricas desactivadas (no borrar filas).';

CREATE INDEX IF NOT EXISTS idx_equipos_supervisor_id
    ON crm.equipos (supervisor_id);

CREATE INDEX IF NOT EXISTS idx_equipos_asesor_id
    ON crm.equipos (asesor_id);

-- Trigger para mantener updated_at en crm.equipos
CREATE OR REPLACE FUNCTION crm.fn_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    -- Actualiza el campo updated_at al momento actual en cada UPDATE
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION crm.fn_set_updated_at() IS
    'Trigger genérico: actualiza updated_at = NOW() antes de cada UPDATE. '
    'Se reutiliza en todas las tablas que tienen ese campo.';

CREATE TRIGGER trg_equipos_updated_at
    BEFORE UPDATE ON crm.equipos
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

-- -----------------------------------------------------------------------------
-- Tabla: crm.leads
-- Tabla central de todos los leads del CRM. Reemplaza:
--   - public.md_leadasignacion
--   - public.md_leadconsolidado
--   - public.md_leadfacebookinstagram
--   - public.md_leadtiktok
--   - asesorN.md_lead (todos los schemas individuales)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.leads (
    id               SERIAL      PRIMARY KEY,

    -- Datos personales del lead
    nombres          TEXT,                        -- primer nombre o nombre completo si no hay apellido
    apellidos        TEXT,
    telefono         TEXT,                        -- normalizado a solo dígitos idealmente
    email            TEXT,
    dni              TEXT,                        -- documento de identidad (opcional)

    -- Clasificación y origen
    fuente_id        INTEGER
                     REFERENCES crm.fuentes(id)
                     ON DELETE RESTRICT,          -- no borrar fuente con leads asociados
    fuente_externa_id TEXT,                       -- ID original del lead en Facebook/TikTok/Instagram
    fuente_form_id   TEXT,                        -- ID del formulario de origen
    campana          TEXT,                        -- nombre de la campaña publicitaria
    ciudad           TEXT,                        -- ciudad / ubicación del lead
    trabajo          TEXT,                        -- ocupación (campo "job" en formularios)

    -- Estado del pipeline
    estado_id        INTEGER     NOT NULL
                     DEFAULT 1                    -- estado inicial: 'Nuevo' (id=1 del seed)
                     REFERENCES crm.estados_lead(id)
                     ON DELETE RESTRICT,

    -- Asignación a asesor
    asesor_id        UUID
                     REFERENCES auth.users(id)
                     ON DELETE SET NULL,          -- si se borra el asesor, el lead queda sin asignar

    -- Datos flexibles del formulario de origen (campos variables por plataforma)
    datos_extra      JSONB,

    -- Seguimiento
    observaciones    TEXT,
    intentos_contacto INTEGER    NOT NULL DEFAULT 0,  -- número de intentos de contacto realizados
    es_recontacto    BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Control de registro
    activo           BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by       UUID
                     REFERENCES auth.users(id)
                     ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Deduplicación: SHA256(telefono || COALESCE(fuente_externa_id, ''))
    -- Calculado y enviado por la capa de aplicación (n8n o FastAPI)
    hash_dedup       TEXT        UNIQUE,

    CONSTRAINT leads_telefono_o_email CHECK (
        telefono IS NOT NULL OR email IS NOT NULL
    )
);

COMMENT ON TABLE  crm.leads                  IS 'Tabla centralizada de todos los leads del CRM.';
COMMENT ON COLUMN crm.leads.nombres          IS 'Primer nombre o nombre completo cuando no hay apellido separado.';
COMMENT ON COLUMN crm.leads.fuente_id        IS 'FK a crm.fuentes: facebook, instagram, tiktok, excel, manual, etc.';
COMMENT ON COLUMN crm.leads.fuente_externa_id IS 'ID del lead en la plataforma de origen (Facebook lead_id, TikTok lead_id).';
COMMENT ON COLUMN crm.leads.estado_id        IS 'FK a crm.estados_lead. Por defecto 1 = Nuevo.';
COMMENT ON COLUMN crm.leads.asesor_id        IS 'FK a auth.users. NULL = sin asignar.';
COMMENT ON COLUMN crm.leads.datos_extra      IS 'JSONB para campos variables del formulario de origen.';
COMMENT ON COLUMN crm.leads.hash_dedup       IS 'SHA256(telefono || fuente_externa_id) para deduplicación entre plataformas.';
COMMENT ON COLUMN crm.leads.es_recontacto    IS 'TRUE si el lead ya existía y fue reactivado para un nuevo ciclo.';

-- Índices principales (queries esperados: filtrar por estado, asesor, fuente, fecha, búsqueda)
CREATE INDEX IF NOT EXISTS idx_leads_estado_id
    ON crm.leads (estado_id);

CREATE INDEX IF NOT EXISTS idx_leads_asesor_id
    ON crm.leads (asesor_id);

CREATE INDEX IF NOT EXISTS idx_leads_fuente_id
    ON crm.leads (fuente_id);

CREATE INDEX IF NOT EXISTS idx_leads_created_at
    ON crm.leads (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_leads_hash_dedup
    ON crm.leads (hash_dedup)
    WHERE hash_dedup IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_telefono
    ON crm.leads (telefono)
    WHERE telefono IS NOT NULL;

-- Índice GIN sobre datos_extra para queries JSONB
CREATE INDEX IF NOT EXISTS idx_leads_datos_extra
    ON crm.leads USING GIN (datos_extra)
    WHERE datos_extra IS NOT NULL;

-- Índice compuesto para el dashboard: leads por asesor + estado
CREATE INDEX IF NOT EXISTS idx_leads_asesor_estado
    ON crm.leads (asesor_id, estado_id)
    WHERE activo = TRUE;

-- Índice compuesto para el dashboard de supervisores: filtrar por estado + fecha
CREATE INDEX IF NOT EXISTS idx_leads_estado_fecha
    ON crm.leads (estado_id, created_at DESC)
    WHERE activo = TRUE;

CREATE TRIGGER trg_leads_updated_at
    BEFORE UPDATE ON crm.leads
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

-- -----------------------------------------------------------------------------
-- Tabla: crm.contactos
-- Historial de todas las interacciones (llamadas, mensajes, visitas) con
-- un lead. Reemplaza asesorN.md_contactolead.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.contactos (
    id                    SERIAL      PRIMARY KEY,
    lead_id               INTEGER     NOT NULL
                          REFERENCES crm.leads(id)
                          ON DELETE CASCADE,       -- si se borra el lead, se borran sus contactos
    asesor_id             UUID
                          REFERENCES auth.users(id)
                          ON DELETE SET NULL,       -- si se borra el asesor, el contacto queda huérfano de asesor

    tipo_contacto         TEXT        NOT NULL,    -- 'llamada' | 'whatsapp' | 'email' | 'presencial' | 'nota'
    resultado             TEXT,                    -- 'contesto' | 'no_contesto' | 'buzon' | 'cita_agendada' | 'interesado' | 'no_interesado'
    notas                 TEXT,                    -- observaciones del contacto

    -- Seguimiento programado
    proxima_accion        TEXT,                    -- descripción de la próxima acción a tomar
    fecha_proxima_accion  TIMESTAMPTZ,             -- cuándo ejecutar la próxima acción

    -- Cita agendada (si aplica)
    fecha_cita            TIMESTAMPTZ,
    tipo_cita             TEXT,                    -- 'presencial' | 'virtual' | 'telefonica'

    -- Métricas
    duracion_minutos      INTEGER,                 -- para llamadas y reuniones

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.contactos                     IS 'Historial de interacciones con cada lead.';
COMMENT ON COLUMN crm.contactos.tipo_contacto       IS 'Canal usado: llamada, whatsapp, email, presencial, nota.';
COMMENT ON COLUMN crm.contactos.resultado           IS 'Resultado de la interacción: contesto, no_contesto, cita_agendada, etc.';
COMMENT ON COLUMN crm.contactos.fecha_proxima_accion IS 'Fecha programada para el próximo seguimiento.';
COMMENT ON COLUMN crm.contactos.fecha_cita          IS 'Fecha y hora de la cita agendada si tipo_contacto/resultado lo indica.';

CREATE INDEX IF NOT EXISTS idx_contactos_lead_id
    ON crm.contactos (lead_id);

CREATE INDEX IF NOT EXISTS idx_contactos_asesor_id
    ON crm.contactos (asesor_id);

CREATE INDEX IF NOT EXISTS idx_contactos_fecha_proxima_accion
    ON crm.contactos (fecha_proxima_accion)
    WHERE fecha_proxima_accion IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contactos_fecha_cita
    ON crm.contactos (fecha_cita)
    WHERE fecha_cita IS NOT NULL;

-- Índice compuesto para obtener el último contacto de un lead (usado en vistas)
CREATE INDEX IF NOT EXISTS idx_contactos_lead_created
    ON crm.contactos (lead_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- Tabla: crm.asignaciones_log
-- Historial de reasignaciones de leads. Permite auditar quién asignó qué
-- y cuándo. También sirve para calcular tiempos de respuesta.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.asignaciones_log (
    id               SERIAL      PRIMARY KEY,
    lead_id          INTEGER     NOT NULL
                     REFERENCES crm.leads(id)
                     ON DELETE CASCADE,
    asesor_anterior  UUID
                     REFERENCES auth.users(id)
                     ON DELETE SET NULL,
    asesor_nuevo     UUID
                     REFERENCES auth.users(id)
                     ON DELETE SET NULL,
    asignado_por     UUID
                     REFERENCES auth.users(id)
                     ON DELETE SET NULL,
    motivo           TEXT,  -- 'inicial' | 'round_robin' | 'manual_supervisor' | 'manual_admin' | 'reasignacion'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.asignaciones_log              IS 'Historial de asignaciones y reasignaciones de leads a asesores.';
COMMENT ON COLUMN crm.asignaciones_log.motivo       IS 'Razón de la asignación: inicial, round_robin, manual_supervisor, manual_admin, reasignacion.';
COMMENT ON COLUMN crm.asignaciones_log.asesor_anterior IS 'NULL en la primera asignación.';

CREATE INDEX IF NOT EXISTS idx_asignaciones_lead_id
    ON crm.asignaciones_log (lead_id);

CREATE INDEX IF NOT EXISTS idx_asignaciones_asesor_nuevo
    ON crm.asignaciones_log (asesor_nuevo);

-- -----------------------------------------------------------------------------
-- Tabla: crm.leads_raw_facebook
-- Datos crudos de leads recibidos desde Facebook/Instagram Lead Ads.
-- Se mantienen sin modificar para auditoría y reprocesamiento.
-- Una vez procesados y migrados a crm.leads, se marca procesado=TRUE.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.leads_raw_facebook (
    lead_id       TEXT        PRIMARY KEY,         -- ID original de Facebook
    created_time  TIMESTAMPTZ,
    form_id       TEXT,                            -- ID del formulario de Facebook
    ad_name       TEXT,
    adset_name    TEXT,
    campaign_name TEXT,
    platform      TEXT        DEFAULT 'facebook',  -- 'facebook' | 'instagram'
    full_name     TEXT,
    phone         TEXT,
    email         TEXT,
    city          TEXT,
    job           TEXT,
    datos_raw     JSONB,                           -- JSON completo de la respuesta de la API
    procesado     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.leads_raw_facebook         IS 'Datos crudos de Facebook/Instagram Lead Ads. No modificar — es registro fiel de la plataforma.';
COMMENT ON COLUMN crm.leads_raw_facebook.lead_id IS 'ID original del lead en la API de Facebook. Es el PK.';
COMMENT ON COLUMN crm.leads_raw_facebook.procesado IS 'TRUE cuando el lead fue migrado a crm.leads.';
COMMENT ON COLUMN crm.leads_raw_facebook.datos_raw IS 'Respuesta JSON completa de la API de Facebook para auditoría.';

CREATE INDEX IF NOT EXISTS idx_leads_raw_fb_procesado
    ON crm.leads_raw_facebook (procesado)
    WHERE procesado = FALSE;

CREATE INDEX IF NOT EXISTS idx_leads_raw_fb_created_time
    ON crm.leads_raw_facebook (created_time DESC);

-- -----------------------------------------------------------------------------
-- Tabla: crm.leads_raw_tiktok
-- Datos crudos de leads recibidos desde TikTok Lead Ads.
-- Misma filosofía que leads_raw_facebook.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.leads_raw_tiktok (
    lead_id      TEXT        PRIMARY KEY,          -- ID original de TikTok
    created_time TIMESTAMPTZ,
    ad_id        TEXT,
    ad_name      TEXT,
    adgroup_id   TEXT,
    adgroup_name TEXT,
    campaign_id  TEXT,
    campaign_name TEXT,
    form_id      TEXT,
    form_name    TEXT,
    platform     TEXT        DEFAULT 'tiktok',
    full_name    TEXT,
    phone        TEXT,
    email        TEXT,
    city         TEXT,
    job          TEXT,
    datos_raw    JSONB,                            -- JSON completo de la respuesta de la API
    procesado    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.leads_raw_tiktok         IS 'Datos crudos de TikTok Lead Ads. No modificar — es registro fiel de la plataforma.';
COMMENT ON COLUMN crm.leads_raw_tiktok.lead_id IS 'ID original del lead en la API de TikTok. Es el PK.';
COMMENT ON COLUMN crm.leads_raw_tiktok.procesado IS 'TRUE cuando el lead fue migrado a crm.leads.';

CREATE INDEX IF NOT EXISTS idx_leads_raw_tt_procesado
    ON crm.leads_raw_tiktok (procesado)
    WHERE procesado = FALSE;

CREATE INDEX IF NOT EXISTS idx_leads_raw_tt_created_time
    ON crm.leads_raw_tiktok (created_time DESC);

-- -----------------------------------------------------------------------------
-- Tabla: crm.cargas_masivas
-- Registro de cada upload de Excel con su resumen de procesamiento.
-- Los errores individuales se guardan en errores_detalle como JSONB array.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.cargas_masivas (
    id                   SERIAL      PRIMARY KEY,
    usuario_id           UUID
                         REFERENCES auth.users(id)
                         ON DELETE SET NULL,
    nombre_archivo       TEXT        NOT NULL,
    total_registros      INTEGER     NOT NULL DEFAULT 0,
    registros_insertados INTEGER     NOT NULL DEFAULT 0,
    registros_duplicados INTEGER     NOT NULL DEFAULT 0,
    registros_error      INTEGER     NOT NULL DEFAULT 0,
    estado               TEXT        NOT NULL DEFAULT 'procesando',  -- 'procesando' | 'completado' | 'error'
    errores_detalle      JSONB,      -- array de objetos {fila, campo, mensaje}
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cargas_masivas_estado_check CHECK (
        estado IN ('procesando', 'completado', 'error')
    )
);

COMMENT ON TABLE  crm.cargas_masivas                  IS 'Registro de cargas masivas de leads desde Excel.';
COMMENT ON COLUMN crm.cargas_masivas.estado           IS 'Estado del proceso: procesando, completado, error.';
COMMENT ON COLUMN crm.cargas_masivas.errores_detalle  IS 'Array JSONB de errores: [{fila: N, campo: "...", mensaje: "..."}].';

CREATE INDEX IF NOT EXISTS idx_cargas_masivas_usuario_id
    ON crm.cargas_masivas (usuario_id);

CREATE INDEX IF NOT EXISTS idx_cargas_masivas_created_at
    ON crm.cargas_masivas (created_at DESC);

-- -----------------------------------------------------------------------------
-- Tabla: crm.round_robin_estado
-- Controla el estado del algoritmo de asignación round-robin.
-- Una fila por fuente (fuente_id = NULL aplica a todas).
-- SELECT FOR UPDATE en la aplicación garantiza atomicidad.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.round_robin_estado (
    id               SERIAL      PRIMARY KEY,
    fuente_id        INTEGER
                     REFERENCES crm.fuentes(id)
                     ON DELETE CASCADE,            -- si se borra la fuente, se borra el estado
    ultimo_asesor_id UUID
                     REFERENCES auth.users(id)
                     ON DELETE SET NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT round_robin_fuente_unico UNIQUE (fuente_id)
);

COMMENT ON TABLE  crm.round_robin_estado              IS 'Estado del round-robin de asignación automática de leads por fuente.';
COMMENT ON COLUMN crm.round_robin_estado.fuente_id    IS 'NULL = aplica a todas las fuentes globalmente.';
COMMENT ON COLUMN crm.round_robin_estado.ultimo_asesor_id IS 'Último asesor al que se le asignó un lead. El siguiente lead va al asesor siguiente.';

-- -----------------------------------------------------------------------------
-- Tabla: crm.auditoria
-- Log de todas las operaciones de escritura sobre tablas del CRM.
-- BIGSERIAL por volumen esperado alto a lo largo del tiempo.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.auditoria (
    id              BIGSERIAL   PRIMARY KEY,
    tabla           TEXT        NOT NULL,          -- nombre de la tabla afectada
    registro_id     INTEGER,                       -- PK del registro afectado
    accion          TEXT        NOT NULL,          -- 'INSERT' | 'UPDATE' | 'DELETE'
    datos_anteriores JSONB,                        -- valores antes del cambio (NULL en INSERT)
    datos_nuevos    JSONB,                         -- valores después del cambio (NULL en DELETE)
    usuario_id      UUID,                          -- quién hizo el cambio (puede ser NULL si fue sistema)
    ip_address      INET,                          -- IP del cliente (enviada desde la aplicación)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT auditoria_accion_check CHECK (
        accion IN ('INSERT', 'UPDATE', 'DELETE')
    )
);

COMMENT ON TABLE  crm.auditoria                   IS 'Log de auditoría de todas las operaciones de escritura en tablas CRM.';
COMMENT ON COLUMN crm.auditoria.registro_id       IS 'PK del registro afectado en la tabla correspondiente.';
COMMENT ON COLUMN crm.auditoria.datos_anteriores  IS 'Estado anterior del registro. NULL en INSERT.';
COMMENT ON COLUMN crm.auditoria.datos_nuevos      IS 'Estado nuevo del registro. NULL en DELETE.';
COMMENT ON COLUMN crm.auditoria.usuario_id        IS 'FK a auth.users. NULL si fue operación automática del sistema.';

-- Índices para consultas de auditoría (buscar por tabla+id o por usuario)
CREATE INDEX IF NOT EXISTS idx_auditoria_tabla_registro
    ON crm.auditoria (tabla, registro_id);

CREATE INDEX IF NOT EXISTS idx_auditoria_usuario_id
    ON crm.auditoria (usuario_id)
    WHERE usuario_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auditoria_created_at
    ON crm.auditoria (created_at DESC);

-- GIN sobre datos_nuevos para búsquedas dentro del JSONB de auditoría
CREATE INDEX IF NOT EXISTS idx_auditoria_datos_nuevos
    ON crm.auditoria USING GIN (datos_nuevos)
    WHERE datos_nuevos IS NOT NULL;

COMMIT;

-- =============================================================================
-- Migración V126: Tabla crm.lead_historial_cambios
-- Fecha:       2026-11-04
-- Autor:       Brighton CRM Team
-- Descripción: Historial de cambios y auditoría de datos para leads.
--              Registra todos los cambios realizados en los datos de un lead
--              (nombres, teléfono, fuente, estado, asesor, calidad, observaciones,
--              ficha técnica, etc.), indicando quién lo cambió, cuándo, valor
--              anterior y valor nuevo.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS crm.lead_historial_cambios (
    id                  BIGSERIAL PRIMARY KEY,
    lead_id             INTEGER NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    usuario_id          UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    usuario_nombre      TEXT,
    usuario_rol         TEXT,
    campo               TEXT NOT NULL,
    campo_label         TEXT NOT NULL,
    valor_anterior      TEXT,
    valor_nuevo         TEXT,
    origen              TEXT NOT NULL DEFAULT 'edicion_ficha',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  crm.lead_historial_cambios IS
    'Historial de cambios y auditoría de campos de leads.';
COMMENT ON COLUMN crm.lead_historial_cambios.campo IS
    'Identificador del campo modificado (telefono, nombres, estado_id, etc.)';
COMMENT ON COLUMN crm.lead_historial_cambios.campo_label IS
    'Nombre legible del campo (Teléfono, Nombres, Estado, etc.)';
COMMENT ON COLUMN crm.lead_historial_cambios.origen IS
    'Origen del cambio: edicion_ficha | cambio_estado | reasignacion | cambio_fuente | carga_masiva | sistema';

-- Índices de consulta frecuente: por lead ordenado por fecha descendente
CREATE INDEX IF NOT EXISTS idx_lead_historial_cambios_lead_created
    ON crm.lead_historial_cambios (lead_id, created_at DESC);

-- Búsqueda por usuario (para auditoría de acciones de usuarios)
CREATE INDEX IF NOT EXISTS idx_lead_historial_cambios_usuario
    ON crm.lead_historial_cambios (usuario_id)
    WHERE usuario_id IS NOT NULL;

-- Búsqueda por campo
CREATE INDEX IF NOT EXISTS idx_lead_historial_cambios_campo
    ON crm.lead_historial_cambios (campo);

-- Backfill histórico inicial desde crm.asignaciones_log (si la tabla existe)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'crm' AND table_name = 'asignaciones_log'
    ) THEN
        INSERT INTO crm.lead_historial_cambios (
            lead_id, usuario_id, usuario_nombre, usuario_rol,
            campo, campo_label, valor_anterior, valor_nuevo, origen, created_at
        )
        SELECT
            al.lead_id,
            al.asignado_por,
            COALESCE(NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''), u.email, 'Sistema') AS usuario_nombre,
            COALESCE(u.role, 'sistema') AS usuario_rol,
            'asesor_id' AS campo,
            'Asesor asignado' AS campo_label,
            COALESCE(NULLIF(TRIM(COALESCE(ua.first_name, '') || ' ' || COALESCE(ua.last_name, '')), ''), 'Sin asignar') AS valor_anterior,
            COALESCE(NULLIF(TRIM(COALESCE(un.first_name, '') || ' ' || COALESCE(un.last_name, '')), ''), 'Sin asignar') AS valor_nuevo,
            'reasignacion' AS origen,
            al.created_at
        FROM crm.asignaciones_log al
        LEFT JOIN auth.users u ON u.id = al.asignado_por
        LEFT JOIN auth.users ua ON ua.id = al.asesor_anterior
        LEFT JOIN auth.users un ON un.id = al.asesor_nuevo
        WHERE EXISTS (SELECT 1 FROM crm.leads l WHERE l.id = al.lead_id);
    END IF;
END $$;

-- Backfill histórico inicial desde crm.contactos con tipo_contacto = 'cambio_estado'
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'crm' AND table_name = 'contactos'
    ) THEN
        INSERT INTO crm.lead_historial_cambios (
            lead_id, usuario_id, usuario_nombre, usuario_rol,
            campo, campo_label, valor_anterior, valor_nuevo, origen, created_at
        )
        SELECT
            c.lead_id,
            c.asesor_id,
            COALESCE(NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''), u.email, 'Sistema') AS usuario_nombre,
            COALESCE(u.role, 'sistema') AS usuario_rol,
            'estado_id' AS campo,
            'Estado' AS campo_label,
            '—' AS valor_anterior,
            COALESCE(c.notas, 'Cambio de estado') AS valor_nuevo,
            'cambio_estado' AS origen,
            c.created_at
        FROM crm.contactos c
        LEFT JOIN auth.users u ON u.id = c.asesor_id
        WHERE c.tipo_contacto = 'cambio_estado'
          AND EXISTS (SELECT 1 FROM crm.leads l WHERE l.id = c.lead_id);
    END IF;
END $$;

-- Backfill histórico inicial desde crm.contactos con tipo_contacto = 'cambio_fuente'
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'crm' AND table_name = 'contactos'
    ) THEN
        INSERT INTO crm.lead_historial_cambios (
            lead_id, usuario_id, usuario_nombre, usuario_rol,
            campo, campo_label, valor_anterior, valor_nuevo, origen, created_at
        )
        SELECT
            c.lead_id,
            c.asesor_id,
            COALESCE(NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''), u.email, 'Sistema') AS usuario_nombre,
            COALESCE(u.role, 'sistema') AS usuario_rol,
            'fuente_id' AS campo,
            'Fuente' AS campo_label,
            '—' AS valor_anterior,
            COALESCE(c.notas, 'Cambio de fuente') AS valor_nuevo,
            'cambio_fuente' AS origen,
            c.created_at
        FROM crm.contactos c
        LEFT JOIN auth.users u ON u.id = c.asesor_id
        WHERE c.tipo_contacto = 'cambio_fuente'
          AND EXISTS (SELECT 1 FROM crm.leads l WHERE l.id = c.lead_id);
    END IF;
END $$;

COMMIT;


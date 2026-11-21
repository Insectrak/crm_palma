-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V046 — Asignacion automatica de leads (Lead Routing Engine)           ║
-- ║                                                                        ║
-- ║ Comercial pidio: que el supervisor quede mas libre. Hoy el lead llega ║
-- ║ al supervisor por round-robin diario y este reasigna manualmente al   ║
-- ║ asesor. Esta migracion agrega un segundo salto AUTOMATICO al asesor.  ║
-- ║                                                                        ║
-- ║ ARQUITECTURA:                                                          ║
-- ║                                                                        ║
-- ║ 1. assignment_config — singleton, control global (auto on/off,         ║
-- ║    fallback, horario)                                                  ║
-- ║ 2. lead_assignment_rules — reglas configurables ordenadas por          ║
-- ║    prioridad (estilo Salesforce Lead Assignment Rules)                ║
-- ║ 3. asesor_settings — capacity, horario, vacaciones por asesor         ║
-- ║ 4. assignment_log — audit detallado de cada decision automatica       ║
-- ║ 5. equipos.auto_asignar_enabled — toggle por supervisor (gradual      ║
-- ║    rollout)                                                            ║
-- ║                                                                        ║
-- ║ FAIL-SAFE: si auto-asignacion esta apagada o falla, comportamiento    ║
-- ║ actual se preserva (lead queda en el supervisor). NUNCA bloqueamos    ║
-- ║ la ingesta por un fallo del motor de routing.                         ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ─── 1) Configuracion global (singleton) ───────────────────────────────────

CREATE TABLE IF NOT EXISTS crm.assignment_config (
    id                          INTEGER     PRIMARY KEY DEFAULT 1
                                CHECK (id = 1),                 -- Singleton: una sola fila
    auto_asignar_enabled        BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Estrategia cuando NO existe regla matcheante:
    --   'round_robin_equipo' = round-robin entre asesores del equipo del supervisor
    --   'manual'             = deja al supervisor (comportamiento actual)
    estrategia_default          VARCHAR(40) NOT NULL DEFAULT 'round_robin_equipo'
                                CHECK (estrategia_default IN ('round_robin_equipo', 'manual')),
    max_leads_abiertos_default  INTEGER     NOT NULL DEFAULT 50
                                CHECK (max_leads_abiertos_default > 0),
    -- Horario laboral global (opcional). NULL = 24/7.
    horario_inicio              TIME        DEFAULT '08:00',
    horario_fin                 TIME        DEFAULT '20:00',
    -- Que hacer si lead llega fuera de horario:
    --   'asignar_igual'    = ignora horario, asigna ya
    --   'cola_proximo_dia' = lo deja en supervisor hasta proximo horario
    --   'asignar_supervisor' = fallback al supervisor (comportamiento actual)
    estrategia_fuera_horario    VARCHAR(40) NOT NULL DEFAULT 'asignar_igual'
                                CHECK (estrategia_fuera_horario IN ('asignar_igual', 'cola_proximo_dia', 'asignar_supervisor')),
    -- Que hacer si NINGUN asesor esta disponible (todos full / vacaciones / fuera horario):
    estrategia_sin_disponibles  VARCHAR(40) NOT NULL DEFAULT 'asignar_supervisor'
                                CHECK (estrategia_sin_disponibles IN ('asignar_supervisor', 'asignar_admin', 'cola_pendiente', 'ignorar_capacity')),
    -- Considerar leads "abiertos" para capacity:
    --   'todos_activos'        = WHERE l.activo = TRUE AND e.es_final = FALSE
    --   'sin_contacto_48h'     = leads sin contacto desde hace > 48h
    capacity_definicion         VARCHAR(40) NOT NULL DEFAULT 'todos_activos'
                                CHECK (capacity_definicion IN ('todos_activos', 'sin_contacto_48h')),
    notificar_supervisor_auto   BOOLEAN     NOT NULL DEFAULT TRUE,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by                  UUID        REFERENCES auth.users(id) ON DELETE SET NULL
);

-- Asegura que exista la fila singleton
INSERT INTO crm.assignment_config (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE crm.assignment_config IS
    'Configuracion global del motor de asignacion automatica. Singleton (id=1). Default: auto-asignar OFF.';


-- ─── 2) Reglas de asignacion (estilo Salesforce Lead Assignment Rules) ────

CREATE TABLE IF NOT EXISTS crm.lead_assignment_rules (
    id              SERIAL          PRIMARY KEY,
    nombre          VARCHAR(120)    NOT NULL,
    descripcion     TEXT,
    prioridad       INTEGER         NOT NULL,                   -- 1 = mas alta. Las reglas se evaluan en orden.
    activo          BOOLEAN         NOT NULL DEFAULT TRUE,
    -- Condiciones (todas deben matchear: AND logico). NULL = no filtra por ese campo.
    fuente_id       INTEGER         REFERENCES crm.fuentes(id) ON DELETE CASCADE,
    api_client_id   UUID            REFERENCES crm.api_clients(id) ON DELETE CASCADE,
    campana_pattern VARCHAR(200),                               -- LIKE pattern (ej '%palmeras%')
    palabras_clave  TEXT[],                                     -- match en observaciones
    horario_inicio  TIME,                                       -- regla solo aplica en este horario
    horario_fin     TIME,
    dias_semana     INTEGER[],                                  -- [1..7] lunes=1; NULL = todos
    -- Target: a que se asigna cuando matchea
    asignar_a_tipo  VARCHAR(20)     NOT NULL
                    CHECK (asignar_a_tipo IN ('asesor_especifico', 'equipo_round_robin', 'asesor_round_robin_global')),
    asignar_a_id    UUID            REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Si la regla matchea pero el target esta sin capacity, ¿que hacer?
    fallback_si_lleno VARCHAR(40)   NOT NULL DEFAULT 'siguiente_regla'
                    CHECK (fallback_si_lleno IN ('siguiente_regla', 'estrategia_default', 'asignar_igual')),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_by      UUID            REFERENCES auth.users(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Total leads asignados por esta regla (incremental, evita full-scan en UI)
    total_aplicaciones INTEGER      NOT NULL DEFAULT 0,
    ultima_aplicacion  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_lead_rules_prioridad
    ON crm.lead_assignment_rules (prioridad) WHERE activo = TRUE;

COMMENT ON TABLE crm.lead_assignment_rules IS
    'Reglas configurables de routing. Se evaluan en orden de prioridad ascendente (1 primero).';
COMMENT ON COLUMN crm.lead_assignment_rules.asignar_a_tipo IS
    '''asesor_especifico'' = asignar siempre al asesor en asignar_a_id. ''equipo_round_robin'' = round-robin del equipo del supervisor en asignar_a_id. ''asesor_round_robin_global'' = round-robin global de asesores activos.';


-- ─── 3) Configuracion por asesor ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS crm.asesor_settings (
    asesor_id               UUID            PRIMARY KEY
                            REFERENCES auth.users(id) ON DELETE CASCADE,
    disponible_rotacion     BOOLEAN         NOT NULL DEFAULT TRUE,
    -- NULL = usa max_leads_abiertos_default de assignment_config
    max_leads_abiertos      INTEGER         CHECK (max_leads_abiertos IS NULL OR max_leads_abiertos > 0),
    -- Horario individual del asesor. NULL = usa horario global o 24/7
    horario_inicio          TIME,
    horario_fin             TIME,
    dias_semana             INTEGER[],                          -- [1..7] lunes=1
    -- Vacaciones / ausencias programadas
    ausencia_desde          DATE,
    ausencia_hasta          DATE,
    motivo_ausencia         VARCHAR(120),
    -- Peso para round-robin: 1.0 = normal, 2.0 = recibe el doble. Default 1.
    peso_rotacion           DECIMAL(3,1)    NOT NULL DEFAULT 1.0
                            CHECK (peso_rotacion >= 0 AND peso_rotacion <= 10),
    notas                   TEXT,
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_by              UUID            REFERENCES auth.users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_asesor_settings_disponible
    ON crm.asesor_settings (disponible_rotacion) WHERE disponible_rotacion = TRUE;

CREATE INDEX IF NOT EXISTS idx_asesor_settings_ausencia
    ON crm.asesor_settings (ausencia_desde, ausencia_hasta)
    WHERE ausencia_desde IS NOT NULL;

COMMENT ON TABLE crm.asesor_settings IS
    'Configuracion individual por asesor para auto-asignacion: capacity, horario, vacaciones, peso.';
COMMENT ON COLUMN crm.asesor_settings.peso_rotacion IS
    'Peso para round-robin ponderado. 1.0 default. 2.0 = recibe el doble que un asesor con peso 1.';


-- ─── 4) Toggle por equipo (supervisor) ─────────────────────────────────────

ALTER TABLE crm.equipos
    ADD COLUMN IF NOT EXISTS auto_asignar_enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN crm.equipos.auto_asignar_enabled IS
    'Si TRUE, los leads que caen al supervisor de este equipo se auto-asignan al asesor. Default FALSE para rollout gradual.';


-- ─── 5) Audit log de decisiones de asignacion automatica ──────────────────

CREATE TABLE IF NOT EXISTS crm.assignment_log (
    id                  BIGSERIAL       PRIMARY KEY,
    lead_id             INTEGER         REFERENCES crm.leads(id) ON DELETE CASCADE,
    fecha               TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- Estrategia que termino aplicandose
    estrategia          VARCHAR(40)     NOT NULL,               -- 'regla' | 'round_robin_equipo' | 'fallback_supervisor' | 'manual' | etc
    regla_aplicada_id   INTEGER         REFERENCES crm.lead_assignment_rules(id) ON DELETE SET NULL,
    supervisor_id       UUID            REFERENCES auth.users(id) ON DELETE SET NULL,
    asignado_a_id       UUID            REFERENCES auth.users(id) ON DELETE SET NULL,
    candidatos_evaluados JSONB,                                 -- [{user_id, nombre, leads_abiertos, disponible, motivo_descarte}]
    razon               TEXT,                                   -- explicacion human-readable de la eleccion
    duracion_ms         INTEGER                                 -- tiempo de calculo (telemetria)
);

CREATE INDEX IF NOT EXISTS idx_assignment_log_fecha
    ON crm.assignment_log (fecha DESC);

CREATE INDEX IF NOT EXISTS idx_assignment_log_lead
    ON crm.assignment_log (lead_id);

CREATE INDEX IF NOT EXISTS idx_assignment_log_asignado
    ON crm.assignment_log (asignado_a_id, fecha DESC);

COMMENT ON TABLE crm.assignment_log IS
    'Audit trail de cada decision del motor de auto-asignacion. Forensics + analisis de comportamiento.';


-- ─── 6) Funcion helper: count de leads abiertos por asesor ────────────────

CREATE OR REPLACE FUNCTION crm.count_leads_abiertos(
    p_asesor_id UUID,
    p_modo VARCHAR DEFAULT 'todos_activos'
) RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    IF p_modo = 'sin_contacto_48h' THEN
        SELECT COUNT(*)::int INTO v_count
        FROM crm.leads l
        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
        WHERE l.asesor_id = p_asesor_id
          AND l.activo = TRUE
          AND COALESCE(e.es_final, FALSE) = FALSE
          AND NOT EXISTS (
              SELECT 1 FROM crm.contactos c
              WHERE c.lead_id = l.id
                AND c.tipo_contacto != 'cambio_estado'
                AND c.created_at >= NOW() - INTERVAL '48 hours'
          );
    ELSE
        -- 'todos_activos' default
        SELECT COUNT(*)::int INTO v_count
        FROM crm.leads l
        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
        WHERE l.asesor_id = p_asesor_id
          AND l.activo = TRUE
          AND COALESCE(e.es_final, FALSE) = FALSE;
    END IF;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION crm.count_leads_abiertos IS
    'Cuenta leads abiertos de un asesor segun la definicion de capacity (todos_activos | sin_contacto_48h).';


-- ─── 7) Trigger: incrementar contador de regla cuando se aplica ───────────

CREATE OR REPLACE FUNCTION crm.bump_rule_counter() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.regla_aplicada_id IS NOT NULL THEN
        UPDATE crm.lead_assignment_rules
        SET total_aplicaciones = total_aplicaciones + 1,
            ultima_aplicacion  = NEW.fecha
        WHERE id = NEW.regla_aplicada_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_assignment_log_bump_rule ON crm.assignment_log;
CREATE TRIGGER trg_assignment_log_bump_rule
    AFTER INSERT ON crm.assignment_log
    FOR EACH ROW
    EXECUTE FUNCTION crm.bump_rule_counter();


-- ─── 8) Seed: asesor_settings para todos los asesores activos ─────────────
-- Garantiza que cada asesor tenga su fila de configuracion lista. Solo
-- inserta los que no la tienen — idempotente.

INSERT INTO crm.asesor_settings (asesor_id, disponible_rotacion)
SELECT u.id, TRUE
FROM auth.users u
WHERE u.role IN ('asesor', 'supervisor')
  AND u.is_active = TRUE
ON CONFLICT (asesor_id) DO NOTHING;

COMMIT;

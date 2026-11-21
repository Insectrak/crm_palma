-- V072: team status history — auditoria de bloqueos/desbloqueos automaticos
-- por el circuit breaker (ADR-0010).
--
-- Permite responder preguntas como:
--   "¿Cuantas veces se bloqueo el equipo de Paola la ultima semana?"
--   "¿Cuanto tiempo estuvo bloqueado en promedio?"
--   "¿Que asesor o evento dispara mas bloqueos?"
--
-- Insertamos UNA fila cada vez que un equipo CAMBIA de estado
-- (active <-> at_risk <-> blocked). NO insertamos snapshots periodicos
-- — la tabla se mantiene chica (1-10 filas por equipo por dia tipico).

CREATE TABLE IF NOT EXISTS crm.team_status_history (
    id              BIGSERIAL PRIMARY KEY,
    supervisor_id   UUID         NOT NULL,
    previous_status TEXT,                  -- 'active', 'at_risk', 'blocked', NULL en el primer registro
    new_status      TEXT         NOT NULL CHECK (new_status IN ('active', 'at_risk', 'blocked')),
    -- Snapshot de la metrica que disparo el cambio (para auditoria)
    total_asesores       INTEGER NOT NULL,
    asesores_pausados    INTEGER NOT NULL,
    pct_pausados         NUMERIC(5,2) NOT NULL,   -- 0.00 a 100.00
    -- Que asesor (si alguno) disparo el cambio (asesor que se pauso/despauso justo antes)
    triggering_user_id   UUID,
    -- Texto libre con el motivo / contexto (opcional)
    nota                 TEXT,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indices para queries tipicas:
-- 1. Historia de un equipo (ordenado por tiempo).
CREATE INDEX IF NOT EXISTS idx_team_status_history_supervisor_time
    ON crm.team_status_history (supervisor_id, created_at DESC);

-- 2. Filtrar por estado (ej: "todos los eventos de bloqueo del mes").
CREATE INDEX IF NOT EXISTS idx_team_status_history_new_status
    ON crm.team_status_history (new_status, created_at DESC);

COMMENT ON TABLE crm.team_status_history IS
    'Auditoria de transiciones de estado de equipo por el circuit breaker (ADR-0010). '
    'Una fila por cambio de estado — NO snapshots periodicos.';
COMMENT ON COLUMN crm.team_status_history.pct_pausados IS
    'Porcentaje (0-100) de asesores del equipo en estado pausado/ausente/lleno al momento del cambio.';
COMMENT ON COLUMN crm.team_status_history.triggering_user_id IS
    'Usuario cuya transicion de estado (pause/unpause) disparo el recalculo. NULL si fue un check periodico.';

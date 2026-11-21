-- =============================================================================
-- Migración V009: Catálogos de tipos y resultados de contacto
-- Fecha:       2026-04-05
-- Autor:       Brighton
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS crm.tipos_contacto (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    icono   TEXT DEFAULT '📋',
    activo  BOOLEAN DEFAULT TRUE,
    orden   INT DEFAULT 0
);

INSERT INTO crm.tipos_contacto (nombre, icono, orden) VALUES
    ('Cita oficina Bustamante', '🏢', 1),
    ('Cita oficina Umacollo',   '🏢', 2),
    ('Cita Exteriores',         '🚗', 3),
    ('Cita Virtual',            '💻', 4)
ON CONFLICT (nombre) DO NOTHING;

CREATE TABLE IF NOT EXISTS crm.resultados_contacto (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    activo  BOOLEAN DEFAULT TRUE,
    orden   INT DEFAULT 0
);

INSERT INTO crm.resultados_contacto (nombre, orden) VALUES
    ('contesto',      1),
    ('no_contesto',   2),
    ('buzon',         3),
    ('cita_agendada', 4),
    ('no_interesado', 5),
    ('volver_llamar', 6)
ON CONFLICT (nombre) DO NOTHING;

COMMIT;

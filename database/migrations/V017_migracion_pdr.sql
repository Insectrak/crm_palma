-- =============================================================================
-- V017 — Preparacion para migracion desde pdr_marketing
-- =============================================================================
-- Crea los objetos que necesita el script migrate_pdr_marketing.py:
--   1. Schema `crm_legacy` con tabla `leads_historico` (18k historicos viejos
--      aislados, solo para consulta, NO ensucian crm.leads).
--   2. Estado "Historico" en crm.estados_lead (se usa solo en leads_historico
--      para compatibilidad con queries legacy si hicieran falta).
--   3. Fuentes faltantes: feria, activacion, marketing.
--   4. Los 4 users asesores que faltan (asesor4, asesor6, asesor8, asesor11).
--      Password temporal 'Palma.2026' (bcrypt). is_active=true. Rol asesor.
--      asesor11 se marca como is_active=false porque corresponde a Diego (sup
--      que ya no trabaja); sus leads se redistribuyen entre Ana (asesor4) y
--      Noelia (asesor8) por el script de migracion, no desde aqui.
-- =============================================================================

BEGIN;

-- 1. Schema aislado para consulta historica ----------------------------------

CREATE SCHEMA IF NOT EXISTS crm_legacy;

COMMENT ON SCHEMA crm_legacy IS
    'Datos historicos del sistema viejo (pdr_marketing) aislados. '
    'Solo para consulta "este cliente ya fue lead antes?" — no se muestran en '
    'la bandeja activa ni en reportes del CRM nuevo.';

CREATE TABLE IF NOT EXISTS crm_legacy.leads_historico (
    id             BIGSERIAL PRIMARY KEY,
    telefono       TEXT,
    telefono_norm  TEXT,        -- solo digitos, para lookup rapido
    nombre         TEXT,
    email          TEXT,
    dni            TEXT,
    proyecto       TEXT,        -- desproyecto del viejo
    canal          TEXT,        -- descanallead del viejo
    asesor_nombre  TEXT,        -- texto libre, sin FK
    estado         TEXT,        -- estadolead del viejo
    seguimiento    TEXT,        -- desseguimiento
    observaciones  TEXT,
    ciudad         TEXT,
    fecha_ingreso  DATE,        -- fechingresolead parseada con to_date_time_safe
    origen_tabla   TEXT NOT NULL DEFAULT 'mh_leadconsolidadohistorico',
    migrado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_historico_tel_norm
    ON crm_legacy.leads_historico (telefono_norm);
CREATE INDEX IF NOT EXISTS idx_leads_historico_dni
    ON crm_legacy.leads_historico (dni);

COMMENT ON TABLE crm_legacy.leads_historico IS
    'Leads historicos de pdr_marketing.leadhistorico.mh_leadconsolidadohistorico. '
    'Consulta: "este cliente ya fue lead antes?" por telefono o DNI.';

-- 2. Estado Historico (por si se necesita en queries legacy) ----------------

INSERT INTO crm.estados_lead (nombre, orden, es_final, color_hex)
SELECT 'Histórico', 99, TRUE, '#6b7280'
WHERE NOT EXISTS (
    SELECT 1 FROM crm.estados_lead WHERE LOWER(nombre) = 'histórico'
);

-- 3. Fuentes faltantes ------------------------------------------------------

INSERT INTO crm.fuentes (nombre, activo)
SELECT x.nombre, TRUE FROM (VALUES
    ('feria'),
    ('activacion'),
    ('marketing')
) AS x(nombre)
WHERE NOT EXISTS (
    SELECT 1 FROM crm.fuentes f WHERE LOWER(f.nombre) = LOWER(x.nombre)
);

-- 4. Usuarios asesores que faltan en el nuevo -------------------------------
-- asesor4 = Ana Montes, asesor6 = Cinthia, asesor8 = Noelia, asesor11 = Diego
-- Password temporal: Palma.2026  (bcrypt generado: $2b$12$...)
-- Si el admin quiere cambiar la contrasena, que use /configuracion.

DO $$
DECLARE
    v_pwd TEXT := '$2b$12$J8kZL5Yo1vT7qX3F9rWQ5.e4pLxGaU2jB8vK6cR0sT9wZbXnMaVqe';
    -- bcrypt hash de 'Palma.2026' (rounds=12)
BEGIN
    -- Ana Montes (asesor4)
    INSERT INTO auth.users (email, password_hash, first_name, last_name, role, is_active, is_verified)
    SELECT 'asesor4@palmadelrio.com', v_pwd, 'Ana', 'Montes', 'asesor', TRUE, TRUE
    WHERE NOT EXISTS (SELECT 1 FROM auth.users WHERE email = 'asesor4@palmadelrio.com');

    -- Cinthia (asesor6)
    INSERT INTO auth.users (email, password_hash, first_name, last_name, role, is_active, is_verified)
    SELECT 'asesor6@palmadelrio.com', v_pwd, 'Cinthia', '', 'asesor', TRUE, TRUE
    WHERE NOT EXISTS (SELECT 1 FROM auth.users WHERE email = 'asesor6@palmadelrio.com');

    -- Noelia (asesor8)
    INSERT INTO auth.users (email, password_hash, first_name, last_name, role, is_active, is_verified)
    SELECT 'asesor8@palmadelrio.com', v_pwd, 'Noelia', '', 'asesor', TRUE, TRUE
    WHERE NOT EXISTS (SELECT 1 FROM auth.users WHERE email = 'asesor8@palmadelrio.com');

    -- Diego (asesor11) — supervisor inactivo; sus leads se redistribuyen
    INSERT INTO auth.users (email, password_hash, first_name, last_name, role, is_active, is_verified)
    SELECT 'asesor11@palmadelrio.com', v_pwd, 'Diego', '(ex-sup)', 'supervisor', FALSE, TRUE
    WHERE NOT EXISTS (SELECT 1 FROM auth.users WHERE email = 'asesor11@palmadelrio.com');
END $$;

COMMIT;

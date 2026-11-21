-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V043 — Sistema de Metas Mensuales (Sprint 3)                          ║
-- ║                                                                        ║
-- ║ Comercial pidio: cumplimiento de metas mensuales por asesor / equipo. ║
-- ║ Patron Salesforce Quotas / HubSpot Goals: el admin / supervisor       ║
-- ║ define una meta numerica por persona y por mes; el sistema mide       ║
-- ║ cumplimiento real-time contra los datos de leads / citas / llamadas.  ║
-- ║                                                                        ║
-- ║ SCHEMA:                                                                ║
-- ║   crm.metas_mensuales (id, asesor_id, mes, meta_ventas,                ║
-- ║                        meta_citas, meta_llamadas, created_at, ...)    ║
-- ║                                                                        ║
-- ║ Una fila por (asesor_id, mes). Mes en formato 'YYYY-MM-01' (primer    ║
-- ║ dia del mes; el periodo es el mes completo).                          ║
-- ║                                                                        ║
-- ║ NOTA: equipo / supervisor se infiere via crm.equipos — no es necesa-  ║
-- ║ rio guardar 'meta_equipo' aqui; el backend agrega sumas de los        ║
-- ║ asesores del equipo cuando hace falta.                                ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

CREATE TABLE IF NOT EXISTS crm.metas_mensuales (
    id              SERIAL      PRIMARY KEY,
    asesor_id       UUID        NOT NULL
                    REFERENCES auth.users(id)
                    ON DELETE CASCADE,
    mes             DATE        NOT NULL,    -- siempre primer dia del mes
    meta_ventas     INTEGER     NOT NULL DEFAULT 0,
    meta_citas      INTEGER     NOT NULL DEFAULT 0,
    meta_llamadas   INTEGER     NOT NULL DEFAULT 0,
    notas           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      UUID
                    REFERENCES auth.users(id)
                    ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT metas_mensuales_uniq UNIQUE (asesor_id, mes),
    CONSTRAINT metas_mensuales_mes_valido
        CHECK (EXTRACT(DAY FROM mes) = 1),
    CONSTRAINT metas_mensuales_no_negativas
        CHECK (meta_ventas >= 0 AND meta_citas >= 0 AND meta_llamadas >= 0)
);

CREATE INDEX IF NOT EXISTS idx_metas_mensuales_mes
    ON crm.metas_mensuales (mes);

CREATE INDEX IF NOT EXISTS idx_metas_mensuales_asesor_mes
    ON crm.metas_mensuales (asesor_id, mes DESC);

COMMENT ON TABLE crm.metas_mensuales IS
    'Metas mensuales de ventas/citas/llamadas por asesor. Salesforce Quotas / HubSpot Goals.';
COMMENT ON COLUMN crm.metas_mensuales.mes IS
    'Primer dia del mes que la meta cubre. Ej: 2026-05-01 = mayo 2026.';
COMMENT ON COLUMN crm.metas_mensuales.meta_ventas IS
    'Cantidad de leads que deben llegar a estado Ganado en el mes.';
COMMENT ON COLUMN crm.metas_mensuales.meta_citas IS
    'Cantidad de citas (cita_estado_id NOT NULL) que deben agendarse en el mes.';
COMMENT ON COLUMN crm.metas_mensuales.meta_llamadas IS
    'Cantidad total de llamadas a registrar en el mes.';

COMMIT;

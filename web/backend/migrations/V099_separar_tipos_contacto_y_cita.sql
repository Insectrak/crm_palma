-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V099 — Separación de Tipos de Contacto y Tipos de Cita                ║
-- ║                                                                        ║
-- ║ MOTIVO:                                                                ║
-- ║ Históricamente crm.tipos_contacto fue inicializado con modalidades de  ║
-- ║ cita ("Cita oficina Bustamante", etc.) en lugar de canales de          ║
-- ║ comunicación ("Llamada", "WhatsApp", "Email", etc.).                  ║
-- ║                                                                        ║
-- ║ SOLUCIÓN:                                                              ║
-- ║ 1. Crear crm.tipos_cita para modalidades/ubicaciones de cita.          ║
-- ║ 2. Sembrar tipos de cita por defecto.                                  ║
-- ║ 3. Sembrar canales de comunicación reales en crm.tipos_contacto.       ║
-- ║ 4. Desactivar modalidades de cita que estaban en crm.tipos_contacto.   ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1. Catálogo de Tipos de Cita ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crm.tipos_cita (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    icono   TEXT DEFAULT '📋',
    activo  BOOLEAN DEFAULT TRUE,
    orden   INT DEFAULT 0
);

COMMENT ON TABLE crm.tipos_cita IS 'Catálogo de modalidades y lugares de cita (Oficina Bustamante, Virtual, etc.)';

-- Migrar / Inicializar modalidades de cita
INSERT INTO crm.tipos_cita (nombre, icono, orden) VALUES
    ('Cita oficina Bustamante', '🏢', 1),
    ('Cita oficina Umacollo',   '🏢', 2),
    ('Cita Exteriores',         '🚗', 3),
    ('Cita Virtual',            '💻', 4)
ON CONFLICT (nombre) DO UPDATE SET activo = TRUE;

-- Si existían otros tipos personalizados con 'Cita' en tipos_contacto, copiarlos a tipos_cita
INSERT INTO crm.tipos_cita (nombre, icono, orden)
SELECT nombre, icono, orden
FROM crm.tipos_contacto
WHERE nombre ILIKE 'Cita%'
ON CONFLICT (nombre) DO NOTHING;

-- ── 2. Canales de comunicación en crm.tipos_contacto ───────────────────────
CREATE TABLE IF NOT EXISTS crm.tipos_contacto (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    icono   TEXT DEFAULT '📋',
    activo  BOOLEAN DEFAULT TRUE,
    orden   INT DEFAULT 0
);

INSERT INTO crm.tipos_contacto (nombre, icono, orden)
SELECT v.nombre, v.icono, v.orden
FROM (VALUES
    ('Llamada',    '📞', 1),
    ('WhatsApp',   '💬', 2),
    ('Email',      '✉️', 3),
    ('Presencial', '👥', 4),
    ('Nota',       '📝', 5)
) AS v(nombre, icono, orden)
WHERE NOT EXISTS (
    SELECT 1 FROM crm.tipos_contacto tc WHERE LOWER(tc.nombre) = LOWER(v.nombre)
);

-- ── 3. Desactivar modalidades de cita que estaban en crm.tipos_contacto ───
UPDATE crm.tipos_contacto
SET activo = FALSE
WHERE nombre ILIKE 'Cita%'
  OR nombre IN ('Cita oficina Bustamante', 'Cita oficina Umacollo', 'Cita Exteriores', 'Cita Virtual');

COMMIT;

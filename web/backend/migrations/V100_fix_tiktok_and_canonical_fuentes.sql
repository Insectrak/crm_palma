-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V100 — Catálogo canónico de fuentes                                     ║
-- ║                                                                        ║
-- ║ MOTIVO:                                                                ║
-- ║ Asegurar la existencia de las fuentes canónicas en crm.fuentes para    ║
-- ║ evitar fallos de resolución en nuevos leads sin forzar updates.        ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

CREATE TABLE IF NOT EXISTS crm.fuentes (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    activo  BOOLEAN DEFAULT TRUE
);

INSERT INTO crm.fuentes (nombre, activo)
SELECT v.nombre, v.activo
FROM (VALUES
    ('TikTok',    TRUE),
    ('Facebook',  TRUE),
    ('Instagram', TRUE),
    ('WhatsApp',  TRUE),
    ('Web',       TRUE),
    ('Referido',  TRUE),
    ('Manual',    TRUE)
) AS v(nombre, activo)
WHERE NOT EXISTS (
    SELECT 1 FROM crm.fuentes f WHERE LOWER(f.nombre) = LOWER(v.nombre)
);

COMMIT;

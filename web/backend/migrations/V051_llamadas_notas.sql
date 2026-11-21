-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V051 — Notas + resultado en llamadas del celular                      ║
-- ║                                                                        ║
-- ║ Las llamadas que entran via la APK Android (sync del call log) llegan ║
-- ║ a crm.llamadas con datos basicos (telefono, duracion, tipo, fecha)    ║
-- ║ pero el asesor no podia agregar contexto: "el cliente pidio recall   ║
-- ║ jueves", "no contesto pero dejo voicemail", etc.                       ║
-- ║                                                                        ║
-- ║ Esta migracion agrega:                                                 ║
-- ║   - notas: texto libre para que el asesor anote contexto              ║
-- ║   - resultado: codigo del catalogo (contacto, no_contesto, etc.)     ║
-- ║                                                                        ║
-- ║ Endpoint PATCH /api/llamadas/{id} permite editarlos sin modificar    ║
-- ║ los datos automaticos (duracion, fecha) capturados por el OS.        ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.llamadas
    ADD COLUMN IF NOT EXISTS notas TEXT,
    ADD COLUMN IF NOT EXISTS resultado VARCHAR(40),
    ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS edited_by UUID REFERENCES auth.users(id) ON DELETE SET NULL;

COMMENT ON COLUMN crm.llamadas.notas IS
    'Notas que el asesor agrega despues de la llamada. Las llamadas del cel llegan vacias y el asesor las completa.';
COMMENT ON COLUMN crm.llamadas.resultado IS
    'Codigo del catalogo de resultados (contacto, no_contesto, ocupado, etc.). Editable por el asesor.';

COMMIT;

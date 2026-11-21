-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V068.4 — Backfill protection: external_created_at en lead_recontactos ║
-- ║                                                                        ║
-- ║ Pregunta del usuario en prod: "como sabemos que ↻ N es REAL?           ║
-- ║ Si TikTok hace backfill de un lead viejo, no deberia contar como       ║
-- ║ reengagement aunque el fext sea distinto."                             ║
-- ║                                                                        ║
-- ║ Solucion: capturar el timestamp REAL del evento en TikTok (campo       ║
-- ║ "created_time" del CSV) y validar contra el created_at del lead:       ║
-- ║                                                                        ║
-- ║   external_created_at <= lead.created_at  -> backfill -> SKIP          ║
-- ║   external_created_at >  lead.created_at  -> reactivacion REAL         ║
-- ║                                                                        ║
-- ║ Esta es la tercera capa de defensa, despues de:                        ║
-- ║   V068.2  fext dedup (mismo lead_id -> SKIP)                           ║
-- ║   V068.3  Reactivation Window (mismo dia que creacion -> SKIP)         ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- Agregar la columna. NULL para filas historicas — el codigo de validacion
-- aplica solo cuando el valor esta presente (best-effort backward compat).
ALTER TABLE crm.lead_recontactos
    ADD COLUMN IF NOT EXISTS external_created_at TIMESTAMPTZ;

COMMENT ON COLUMN crm.lead_recontactos.external_created_at IS
    'V068.4: timestamp REAL del evento en el proveedor (TikTok CSV '
    '"created_time", Meta webhook "created_time", etc). NULL para filas '
    'pre-V068.4. Si > NULL Y <= lead.created_at, era backfill y NO se '
    'insertó (la decisión vive en ingest_core.py / lead_recapture.py).';

COMMIT;

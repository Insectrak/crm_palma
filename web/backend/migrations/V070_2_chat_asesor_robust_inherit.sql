-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V070.2 — Chat asesor: backfill robusto + indice para join por phone    ║
-- ║                                                                        ║
-- ║ Iteracion final tras V070 y V070.1. El bug "Sin asignar" persistia    ║
-- ║ para algunos leads aunque ambas migraciones intentaron repararlo.     ║
-- ║                                                                        ║
-- ║ Bugs detectados en V070.1:                                            ║
-- ║   - DISTINCT ON con ORDER BY created_at DESC tomaba el lead MAS       ║
-- ║     RECIENTE por phone. Si ese lead no tenia asesor (NULL), el WHERE  ║
-- ║     lo filtraba y NO buscaba otros leads del mismo phone que SI       ║
-- ║     tuvieran asesor. Multi-lead-same-phone = caso comun cuando hay    ║
-- ║     duplicados.                                                       ║
-- ║   - Sin indice en REGEXP_REPLACE(telefono, '\D', '', 'g'), el match   ║
-- ║     por phone era O(n) por row -> lento en >1000 convs.               ║
-- ║                                                                        ║
-- ║ Fix:                                                                  ║
-- ║   1. DISTINCT ON con prioridad explicita por asesor IS NULL (los que  ║
-- ║      tienen asesor real ganan).                                       ║
-- ║   2. Indice expresion sobre phone normalizado en ambas tablas.        ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1) Indices para acelerar el match por phone normalizado ─────────────
CREATE INDEX IF NOT EXISTS idx_leads_telefono_digits
    ON crm.leads (REGEXP_REPLACE(COALESCE(telefono, ''), '\D', '', 'g'))
 WHERE activo = TRUE AND telefono IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_conv_phone_digits
    ON crm.wa_conversations (REGEXP_REPLACE(COALESCE(wa_phone, ''), '\D', '', 'g'))
 WHERE lead_id IS NULL OR asesor_id IS NULL;

-- ── 2) Backfill robusto: prefiere leads CON asesor sobre los que no ────
-- Para cada phone, elige el lead que MEJOR matchea:
--   - Primero los que tienen asesor_id NOT NULL (los priorizamos)
--   - Despues por created_at DESC (mas reciente)
-- Cubre el escenario multi-lead-mismo-telefono donde el mas reciente
-- pudiera no tener asesor pero uno mas antiguo si.

UPDATE crm.wa_conversations c
   SET lead_id    = matched.lead_id,
       asesor_id  = COALESCE(c.asesor_id, matched.asesor_id),
       updated_at = NOW()
  FROM (
        SELECT DISTINCT ON (phone_digits)
               phone_digits,
               lead_id,
               asesor_id
          FROM (
                SELECT REGEXP_REPLACE(COALESCE(l.telefono, ''), '\D', '', 'g') AS phone_digits,
                       l.id        AS lead_id,
                       l.asesor_id AS asesor_id,
                       l.created_at
                  FROM crm.leads l
                 WHERE l.activo = TRUE
                   AND l.telefono IS NOT NULL
                   AND l.telefono <> ''
               ) base
         ORDER BY phone_digits,
                  -- (asesor_id IS NULL) ASC en PG: FALSE(0) antes que TRUE(1)
                  -- entonces los con asesor real ganan sobre los sin asesor.
                  (asesor_id IS NULL) ASC,
                  created_at DESC
        ) matched
 WHERE c.lead_id IS NULL
   AND REGEXP_REPLACE(COALESCE(c.wa_phone, ''), '\D', '', 'g') = matched.phone_digits;

-- ── 3) Re-run del backfill de V070 (idempotente) por si V070 no corrio ─
-- antes que se creara una conv huerfana, ahora ya estaria linkeada por (2).
UPDATE crm.wa_conversations c
   SET asesor_id  = l.asesor_id,
       updated_at = NOW()
  FROM crm.leads l
 WHERE l.id = c.lead_id
   AND c.asesor_id IS NULL
   AND l.asesor_id IS NOT NULL;

COMMIT;

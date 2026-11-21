-- ║ V115 — Corrección y Deduplicación de Campañas TikTok/Meta                            ║
-- ║ Corrige campañas originadas en TikTok Ads que fueron erróneamente atribuidas a Meta  ║
-- ║ Ads debido al cache compartido de meta_catalog_cache.                                 ║

-- 1. Actualizar el nombre legible en el registro de TikTok tomando el nombre del registro Meta duplicado
UPDATE crm.campaign_supervisor_assignments t
SET campaign_name = m.campaign_name,
    supervisor_id = COALESCE(t.supervisor_id, m.supervisor_id),
    distribution_mode = CASE WHEN t.supervisor_id IS NULL AND m.supervisor_id IS NOT NULL THEN m.distribution_mode ELSE t.distribution_mode END,
    updated_at = NOW()
FROM crm.campaign_supervisor_assignments m
WHERE m.campaign_id = t.campaign_id
  AND m.provider = 'meta'
  AND t.provider = 'tiktok'
  AND m.campaign_name IS NOT NULL
  AND m.campaign_name !~ '^\d+$';

-- 2. Migrar asignaciones de supervisores desde el registro Meta al registro TikTok
INSERT INTO crm.campaign_assigned_supervisors (assignment_id, supervisor_id, last_assigned_at, created_at)
SELECT t.id, cas.supervisor_id, cas.last_assigned_at, cas.created_at
FROM crm.campaign_supervisor_assignments m
JOIN crm.campaign_supervisor_assignments t
  ON t.campaign_id = m.campaign_id AND t.provider = 'tiktok'
JOIN crm.campaign_assigned_supervisors cas
  ON cas.assignment_id = m.id
WHERE m.provider = 'meta'
ON CONFLICT (assignment_id, supervisor_id) DO NOTHING;

-- 3. Eliminar los registros 'meta' duplicados que ya tienen su par en 'tiktok'
DELETE FROM crm.campaign_supervisor_assignments m
USING crm.campaign_supervisor_assignments t
WHERE m.campaign_id = t.campaign_id
  AND m.provider = 'meta'
  AND t.provider = 'tiktok';

-- 4. Si quedan registros 'meta' cuyos leads pertenecen exclusivamente a la fuente TikTok, cambiarles el provider a 'tiktok'
UPDATE crm.campaign_supervisor_assignments m
SET provider = 'tiktok',
    updated_at = NOW()
WHERE m.provider = 'meta'
  AND EXISTS (
      SELECT 1
      FROM crm.leads l
      JOIN crm.fuentes f ON f.id = l.fuente_id
      WHERE (l.campana = m.campaign_id OR l.campana = m.campaign_name)
        AND LOWER(f.nombre) LIKE '%tiktok%'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM crm.leads l2
      JOIN crm.fuentes f2 ON f2.id = l2.fuente_id
      WHERE (l2.campana = m.campaign_id OR l2.campana = m.campaign_name)
        AND (LOWER(f2.nombre) LIKE '%facebook%' OR LOWER(f2.nombre) LIKE '%instagram%' OR LOWER(f2.nombre) LIKE '%meta%')
  )
  AND NOT EXISTS (
      SELECT 1
      FROM crm.campaign_supervisor_assignments t2
      WHERE t2.provider = 'tiktok' AND t2.campaign_id = m.campaign_id
  );

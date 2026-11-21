-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V113 — Respaldo visible de matrículas en cartera de supervisión        ║
-- ║                                                                        ║
-- ║ Garantiza que las matrículas (ganados/cierres) gestionadas bajo la     ║
-- ║ supervisión de un equipo permanezcan visibles en los KPIs y reportes  ║
-- ║ del supervisor correspondiente aun si el asesor sale del equipo o es  ║
-- ║ dado de baja.                                                          ║
-- ╚════════════════════════════════════════════════════════════════════════╝

DROP VIEW IF EXISTS crm.vw_kpis_por_asesor CASCADE;

CREATE OR REPLACE VIEW crm.vw_kpis_por_asesor AS
SELECT
    a.id                                                   AS asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                                                AS asesor_email,
    COALESCE(eq.supervisor_id, l.supervisor_id)           AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
    COUNT(l.id)                                            AS total_leads,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación') AS leads_en_negociacion,
    COUNT(l.id) FILTER (
        WHERE e.nombre ILIKE '%matr%'
           OR e.nombre ILIKE '%ganad%'
           OR e.nombre ILIKE '%cierr%'
           OR l.tipo_cierre IS NOT NULL
    )                                                      AS leads_ganado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
    COUNT(l.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,
    COUNT(l.id) FILTER (
        WHERE NOT EXISTS (
            SELECT 1 FROM crm.contactos c
            WHERE c.lead_id = l.id
              AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
        )
    )                                                      AS leads_sin_contacto,
    COUNT(DISTINCT co_vencido.lead_id)                     AS leads_accion_vencida,
    CASE
        WHEN COUNT(l.id) = 0 THEN 0
        ELSE ROUND(
            100.0 * COUNT(l.id) FILTER (
                WHERE e.nombre ILIKE '%matr%'
                   OR e.nombre ILIKE '%ganad%'
                   OR e.nombre ILIKE '%cierr%'
                   OR l.tipo_cierre IS NOT NULL
            ) / COUNT(l.id),
            2
        )
    END                                                    AS tasa_conversion_pct
FROM auth.users a
LEFT JOIN crm.equipos eq
    ON eq.asesor_id = a.id AND eq.activo = TRUE
LEFT JOIN crm.leads l
    ON l.asesor_id = a.id AND l.activo = TRUE
LEFT JOIN auth.users s
    ON s.id = COALESCE(eq.supervisor_id, l.supervisor_id)
LEFT JOIN crm.estados_lead e
    ON e.id = l.estado_id
LEFT JOIN LATERAL (
    SELECT c.lead_id
    FROM crm.contactos c
    WHERE c.lead_id = l.id
      AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
      AND c.fecha_proxima_accion < NOW()
    ORDER BY c.created_at DESC
    LIMIT 1
) co_vencido ON co_vencido.lead_id = l.id
WHERE a.role IN ('asesor', 'supervisor')
  AND (a.is_active = TRUE OR l.id IS NOT NULL)
GROUP BY a.id, a.first_name, a.last_name, a.email, COALESCE(eq.supervisor_id, l.supervisor_id), s.first_name, s.last_name;

COMMENT ON VIEW crm.vw_kpis_por_asesor IS
    'V113: KPIs por asesor/supervisor con respaldo visible de matrículas para el supervisor correspondiente aun si el asesor cambia de equipo.';


CREATE OR REPLACE VIEW crm.vw_kpis_por_asesor AS
SELECT
    a.id                    AS asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                 AS asesor_email,

    -- Supervisor del asesor
    eq.supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,

    -- Conteos por estado del pipeline (disjuntos)
    COUNT(l.id)             AS total_leads,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación') AS leads_en_negociacion,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Ganado')         AS leads_ganado,
    COUNT(l.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
    COUNT(l.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,

    -- Leads sin contactar todavía — V039: excluye los que solo tienen
    -- cambios de estado registrados (eso no cuenta como contacto real).
    COUNT(l.id) FILTER (
        WHERE NOT EXISTS (
            SELECT 1 FROM crm.contactos c
            WHERE c.lead_id = l.id
              AND c.tipo_contacto != 'cambio_estado'
        )
    )                       AS leads_sin_contacto,

    -- Leads con próxima acción vencida (fecha_proxima_accion < ahora)
    COUNT(DISTINCT co_vencido.lead_id) AS leads_accion_vencida,

    -- Tasa de conversión (Ganados / Total)
    CASE
        WHEN COUNT(l.id) = 0 THEN 0
        ELSE ROUND(
            100.0 * COUNT(l.id) FILTER (WHERE e.nombre = 'Ganado') / COUNT(l.id),
            2
        )
    END                     AS tasa_conversion_pct

FROM auth.users a
LEFT JOIN crm.equipos eq
    ON eq.asesor_id = a.id AND eq.activo = TRUE
LEFT JOIN auth.users s
    ON s.id = eq.supervisor_id
LEFT JOIN crm.leads l
    ON l.asesor_id = a.id AND l.activo = TRUE
LEFT JOIN crm.estados_lead e
    ON e.id = l.estado_id
LEFT JOIN LATERAL (
    -- Subconsulta lateral: leads de este asesor con próxima acción vencida.
    -- V039: también excluye contactos tipo cambio_estado.
    SELECT DISTINCT c.lead_id
    FROM crm.contactos c
    JOIN crm.leads lv ON lv.id = c.lead_id
    WHERE lv.asesor_id = a.id
      AND c.tipo_contacto != 'cambio_estado'
      AND c.fecha_proxima_accion < NOW()
      AND c.id = (
          SELECT id FROM crm.contactos
          WHERE lead_id = c.lead_id
            AND tipo_contacto != 'cambio_estado'
          ORDER BY created_at DESC
          LIMIT 1
      )
) co_vencido ON TRUE
WHERE a.role = 'asesor'
  AND a.is_active = TRUE
GROUP BY
    a.id, a.first_name, a.last_name, a.email,
    eq.supervisor_id, s.first_name, s.last_name;

COMMENT ON VIEW crm.vw_kpis_por_asesor IS
    'KPIs de performance individual por asesor. V039: leads_sin_contacto y '
    'leads_accion_vencida excluyen los registros de tipo_contacto=cambio_estado, '
    'que son eventos administrativos y no contactos reales con el cliente.';

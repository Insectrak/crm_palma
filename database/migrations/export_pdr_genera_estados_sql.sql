-- =============================================================================
-- EJECUTAR EN: pdr_marketing
-- RESULTADO:   Un único bloque SQL — copiar y pegar en el servidor CRM
--
-- PROPÓSITO: Actualiza crm.leads.estado_id según el ÚLTIMO estado de contacto
--            registrado por los asesores en sus schemas individuales.
--
-- Instrucciones:
--   1. Ejecuta en pgAdmin conectado a pdr_marketing
--   2. En Data Output verás UNA celda con el SQL generado
--   3. Copia el contenido de esa celda
--   4. Abre una nueva pestaña conectada al servidor CRM
--   5. Pega y ejecuta
-- =============================================================================

SELECT
    'BEGIN;' || chr(10) ||

    '-- Actualizar estado_id de leads según último contacto registrado' || chr(10) ||
    'UPDATE crm.leads l' || chr(10) ||
    'SET estado_id = e.id, updated_at = NOW()' || chr(10) ||
    'FROM (VALUES' || chr(10) ||

    string_agg(
        '  (''' || replace(latest.codigo_lead, '''', '''''') || ''', ''' || latest.estado_crm || ''')',
        ',' || chr(10)
        ORDER BY latest.codigo_lead
    ) || chr(10) ||

    ') AS m(fuente_externa_id, estado_nombre)' || chr(10) ||
    'JOIN crm.estados_lead e ON e.nombre = m.estado_nombre' || chr(10) ||
    'WHERE l.fuente_externa_id = m.fuente_externa_id' || chr(10) ||
    '  AND l.activo = TRUE;' || chr(10) || chr(10) ||

    '-- Verificar resultado' || chr(10) ||
    'SELECT e.nombre AS estado, COUNT(l.id) AS total' || chr(10) ||
    'FROM crm.leads l' || chr(10) ||
    'LEFT JOIN crm.estados_lead e ON e.id = l.estado_id' || chr(10) ||
    'WHERE l.activo = TRUE' || chr(10) ||
    'GROUP BY e.nombre' || chr(10) ||
    'ORDER BY total DESC;' || chr(10) || chr(10) ||

    'COMMIT;'

    AS sql_para_crm

FROM (
    -- Último estado por lead (ordenado por fecha más reciente)
    SELECT DISTINCT ON (codigo_lead)
        codigo_lead,
        CASE
            WHEN LOWER(TRIM(COALESCE(estado_contacto_lead, ''))) IN ('venta')
                THEN 'Ganado'
            WHEN LOWER(TRIM(COALESCE(estado_contacto_lead, ''))) IN ('con reserva', 'cita', 'cita programada')
                THEN 'En negociación'
            WHEN LOWER(TRIM(COALESCE(estado_contacto_lead, ''))) IN ('interesado', 'cliente potencial')
                THEN 'Calificado'
            WHEN LOWER(TRIM(COALESCE(estado_contacto_lead, ''))) IN ('desistio', 'desistió', 'desestimado', 'no interesado')
                THEN 'No interesado'
            WHEN LOWER(TRIM(COALESCE(estado_contacto_lead, ''))) = 'no contactado'
                THEN 'Nuevo'
            -- en seguimiento, no responde, corta llamada, seguimiento, sin_estado,
            -- no contesta, volver a llamare, null → Contactado
            ELSE 'Contactado'
        END AS estado_crm
    FROM (
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor7.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor2.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor6.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor4.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor9.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor13.md_contactolead WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor10.md_contactolead WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor5.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor11.md_contactolead WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT codigo_lead, estado_contacto_lead, fecha_contacto_lead FROM asesor12.md_contactolead WHERE codigo_lead IS NOT NULL
    ) all_contactos
    ORDER BY codigo_lead, fecha_contacto_lead DESC NULLS LAST
) latest;

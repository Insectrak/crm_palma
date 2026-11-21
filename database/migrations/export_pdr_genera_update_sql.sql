-- =============================================================================
-- EJECUTAR EN: pdr_marketing
-- RESULTADO:   Un único bloque SQL — copiar y pegar en el servidor CRM
--
-- Instrucciones:
--   1. Ejecuta esta query en pgAdmin conectado a pdr_marketing
--   2. En Data Output verás UNA celda con el SQL generado
--   3. Copia el contenido de esa celda
--   4. Abre una nueva pestaña en pgAdmin conectado al servidor CRM
--   5. Pega y ejecuta el SQL
-- =============================================================================

SELECT
    'BEGIN;' || chr(10) ||

    '-- Insertar fuentes nuevas si no existen' || chr(10) ||
    'INSERT INTO crm.fuentes (nombre, activo) VALUES' || chr(10) ||
    '  (''wa mensaje'', TRUE), (''fb mensaje'', TRUE),' || chr(10) ||
    '  (''ig mensaje'', TRUE), (''tt mensaje'', TRUE),' || chr(10) ||
    '  (''fb'', TRUE), (''ig'', TRUE), (''referido'', TRUE)' || chr(10) ||
    'ON CONFLICT (nombre) DO UPDATE SET activo = TRUE;' || chr(10) || chr(10) ||

    '-- Actualizar fuente_id de leads' || chr(10) ||
    'UPDATE crm.leads l' || chr(10) ||
    'SET fuente_id = f.id, updated_at = NOW()' || chr(10) ||
    'FROM (VALUES' || chr(10) ||

    string_agg(
        '  (''' || replace(la.lead_id::text, '''', '''''') || ''', ''' ||
        CASE
            WHEN LOWER(TRIM(la.plataforma)) = 'wa mensaje' THEN 'wa mensaje'
            WHEN LOWER(TRIM(la.plataforma)) = 'fb mensaje' THEN 'fb mensaje'
            WHEN LOWER(TRIM(la.plataforma)) = 'ig mensaje' THEN 'ig mensaje'
            WHEN LOWER(TRIM(la.plataforma)) = 'tt mensaje' THEN 'tt mensaje'
            WHEN LOWER(TRIM(la.plataforma)) = 'fb'         THEN 'fb'
            WHEN LOWER(TRIM(la.plataforma)) = 'ig'         THEN 'ig'
            WHEN LOWER(TRIM(la.plataforma)) = 'tt'         THEN 'tt mensaje'
            WHEN LOWER(TRIM(la.plataforma)) = 'referido'   THEN 'referido'
            WHEN LOWER(la.plataforma) LIKE '%whatsapp%'    THEN 'whatsapp'
            WHEN LOWER(la.plataforma) LIKE '%facebook%'    THEN 'facebook'
            WHEN LOWER(la.plataforma) LIKE '%instagram%'   THEN 'instagram'
            WHEN LOWER(la.plataforma) LIKE '%tiktok%'      THEN 'tiktok'
            WHEN LOWER(la.plataforma) LIKE '%excel%'       THEN 'excel'
            WHEN LOWER(la.plataforma) LIKE '%web%'         THEN 'web'
            ELSE 'manual'
        END || ''')',
        ',' || chr(10)
        ORDER BY la.id
    ) || chr(10) ||

    ') AS m(fuente_externa_id, plataforma_crm)' || chr(10) ||
    'JOIN crm.fuentes f ON f.nombre = m.plataforma_crm' || chr(10) ||
    'WHERE l.fuente_externa_id = m.fuente_externa_id' || chr(10) ||
    '  AND l.activo = TRUE;' || chr(10) || chr(10) ||

    '-- Verificar resultado' || chr(10) ||
    'SELECT f.nombre AS fuente, COUNT(l.id) AS total_leads' || chr(10) ||
    'FROM crm.leads l' || chr(10) ||
    'LEFT JOIN crm.fuentes f ON f.id = l.fuente_id' || chr(10) ||
    'WHERE l.activo = TRUE' || chr(10) ||
    'GROUP BY f.nombre' || chr(10) ||
    'ORDER BY total_leads DESC;' || chr(10) || chr(10) ||

    'COMMIT;'

    AS sql_para_crm

FROM public.md_leadasignacion la
WHERE la.plataforma IS NOT NULL;

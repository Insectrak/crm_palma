-- =============================================================================
-- EJECUTAR EN: pdr_marketing
-- RESULTADO:   Un único bloque SQL — copiar y pegar en el servidor CRM
--
-- PROPÓSITO: Inserta el historial de contactos (1,053 registros) de todos los
--            schemas de asesores en crm.contactos.
--            El link se hace por: codigo_lead → crm.leads.fuente_externa_id
--                                 asesor_schema → auth.users.advisor_schema
--
-- Instrucciones:
--   1. Ejecuta en pgAdmin conectado a pdr_marketing
--   2. En Data Output verás UNA celda con el SQL generado
--   3. Copia el contenido de esa celda (puede ser grande)
--   4. Abre una nueva pestaña conectada al servidor CRM
--   5. Pega y ejecuta
-- =============================================================================

SELECT
    'BEGIN;' || chr(10) ||

    '-- Limpiar migración anterior si existe (idempotente)' || chr(10) ||
    'DELETE FROM crm.contactos WHERE origen = ''pdr_migration'';' || chr(10) || chr(10) ||
    '-- Insertar historial de contactos de pdr_marketing en crm.contactos' || chr(10) ||
    'INSERT INTO crm.contactos' || chr(10) ||
    '  (lead_id, asesor_id, tipo_contacto, resultado, notas, proxima_accion,' || chr(10) ||
    '   fecha_cita, tipo_cita, created_at, origen)' || chr(10) ||
    'SELECT' || chr(10) ||
    '  l.id,' || chr(10) ||
    '  NULL,' || chr(10) ||
    '  m.tipo_contacto,' || chr(10) ||
    '  NULLIF(m.resultado, ''''),' || chr(10) ||
    '  NULLIF(m.notas, ''''),' || chr(10) ||
    '  NULLIF(m.proxima_accion, ''''),' || chr(10) ||
    '  NULLIF(m.fecha_cita, '''')::timestamptz,' || chr(10) ||
    '  NULLIF(m.tipo_cita, ''''),' || chr(10) ||
    '  COALESCE(NULLIF(m.fecha_contacto, '''')::timestamptz, NOW()),' || chr(10) ||
    '  ''pdr_migration''' || chr(10) ||
    'FROM (VALUES' || chr(10) ||

    string_agg(
        '  (''' || c.fuente_externa_id     || ''', ''' ||
                   c.asesor_schema         || ''', ''' ||
                   c.tipo_contacto         || ''', ''' ||
                   c.resultado             || ''', ''' ||
                   c.notas_esc             || ''', ''' ||
                   c.proxima_accion_esc    || ''', ''' ||
                   c.fecha_cita_str        || ''', ''' ||
                   c.tipo_cita_esc         || ''', ''' ||
                   c.fecha_contacto_str    || ''')',
        ',' || chr(10)
        ORDER BY c.asesor_schema, c.fuente_externa_id
    ) || chr(10) ||

    ') AS m(fuente_externa_id, asesor_schema, tipo_contacto, resultado, notas,' || chr(10) ||
    '       proxima_accion, fecha_cita, tipo_cita, fecha_contacto)' || chr(10) ||
    'JOIN crm.leads l' || chr(10) ||
    '  ON l.fuente_externa_id = m.fuente_externa_id AND l.activo = TRUE;' || chr(10) || chr(10) ||

    '-- Verificar' || chr(10) ||
    'SELECT COUNT(*) AS contactos_insertados FROM crm.contactos;' || chr(10) || chr(10) ||

    'COMMIT;'

    AS sql_para_crm

FROM (
    SELECT
        -- Escapar fuente_externa_id (por si tiene comillas, aunque es UUID/número)
        replace(raw.codigo_lead, '''', '''''')  AS fuente_externa_id,
        raw.asesor_schema,

        -- tipo_contacto: normalizar a valores del CRM
        COALESCE(LOWER(TRIM(raw.tipo_contacto_lead)), 'llamada') AS tipo_contacto,

        -- resultado: mapear desde estado_contacto_lead
        CASE
            WHEN LOWER(TRIM(COALESCE(raw.estado_contacto_lead, ''))) IN ('cita', 'cita programada', 'con reserva')
                THEN 'cita_agendada'
            WHEN LOWER(TRIM(COALESCE(raw.estado_contacto_lead, ''))) IN ('interesado', 'cliente potencial', 'en seguimiento', 'seguimiento', 'venta')
                THEN 'interesado'
            WHEN LOWER(TRIM(COALESCE(raw.estado_contacto_lead, ''))) IN ('desistio', 'desistió', 'desestimado', 'no interesado')
                THEN 'no_interesado'
            WHEN LOWER(TRIM(COALESCE(raw.estado_contacto_lead, ''))) IN ('no responde', 'no contesta', 'no contactado', 'volver a llamare', 'corta llamada')
                THEN 'no_contesto'
            ELSE ''
        END AS resultado,

        -- Escapar campos de texto libre (comillas simples y limpiar saltos de línea)
        replace(
            replace(
                replace(COALESCE(raw.observaciones, ''), E'\r\n', ' '),
                E'\n', ' '),
            '''', '''''')
        AS notas_esc,

        replace(
            replace(
                replace(COALESCE(raw.seguimiento_lead, ''), E'\r\n', ' '),
                E'\n', ' '),
            '''', '''''')
        AS proxima_accion_esc,

        -- Fechas como texto para incluir en VALUES
        COALESCE(TO_CHAR(raw.fecha_cita_lead,    'YYYY-MM-DD HH24:MI:SS'), '') AS fecha_cita_str,
        replace(COALESCE(raw.tipo_cita_lead, ''), '''', '''''')                AS tipo_cita_esc,
        COALESCE(TO_CHAR(raw.fecha_contacto_lead,'YYYY-MM-DD HH24:MI:SS'), '') AS fecha_contacto_str

    FROM (
        SELECT 'asesor7'  AS asesor_schema, codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor7.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor2',  codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor2.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor6',  codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor6.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor4',  codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor4.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor9',  codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor9.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor13', codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor13.md_contactolead WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor10', codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor10.md_contactolead WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor5',  codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor5.md_contactolead  WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor11', codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor11.md_contactolead WHERE codigo_lead IS NOT NULL
        UNION ALL
        SELECT 'asesor12', codigo_lead, tipo_contacto_lead, estado_contacto_lead, observaciones, seguimiento_lead, fecha_cita_lead, tipo_cita_lead, fecha_contacto_lead FROM asesor12.md_contactolead WHERE codigo_lead IS NOT NULL
    ) raw
) c;

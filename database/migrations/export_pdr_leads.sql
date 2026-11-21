-- =============================================================================
-- EXPORT: Leads consolidados desde pdr_marketing
-- Ejecutar en: pdr_marketing (pdr-pgadmin.fs0dkz.easypanel.host)
-- Resultado:   Descargar como CSV → guardar como "leads_pdr.csv"
--
-- Cómo descargar en pgAdmin:
--   1. Ejecuta esta query
--   2. En Data Output → clic en el ícono de descarga (flecha hacia abajo)
--   3. Selecciona "CSV" → guardar como leads_pdr.csv
-- =============================================================================

SELECT
    la.id                                                    AS src_id,
    la.lead_id                                               AS fuente_externa_id,

    -- Normalizar plataforma a los valores del CRM
    CASE
        -- Valores exactos de Palma Río (deben existir en crm.fuentes)
        WHEN LOWER(TRIM(la.plataforma)) = 'wa mensaje'  THEN 'wa mensaje'
        WHEN LOWER(TRIM(la.plataforma)) = 'fb mensaje'  THEN 'fb mensaje'
        WHEN LOWER(TRIM(la.plataforma)) = 'ig mensaje'  THEN 'ig mensaje'
        WHEN LOWER(TRIM(la.plataforma)) = 'tt mensaje'  THEN 'tt mensaje'
        WHEN LOWER(TRIM(la.plataforma)) = 'fb'          THEN 'fb'
        WHEN LOWER(TRIM(la.plataforma)) = 'ig'          THEN 'ig'
        WHEN LOWER(TRIM(la.plataforma)) = 'referido'    THEN 'referido'
        -- Valores genéricos
        WHEN LOWER(la.plataforma) LIKE '%whatsapp%'     THEN 'whatsapp'
        WHEN LOWER(la.plataforma) LIKE '%facebook%'     THEN 'facebook'
        WHEN LOWER(la.plataforma) LIKE '%instagram%'    THEN 'instagram'
        WHEN LOWER(la.plataforma) LIKE '%tiktok%'       THEN 'tiktok'
        WHEN LOWER(la.plataforma) LIKE '%excel%'        THEN 'excel'
        WHEN LOWER(la.plataforma) LIKE '%web%'          THEN 'web'
        ELSE 'manual'
    END                                                      AS plataforma,

    la.proyecto_campania                                     AS campana,
    la.fecha_ingreso_lead                                    AS created_at,

    -- Separar nombre completo en nombres y apellidos
    TRIM(SPLIT_PART(TRIM(COALESCE(la.nombre_lead, '')), ' ', 1))  AS nombres,
    CASE
        WHEN POSITION(' ' IN TRIM(COALESCE(la.nombre_lead, ''))) > 0
        THEN TRIM(SUBSTRING(TRIM(la.nombre_lead)
                  FROM POSITION(' ' IN TRIM(la.nombre_lead)) + 1))
        ELSE NULL
    END                                                      AS apellidos,

    la.celular_lead                                          AS telefono,
    la.correo_lead                                           AS email,
    la.city_lead                                             AS ciudad,
    la.job_lead                                              AS trabajo,

    -- Normalizar estado al catálogo del CRM
    CASE
        WHEN LOWER(COALESCE(la.estado_lead, '')) IN ('nuevo', 'new')            THEN 'Nuevo'
        WHEN LOWER(COALESCE(la.estado_lead, '')) IN ('contactado', 'contacted') THEN 'Contactado'
        WHEN LOWER(COALESCE(la.estado_lead, '')) IN ('calificado', 'qualified') THEN 'Calificado'
        WHEN LOWER(COALESCE(la.estado_lead, '')) LIKE '%negoci%'                THEN 'En negociación'
        WHEN LOWER(COALESCE(la.estado_lead, '')) IN ('ganado', 'won', 'cerrado', 'matriculado') THEN 'Ganado'
        WHEN LOWER(COALESCE(la.estado_lead, '')) IN ('perdido', 'lost')         THEN 'Perdido'
        WHEN LOWER(COALESCE(la.estado_lead, '')) LIKE '%no interes%'            THEN 'No interesado'
        ELSE 'Nuevo'
    END                                                      AS estado_crm,

    -- Guardar el estado original por si hay que revisarlo
    la.estado_lead                                           AS estado_original,

    CASE
        WHEN UPPER(COALESCE(la.es_recontacto_lead, '')) IN ('SI', 'SÍ', 'TRUE', '1', 'YES', 'S')
        THEN true
        ELSE false
    END                                                      AS es_recontacto,

    la.observaciones,
    COALESCE(la.intentos_contacto_lead, 0)                   AS intentos_contacto,

    -- Info del asesor asignado
    la.me_asesor_id,
    a.nbrasesor                                              AS asesor_nombre,
    a.asesor_id                                              AS asesor_schema,
    a.numcelularasesor                                       AS asesor_telefono

FROM public.md_leadasignacion la
LEFT JOIN public.me_asesor a ON a.id = la.me_asesor_id
ORDER BY la.id;

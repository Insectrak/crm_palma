-- =============================================================================
-- VERIFICACIÓN COMPLETA DE MIGRACIÓN PDR → CRM
-- Ejecutar en: brighton_crm
-- Fecha:  2026-04-05
--
-- Corre este script en cualquier momento para verificar el estado
-- de la migración. No modifica ningún dato.
-- =============================================================================

-- ─── 1. RESUMEN GENERAL ─────────────────────────────────────────────────────
SELECT
    (SELECT COUNT(*) FROM crm.leads     WHERE activo = TRUE)  AS total_leads,
    (SELECT COUNT(*) FROM crm.contactos)                       AS total_contactos,
    (SELECT COUNT(*) FROM crm.contactos WHERE origen = 'pdr_migration') AS contactos_migrados,
    (SELECT COUNT(*) FROM crm.contactos WHERE origen = 'crm')           AS contactos_crm,
    (SELECT COUNT(*) FROM crm.fuentes   WHERE activo = TRUE)  AS total_fuentes;

-- ─── 2. LEADS POR ESTADO ────────────────────────────────────────────────────
SELECT
    e.nombre                                   AS estado,
    COUNT(l.id)                                AS total,
    ROUND(COUNT(l.id) * 100.0 /
        SUM(COUNT(l.id)) OVER (), 1)           AS pct
FROM crm.leads l
LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
WHERE l.activo = TRUE
GROUP BY e.nombre
ORDER BY total DESC;

-- ─── 3. LEADS POR FUENTE ────────────────────────────────────────────────────
SELECT
    COALESCE(f.nombre, '-- sin fuente --')     AS fuente,
    COUNT(l.id)                                AS total,
    ROUND(COUNT(l.id) * 100.0 /
        SUM(COUNT(l.id)) OVER (), 1)           AS pct
FROM crm.leads l
LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
WHERE l.activo = TRUE
GROUP BY f.nombre
ORDER BY total DESC;

-- ─── 4. LEADS SIN FUENTE (fuente_id NULL) ───────────────────────────────────
SELECT COUNT(*) AS leads_sin_fuente
FROM crm.leads
WHERE fuente_id IS NULL AND activo = TRUE;

-- ─── 5. CONTACTOS POR TIPO ──────────────────────────────────────────────────
SELECT
    tipo_contacto,
    COUNT(*)                                   AS total
FROM crm.contactos
GROUP BY tipo_contacto
ORDER BY total DESC;

-- ─── 6. CONTACTOS POR RESULTADO ─────────────────────────────────────────────
SELECT
    COALESCE(resultado, '-- sin resultado --') AS resultado,
    COUNT(*)                                   AS total
FROM crm.contactos
GROUP BY resultado
ORDER BY total DESC;

-- ─── 7. LEADS CON HISTORIAL DE CONTACTOS ────────────────────────────────────
SELECT
    COUNT(DISTINCT lead_id)                    AS leads_con_historial,
    (SELECT COUNT(*) FROM crm.leads WHERE activo = TRUE) AS total_leads,
    ROUND(
        COUNT(DISTINCT lead_id) * 100.0 /
        (SELECT COUNT(*) FROM crm.leads WHERE activo = TRUE),
    1)                                         AS pct_con_historial
FROM crm.contactos;

-- ─── 8. TOP 10 LEADS CON MÁS CONTACTOS ──────────────────────────────────────
SELECT
    l.nombres || ' ' || COALESCE(l.apellidos, '') AS lead,
    l.telefono,
    COUNT(c.id)                                AS num_contactos,
    MAX(c.created_at)::date                    AS ultimo_contacto
FROM crm.contactos c
JOIN crm.leads l ON l.id = c.lead_id
GROUP BY l.id, l.nombres, l.apellidos, l.telefono
ORDER BY num_contactos DESC
LIMIT 10;

-- ─── 9. ASESORES CON LEADS ASIGNADOS ────────────────────────────────────────
SELECT
    COALESCE(u.first_name || ' ' || u.last_name, '-- sin asesor --') AS asesor,
    COUNT(l.id)                                AS leads_asignados
FROM crm.leads l
LEFT JOIN auth.users u ON u.id = l.asesor_id
WHERE l.activo = TRUE
GROUP BY u.first_name, u.last_name
ORDER BY leads_asignados DESC;

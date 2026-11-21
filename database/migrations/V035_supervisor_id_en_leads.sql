-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V035 — Separación supervisor_id / asesor_id en crm.leads              ║
-- ║                                                                        ║
-- ║ PROBLEMA:                                                              ║
-- ║ Cuando un lead llega por Facebook / WhatsApp / formulario público se  ║
-- ║ asignaba automáticamente al supervisor (Paola o Darwin) usando        ║
-- ║ `asesor_id = <supervisor_uuid>`. El lead quedaba fuera de la cola de  ║
-- ║ asignación ("sin asesor") porque ya tenía `asesor_id` poblado, y los  ║
-- ║ asesores no lo veían hasta que el supervisor reasignaba manualmente.  ║
-- ║                                                                        ║
-- ║ SOLUCIÓN:                                                              ║
-- ║   1. Nueva columna `supervisor_id` (dueño funcional del lead).        ║
-- ║   2. `asesor_id` queda exclusivo para asesores reales (NULL = en cola)║
-- ║   3. `fecha_entrada_cola` marca cuándo el lead entró a cola para que  ║
-- ║      el panel de asignación pueda resaltar leads "estancados".        ║
-- ║                                                                        ║
-- ║ BACKFILL:                                                              ║
-- ║   - Leads con asesor_id = supervisor → supervisor_id=<sup>, asesor=∅. ║
-- ║     fecha_entrada_cola = COALESCE(updated_at, created_at).            ║
-- ║   - Leads con asesor_id = asesor real → supervisor_id se resuelve    ║
-- ║     vía crm.equipos (supervisor del equipo del asesor).               ║
-- ║                                                                        ║
-- ║ VIEW:                                                                  ║
-- ║   vw_leads_dashboard ahora usa l.supervisor_id como fuente primaria   ║
-- ║   y cae a crm.equipos solo como fallback histórico.                   ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- ── 1. Columnas nuevas ──────────────────────────────────────────────────────

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS supervisor_id UUID
        REFERENCES auth.users(id)
        ON DELETE SET NULL;

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS fecha_entrada_cola TIMESTAMPTZ;

COMMENT ON COLUMN crm.leads.supervisor_id IS
    'FK a auth.users (role=supervisor). Dueño funcional del lead mientras '
    'no haya asesor asignado. Permite diferenciar "lead del supervisor X en '
    'cola de asignación" de "lead asignado al asesor Y".';

COMMENT ON COLUMN crm.leads.fecha_entrada_cola IS
    'Momento en que el lead entró a la cola de asignación del supervisor '
    '(asesor_id NULL). Se resetea cuando se asigna un asesor real. Sirve '
    'al panel de Asignación para marcar leads estancados.';

-- ── 2. Índices ──────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_leads_supervisor_id
    ON crm.leads (supervisor_id)
    WHERE activo = TRUE;

-- Cola estancada: leads sin asesor ordenados por tiempo en cola
CREATE INDEX IF NOT EXISTS idx_leads_cola_estancada
    ON crm.leads (fecha_entrada_cola)
    WHERE activo = TRUE AND asesor_id IS NULL;

-- ── 3. Backfill (a): leads asignados a un supervisor ────────────────────────
-- Mueve el UUID del supervisor a la nueva columna y libera asesor_id para
-- que entren a la cola. Usa updated_at como proxy de "cuándo entraron".

UPDATE crm.leads l
SET supervisor_id      = l.asesor_id,
    asesor_id          = NULL,
    fecha_entrada_cola = COALESCE(l.updated_at, l.created_at)
FROM auth.users u
WHERE u.id = l.asesor_id
  AND u.role = 'supervisor'
  AND l.supervisor_id IS NULL;

-- ── 4. Backfill (b): leads asignados a un asesor real ──────────────────────
-- Resuelve el supervisor_id desde crm.equipos. Si un asesor pertenece a
-- varios equipos (no debería, pero el schema lo permite) toma el activo.

UPDATE crm.leads l
SET supervisor_id = eq.supervisor_id
FROM crm.equipos eq
WHERE eq.asesor_id = l.asesor_id
  AND eq.activo = TRUE
  AND l.supervisor_id IS NULL
  AND l.asesor_id IS NOT NULL;

-- ── 5. vw_leads_dashboard: usar supervisor_id de la columna, con fallback ──
-- La view V027 resolvía supervisor_id sólo vía crm.equipos, lo que dejaba
-- NULL los leads en cola (sin asesor_id). Ahora la fuente primaria es la
-- nueva columna y crm.equipos queda como fallback para datos históricos.

CREATE OR REPLACE VIEW crm.vw_leads_dashboard AS
WITH ultimo_contacto AS (
    SELECT DISTINCT ON (lead_id)
        lead_id,
        id                   AS contacto_id,
        tipo_contacto        AS ultimo_tipo_contacto,
        resultado            AS ultimo_resultado,
        notas                AS ultimas_notas,
        fecha_proxima_accion,
        fecha_cita           AS proxima_cita,
        created_at           AS fecha_ultimo_contacto
    FROM crm.contactos
    ORDER BY lead_id, created_at DESC
),
contactos_count AS (
    SELECT lead_id, COUNT(*)::int AS total
    FROM crm.contactos
    GROUP BY lead_id
),
primer_contacto AS (
    SELECT lead_id, MIN(created_at) AS fecha_primer_contacto
    FROM crm.contactos
    GROUP BY lead_id
),
primera_asignacion AS (
    SELECT DISTINCT ON (lead_id)
        lead_id, created_at AS fecha_asignacion
    FROM crm.asignaciones_log
    ORDER BY lead_id, created_at ASC
)
SELECT
    l.id,
    l.nombres,
    l.apellidos,
    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
    l.telefono,
    l.email,
    l.ciudad,
    l.trabajo,
    l.es_recontacto,
    COALESCE(cc.total, 0)   AS intentos_contacto,
    l.observaciones,
    l.datos_extra,
    l.hash_dedup,
    l.activo,
    l.created_at            AS fecha_ingreso,
    l.updated_at,

    l.estado_id,
    e.nombre                AS estado_nombre,
    e.color_hex             AS estado_color,
    e.es_final              AS estado_es_final,

    l.fuente_id,
    f.nombre                AS fuente_nombre,
    l.fuente_externa_id,
    l.campana,

    l.asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                 AS asesor_email,

    -- V035: supervisor_id de la columna directa, con fallback a equipos
    COALESCE(l.supervisor_id, eq.supervisor_id)                       AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,

    uc.contacto_id,
    uc.ultimo_tipo_contacto,
    uc.ultimo_resultado,
    uc.ultimas_notas,
    uc.fecha_ultimo_contacto,
    uc.fecha_proxima_accion,
    uc.proxima_cita,

    CASE
        WHEN uc.fecha_ultimo_contacto IS NULL THEN TRUE
        WHEN uc.fecha_ultimo_contacto < NOW() - INTERVAL '24 hours' THEN TRUE
        ELSE FALSE
    END                     AS sin_contacto_reciente,

    EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 3600 AS horas_desde_ingreso,

    pa.fecha_asignacion,
    pc.fecha_primer_contacto,

    -- V027
    l.proyecto,
    l.estrategia,
    l.calidad,

    -- V035: señal de cola
    l.fecha_entrada_cola,
    CASE
        WHEN l.asesor_id IS NULL
         AND l.fecha_entrada_cola IS NOT NULL
         AND l.fecha_entrada_cola < NOW() - INTERVAL '24 hours'
        THEN TRUE
        ELSE FALSE
    END                     AS cola_estancada

FROM crm.leads l
LEFT JOIN crm.estados_lead   e  ON e.id  = l.estado_id
LEFT JOIN crm.fuentes        f  ON f.id  = l.fuente_id
LEFT JOIN auth.users         a  ON a.id  = l.asesor_id
LEFT JOIN crm.equipos        eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
LEFT JOIN auth.users         s  ON s.id  = COALESCE(l.supervisor_id, eq.supervisor_id)
LEFT JOIN ultimo_contacto    uc ON uc.lead_id = l.id
LEFT JOIN contactos_count    cc ON cc.lead_id = l.id
LEFT JOIN primer_contacto    pc ON pc.lead_id = l.id
LEFT JOIN primera_asignacion pa ON pa.lead_id = l.id
WHERE l.activo = TRUE;

-- ── 6. vw_kpis_por_supervisor: incluir leads en cola del supervisor ────────
-- Antes sólo contaba leads con asesor_id dentro del equipo. Ahora también
-- sumamos los leads en cola (supervisor_id = s.id, asesor_id NULL) para que
-- el supervisor vea su backlog real.

CREATE OR REPLACE VIEW crm.vw_kpis_por_supervisor AS
WITH leads_del_supervisor AS (
    -- Asignados a algún asesor del equipo
    SELECT l.id, l.estado_id, l.created_at, l.activo, eq.supervisor_id
    FROM crm.leads l
    JOIN crm.equipos eq
      ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
    WHERE l.activo = TRUE
    UNION
    -- En cola del supervisor (sin asesor)
    SELECT l.id, l.estado_id, l.created_at, l.activo, l.supervisor_id
    FROM crm.leads l
    WHERE l.activo = TRUE
      AND l.asesor_id IS NULL
      AND l.supervisor_id IS NOT NULL
)
SELECT
    s.id                    AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
    s.email                 AS supervisor_email,
    COUNT(DISTINCT eq.asesor_id)    AS total_asesores,
    COUNT(lds.id)           AS total_leads,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'En negociación') AS leads_en_negociacion,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Ganado')         AS leads_ganado,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,
    CASE
        WHEN COUNT(lds.id) = 0 THEN 0
        ELSE ROUND(
            100.0 * COUNT(lds.id) FILTER (WHERE e.nombre = 'Ganado') / COUNT(lds.id),
            2
        )
    END                     AS tasa_conversion_pct,
    COUNT(lds.id) FILTER (
        WHERE lds.created_at >= CURRENT_DATE::TIMESTAMPTZ
    )                       AS leads_hoy,
    COUNT(lds.id) FILTER (
        WHERE lds.created_at >= NOW() - INTERVAL '7 days'
    )                       AS leads_ultimos_7dias,
    COUNT(lds.id) FILTER (
        WHERE lds.created_at >= NOW() - INTERVAL '30 days'
    )                       AS leads_ultimos_30dias,
    -- V035: backlog del supervisor (en cola sin asesor). Al final para que
    -- CREATE OR REPLACE VIEW no rompa por reordenamiento de columnas.
    COUNT(lds.id) FILTER (
        WHERE lds.id IN (
            SELECT id FROM crm.leads
            WHERE supervisor_id = s.id AND asesor_id IS NULL AND activo = TRUE
        )
    )                       AS leads_en_cola
FROM auth.users s
LEFT JOIN crm.equipos eq
    ON eq.supervisor_id = s.id AND eq.activo = TRUE
LEFT JOIN leads_del_supervisor lds
    ON lds.supervisor_id = s.id
LEFT JOIN crm.estados_lead e
    ON e.id = lds.estado_id
WHERE s.role = 'supervisor'
  AND s.is_active = TRUE
GROUP BY s.id, s.first_name, s.last_name, s.email;

COMMIT;

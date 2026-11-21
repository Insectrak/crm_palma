-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V086 — Backfill api_client_id en recontactos de los 4 leads que       ║
-- ║        wedo confirmó haber re-trabajado en Palma producción           ║
-- ║                                                                        ║
-- ║ Reportado por admin de Palma producción 2026-06-17: la Sharing Rule   ║
-- ║ "Proveedor = wedo + Incluir recontactos del proveedor" no mostraba    ║
-- ║ leads cuyos recontactos provenían de wedo (THELXE, Wilfredo Marroquin,║
-- ║ chiky pb, Edo Ramos — todos con badge ↻1).                            ║
-- ║                                                                        ║
-- ║ Causa raíz (deuda histórica): antes del fix V085 (commit 63189b2 del  ║
-- ║ 2026-06-16), había un bug en lead_recapture.handle_recontacto que     ║
-- ║ guardaba TODOS los recontactos con api_client_id=NULL porque          ║
-- ║ IngestPayload no tenía el campo declarado.                            ║
-- ║                                                                        ║
-- ║ Decisión conservadora 2026-06-18: wedo confirmó al admin de Palma que ║
-- ║ SOLO trabajó esos 4 leads específicos. NO atribuimos a wedo todos los ║
-- ║ recontactos con api_client_id NULL en general — solo los de los       ║
-- ║ teléfonos confirmados. Los otros recontactos NULL quedan como están   ║
-- ║ (sin atribución) para no falsear los reportes con datos no verificados║
-- ║                                                                        ║
-- ║ Idempotente: filtra por api_client_id IS NULL, después de aplicada    ║
-- ║ no hay match. Multi-tenant safe: si "wedo" no existe en este tenant   ║
-- ║ (ej. lab brighton tiene "wedo3"), termina como no-op.                ║
-- ║                                                                        ║
-- ║ Reversible vía la cláusula `razon` que anota el marcador del backfill.║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

DO $$
DECLARE
    wedo_id UUID;
    rows_updated INTEGER;
BEGIN
    -- Buscar el id del proveedor "wedo" en este tenant (case-insensitive).
    SELECT id INTO wedo_id
    FROM crm.api_clients
    WHERE LOWER(nombre) = 'wedo'
       OR LOWER(slug) = 'wedo'
    LIMIT 1;

    IF wedo_id IS NULL THEN
        RAISE NOTICE '[V086] Proveedor "wedo" no existe en este tenant — backfill skipped (no-op).';
        RETURN;
    END IF;

    -- UPDATE selectivo: solo los recontactos asociados a los 4 leads
    -- por teléfono que wedo explícitamente confirmó haber re-trabajado.
    -- Si en el futuro wedo confirma más, se agregan via migración nueva
    -- (V087, V088, etc.).
    UPDATE crm.lead_recontactos r
    SET api_client_id = wedo_id,
        razon = COALESCE(r.razon, '') ||
                CASE WHEN r.razon IS NULL OR r.razon = '' THEN '' ELSE ' · ' END ||
                '[V086 backfill 2026-06-18: atribución a wedo confirmada por el proveedor]'
    FROM crm.leads l
    WHERE r.lead_id = l.id
      AND r.api_client_id IS NULL
      AND l.telefono IN (
          '+51955417575',  -- THELXE
          '+51958430457',  -- Wilfredo Marroquin Quispe
          '+51976020932',  -- chiky pb
          '+51950508382'   -- Edo Ramos
      );

    GET DIAGNOSTICS rows_updated = ROW_COUNT;

    RAISE NOTICE '[V086] Backfill aplicado: % filas atualizadas a wedo (id=%) para los 4 leads confirmados.',
                 rows_updated, wedo_id;
END
$$;

COMMIT;

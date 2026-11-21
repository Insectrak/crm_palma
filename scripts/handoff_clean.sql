-- ============================================================
-- handoff_clean.sql — Limpieza pre-entrega del CRM a un cliente
-- ============================================================
--
-- Que es esto:
-- Antes de entregarle el CRM a un cliente real (Palma del Rio,
-- Doctor Muelita, futuro), se ejecuta este script para eliminar
-- TODO rastro de testing/QA que el implementador (brighton) haya
-- dejado durante la instalacion y validacion.
--
-- Cuando ejecutarlo:
--   1. Antes de pasar las credenciales al cliente.
--   2. NUNCA en produccion ya entregada — borra data real.
--
-- Como ejecutarlo (pgAdmin):
--   1. Conectarse a la DB del tenant (ej. brighton_crm).
--   2. Abrir Query Tool.
--   3. Pegar este archivo completo.
--   4. F5 (Ejecutar).
--   5. Revisar el snapshot en Data Output — debe mostrar 0 en
--      todos los counts criticos.
--
-- Garantias:
--   - Idempotente: re-ejecutarlo no rompe nada. Cada operacion
--     usa to_regclass() para verificar que la tabla existe
--     ANTES de truncar/borrar. Si la tabla no existe, se saltea
--     silenciosamente (RAISE NOTICE) — el script sigue.
--   - Transaccional: todo en UN bloque DO. Si algo grave falla,
--     se propaga la excepcion y rollback completo.
--   - Tolerante a esquemas distintos: funciona en cualquier
--     tenant sin importar si tiene todas las migraciones V040+
--     aplicadas o no. Lo que existe se limpia, lo que no, se
--     ignora con un mensaje informativo.
--   - NO toca el schema base, las migraciones, ni los catalogos
--     genericos (estados, fuentes default) — solo data de uso
--     del CRM (vistas custom, leads, sesiones, etc.).
--   - NO toca crm.schema_migrations (el tracker debe persistir).
-- ============================================================

BEGIN;

DO $handoff$
DECLARE
    -- Lista ordenada de tablas a TRUNCATE. El orden importa por
    -- las FKs (las tablas dependientes van primero). Cada item
    -- es {schema.tabla, comentario_para_logs}.
    truncate_targets TEXT[][] := ARRAY[
        -- Vistas custom de usuarios (las 'h', 'd', 'test' de QA)
        ['crm.user_views',                  '1. vistas guardadas del implementador'],
        -- Notificaciones encoladas / push de prueba
        ['crm.notification_buffer',         '2.a notificaciones encoladas'],
        ['auth.user_fcm_tokens',            '2.b tokens FCM de telefonos QA'],
        -- Sesiones activas: cerrar todas las del implementador
        ['auth.user_sessions',              '3. sesiones JWT activas'],
        -- Audit logs del periodo de QA
        ['crm.audit_lead_access',           '4. audit logs de QA'],
        -- Datos transaccionales de prueba (orden importa por FKs)
        ['crm.lead_recontactos',            '5.a recontactos de prueba'],
        ['crm.lead_interacciones_meta',     '5.b interacciones Meta de prueba'],
        ['crm.lead_tags',                   '5.c tags por lead de prueba'],
        ['crm.contactos',                   '5.d contactos de prueba'],
        ['crm.eventos_calendario',          '5.e eventos calendario QA'],
        ['crm.cargas_masivas',              '5.f historial cargas masivas QA'],
        ['crm.asignaciones_log',            '5.g log de asignaciones QA'],
        ['crm.leads_raw_facebook',          '5.h leads raw FB de QA'],
        ['crm.leads_raw_tiktok',            '5.i leads raw TT de QA'],
        ['crm.leads',                       '5.j leads de prueba'],
        -- WhatsApp testing
        ['crm.wa_conversation_tags',        '6.a tags WA de QA'],
        ['crm.wa_conversation_leads',       '6.b vinculos chat-lead QA'],
        ['crm.wa_messages',                 '6.c mensajes WA de QA'],
        ['crm.wa_media_cache',              '6.d media WA cacheada'],
        ['crm.wa_archived_audit',           '6.e audit WA archivados'],
        ['crm.wa_campaigns',                '6.f campanas WA de prueba'],
        ['crm.wa_conversations',            '6.g conversaciones WA QA'],
        ['crm.meta_catalog_cache',          '6.h cache catalogo Meta'],
        -- Webhooks salientes de prueba
        ['crm.webhook_deliveries',          '7. webhooks salientes QA'],
        -- Integraciones (credenciales del implementador)
        ['crm.integrations_events',         '8.a eventos integraciones QA'],
        ['crm.integrations_credentials',    '8.b credenciales Meta/TikTok QA'],
        -- Historico legacy: data de prueba si se hizo un import test
        ['crm_legacy.leads_historico',      '9. historico legacy (Fase 2)'],
        -- Auth: intentos y resets del periodo QA
        ['auth.login_attempts',             '10.a login attempts QA'],
        ['auth.password_resets',            '10.b password resets QA'],
        -- Formularios publicos
        ['crm.public_form_submissions',     '11.a submissions de QA']
    ];

    -- DELETE con WHERE (no TRUNCATE) para preservar data que pueda
    -- ser valida. Por ejemplo, las tags antiguas las dejamos (V026
    -- pudo sembrar defaults), solo borramos las creadas durante QA.
    target_record TEXT[];
    table_qualified TEXT;
    label TEXT;
    skipped_count INTEGER := 0;
    cleaned_count INTEGER := 0;
BEGIN
    RAISE NOTICE '╔══════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║       HANDOFF CLEAN — eliminando rastros de QA           ║';
    RAISE NOTICE '╚══════════════════════════════════════════════════════════╝';

    -- ── Loop principal: TRUNCATE solo si la tabla existe ────────
    FOREACH target_record SLICE 1 IN ARRAY truncate_targets LOOP
        table_qualified := target_record[1];
        label           := target_record[2];

        IF to_regclass(table_qualified) IS NOT NULL THEN
            EXECUTE format('TRUNCATE %s CASCADE', table_qualified);
            RAISE NOTICE '  [OK]   %  (%)', label, table_qualified;
            cleaned_count := cleaned_count + 1;
        ELSE
            RAISE NOTICE '  [skip] %  (% no existe)', label, table_qualified;
            skipped_count := skipped_count + 1;
        END IF;
    END LOOP;

    -- ── DELETEs selectivos (con WHERE) ─────────────────────────
    -- Tags creadas recientemente (probablemente del implementador)
    IF to_regclass('crm.tags') IS NOT NULL THEN
        DELETE FROM crm.tags WHERE created_at > NOW() - INTERVAL '30 days';
        RAISE NOTICE '  [OK]   12. tags recientes (created_at > 30 dias) (crm.tags)';
        cleaned_count := cleaned_count + 1;
    END IF;

    -- Formularios publicos recientes (probablemente del implementador)
    IF to_regclass('crm.public_forms') IS NOT NULL THEN
        DELETE FROM crm.public_forms WHERE created_at > NOW() - INTERVAL '30 days';
        RAISE NOTICE '  [OK]   13. formularios publicos recientes (crm.public_forms)';
        cleaned_count := cleaned_count + 1;
    END IF;

    -- ── Resumen ────────────────────────────────────────────────
    RAISE NOTICE '';
    RAISE NOTICE '╔══════════════════════════════════════════════════════════╗';
    RAISE NOTICE '║  HANDOFF CLEAN: % tablas limpiadas, % skip (no existian)  ║', cleaned_count, skipped_count;
    RAISE NOTICE '╚══════════════════════════════════════════════════════════╝';
END $handoff$;

-- ── Snapshot final para validar el handoff ─────────────────────
-- Esta query se muestra en Data Output de pgAdmin.
-- COALESCE para tolerar tablas que no existan en este tenant.
SELECT
    COALESCE((SELECT COUNT(*)::TEXT FROM crm.leads),              'n/a') AS leads,
    COALESCE((SELECT COUNT(*)::TEXT FROM crm.contactos),          'n/a') AS contactos,
    COALESCE((SELECT COUNT(*)::TEXT FROM crm.user_views),         'n/a') AS vistas_custom,
    COALESCE((SELECT COUNT(*)::TEXT FROM crm.wa_messages),        'n/a') AS wa_mensajes,
    COALESCE((SELECT COUNT(*)::TEXT FROM auth.user_sessions),     'n/a') AS sesiones,
    COALESCE((SELECT COUNT(*)::TEXT FROM auth.users),             'n/a') AS usuarios,
    COALESCE((SELECT COUNT(*)::TEXT FROM crm.schema_migrations),  'n/a') AS migraciones_aplicadas;

COMMIT;

-- ============================================================
-- HANDOFF CLEAN COMPLETO
--
-- Despues de este script, las siguientes cosas DEBEN ser
-- verdaderas en una entrega limpia:
--   - leads               = 0
--   - contactos           = 0
--   - vistas_custom       = 0
--   - wa_mensajes         = 0
--   - sesiones            = 0 (todos deben re-loguearse)
--   - usuarios            = 1 (solo el admin del implementador,
--                              que el cliente despues rotara)
--   - migraciones_aplicadas >= 70 (no se toca)
--
-- Si alguna tabla aparece como 'skip' en los NOTICE, NO es error:
-- significa que esa V0XX no se aplico en este tenant (ej. un
-- install muy temprano sin las migraciones de WhatsApp). El
-- handoff se completo igual sobre lo que SI existe.
--
-- Pasos siguientes a este script:
--   1. Rotar password del admin actual O crear admin del
--      cliente y eliminar el del implementador (ver
--      docs/HANDOFF_CHECKLIST.md Paso 3-4).
--   2. Configurar branding del cliente desde UI.
--   3. Smoke test: GET /api/health, /api/setup/status
--   4. Entregar URL + credenciales al cliente.
-- ============================================================

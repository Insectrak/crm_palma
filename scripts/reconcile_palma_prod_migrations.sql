-- ============================================================================
-- reconcile_palma_prod_migrations.sql
-- Prepara una BD existente de Palma CRM (rama V097..V149) para ejecutar
-- limpiamente las migraciones V095..V128 de la nueva base unificada.
--
-- Idempotente y no destructivo con datos de negocio (leads, usuarios,
-- contactos, configuraciones, etc.). Solo archiva y limpia los registros
-- divergentes en crm.schema_migrations identificándolos por filename exacto.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS crm.schema_migrations_palma_legacy (
    version    TEXT PRIMARY KEY,
    filename   TEXT        NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL
);

INSERT INTO crm.schema_migrations_palma_legacy (version, filename, applied_at)
SELECT version, filename, applied_at
FROM crm.schema_migrations
WHERE filename IN (
    'V097_lead_valor_venta.sql',
    'V098_public_forms_auto_distribuir.sql',
    'V099_wa_bot_knowledge_base.sql',
    'V100_kb_hybrid_search.sql',
    'V101_wa_bot_flows.sql',
    'V102_wa_bot_supervisor_auto_assign.sql',
    'V103_wa_bot_handoff_triggers.sql',
    'V104_wa_bot_takeover.sql',
    'V105_wa_bot_trigger_sets.sql',
    'V106_wa_media_processed.sql',
    'V107_leads_carga_masiva_id.sql',
    'V107_2_backfill_carga_masiva_id.sql',
    'V108_estados_display_visibility.sql',
    'V109_cita_estados_es_sistema.sql',
    'V110_calidad_es_sistema.sql',
    'V111_wa_messages_soft_delete_edit.sql',
    'V140_leads_field_history.sql',
    'V143_tipos_contacto_color.sql',
    'V149_backfill_previous_asesor.sql'
)
ON CONFLICT (version) DO NOTHING;

DELETE FROM crm.schema_migrations
WHERE filename IN (
    'V097_lead_valor_venta.sql',
    'V098_public_forms_auto_distribuir.sql',
    'V099_wa_bot_knowledge_base.sql',
    'V100_kb_hybrid_search.sql',
    'V101_wa_bot_flows.sql',
    'V102_wa_bot_supervisor_auto_assign.sql',
    'V103_wa_bot_handoff_triggers.sql',
    'V104_wa_bot_takeover.sql',
    'V105_wa_bot_trigger_sets.sql',
    'V106_wa_media_processed.sql',
    'V107_leads_carga_masiva_id.sql',
    'V107_2_backfill_carga_masiva_id.sql',
    'V108_estados_display_visibility.sql',
    'V109_cita_estados_es_sistema.sql',
    'V110_calidad_es_sistema.sql',
    'V111_wa_messages_soft_delete_edit.sql',
    'V140_leads_field_history.sql',
    'V143_tipos_contacto_color.sql',
    'V149_backfill_previous_asesor.sql'
);

COMMIT;

-- ============================================================================
-- V118 — Índices de optimización para Reportería Especial
--
-- Caso de uso: Auditoría y reporte histórico de leads recibidos por supervisor,
-- permitiendo cruzar rápidamente leads que fueron reasignados o enviados a
-- la Bolsa de Reciclaje TMK con sus fuentes y estados originales.
-- ============================================================================

-- Asegurar columnas de trazabilidad pre-reciclaje antes de indexar (idempotente)
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS fuente_pre_reciclaje_id INTEGER REFERENCES crm.fuentes(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS estado_pre_reciclaje_id INTEGER REFERENCES crm.estados_lead(id) ON DELETE SET NULL;

-- Índice para búsquedas rápidas de leads por supervisor_id y estado activo
CREATE INDEX IF NOT EXISTS idx_leads_supervisor_historico
    ON crm.leads (supervisor_id, created_at DESC);

-- Índice para tracing de leads que pasaron por Bolsa TMK o reasignación
CREATE INDEX IF NOT EXISTS idx_leads_previous_asesor_id
    ON crm.leads (previous_asesor_id)
    WHERE previous_asesor_id IS NOT NULL;

-- Índice para trazabilidad de fuente original antes de reciclaje
CREATE INDEX IF NOT EXISTS idx_leads_fuente_pre_reciclaje_id
    ON crm.leads (fuente_pre_reciclaje_id)
    WHERE fuente_pre_reciclaje_id IS NOT NULL;

-- Índice compuesto en crm.asignaciones_log para resolver historial cruzado por lead
CREATE INDEX IF NOT EXISTS idx_asignaciones_log_lead_asesores
    ON crm.asignaciones_log (lead_id, asesor_anterior, asesor_nuevo);

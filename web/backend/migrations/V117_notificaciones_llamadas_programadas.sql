-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V117 — Notificaciones de llamadas y citas programadas con 1 hora de   ║
-- ║        anticipación                                                    ║
-- ║                                                                        ║
-- ║ Agrega rastreo de notificaciones de próxima gestión/llamada en leads  ║
-- ║ e índices para optimizar la búsqueda periódica de recordatorios.       ║
-- ╚════════════════════════════════════════════════════════════════════════╝

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS proxima_gestion_notificada_at timestamptz DEFAULT NULL;

-- Índice para acelerar la búsqueda de próximas gestiones pendientes de alertar
CREATE INDEX IF NOT EXISTS idx_leads_fecha_proxima_gestion_pending
    ON crm.leads (fecha_proxima_gestion)
    WHERE fecha_proxima_gestion IS NOT NULL AND proxima_gestion_notificada_at IS NULL AND activo = TRUE;

-- Índice para acelerar la búsqueda de citas programadas
CREATE INDEX IF NOT EXISTS idx_contactos_fecha_cita_pendiente
    ON crm.contactos (fecha_cita)
    WHERE fecha_cita IS NOT NULL;

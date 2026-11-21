-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V068.3 — Reactivation Window: limpia recontactos del mismo dia        ║
-- ║                                                                        ║
-- ║ Bug reportado en prod (2026-05-13): leads creados HOY a las 18:27     ║
-- ║ mostraban "↻ 1" recontacto. Eso no puede ser un re-engagement real:   ║
-- ║ el cliente literalmente acaba de entrar al CRM.                       ║
-- ║                                                                        ║
-- ║ Causa: el poll de TikTok corre cada N minutos y dentro de la misma    ║
-- ║ ventana puede entregar el MISMO telefono con fexts distintos (TikTok  ║
-- ║ a veces genera multiples lead_ids por touch). El primer touch crea el ║
-- ║ lead, el segundo touch del mismo dia se registra como "recontacto".    ║
-- ║                                                                        ║
-- ║ Patron Salesforce / HubSpot / Marketo: un re-engagement valido        ║
-- ║ requiere GAP MINIMO entre la creacion del lead y el nuevo touch:      ║
-- ║   Salesforce default: 30 dias                                          ║
-- ║   HubSpot:            cambio de attribution source                     ║
-- ║   Marketo:            X dias configurables                             ║
-- ║                                                                        ║
-- ║ Aplicamos la regla minima: NO recontacto si fue creado el mismo dia   ║
-- ║ comercial peruano que el lead. Mas conservador que Salesforce, pero   ║
-- ║ adecuado para un poll de alta frecuencia (cada minuto).               ║
-- ║                                                                        ║
-- ║ El bloqueo a futuro vive en services/integrations/ingest_core.py.     ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

-- DELETE retroactivo: borrar los recontactos creados el mismo dia comercial
-- Lima que la creacion del lead asociado.
DELETE FROM crm.lead_recontactos r
USING crm.leads l
WHERE r.lead_id = l.id
  AND DATE(r.created_at AT TIME ZONE 'America/Lima')
      = DATE(l.created_at AT TIME ZONE 'America/Lima');

-- Comentario en la tabla para que quede claro el contrato a futuro.
COMMENT ON TABLE crm.lead_recontactos IS
    'V068.3: Recontactos = re-engagement. Solo se inserta si el lead ya '
    'existia desde un dia anterior (Reactivation Window estilo Salesforce). '
    'Eventos del mismo dia que la creacion son re-submissions/noise — no '
    'cuentan como reactivacion. Bloqueo upstream en ingest_core.py.';

COMMIT;

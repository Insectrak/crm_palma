"""
call_reminder_service.py — Servicio de recordatorios para llamadas y citas programadas.

Monitorea compromisos agendados (citas en crm.contactos y próximas gestiones en crm.leads)
y despacha notificaciones automáticas (push FCM e inbox) con 1 hora de anticipación.

Diseño:
- Ejecutado cada 60s por el scheduler en el worker líder.
- Ventana de anticipación: NOW() < fecha <= NOW() + INTERVAL '65 minutes'.
  (65m cubre el ciclo de 60s del scheduler sin gaps ni desbordes).
- Deduplicación estricta:
  * crm.recordatorios_enviados para citas (tipo: 'push_llamada_1h' / 'push_cita_1h').
  * crm.leads.proxima_gestion_notificada_at para próximas gestiones.
- Despacho seguro: marcas en BD dentro de la transacción, envío push fuera
  del lock de BD para no retener conexiones.
- Al reprogramar fecha_cita o fecha_proxima_gestion, los endpoints limpian
  las marcas permitiendo que la nueva fecha vuelva a alertar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db
from app.services import notification_service

logger = logging.getLogger(__name__)

LIMA_TZ = timezone(timedelta(hours=-5))


def _format_hora_local(dt: Optional[datetime]) -> str:
    """Formatea la hora a formato HH:MM en zona horaria Lima."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(LIMA_TZ)
    return local_dt.strftime("%H:%M")


def check_scheduled_call_reminders() -> int:
    """Chequea citas y próximas gestiones agendadas dentro de la próxima hora.
    
    Retorna la cantidad total de alertas despachadas en este ciclo.
    """
    logger.debug("[CallReminders] Verificando llamadas y citas programadas en la próxima hora...")
    notifications_to_send: list[tuple[str, str, dict, dict]] = []
    # cada elemento: (event_type, recipient_user_id, context_dict, data_dict)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ─────────────────────────────────────────────────────────────────
            # 1. Citas programadas en crm.contactos (tipo_cita = 'llamada' u otro)
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    c.id AS contacto_id,
                    c.lead_id,
                    c.fecha_cita,
                    c.tipo_cita,
                    c.notas,
                    COALESCE(c.asesor_id, l.asesor_id) AS asesor_id,
                    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_lead,
                    l.telefono
                FROM crm.contactos c
                JOIN crm.leads l ON l.id = c.lead_id
                LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                WHERE l.activo = TRUE
                  AND c.fecha_cita IS NOT NULL
                  AND c.fecha_cita > NOW()
                  AND c.fecha_cita <= NOW() + INTERVAL '65 minutes'
                  AND (
                      c.cita_estado_id IS NULL
                      OR c.cita_estado_id = 1
                      OR ce.codigo = 'pendiente'
                      OR (COALESCE(ce.es_final, FALSE) = FALSE AND COALESCE(ce.codigo, '') != 'cancelada')
                  )
                  AND COALESCE(c.asesor_id, l.asesor_id) IS NOT NULL
                ORDER BY c.fecha_cita ASC
                LIMIT 100
                """
            )
            citas_proximas = cur.fetchall()

            for cita in citas_proximas:
                contacto_id = cita["contacto_id"]
                lead_id = cita["lead_id"]
                asesor_id = str(cita["asesor_id"])
                nombre_lead = cita["nombre_lead"] or f"Lead #{lead_id}"
                telefono = cita["telefono"] or ""
                tipo_cita = (cita["tipo_cita"] or "").strip().lower()

                es_llamada = "llamada" in tipo_cita or not tipo_cita
                recordatorio_tipo = "push_llamada_1h" if es_llamada else "push_cita_1h"
                event_type = "llamada_programada" if es_llamada else "cita_programada"

                # Verificar deduplicación en crm.recordatorios_enviados
                cur.execute(
                    """
                    SELECT 1 FROM crm.recordatorios_enviados
                    WHERE contacto_id = %s AND tipo = %s
                    """,
                    (contacto_id, recordatorio_tipo),
                )
                if cur.fetchone():
                    continue

                # Marcar como enviado de forma atómica
                cur.execute(
                    """
                    INSERT INTO crm.recordatorios_enviados (contacto_id, tipo, enviado_a, enviado_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (contacto_id, tipo) DO NOTHING
                    """,
                    (contacto_id, recordatorio_tipo, asesor_id),
                )

                hora_local = _format_hora_local(cita["fecha_cita"])
                detalle = cita["tipo_cita"] or ("Llamada telefónica" if es_llamada else "Cita programada")
                if cita.get("notas"):
                    detalle = f"{detalle} - {cita['notas'][:40]}"

                notifications_to_send.append((
                    event_type,
                    asesor_id,
                    {
                        "lead_name": nombre_lead,
                        "lead_id": lead_id,
                        "hora": hora_local,
                        "detalle": detalle,
                        "telefono": telefono,
                    },
                    {
                        "lead_id": str(lead_id),
                        "contacto_id": str(contacto_id),
                        "type": event_type,
                    },
                ))

            # ─────────────────────────────────────────────────────────────────
            # 2. Próximas gestiones programadas en crm.leads
            # ─────────────────────────────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    l.id AS lead_id,
                    l.fecha_proxima_gestion,
                    l.accion_proxima_gestion,
                    l.asesor_id,
                    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_lead,
                    l.telefono
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND l.asesor_id IS NOT NULL
                  AND l.fecha_proxima_gestion IS NOT NULL
                  AND l.proxima_gestion_notificada_at IS NULL
                  AND l.fecha_proxima_gestion > NOW()
                  AND l.fecha_proxima_gestion <= NOW() + INTERVAL '65 minutes'
                  AND COALESCE(e.es_final, FALSE) = FALSE
                  AND e.nombre NOT IN ('Perdido', 'No interesado', 'No procede', 'Descartado')
                  AND NOT (
                      e.nombre ILIKE '%%matr%%'
                      OR e.nombre ILIKE '%%ganad%%'
                      OR e.nombre ILIKE '%%cierr%%'
                      OR l.tipo_cierre IS NOT NULL
                  )
                  -- Evitar doble notificación si ya existe una cita en crm.contactos a la misma hora
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c
                      WHERE c.lead_id = l.id
                        AND c.fecha_cita IS NOT NULL
                        AND ABS(EXTRACT(EPOCH FROM (c.fecha_cita - l.fecha_proxima_gestion))) < 300
                  )
                ORDER BY l.fecha_proxima_gestion ASC
                LIMIT 100
                """
            )
            gestiones_proximas = cur.fetchall()

            for gestion in gestiones_proximas:
                lead_id = gestion["lead_id"]
                asesor_id = str(gestion["asesor_id"])
                nombre_lead = gestion["nombre_lead"] or f"Lead #{lead_id}"
                telefono = gestion["telefono"] or ""
                accion = (gestion["accion_proxima_gestion"] or "").strip()

                es_cita = any(k in accion.lower() for k in ("cita", "reunión", "reunion", "zoom", "meet"))
                event_type = "cita_programada" if es_cita else "llamada_programada"

                # Marcar lead como notificado
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET proxima_gestion_notificada_at = NOW()
                    WHERE id = %s AND proxima_gestion_notificada_at IS NULL
                    """,
                    (lead_id,),
                )
                if cur.rowcount == 0:
                    # Otra tarea lo actualizó en simultáneo
                    continue

                hora_local = _format_hora_local(gestion["fecha_proxima_gestion"])
                detalle = accion or "Llamada de seguimiento"

                notifications_to_send.append((
                    event_type,
                    asesor_id,
                    {
                        "lead_name": nombre_lead,
                        "lead_id": lead_id,
                        "hora": hora_local,
                        "detalle": detalle,
                        "telefono": telefono,
                    },
                    {
                        "lead_id": str(lead_id),
                        "type": event_type,
                    },
                ))

            conn.commit()

    # ─────────────────────────────────────────────────────────────────
    # 3. Despacho de notificaciones fuera de la conexión de BD
    # ─────────────────────────────────────────────────────────────────
    dispatched_count = 0
    for event_type, recipient, ctx, data in notifications_to_send:
        try:
            ok = notification_service.notify(
                event_type=event_type,
                recipient_user_id=recipient,
                context=ctx,
                data=data,
            )
            if ok:
                dispatched_count += 1
            logger.info(
                "[CallReminders] Push '%s' despachado a asesor=%s lead=%s (ok=%s)",
                event_type, recipient, ctx.get("lead_id"), ok,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[CallReminders] Error enviando push '%s' a asesor=%s lead=%s: %s",
                event_type, recipient, ctx.get("lead_id"), exc,
            )

    return len(notifications_to_send)

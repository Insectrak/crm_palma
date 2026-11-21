"""
sla_service.py — Motor de monitorización y alertas de Tiempos de Gestión (SLA).

Reglas de Negocio:
  1. Alerta 15 minutos: Si un lead con asesor asignado supera los 15 min hábiles
     sin primer contacto/llamada, notifica al asesor vía push y marca SLA vencido.
  2. Alerta 24 horas: Si un lead supera las 24 horas sin gestión, notifica al
     supervisor y a la jefatura de ventas.
  3. Cálculo en Horario Hábil: Los leads ingresados después de las 21:00 (9:00 p.m.)
     entran como atención prioritaria y su temporizador de 15 min inicia a las 08:00 a.m.
     del día siguiente.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dtime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from psycopg2.extras import RealDictCursor

from app.database import get_db
from app.services import notification_service

logger = logging.getLogger(__name__)
LIMA_TZ = ZoneInfo("America/Lima")

HORA_APERTURA = dtime(8, 0)
HORA_CIERRE = dtime(21, 0)


def _now_lima() -> datetime:
    return datetime.now(LIMA_TZ)


def es_hora_nocturna(dt: Optional[datetime] = None) -> bool:
    """True si la hora en Lima está fuera del rango 08:00 a 21:00."""
    now = dt or _now_lima()
    t = now.time()
    return t >= HORA_CIERRE or t < HORA_APERTURA


def calcular_minutos_habiles(desde: datetime, hasta: Optional[datetime] = None) -> float:
    """Calcula los minutos hábiles transcurridos entre dos fechas considerando la ventana 08:00 a 21:00."""
    if not hasta:
        hasta = _now_lima()

    if desde.tzinfo is None:
        desde = desde.replace(tzinfo=LIMA_TZ)
    else:
        desde = desde.astimezone(LIMA_TZ)

    if hasta.tzinfo is None:
        hasta = hasta.replace(tzinfo=LIMA_TZ)
    else:
        hasta = hasta.astimezone(LIMA_TZ)

    if hasta <= desde:
        return 0.0

    # Si fue creado post 21:00, su tiempo cuenta a partir de las 08:00 a.m. del siguiente día
    desde_hora = desde.time()
    if desde_hora >= HORA_CIERRE:
        siguiente_dia = (desde + timedelta(days=1)).date()
        desde_ajustado = datetime.combine(siguiente_dia, HORA_APERTURA, tzinfo=LIMA_TZ)
    elif desde_hora < HORA_APERTURA:
        desde_ajustado = datetime.combine(desde.date(), HORA_APERTURA, tzinfo=LIMA_TZ)
    else:
        desde_ajustado = desde

    if hasta < desde_ajustado:
        return 0.0

    # Simplificado para la jornada del mismo día o acumulación entre días
    total_segundos = 0.0
    curr = desde_ajustado
    while curr < hasta:
        cierre_hoy = datetime.combine(curr.date(), HORA_CIERRE, tzinfo=LIMA_TZ)
        apertura_hoy = datetime.combine(curr.date(), HORA_APERTURA, tzinfo=LIMA_TZ)

        if curr < apertura_hoy:
            curr = apertura_hoy

        fin_bloque = min(hasta, cierre_hoy)
        if fin_bloque > curr:
            total_segundos += (fin_bloque - curr).total_seconds()

        # Avanzar al siguiente día a las 08:00
        curr = datetime.combine(curr.date() + timedelta(days=1), HORA_APERTURA, tzinfo=LIMA_TZ)

    return total_segundos / 60.0


def check_sla_alerts():
    """Ejecutado periódicamente por el scheduler para detectar y alertar leads vencidos."""
    now = _now_lima()
    logger.debug("[SLA] Ejecutando chequeo periódico de SLA...")

    notifications_to_send: list[tuple[str, str, dict, dict]] = []

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── 1. Alerta de 15 minutos para Asesor ───────────────────────────
            # Leads activos con asesor asignado, sin primer contacto y sin alerta de 15m enviada
            cur.execute(
                """
                SELECT
                    l.id,
                    TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) AS nombre_lead,
                    l.asesor_id,
                    l.created_at,
                    l.atencion_prioritaria
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND l.asesor_id IS NOT NULL
                  AND l.sla_15m_notificado_at IS NULL
                  AND (l.sla_15m_cumplido IS NULL OR l.sla_15m_cumplido = FALSE)
                  AND e.nombre = 'Nuevo'
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c
                      WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.llamadas ll
                      WHERE ll.lead_id = l.id
                  )
                LIMIT 100
                """
            )
            leads_15m = cur.fetchall()

            for lead in leads_15m:
                minutos = calcular_minutos_habiles(lead["created_at"], now)
                if minutos >= 15.0:
                    lead_id = lead["id"]
                    asesor_id = str(lead["asesor_id"])
                    nombre_lead = lead["nombre_lead"] or f"Lead #{lead_id}"

                    logger.info(
                        "[SLA 15m] Lead %s lleva %.1f min hábiles sin gestión. Alertando al asesor %s.",
                        lead_id, minutos, asesor_id,
                    )

                    # Guardar notificación para despachar fuera del lock de BD
                    notifications_to_send.append((
                        "lead_created",
                        asesor_id,
                        {
                            "lead_name": f"⚠️ SLA 15 min: {nombre_lead} espera atención",
                            "lead_id": lead_id,
                        },
                        {
                            "type": "sla_15m",
                            "lead_id": str(lead_id),
                        },
                    ))

                    # Registrar marca de notificación y marcar SLA no cumplido
                    cur.execute(
                        """
                        UPDATE crm.leads
                        SET sla_15m_notificado_at = NOW(),
                            sla_15m_cumplido = FALSE
                        WHERE id = %s
                        """,
                        (lead_id,),
                    )
            conn.commit()

            # ── 2. Alerta de 24 horas para Supervisores y Jefatura ───────────
            cur.execute(
                """
                SELECT
                    l.id,
                    TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) AS nombre_lead,
                    l.asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre_asesor,
                    COALESCE(l.supervisor_id, eq.supervisor_id) AS supervisor_id,
                    l.created_at
                FROM crm.leads l
                LEFT JOIN auth.users u ON u.id = l.asesor_id
                LEFT JOIN crm.equipos eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND l.sla_24h_notificado_at IS NULL
                  AND l.created_at <= NOW() - INTERVAL '24 hours'
                  AND e.nombre = 'Nuevo'
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.contactos c
                      WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.llamadas ll
                      WHERE ll.lead_id = l.id
                  )
                LIMIT 100
                """
            )
            leads_24h = cur.fetchall()

            cur.execute(
                """
                SELECT id FROM auth.users
                WHERE role = 'admin' AND is_active = TRUE
                LIMIT 5
                """
            )
            admins = cur.fetchall()

            for lead in leads_24h:
                lead_id = lead["id"]
                nombre_lead = lead["nombre_lead"] or f"Lead #{lead_id}"
                nombre_asesor = lead["nombre_asesor"] or "Sin asesor"
                supervisor_id = lead["supervisor_id"]

                logger.warning(
                    "[SLA 24h] Lead %s sin gestión tras 24h. Notificando a supervisión/jefatura.",
                    lead_id,
                )

                # Notificar al supervisor si existe (acumular para post-commit)
                if supervisor_id:
                    notifications_to_send.append((
                        "lead_created",
                        str(supervisor_id),
                        {
                            "lead_name": f"🚨 SLA 24h: {nombre_lead} (Asesor: {nombre_asesor}) sin gestión",
                            "lead_id": lead_id,
                        },
                        {
                            "type": "sla_24h",
                            "lead_id": str(lead_id),
                        },
                    ))

                # Notificar a administradores
                for adm in admins:
                    notifications_to_send.append((
                        "lead_created",
                        str(adm["id"]),
                        {
                            "lead_name": f"🚨 Alerta Jefatura (24h): {nombre_lead} sin gestión ({nombre_asesor})",
                            "lead_id": lead_id,
                        },
                        {
                            "type": "sla_24h",
                            "lead_id": str(lead_id),
                        },
                    ))

                cur.execute(
                    "UPDATE crm.leads SET sla_24h_notificado_at = NOW() WHERE id = %s",
                    (lead_id,),
                )
            conn.commit()

    # Despacho de notificaciones fuera de la conexión de base de datos
    for event_type, recipient, ctx, data in notifications_to_send:
        try:
            notification_service.notify(
                event_type=event_type,
                recipient_user_id=recipient,
                context=ctx,
                data=data,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SLA] Error enviando push a %s: %s", recipient, exc)

    # Ejecutar verificación de citas pendientes que ya pasaron su fecha y hora
    try:
        check_citas_vencidas_alerts()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Citas Vencidas] Error en chequeo periódico: %s", exc)


def check_citas_vencidas_alerts():
    """Detecta citas cuyo horario ya pasó y siguen en estado 'pendiente', alertando a asesores y supervisores."""
    logger.debug("[Citas Vencidas] Verificando citas pendientes que hayan pasado su horario...")
    notifications_to_send: list[tuple[str, str, dict, dict]] = []

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.id AS contacto_id,
                    c.lead_id,
                    c.fecha_cita,
                    c.tipo_cita,
                    c.duracion_minutos,
                    COALESCE(c.asesor_id, l.asesor_id) AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre_asesor,
                    COALESCE(l.supervisor_id, eq.supervisor_id) AS supervisor_id,
                    TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) AS nombre_lead
                FROM crm.contactos c
                JOIN crm.leads l ON l.id = c.lead_id
                LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                LEFT JOIN auth.users u ON u.id = COALESCE(c.asesor_id, l.asesor_id)
                LEFT JOIN crm.equipos eq ON eq.asesor_id = COALESCE(c.asesor_id, l.asesor_id) AND eq.activo = TRUE
                WHERE l.activo = TRUE
                  AND c.fecha_cita IS NOT NULL
                  AND (c.fecha_cita + (COALESCE(c.duracion_minutos, 30) || ' minutes')::interval) < NOW()
                  AND c.fecha_cita > NOW() - INTERVAL '7 days'
                  AND (ce.codigo = 'pendiente' OR ce.codigo IS NULL OR ce.nombre ILIKE '%%pendiente%%' OR c.cita_estado_id IS NULL)
                  AND COALESCE(ce.es_final, FALSE) = FALSE
                ORDER BY c.fecha_cita ASC
                LIMIT 100
                """
            )
            citas_vencidas = cur.fetchall()

            for cita in citas_vencidas:
                contacto_id = cita["contacto_id"]
                lead_id = cita["lead_id"]
                nombre_lead = cita["nombre_lead"] or f"Lead #{lead_id}"
                nombre_asesor = cita["nombre_asesor"] or "Sin asesor"
                asesor_id = cita["asesor_id"]
                supervisor_id = cita["supervisor_id"]
                fecha_cita = cita["fecha_cita"]
                fecha_str = fecha_cita.strftime('%H:%M %d/%m') if hasattr(fecha_cita, 'strftime') else str(fecha_cita)

                # 1. Notificar al asesor
                if asesor_id:
                    cur.execute(
                        """
                        SELECT 1 FROM crm.recordatorios_enviados
                        WHERE contacto_id = %s AND tipo = 'cita_vencida_asesor'
                        """,
                        (contacto_id,),
                    )
                    if not cur.fetchone():
                        notifications_to_send.append((
                            "lead_created",
                            str(asesor_id),
                            {
                                "lead_name": f"⚠️ Cita pendiente vencida: {nombre_lead} ({fecha_str}). Actualiza el estado de la cita.",
                                "lead_id": lead_id,
                            },
                            {
                                "type": "cita_vencida",
                                "lead_id": str(lead_id),
                                "contacto_id": str(contacto_id),
                            },
                        ))

                        cur.execute(
                            """
                            INSERT INTO crm.recordatorios_enviados (contacto_id, tipo, enviado_a)
                            VALUES (%s, 'cita_vencida_asesor', %s)
                            ON CONFLICT (contacto_id, tipo) DO NOTHING
                            """,
                            (contacto_id, str(asesor_id)),
                        )

                # 2. Notificar al supervisor
                if supervisor_id:
                    cur.execute(
                        """
                        SELECT 1 FROM crm.recordatorios_enviados
                        WHERE contacto_id = %s AND tipo = 'cita_vencida_supervisor'
                        """,
                        (contacto_id,),
                    )
                    if not cur.fetchone():
                        notifications_to_send.append((
                            "lead_created",
                            str(supervisor_id),
                            {
                                "lead_name": f"⚠️ Cita sin gestionar: {nombre_lead} ({nombre_asesor}) finalizó a las {fecha_str} y sigue 'Pendiente'.",
                                "lead_id": lead_id,
                            },
                            {
                                "type": "cita_vencida",
                                "lead_id": str(lead_id),
                                "contacto_id": str(contacto_id),
                            },
                        ))

                        cur.execute(
                            """
                            INSERT INTO crm.recordatorios_enviados (contacto_id, tipo, enviado_a)
                            VALUES (%s, 'cita_vencida_supervisor', %s)
                            ON CONFLICT (contacto_id, tipo) DO NOTHING
                            """,
                            (contacto_id, str(supervisor_id)),
                        )

            conn.commit()

    # Despacho de notificaciones fuera de la transacción de BD
    for event_type, recipient, ctx, data in notifications_to_send:
        try:
            notification_service.notify(
                event_type=event_type,
                recipient_user_id=recipient,
                context=ctx,
                data=data,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Cita Vencida] Error enviando push a %s: %s", recipient, exc)


def registrar_primer_contacto_sla(lead_id: int):
    """Evalúa y registra el cumplimiento de SLA al registrar el primer contacto o llamada."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT created_at, sla_15m_cumplido FROM crm.leads WHERE id = %s",
                (lead_id,),
            )
            row = cur.fetchone()
            if not row or row["sla_15m_cumplido"] is not None:
                return

            minutos = calcular_minutos_habiles(row["created_at"], _now_lima())
            cumplido = minutos <= 15.0
            cur.execute(
                "UPDATE crm.leads SET sla_15m_cumplido = %s WHERE id = %s",
                (cumplido, lead_id),
            )
            conn.commit()
            logger.info("[SLA] Lead %s primer contacto en %.1f min hábiles -> SLA cumplido=%s", lead_id, minutos, cumplido)

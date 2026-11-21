"""
notifications.py — Endpoints de notificaciones push (FCM).

- POST /fcm-token  — registrar token FCM
- DELETE /fcm-token — desregistrar token FCM (logout)
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor
from app.config import settings
from app.auth.jwt import get_current_user, TokenData
from app.database import get_db
from app.services import fcm_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/config")
def get_notification_config(current_user: TokenData = Depends(get_current_user)):
    """Retorna la configuracion de push para el movil."""
    return {
        "enabled": settings.fcm_enabled,
        "fcm_enabled": settings.fcm_enabled,
    }


@router.get("/inbox")
def get_notifications_inbox(current_user: TokenData = Depends(get_current_user)):
    """Retorna las notificaciones y alertas activas para el usuario actual en la Web."""
    user_id = current_user.user_id
    role = current_user.role
    notifications = []

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 0. Leads nuevos en últimas 24 horas (alerta inmediata para supervisor/admin/asesor)
                cur.execute(
                    """
                    SELECT 
                        l.id, l.nombres, l.apellidos, l.telefono, l.created_at,
                        f.nombre AS fuente_nombre,
                        TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre
                    FROM crm.leads l
                    JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    LEFT JOIN auth.users u ON u.id = l.asesor_id
                    WHERE l.activo = TRUE
                      AND e.nombre = 'Nuevo'
                      AND l.created_at >= NOW() - INTERVAL '24 hours'
                      AND (
                          %s = 'admin'
                          OR (%s = 'supervisor' AND (
                              l.asesor_id IN (
                                  SELECT eq.asesor_id FROM crm.equipos eq 
                                  WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN (
                                      SELECT s.id FROM auth.users s WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'
                                  )) AND eq.activo = TRUE
                              )
                              OR l.supervisor_id = %s::uuid
                              OR l.asesor_id = %s::uuid
                          ))
                          OR (%s = 'asesor' AND l.asesor_id = %s::uuid)
                      )
                    ORDER BY l.created_at DESC
                    LIMIT 15
                    """,
                    (role, role, user_id, user_id, user_id, user_id, role, user_id),
                )
                for row in cur.fetchall():
                    nombre = f"{row['nombres'] or ''} {row['apellidos'] or ''}".strip() or "Lead"
                    fuente_str = f" de {row['fuente_nombre']}" if row['fuente_nombre'] else ""
                    asesor_str = f" asignado a {row['asesor_nombre']}" if row['asesor_nombre'] and role in ('admin', 'supervisor') else ""
                    notifications.append({
                        "id": f"lead-nuevo-{row['id']}",
                        "type": "lead_nuevo",
                        "title": f"Nuevo lead: {nombre}",
                        "message": f"Lead nuevo{fuente_str}{asesor_str}.",
                        "lead_id": row["id"],
                        "created_at": str(row["created_at"]),
                        "severity": "info",
                        "link": f"/leads/{row['id']}",
                    })

                # 1. Citas programadas para hoy o próximas 24 horas
                cur.execute(
                    """
                    SELECT 
                        c.id, c.lead_id, c.fecha_cita, c.notas, c.tipo_cita,
                        l.nombres, l.apellidos, l.telefono,
                        (c.fecha_cita >= NOW() AND c.fecha_cita <= NOW() + INTERVAL '1 hour') AS en_proxima_hora
                    FROM crm.contactos c
                    JOIN crm.leads l ON l.id = c.lead_id
                    WHERE l.activo = TRUE
                      AND c.fecha_cita IS NOT NULL
                      AND c.fecha_cita >= NOW() - INTERVAL '2 hours'
                      AND c.fecha_cita <= NOW() + INTERVAL '24 hours'
                      AND (%s = 'admin' OR %s = 'supervisor' OR l.asesor_id = %s::uuid)
                    ORDER BY c.fecha_cita ASC
                    LIMIT 15
                    """,
                    (role, role, user_id),
                )
                for row in cur.fetchall():
                    nombre = f"{row['nombres'] or ''} {row['apellidos'] or ''}".strip() or "Lead"
                    tipo = (row['tipo_cita'] or 'Cita').strip()
                    es_llamada = 'llamada' in tipo.lower()
                    en_1h = bool(row.get('en_proxima_hora'))
                    hora_str = row['fecha_cita'].strftime('%H:%M %d/%m') if hasattr(row['fecha_cita'], 'strftime') else str(row['fecha_cita'])

                    if en_1h:
                        prefix = "📞 Llamada en 1 hora" if es_llamada else "📅 Cita en 1 hora"
                        severity = "warning"
                    else:
                        prefix = "📞 Llamada" if es_llamada else "📅 Cita"
                        severity = "info"

                    notifications.append({
                        "id": f"cita-{row['id']}",
                        "type": "llamada_programada" if es_llamada else "cita",
                        "title": f"{prefix}: {nombre}",
                        "message": f"{tipo} a las {hora_str}" + (f" · {row['notas'][:40]}" if row.get('notas') else ""),
                        "lead_id": row["lead_id"],
                        "created_at": str(row["fecha_cita"]),
                        "severity": severity,
                        "link": f"/leads/{row['lead_id']}",
                    })

                # 1.1 Citas vencidas que siguen en estado 'Pendiente' (después de su fecha y hora)
                cur.execute(
                    """
                    SELECT 
                        c.id, c.lead_id, c.fecha_cita, c.tipo_cita, c.duracion_minutos,
                        l.nombres, l.apellidos, l.telefono,
                        TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre
                    FROM crm.contactos c
                    JOIN crm.leads l ON l.id = c.lead_id
                    LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                    LEFT JOIN auth.users u ON u.id = COALESCE(c.asesor_id, l.asesor_id)
                    WHERE l.activo = TRUE
                      AND c.fecha_cita IS NOT NULL
                      AND (c.fecha_cita + (COALESCE(c.duracion_minutos, 30) || ' minutes')::interval) < NOW()
                      AND c.fecha_cita > NOW() - INTERVAL '7 days'
                      AND (ce.codigo = 'pendiente' OR ce.codigo IS NULL OR ce.nombre ILIKE '%%pendiente%%' OR c.cita_estado_id IS NULL)
                      AND COALESCE(ce.es_final, FALSE) = FALSE
                      AND (
                          %s = 'admin'
                          OR (%s = 'supervisor' AND (
                              l.asesor_id IN (SELECT eq.asesor_id FROM crm.equipos eq WHERE eq.supervisor_id = %s::uuid AND eq.activo = TRUE)
                              OR l.supervisor_id = %s::uuid
                              OR l.asesor_id = %s::uuid
                              OR c.asesor_id = %s::uuid
                          ))
                          OR (%s = 'asesor' AND (l.asesor_id = %s::uuid OR c.asesor_id = %s::uuid))
                      )
                    ORDER BY c.fecha_cita DESC
                    LIMIT 15
                    """,
                    (role, role, user_id, user_id, user_id, user_id, role, user_id, user_id),
                )
                for row in cur.fetchall():
                    nombre = f"{row['nombres'] or ''} {row['apellidos'] or ''}".strip() or "Lead"
                    fc = row["fecha_cita"]
                    hora_str = fc.strftime('%H:%M %d/%m') if hasattr(fc, 'strftime') else str(fc)
                    asesor_info = f" · Asesor: {row['asesor_nombre']}" if row['asesor_nombre'] and role in ('admin', 'supervisor') else ""
                    notifications.append({
                        "id": f"cita-vencida-{row['id']}",
                        "type": "cita_vencida",
                        "title": f"Cita pendiente vencida: {nombre}",
                        "message": f"Cita de las {hora_str}{asesor_info} ya finalizó y sigue en estado 'Pendiente'. Favor de registrar su resultado.",
                        "lead_id": row["lead_id"],
                        "created_at": str(row["fecha_cita"]),
                        "severity": "urgent",
                        "link": f"/leads/{row['lead_id']}",
                    })

                # 2. Leads con SLA de 15m vencido (sin primer contacto en >15 min)
                cur.execute(
                    """
                    SELECT 
                        l.id, l.nombres, l.apellidos, l.telefono, l.created_at,
                        f.nombre AS fuente_nombre
                    FROM crm.leads l
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    WHERE l.activo = TRUE
                      AND l.created_at < NOW() - INTERVAL '15 minutes'
                      AND l.created_at > NOW() - INTERVAL '48 hours'
                      AND (%s = 'admin' OR %s = 'supervisor' OR l.asesor_id = %s::uuid)
                      AND NOT EXISTS (
                          SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                          UNION ALL
                          SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id
                      )
                    ORDER BY l.created_at DESC
                    LIMIT 15
                    """,
                    (role, role, user_id),
                )
                for row in cur.fetchall():
                    nombre = f"{row['nombres'] or ''} {row['apellidos'] or ''}".strip() or "Lead"
                    notifications.append({
                        "id": f"sla15-{row['id']}",
                        "type": "sla_15m",
                        "title": f"SLA 15m: {nombre}",
                        "message": f"Lead de {row['fuente_nombre'] or 'origen web'} esperando primera gestión.",
                        "lead_id": row["id"],
                        "created_at": str(row["created_at"]),
                        "severity": "urgent",
                        "link": f"/leads/{row['id']}",
                    })

                # 3. Recontactos recientes (leads que volvieron a entrar en últimas 48h)
                cur.execute(
                    """
                    SELECT 
                        lr.id, lr.lead_id, lr.created_at,
                        l.nombres, l.apellidos, f.nombre AS fuente_nombre
                    FROM crm.lead_recontactos lr
                    JOIN crm.leads l ON l.id = lr.lead_id
                    LEFT JOIN crm.fuentes f ON f.id = lr.fuente_id
                    WHERE l.activo = TRUE
                      AND lr.created_at > NOW() - INTERVAL '48 hours'
                      AND (%s = 'admin' OR %s = 'supervisor' OR l.asesor_id = %s::uuid)
                    ORDER BY lr.created_at DESC
                    LIMIT 10
                    """,
                    (role, role, user_id),
                )
                for row in cur.fetchall():
                    nombre = f"{row['nombres'] or ''} {row['apellidos'] or ''}".strip() or "Lead"
                    notifications.append({
                        "id": f"recontacto-{row['id']}",
                        "type": "recontacto",
                        "title": f"Recontacto: {nombre}",
                        "message": f"El lead volvió a ingresar por {row['fuente_nombre'] or 'campaña'}.",
                        "lead_id": row["lead_id"],
                        "created_at": str(row["created_at"]),
                        "severity": "warning",
                        "link": f"/leads/{row['lead_id']}",
                    })

                # 4. Cola estancada (para admin / supervisor)
                if role in ("admin", "supervisor"):
                    cur.execute(
                        """
                        SELECT id, nombres, apellidos, fecha_entrada_cola
                        FROM crm.leads
                        WHERE activo = TRUE
                          AND asesor_id IS NULL
                          AND fecha_entrada_cola IS NOT NULL
                          AND fecha_entrada_cola < NOW() - INTERVAL '24 hours'
                        ORDER BY fecha_entrada_cola ASC
                        LIMIT 5
                        """
                    )
                    for row in cur.fetchall():
                        nombre = f"{row['nombres'] or ''} {row['apellidos'] or ''}".strip() or "Lead"
                        notifications.append({
                            "id": f"cola-{row['id']}",
                            "type": "cola_estancada",
                            "title": f"Cola estancada: {nombre}",
                            "message": "Lead sin asignar por más de 24h en cola.",
                            "lead_id": row["id"],
                            "created_at": str(row["fecha_entrada_cola"]),
                            "severity": "warning",
                            "link": "/asignacion",
                        })

                # 5. Próxima acción / seguimiento programada en la próxima hora (alerta anticipada de 1 hora)
                cur.execute(
                    """
                    SELECT 
                        l.id, l.nombres, l.apellidos, l.telefono, l.fecha_proxima_gestion,
                        l.accion_proxima_gestion,
                        e.nombre AS estado_nombre,
                        TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN auth.users u ON u.id = l.asesor_id
                    WHERE l.activo = TRUE
                      AND l.fecha_proxima_gestion IS NOT NULL
                      AND l.fecha_proxima_gestion >= NOW() - INTERVAL '30 minutes'
                      AND l.fecha_proxima_gestion <= NOW() + INTERVAL '1 hour'
                      AND (%s = 'admin' OR %s = 'supervisor' OR l.asesor_id = %s::uuid)
                    ORDER BY l.fecha_proxima_gestion ASC
                    LIMIT 15
                    """,
                    (role, role, user_id),
                )
                for row in cur.fetchall():
                    nombre = f"{row['nombres'] or ''} {row['apellidos'] or ''}".strip() or "Lead"
                    fpg = row["fecha_proxima_gestion"]
                    hora_str = fpg.strftime('%H:%M %d/%m') if hasattr(fpg, 'strftime') else str(fpg)
                    accion = (row["accion_proxima_gestion"] or "").strip()
                    es_llamada = "llam" in accion.lower() or not accion
                    prefix = "📞 Llamada en 1 hora" if es_llamada else "⏰ Próxima gestión"
                    detalle_accion = accion or "Llamada de seguimiento"
                    notifications.append({
                        "id": f"prox-accion-{row['id']}",
                        "type": "llamada_programada" if es_llamada else "proxima_gestion",
                        "title": f"{prefix}: {nombre}",
                        "message": f"{detalle_accion} a las {hora_str}. Estado: {row['estado_nombre'] or 'Seguimiento'}.",
                        "lead_id": row["id"],
                        "created_at": str(fpg),
                        "severity": "warning",
                        "link": f"/leads/{row['id']}",
                    })

    except Exception:
        pass

    return {
        "total": len(notifications),
        "items": notifications[:30],
    }


class FCMTokenRequest(BaseModel):
    fcm_token: str
    device_info: str = ""


@router.post("/fcm-token")
def register_fcm_token(
    body: FCMTokenRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """Registra un token FCM para recibir push instantaneo."""
    ok = fcm_service.register_token(
        user_id=current_user.user_id,
        fcm_token=body.fcm_token,
        device_info=body.device_info,
    )
    return {"registered": ok}


@router.delete("/fcm-token")
def unregister_fcm_token(
    body: FCMTokenRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """Desregistra un token FCM (logout)."""
    ok = fcm_service.unregister_token(fcm_token=body.fcm_token)
    return {"unregistered": ok}

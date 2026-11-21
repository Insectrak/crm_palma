"""
test_call_reminders.py — Pruebas para el sistema de notificaciones de llamadas y citas programadas.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch
import pytest

from app.services.call_reminder_service import (
    _format_hora_local,
    check_scheduled_call_reminders,
    LIMA_TZ,
)
from app.services.notification_service import (
    _TEMPLATE_DEFAULTS,
    _TEMPLATE_VARIABLES,
    URGENT_EVENTS,
)


def test_notification_templates_and_urgent_events():
    """Verifica que llamada_programada y cita_programada estén registradas correctamente."""
    assert "llamada_programada" in _TEMPLATE_DEFAULTS
    assert "cita_programada" in _TEMPLATE_DEFAULTS

    assert "llamada_programada" in URGENT_EVENTS
    assert "cita_programada" in URGENT_EVENTS

    assert "llamada_programada" in _TEMPLATE_VARIABLES
    assert "cita_programada" in _TEMPLATE_VARIABLES

    tpl = _TEMPLATE_DEFAULTS["llamada_programada"]
    assert "1 hora" in tpl["title"]
    assert "{lead_name}" in tpl["body"]
    assert "{hora}" in tpl["body"]


def test_format_hora_local():
    """Verifica el formateo correcto de hora en zona horaria Lima (UTC-5)."""
    # 15:30 UTC -> 10:30 Lima
    dt_utc = datetime(2026, 9, 18, 15, 30, tzinfo=timezone.utc)
    assert _format_hora_local(dt_utc) == "10:30"

    # None retorna cadena vacía
    assert _format_hora_local(None) == ""


def test_check_scheduled_call_reminders_dispatches_contactos():
    """Verifica que una cita agendada en 45 min despache push y registre deduplicación."""
    fake_fecha_cita = datetime.now(timezone.utc) + timedelta(minutes=45)

    fake_cita = {
        "contacto_id": 101,
        "lead_id": 202,
        "fecha_cita": fake_fecha_cita,
        "tipo_cita": "Llamada telefónica",
        "notas": "Llamar para coordinar inicio",
        "asesor_id": "00000000-0000-0000-0000-000000000001",
        "nombre_lead": "Juan Perez",
        "telefono": "+51999888777",
    }

    cur = MagicMock()
    # 1er fetchall para SELECT contactos: retorna la cita
    # 2do fetchone para deduplicación: retorna None (no enviado previamente)
    # 3er fetchall para SELECT leads: retorna vacío
    cur.fetchall.side_effect = [
        [fake_cita],  # crm.contactos
        [],           # crm.leads
    ]
    cur.fetchone.return_value = None  # deduplicacion recordatorios_enviados

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.call_reminder_service.get_db", return_value=db_cm), \
         patch("app.services.notification_service.notify", return_value=True) as mock_notify:

        count = check_scheduled_call_reminders()

        assert count == 1
        mock_notify.assert_called_once()
        kargs = mock_notify.call_args.kwargs
        assert kargs["event_type"] == "llamada_programada"
        assert kargs["recipient_user_id"] == "00000000-0000-0000-0000-000000000001"
        assert kargs["context"]["lead_name"] == "Juan Perez"
        assert kargs["context"]["lead_id"] == 202
        assert "Llamada" in kargs["context"]["detalle"]

        # Verificar que se insertó en crm.recordatorios_enviados
        inserted = False
        for c in cur.execute.call_args_list:
            sql = c[0][0]
            if "INSERT INTO crm.recordatorios_enviados" in sql:
                inserted = True
                assert c[0][1][0] == 101
                assert c[0][1][1] == "push_llamada_1h"
                break
        assert inserted, "No se registró en crm.recordatorios_enviados"


def test_check_scheduled_call_reminders_deduplication():
    """Si ya existe registro en recordatorios_enviados, no vuelve a notificar."""
    fake_fecha_cita = datetime.now(timezone.utc) + timedelta(minutes=45)

    fake_cita = {
        "contacto_id": 101,
        "lead_id": 202,
        "fecha_cita": fake_fecha_cita,
        "tipo_cita": "Llamada",
        "notas": "",
        "asesor_id": "00000000-0000-0000-0000-000000000001",
        "nombre_lead": "Juan Perez",
        "telefono": "+51999888777",
    }

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [fake_cita],  # crm.contactos
        [],           # crm.leads
    ]
    cur.fetchone.return_value = {"id": 1}  # Ya existe recordatorio

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.call_reminder_service.get_db", return_value=db_cm), \
         patch("app.services.notification_service.notify") as mock_notify:

        count = check_scheduled_call_reminders()

        assert count == 0
        mock_notify.assert_not_called()


def test_check_scheduled_call_reminders_dispatches_leads():
    """Verifica que una próxima gestión en crm.leads despache notificación y marque el timestamp."""
    fake_fecha_proxima = datetime.now(timezone.utc) + timedelta(minutes=30)

    fake_lead = {
        "lead_id": 303,
        "fecha_proxima_gestion": fake_fecha_proxima,
        "accion_proxima_gestion": "Llamar para resolver dudas",
        "asesor_id": "00000000-0000-0000-0000-000000000002",
        "nombre_lead": "Maria Lopez",
        "telefono": "+51988777666",
    }

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [],            # crm.contactos
        [fake_lead],   # crm.leads
    ]
    cur.rowcount = 1  # UPDATE exitoso

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.call_reminder_service.get_db", return_value=db_cm), \
         patch("app.services.notification_service.notify", return_value=True) as mock_notify:

        count = check_scheduled_call_reminders()

        assert count == 1
        mock_notify.assert_called_once()
        kargs = mock_notify.call_args.kwargs
        assert kargs["event_type"] == "llamada_programada"
        assert kargs["recipient_user_id"] == "00000000-0000-0000-0000-000000000002"
        assert kargs["context"]["lead_name"] == "Maria Lopez"
        assert kargs["context"]["lead_id"] == 303

        # Verificar que se actualizó crm.leads.proxima_gestion_notificada_at
        updated = False
        for c in cur.execute.call_args_list:
            sql = c[0][0]
            if "UPDATE crm.leads" in sql and "proxima_gestion_notificada_at = NOW()" in sql:
                updated = True
                assert c[0][1][0] == 303
                break
        assert updated, "No se actualizó proxima_gestion_notificada_at en crm.leads"


def test_reschedule_contacto_clears_call_recordatorios():
    """Verifica que al reprogramar una cita en crm.contactos se borren los recordatorios previos."""
    from app.routers.contactos import update_contacto, ContactoUpdate
    from app.auth.jwt import TokenData

    cur = MagicMock()
    # SELECT contacto, SELECT app_settings, RETURNING id
    cur.fetchone.side_effect = [
        {"id": 55, "tipo_contacto": "llamada", "fecha_cita": "2026-09-18 10:00:00+00", "resultado": "cita_agendada"}, # contacto_existente
        {"value": {"asesor_can_edit": True}}, # app_settings
        {"id": 55}, # RETURNING id from update
    ]
    cur.rowcount = 1

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    user = TokenData(user_id="00000000-0000-0000-0000-000000000001", role="asesor", email="test@example.com")
    data = ContactoUpdate(fecha_cita="2026-09-18 15:00:00+00")

    with patch("app.routers.contactos.get_db", return_value=db_cm):
        res = update_contacto(lead_id=10, contacto_id=55, data=data, current_user=user)
        assert "message" in res

    deleted = False
    for c in cur.execute.call_args_list:
        sql = c[0][0]
        if "DELETE FROM crm.recordatorios_enviados" in sql:
            deleted = True
            assert "push_llamada_1h" in sql
            assert "push_cita_1h" in sql
            assert c[0][1][0] == 55
            break
    assert deleted, "No se ejecutó DELETE FROM crm.recordatorios_enviados para push_llamada_1h"


def test_notifications_inbox_1h_badge():
    """Verifica que citas dentro de 1 hora reciban severity='warning' y prefijo '📞 Llamada en 1 hora'."""
    from app.routers.notifications import get_notifications_inbox
    from app.auth.jwt import TokenData

    fake_dt = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [],  # 0. leads nuevos
        [    # 1. citas
            {
                "id": 88,
                "lead_id": 99,
                "fecha_cita": fake_dt,
                "notas": "Llamada de cierre",
                "tipo_cita": "Llamada telefónica",
                "nombres": "Carlos",
                "apellidos": "Santana",
                "telefono": "+51900111222",
                "en_proxima_hora": True,
            }
        ],
        [],  # 1.1 citas vencidas
        [],  # 2. sla 15m
        [],  # 3. recontactos
        [],  # 5. proxima gestion
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    user = TokenData(user_id="00000000-0000-0000-0000-000000000001", role="asesor", email="test@example.com")

    with patch("app.routers.notifications.get_db", return_value=db_cm):
        result = get_notifications_inbox(current_user=user)

    items = result["items"]
    assert len(items) == 1
    cita_item = items[0]
    assert "📞 Llamada en 1 hora" in cita_item["title"]
    assert cita_item["severity"] == "warning"
    assert cita_item["lead_id"] == 99


def test_integration_check_scheduled_call_reminders_db():
    """Prueba de integración end-to-end con la base de datos real (crm_local)."""
    from app.database import init_db_pool, get_db
    init_db_pool()

    test_lead_id = None
    test_contacto_id = None

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Obtener un asesor y una fuente reales
                cur.execute("SELECT id FROM auth.users WHERE is_active = TRUE LIMIT 1")
                user_row = cur.fetchone()
                if not user_row:
                    pytest.skip("No hay usuarios activos en la BD local")
                test_user_id = str(user_row[0])

                cur.execute("SELECT id FROM crm.fuentes LIMIT 1")
                fuente_row = cur.fetchone()
                test_fuente_id = fuente_row[0] if fuente_row else 1

                # 1. Crear un lead con fecha_proxima_gestion en 40 minutos
                cur.execute(
                    """
                    INSERT INTO crm.leads (
                        nombres, apellidos, telefono, fuente_id, estado_id,
                        asesor_id, fecha_proxima_gestion, accion_proxima_gestion, activo
                    )
                    VALUES (
                        'TestLlamada', 'Antigravity', '+51999000111', %s, 10,
                        %s::uuid, NOW() + INTERVAL '40 minutes', 'Llamar para matrícula', TRUE
                    )
                    RETURNING id
                    """,
                    (test_fuente_id, test_user_id),
                )
                test_lead_id = cur.fetchone()[0]

                # 2. Crear una cita para ese lead en 50 minutos
                cur.execute(
                    """
                    INSERT INTO crm.contactos (
                        lead_id, asesor_id, tipo_contacto, tipo_cita,
                        fecha_cita, notas
                    )
                    VALUES (
                        %s, %s::uuid, 'cita_agendada', 'llamada',
                        NOW() + INTERVAL '50 minutes', 'Llamada agendada test'
                    )
                    RETURNING id
                    """,
                    (test_lead_id, test_user_id),
                )
                test_contacto_id = cur.fetchone()[0]
                conn.commit()

        # Mock solo de notification_service.notify para no enviar FCM real en tests
        with patch("app.services.notification_service.notify", return_value=True) as mock_notify:
            dispatched = check_scheduled_call_reminders()

            # Debe haber despachado al menos la cita
            assert dispatched >= 1
            assert mock_notify.called

            # Verificar que la cita fue marcada en crm.recordatorios_enviados
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM crm.recordatorios_enviados WHERE contacto_id = %s AND tipo = 'push_llamada_1h'",
                        (test_contacto_id,),
                    )
                    assert cur.fetchone() is not None, "Cita no fue registrada en recordatorios_enviados"

            # Ejecución sucesiva: no debe duplicar para este lead ni contacto
            mock_notify.reset_mock()
            dispatched_second = check_scheduled_call_reminders()

            # En el segundo ciclo, test_contacto_id ya está en recordatorios_enviados
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM crm.recordatorios_enviados WHERE contacto_id = %s AND tipo = 'push_llamada_1h'",
                        (test_contacto_id,),
                    )
                    assert cur.fetchone()[0] == 1, "Hubo duplicado en crm.recordatorios_enviados"

    finally:
        # Limpieza
        if test_lead_id:
            with get_db() as conn:
                with conn.cursor() as cur:
                    if test_contacto_id:
                        cur.execute("DELETE FROM crm.recordatorios_enviados WHERE contacto_id = %s", (test_contacto_id,))
                        cur.execute("DELETE FROM crm.contactos WHERE id = %s", (test_contacto_id,))
                    cur.execute("DELETE FROM crm.leads WHERE id = %s", (test_lead_id,))
                    conn.commit()


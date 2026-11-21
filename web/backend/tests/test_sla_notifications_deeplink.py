"""
test_sla_notifications_deeplink.py — Verifica que sla_service envia `data` con
type y lead_id para deep-link en notificaciones móviles (SLA 15m, SLA 24h y Citas vencidas).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.sla_service import check_citas_vencidas_alerts, check_sla_alerts


def test_check_sla_alerts_includes_deeplink_data():
    now_utc = datetime.now(timezone.utc)
    fake_lead_15m = {
        "id": 42,
        "nombre_lead": "Ana Torres",
        "asesor_id": "11111111-1111-1111-1111-111111111111",
        "created_at": now_utc - timedelta(minutes=25),
        "atencion_prioritaria": False,
    }
    fake_lead_24h = {
        "id": 99,
        "nombre_lead": "Luis Rojas",
        "asesor_id": "11111111-1111-1111-1111-111111111111",
        "nombre_asesor": "Asesor Uno",
        "supervisor_id": "22222222-2222-2222-2222-222222222222",
        "created_at": now_utc - timedelta(hours=25),
    }
    fake_admin = {"id": "33333333-3333-3333-3333-333333333333"}

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [fake_lead_15m],
        [fake_lead_24h],
        [fake_admin],
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.sla_service.get_db", return_value=db_cm), \
         patch("app.services.sla_service.calcular_minutos_habiles", return_value=20.0), \
         patch("app.services.sla_service.check_citas_vencidas_alerts"), \
         patch("app.services.notification_service.notify", return_value=True) as mock_notify:
        check_sla_alerts()

    assert mock_notify.call_count == 3
    calls_data = [c.kwargs["data"] for c in mock_notify.call_args_list]
    assert {"type": "sla_15m", "lead_id": "42"} in calls_data
    assert calls_data.count({"type": "sla_24h", "lead_id": "99"}) == 2


def test_check_citas_vencidas_alerts_includes_deeplink_data():
    now_utc = datetime.now(timezone.utc)
    fake_cita = {
        "contacto_id": 501,
        "lead_id": 77,
        "fecha_cita": now_utc - timedelta(hours=2),
        "tipo_cita": "Cita virtual",
        "duracion_minutos": 30,
        "asesor_id": "11111111-1111-1111-1111-111111111111",
        "nombre_asesor": "Asesor Uno",
        "supervisor_id": "22222222-2222-2222-2222-222222222222",
        "nombre_lead": "Carla Diaz",
    }

    cur = MagicMock()
    cur.fetchall.return_value = [fake_cita]
    cur.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.sla_service.get_db", return_value=db_cm), \
         patch("app.services.notification_service.notify", return_value=True) as mock_notify:
        check_citas_vencidas_alerts()

    assert mock_notify.call_count == 2
    for c in mock_notify.call_args_list:
        assert c.kwargs["data"] == {
            "type": "cita_vencida",
            "lead_id": "77",
            "contacto_id": "501",
        }

"""
test_proxima_gestion_notifications.py — Tests para las notificaciones de próxima acción / seguimiento.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest

from app.auth.jwt import TokenData
from app.routers.notifications import get_notifications_inbox


@pytest.fixture
def mock_asesor_user():
    return TokenData(
        user_id="22222222-2222-2222-2222-222222222222",
        email="asesor@test.local",
        role="asesor",
    )


@pytest.fixture
def mock_admin_user():
    return TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="admin@test.local",
        role="admin",
    )


def test_get_notifications_inbox_includes_proxima_gestion(mock_asesor_user):
    now = datetime.now(timezone.utc)
    target_time = now + timedelta(minutes=45)

    cur = MagicMock()
    # Mock return values for queries:
    # 1. Citas programadas
    # 1.1 Citas vencidas
    # 2. SLA 15m
    # 3. Recontactos
    # 4. Cola estancada (skipped for asesor)
    # 5. Proxima accion
    cur.fetchall.side_effect = [
        [],  # 1. Citas
        [],  # 1.1 Citas vencidas
        [],  # 2. SLA 15m
        [],  # 3. Recontactos
        [    # 5. Proxima gestion
            {
                "id": 501,
                "nombres": "Juan",
                "apellidos": "Pérez",
                "telefono": "+51999111222",
                "fecha_proxima_gestion": target_time,
                "estado_nombre": "En seguimiento",
                "asesor_nombre": "Carlos Asesor",
            }
        ],
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.notifications.get_db", return_value=db_cm):
        res = get_notifications_inbox(current_user=mock_asesor_user)

    assert res["total"] == 1
    item = res["items"][0]
    assert item["id"] == "prox-accion-501"
    assert item["type"] == "proxima_gestion"
    assert "Juan Pérez" in item["title"]
    assert "En seguimiento" in item["message"]
    assert item["lead_id"] == 501
    assert item["severity"] == "warning"
    assert item["link"] == "/leads/501"


def test_get_notifications_inbox_includes_citas_vencidas(mock_asesor_user):
    now = datetime.now(timezone.utc)
    cita_past = now - timedelta(hours=2)

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [],  # 1. Citas
        [    # 1.1 Citas vencidas
            {
                "id": 901,
                "lead_id": 601,
                "nombres": "Maria",
                "apellidos": "Gomez",
                "telefono": "+51988222333",
                "fecha_cita": cita_past,
                "tipo_cita": "Presencial",
                "duracion_minutos": 30,
                "asesor_nombre": "Carlos Asesor",
            }
        ],
        [],  # 2. SLA 15m
        [],  # 3. Recontactos
        [],  # 5. Proxima gestion
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.notifications.get_db", return_value=db_cm):
        res = get_notifications_inbox(current_user=mock_asesor_user)

    assert res["total"] == 1
    item = res["items"][0]
    assert item["id"] == "cita-vencida-901"
    assert item["type"] == "cita_vencida"
    assert "Maria Gomez" in item["title"]
    assert "Pendiente" in item["message"]
    assert item["lead_id"] == 601
    assert item["severity"] == "urgent"
    assert item["link"] == "/leads/601"

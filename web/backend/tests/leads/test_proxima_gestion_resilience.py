"""
test_proxima_gestion_resilience.py — Verifica que actualizar el estado o datos del lead
sea tolerante a drift de esquema respecto a proxima_gestion_notificada_at.
"""
import pytest
from unittest.mock import MagicMock, patch
from app.routers.leads import update_estado, update_lead, EstadoUpdate, LeadUpdate
from app.auth.schemas import TokenData


def test_update_estado_without_proxima_gestion_column():
    """Si la columna proxima_gestion_notificada_at no existe en la BD, update_estado
    no debe incluirla en el SQL ni fallar."""
    fake_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@example.com",
        role="admin",
    )

    cur = MagicMock()
    # 1. SELECT nombre FROM crm.estados_lead
    # 2. SELECT estado_id, api_client_id FROM crm.leads
    # 3. UPDATE crm.leads RETURNING id
    # 4. SELECT nombre FROM crm.estados_lead
    # 5. INSERT INTO crm.contactos
    cur.fetchone.side_effect = [
        {"nombre": "Contactado"},
        {"estado_id": 1, "api_client_id": None},
        {"id": 10},
        {"nombre": "Contactado"},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    payload = EstadoUpdate(
        estado_id=2,
        fecha_proxima_gestion=None,
    )

    with patch("app.routers.leads.get_db", return_value=db_cm), \
         patch("app.routers.leads._has_proxima_gestion_notificada_column", return_value=False):

        result = update_estado(
            lead_id=10,
            data=payload,
            current_user=fake_user,
        )

        assert result["message"] == "Estado actualizado"

        # Verificar el SQL generado para el UPDATE
        update_calls = [
            c[0][0] for c in cur.execute.call_args_list
            if "UPDATE crm.leads" in c[0][0]
        ]
        assert len(update_calls) == 1
        update_sql = update_calls[0]
        assert "proxima_gestion_notificada_at" not in update_sql
        assert "fecha_proxima_gestion = NULL" in update_sql


def test_update_estado_with_proxima_gestion_column():
    """Si la columna proxima_gestion_notificada_at sí existe en la BD, update_estado
    debe incluirla para resetear la marca de notificación."""
    fake_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@example.com",
        role="admin",
    )

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"nombre": "Contactado"},
        {"estado_id": 1, "api_client_id": None},
        {"id": 10},
        {"nombre": "Contactado"},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    payload = EstadoUpdate(
        estado_id=2,
        fecha_proxima_gestion=None,
    )

    with patch("app.routers.leads.get_db", return_value=db_cm), \
         patch("app.routers.leads._has_proxima_gestion_notificada_column", return_value=True):

        result = update_estado(
            lead_id=10,
            data=payload,
            current_user=fake_user,
        )

        assert result["message"] == "Estado actualizado"

        update_calls = [
            c[0][0] for c in cur.execute.call_args_list
            if "UPDATE crm.leads" in c[0][0]
        ]
        assert len(update_calls) == 1
        update_sql = update_calls[0]
        assert "proxima_gestion_notificada_at = NULL" in update_sql


def test_update_lead_without_proxima_gestion_column():
    """update_lead tampoco debe incluir proxima_gestion_notificada_at si la columna no existe."""
    fake_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@example.com",
        role="admin",
    )

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"nombre": "Contactado"},
        {"estado_id": 1, "api_client_id": None},
        {"id": 10},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    payload = LeadUpdate(
        fecha_proxima_gestion="2026-09-20T10:00:00Z",
    )

    with patch("app.routers.leads.get_db", return_value=db_cm), \
         patch("app.routers.leads._has_proxima_gestion_notificada_column", return_value=False):

        result = update_lead(
            lead_id=10,
            data=payload,
            current_user=fake_user,
        )

        assert result["message"] == "Lead actualizado"

        update_calls = [
            c[0][0] for c in cur.execute.call_args_list
            if "UPDATE crm.leads l" in c[0][0]
        ]
        assert len(update_calls) == 1
        update_sql = update_calls[0]
        assert "proxima_gestion_notificada_at" not in update_sql
        assert "fecha_proxima_gestion = %s" in update_sql


def test_update_lead_with_proxima_gestion_column():
    """update_lead resetea proxima_gestion_notificada_at si la columna sí existe."""
    fake_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@example.com",
        role="admin",
    )

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"nombre": "Contactado"},
        {"estado_id": 1, "api_client_id": None},
        {"id": 10},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    payload = LeadUpdate(
        fecha_proxima_gestion="2026-09-20T10:00:00Z",
    )

    with patch("app.routers.leads.get_db", return_value=db_cm), \
         patch("app.routers.leads._has_proxima_gestion_notificada_column", return_value=True):

        result = update_lead(
            lead_id=10,
            data=payload,
            current_user=fake_user,
        )

        assert result["message"] == "Lead actualizado"

        update_calls = [
            c[0][0] for c in cur.execute.call_args_list
            if "UPDATE crm.leads l" in c[0][0]
        ]
        assert len(update_calls) == 1
        update_sql = update_calls[0]
        assert "proxima_gestion_notificada_at = NULL" in update_sql

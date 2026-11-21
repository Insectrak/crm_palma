"""
test_historicos_fuente_mantenimiento.py — Tests unitarios para detección y corrección de leads históricos sin fuente.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.auth.schemas import TokenData
from app.routers.leads import (
    CorregirFuenteHistoricosRequest,
    detectar_historicos_sin_fuente,
    corregir_fuente_historicos,
    bulk_update_fuente,
)


@pytest.fixture
def mock_admin_user():
    return TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="admin@test.local",
        role="admin",
    )


def test_detectar_historicos_sin_fuente(mock_admin_user):
    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "id": 101,
            "nombre_completo": "Lead Historico",
            "telefono": "+51999888777",
            "email": "lead@test.local",
            "fuente_actual": "Sin fuente",
            "estado_nombre": "Nuevo",
            "asesor_nombre": "Asesor Test",
            "fecha_ingreso": "2026-08-01 10:00:00",
        }
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.leads.get_db", return_value=db_cm):
        res = detectar_historicos_sin_fuente(current_user=mock_admin_user)

    assert res["count"] == 1
    assert len(res["leads"]) == 1
    assert res["leads"][0]["id"] == 101
    assert cur.execute.called

    query = cur.execute.call_args[0][0]
    assert "crm_legacy.leads_historico" in query
    assert "crm.asignaciones_log" in query
    assert "historico" in query.lower()


def test_corregir_fuente_historicos(mock_admin_user):
    cur = MagicMock()
    # 1. frow for fuente_id
    cur.fetchone.return_value = {"id": 10}
    # 2. updated rows
    cur.fetchall.return_value = [{"id": 101}, {"id": 102}]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = CorregirFuenteHistoricosRequest(lead_ids=[101, 102])

    with patch("app.routers.leads.get_db", return_value=db_cm):
        res = corregir_fuente_historicos(body=req, current_user=mock_admin_user)

    assert res["ok"] is True
    assert res["updated_count"] == 2
    assert res["fuente_id"] == 10
    assert conn.commit.called

    queries = [call[0][0] for call in cur.execute.call_args_list]
    assert any("UPDATE crm.leads" in q for q in queries)


def test_bulk_update_fuente(mock_admin_user):
    cur = MagicMock()
    cur.fetchone.return_value = {"nombre": "Historico"}
    cur.fetchall.return_value = [{"id": 201}, {"id": 202}]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.leads.get_db", return_value=db_cm):
        res = bulk_update_fuente(
            payload={"ids": [201, 202], "fuente_id": 5},
            current_user=mock_admin_user,
        )

    assert res["updated"] == 2
    assert res["fuente"] == "Historico"
    assert cur.execute.called


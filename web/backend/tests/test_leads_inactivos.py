"""
test_leads_inactivos.py — Tests unitarios para el router de leads inactivos / papelera.
"""
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.auth.schemas import TokenData
from app.routers.leads_inactivos import (
    RestaurarLeadsRequest,
    CambiarEstadoRequest,
    BulkCambiarEstadoRequest,
    EliminarPermanenteRequest,
    list_leads_inactivos,
    get_leads_inactivos_stats,
    restaurar_leads,
    cambiar_estado_lead_inactivo,
    bulk_cambiar_estado_leads_inactivos,
    eliminar_leads_permanente,
)


@pytest.fixture
def mock_admin():
    return TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="admin@test.local",
        role="admin",
    )


def test_list_leads_inactivos(mock_admin):
    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "id": 10,
            "nombre_completo": "Juan Perez",
            "telefono": "+51999999999",
            "email": "juan@test.com",
            "estado_id": 5,
            "estado_nombre": "Matricula verificada",
            "estado_color": "#3B82F6",
            "fecha_inactivacion": "2026-08-01 10:00:00",
        }
    ]
    cur.fetchone.return_value = {"total": 1}

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = MagicMock()

    with patch("app.routers.leads_inactivos.get_db", return_value=db_cm):
        res = list_leads_inactivos(
            request=req,
            search="Juan",
            estado_id=5,
            limit=50,
            offset=0,
            admin=mock_admin,
        )

    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["nombre_completo"] == "Juan Perez"


def test_get_leads_inactivos_stats(mock_admin):
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"total": 25},
        {"total_recientes": 10},
    ]
    cur.fetchall.return_value = [
        {"estado_id": 5, "estado_nombre": "Matricula verificada", "estado_color": "#3B82F6", "count": 2},
        {"estado_id": 1, "estado_nombre": "Nuevo", "estado_color": "#10B981", "count": 23},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.leads_inactivos.get_db", return_value=db_cm):
        stats = get_leads_inactivos_stats(admin=mock_admin)

    assert stats["total"] == 25
    assert stats["total_recientes"] == 10
    assert len(stats["por_estado"]) == 2


def test_restaurar_leads_success(mock_admin):
    cur = MagicMock()
    cur.fetchall.return_value = [(10,), (11,)]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = RestaurarLeadsRequest(ids=[10, 11])

    with patch("app.routers.leads_inactivos.get_db", return_value=db_cm):
        res = restaurar_leads(data=req, admin=mock_admin)

    assert res["restaurados"] == 2
    assert res["ids"] == [10, 11]


def test_cambiar_estado_lead_inactivo(mock_admin):
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 1, "nombre": "Nuevo"},  # check estado exists
        {"id": 10, "estado_id": 1},    # update lead
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = CambiarEstadoRequest(estado_id=1)

    with patch("app.routers.leads_inactivos.get_db", return_value=db_cm):
        res = cambiar_estado_lead_inactivo(lead_id=10, data=req, admin=mock_admin)

    assert res["lead_id"] == 10
    assert res["estado_id"] == 1


def test_bulk_cambiar_estado_leads_inactivos(mock_admin):
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 1, "nombre": "Nuevo"}  # check estado exists
    cur.fetchall.return_value = [(10,), (11,)]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = BulkCambiarEstadoRequest(ids=[10, 11], estado_id=1)

    with patch("app.routers.leads_inactivos.get_db", return_value=db_cm):
        res = bulk_cambiar_estado_leads_inactivos(data=req, admin=mock_admin)

    assert res["actualizados"] == 2


def test_eliminar_leads_permanente(mock_admin):
    cur = MagicMock()
    cur.fetchall.return_value = [(10,)]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = EliminarPermanenteRequest(ids=[10])

    with patch("app.routers.leads_inactivos.get_db", return_value=db_cm):
        res = eliminar_leads_permanente(data=req, admin=mock_admin)

    assert res["eliminados"] == 1

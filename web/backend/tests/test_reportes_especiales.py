"""
test_reportes_especiales.py — Tests unitarios para el router de Reportería Especial.
"""
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException

from app.auth.schemas import TokenData
from app.constants import Role
from app.routers.reportes_especiales import (
    get_supervisores_disponibles,
    get_resumen_leads_historicos_supervisor,
    get_detalle_leads_historicos_supervisor,
    _check_access,
)


@pytest.fixture
def admin_user():
    return TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@test.com",
        role=Role.ADMIN,
        is_active=True,
    )


@pytest.fixture
def supervisor_user():
    return TokenData(
        user_id="00000000-0000-0000-0000-000000000002",
        email="supervisor@test.com",
        role=Role.SUPERVISOR,
        is_active=True,
    )


@pytest.fixture
def asesor_user():
    return TokenData(
        user_id="00000000-0000-0000-0000-000000000003",
        email="asesor@test.com",
        role=Role.ASESOR,
        is_active=True,
    )


def test_check_access_supervisor_forbidden(supervisor_user):
    with pytest.raises(HTTPException) as exc_info:
        _check_access(supervisor_user)
    assert exc_info.value.status_code == 403


def test_check_access_asesor_forbidden(asesor_user):
    with pytest.raises(HTTPException) as exc_info:
        _check_access(asesor_user)
    assert exc_info.value.status_code == 403


def test_check_access_admin_allowed(admin_user):
    # Does not raise
    _check_access(admin_user)


def test_get_supervisores_disponibles_admin(admin_user):
    cur = MagicMock()
    cur.fetchall.return_value = [
        {"id": "00000000-0000-0000-0000-000000000002", "nombre": "Supervisor 1", "asesores_activos": 3},
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.reportes_especiales.get_db", return_value=db_cm):
        res = get_supervisores_disponibles(current_user=admin_user)
        assert len(res) == 1
        assert res[0]["nombre"] == "Supervisor 1"


def test_resumen_leads_historicos_supervisor_structure(admin_user):
    cur = MagicMock()
    # 1. allowed IDs
    # 2. sup_info
    # 3. KPIs
    # 4. fuentes
    # 5. origenes
    # 6. ubicacion
    # 7. asesores_equipo
    # 8. estados
    cur.fetchall.side_effect = [
        [{"id": "00000000-0000-0000-0000-000000000002"}],  # allowed IDs
        [{"id": 1, "nombre": "Meta", "total": 10}],  # fuentes
        [{"nombre": "Campaña Verano", "total": 10}],  # origenes
        [{"tipo_ubicacion": "bolsa_tmk", "ubicacion_label": "Bolsa TMK", "total": 4}],  # ubicacion
        [{"id": "asesor-1", "nombre": "Carlos", "total": 6}],  # asesores_equipo
        [{"id": 1, "nombre": "Nuevo", "color_hex": "#3b82f6", "total": 10}],  # estados
    ]
    cur.fetchone.side_effect = [
        {"id": "00000000-0000-0000-0000-000000000002", "nombre": "Supervisor Prueba", "email": "sup@test.com"},  # sup_info
        {
            "total_recibidos": 10,
            "en_equipo_actual": 6,
            "en_bolsa_tmk": 4,
            "reasignados_otro_equipo": 0,
            "en_cola": 0,
            "inactivos": 0,
            "matriculados": 2,
            "perdidos": 1,
        },  # KPIs
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.reportes_especiales.get_db", return_value=db_cm):
        res = get_resumen_leads_historicos_supervisor(
            supervisor_id="00000000-0000-0000-0000-000000000002",
            current_user=admin_user,
        )
        assert res["kpis"]["total_recibidos"] == 10
        assert res["kpis"]["en_bolsa_tmk"] == 4
        assert len(res["desglose_fuentes"]) == 1
        assert len(res["desglose_ubicacion"]) == 1
        assert res["desglose_ubicacion"][0]["key"] == "bolsa_tmk"

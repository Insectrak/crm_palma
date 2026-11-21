"""
test_agenda_role_scoping.py — Tests de control de acceso y visibilidad en Agenda.

Reglas:
1. Admin o permiso data.view_all / agenda.view_all -> ve todas las citas globales.
2. Supervisor por defecto (sin switch view_all) -> ve ÚNICAMENTE las citas de su equipo.
3. Asesor sin permiso view_all -> ve solo sus citas propias.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.auth.schemas import TokenData
from app.routers.agenda import _role_filter_contactos, get_citas


def test_supervisor_default_sees_only_team_appointments():
    """Un supervisor sin agenda.view_all ni data.view_all solo debe ver citas de su equipo."""
    sup_user = TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="supervisor@test.local",
        role="supervisor",
        permissions={},
    )
    clause, params = _role_filter_contactos(sup_user)
    assert clause != ""
    assert "crm.equipos" in clause
    assert "c.asesor_id" in clause
    assert sup_user.user_id in params


def test_supervisor_with_data_view_all_sees_all_appointments():
    """Un supervisor con permiso maestro data.view_all ve todas las citas globales."""
    sup_all_user = TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="supervisor_all@test.local",
        role="supervisor",
        permissions={"data.view_all": True},
    )
    clause, params = _role_filter_contactos(sup_all_user)
    assert clause == ""
    assert params == []


def test_supervisor_with_agenda_view_all_sees_all_appointments():
    """Un supervisor con permiso específico agenda.view_all ve todas las citas globales."""
    sup_agenda_all_user = TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="supervisor_agenda@test.local",
        role="supervisor",
        permissions={"agenda.view_all": True},
    )
    clause, params = _role_filter_contactos(sup_agenda_all_user)
    assert clause == ""
    assert params == []


def test_admin_sees_all_appointments():
    """El rol admin siempre ve todas las citas globales."""
    admin_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@test.local",
        role="admin",
        permissions={},
    )
    clause, params = _role_filter_contactos(admin_user)
    assert clause == ""
    assert params == []

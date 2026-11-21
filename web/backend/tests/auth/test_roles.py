"""
Tests del endpoint PATCH /auth/users/{user_id}/role.

Cubre escenarios de cambio de rol:
  - Admin cambia rol de un user existente -> 200.
  - No-admin (supervisor) NO puede cambiar roles (escalation blocked) -> 403.
  - No-admin (asesor) tampoco -> 403.
  - Rol invalido (ej: "superuser") -> 400.
  - User_id inexistente -> 404.

Por que importan estos tests:
El endpoint PATCH /role es la unica puerta para que alguien suba a admin.
Si alguien que NO es admin pudiera llamar este endpoint, escalaria
privilegios y podria volverse admin. Estos tests previenen ese vector.
"""
import pytest

from tests.fixtures import fake_db_returning


ROLE_PATH = "/auth/users/00000000-0000-0000-0000-000000000099/role"


@pytest.mark.auth
@pytest.mark.unit
def test_change_role_as_admin_succeeds(client, auth_headers_admin, monkeypatch):
    # Arrange — el endpoint ahora consulta el estado previo (email + role)
    # para el audit log. El test debe proveer ese row antes del UPDATE.
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"email": "u99@palma.test", "role": "asesor"},  # SELECT previo
            {"id": "00000000-0000-0000-0000-000000000099"},  # respaldo
        ),
    )

    # Act — admin promueve asesor a supervisor
    response = client.patch(
        ROLE_PATH,
        headers=auth_headers_admin,
        json={"role": "supervisor"},
    )

    # Assert
    assert response.status_code == 200
    assert "supervisor" in response.json()["message"]


@pytest.mark.auth
@pytest.mark.unit
def test_change_role_as_supervisor_is_forbidden(
    client, auth_headers_supervisor,
):
    """Escalation block: un supervisor NO puede promover a otro a admin
    (ni a si mismo). Solo admins pueden mover roles."""
    # Act
    response = client.patch(
        ROLE_PATH,
        headers=auth_headers_supervisor,
        json={"role": "admin"},
    )

    # Assert — require_admin guard rechaza ANTES de procesar el body
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_change_role_as_asesor_is_forbidden(client, auth_headers_asesor):
    """Mismo guard que supervisor: asesor tampoco puede tocar roles."""
    # Act
    response = client.patch(
        ROLE_PATH,
        headers=auth_headers_asesor,
        json={"role": "admin"},
    )

    # Assert
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_change_role_with_invalid_role_returns_400(
    client, auth_headers_admin,
):
    """El router valida la lista cerrada de roles: admin/supervisor/asesor."""
    # Act
    response = client.patch(
        ROLE_PATH,
        headers=auth_headers_admin,
        json={"role": "superuser"},
    )

    # Assert
    assert response.status_code == 400
    assert "inv" in response.json()["detail"].lower()  # "Rol inválido"

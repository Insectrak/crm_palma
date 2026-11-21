"""
Tests del endpoint PATCH /auth/users/{user_id}.

Cubre:
  - Admin actualiza un campo simple (first_name) -> 200.
  - No-admin (asesor) recibe 403 (require_admin guard).
  - Sin token recibe 401.
  - Body vacio (sin campos) -> 400 'Sin campos a actualizar'.
  - User_id inexistente -> 404.

NO cubre todavia (sesion futura):
  - POST /auth/users (crear)
  - DELETE /auth/users/{id}
  - Validacion del schema Pydantic en email mal formado (Pydantic v2 lo
    hace automatico, no es responsabilidad del router).
"""
import pytest

from tests.fixtures import fake_db_returning


PATCH_PATH = "/auth/users/00000000-0000-0000-0000-000000000099"


@pytest.mark.auth
@pytest.mark.unit
def test_update_user_as_admin_updates_first_name(
    client, auth_headers_admin, monkeypatch,
):
    # Arrange — el UPDATE devuelve el ID via RETURNING (1 fila)
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({"id": "00000000-0000-0000-0000-000000000099"}),
    )

    # Act
    response = client.patch(
        PATCH_PATH,
        headers=auth_headers_admin,
        json={"first_name": "NuevoNombre"},
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == {"message": "Usuario actualizado"}


@pytest.mark.auth
@pytest.mark.unit
def test_update_user_as_asesor_returns_403(
    client, auth_headers_asesor,
):
    """require_admin guard: asesor NO puede tocar usuarios."""
    # Act
    response = client.patch(
        PATCH_PATH,
        headers=auth_headers_asesor,
        json={"first_name": "Cualquiera"},
    )

    # Assert
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_update_user_without_token_returns_401(client):
    # Act
    response = client.patch(PATCH_PATH, json={"first_name": "X"})

    # Assert
    assert response.status_code == 401


@pytest.mark.auth
@pytest.mark.unit
def test_update_user_with_empty_body_returns_400(
    client, auth_headers_admin,
):
    """Si admin manda PATCH sin campos validos, router rechaza con 400
    en vez de hacer un UPDATE vacio."""
    # Act — body con solo strings vacios (que el router filtra)
    response = client.patch(
        PATCH_PATH,
        headers=auth_headers_admin,
        json={"first_name": "", "last_name": ""},
    )

    # Assert
    assert response.status_code == 400
    assert response.json()["detail"] == "Sin campos a actualizar"


@pytest.mark.auth
@pytest.mark.unit
def test_update_user_with_nonexistent_id_returns_404(
    client, auth_headers_admin, monkeypatch,
):
    # Arrange — UPDATE ... RETURNING id NO devuelve fila (user no existe)
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(None),
    )

    # Act
    response = client.patch(
        PATCH_PATH,
        headers=auth_headers_admin,
        json={"first_name": "Algo"},
    )

    # Assert
    assert response.status_code == 404
    assert response.json()["detail"] == "Usuario no encontrado"

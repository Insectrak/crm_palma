"""
Tests del endpoint GET /auth/me.

Cubre:
  - Sin Authorization header devuelve 403 (FastAPI HTTPBearer default).
  - Con token invalido devuelve 401.
  - Con token valido devuelve datos del usuario logueado.

Nota: /auth/me usa Depends(get_current_user) que decodifica el JWT y
busca al user en DB. Si el usuario fue borrado pero el token sigue
vivo, devuelve 404.
"""
import pytest

from tests.fixtures import make_user


@pytest.mark.auth
@pytest.mark.unit
def test_me_without_token_returns_401(client):
    # Arrange — sin headers de auth

    # Act
    response = client.get("/auth/me")

    # Assert — sin Authorization header, FastAPI HTTPBearer devuelve 401
    # ("Not authenticated"). Esto es lo correcto semanticamente: 401 = "te
    # falta autenticarte"; 403 seria si tuvieras auth pero te faltara permiso.
    assert response.status_code == 401


@pytest.mark.auth
@pytest.mark.unit
def test_me_with_invalid_token_returns_401(client):
    # Arrange
    headers = {"Authorization": "Bearer este-token-es-basura"}

    # Act
    response = client.get("/auth/me", headers=headers)

    # Assert
    assert response.status_code == 401
    assert "inv" in response.json()["detail"].lower()  # "Token inválido o expirado"


@pytest.mark.auth
@pytest.mark.unit
def test_me_with_valid_token_returns_user_data(
    client, auth_headers_admin, monkeypatch,
):
    # Arrange — mockeamos la query del router que busca al user por id
    from tests.fixtures import fake_db_returning

    user = make_user(
        role="admin",
        email="admin@test.local",
        first_name="Admin",
        last_name="Test",
    )
    # /auth/me hace JOIN con wa_numbers, agregamos los campos esperados
    user["default_wa_number_name"] = None
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))

    # Act
    response = client.get("/auth/me", headers=auth_headers_admin)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@test.local"
    assert body["role"] == "admin"
    assert body["first_name"] == "Admin"
    assert body["is_active"] is True

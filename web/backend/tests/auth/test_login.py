"""
Tests del endpoint POST /auth/login.

Cubre:
  - Login exitoso devuelve token + datos del usuario.
  - Email inexistente devuelve 401 con mensaje generico (anti enumeration).
  - Password incorrecto devuelve 401 con MISMO mensaje (anti enumeration).
  - Usuario desactivado devuelve 403 con mensaje claro.

NO cubre (estos van en otro test):
  - Rate limiting (10/min) — necesita test integration
  - Bloqueo por intentos fallidos (no esta implementado en este router)
"""
import pytest

from tests.fixtures import make_user


@pytest.mark.auth
@pytest.mark.unit
def test_login_with_valid_credentials_returns_token(
    client, mock_user_in_db, patch_bcrypt, disable_rate_limit,
):
    # Arrange
    user = make_user(email="ana@palma.com", role="admin", first_name="Ana", last_name="Montes")
    mock_user_in_db(user)
    patch_bcrypt(returns=True)

    # Act
    response = client.post("/auth/login", json={
        "email": "ana@palma.com",
        "password": "supersecret",
    })

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]                # token presente
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"
    assert body["email"] == "ana@palma.com"
    assert body["nombre_completo"] == "Ana Montes"


@pytest.mark.auth
@pytest.mark.unit
def test_login_with_nonexistent_email_returns_401_generic(
    client, mock_user_in_db, disable_rate_limit,
):
    """Anti-enumeration: mismo mensaje que password incorrecto, no revelar
    si el email existe."""
    # Arrange
    mock_user_in_db(None)  # ningun user matchea

    # Act
    response = client.post("/auth/login", json={
        "email": "noexiste@palma.com",
        "password": "lo-que-sea",
    })

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales incorrectas"


@pytest.mark.auth
@pytest.mark.unit
def test_login_with_wrong_password_returns_401_generic(
    client, mock_user_in_db, patch_bcrypt, disable_rate_limit,
):
    """Anti-enumeration: mismo mensaje que email inexistente."""
    # Arrange
    user = make_user(email="ana@palma.com")
    mock_user_in_db(user)
    patch_bcrypt(returns=False)  # bcrypt rechaza el password

    # Act
    response = client.post("/auth/login", json={
        "email": "ana@palma.com",
        "password": "incorrecto",
    })

    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales incorrectas"


@pytest.mark.auth
@pytest.mark.unit
def test_login_with_inactive_user_returns_403_clear_message(
    client, mock_user_in_db, disable_rate_limit,
):
    """Usuario desactivado debe recibir mensaje EXPLICITO (no enumeration aqui
    porque el endpoint solo llega a este check si el email matcheo)."""
    # Arrange
    user = make_user(email="ana@palma.com", is_active=False)
    mock_user_in_db(user)

    # Act
    response = client.post("/auth/login", json={
        "email": "ana@palma.com",
        "password": "supersecret",
    })

    # Assert
    assert response.status_code == 403
    assert "desactivado" in response.json()["detail"].lower()
    assert "administrador" in response.json()["detail"].lower()

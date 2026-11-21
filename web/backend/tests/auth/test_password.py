"""
Tests de gestion de password:
  - POST /auth/change-password: user logueado cambia su pass.
  - POST /auth/users/{id}/reset-link: admin genera token de 24h.
  - POST /auth/reset-password: usuario usa token publico para resetear.
"""
import pytest

from tests.fixtures import fake_db_returning, make_user


@pytest.mark.auth
@pytest.mark.unit
def test_change_password_with_correct_current_pass_succeeds(
    client, auth_headers_admin, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    # Arrange — SELECT password_hash devuelve el user con su hash placeholder
    user = make_user(role="admin")
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(user),
    )
    patch_bcrypt(returns=True)  # current password matchea

    # Act
    response = client.post(
        "/auth/change-password",
        headers=auth_headers_admin,
        json={"current_password": "vieja", "new_password": "nuevasupersecret"},
    )

    # Assert
    assert response.status_code == 200
    assert "actualizada" in response.json()["message"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_change_password_with_wrong_current_pass_returns_400(
    client, auth_headers_admin, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """Si la pass actual no matchea, devuelve 400 con mensaje claro."""
    user = make_user(role="admin")
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))
    patch_bcrypt(returns=False)  # current password incorrecto

    response = client.post(
        "/auth/change-password",
        headers=auth_headers_admin,
        json={"current_password": "incorrecta", "new_password": "nuevasupersecret"},
    )
    assert response.status_code == 400
    assert "actual" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_change_password_with_weak_new_pass_returns_400(
    client, auth_headers_admin, disable_rate_limit,
):
    """Nueva password debe ser >=6 chars."""
    response = client.post(
        "/auth/change-password",
        headers=auth_headers_admin,
        json={"current_password": "vieja", "new_password": "abc"},
    )
    assert response.status_code == 400
    assert "6 caracteres" in response.json()["detail"]


@pytest.mark.auth
@pytest.mark.unit
def test_change_password_without_token_returns_401(client, disable_rate_limit):
    response = client.post(
        "/auth/change-password",
        json={"current_password": "x", "new_password": "supersecret"},
    )
    assert response.status_code == 401


@pytest.mark.auth
@pytest.mark.unit
def test_reset_link_as_admin_returns_token(client, auth_headers_admin, monkeypatch):
    """Admin pide reset-link para un user -> devuelve token urlsafe."""
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": user_id},   # SELECT user (existe)
            None,              # INSERT password_resets
        ),
    )

    response = client.post(
        f"/auth/users/{user_id}/reset-link",
        headers=auth_headers_admin,
    )

    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert len(body["token"]) > 20  # secrets.token_urlsafe(32) genera ~43 chars


@pytest.mark.auth
@pytest.mark.unit
def test_reset_link_for_nonexistent_user_returns_404(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(None))

    response = client.post(
        "/auth/users/00000000-0000-0000-0000-000000000099/reset-link",
        headers=auth_headers_admin,
    )
    assert response.status_code == 404


@pytest.mark.auth
@pytest.mark.unit
def test_reset_password_with_weak_password_returns_400(client, disable_rate_limit):
    """Endpoint publico: pass debe ser >=6 chars antes de validar token."""
    response = client.post("/auth/reset-password", json={
        "token": "cualquier",
        "new_password": "abc",
    })
    assert response.status_code == 400


@pytest.mark.auth
@pytest.mark.unit
def test_reset_password_with_invalid_token_returns_400(
    client, monkeypatch, disable_rate_limit,
):
    """Token no encontrado, ya usado o expirado."""
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(None))

    response = client.post("/auth/reset-password", json={
        "token": "token-falso",
        "new_password": "supersecret",
    })
    assert response.status_code == 400
    assert "token" in response.json()["detail"].lower()

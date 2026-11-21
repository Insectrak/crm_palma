"""
Tests del flujo de invitacion: POST /auth/invite, GET /auth/invitations,
DELETE /auth/invitations/{id}, GET /auth/invite/{token}, POST /auth/accept-invite.

Cubre:
  - POST /invite: admin OK, no-admin 403, rol invalido 400, email malformado 400.
  - GET /invitations: admin lista, no-admin 403.
  - DELETE /invitations/{id}: admin OK, no encontrada 404.
  - GET /invite/{token}: token valido devuelve email+role, token expirado 404.
  - POST /accept-invite: OK, password debil 400, token invalido 400, email ya existe 409.
"""
import pytest

from tests.fixtures import fake_db_returning


@pytest.mark.auth
@pytest.mark.unit
def test_invite_as_admin_creates_invitation(client, auth_headers_admin, monkeypatch):
    """Happy path: admin invita a un email nuevo. Email service mockeado a True."""
    # Arrange
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(
        None,                                        # CREATE TABLE IF NOT EXISTS (no fetch)
        None,                                        # DELETE prev invitations
        None,                                        # INSERT new invitation
        {"first_name": "Admin", "last_name": "Test"},  # SELECT name del admin
    ))
    monkeypatch.setattr(
        "app.services.email_service.send_invitation_email",
        lambda **kwargs: True,
    )

    # Act
    response = client.post(
        "/auth/invite",
        headers=auth_headers_admin,
        json={"email": "nuevo@palma.com", "role": "asesor"},
    )

    # Assert
    assert response.status_code == 201
    body = response.json()
    assert body["invite_email"] == "nuevo@palma.com"
    assert body["email_sent"] is True
    assert "invite_url" in body
    assert "token=" in body["invite_url"]


@pytest.mark.auth
@pytest.mark.unit
def test_invite_as_asesor_returns_403(client, auth_headers_asesor):
    """require_admin guard."""
    response = client.post(
        "/auth/invite",
        headers=auth_headers_asesor,
        json={"email": "x@y.com", "role": "asesor"},
    )
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_invite_with_invalid_role_returns_400(client, auth_headers_admin):
    """Lista cerrada: admin/supervisor/asesor. 'superuser' debe rechazar."""
    response = client.post(
        "/auth/invite",
        headers=auth_headers_admin,
        json={"email": "x@y.com", "role": "superuser"},
    )
    assert response.status_code == 400
    assert "inv" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_invite_with_malformed_email_returns_400(client, auth_headers_admin):
    """Sin @ en el email (validacion liviana del router)."""
    response = client.post(
        "/auth/invite",
        headers=auth_headers_admin,
        json={"email": "no-es-email", "role": "asesor"},
    )
    assert response.status_code == 400


@pytest.mark.auth
@pytest.mark.unit
def test_list_invitations_as_asesor_returns_403(client, auth_headers_asesor):
    response = client.get("/auth/invitations", headers=auth_headers_asesor)
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_cancel_invitation_as_admin_succeeds(client, auth_headers_admin, monkeypatch):
    # Arrange — DELETE ... RETURNING id devuelve la fila
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({"id": 1}),
    )

    # Act
    response = client.delete("/auth/invitations/1", headers=auth_headers_admin)

    # Assert
    assert response.status_code == 200
    assert "cancelada" in response.json()["message"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_cancel_invitation_not_found_returns_404(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(None),
    )

    response = client.delete("/auth/invitations/999", headers=auth_headers_admin)
    assert response.status_code == 404


@pytest.mark.auth
@pytest.mark.unit
def test_verify_invite_token_with_invalid_token_returns_404(
    client, monkeypatch,
):
    """Token que no matchea ningun registro (o expiro)."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(None),
    )

    response = client.get("/auth/invite/token-falso-xxxxx")
    assert response.status_code == 404


@pytest.mark.auth
@pytest.mark.unit
def test_verify_invite_token_with_valid_token_returns_email_role(
    client, monkeypatch,
):
    """Token vivo devuelve email + rol que el frontend usa para pre-llenar el form."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({"email": "nuevo@palma.com", "role": "asesor"}),
    )

    response = client.get("/auth/invite/token-valido-xxxxx")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "nuevo@palma.com"
    assert body["role"] == "asesor"


@pytest.mark.auth
@pytest.mark.unit
def test_accept_invite_with_weak_password_returns_400(client):
    """Password <6 chars rechazado antes de tocar DB."""
    response = client.post("/auth/accept-invite", json={
        "token": "cualquier-token",
        "password": "12345",   # 5 chars
        "nombre_completo": "Test User",
    })
    assert response.status_code == 400
    assert "6 caracteres" in response.json()["detail"]


@pytest.mark.auth
@pytest.mark.unit
def test_accept_invite_with_invalid_token_returns_400(client, monkeypatch):
    """Token no encontrado o expirado."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(None),
    )

    response = client.post("/auth/accept-invite", json={
        "token": "token-falso",
        "password": "supersecret",
        "nombre_completo": "Test User",
    })
    assert response.status_code == 400
    assert "invitación" in response.json()["detail"].lower() or "invitacion" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_accept_invite_with_existing_email_returns_409(client, monkeypatch):
    """Token valido pero el email ya tiene cuenta -> 409 conflict."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": 1, "email": "ya-existe@palma.com", "role": "asesor"},   # invitation valida
            {"id": "uuid-existente"},                                         # user ya existe
        ),
    )

    response = client.post("/auth/accept-invite", json={
        "token": "token-valido",
        "password": "supersecret",
        "nombre_completo": "Test User",
    })
    assert response.status_code == 409

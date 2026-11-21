"""
Tests del endpoint GET /auth/me/permissions (Live Permission Refresh — ADR-0011).

Cubre:
- Sin Authorization header devuelve 401.
- Con token invalido devuelve 401.
- Con token valido devuelve permisos actuales del rol leyendo DB (no JWT).
- Usuario eliminado entre login y refresh: 401.
- Usuario desactivado entre login y refresh: 401.
- Rol con `permissions` cambiado por admin: refresh devuelve los NUEVOS permisos
  (no los del snapshot del JWT) — es lo que hace este endpoint valioso.
- Usuario sin role_id (legacy) devuelve permissions = {} sin romperse.

El JWT del fixture tiene `permissions = {}` por defecto. El endpoint NO usa
los permisos del JWT — siempre va a DB. Por eso los tests configuran el mock
de DB con las permissions "actuales" del rol.
"""
import pytest

from tests.fixtures import fake_db_returning


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_without_token_returns_401(client):
    response = client.get("/auth/me/permissions")
    assert response.status_code == 401


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_with_invalid_token_returns_401(client):
    response = client.get(
        "/auth/me/permissions",
        headers={"Authorization": "Bearer este-token-es-basura"},
    )
    assert response.status_code == 401


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_returns_fresh_snapshot_from_db(
    client, auth_headers_asesor, monkeypatch,
):
    # Arrange: el usuario "asesor" en DB ahora tiene un role_id custom con
    # `usuarios.manage` activado. Aunque el JWT del fixture no trae permisos,
    # el endpoint los lee del JOIN con auth.roles.
    db_row = {
        "email": "asesor@test.local",
        "role": "asesor",  # rol legacy text — no cambia por el role custom
        "is_active": True,
        "api_client_id": None,
        "role_id": 5,
        "role_name": "marketing_proveedor",
        "role_permissions": {"usuarios.manage": True, "integraciones.manage": True},
        "role_is_external": False,
    }
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(db_row))

    # Act
    response = client.get("/auth/me/permissions", headers=auth_headers_asesor)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "asesor"
    assert body["role_id"] == 5
    assert body["role_name"] == "marketing_proveedor"
    assert body["permissions"] == {"usuarios.manage": True, "integraciones.manage": True}
    assert body["role_is_external"] is False
    assert body["api_client_id"] is None
    # CRITICAL: el endpoint debe devolver un access_token fresco para que
    # el cliente lo reemplace en storage. Sin esto, las proximas requests
    # backend usarian el JWT viejo con permisos stale.
    assert body.get("access_token"), "Falta access_token en la respuesta"
    assert isinstance(body["access_token"], str)
    assert len(body["access_token"]) > 20  # JWT mas o menos serio


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_new_token_embeds_fresh_permissions(
    client, auth_headers_asesor, monkeypatch,
):
    """El JWT devuelto debe tener los permisos NUEVOS embebidos, no los
    del JWT entrante. Es lo que hace que la proxima request al backend
    use el snapshot fresco para chequeos de check_permission/FLS."""
    db_row = {
        "email": "asesor@test.local",
        "role": "asesor",
        "is_active": True,
        "api_client_id": None,
        "role_id": 5,
        "role_name": "marketing_proveedor",
        "role_permissions": {
            "leads.view": True,
            "field.leads.telefono.read": False,
        },
        "role_is_external": False,
    }
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(db_row))

    response = client.get("/auth/me/permissions", headers=auth_headers_asesor)
    assert response.status_code == 200

    # Decodificar el JWT devuelto y verificar que tiene los permisos frescos.
    from app.auth.jwt import verify_token
    new_token = response.json()["access_token"]
    payload = verify_token(new_token)
    assert payload.permissions.get("leads.view") is True
    assert payload.permissions.get("field.leads.telefono.read") is False
    assert payload.role_id == 5


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_reflects_revoked_permission(
    client, auth_headers_asesor, monkeypatch,
):
    # Arrange: el admin acaba de quitar usuarios.manage del rol custom del
    # usuario. El JWT lo trae como activo, pero la DB no. El endpoint debe
    # devolver el estado actual de DB (sin usuarios.manage).
    db_row = {
        "role": "asesor",
        "is_active": True,
        "api_client_id": None,
        "role_id": 5,
        "role_name": "marketing_proveedor",
        "role_permissions": {"integraciones.manage": True},  # usuarios.manage removido
        "role_is_external": False,
    }
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(db_row))

    response = client.get("/auth/me/permissions", headers=auth_headers_asesor)

    assert response.status_code == 200
    body = response.json()
    assert body["permissions"].get("usuarios.manage") is None
    assert body["permissions"]["integraciones.manage"] is True


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_user_deleted_returns_401(
    client, auth_headers_asesor, monkeypatch,
):
    # Arrange: el usuario fue eliminado de DB entre login y refresh.
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(None))

    response = client.get("/auth/me/permissions", headers=auth_headers_asesor)

    # Assert: 401 para que el cliente fuerce logout
    assert response.status_code == 401
    assert "sesion" in response.json()["detail"].lower() or "encontrado" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_user_deactivated_returns_401(
    client, auth_headers_asesor, monkeypatch,
):
    # Arrange: el admin desactivo al usuario.
    db_row = {
        "role": "asesor",
        "is_active": False,
        "api_client_id": None,
        "role_id": None,
        "role_name": None,
        "role_permissions": None,
        "role_is_external": False,
    }
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(db_row))

    response = client.get("/auth/me/permissions", headers=auth_headers_asesor)

    assert response.status_code == 401
    assert "desactivado" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_legacy_user_without_role_id(
    client, auth_headers_supervisor, monkeypatch,
):
    # Arrange: usuario legacy sin role_id custom asignado (Paola/Darwin tipico).
    # El LEFT JOIN devuelve NULL en los campos del rol.
    db_row = {
        "role": "supervisor",
        "is_active": True,
        "api_client_id": None,
        "role_id": None,
        "role_name": None,
        "role_permissions": None,
        "role_is_external": False,
    }
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(db_row))

    response = client.get("/auth/me/permissions", headers=auth_headers_supervisor)

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "supervisor"
    assert body["role_id"] is None
    assert body["role_name"] is None
    assert body["permissions"] == {}  # NULL en DB -> {} en respuesta


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_external_provider_role(
    client, auth_headers_asesor, monkeypatch,
):
    # Arrange: rol externo (proveedor) con api_client_id.
    db_row = {
        "role": "asesor",
        "is_active": True,
        "api_client_id": "11111111-2222-3333-4444-555555555555",
        "role_id": 7,
        "role_name": "proveedor_externo",
        "role_permissions": {"leads.view": True},
        "role_is_external": True,
    }
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(db_row))

    response = client.get("/auth/me/permissions", headers=auth_headers_asesor)

    assert response.status_code == 200
    body = response.json()
    assert body["role_is_external"] is True
    assert body["api_client_id"] == "11111111-2222-3333-4444-555555555555"
    assert body["permissions"] == {"leads.view": True}

"""
Tests V088 — control de acceso y soft-disable de usuarios.

Bug origen: un admin asignó un rol custom "Sin Acceso" (permissions={}) a
un asesor pensando que lo desactivaría. El rol custom no tocó el role
legacy ni is_active, así que el asesor seguía viendo módulos en la UI
(fallback legacy) y aparecía en listas de supervisores. V088 cierra ese
gap por tres frentes:

  - Login bloquea cuentas sin acceso efectivo.
  - Endpoint dedicado PATCH /auth/users/{id}/active para soft-disable.
  - Audit log + sesiones invalidadas al deshabilitar.
"""
import pytest

from tests.fixtures import fake_db_returning, make_user


# ── Login: bloqueo de cuenta sin acceso efectivo ─────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_login_blocks_user_with_custom_role_and_empty_permissions(
    client, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """Bug ID: V088 sin_acceso_role_bypass

    Asesor con role_id de un rol custom con permissions={} debe ser
    bloqueado al loguearse, no entrar a una UI inútil.
    """
    user = make_user(role="asesor")
    user["role_id"] = 42
    user["role_permissions"] = {}  # Rol custom "Sin Acceso"
    user["role_is_external"] = False
    user["api_client_id"] = None
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))
    patch_bcrypt(returns=True)

    response = client.post("/auth/login", json={
        "email": "user@palma.test", "password": "any",
    })

    assert response.status_code == 403
    assert "no tiene acceso" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_login_allows_user_with_custom_role_and_at_least_one_permission(
    client, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """Si el rol custom tiene aunque sea un permiso = true, el login pasa."""
    user = make_user(role="asesor")
    user["role_id"] = 42
    user["role_permissions"] = {"leads.view": True}
    user["role_is_external"] = False
    user["api_client_id"] = None
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))
    patch_bcrypt(returns=True)

    response = client.post("/auth/login", json={
        "email": "user@palma.test", "password": "any",
    })
    assert response.status_code == 200


@pytest.mark.auth
@pytest.mark.unit
def test_login_allows_admin_even_with_empty_perms(
    client, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """El admin legacy entra siempre — su acceso no depende del rol custom."""
    user = make_user(role="admin")
    user["role_id"] = 42
    user["role_permissions"] = {}
    user["role_is_external"] = False
    user["api_client_id"] = None
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))
    patch_bcrypt(returns=True)

    response = client.post("/auth/login", json={
        "email": "admin@palma.test", "password": "any",
    })
    assert response.status_code == 200


@pytest.mark.auth
@pytest.mark.unit
def test_login_allows_user_without_custom_role(
    client, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """Usuario legacy sin role_id mantiene el comportamiento previo —
    no se aplica el bloqueo V088."""
    user = make_user(role="asesor")
    user["role_id"] = None
    user["role_permissions"] = None
    user["role_is_external"] = False
    user["api_client_id"] = None
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))
    patch_bcrypt(returns=True)

    response = client.post("/auth/login", json={
        "email": "user@palma.test", "password": "any",
    })
    assert response.status_code == 200


# ── PATCH /auth/users/{id}/active — soft-disable ─────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_deactivate_user_as_admin_succeeds(client, auth_headers_admin, monkeypatch):
    """Admin deshabilita un usuario activo → 200 + mensaje claro."""
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": user_id, "email": "diego@palma.test", "is_active": True},
            None,  # UPDATE is_active
            None,  # DELETE user_sessions
        ),
    )
    # Stub el audit para que no toque DB real.
    monkeypatch.setattr(
        "app.services.permission_audit_service.record_user_active_change",
        lambda **kwargs: None,
    )

    response = client.patch(
        f"/auth/users/{user_id}/active",
        headers=auth_headers_admin,
        json={"is_active": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert "deshabilitado" in body["message"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_reactivate_user_as_admin_succeeds(client, auth_headers_admin, monkeypatch):
    """Re-habilitar un usuario deshabilitado → mensaje simétrico."""
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": user_id, "email": "diego@palma.test", "is_active": False},
            None,
        ),
    )
    monkeypatch.setattr(
        "app.services.permission_audit_service.record_user_active_change",
        lambda **kwargs: None,
    )

    response = client.patch(
        f"/auth/users/{user_id}/active",
        headers=auth_headers_admin,
        json={"is_active": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is True
    assert "habilitado" in body["message"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_toggle_active_for_nonexistent_user_returns_404(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(None))

    response = client.patch(
        "/auth/users/00000000-0000-0000-0000-000000000099/active",
        headers=auth_headers_admin,
        json={"is_active": False},
    )
    assert response.status_code == 404


@pytest.mark.auth
@pytest.mark.unit
def test_toggle_active_as_asesor_returns_403(client, auth_headers_asesor):
    """usuarios.manage es admin-only."""
    response = client.patch(
        "/auth/users/00000000-0000-0000-0000-000000000099/active",
        headers=auth_headers_asesor,
        json={"is_active": False},
    )
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_admin_cannot_deactivate_own_user(client, auth_headers_admin):
    """Bloqueo de seguridad: el admin no puede auto-deshabilitarse
    (quedaría sin admins en el tenant)."""
    own_id = "00000000-0000-0000-0000-000000000001"  # TEST_UUID_ADMIN

    response = client.patch(
        f"/auth/users/{own_id}/active",
        headers=auth_headers_admin,
        json={"is_active": False},
    )
    assert response.status_code == 400
    assert "propio" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_toggle_active_is_idempotent_when_no_change(
    client, auth_headers_admin, monkeypatch,
):
    """Si el usuario ya está en el estado solicitado, devolvemos 200 igual
    sin tocar nada. Idempotente — el cliente no tiene que diferenciar."""
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": user_id, "email": "diego@palma.test", "is_active": False},
        ),
    )

    response = client.patch(
        f"/auth/users/{user_id}/active",
        headers=auth_headers_admin,
        json={"is_active": False},  # ya estaba deshabilitado
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

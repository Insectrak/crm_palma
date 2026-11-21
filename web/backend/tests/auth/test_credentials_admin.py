"""
Tests V087 — flujos de credenciales que ejecuta el admin sobre otro usuario:

  - POST /auth/users/{id}/send-reset-email — envia correo branded al usuario.
  - GET  /auth/users/check-email           — pre-check de duplicado de email.
  - PATCH /auth/users/{id}                  — error 409 con mensaje claro
                                              cuando el email colisiona.

Diseno: estos tests son unit + mocks (no DB real), siguen el mismo patron
de test_invite.py / test_password.py.
"""
import pytest

from tests.fixtures import fake_db_returning


# ── POST /auth/users/{id}/send-reset-email ────────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_send_reset_email_as_admin_succeeds(client, auth_headers_admin, monkeypatch):
    """Happy path: admin pide envio para un usuario activo.

    Flujo:
      1. SELECT user existente → trae email + first_name + last_name
      2. INSERT token en password_resets
      3. send_password_reset_email() retorna success=True
      4. record_send_reset_email() audita el envio (no rompe si falla)
      5. Response 200 con email_sent=True
    """
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {                                              # SELECT user existe
                "id": user_id,
                "email": "fabiola@palma.com",
                "first_name": "Fabiola",
                "last_name": "Gamero",
            },
            None,                                          # INSERT password_resets
        ),
    )
    # SMTP mockeado a OK
    monkeypatch.setattr(
        "app.services.email_service.send_password_reset_email",
        lambda **kwargs: {"success": True, "error": None},
    )
    # Audit: spy para verificar que se llamo con los argumentos correctos
    audit_calls = []
    monkeypatch.setattr(
        "app.services.password_reset_audit_service.record_send_reset_email",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    response = client.post(
        f"/auth/users/{user_id}/send-reset-email",
        headers=auth_headers_admin,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email_sent"] is True
    assert body["target_email"] == "fabiola@palma.com"
    assert "fabiola@palma.com" in body["message"]
    # Audit registrado con sent=True y sin error SMTP
    assert len(audit_calls) == 1
    assert audit_calls[0]["target_user_id"] == user_id
    assert audit_calls[0]["target_user_email"] == "fabiola@palma.com"
    assert audit_calls[0]["email_sent"] is True
    assert audit_calls[0]["smtp_error"] is None


@pytest.mark.auth
@pytest.mark.unit
def test_send_reset_email_for_nonexistent_user_returns_404(
    client, auth_headers_admin, monkeypatch,
):
    """Si el user_id no matchea ningun usuario, devuelve 404."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(None),  # SELECT no encuentra
    )

    response = client.post(
        "/auth/users/00000000-0000-0000-0000-000000000099/send-reset-email",
        headers=auth_headers_admin,
    )

    assert response.status_code == 404
    assert "no encontrado" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_send_reset_email_as_asesor_returns_403(client, auth_headers_asesor):
    """usuarios.manage es admin-only — un asesor no puede disparar resets."""
    response = client.post(
        "/auth/users/00000000-0000-0000-0000-000000000099/send-reset-email",
        headers=auth_headers_asesor,
    )
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_send_reset_email_when_smtp_fails_returns_502_and_audits_failure(
    client, auth_headers_admin, monkeypatch,
):
    """Si el SMTP falla:
      - HTTP 502 con detalle del error (admin necesita debug)
      - Audit registrado con email_sent=False + smtp_error truncado

    Bug ID: V087 send_reset_email_failure_path
    """
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {
                "id": user_id,
                "email": "fabiola@palma.com",
                "first_name": "Fabiola",
                "last_name": "Gamero",
            },
            None,
        ),
    )
    # SMTP falla con un error concreto
    monkeypatch.setattr(
        "app.services.email_service.send_password_reset_email",
        lambda **kwargs: {"success": False, "error": "SMTP relay rejected: 550 user unknown"},
    )
    audit_calls = []
    monkeypatch.setattr(
        "app.services.password_reset_audit_service.record_send_reset_email",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    response = client.post(
        f"/auth/users/{user_id}/send-reset-email",
        headers=auth_headers_admin,
    )

    assert response.status_code == 502
    assert "SMTP relay rejected" in response.json()["detail"]
    # Importante: el audit se grabo IGUAL aunque el SMTP haya fallado, asi
    # tenemos forensia de los intentos.
    assert len(audit_calls) == 1
    assert audit_calls[0]["email_sent"] is False
    assert "SMTP relay rejected" in audit_calls[0]["smtp_error"]


@pytest.mark.auth
@pytest.mark.unit
def test_send_reset_email_without_token_returns_401(client):
    """Endpoint protegido — sin Bearer token devuelve 401."""
    response = client.post(
        "/auth/users/00000000-0000-0000-0000-000000000099/send-reset-email",
    )
    assert response.status_code == 401


# ── GET /auth/users/check-email ────────────────────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_check_email_available_when_no_match(client, auth_headers_admin, monkeypatch):
    """Email libre → available=True, owner_name=None."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(None),  # SELECT no encuentra owner
    )

    response = client.get(
        "/auth/users/check-email",
        headers=auth_headers_admin,
        params={"email": "nuevo@palma.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["owner_name"] is None
    assert body["owner_email"] is None


@pytest.mark.auth
@pytest.mark.unit
def test_check_email_taken_returns_owner_name(client, auth_headers_admin, monkeypatch):
    """Email ocupado por OTRO usuario → available=False + owner_name."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({
            "id": "00000000-0000-0000-0000-000000000099",
            "nombre": "Fabiola Gamero",
            "email": "fabiola@palma.com",
        }),
    )

    response = client.get(
        "/auth/users/check-email",
        headers=auth_headers_admin,
        params={"email": "fabiola@palma.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["owner_name"] == "Fabiola Gamero"
    assert body["owner_email"] == "fabiola@palma.com"


@pytest.mark.auth
@pytest.mark.unit
def test_check_email_owned_by_self_returns_available(
    client, auth_headers_admin, monkeypatch,
):
    """Cuando se pasa exclude_user_id y el email pertenece a ese mismo user,
    el endpoint NO debe reportarlo como ocupado (UX: el admin puede dejar
    el email actual del usuario al editar)."""
    user_id = "00000000-0000-0000-0000-000000000099"
    # El SELECT con exclude_user_id no encuentra otro owner → None
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(None),
    )

    response = client.get(
        "/auth/users/check-email",
        headers=auth_headers_admin,
        params={"email": "fabiola@palma.com", "exclude_user_id": user_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True


@pytest.mark.auth
@pytest.mark.unit
def test_check_email_malformed_returns_400(client, auth_headers_admin):
    """Email sin @ o sin TLD → 400 antes de tocar DB."""
    response = client.get(
        "/auth/users/check-email",
        headers=auth_headers_admin,
        params={"email": "no-es-email"},
    )
    assert response.status_code == 400


@pytest.mark.auth
@pytest.mark.unit
def test_check_email_as_asesor_returns_403(client, auth_headers_asesor):
    """usuarios.manage es admin-only — un asesor no puede consultar."""
    response = client.get(
        "/auth/users/check-email",
        headers=auth_headers_asesor,
        params={"email": "x@y.com"},
    )
    assert response.status_code == 403


# ── PATCH /auth/users/{id} con email duplicado ─────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
@pytest.mark.regression
def test_patch_user_with_duplicate_email_returns_409_clear_message(
    client, auth_headers_admin, monkeypatch,
):
    """Bug ID: V087 patch_email_collision_was_500

    Antes de V087, el PATCH /auth/users/{id} no manejaba el caso de email
    duplicado: psycopg2 levantaba IntegrityError y FastAPI devolvia 500
    opaco. El admin no entendia por que no podia guardar.

    Ahora el pre-check encuentra el dueño y devuelve 409 con mensaje claro
    que incluye el nombre del usuario que tiene ese email.
    """
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({
            "id": "00000000-0000-0000-0000-000000000088",
            "nombre": "Carlos Ramirez",
            "email": "duplicado@palma.com",
        }),
    )

    response = client.patch(
        f"/auth/users/{user_id}",
        headers=auth_headers_admin,
        json={"email": "duplicado@palma.com"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Carlos Ramirez" in detail
    assert "ya está usado" in detail.lower() or "ya esta usado" in detail.lower()

"""
Tests V094 — bloqueo de login independiente de is_active.

Diferencia clave con V088 (soft-disable):
  - V088 `is_active=FALSE`  → bloqueado + invisible en listas operacionales
  - V094 `login_blocked=TRUE` → bloqueado + SIGUE visible en listas

Esto cubre:
  1. /auth/login rechaza con 403 si login_blocked=TRUE.
  2. /auth/login no se confunde si la columna no existe (defaults a FALSE).
  3. PATCH /auth/users/{id}/login-blocked bloquea correctamente.
  4. PATCH /auth/users/{id}/login-blocked desbloquea correctamente.
  5. Admin no puede bloquearse a si mismo.
  6. Asesor no puede usar el endpoint.
  7. Idempotencia: dos llamadas seguidas no rompen.
  8. /auth/me/permissions rechaza si admin bloqueo mientras sesion activa.
"""
import pytest

from tests.fixtures import fake_db_returning, make_user


# ── Login: bloqueo independiente de is_active ────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_login_rejects_user_with_login_blocked_true(
    client, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """Bug ID: V094 login_blocked_separation

    Usuario activo (is_active=TRUE) pero con login_blocked=TRUE no puede
    iniciar sesion. El login devuelve 403 con mensaje claro.
    """
    user = make_user(role="asesor")
    user["login_blocked"] = True
    user["role_id"] = None
    user["role_permissions"] = None
    user["role_is_external"] = False
    user["api_client_id"] = None
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))
    patch_bcrypt(returns=True)

    response = client.post("/auth/login", json={
        "email": "user@palma.test", "password": "any",
    })

    assert response.status_code == 403
    detail = response.json()["detail"].lower()
    assert "bloqueado" in detail


@pytest.mark.auth
@pytest.mark.unit
def test_login_allows_user_with_login_blocked_false(
    client, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """Caso normal: usuario activo, login_blocked=FALSE → entra sin problema."""
    user = make_user(role="asesor")
    user["login_blocked"] = False
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


@pytest.mark.auth
@pytest.mark.unit
def test_login_is_active_takes_precedence_over_login_blocked(
    client, patch_bcrypt, monkeypatch, disable_rate_limit,
):
    """Si is_active=FALSE, el mensaje es el de "desactivado" (V088), no el
    de "login bloqueado" (V094). is_active se chequea primero."""
    user = make_user(role="asesor", is_active=False)
    user["login_blocked"] = True
    user["role_id"] = None
    user["role_permissions"] = None
    user["role_is_external"] = False
    user["api_client_id"] = None
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user))
    patch_bcrypt(returns=True)

    response = client.post("/auth/login", json={
        "email": "user@palma.test", "password": "any",
    })
    assert response.status_code == 403
    assert "desactivado" in response.json()["detail"].lower()


# ── PATCH /auth/users/{id}/login-blocked ─────────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_block_login_as_admin_succeeds(client, auth_headers_admin, monkeypatch):
    """Admin bloquea el login de un usuario → 200 + mensaje claro."""
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": user_id, "email": "diego@palma.test", "login_blocked": False},
            None,  # UPDATE login_blocked
            None,  # DELETE user_sessions
        ),
    )
    monkeypatch.setattr(
        "app.services.permission_audit_service.record_user_login_blocked_change",
        lambda **kwargs: None,
    )

    response = client.patch(
        f"/auth/users/{user_id}/login-blocked",
        headers=auth_headers_admin,
        json={"login_blocked": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["login_blocked"] is True
    # Mensaje debe aclarar que el usuario SIGUE visible.
    msg = body["message"].lower()
    assert "bloqueado" in msg
    assert "visible" in msg or "listas" in msg


@pytest.mark.auth
@pytest.mark.unit
def test_unblock_login_as_admin_succeeds(client, auth_headers_admin, monkeypatch):
    """Desbloquear es simetrico — mismo endpoint con login_blocked=false."""
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": user_id, "email": "diego@palma.test", "login_blocked": True},
            None,  # UPDATE
        ),
    )
    monkeypatch.setattr(
        "app.services.permission_audit_service.record_user_login_blocked_change",
        lambda **kwargs: None,
    )

    response = client.patch(
        f"/auth/users/{user_id}/login-blocked",
        headers=auth_headers_admin,
        json={"login_blocked": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["login_blocked"] is False
    assert "desbloqueado" in body["message"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_block_login_for_nonexistent_user_returns_404(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(None))
    response = client.patch(
        "/auth/users/00000000-0000-0000-0000-000000000099/login-blocked",
        headers=auth_headers_admin,
        json={"login_blocked": True},
    )
    assert response.status_code == 404


@pytest.mark.auth
@pytest.mark.unit
def test_block_login_as_asesor_returns_403(client, auth_headers_asesor):
    """usuarios.manage es admin-only — un asesor no puede bloquear logins."""
    response = client.patch(
        "/auth/users/00000000-0000-0000-0000-000000000099/login-blocked",
        headers=auth_headers_asesor,
        json={"login_blocked": True},
    )
    assert response.status_code == 403


@pytest.mark.auth
@pytest.mark.unit
def test_admin_cannot_block_own_login(client, auth_headers_admin):
    """Defensa: el admin no puede bloquear su propio login (lockout suicida).
    Mismo patron que update_user_active."""
    own_id = "00000000-0000-0000-0000-000000000001"
    response = client.patch(
        f"/auth/users/{own_id}/login-blocked",
        headers=auth_headers_admin,
        json={"login_blocked": True},
    )
    assert response.status_code == 400
    assert "propio" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_block_login_is_idempotent(client, auth_headers_admin, monkeypatch):
    """Si el usuario ya tiene login_blocked en el estado pedido, devolvemos
    200 igual. Idempotente — el cliente no diferencia."""
    user_id = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": user_id, "email": "diego@palma.test", "login_blocked": True},
        ),
    )

    response = client.patch(
        f"/auth/users/{user_id}/login-blocked",
        headers=auth_headers_admin,
        json={"login_blocked": True},  # ya estaba bloqueado
    )
    assert response.status_code == 200
    assert response.json()["login_blocked"] is True


# ── /auth/me/permissions tambien debe rechazar ──────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_me_permissions_rejects_login_blocked_user(
    client, auth_headers_asesor, monkeypatch,
):
    """Si el admin bloqueo el login mientras el usuario tenia sesion activa,
    el siguiente refresh de permisos lo echa del cliente."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({
            "email": "asesor@palma.test",
            "role": "asesor",
            "is_active": True,
            "login_blocked": True,
            "api_client_id": None,
            "role_id": None,
            "role_name": None,
            "role_permissions": None,
            "role_is_external": False,
        }),
    )

    response = client.get("/auth/me/permissions", headers=auth_headers_asesor)
    assert response.status_code == 401
    assert "bloqueado" in response.json()["detail"].lower()


# ── V094.6 — Auto-routing salta login_blocked (patron Salesforce "Freeze") ──


@pytest.mark.unit
def test_lead_routing_team_excludes_login_blocked_asesores():
    """Bug ID: V094.6 freeze_blocks_auto_assignment

    `_get_asesores_del_equipo` debe omitir asesores con login_blocked=TRUE.
    Validamos la composicion de la SQL (no necesita DB real)."""
    import inspect
    from app.services import lead_routing
    src = inspect.getsource(lead_routing._get_asesores_del_equipo)
    assert "u.is_active = TRUE" in src
    assert "login_blocked" in src


@pytest.mark.unit
def test_lead_routing_individual_excludes_login_blocked():
    """`_es_elegible_individual` no debe declarar elegible a un asesor con
    login_blocked=TRUE — si fuera elegible, el round-robin lo elegiria."""
    import inspect
    from app.services import lead_routing
    src = inspect.getsource(lead_routing._es_elegible_individual)
    assert "login_blocked" in src


@pytest.mark.unit
def test_lead_routing_global_round_robin_excludes_login_blocked():
    """`_round_robin_global` (round-robin sin equipo) tambien debe saltar
    a los asesores con login_blocked=TRUE."""
    import inspect
    from app.services import lead_routing
    src = inspect.getsource(lead_routing._round_robin_global)
    assert "login_blocked" in src


@pytest.mark.unit
def test_next_supervisor_excludes_login_blocked():
    """`_next_supervisor` (round-robin entre supervisores en ingest_core)
    debe omitir supervisores con login_blocked=TRUE.

    Importante: mantiene los otros filtros (is_active + activo_rotacion)
    para no regresionar el comportamiento previo."""
    import inspect
    from app.services.integrations import ingest_core
    src = inspect.getsource(ingest_core._next_supervisor)
    assert "login_blocked" in src
    assert "is_active = TRUE" in src
    assert "activo_rotacion = TRUE" in src


@pytest.mark.unit
def test_asignacion_automatica_excludes_login_blocked_in_router():
    """`POST /api/leads/asignacion-automatica` filtra asesores login_blocked
    tanto para admin como para supervisor (dos paths separados en la
    misma funcion). Debe aparecer al menos 2 veces."""
    import inspect
    from app.routers import leads as leads_router
    src = inspect.getsource(leads_router.asignacion_automatica)
    assert src.count("login_blocked") >= 2

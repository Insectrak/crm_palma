"""
Tests del Sprint 1 — endpoints CRUD de roles (ADR-0011).

Estrategia: mockear directamente `roles_service` (no tocamos DB real).
Cubre auth + serialización + códigos de respuesta de los endpoints del
router. La lógica del service se prueba aparte en tests unitarios si
se vuelve compleja (Sprint 2/3).
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ─── Fixtures auxiliares ────────────────────────────────────────────────────

def _role(
    id: int = 1,
    name: str = "marketing",
    permissions: dict | None = None,
    is_builtin: bool = False,
    is_external: bool = False,
    user_count: int = 0,
) -> dict:
    """Construye un dict de rol con timestamps. Imita lo que devuelve psycopg2."""
    return {
        "id": id,
        "name": name,
        "description": f"{name} role",
        "permissions": permissions or {"reportes.view": True},
        "is_external": is_external,
        "is_builtin": is_builtin,
        "user_count": user_count,
        "created_at": datetime(2026, 6, 12, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 6, 12, tzinfo=timezone.utc),
    }


# ─── Auth gating ─────────────────────────────────────────────────────────────

def test_list_roles_requires_admin(client, auth_headers_supervisor=None):
    """Sin auth → 401. Con rol no-admin → 403."""
    r = client.get("/api/roles")
    assert r.status_code == 401

    from app.auth.jwt import create_access_token
    token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000002",
        "email": "sup@test.local",
        "role": "supervisor",
    })
    r = client.get("/api/roles", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ─── GET /api/roles ──────────────────────────────────────────────────────────

@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.list_roles_with_counts")
def test_list_roles_ok(mock_list, mock_db, client, auth_headers_admin):
    mock_db.return_value.__enter__.return_value = type("C", (), {
        "cursor": lambda self, **kw: _FakeCtx(),
    })()
    mock_list.return_value = [
        _role(id=1, name="admin", is_builtin=True, user_count=2),
        _role(id=4, name="marketing", user_count=0),
    ]
    r = client.get("/api/roles", headers=auth_headers_admin)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["name"] == "admin"
    assert data[0]["is_builtin"] is True
    # Timestamps deben venir como string ISO
    assert isinstance(data[0]["created_at"], str)


# ─── POST /api/roles ─────────────────────────────────────────────────────────

@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.create_role")
def test_create_role_ok(mock_create, mock_db, client, auth_headers_admin):
    mock_db.return_value.__enter__.return_value = _FakeConn()
    mock_create.return_value = _role(id=10, name="marketing")
    body = {
        "name": "marketing",
        "description": "Equipo de marketing",
        "permissions": {"reportes.view": True, "dashboards.view": True},
        "is_external": False,
    }
    r = client.post("/api/roles", json=body, headers=auth_headers_admin)
    assert r.status_code == 201
    assert r.json()["name"] == "marketing"
    mock_create.assert_called_once()


@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.create_role")
def test_create_role_duplicate_name(mock_create, mock_db, client, auth_headers_admin):
    mock_db.return_value.__enter__.return_value = _FakeConn()
    mock_create.side_effect = ValueError("Ya existe un rol con nombre 'marketing'.")
    r = client.post(
        "/api/roles",
        json={"name": "marketing", "permissions": {}},
        headers=auth_headers_admin,
    )
    assert r.status_code == 400
    assert "Ya existe" in r.json()["detail"]


# ─── PATCH /api/roles/{id}/permissions ───────────────────────────────────────

@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.get_role_by_id")
@patch("app.services.roles_service.update_role_permissions")
def test_update_permissions_ok(mock_update, mock_get, mock_db, client, auth_headers_admin):
    mock_db.return_value.__enter__.return_value = _FakeConn()
    # Snapshot previo (para audit)
    mock_get.return_value = _role(id=4, permissions={})
    mock_update.return_value = _role(id=4, permissions={"leads.view": True})
    r = client.patch(
        "/api/roles/4/permissions",
        json={"permissions": {"leads.view": True}},
        headers=auth_headers_admin,
    )
    assert r.status_code == 200
    assert r.json()["permissions"] == {"leads.view": True}


@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.get_role_by_id")
@patch("app.services.roles_service.update_role_permissions")
def test_update_permissions_not_found(mock_update, mock_get, mock_db, client, auth_headers_admin):
    # ADR-0011 Sprint 4: el router captura before-state via get_role_by_id
    # antes de actualizar. Si NO existe, devuelve 404 directo (no llama update).
    mock_db.return_value.__enter__.return_value = _FakeConn()
    mock_get.return_value = None  # rol no existe
    mock_update.return_value = None
    r = client.patch(
        "/api/roles/999/permissions",
        json={"permissions": {}},
        headers=auth_headers_admin,
    )
    assert r.status_code == 404


# ─── DELETE /api/roles/{id} ──────────────────────────────────────────────────

@pytest.mark.parametrize("svc_result, affected, expected_status, expected_affected", [
    ("ok",        0, 200, 0),
    ("ok",        3, 200, 3),   # ADR-0011 Salesforce-style: borrar transparente con usuarios
    ("not_found", 0, 404, None),
    ("builtin",   0, 403, None),
])
@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.get_role_by_id")
@patch("app.services.roles_service.delete_role")
def test_delete_role_all_paths(
    mock_delete, mock_get, mock_db, svc_result, affected, expected_status, expected_affected,
    client, auth_headers_admin,
):
    mock_db.return_value.__enter__.return_value = _FakeConn()
    # Snapshot previo (para audit). El router lo usa para registrar el name
    # del rol borrado aunque ya no exista en DB.
    mock_get.return_value = _role(id=4, name="marketing")
    # delete_role devuelve tupla (codigo, affected) desde ADR-0011 follow-up
    mock_delete.return_value = (svc_result, affected)
    r = client.delete("/api/roles/4", headers=auth_headers_admin)
    assert r.status_code == expected_status
    if expected_affected is not None:
        assert r.json().get("users_affected") == expected_affected


# ─── PATCH /api/roles/users/{user_id} ────────────────────────────────────────

@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.get_role_by_id")
@patch("app.services.roles_service.assign_role_to_user")
def test_assign_role_to_user_ok(mock_assign, mock_get_role, mock_db, client, auth_headers_admin):
    # El router pre-cargo: SELECT prev (email, role_id, role_name) + assign + get_role_by_id (audit)
    mock_db.return_value.__enter__.return_value = _FakeConn(cursor_fetches=[
        {"email": "u10@palma.test", "role_id": None, "role_name": None},
    ])
    mock_assign.return_value = True
    mock_get_role.return_value = _role(id=4, name="marketing")
    r = client.patch(
        "/api/roles/users/00000000-0000-0000-0000-000000000010",
        json={"role_id": 4},
        headers=auth_headers_admin,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


@patch("app.routers.roles.get_db")
@patch("app.services.roles_service.assign_role_to_user")
def test_assign_role_to_user_not_found(mock_assign, mock_db, client, auth_headers_admin):
    # Aun si el usuario no existe (assign devuelve False), el router primero
    # consulta el SELECT prev. Lo pre-cargamos con None para que fetchone
    # devuelva None y el endpoint responda 404 al fallar el assign.
    mock_db.return_value.__enter__.return_value = _FakeConn(cursor_fetches=[None])
    mock_assign.return_value = False
    r = client.patch(
        "/api/roles/users/00000000-0000-0000-0000-000000000010",
        json={"role_id": 4},
        headers=auth_headers_admin,
    )
    assert r.status_code == 404


# ─── Helpers para mockear el ctx manager de psycopg2 ─────────────────────────

class _FakeCtx:
    """Context manager fake con execute/fetchone configurables.

    `_fetch_results` es una cola que `fetchone` consume en orden. Si esta
    vacia, fetchone devuelve None (semantica de "no row").
    """
    def __init__(self, fetch_results=None):
        self._fetch_results = list(fetch_results or [])
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def execute(self, *a, **k): return None
    def fetchone(self, *a, **k):
        return self._fetch_results.pop(0) if self._fetch_results else None
    def fetchall(self, *a, **k): return []


class _FakeConn:
    """Connection mock: cursor() devuelve un context manager fake + commit() noop.

    Pasa `cursor_fetches` para encolar resultados de fetchone() para las
    queries directas que hacen los routers (ej. snapshot previo para audit).
    """
    def __init__(self, cursor_fetches=None):
        self._cursor_fetches = cursor_fetches or []
    def cursor(self, **kw): return _FakeCtx(self._cursor_fetches)
    def commit(self): pass
    def rollback(self): pass

    def __enter__(self): return self
    def __exit__(self, *a): pass

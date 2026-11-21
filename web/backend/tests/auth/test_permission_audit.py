"""
Tests del audit log de cambios de permisos (ADR-0011 Sprint 4).

Cubre:
- permission_audit_service: cada recorder hace un INSERT correcto.
- permission_audit_service: skip cuando before == after (no genera ruido).
- permission_audit_service: fail-safe — si DB tira excepcion, NO se propaga.
- Router GET /api/permission-audit: requiere roles.manage.
- Router GET /api/permission-audit: lista entradas con filtros.

NO testeamos integracion end-to-end con routers/roles.py aqui (eso vive en
test_roles_audit_integration.py, separado por SRP).
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.auth.schemas import TokenData
from app.services import permission_audit_service as svc


# ── Helpers ─────────────────────────────────────────────────────────────────

@contextmanager
def _fake_db_capturing_executes(captured: list):
    """Context manager que se comporta como get_db() pero captura todas las
    queries ejecutadas en una lista — para hacer assertions sobre que se
    inserto."""
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.fetchall.return_value = []

    def _exec(sql, params=None):
        captured.append((sql.strip().split("\n")[0], params))
    cur.execute.side_effect = _exec
    cur.__enter__ = lambda self: cur
    cur.__exit__ = lambda *a: False

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = lambda self: conn
    conn.__exit__ = lambda *a: False
    yield conn


def _patch_db(monkeypatch, captured: list):
    """Reemplaza app.services.permission_audit_service.get_db por uno
    que captura las queries en `captured`."""
    def _factory(*_a, **_k):
        return _fake_db_capturing_executes(captured)
    monkeypatch.setattr("app.services.permission_audit_service.get_db", _factory)


def _actor() -> TokenData:
    return TokenData(
        user_id="11111111-2222-3333-4444-555555555555",
        email="admin@palma.test",
        role="admin",
    )


# ── Service: recorders ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_record_role_create_inserts_row(monkeypatch):
    captured = []
    _patch_db(monkeypatch, captured)

    svc.record_role_create(
        actor=_actor(),
        role={"id": 42, "name": "marketing", "description": "x",
              "permissions": {"leads.view": True}, "is_external": False},
    )

    assert len(captured) == 1
    sql, params = captured[0]
    assert "INSERT INTO auth.permission_audit_log" in sql
    # actor_email, action, target_kind, target_id, target_label deben estar en params
    assert "admin@palma.test" in params
    assert "role.create" in params
    assert "role" in params
    assert "42" in params
    assert "marketing" in params


@pytest.mark.unit
def test_record_role_update_perms_inserts_with_diff(monkeypatch):
    captured = []
    _patch_db(monkeypatch, captured)

    svc.record_role_update_perms(
        actor=_actor(),
        role_id=42,
        role_name="marketing",
        before_perms={"leads.view": True},
        after_perms={"leads.view": True, "usuarios.manage": True},
    )

    assert len(captured) == 1
    sql, _params = captured[0]
    assert "INSERT INTO auth.permission_audit_log" in sql


@pytest.mark.unit
def test_record_role_update_perms_skips_when_no_change(monkeypatch):
    captured = []
    _patch_db(monkeypatch, captured)

    svc.record_role_update_perms(
        actor=_actor(),
        role_id=42,
        role_name="marketing",
        before_perms={"leads.view": True},
        after_perms={"leads.view": True},
    )

    assert captured == [], "no debe insertar fila si no hay cambio real"


@pytest.mark.unit
def test_record_role_update_meta_skips_when_no_change(monkeypatch):
    captured = []
    _patch_db(monkeypatch, captured)

    svc.record_role_update_meta(
        actor=_actor(),
        role_id=42,
        role_name="marketing",
        before={"description": "x", "is_external": False},
        after={"description": "x", "is_external": False},
    )

    assert captured == []


@pytest.mark.unit
def test_record_role_delete_inserts(monkeypatch):
    captured = []
    _patch_db(monkeypatch, captured)

    svc.record_role_delete(
        actor=_actor(),
        role_id=42,
        role_name="marketing",
        users_affected=3,
    )

    assert len(captured) == 1
    _sql, params = captured[0]
    assert "role.delete" in params


@pytest.mark.unit
def test_record_user_role_change_inserts(monkeypatch):
    captured = []
    _patch_db(monkeypatch, captured)

    svc.record_user_role_change(
        actor=_actor(),
        target_user_id="99999999-0000-0000-0000-000000000000",
        target_user_email="juan@palma.test",
        before_role_id=None,
        before_role_name="asesor",
        after_role_id=None,
        after_role_name="supervisor",
    )

    assert len(captured) == 1
    _sql, params = captured[0]
    assert "user.role_change" in params
    assert "juan@palma.test" in params


@pytest.mark.unit
def test_record_user_role_change_skips_when_same_role(monkeypatch):
    captured = []
    _patch_db(monkeypatch, captured)

    svc.record_user_role_change(
        actor=_actor(),
        target_user_id="99999999-0000-0000-0000-000000000000",
        target_user_email="juan@palma.test",
        before_role_id=5,
        before_role_name="marketing",
        after_role_id=5,
        after_role_name="marketing",
    )

    assert captured == []


@pytest.mark.unit
def test_recorders_are_failsafe_when_db_raises(monkeypatch):
    """Si el INSERT falla, el recorder NO debe propagar la excepcion.
    Si la propagara, una caida del audit log romperia las operaciones
    legitimas del admin — el opuesto de lo que queremos."""
    @contextmanager
    def _exploding_db():
        raise RuntimeError("DB caida")
        yield None  # pragma: no cover

    monkeypatch.setattr(
        "app.services.permission_audit_service.get_db",
        _exploding_db,
    )

    # No debe levantar ninguna excepcion
    svc.record_role_create(actor=_actor(), role={"id": 1, "name": "x"})
    svc.record_role_delete(actor=_actor(), role_id=1, role_name="x", users_affected=0)


# ── Router: GET /api/permission-audit ───────────────────────────────────────

@pytest.mark.auth
@pytest.mark.unit
def test_get_audit_requires_authentication(client):
    response = client.get("/api/permission-audit")
    assert response.status_code == 401


@pytest.mark.auth
@pytest.mark.unit
def test_get_audit_requires_roles_manage_permission(client, auth_headers_asesor):
    # Asesor sin roles.manage -> 403
    response = client.get("/api/permission-audit", headers=auth_headers_asesor)
    assert response.status_code == 403
    assert "roles.manage" in response.json()["detail"]


@pytest.mark.auth
@pytest.mark.unit
def test_get_audit_admin_can_list(client, auth_headers_admin, monkeypatch):
    # Mock service.list_recent para devolver datos canned
    fake_data = {
        "items": [
            {
                "id": 1,
                "actor_user_id": "11111111-2222-3333-4444-555555555555",
                "actor_email": "admin@palma.test",
                "actor_role": "admin",
                "action": "role.create",
                "target_kind": "role",
                "target_id": "5",
                "target_label": "marketing",
                "before_state": None,
                "after_state": {"name": "marketing", "permissions": {}},
                "ip_address": "1.2.3.4",
                "user_agent": "test-ua",
                "created_at": "2026-06-15T12:00:00",
            }
        ],
        "total": 1,
    }
    monkeypatch.setattr(
        "app.routers.permission_audit.audit.list_recent",
        lambda **kw: fake_data,
    )

    response = client.get("/api/permission-audit", headers=auth_headers_admin)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["action"] == "role.create"
    assert body["items"][0]["target_label"] == "marketing"


@pytest.mark.auth
@pytest.mark.unit
def test_get_audit_validates_limit_range(client, auth_headers_admin):
    # limit < 1 debe rechazar (pydantic Query ge=1)
    response = client.get("/api/permission-audit?limit=0", headers=auth_headers_admin)
    assert response.status_code == 422
    # limit > 200 debe rechazar (pydantic Query le=200)
    response = client.get("/api/permission-audit?limit=500", headers=auth_headers_admin)
    assert response.status_code == 422


@pytest.mark.auth
@pytest.mark.unit
def test_get_audit_passes_filters_through(client, auth_headers_admin, monkeypatch):
    captured_kwargs = {}

    def _capture(**kw):
        captured_kwargs.update(kw)
        return {"items": [], "total": 0}

    monkeypatch.setattr(
        "app.routers.permission_audit.audit.list_recent",
        _capture,
    )

    response = client.get(
        "/api/permission-audit?action=role.delete&target_kind=role&target_id=42&limit=10&offset=20",
        headers=auth_headers_admin,
    )

    assert response.status_code == 200
    assert captured_kwargs["action"] == "role.delete"
    assert captured_kwargs["target_kind"] == "role"
    assert captured_kwargs["target_id"] == "42"
    assert captured_kwargs["limit"] == 10
    assert captured_kwargs["offset"] == 20

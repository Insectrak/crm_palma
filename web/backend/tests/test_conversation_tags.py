"""Tests para los endpoints de etiquetas a nivel conversacion (V038).

Cubren:
- POST   /api/whatsapp/conversations/{id}/tags
- DELETE /api/whatsapp/conversations/{id}/tags/{tag_id}
- GET    /api/whatsapp/conversations/{id}/tags

Validaciones:
- Auth requerida (401 sin token)
- Reglas de acceso por rol (admin, supervisor, asesor)
- 404 conv inexistente, 404 tag inactiva
- Idempotencia (ON CONFLICT DO NOTHING en POST)

Mocking: get_db con _FakeConn parametrizable. Cada test inyecta el set
de filas que el cursor debe devolver para esa secuencia de queries.
"""
from contextlib import contextmanager

import pytest

from app.config import settings as app_settings


# ── Fakes ──────────────────────────────────────────────────────────────────

class _FakeCursor:
    """Cursor con cola FIFO de fetchone/fetchall responses."""

    def __init__(self, fetchone_queue=None, fetchall_queue=None):
        self._fetchone_queue = list(fetchone_queue or [])
        self._fetchall_queue = list(fetchall_queue or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone_queue.pop(0) if self._fetchone_queue else None

    def fetchall(self):
        return self._fetchall_queue.pop(0) if self._fetchall_queue else []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, **kwargs):
        return self._cursor

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_get_db(monkeypatch, cursor):
    monkeypatch.setattr(app_settings, "demo_mode", False)

    @contextmanager
    def fake_get_db():
        yield _FakeConn(cursor)

    monkeypatch.setattr("app.database.get_db", fake_get_db)
    monkeypatch.setattr("app.routers.tags.get_db", fake_get_db)


# ── POST: assign_tag_to_conversation ──────────────────────────────────────

def test_assign_tag_to_conv_admin_happy_path(client, auth_headers_admin, monkeypatch):
    """Admin asigna tag a conv sin asesor → ok."""
    cursor = _FakeCursor(fetchone_queue=[
        {"lead_id": None, "asesor_id": None},   # _assert_conv_access SELECT
        {"id": 1},                              # tag exists & activo
    ])
    _patch_get_db(monkeypatch, cursor)

    res = client.post(
        "/api/whatsapp/conversations/42/tags",
        headers=auth_headers_admin,
        json={"tag_id": 1},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["conversation_id"] == 42
    assert body["tag_id"] == 1
    # Verificamos que se ejecuto el INSERT con ON CONFLICT
    inserts = [s for s, _ in cursor.executed if "INSERT INTO crm.wa_conversation_tags" in s]
    assert len(inserts) == 1
    assert "ON CONFLICT (conversation_id, tag_id) DO NOTHING" in inserts[0]


def test_assign_tag_to_conv_returns_404_when_conv_not_found(
    client, auth_headers_admin, monkeypatch,
):
    cursor = _FakeCursor(fetchone_queue=[None])  # primera SELECT no encuentra
    _patch_get_db(monkeypatch, cursor)

    res = client.post(
        "/api/whatsapp/conversations/9999/tags",
        headers=auth_headers_admin,
        json={"tag_id": 1},
    )
    assert res.status_code == 404
    assert "conversaci" in res.json()["detail"].lower()


def test_assign_tag_to_conv_returns_404_when_tag_inactive(
    client, auth_headers_admin, monkeypatch,
):
    """Tag con activo=FALSE no debe poder asignarse."""
    cursor = _FakeCursor(fetchone_queue=[
        {"lead_id": None, "asesor_id": None},   # conv encontrada
        None,                                   # tag no existe / inactiva
    ])
    _patch_get_db(monkeypatch, cursor)

    res = client.post(
        "/api/whatsapp/conversations/42/tags",
        headers=auth_headers_admin,
        json={"tag_id": 99},
    )
    assert res.status_code == 404
    assert "etiqueta" in res.json()["detail"].lower()


def test_assign_tag_to_conv_asesor_blocked_when_not_assigned(
    client, auth_headers_asesor, monkeypatch,
):
    """Asesor que NO es duenio de la conv → 403."""
    cursor = _FakeCursor(fetchone_queue=[
        {"lead_id": None, "asesor_id": "00000000-0000-0000-0000-000000000099"},
    ])
    _patch_get_db(monkeypatch, cursor)

    res = client.post(
        "/api/whatsapp/conversations/42/tags",
        headers=auth_headers_asesor,
        json={"tag_id": 1},
    )
    assert res.status_code == 403


def test_assign_tag_to_conv_asesor_ok_when_owner(
    client, auth_headers_asesor, monkeypatch,
):
    """Asesor con conv.asesor_id == self → puede etiquetar."""
    asesor_uuid = "00000000-0000-0000-0000-000000000003"  # mismo del fixture
    cursor = _FakeCursor(fetchone_queue=[
        {"lead_id": None, "asesor_id": asesor_uuid},
        {"id": 1},
    ])
    _patch_get_db(monkeypatch, cursor)

    res = client.post(
        "/api/whatsapp/conversations/42/tags",
        headers=auth_headers_asesor,
        json={"tag_id": 1},
    )
    assert res.status_code == 201


def test_assign_tag_to_conv_supervisor_can_tag_unassigned_conv(
    client, auth_headers_supervisor, monkeypatch,
):
    """Supervisor puede etiquetar convs sin asesor (workflow de triage)."""
    cursor = _FakeCursor(fetchone_queue=[
        {"lead_id": None, "asesor_id": None},  # sin asesor
        {"id": 1},                              # tag valida
    ])
    _patch_get_db(monkeypatch, cursor)

    res = client.post(
        "/api/whatsapp/conversations/42/tags",
        headers=auth_headers_supervisor,
        json={"tag_id": 1},
    )
    assert res.status_code == 201


def test_assign_tag_to_conv_supervisor_team_check(
    client, auth_headers_supervisor, monkeypatch,
):
    """Supervisor con conv de un asesor que NO esta en su equipo → 403."""
    cursor = _FakeCursor(fetchone_queue=[
        {"lead_id": None, "asesor_id": "00000000-0000-0000-0000-000000000099"},
        None,  # crm.equipos no devuelve fila → fuera del equipo
    ])
    _patch_get_db(monkeypatch, cursor)

    res = client.post(
        "/api/whatsapp/conversations/42/tags",
        headers=auth_headers_supervisor,
        json={"tag_id": 1},
    )
    assert res.status_code == 403


def test_assign_tag_to_conv_requires_auth(client):
    res = client.post("/api/whatsapp/conversations/42/tags", json={"tag_id": 1})
    assert res.status_code == 401


# ── DELETE: remove_tag_from_conversation ──────────────────────────────────

def test_remove_tag_from_conv_happy_path(client, auth_headers_admin, monkeypatch):
    cursor = _FakeCursor(fetchone_queue=[
        {"lead_id": None, "asesor_id": None},  # _assert_conv_access
    ])
    _patch_get_db(monkeypatch, cursor)

    res = client.delete(
        "/api/whatsapp/conversations/42/tags/1",
        headers=auth_headers_admin,
    )
    assert res.status_code == 200
    deletes = [s for s, _ in cursor.executed if "DELETE FROM crm.wa_conversation_tags" in s]
    assert len(deletes) == 1


def test_remove_tag_from_conv_requires_auth(client):
    res = client.delete("/api/whatsapp/conversations/42/tags/1")
    assert res.status_code == 401


# ── GET: get_conversation_tags ────────────────────────────────────────────

def test_get_conversation_tags_returns_list(client, auth_headers_admin, monkeypatch):
    cursor = _FakeCursor(
        fetchone_queue=[
            {"lead_id": None, "asesor_id": None},  # _assert_conv_access
        ],
        fetchall_queue=[
            [
                {"id": 1, "nombre": "Caliente", "color_hex": "#ef4444", "descripcion": None},
                {"id": 2, "nombre": "Soporte", "color_hex": "#14b8a6", "descripcion": "Caso soporte"},
            ],
        ],
    )
    _patch_get_db(monkeypatch, cursor)

    res = client.get("/api/whatsapp/conversations/42/tags", headers=auth_headers_admin)
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    assert body[0]["nombre"] == "Caliente"
    assert body[1]["nombre"] == "Soporte"


def test_get_conversation_tags_requires_auth(client):
    res = client.get("/api/whatsapp/conversations/42/tags")
    assert res.status_code == 401


def test_get_conversation_tags_404_when_conv_missing(
    client, auth_headers_admin, monkeypatch,
):
    cursor = _FakeCursor(fetchone_queue=[None])
    _patch_get_db(monkeypatch, cursor)

    res = client.get("/api/whatsapp/conversations/9999/tags", headers=auth_headers_admin)
    assert res.status_code == 404

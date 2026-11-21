"""Tests para el flujo "Tomar este chat" que ahora crea/reusa lead.

Antes el endpoint /take solo asignaba asesor_id en wa_conversations cuando
no habia lead — eso dejaba la conv huerfana (no aparecia en /Leads). Ahora
crea (o reusa) un lead activo y devuelve flags para que el frontend pueda
dar feedback claro al usuario.

Cubre la unidad pura (`create_lead_from_take_action` con cursor mockeado),
no el endpoint completo — el endpoint se prueba via integration cuando
tengamos DB real. La logica critica es la creacion/reuso del lead.
"""
import pytest


# ── Fakes ──────────────────────────────────────────────────────────────────

class _FakeCursor:
    """Cursor con cola FIFO de fetchone responses parametrizable.

    Las execute() se loguean para poder afirmar sobre que SQL corrio."""

    def __init__(self, fetchone_queue=None):
        self._fetchone_queue = list(fetchone_queue or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone_queue.pop(0) if self._fetchone_queue else None

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
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_get_db(monkeypatch, cursor):
    from contextlib import contextmanager

    @contextmanager
    def fake_get_db():
        yield _FakeConn(cursor)

    monkeypatch.setattr(
        "app.services.wa_router_service.get_db", fake_get_db,
    )


def _stub_helpers(monkeypatch):
    """Stub de helpers externos invocados por la funcion."""
    monkeypatch.setattr(
        "app.services.integrations.ingest_core._resolve_fuente_id",
        lambda cur, name: 7,  # fuente_id arbitrario
    )
    monkeypatch.setattr(
        "app.services.integrations.ingest_core.clean_phone",
        lambda raw: (raw or "").strip(),
    )
    # Stub de notify_new_lead — sin red ni FCM
    monkeypatch.setattr(
        "app.services.wa_router_service.notify_new_lead",
        lambda *a, **kw: None,
    )


# ── Tests ──────────────────────────────────────────────────────────────────

def test_take_returns_existing_lead_when_conv_already_has_lead_id(monkeypatch):
    """Si la conv ya tiene lead_id, devuelve el existente sin crear nuevo."""
    from app.services.wa_router_service import create_lead_from_take_action

    cursor = _FakeCursor(fetchone_queue=[
        {"id": 42, "wa_phone": "51987654321", "contact_name": "Juan", "lead_id": 100},
        {"nombres": "Juan", "apellidos": "Perez"},
    ])
    _patch_get_db(monkeypatch, cursor)
    _stub_helpers(monkeypatch)

    result = create_lead_from_take_action(
        conversation_id=42, taker_user_id="uuid-asesor", taker_role="asesor",
    )

    assert result["ok"] is True
    assert result["lead_id"] == 100
    assert result["lead_created"] is False
    assert result["lead_name"] == "Juan Perez"
    # No debe ejecutar INSERT en crm.leads
    inserts = [s for s, _ in cursor.executed if "INSERT INTO crm.leads" in s]
    assert len(inserts) == 0


def test_take_creates_new_lead_when_no_existing_phone(monkeypatch):
    """Conv sin lead + telefono sin lead activo → INSERT crm.leads + UPDATE conv."""
    from app.services.wa_router_service import create_lead_from_take_action

    cursor = _FakeCursor(fetchone_queue=[
        # 1) SELECT conv data
        {"id": 42, "wa_phone": "51987654321", "contact_name": "Helber Gonzales", "lead_id": None},
        # 2) Dedupe por telefono → no encuentra
        None,
        # 3) Estado 'Nuevo' lookup
        {"id": 1},
        # 4) Resolver supervisor (asesor → busca su supervisor en equipos)
        {"supervisor_id": "uuid-sup-of-asesor"},
        # 5) INSERT lead RETURNING id
        {"id": 999},
    ])
    _patch_get_db(monkeypatch, cursor)
    _stub_helpers(monkeypatch)

    result = create_lead_from_take_action(
        conversation_id=42, taker_user_id="uuid-asesor", taker_role="asesor",
    )

    assert result["ok"] is True
    assert result["lead_id"] == 999
    assert result["lead_created"] is True
    assert result["lead_name"] == "Helber Gonzales"

    # Verifica INSERT crm.leads + UPDATE wa_conversations
    inserts = [s for s, _ in cursor.executed if "INSERT INTO crm.leads" in s]
    updates = [s for s, _ in cursor.executed if "UPDATE crm.wa_conversations" in s]
    assert len(inserts) == 1
    assert len(updates) == 1


def test_take_reuses_existing_active_lead_by_phone(monkeypatch):
    """Mismo telefono ya tiene lead activo → reusa, no crea nuevo."""
    from app.services.wa_router_service import create_lead_from_take_action

    cursor = _FakeCursor(fetchone_queue=[
        # 1) SELECT conv data — sin lead todavia
        {"id": 42, "wa_phone": "51987654321", "contact_name": "Helber", "lead_id": None},
        # 2) Dedupe por telefono → ENCUENTRA un lead activo
        {"id": 555, "nombres": "Helber", "apellidos": "Gonzales"},
    ])
    _patch_get_db(monkeypatch, cursor)
    _stub_helpers(monkeypatch)
    # Stub el reassign_one
    monkeypatch.setattr(
        "app.services.assignments_service.reassign_one",
        lambda **kw: {"ok": True},
    )

    result = create_lead_from_take_action(
        conversation_id=42, taker_user_id="uuid-asesor", taker_role="asesor",
    )

    assert result["ok"] is True
    assert result["lead_id"] == 555
    assert result["lead_created"] is False
    assert result["lead_name"] == "Helber Gonzales"

    # NO debe haber INSERT crm.leads
    inserts = [s for s, _ in cursor.executed if "INSERT INTO crm.leads" in s]
    assert len(inserts) == 0
    # SI debe haber UPDATE wa_conversations
    updates = [s for s, _ in cursor.executed if "UPDATE crm.wa_conversations" in s]
    assert len(updates) == 1


def test_take_admin_role_supervisor_id_is_null(monkeypatch):
    """Admin tomando chat → supervisor_id NULL en el lead nuevo."""
    from app.services.wa_router_service import create_lead_from_take_action

    cursor = _FakeCursor(fetchone_queue=[
        {"id": 42, "wa_phone": "51999", "contact_name": "X", "lead_id": None},
        None,             # dedupe miss
        {"id": 1},        # estado Nuevo
        # NO se hace SELECT crm.equipos para admin (supervisor=None directo)
        {"id": 1234},     # INSERT RETURNING
    ])
    _patch_get_db(monkeypatch, cursor)
    _stub_helpers(monkeypatch)

    result = create_lead_from_take_action(
        conversation_id=42, taker_user_id="uuid-admin", taker_role="admin",
    )

    assert result["lead_created"] is True
    assert result["lead_id"] == 1234
    # Verificamos que el INSERT pase NULL para supervisor_id (positions 6 y 7
    # en el tuple — supervisor_id se pasa dos veces por el CASE WHEN)
    insert_calls = [
        (s, p) for s, p in cursor.executed
        if "INSERT INTO crm.leads" in s
    ]
    assert len(insert_calls) == 1
    _, params = insert_calls[0]
    # params layout: nombres, apellidos, telefono, fuente_id, estado_id,
    #                taker_user_id, supervisor_id, supervisor_id, observaciones
    assert params[6] is None  # supervisor_id is None for admin
    assert params[7] is None


def test_take_supervisor_role_supervisor_id_is_self(monkeypatch):
    """Supervisor tomando chat → supervisor_id = self."""
    from app.services.wa_router_service import create_lead_from_take_action

    cursor = _FakeCursor(fetchone_queue=[
        {"id": 42, "wa_phone": "51999", "contact_name": "X", "lead_id": None},
        None,
        {"id": 1},
        {"id": 5678},
    ])
    _patch_get_db(monkeypatch, cursor)
    _stub_helpers(monkeypatch)

    result = create_lead_from_take_action(
        conversation_id=42,
        taker_user_id="uuid-sup",
        taker_role="supervisor",
    )

    assert result["lead_created"] is True
    insert_calls = [
        (s, p) for s, p in cursor.executed
        if "INSERT INTO crm.leads" in s
    ]
    _, params = insert_calls[0]
    assert params[6] == "uuid-sup"
    assert params[7] == "uuid-sup"


def test_take_raises_if_conversation_not_found(monkeypatch):
    from app.services.wa_router_service import create_lead_from_take_action

    cursor = _FakeCursor(fetchone_queue=[None])  # conv no existe
    _patch_get_db(monkeypatch, cursor)
    _stub_helpers(monkeypatch)

    with pytest.raises(ValueError, match="no existe"):
        create_lead_from_take_action(
            conversation_id=9999, taker_user_id="uuid", taker_role="asesor",
        )

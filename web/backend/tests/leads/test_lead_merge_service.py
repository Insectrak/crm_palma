"""
Tests de lead_merge_service.py.

Cubre las funciones puras + las validaciones del flujo merge.

NO testeado aqui (requiere integration):
  - merge_leads completo (mueve children entre tablas, requiere DB real)
  - list_duplicate_clusters (SQL query compleja con CTEs)

Cubierto:
  - _serialize_for_json: datetime, UUID, primitivos
  - _strip_secrets: campos eliminados del preview
  - _fetch_lead_full: SQL ejecutado correctamente
  - preview_merge: validaciones (mismo id, no encontrado, ya mergeado)
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── _serialize_for_json ──────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_serialize_for_json_converts_datetime():
    from app.services.lead_merge_service import _serialize_for_json
    d = {"created_at": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)}
    result = _serialize_for_json(d)
    assert isinstance(result["created_at"], str)
    assert "2026-05-01" in result["created_at"]


@pytest.mark.leads
@pytest.mark.unit
def test_serialize_for_json_passes_through_primitives():
    from app.services.lead_merge_service import _serialize_for_json
    d = {
        "id": 42,
        "nombre": "Ana",
        "activo": True,
        "score": 3.14,
        "tags": ["a", "b"],
        "meta": {"k": "v"},
        "nada": None,
    }
    result = _serialize_for_json(d)
    assert result == d   # primitivos sin cambio


@pytest.mark.leads
@pytest.mark.unit
def test_serialize_for_json_stringifies_unknown_types():
    """Si el tipo no es primitivo ni tiene isoformat, str()."""
    from app.services.lead_merge_service import _serialize_for_json
    import uuid
    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    d = {"id": uid}
    result = _serialize_for_json(d)
    assert isinstance(result["id"], str)
    assert "12345678" in result["id"]


# ── _strip_secrets ───────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_strip_secrets_removes_known_internal_fields():
    from app.services.lead_merge_service import _strip_secrets
    d = {
        "id": 42,
        "nombres": "Ana",
        "merged_into": 99,                          # se elimina
        "merged_at": "2026-05-01",                  # se elimina
        "created_by": "uuid",                       # se elimina
        "updated_at": "2026-05-01",                 # se elimina
        "duplicate_override_reason": "test",        # se elimina
        "created_with_duplicate_override": True,    # se elimina
    }
    result = _strip_secrets(d)
    assert "id" in result
    assert "nombres" in result
    assert "merged_into" not in result
    assert "merged_at" not in result
    assert "created_by" not in result
    assert "updated_at" not in result
    assert "duplicate_override_reason" not in result
    assert "created_with_duplicate_override" not in result


@pytest.mark.leads
@pytest.mark.unit
def test_strip_secrets_serializes_datetime():
    """Despues de strippear, los campos restantes con datetime se convierten."""
    from app.services.lead_merge_service import _strip_secrets
    d = {
        "id": 42,
        "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    }
    result = _strip_secrets(d)
    assert isinstance(result["created_at"], str)


@pytest.mark.leads
@pytest.mark.unit
def test_strip_secrets_returns_empty_when_input_empty():
    from app.services.lead_merge_service import _strip_secrets
    assert _strip_secrets({}) == {}


# ── _fetch_lead_full ─────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_fetch_lead_full_executes_select_and_returns_row():
    from app.services.lead_merge_service import _fetch_lead_full
    cur = MagicMock()
    expected = {"id": 42, "nombres": "Ana", "estado_nombre": "Nuevo"}
    cur.fetchone.return_value = expected

    result = _fetch_lead_full(cur, 42)

    assert result == expected
    cur.execute.assert_called_once()
    sql = cur.execute.call_args[0][0]
    assert "FROM crm.leads" in sql
    assert "LEFT JOIN crm.estados_lead" in sql
    assert "LEFT JOIN crm.fuentes" in sql


@pytest.mark.leads
@pytest.mark.unit
def test_fetch_lead_full_returns_none_when_not_found():
    from app.services.lead_merge_service import _fetch_lead_full
    cur = MagicMock()
    cur.fetchone.return_value = None
    assert _fetch_lead_full(cur, 999) is None


# ── preview_merge: validaciones ──────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_preview_merge_same_id_raises_400():
    """master_id y secondary_id no pueden ser el mismo."""
    from app.services.lead_merge_service import preview_merge
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        preview_merge(42, 42)
    assert exc.value.status_code == 400
    assert "iguales" in exc.value.detail.lower()


@pytest.mark.leads
@pytest.mark.unit
def test_preview_merge_master_not_found_raises_404(monkeypatch):
    """Si _fetch_lead_full devuelve None para alguno, raise 404."""
    from app.services.lead_merge_service import preview_merge
    from fastapi import HTTPException
    from tests.fixtures import fake_db_returning

    monkeypatch.setattr(
        "app.services.lead_merge_service.get_db",
        fake_db_returning(None, None),  # master=None, secondary=None
    )

    with pytest.raises(HTTPException) as exc:
        preview_merge(1, 2)
    assert exc.value.status_code == 404


@pytest.mark.leads
@pytest.mark.unit
def test_preview_merge_master_already_merged_raises_409(monkeypatch):
    """Si el master ya tiene merged_into != None, raise 409."""
    from app.services.lead_merge_service import preview_merge
    from fastapi import HTTPException
    from tests.fixtures import fake_db_returning

    master = {"id": 1, "merged_into": 99, "nombres": "x"}    # ya mergeado
    secondary = {"id": 2, "merged_into": None, "nombres": "y"}
    monkeypatch.setattr(
        "app.services.lead_merge_service.get_db",
        fake_db_returning(master, secondary),
    )

    with pytest.raises(HTTPException) as exc:
        preview_merge(1, 2)
    assert exc.value.status_code == 409
    assert "master" in exc.value.detail.lower()


@pytest.mark.leads
@pytest.mark.unit
def test_preview_merge_secondary_already_merged_raises_409(monkeypatch):
    """Si el secondary ya tiene merged_into != None, raise 409."""
    from app.services.lead_merge_service import preview_merge
    from fastapi import HTTPException
    from tests.fixtures import fake_db_returning

    master = {"id": 1, "merged_into": None, "nombres": "x"}
    secondary = {"id": 2, "merged_into": 99, "nombres": "y"}  # ya mergeado
    monkeypatch.setattr(
        "app.services.lead_merge_service.get_db",
        fake_db_returning(master, secondary),
    )

    with pytest.raises(HTTPException) as exc:
        preview_merge(1, 2)
    assert exc.value.status_code == 409
    assert "secondary" in exc.value.detail.lower()

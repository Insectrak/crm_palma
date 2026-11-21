"""
Tests de wa_numbers_service.py — catalogo de numeros WhatsApp activos.

Cubre:
  - _row_to_dict: mapea row a dict publico.
  - invalidate_cache: limpia _CACHE module-level.
  - get_by_phone_number_id: lookup + cache + None inputs.
  - get_by_id: lookup por PK + None inputs.
  - get_default: query con ORDER BY is_default DESC.
  - has_sending_capability: EXISTS query booleano.

NO cubre (requiere DB real):
  - get_or_register (escribe en DB)
  - set_default (transaccion compleja con BEGIN/COMMIT y UPDATE multiple)
  - list_all con JOIN a wa_babas (mock complejo)
"""
from unittest.mock import MagicMock

import pytest


# ── invalidate_cache ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_invalidate_cache_clears_cache():
    from app.services import wa_numbers_service

    wa_numbers_service._CACHE["phone-x"] = {"id": 1}
    wa_numbers_service._CACHE["phone-y"] = {"id": 2}

    wa_numbers_service.invalidate_cache()

    assert len(wa_numbers_service._CACHE) == 0


# ── _row_to_dict ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_row_to_dict_maps_dict_row():
    """Funciona con dict (RealDictCursor)."""
    from app.services.wa_numbers_service import _row_to_dict

    row = {
        "id": 1,
        "phone_number_id": "phone-meta-123",
        "display_phone": "+51999888777",
        "display_name": "Palma Principal",
        "waba_id": "waba-abc",
        "waba_id_ref": 5,
        "is_default": True,
        "activo": True,
    }
    result = _row_to_dict(row)

    assert result["id"] == 1
    assert result["phone_number_id"] == "phone-meta-123"
    assert result["display_name"] == "Palma Principal"
    assert result["is_default"] is True
    assert result["waba_id_ref"] == 5


# ── get_by_phone_number_id ───────────────────────────────────────────────

@pytest.mark.unit
def test_get_by_phone_number_id_with_empty_string_returns_none():
    """Defensa: input vacio NO consulta DB."""
    from app.services.wa_numbers_service import get_by_phone_number_id
    assert get_by_phone_number_id("") is None
    assert get_by_phone_number_id(None) is None


@pytest.mark.unit
def test_get_by_phone_number_id_returns_from_cache_if_present(monkeypatch):
    """Si el cache tiene la entrada, NO consulta DB."""
    from app.services import wa_numbers_service

    wa_numbers_service._CACHE.clear()
    cached_value = {"id": 99, "phone_number_id": "phone-cached"}
    wa_numbers_service._CACHE["phone-cached"] = cached_value

    db_called = MagicMock()
    monkeypatch.setattr("app.services.wa_numbers_service.get_db", db_called)

    result = wa_numbers_service.get_by_phone_number_id("phone-cached")

    assert result == cached_value
    db_called.assert_not_called()  # No tocamos DB

    wa_numbers_service._CACHE.clear()


@pytest.mark.unit
def test_get_by_phone_number_id_queries_db_and_caches_on_miss(monkeypatch):
    """Cache miss -> SELECT + guarda en cache."""
    from app.services import wa_numbers_service
    from tests.fixtures import fake_db_returning

    wa_numbers_service._CACHE.clear()
    row = {
        "id": 1, "phone_number_id": "phone-new",
        "display_phone": "+51X", "display_name": "X",
        "waba_id": "w", "waba_id_ref": 1,
        "is_default": False, "activo": True,
    }
    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        fake_db_returning(row),
    )

    result = wa_numbers_service.get_by_phone_number_id("phone-new")

    assert result["id"] == 1
    assert "phone-new" in wa_numbers_service._CACHE

    wa_numbers_service._CACHE.clear()


@pytest.mark.unit
def test_get_by_phone_number_id_returns_none_when_not_found(monkeypatch):
    """SELECT devuelve None -> return None, no cachea."""
    from app.services import wa_numbers_service
    from tests.fixtures import fake_db_returning

    wa_numbers_service._CACHE.clear()
    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        fake_db_returning(None),
    )

    result = wa_numbers_service.get_by_phone_number_id("phone-inexistente")

    assert result is None
    assert "phone-inexistente" not in wa_numbers_service._CACHE


# ── get_by_id ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_get_by_id_with_zero_or_none_returns_none():
    """Defensa: id falsy NO consulta DB."""
    from app.services.wa_numbers_service import get_by_id
    assert get_by_id(0) is None
    assert get_by_id(None) is None


@pytest.mark.unit
def test_get_by_id_returns_dict_when_found(monkeypatch):
    from app.services.wa_numbers_service import get_by_id
    from tests.fixtures import fake_db_returning

    row = {
        "id": 42, "phone_number_id": "phone-42",
        "display_phone": "+51", "display_name": "Linea 42",
        "waba_id": "w", "waba_id_ref": 1,
        "is_default": False, "activo": True,
    }
    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        fake_db_returning(row),
    )

    result = get_by_id(42)

    assert result["id"] == 42
    assert result["display_name"] == "Linea 42"


@pytest.mark.unit
def test_get_by_id_returns_none_when_not_found(monkeypatch):
    from app.services.wa_numbers_service import get_by_id
    from tests.fixtures import fake_db_returning

    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        fake_db_returning(None),
    )

    assert get_by_id(999) is None


# ── get_default ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_get_default_returns_first_default_when_exists(monkeypatch):
    """ORDER BY is_default DESC asegura que el default activo gane."""
    from app.services.wa_numbers_service import get_default
    from tests.fixtures import fake_db_returning

    default_row = {
        "id": 5, "phone_number_id": "phone-default",
        "display_phone": "+51", "display_name": "Principal",
        "waba_id": "w", "waba_id_ref": 1,
        "is_default": True, "activo": True,
    }
    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        fake_db_returning(default_row),
    )

    result = get_default()

    assert result["id"] == 5
    assert result["is_default"] is True


@pytest.mark.unit
def test_get_default_returns_none_when_no_active_numbers(monkeypatch):
    from app.services.wa_numbers_service import get_default
    from tests.fixtures import fake_db_returning

    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        fake_db_returning(None),
    )

    assert get_default() is None


# ── has_sending_capability ───────────────────────────────────────────────

def _mock_db_returning_tuple(value):
    """Helper local: mock get_db que hace cur.fetchone() devolver una tupla.
    Necesario porque has_sending_capability hace cur.fetchone()[0]."""
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    @contextmanager
    def _ctx():
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = (value,)  # tupla con un elemento
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        yield conn

    return _ctx


@pytest.mark.unit
def test_has_sending_capability_returns_true_when_active_number_exists(monkeypatch):
    """EXISTS query devuelve (True,) -> True."""
    from app.services.wa_numbers_service import has_sending_capability

    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        _mock_db_returning_tuple(True),
    )

    assert has_sending_capability() is True


@pytest.mark.unit
def test_has_sending_capability_returns_false_when_no_active_numbers(monkeypatch):
    """EXISTS query devuelve (False,) -> False."""
    from app.services.wa_numbers_service import has_sending_capability

    monkeypatch.setattr(
        "app.services.wa_numbers_service.get_db",
        _mock_db_returning_tuple(False),
    )

    assert has_sending_capability() is False

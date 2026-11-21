"""Tests para `app.services.wa_ia_mode_service`.

V070.70 (Bundle C — split de whatsapp.py). Cubre el cache TTL, fallback
al default cuando la DB falla, invalidacion explicita.
"""
from contextlib import contextmanager

import pytest


@pytest.fixture(autouse=True)
def _reset_cache():
    """Cada test arranca con cache limpio para no depender del orden."""
    from app.services.wa_ia_mode_service import invalidate_ia_mode_cache
    invalidate_ia_mode_cache()
    yield
    invalidate_ia_mode_cache()


def _patch_get_db(monkeypatch, fetchone_result):
    """Stub de get_db que devuelve `fetchone_result` ante cualquier query."""
    class _Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return fetchone_result
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Conn:
        def cursor(self, *a, **k): return _Cur()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    @contextmanager
    def fake_get_db():
        yield _Conn()

    monkeypatch.setattr("app.database.get_db", fake_get_db)


class TestLoadIaMode:
    def test_default_es_auto_si_no_hay_row(self, monkeypatch):
        from app.services.wa_ia_mode_service import load_ia_mode
        _patch_get_db(monkeypatch, None)
        assert load_ia_mode() == "auto"

    def test_devuelve_manual_si_row_lo_dice(self, monkeypatch):
        from app.services.wa_ia_mode_service import load_ia_mode
        _patch_get_db(monkeypatch, ({"mode": "manual"},))
        assert load_ia_mode() == "manual"

    def test_ignora_valor_invalido_y_devuelve_default(self, monkeypatch):
        """Si la DB tiene 'mode': 'autopilot' (no valido), cae a default."""
        from app.services.wa_ia_mode_service import load_ia_mode
        _patch_get_db(monkeypatch, ({"mode": "autopilot"},))
        assert load_ia_mode() == "auto"

    def test_fallback_a_default_si_db_levanta(self, monkeypatch):
        """Si get_db levanta, no debe romper el webhook (best-effort)."""
        from app.services.wa_ia_mode_service import load_ia_mode

        @contextmanager
        def broken_get_db():
            raise RuntimeError("DB down")
            yield  # pragma: no cover
        monkeypatch.setattr("app.database.get_db", broken_get_db)
        assert load_ia_mode() == "auto"


class TestCacheBehavior:
    def test_cache_evita_segunda_query(self, monkeypatch):
        """Segunda llamada en <60s no debe re-leer la DB."""
        from app.services.wa_ia_mode_service import load_ia_mode

        calls = {"count": 0}

        class _Cur:
            def execute(self, *a, **k): calls["count"] += 1
            def fetchone(self): return ({"mode": "manual"},)
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class _Conn:
            def cursor(self, *a, **k): return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        @contextmanager
        def fake_get_db():
            yield _Conn()

        monkeypatch.setattr("app.database.get_db", fake_get_db)

        assert load_ia_mode() == "manual"
        assert calls["count"] == 1
        assert load_ia_mode() == "manual"  # cache hit
        assert calls["count"] == 1, "El cache no funciono — query repetida"

    def test_invalidate_fuerza_relectura(self, monkeypatch):
        from app.services.wa_ia_mode_service import (
            invalidate_ia_mode_cache,
            load_ia_mode,
        )
        calls = {"count": 0}

        class _Cur:
            def execute(self, *a, **k): calls["count"] += 1
            def fetchone(self): return ({"mode": "manual"},)
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class _Conn:
            def cursor(self, *a, **k): return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        @contextmanager
        def fake_get_db():
            yield _Conn()

        monkeypatch.setattr("app.database.get_db", fake_get_db)
        load_ia_mode()
        invalidate_ia_mode_cache()
        load_ia_mode()
        assert calls["count"] == 2

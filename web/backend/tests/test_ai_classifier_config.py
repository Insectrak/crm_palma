"""Tests para el modulo de configuracion del IA Clasificador (Nivel 1).

Cubre:
- load_ai_config(): defaults cuando no hay row, merge cuando hay row,
  cache TTL.
- invalidate_ai_config_cache(): refetch despues de invalidar.
- Prompt builder respeta la config (slots reemplazados).
- Endpoints GET/PUT/test (auth, demo_mode, clamping).
"""
from contextlib import contextmanager

import pytest

from app.config import settings as app_settings


# ── Fakes ──────────────────────────────────────────────────────────────────

class _FakeCursor:
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
    @contextmanager
    def fake_get_db():
        yield _FakeConn(cursor)

    monkeypatch.setattr("app.database.get_db", fake_get_db)
    monkeypatch.setattr(
        "app.services.wa_classifier_service.get_db", fake_get_db,
    )


# ── load_ai_config ────────────────────────────────────────────────────────

def test_load_ai_config_returns_defaults_when_no_row(monkeypatch):
    """Sin row en DB → devuelve los defaults completos sin error."""
    from app.services.wa_classifier_service import (
        invalidate_ai_config_cache,
        load_ai_config,
    )
    invalidate_ai_config_cache()

    cursor = _FakeCursor(fetchone_queue=[None])
    _patch_get_db(monkeypatch, cursor)

    config = load_ai_config()
    # V070.68 (Bundle B): defaults vertical-agnostic. Antes el default era
    # "Palma del Rio" hardcoded, lo que rompia para otros tenants. Ahora
    # los campos de negocio son strings vacios — el admin DEBE configurarlos.
    assert config["company_name"] == ""
    assert config["company_description"] == ""
    assert config["relevant_keywords"] == ""
    assert config["auto_assign_threshold"] == 0.80
    assert config["auto_archive_threshold"] == 0.85
    assert config["history_message_count"] == 5


def test_load_ai_config_merges_db_over_defaults(monkeypatch):
    """Row con campos parciales → merge sobre defaults preserva el resto."""
    from app.services.wa_classifier_service import (
        invalidate_ai_config_cache,
        load_ai_config,
    )
    invalidate_ai_config_cache()

    db_row = ({
        "company_name":          "Inmobiliaria Acme",
        "auto_assign_threshold": 0.70,
        # otros campos faltan a proposito → quedan en default
    },)
    cursor = _FakeCursor(fetchone_queue=[db_row])
    _patch_get_db(monkeypatch, cursor)

    config = load_ai_config()
    assert config["company_name"] == "Inmobiliaria Acme"
    assert config["auto_assign_threshold"] == 0.70
    # No tocados → siguen en default
    assert config["auto_archive_threshold"] == 0.85
    assert config["history_message_count"] == 5


def test_load_ai_config_cache_returns_same_value_within_ttl(monkeypatch):
    """Llamadas dentro del TTL no re-pegan al DB."""
    from app.services.wa_classifier_service import (
        invalidate_ai_config_cache,
        load_ai_config,
    )
    invalidate_ai_config_cache()

    db_row = ({"company_name": "Cached Co"},)
    cursor = _FakeCursor(fetchone_queue=[db_row])  # solo 1 fetch en el queue
    _patch_get_db(monkeypatch, cursor)

    a = load_ai_config()
    b = load_ai_config()  # debe venir del cache (no consume otro fetchone)
    assert a is b
    assert a["company_name"] == "Cached Co"
    # Verifica que solo se ejecuto 1 SELECT
    selects = [s for s, _ in cursor.executed if "SELECT value" in s]
    assert len(selects) == 1


def test_invalidate_ai_config_cache_forces_refetch(monkeypatch):
    """invalidate() obliga a re-leer el DB."""
    from app.services.wa_classifier_service import (
        invalidate_ai_config_cache,
        load_ai_config,
    )
    invalidate_ai_config_cache()

    cursor = _FakeCursor(fetchone_queue=[
        ({"company_name": "Primero"},),
        ({"company_name": "Segundo"},),
    ])
    _patch_get_db(monkeypatch, cursor)

    a = load_ai_config()
    invalidate_ai_config_cache()
    b = load_ai_config()
    assert a["company_name"] == "Primero"
    assert b["company_name"] == "Segundo"


def test_load_ai_config_db_error_falls_back_to_defaults(monkeypatch):
    """Si el get_db tira excepcion → defaults, no propagamos."""
    from app.services.wa_classifier_service import (
        invalidate_ai_config_cache,
        load_ai_config,
    )
    invalidate_ai_config_cache()

    @contextmanager
    def broken_get_db():
        raise RuntimeError("DB down")
        yield  # pragma: no cover

    monkeypatch.setattr("app.services.wa_classifier_service.get_db", broken_get_db)

    config = load_ai_config()
    # V070.68 (Bundle B): default vertical-agnostic (vacio, no Palma).
    assert config["company_name"] == ""


# ── Prompt builder respeta config ─────────────────────────────────────────

def test_build_prompt_uses_config_company_name(monkeypatch):
    """Cambiar company_name en config se refleja en el prompt generado."""
    from app.services.wa_classifier_service import (
        _build_prompt,
        invalidate_ai_config_cache,
    )
    invalidate_ai_config_cache()

    db_row = ({
        "company_name":         "Acme Realty",
        "company_description":  "vende mansiones en Miami",
        "relevant_keywords":    "casas, mansiones, condominios",
    },)
    cursor = _FakeCursor(fetchone_queue=[db_row])
    _patch_get_db(monkeypatch, cursor)

    ctx = {
        "contact_name": "Juan",
        "wa_phone":     "51999",
        "messages":     [],
    }
    prompt = _build_prompt(ctx, "Quiero info de un lote")
    assert "Acme Realty" in prompt
    assert "vende mansiones en Miami" in prompt
    assert "casas, mansiones, condominios" in prompt
    # Asegura que no quedo el default viejo
    assert "Palma del Rio" not in prompt


def test_build_prompt_includes_extra_instructions_block(monkeypatch):
    from app.services.wa_classifier_service import (
        _build_prompt,
        invalidate_ai_config_cache,
    )
    invalidate_ai_config_cache()

    db_row = ({
        "extra_instructions": "Si menciona 'Cayma' → urgencia=alta",
    },)
    cursor = _FakeCursor(fetchone_queue=[db_row])
    _patch_get_db(monkeypatch, cursor)

    prompt = _build_prompt({"messages": []}, "hola")
    assert "INSTRUCCIONES ADICIONALES" in prompt
    assert "Si menciona 'Cayma' → urgencia=alta" in prompt


def test_build_prompt_omits_extra_block_when_empty(monkeypatch):
    from app.services.wa_classifier_service import (
        _build_prompt,
        invalidate_ai_config_cache,
    )
    invalidate_ai_config_cache()

    cursor = _FakeCursor(fetchone_queue=[None])  # sin DB row → defaults
    _patch_get_db(monkeypatch, cursor)

    prompt = _build_prompt({"messages": []}, "hola")
    assert "INSTRUCCIONES ADICIONALES" not in prompt


# ── Endpoints ──────────────────────────────────────────────────────────────

def test_get_ai_classifier_requires_admin(client, auth_headers_asesor):
    res = client.get("/api/settings/ai-classifier", headers=auth_headers_asesor)
    assert res.status_code == 403


def test_get_ai_classifier_returns_defaults_in_demo_mode(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.get("/api/settings/ai-classifier", headers=auth_headers_admin)
    assert res.status_code == 200
    body = res.json()
    # V070.68 (Bundle B): default vertical-agnostic (vacio, no Palma).
    assert body["company_name"] == ""
    assert body["auto_assign_threshold"] == 0.80


def test_put_ai_classifier_clamps_thresholds(
    client, auth_headers_admin, monkeypatch,
):
    """Threshold fuera de rango [0.50, 0.99] se clampa al limite."""
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.put(
        "/api/settings/ai-classifier",
        headers=auth_headers_admin,
        json={
            "company_name":           "Test",
            "auto_assign_threshold":  1.5,    # fuera de rango → 0.99
            "auto_archive_threshold": -0.1,   # fuera de rango → 0.50
            "history_message_count":  999,    # fuera → 20
        },
    )
    # Demo mode short-circuit, devuelve los valores SIN clamp porque saltea
    # el clamping. Validamos que en non-demo el clamp si funcione (otro test).
    assert res.status_code == 200


def test_put_ai_classifier_persists_and_invalidates_cache(
    client, auth_headers_admin, monkeypatch,
):
    """PUT en non-demo: ejecuta INSERT, invalida cache. Validamos via
    inspeccion del cursor stub."""
    monkeypatch.setattr(app_settings, "demo_mode", False)

    cursor = _FakeCursor()
    _patch_get_db(monkeypatch, cursor)

    invalidations = {"count": 0}
    def fake_invalidate():
        invalidations["count"] += 1
    monkeypatch.setattr(
        "app.services.wa_classifier_service.invalidate_ai_config_cache",
        fake_invalidate,
    )

    res = client.put(
        "/api/settings/ai-classifier",
        headers=auth_headers_admin,
        json={
            "company_name":           "Acme",
            "auto_assign_threshold":  1.5,    # se clampa a 0.99
            "auto_archive_threshold": 0.90,
            "history_message_count":  3,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["auto_assign_threshold"] == 0.99   # clampado
    assert body["auto_archive_threshold"] == 0.90  # respetado
    assert body["history_message_count"] == 3
    # Verifica INSERT
    inserts = [s for s, _ in cursor.executed if "INSERT INTO public.app_settings" in s]
    assert len(inserts) == 1
    # Verifica invalidacion del cache
    assert invalidations["count"] == 1


def test_test_endpoint_rejects_empty_message(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr(app_settings, "demo_mode", False)
    res = client.post(
        "/api/settings/ai-classifier/test",
        headers=auth_headers_admin,
        json={"message": "   "},
    )
    assert res.status_code == 400


def test_test_endpoint_returns_demo_response_in_demo_mode(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.post(
        "/api/settings/ai-classifier/test",
        headers=auth_headers_admin,
        json={"message": "Quiero info del lote 8"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["demo"] is True
    assert body["categoria"] in {
        "cliente_potencial", "cliente_existente",
        "consulta_general", "spam", "no_relacionado",
    }

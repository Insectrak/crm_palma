"""Tests del driver y router de Meta (Facebook Lead Ads).

Cubren:
  - Firma HMAC-SHA256 (timing-safe, casos válidos / inválidos / mal formato).
  - verify_challenge_token (incluye empty-guard).
  - parse_leadgen_changes (payload oficial + shapes parciales).
  - normalize_field_data (full_name split, extras → observaciones).
  - GET /webhook: challenge OK, verify_token inválido → 403.
  - POST /webhook: firma inválida → 403, firma válida → 200 y encola tasks.
  - process_leadgen_event con ingest_core mockeado + fetch mockeado.

No tocan DB real. Corre con DEMO_MODE=true en CI.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest


# ── Firma HMAC ──────────────────────────────────────────────────────────────

def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_correct_sha256():
    from app.services.integrations.meta_service import verify_signature

    body = b'{"object":"page","entry":[]}'
    secret = "my-app-secret"
    header = _sign(body, secret)

    assert verify_signature(body, header, secret) is True


def test_verify_signature_rejects_tampered_body():
    from app.services.integrations.meta_service import verify_signature

    body = b'{"object":"page","entry":[]}'
    secret = "my-app-secret"
    header = _sign(body, secret)

    # Cambio silencioso del body
    tampered = b'{"object":"page","entry":[{}]}'
    assert verify_signature(tampered, header, secret) is False


def test_verify_signature_rejects_wrong_prefix():
    from app.services.integrations.meta_service import verify_signature

    body = b"{}"
    secret = "s"
    # Sin prefijo sha256=
    raw_digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, raw_digest, secret) is False
    # Prefijo incorrecto
    assert verify_signature(body, f"md5={raw_digest}", secret) is False


def test_verify_signature_rejects_empty_inputs():
    from app.services.integrations.meta_service import verify_signature

    assert verify_signature(b"x", None, "s") is False
    assert verify_signature(b"x", "", "s") is False
    assert verify_signature(b"x", "sha256=", "s") is False
    assert verify_signature(b"x", "sha256=abc", None) is False


# ── Challenge token ─────────────────────────────────────────────────────────

def test_verify_challenge_token_matches():
    from app.services.integrations.meta_service import verify_challenge_token

    assert verify_challenge_token("abc123", "abc123") is True


def test_verify_challenge_token_rejects_mismatch_and_empty():
    from app.services.integrations.meta_service import verify_challenge_token

    assert verify_challenge_token("abc", "xyz") is False
    assert verify_challenge_token(None, "abc") is False
    assert verify_challenge_token("abc", None) is False
    assert verify_challenge_token("", "") is False


# ── parse_leadgen_changes ───────────────────────────────────────────────────

_META_WEBHOOK_SAMPLE = {
    "object": "page",
    "entry": [
        {
            "id": "12345",
            "time": 1700000000,
            "changes": [
                {
                    "field": "leadgen",
                    "value": {
                        "leadgen_id": "lg-1",
                        "page_id": "12345",
                        "form_id": "form-1",
                        "ad_id": "ad-1",
                        "adset_id": "adset-1",
                        "campaign_id": "camp-1",
                        "created_time": 1700000001,
                    },
                }
            ],
        }
    ],
}


def test_parse_leadgen_changes_flattens_entries():
    from app.services.integrations.meta_service import parse_leadgen_changes

    out = parse_leadgen_changes(_META_WEBHOOK_SAMPLE)
    assert len(out) == 1
    c = out[0]
    assert c["leadgen_id"] == "lg-1"
    assert c["page_id"] == "12345"
    assert c["form_id"] == "form-1"
    assert c["campaign_id"] == "camp-1"


def test_parse_leadgen_changes_ignores_non_leadgen_fields():
    from app.services.integrations.meta_service import parse_leadgen_changes

    body = {
        "object": "page",
        "entry": [{
            "id": "p",
            "changes": [{"field": "feed", "value": {"leadgen_id": "x", "page_id": "p"}}],
        }],
    }
    assert parse_leadgen_changes(body) == []


def test_parse_leadgen_changes_skips_malformed():
    from app.services.integrations.meta_service import parse_leadgen_changes

    # No body, body raro, entry sin changes, value sin leadgen_id, etc.
    assert parse_leadgen_changes({}) == []
    assert parse_leadgen_changes({"entry": "not-a-list"}) == []
    assert parse_leadgen_changes({"entry": [{"changes": []}]}) == []
    assert parse_leadgen_changes(None) == []


def test_parse_leadgen_falls_back_to_entry_id_for_page_id():
    from app.services.integrations.meta_service import parse_leadgen_changes

    body = {
        "object": "page",
        "entry": [{
            "id": "page-from-entry",
            "changes": [{
                "field": "leadgen",
                "value": {"leadgen_id": "lg-x"},  # sin page_id
            }],
        }],
    }
    out = parse_leadgen_changes(body)
    assert len(out) == 1
    assert out[0]["page_id"] == "page-from-entry"


# ── normalize_field_data ────────────────────────────────────────────────────

def test_normalize_field_data_maps_standard_fields():
    from app.services.integrations.meta_service import normalize_field_data

    field_data = [
        {"name": "full_name",    "values": ["Juan Pérez García"]},
        {"name": "phone_number", "values": ["+51 987 654 321"]},
        {"name": "email",        "values": ["juan@example.com"]},
    ]
    p = normalize_field_data(field_data)
    assert p.nombres == "Juan"
    assert p.apellidos == "Pérez García"
    assert p.telefono == "+51 987 654 321"
    assert p.email == "juan@example.com"
    assert p.observaciones is None


def test_normalize_field_data_maps_whatsapp_number_fields():
    from app.services.integrations.meta_service import normalize_field_data

    field_data = [
        {"name": "full_name",       "values": ["Carlos Mendoza"]},
        {"name": "WHATSAPP NUMBER", "values": ["+51995834068"]},
        {"name": "email",           "values": ["carlos@example.com"]},
    ]
    p = normalize_field_data(field_data)
    assert p.telefono == "+51995834068"
    assert p.nombres == "Carlos"
    assert p.apellidos == "Mendoza"


def test_normalize_field_data_prefers_first_last_over_full_name():
    from app.services.integrations.meta_service import normalize_field_data

    field_data = [
        {"name": "first_name", "values": ["Ana"]},
        {"name": "last_name",  "values": ["Quispe"]},
        {"name": "full_name",  "values": ["Otro Nombre Distinto"]},
        {"name": "phone",      "values": ["987654321"]},
    ]
    p = normalize_field_data(field_data)
    assert p.nombres == "Ana"
    assert p.apellidos == "Quispe"


def test_normalize_field_data_accumulates_extras_in_observaciones():
    from app.services.integrations.meta_service import normalize_field_data

    field_data = [
        {"name": "phone_number", "values": ["987654321"]},
        {"name": "city",         "values": ["Arequipa"]},
        {"name": "ocupacion",    "values": ["Ingeniero"]},
    ]
    p = normalize_field_data(field_data, campana="camp-42")
    assert p.telefono == "987654321"
    assert "city: Arequipa" in p.observaciones
    assert "ocupacion: Ingeniero" in p.observaciones
    assert p.campana == "camp-42"


def test_normalize_field_data_handles_missing_values():
    from app.services.integrations.meta_service import normalize_field_data

    field_data = [
        {"name": "phone_number", "values": []},
        {"name": "email",        "values": ["x@x.com"]},
        {"name": "nope"},  # sin values
    ]
    p = normalize_field_data(field_data)
    assert p.telefono == ""
    assert p.email == "x@x.com"


# ── GET /webhook ────────────────────────────────────────────────────────────

def test_meta_webhook_verify_ok(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.integrations_meta.get_verify_token", lambda: "my-token"
    )
    # Evitamos escribir a la DB durante el test
    monkeypatch.setattr(
        "app.routers.integrations_meta.events_repo.log_event",
        lambda **kw: 0,
    )
    resp = client.get(
        "/api/integrations/meta/webhook",
        params={
            "hub.mode":         "subscribe",
            "hub.challenge":    "CH4LL3NGE",
            "hub.verify_token": "my-token",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "CH4LL3NGE"


def test_meta_webhook_verify_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.integrations_meta.get_verify_token", lambda: "my-token"
    )
    monkeypatch.setattr(
        "app.routers.integrations_meta.events_repo.log_event",
        lambda **kw: 0,
    )
    resp = client.get(
        "/api/integrations/meta/webhook",
        params={
            "hub.mode":         "subscribe",
            "hub.challenge":    "CH4LL3NGE",
            "hub.verify_token": "wrong",
        },
    )
    assert resp.status_code == 403


def test_meta_webhook_verify_rejects_missing_mode(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.integrations_meta.get_verify_token", lambda: "my-token"
    )
    resp = client.get(
        "/api/integrations/meta/webhook",
        params={"hub.challenge": "x", "hub.verify_token": "my-token"},
    )
    assert resp.status_code == 400


# ── POST /webhook ───────────────────────────────────────────────────────────

def test_meta_webhook_post_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.integrations_meta.get_app_secret", lambda: "secret"
    )
    monkeypatch.setattr(
        "app.routers.integrations_meta.events_repo.log_event",
        lambda **kw: 0,
    )
    resp = client.post(
        "/api/integrations/meta/webhook",
        content=b'{"object":"page","entry":[]}',
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert resp.status_code == 403


def test_meta_webhook_post_accepts_valid_signature_and_queues(client, monkeypatch):
    secret = "secret"
    body = json.dumps(_META_WEBHOOK_SAMPLE).encode("utf-8")
    sig = _sign(body, secret)

    monkeypatch.setattr(
        "app.routers.integrations_meta.get_app_secret", lambda: secret
    )
    monkeypatch.setattr(
        "app.routers.integrations_meta.events_repo.log_event",
        lambda **kw: 0,
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "app.routers.integrations_meta._handle_leadgen_change",
        lambda change: calls.append(change),
    )

    resp = client.post(
        "/api/integrations/meta/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["queued"] == 1

    # Las BackgroundTasks corren al cerrar el response del TestClient
    assert len(calls) == 1
    assert calls[0]["leadgen_id"] == "lg-1"
    assert calls[0]["page_id"] == "12345"


def test_meta_webhook_post_without_app_secret_returns_200(client, monkeypatch):
    """Sin app_secret configurado, devolvemos 200 para que Meta no reintente."""
    monkeypatch.setattr(
        "app.routers.integrations_meta.get_app_secret", lambda: None
    )
    monkeypatch.setattr(
        "app.routers.integrations_meta.events_repo.log_event",
        lambda **kw: 0,
    )
    resp = client.post(
        "/api/integrations/meta/webhook",
        content=b'{}',
        headers={"X-Hub-Signature-256": "sha256=00"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


# ── process_leadgen_event con Graph API mockeado ────────────────────────────

class _FakeCursor:
    def __init__(self):
        self.executed: list = []
    def execute(self, *a, **kw):
        self.executed.append(a)
    def fetchone(self):
        return None


def test_process_leadgen_event_logs_missing_token(monkeypatch):
    """Sin page_access_token → error + no se intenta fetch."""
    from app.services.integrations import meta_service

    monkeypatch.setattr(
        meta_service, "_resolve_page_access_token", lambda pid: None
    )
    logged: list = []
    monkeypatch.setattr(
        meta_service.events_repo, "log_event",
        lambda **kw: logged.append(kw) or 0,
    )

    result = meta_service.process_leadgen_event(
        cur=_FakeCursor(),
        leadgen_id="lg-x",
        page_id="page-unknown",
    )
    assert result["ok"] is False
    assert result["reason"] == "missing_page_access_token"
    assert logged and logged[0]["event_type"] == "error"


def test_process_leadgen_event_missing_phone_is_skipped(monkeypatch):
    from app.services.integrations import meta_service

    monkeypatch.setattr(
        meta_service, "_resolve_page_access_token", lambda pid: "tok"
    )
    monkeypatch.setattr(
        meta_service, "fetch_lead_details",
        lambda lg, tok, client=None: {
            "id": lg,
            "field_data": [
                {"name": "email", "values": ["x@x.com"]},
                {"name": "full_name", "values": ["Sin Telefono"]},
            ],
        },
    )
    logged: list = []
    monkeypatch.setattr(
        meta_service.events_repo, "log_event",
        lambda **kw: logged.append(kw) or 0,
    )

    result = meta_service.process_leadgen_event(
        cur=_FakeCursor(),
        leadgen_id="lg-2",
        page_id="page-1",
    )
    assert result["ok"] is False
    assert result["reason"] == "missing_phone"
    assert logged and logged[0]["status"] == "skipped"


def test_process_leadgen_event_creates_lead(monkeypatch):
    from app.services.integrations import meta_service

    monkeypatch.setattr(
        meta_service, "_resolve_page_access_token", lambda pid: "tok"
    )
    monkeypatch.setattr(
        meta_service, "fetch_lead_details",
        lambda lg, tok, client=None: {
            "id": lg,
            "form_id": "form-9",
            "campaign_id": "camp-9",
            "field_data": [
                {"name": "full_name",    "values": ["Ana Pérez"]},
                {"name": "phone_number", "values": ["987654321"]},
                {"name": "email",        "values": ["ana@x.com"]},
            ],
        },
    )

    # Stub de ingest_lead_core — captura el payload y devuelve un result fake
    captured: dict = {}
    def _fake_ingest(cur, payload):
        captured["payload"] = payload
        return {
            "duplicated":    False,
            "id":            777,
            "mode":          "rotacion",
            "asesor_id":     "u-1",
            "supervisor_id": "u-1",
            "nombres":       payload.nombres,
            "apellidos":     payload.apellidos,
        }
    monkeypatch.setattr(meta_service, "ingest_lead_core", _fake_ingest)

    events_logged: list = []
    monkeypatch.setattr(
        meta_service.events_repo, "log_event",
        lambda **kw: events_logged.append(kw) or 0,
    )

    result = meta_service.process_leadgen_event(
        cur=_FakeCursor(),
        leadgen_id="lg-9",
        page_id="page-1",
    )
    assert result["ok"] is True
    assert result["duplicated"] is False
    assert result["lead_id"] == 777

    # Mapping correcto a IngestPayload
    p = captured["payload"]
    assert p.telefono == "987654321"
    assert p.email == "ana@x.com"
    assert p.fuente_externa_id == "lg-9"
    assert p.campana == "camp-9"
    assert p.nombres == "Ana"
    assert p.apellidos == "Pérez"

    # Evento lead_created registrado
    assert any(e["event_type"] == "lead_created" for e in events_logged)


def test_process_leadgen_event_duplicated_lead(monkeypatch):
    from app.services.integrations import meta_service

    monkeypatch.setattr(
        meta_service, "_resolve_page_access_token", lambda pid: "tok"
    )
    monkeypatch.setattr(
        meta_service, "fetch_lead_details",
        lambda lg, tok, client=None: {
            "field_data": [
                {"name": "phone_number", "values": ["987654321"]},
            ],
        },
    )
    monkeypatch.setattr(
        meta_service, "ingest_lead_core",
        lambda cur, payload: {"duplicated": True, "id": 42},
    )
    logged: list = []
    monkeypatch.setattr(
        meta_service.events_repo, "log_event",
        lambda **kw: logged.append(kw) or 0,
    )

    result = meta_service.process_leadgen_event(
        cur=_FakeCursor(),
        leadgen_id="lg-d",
        page_id="page-1",
    )
    assert result["ok"] is True
    assert result["duplicated"] is True
    assert result["lead_id"] == 42
    assert any(e["event_type"] == "lead_duplicated" for e in logged)


# ── fetch_lead_details con httpx mockeado ──────────────────────────────────

class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_body
        self.text = text
    def json(self):
        return self._json


class _FakeHttpClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list = []
    def get(self, url, params=None):
        self.calls.append((url, params))
        return self._responses.pop(0)
    def close(self):
        pass


def test_fetch_lead_details_success():
    from app.services.integrations.meta_service import fetch_lead_details

    client = _FakeHttpClient([
        _FakeResponse(200, {"id": "lg-1", "field_data": []}),
    ])
    data = fetch_lead_details("lg-1", "tok", client=client)
    assert data["id"] == "lg-1"
    # El token debe viajar por query param
    assert client.calls[0][1]["access_token"] == "tok"


def test_fetch_lead_details_4xx_no_retry():
    from app.services.integrations.meta_service import (
        fetch_lead_details,
        MetaFetchError,
    )

    client = _FakeHttpClient([
        _FakeResponse(400, text="bad token"),
    ])
    with pytest.raises(MetaFetchError):
        fetch_lead_details("lg-1", "tok", client=client)
    assert len(client.calls) == 1  # no reintentó


def test_fetch_lead_details_empty_inputs():
    from app.services.integrations.meta_service import (
        fetch_lead_details,
        MetaFetchError,
    )

    with pytest.raises(MetaFetchError):
        fetch_lead_details("", "tok")
    with pytest.raises(MetaFetchError):
        fetch_lead_details("lg", "")


# ─────────────────────────────────────────────────────────────────────────────
# Enrichment de CTWA: resolve_ad_hierarchy + enrich_wa_campaign_by_ad_id
# ─────────────────────────────────────────────────────────────────────────────

class _FakeCursorWithCapture:
    """Cursor capturador de (sql, params). No necesita conexion."""
    def __init__(self, fetchone_values=None):
        self.executed: list[tuple[str, tuple]] = []
        self._fetchone = list(fetchone_values or [])
    def execute(self, sql, params=None):
        self.executed.append((sql, params))
    def fetchone(self):
        if not self._fetchone:
            return None
        return self._fetchone.pop(0)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _make_fake_response(status=200, json_body=None, content=b"{}"):
    resp = _FakeResponse(status, json_body=json_body, text="")
    resp.content = content
    return resp


def test_resolve_ad_hierarchy_parses_full_graph_shape():
    """Graph API devuelve ad.name + adset{id,name} + campaign{id,name} → dict."""
    from app.services.integrations import meta_catalog

    body = {
        "name":     "CTA WhatsApp - Video dron",
        "adset":    {"id": "adset_222", "name": "Adset Lima Norte"},
        "campaign": {"id": "camp_333",  "name": "Palma Rio - Abril 2026"},
        "creative": {"id": "cre_444", "body": "Conoce Palma Rio hoy!", "title": "Reserva ya"},
    }
    client = _FakeHttpClient([_make_fake_response(200, body, content=json.dumps(body).encode())])
    cur = _FakeCursorWithCapture()

    result = meta_catalog.resolve_ad_hierarchy(
        cur, ad_id="ad_111", access_token="tok_ads_read", client=client,
    )
    assert result == {
        "ad_name":        "CTA WhatsApp - Video dron",
        "adset_id":       "adset_222",
        "adset_name":     "Adset Lima Norte",
        "campaign_id":    "camp_333",
        "campaign_name":  "Palma Rio - Abril 2026",
        "creative_body":  "Conoce Palma Rio hoy!",
        "creative_title": "Reserva ya",
        "creative_thumbnail_url":   None,
        "creative_image_url":       None,
        "creative_video_id":        None,
        "creative_object_type":     None,
        "creative_object_story_id": None,
        "creative_media_type":      None,
    }
    # Token viaja por query param y pide los campos correctos en una sola llamada
    assert client.calls[0][1]["access_token"] == "tok_ads_read"
    assert "adset{id,name}" in client.calls[0][1]["fields"]
    assert "campaign{id,name}" in client.calls[0][1]["fields"]
    fields_requested = client.calls[0][1]["fields"]
    assert "creative{" in fields_requested
    assert "body" in fields_requested and "title" in fields_requested
    assert "thumbnail_url" in fields_requested
    # Upserteamos 3 filas en meta_catalog_cache (ad, adset, campaign)
    insert_rows = [e for e in cur.executed if "meta_catalog_cache" in e[0]]
    assert len(insert_rows) == 3


def test_resolve_ad_hierarchy_missing_inputs_returns_none():
    from app.services.integrations import meta_catalog
    cur = _FakeCursorWithCapture()
    assert meta_catalog.resolve_ad_hierarchy(cur, ad_id="", access_token="tok") is None
    assert meta_catalog.resolve_ad_hierarchy(cur, ad_id="ad_1", access_token="") is None


def test_resolve_ad_hierarchy_http_4xx_returns_none():
    """Graph API 400/403/404 → None, no cachea, no rompe."""
    from app.services.integrations import meta_catalog

    client = _FakeHttpClient([_make_fake_response(400, None, content=b"")])
    cur = _FakeCursorWithCapture()
    result = meta_catalog.resolve_ad_hierarchy(
        cur, ad_id="ad_xx", access_token="tok", client=client,
    )
    assert result is None
    # No se cachea nada porque no hubo respuesta valida
    assert not any("meta_catalog_cache" in e[0] for e in cur.executed)


def test_resolve_ad_hierarchy_partial_response_still_cached():
    """Si Graph devuelve solo ad.name sin adset/campaign, se cachea lo que hay."""
    from app.services.integrations import meta_catalog

    body = {"name": "Mi Ad"}
    client = _FakeHttpClient([_make_fake_response(200, body, content=json.dumps(body).encode())])
    cur = _FakeCursorWithCapture()

    result = meta_catalog.resolve_ad_hierarchy(
        cur, ad_id="ad_solo", access_token="tok", client=client,
    )
    assert result["ad_name"] == "Mi Ad"
    assert result["adset_id"] is None
    assert result["campaign_id"] is None
    # Solo se cachea el ad (1 fila)
    insert_rows = [e for e in cur.executed if "meta_catalog_cache" in e[0]]
    assert len(insert_rows) == 1


def test_enrich_wa_campaign_without_token_persists_reason(monkeypatch):
    """Sin ads_access_token configurado, la funcion devuelve no_token sin tocar Graph."""
    from app.services.integrations import meta_service

    monkeypatch.setattr(meta_service, "get_ads_access_token", lambda: None)

    persisted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        meta_service, "_persist_enrich_error",
        lambda ad_id, reason: persisted.append((ad_id, reason)),
    )

    result = meta_service.enrich_wa_campaign_by_ad_id("ad_999")
    assert result == {"ok": False, "reason": "no_token"}
    assert persisted == [("ad_999", "no_token")]


def test_enrich_wa_campaign_empty_ad_id_returns_early():
    from app.services.integrations import meta_service
    result = meta_service.enrich_wa_campaign_by_ad_id("")
    assert result == {"ok": False, "reason": "missing_ad_id"}


def test_enrich_wa_campaign_when_wa_campaign_missing(monkeypatch):
    """Token OK, pero el ad_id no esta en crm.wa_campaigns → wa_campaign_not_found."""
    from app.services.integrations import meta_service
    from contextlib import contextmanager

    monkeypatch.setattr(meta_service, "get_ads_access_token", lambda: "tok")

    # Fake DB: conn.cursor() devuelve un cursor cuya _load_wa_campaign_by_ad_id
    # entregara None (sin matches).
    class _FakeConn:
        def __init__(self, cur):
            self._cur = cur
        def cursor(self, cursor_factory=None):
            @contextmanager
            def _cm():
                yield self._cur
            return _cm()
        def commit(self):
            pass

    cur = _FakeCursorWithCapture(fetchone_values=[None])

    @contextmanager
    def _fake_db():
        yield _FakeConn(cur)

    monkeypatch.setattr(meta_service, "get_db", _fake_db)

    result = meta_service.enrich_wa_campaign_by_ad_id("ad_orphan")
    assert result == {"ok": False, "reason": "wa_campaign_not_found"}


def test_enrich_wa_campaign_happy_path_updates_row(monkeypatch):
    """Token OK + row existe + Graph responde → UPDATE con nombres resueltos."""
    from app.services.integrations import meta_service, meta_catalog
    from contextlib import contextmanager
    from datetime import datetime

    monkeypatch.setattr(meta_service, "get_ads_access_token", lambda: "tok")

    # Resolve_ad_hierarchy stub — no tocamos Graph real.
    hierarchy = {
        "ad_name":        "CTA Video Dron",
        "adset_id":       "adset_1",
        "adset_name":     "Lima Norte",
        "campaign_id":    "camp_1",
        "campaign_name":  "Palma Rio - Abril",
        "creative_body":  "Conoce Palma Rio hoy, cuotas desde S/ 990",
        "creative_title": "Reserva tu lote",
        "creative_media_type":      None,
        "creative_thumbnail_url":   None,
        "creative_image_url":       None,
        "creative_video_id":        None,
        "creative_object_type":     None,
        "creative_object_story_id": None,
    }
    monkeypatch.setattr(
        meta_catalog, "resolve_ad_hierarchy_with_debug",
        lambda cur, *, ad_id, access_token, client=None: (hierarchy, {"http_status": 200}),
    )

    # wa_campaign existente con fallback name="Ad ad_777" → DEBE promoverse a ad_name
    # V037: 7 columnas (se anaden creative_media_cached_at, creative_media_error).
    wa_row = (42, "Ad ad_777", "ad_777", None, None, None, None)

    class _FakeConn:
        def __init__(self, cur):
            self._cur = cur
        def cursor(self, cursor_factory=None):
            @contextmanager
            def _cm():
                yield self._cur
            return _cm()
        def commit(self):
            self._cur.committed = True

    cur = _FakeCursorWithCapture(fetchone_values=[wa_row])

    @contextmanager
    def _fake_db():
        yield _FakeConn(cur)

    monkeypatch.setattr(meta_service, "get_db", _fake_db)
    monkeypatch.setattr(
        meta_service.events_repo, "log_event",
        lambda **kw: None,
    )

    result = meta_service.enrich_wa_campaign_by_ad_id("ad_777")
    assert result["ok"] is True
    assert result["resolved"] == hierarchy
    # Debe haber ejecutado el UPDATE final con los 6 campos resueltos
    update_sql = [e for e in cur.executed if "UPDATE crm.wa_campaigns" in e[0] and "ad_name" in e[0]]
    assert len(update_sql) == 1
    params = update_sql[0][1]
    assert params[0] == "CTA Video Dron"             # ad_name
    assert params[3] == "camp_1"                     # meta_campaign_id
    assert params[4] == "Palma Rio - Abril"          # meta_campaign_name
    assert params[5] == "Conoce Palma Rio hoy, cuotas desde S/ 990"  # creative_body
    assert params[6] == "Reserva tu lote"            # creative_title
    # V037: nuevas posiciones 7..11 para creative_media_* (todas None en este fixture)
    assert params[7] is None                         # creative_media_type
    assert params[8] is None                         # creative_thumbnail_url
    assert params[9] is None                         # creative_image_url
    assert params[10] is None                        # creative_video_id
    assert params[11] is None                        # creative_object_story_id
    assert params[12] == "CTA Video Dron"            # new_display_name (fallback reemplazado)


def test_enrich_wa_campaign_skips_when_fresh_and_not_forced(monkeypatch):
    """Si enriched_at < 14 dias y force=False → corta con reason='fresh' sin pegarle a Graph."""
    from app.services.integrations import meta_service, meta_catalog
    from contextlib import contextmanager

    monkeypatch.setattr(meta_service, "get_ads_access_token", lambda: "tok")

    called: dict = {"graph": False}
    def _fail(*a, **kw):
        called["graph"] = True
        raise AssertionError("No deberia haberse llamado Graph API")
    monkeypatch.setattr(meta_catalog, "resolve_ad_hierarchy_with_debug", _fail)

    from datetime import datetime, timezone
    # row con enriched_at reciente (hoy) + age_days pequeno. V037: media ya
    # cacheada para evitar disparar el self-heal backfill y mantener el skip.
    wa_row = (7, "Label", "ad_7", datetime.now(timezone.utc), 0.1, datetime.now(timezone.utc), None)

    class _FakeConn:
        def __init__(self, cur):
            self._cur = cur
        def cursor(self, cursor_factory=None):
            @contextmanager
            def _cm():
                yield self._cur
            return _cm()
        def commit(self):
            pass

    cur = _FakeCursorWithCapture(fetchone_values=[wa_row])

    @contextmanager
    def _fake_db():
        yield _FakeConn(cur)

    monkeypatch.setattr(meta_service, "get_db", _fake_db)

    result = meta_service.enrich_wa_campaign_by_ad_id("ad_7", force=False)
    assert result == {"ok": True, "reason": "fresh", "resolved": None, "cached": True}
    assert called["graph"] is False

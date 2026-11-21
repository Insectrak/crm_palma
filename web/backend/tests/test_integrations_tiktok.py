"""Tests del driver TikTok y del scheduler de pollers.

Cubren:
  - normalize_tiktok_lead: phone/email/full_name split, campos extras,
    form_fields como lista de {name,value}, external_id.
  - fetch_leads: happy path, 4xx, respuesta con code!=0, inputs vacíos.
  - list_configured_advertisers y get_polling_interval_minutes:
    filtrado y clampeo.
  - poll_advertiser: sin token → error, fetch falla → checkpoint marca
    error, happy path con mix de duplicados / skipped / errors.
  - scheduler: start/stop idempotentes y graceful shutdown.

No tocan DB real. Mockeamos credentials_repo, checkpoint_repo,
events_repo y get_db.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


# ── normalize_tiktok_lead ───────────────────────────────────────────────────

def test_normalize_tiktok_lead_from_flat_payload():
    from app.services.integrations.tiktok_service import normalize_tiktok_lead

    raw = {
        "lead_id":      "lg-1",
        "phone_number": "987 654 321",
        "email":        "x@example.com",
        "full_name":    "Ana María Pérez",
        "campaign_id":  "camp-9",
    }
    payload, ext_id = normalize_tiktok_lead(raw)
    assert ext_id == "lg-1"
    assert payload.telefono == "987 654 321"
    assert payload.email == "x@example.com"
    assert payload.nombres == "Ana"
    assert payload.apellidos == "María Pérez"
    assert payload.campana == "camp-9"
    assert payload.fuente_externa_id == "lg-1"


def test_normalize_tiktok_lead_from_form_fields_list():
    from app.services.integrations.tiktok_service import normalize_tiktok_lead

    raw = {
        "lead_id":     "lg-2",
        "form_fields": [
            {"name": "phone",      "value": "+51987654321"},
            {"name": "email",      "value": "y@y.com"},
            {"name": "first_name", "value": "Pedro"},
            {"name": "last_name",  "value": "Quispe"},
            {"name": "ciudad",     "value": "Arequipa"},
        ],
    }
    payload, _ = normalize_tiktok_lead(raw)
    assert payload.telefono == "+51987654321"
    assert payload.email == "y@y.com"
    assert payload.nombres == "Pedro"
    assert payload.apellidos == "Quispe"
    assert "ciudad: Arequipa" in (payload.observaciones or "")


def test_normalize_tiktok_lead_missing_phone_returns_empty():
    from app.services.integrations.tiktok_service import normalize_tiktok_lead

    payload, ext_id = normalize_tiktok_lead({"lead_id": "x", "email": "e@e.com"})
    assert payload.telefono == ""
    assert payload.email == "e@e.com"
    assert ext_id == "x"


# ── fetch_leads (httpx mockeado, flujo task-based) ──────────────────────────
#
# El nuevo flujo dispara estas requests en orden:
#   1) GET  /page/get/                      → lista pages
#   2) POST /page/lead/task/                → crea task (devuelve task_id)
#   3) POST /page/lead/task/                → polea status (>=1 vez hasta SUCCEED)
#   4) GET  /page/lead/task/download/       → CSV body
# El _FakeHttpClient soporta GET+POST con cola de respuestas FIFO; los tests
# verifican tanto el contenido emitido (leads) como las URLs/params recibidos.

class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json = json_body
        self.text = text
    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


class _FakeHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
    def get(self, url, params=None, headers=None):
        self.calls.append({"method": "GET", "url": url, "params": params,
                           "headers": headers, "json": None})
        return self._responses.pop(0)
    def post(self, url, json=None, headers=None, params=None):
        self.calls.append({"method": "POST", "url": url, "params": params,
                           "headers": headers, "json": json})
        return self._responses.pop(0)
    def close(self):
        pass


# Helper: construye respuestas para el flujo end-to-end happy path
def _happy_responses(*, page_id="page-1", task_id="task-99", csv_rows=()):
    csv_lines = ["Phone Number,Email,Full Name,created_time"]
    for r in csv_rows:
        csv_lines.append(",".join(r))
    csv_body = "\n".join(csv_lines) + "\n"
    return [
        # 1) /page/get/ → 1 page
        _FakeResponse(200, {"code": 0, "data": {
            "list": [{"page_id": page_id, "title": "Form A"}],
            "page_info": {"total_page": 1},
        }}),
        # 2) /page/lead/task/ create → CREATED
        _FakeResponse(200, {"code": 0, "data": {
            "status": "CREATED", "task_id": task_id,
        }}),
        # 3) /page/lead/task/ poll → SUCCEED (1 sola iteración para test)
        _FakeResponse(200, {"code": 0, "data": {
            "status": "SUCCEED", "task_id": task_id,
            "file_name": "leads.csv", "file_type": "csv",
        }}),
        # 4) /page/lead/task/download/ → CSV
        _FakeResponse(200, text=csv_body),
    ]


def test_fetch_leads_happy_path_returns_csv_rows():
    from app.services.integrations.tiktok_service import fetch_leads

    client = _FakeHttpClient(_happy_responses(csv_rows=[
        ("+51987654321", "a@a.com", "Ana Perez", "2026-04-23T22:00:00Z"),
        ("+51999111222", "b@b.com", "Beto Lopez", "2026-04-23T22:30:00Z"),
    ]))
    leads = fetch_leads("adv-1", "tok", client=client, sleep=lambda _s: None)
    assert len(leads) == 2
    assert leads[0]["phone_number"] == "+51987654321"
    assert leads[0]["email"] == "a@a.com"
    assert leads[0]["full_name"] == "Ana Perez"
    # page_id se inyecta para trazabilidad downstream
    assert leads[0]["page_id"] == "page-1"
    # Verificar que el header Access-Token llega en cada call
    for c in client.calls:
        assert c["headers"]["Access-Token"] == "tok"
    # Endpoints golpeados en orden esperado
    urls = [c["url"] for c in client.calls]
    assert urls[0].endswith("/page/get/")
    assert urls[1].endswith("/page/lead/task/")
    assert urls[2].endswith("/page/lead/task/")
    assert urls[3].endswith("/page/lead/task/download/")
    # POSTs del task usan body JSON con advertiser_id
    assert client.calls[1]["json"]["advertiser_id"] == "adv-1"
    assert client.calls[1]["json"]["page_id"] == "page-1"
    assert client.calls[2]["json"]["task_id"] == "task-99"


def test_fetch_leads_no_pages_returns_empty():
    from app.services.integrations.tiktok_service import fetch_leads

    client = _FakeHttpClient([
        _FakeResponse(200, {"code": 0, "data": {
            "list": [], "page_info": {"total_page": 1},
        }}),
    ])
    assert fetch_leads("adv-1", "tok", client=client, sleep=lambda _s: None) == []


def test_fetch_leads_task_failed_skips_page():
    from app.services.integrations.tiktok_service import fetch_leads

    # 1 page → create OK → poll FAILED → no se descarga ni se levanta excepción
    client = _FakeHttpClient([
        _FakeResponse(200, {"code": 0, "data": {
            "list": [{"page_id": "p1"}], "page_info": {"total_page": 1},
        }}),
        _FakeResponse(200, {"code": 0, "data": {
            "status": "CREATED", "task_id": "t-fail",
        }}),
        _FakeResponse(200, {"code": 0, "data": {
            "status": "FAILED", "task_id": "t-fail",
        }}),
    ])
    assert fetch_leads("adv", "tok", client=client, sleep=lambda _s: None) == []


def test_fetch_leads_poll_timeout_skips_page():
    from app.services.integrations.tiktok_service import fetch_leads

    # /page/get/ + create + 7 polls que NUNCA completan (siempre RUNNING).
    # 7 polls = len(_TASK_POLL_BACKOFF_SECONDS) Fibonacci ~86s. Si baja, el
    # test perderia cobertura del path "task colgada agota retries y skipea".
    pending = lambda: _FakeResponse(200, {"code": 0, "data": {
        "status": "RUNNING", "task_id": "t-stuck",
    }})
    client = _FakeHttpClient([
        _FakeResponse(200, {"code": 0, "data": {
            "list": [{"page_id": "p1"}], "page_info": {"total_page": 1},
        }}),
        _FakeResponse(200, {"code": 0, "data": {
            "status": "CREATED", "task_id": "t-stuck",
        }}),
        pending(), pending(), pending(), pending(), pending(), pending(), pending(),
    ])
    assert fetch_leads("adv", "tok", client=client, sleep=lambda _s: None) == []


def test_fetch_leads_two_pages_aggregates_leads():
    from app.services.integrations.tiktok_service import fetch_leads

    csv_a = "phone_number,email\n+51900000001,x@x.com\n"
    csv_b = "phone_number,email\n+51900000002,y@y.com\n"
    client = _FakeHttpClient([
        # /page/get/ → 2 pages
        _FakeResponse(200, {"code": 0, "data": {
            "list": [{"page_id": "pA"}, {"page_id": "pB"}],
            "page_info": {"total_page": 1},
        }}),
        # Page A: create + poll SUCCEED + CSV
        _FakeResponse(200, {"code": 0, "data": {"status": "CREATED", "task_id": "tA"}}),
        _FakeResponse(200, {"code": 0, "data": {"status": "SUCCEED", "task_id": "tA"}}),
        _FakeResponse(200, text=csv_a),
        # Page B: create + poll SUCCEED + CSV
        _FakeResponse(200, {"code": 0, "data": {"status": "CREATED", "task_id": "tB"}}),
        _FakeResponse(200, {"code": 0, "data": {"status": "SUCCEED", "task_id": "tB"}}),
        _FakeResponse(200, text=csv_b),
    ])
    leads = fetch_leads("adv", "tok", client=client, sleep=lambda _s: None)
    assert len(leads) == 2
    page_ids = sorted(l["page_id"] for l in leads)
    assert page_ids == ["pA", "pB"]


def test_fetch_leads_download_returns_json_error_skips_page():
    from app.services.integrations.tiktok_service import fetch_leads

    # /page/get/ + create + poll SUCCEED + download que devuelve JSON error
    client = _FakeHttpClient([
        _FakeResponse(200, {"code": 0, "data": {
            "list": [{"page_id": "p1"}], "page_info": {"total_page": 1},
        }}),
        _FakeResponse(200, {"code": 0, "data": {"status": "CREATED", "task_id": "t1"}}),
        _FakeResponse(200, {"code": 0, "data": {"status": "SUCCEED", "task_id": "t1"}}),
        # CSV reemplazado por JSON de error (TikTok docs explicitamente lo permite)
        _FakeResponse(200, json_body={"code": 40000, "message": "task expired"},
                      text='{"code":40000,"message":"task expired"}'),
    ])
    # No debe levantar — la page se skipea y devuelve []
    assert fetch_leads("adv", "tok", client=client, sleep=lambda _s: None) == []


def test_fetch_leads_pages_endpoint_4xx_raises():
    from app.services.integrations.tiktok_service import fetch_leads, TikTokAPIError

    client = _FakeHttpClient([_FakeResponse(401, text="bad token")])
    with pytest.raises(TikTokAPIError):
        fetch_leads("adv", "tok", client=client, sleep=lambda _s: None)


def test_fetch_leads_pages_endpoint_code_not_zero_raises():
    from app.services.integrations.tiktok_service import fetch_leads, TikTokAPIError

    client = _FakeHttpClient([
        _FakeResponse(200, {"code": 40105, "message": "token expired"},
                      text='{"code":40105,"message":"token expired"}'),
    ])
    with pytest.raises(TikTokAPIError):
        fetch_leads("adv", "tok", client=client, sleep=lambda _s: None)


def test_fetch_leads_scope_error_40001_returns_friendly_message():
    """Cuando TikTok devuelve 40001 'does not grant ... permission', el error
    debe apuntar al fix (agregar scope Lead Generation) en lugar del crudo."""
    from app.services.integrations.tiktok_service import fetch_leads, TikTokAPIError

    client = _FakeHttpClient([
        _FakeResponse(200, {
            "code": 40001,
            "message": "advertiser does not grant you /page/get/:GET permission",
        }),
    ])
    with pytest.raises(TikTokAPIError) as exc_info:
        fetch_leads("adv", "tok", client=client, sleep=lambda _s: None)
    msg = str(exc_info.value)
    assert "Scope insuficiente" in msg
    assert "Lead Generation" in msg
    assert "re-autorizar" in msg


def test_fetch_leads_uses_pages_access_token_override_only_on_page_get():
    """Si se pasa `pages_access_token`, /page/get/ usa ese token y el resto
    de endpoints (task create/poll/download) siguen usando el access_token
    normal. Caso migrado del workflow viejo: dos apps TikTok, una con scope
    Pages (token override) y otra con scope Lead Generation (access_token).
    """
    from app.services.integrations.tiktok_service import fetch_leads

    client = _FakeHttpClient(_happy_responses(csv_rows=[
        ("+51987654321", "a@a.com", "Ana Perez", "2026-04-23T22:00:00Z"),
    ]))
    leads = fetch_leads(
        "adv-1", "lead-tok",
        client=client, sleep=lambda _s: None,
        pages_access_token="pages-tok",
    )
    assert len(leads) == 1
    # Primera call = /page/get/ con el token override
    assert client.calls[0]["url"].endswith("/page/get/")
    assert client.calls[0]["headers"]["Access-Token"] == "pages-tok"
    # Resto con el access_token normal
    for c in client.calls[1:]:
        assert c["headers"]["Access-Token"] == "lead-tok"


def test_fetch_leads_without_override_uses_access_token_everywhere():
    """Cuando no se pasa `pages_access_token`, el comportamiento es identico
    al previo — `access_token` se usa en TODAS las llamadas incluido /page/get/."""
    from app.services.integrations.tiktok_service import fetch_leads

    client = _FakeHttpClient(_happy_responses(csv_rows=[
        ("+51987654321", "a@a.com", "Ana Perez", "2026-04-23T22:00:00Z"),
    ]))
    fetch_leads("adv-1", "same-tok", client=client, sleep=lambda _s: None)
    for c in client.calls:
        assert c["headers"]["Access-Token"] == "same-tok"


def test_fetch_leads_rejects_empty_inputs():
    from app.services.integrations.tiktok_service import fetch_leads, TikTokAPIError

    with pytest.raises(TikTokAPIError):
        fetch_leads("", "tok")
    with pytest.raises(TikTokAPIError):
        fetch_leads("adv", "")


def test_parse_lead_csv_normalizes_headers_to_lowercase_snake():
    from app.services.integrations.tiktok_service import _parse_lead_csv

    rows = _parse_lead_csv(
        "Phone Number,Email Address,Full Name\n"
        "+51999,me@x.com,Juan Perez\n"
    )
    assert len(rows) == 1
    assert rows[0]["phone_number"] == "+51999"
    assert rows[0]["email_address"] == "me@x.com"
    assert rows[0]["full_name"] == "Juan Perez"


def test_parse_lead_csv_empty_returns_empty():
    from app.services.integrations.tiktok_service import _parse_lead_csv

    assert _parse_lead_csv("") == []
    assert _parse_lead_csv("   ") == []


# ── list_configured_advertisers + polling interval ─────────────────────────

def test_list_configured_advertisers_filters_access_tokens(monkeypatch):
    from app.services.integrations import tiktok_service

    fake_list = [
        # Solo este cuenta
        {"key": "access_token",       "account_id": "adv-1", "has_value": True,  "is_secret": True},
        # Mismo advertiser, key distinta — no cuenta
        {"key": "advertiser_name",    "account_id": "adv-1", "has_value": True,  "is_secret": False, "value": "Pepe"},
        # Sin valor — no cuenta
        {"key": "access_token",       "account_id": "adv-2", "has_value": False, "is_secret": True},
        # Otro con valor — sí cuenta
        {"key": "access_token",       "account_id": "adv-3", "has_value": True,  "is_secret": True},
        # Global — se ignora
        {"key": "app_secret",         "account_id": "_global", "has_value": True, "is_secret": True},
    ]
    monkeypatch.setattr(
        tiktok_service.credentials_repo, "list_credentials",
        lambda provider: fake_list,
    )
    assert tiktok_service.list_configured_advertisers() == ["adv-1", "adv-3"]


def test_polling_interval_clamps(monkeypatch):
    from app.services.integrations import tiktok_service

    monkeypatch.setattr(
        tiktok_service.credentials_repo, "get_plaintext",
        lambda *a, **kw: "1",
    )
    assert tiktok_service.get_polling_interval_minutes() == 5  # min

    monkeypatch.setattr(
        tiktok_service.credentials_repo, "get_plaintext",
        lambda *a, **kw: "9999",
    )
    assert tiktok_service.get_polling_interval_minutes() == 60  # max

    monkeypatch.setattr(
        tiktok_service.credentials_repo, "get_plaintext",
        lambda *a, **kw: None,
    )
    assert tiktok_service.get_polling_interval_minutes() == 10  # default


# ── poll_advertiser ────────────────────────────────────────────────────────

class _FakeCursor:
    def execute(self, *a, **kw): pass
    def fetchone(self): return None


class _FakeConn:
    def cursor(self, *a, **kw):
        class _Ctx:
            def __enter__(s): return _FakeCursor()
            def __exit__(s, *a): return False
        return _Ctx()
    def commit(self): pass


class _FakeDbCtx:
    def __enter__(self): return _FakeConn()
    def __exit__(self, *a): return False


def _install_db_stubs(monkeypatch):
    from app.services.integrations import tiktok_service
    monkeypatch.setattr(tiktok_service, "get_db", lambda: _FakeDbCtx())


def test_poll_advertiser_without_token_logs_error(monkeypatch):
    from app.services.integrations import tiktok_service

    monkeypatch.setattr(
        tiktok_service.credentials_repo, "get_plaintext",
        lambda *a, **kw: None,
    )
    logged: list = []
    monkeypatch.setattr(
        tiktok_service.events_repo, "log_event",
        lambda **kw: logged.append(kw) or 0,
    )
    result = tiktok_service.poll_advertiser("adv-x")
    assert result["ok"] is False
    assert result["reason"] == "missing_access_token"
    assert logged and logged[0]["event_type"] == "poll_error"


def test_poll_advertiser_fetch_failure_marks_checkpoint_error(monkeypatch):
    from app.services.integrations import tiktok_service

    monkeypatch.setattr(
        tiktok_service.credentials_repo, "get_plaintext",
        lambda *a, **kw: "tok",
    )
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "mark_run_start",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "get_checkpoint",
        lambda *a, **kw: None,
    )
    errors_marked: list = []
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "mark_run_error",
        lambda *a, **kw: errors_marked.append((a, kw)),
    )
    def _raise(*a, **kw):
        raise tiktok_service.TikTokAPIError("boom")
    monkeypatch.setattr(tiktok_service, "fetch_leads", _raise)

    events: list = []
    monkeypatch.setattr(
        tiktok_service.events_repo, "log_event",
        lambda **kw: events.append(kw) or 0,
    )

    result = tiktok_service.poll_advertiser("adv-1")
    assert result["ok"] is False
    assert result["reason"] == "fetch_failed"
    assert errors_marked, "Debería haberse marcado error en checkpoint."
    assert any(e["event_type"] == "poll_error" for e in events)


def test_poll_advertiser_happy_path_ingests_and_marks_success(monkeypatch):
    from app.services.integrations import tiktok_service

    monkeypatch.setattr(
        tiktok_service.credentials_repo, "get_plaintext",
        lambda *a, **kw: "tok",
    )
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "mark_run_start",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "get_checkpoint",
        lambda *a, **kw: None,
    )
    successes: list = []
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "mark_run_success",
        lambda **kw: successes.append(kw),
    )
    _install_db_stubs(monkeypatch)

    fake_leads = [
        {"lead_id": "a", "phone_number": "987654321", "full_name": "Ana P"},
        {"lead_id": "b", "phone_number": "987111222", "full_name": "Beto Q"},
        {"lead_id": "c", "email": "x@x.com"},  # sin phone → skipped
    ]
    monkeypatch.setattr(
        tiktok_service, "fetch_leads",
        lambda **kw: fake_leads,
    )

    # ingest_lead_core: primera llamada → created, segunda → duplicated
    calls = {"n": 0}
    def _fake_ingest(cur, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"duplicated": False, "id": 100, "asesor_id": "u", "supervisor_id": "u", "mode": "rotacion"}
        return {"duplicated": True, "id": 50}
    monkeypatch.setattr(tiktok_service, "ingest_lead_core", _fake_ingest)

    events: list = []
    monkeypatch.setattr(
        tiktok_service.events_repo, "log_event",
        lambda **kw: events.append(kw) or 0,
    )

    result = tiktok_service.poll_advertiser("adv-1")
    assert result["ok"] is True
    assert result["fetched"] == 3
    assert result["created"] == 1
    assert result["duplicated"] == 1
    assert result["skipped"] == 1

    assert successes, "Debería haberse marcado success en checkpoint."
    event_types = [e["event_type"] for e in events]
    assert "lead_created" in event_types
    assert "lead_duplicated" in event_types
    assert "poll_success" in event_types


def test_poll_advertiser_reads_and_propagates_pages_access_token(monkeypatch):
    """Si credentials_repo tiene `pages_access_token` para el advertiser,
    poll_advertiser lo lee y lo pasa a fetch_leads como kwarg."""
    from app.services.integrations import tiktok_service

    creds = {
        ("tiktok", "access_token", "adv-1"):        "lead-tok",
        ("tiktok", "pages_access_token", "adv-1"):  "pages-tok",
    }
    monkeypatch.setattr(
        tiktok_service.credentials_repo, "get_plaintext",
        lambda provider, key, account_id=None: creds.get((provider, key, account_id)),
    )
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "mark_run_start", lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "get_checkpoint", lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tiktok_service.checkpoint_repo, "mark_run_success", lambda **kw: None,
    )
    monkeypatch.setattr(
        tiktok_service.events_repo, "log_event", lambda **kw: 0,
    )
    _install_db_stubs(monkeypatch)

    captured: dict = {}
    def _capture_fetch(**kwargs):
        captured.update(kwargs)
        return []
    monkeypatch.setattr(tiktok_service, "fetch_leads", _capture_fetch)

    result = tiktok_service.poll_advertiser("adv-1")
    assert result["ok"] is True
    assert captured["access_token"] == "lead-tok"
    assert captured["pages_access_token"] == "pages-tok"


# ── Scheduler: start/stop graceful ─────────────────────────────────────────

def test_scheduler_start_stop_idle(monkeypatch):
    """Sin advertisers, el loop arranca, idlea y para sin errores."""
    from app.services.integrations import scheduler, tiktok_service

    monkeypatch.setattr(tiktok_service, "list_configured_advertisers", lambda: [])
    # Evitamos tocar Postgres: simulamos que este worker es el lider.
    monkeypatch.setattr(scheduler, "_try_become_leader", lambda: True)
    monkeypatch.setattr(scheduler, "_release_leader_lock", lambda: None)

    async def _run():
        scheduler.start()
        assert scheduler._tiktok_task is not None
        # Dejamos que el loop haga un ciclo (sin trabajo) y lo cortamos
        await asyncio.sleep(0.05)
        await scheduler.stop()
        assert scheduler._tiktok_task is None

    asyncio.run(_run())


def test_scheduler_start_is_idempotent(monkeypatch):
    from app.services.integrations import scheduler, tiktok_service

    monkeypatch.setattr(tiktok_service, "list_configured_advertisers", lambda: [])
    monkeypatch.setattr(scheduler, "_try_become_leader", lambda: True)
    monkeypatch.setattr(scheduler, "_release_leader_lock", lambda: None)

    async def _run():
        scheduler.start()
        first = scheduler._tiktok_task
        scheduler.start()  # no debería crear otra tarea
        assert scheduler._tiktok_task is first
        await scheduler.stop()

    asyncio.run(_run())


def test_scheduler_standby_skips_poll_when_not_leader(monkeypatch):
    """Si otro worker tiene el lock, este loop idlea sin llamar al poller."""
    from app.services.integrations import scheduler, tiktok_service

    called: list = []
    monkeypatch.setattr(scheduler, "_try_become_leader", lambda: False)
    monkeypatch.setattr(scheduler, "_release_leader_lock", lambda: None)
    monkeypatch.setattr(
        tiktok_service, "list_configured_advertisers",
        lambda: called.append("listed") or ["adv-1"],
    )
    monkeypatch.setattr(
        tiktok_service, "poll_advertiser",
        lambda adv: called.append(adv) or {"ok": True},
    )

    async def _run():
        scheduler.start()
        await asyncio.sleep(0.05)
        await scheduler.stop()

    asyncio.run(_run())
    # En standby no debe haber llamado poll_advertiser; solo el listado
    # interno del ciclo no corre tampoco porque el standby va directo a sleep.
    assert "adv-1" not in called


def test_scheduler_invokes_poll_for_each_advertiser(monkeypatch):
    from app.services.integrations import scheduler, tiktok_service

    called: list = []
    monkeypatch.setattr(
        tiktok_service, "list_configured_advertisers",
        lambda: ["adv-1", "adv-2"],
    )
    monkeypatch.setattr(
        tiktok_service, "poll_advertiser",
        lambda adv: called.append(adv) or {"ok": True, "fetched": 0},
    )

    async def _run():
        await scheduler._run_tiktok_poll_cycle()

    asyncio.run(_run())
    assert set(called) == {"adv-1", "adv-2"}


# ── Endpoint admin: POST /tiktok/advertisers/{id}/poll ───────────────────────

def test_tiktok_manual_poll_returns_summary_when_ok(client, auth_headers_admin, monkeypatch):
    """ok=True del servicio se traduce en HTTP 200 con el resumen."""
    from app.services.integrations import tiktok_service

    captured: dict = {}
    # **kwargs absorbe lookback_hours/since_override que el endpoint pasa
    # cuando vienen como query params (V038+). Sin esto, los tests viejos
    # rompian con TypeError aunque el comportamiento del endpoint era OK.
    def _fake_poll(adv, **kwargs):
        captured["advertiser_id"] = adv
        captured["kwargs"] = kwargs
        return {
            "ok": True, "fetched": 3, "created": 2, "duplicated": 1,
            "skipped": 0, "errors": 0, "latency_ms": 123,
        }
    monkeypatch.setattr(tiktok_service, "poll_advertiser", _fake_poll)

    res = client.post(
        "/api/integrations/tiktok/advertisers/adv-XYZ/poll",
        headers=auth_headers_admin,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["fetched"] == 3 and body["created"] == 2 and body["duplicated"] == 1
    assert captured["advertiser_id"] == "adv-XYZ"


def test_tiktok_manual_poll_returns_400_when_missing_token(client, auth_headers_admin, monkeypatch):
    """ok=False del servicio se traduce en HTTP 400 (cliente debe corregir)."""
    from app.services.integrations import tiktok_service
    monkeypatch.setattr(
        tiktok_service, "poll_advertiser",
        lambda adv, **kwargs: {"ok": False, "reason": "missing_access_token", "advertiser_id": adv},
    )
    res = client.post(
        "/api/integrations/tiktok/advertisers/adv-noauth/poll",
        headers=auth_headers_admin,
    )
    assert res.status_code == 400
    assert res.json()["reason"] == "missing_access_token"


def test_tiktok_manual_poll_requires_admin(client, auth_headers_asesor):
    """Roles no-admin no pueden disparar polls manuales."""
    res = client.post(
        "/api/integrations/tiktok/advertisers/adv-1/poll",
        headers=auth_headers_asesor,
    )
    # require_admin responde 403 al asesor.
    assert res.status_code in (401, 403)


def test_tiktok_manual_poll_requires_auth(client):
    """Sin token, 401."""
    res = client.post("/api/integrations/tiktok/advertisers/adv-1/poll")
    assert res.status_code in (401, 403)


# ── Service: build_authorize_url + exchange_auth_code + save_oauth_result ──

def test_build_authorize_url_includes_required_params():
    from app.services.integrations.tiktok_service import build_authorize_url

    url = build_authorize_url(
        app_id="APP123",
        redirect_uri="https://crm.example.com/cb",
        state="state-nonce",
    )
    assert url.startswith("https://business-api.tiktok.com/portal/auth?")
    assert "app_id=APP123" in url
    assert "state=state-nonce" in url
    # La URI va URL-encoded — se acepta tanto el encoding estándar como
    # el canonical de httpx.
    assert ("redirect_uri=https%3A%2F%2Fcrm.example.com%2Fcb" in url
            or "redirect_uri=https://crm.example.com/cb" in url)


def test_build_authorize_url_rejects_missing_inputs():
    from app.services.integrations.tiktok_service import build_authorize_url, TikTokAPIError

    with pytest.raises(TikTokAPIError):
        build_authorize_url("", "https://x", "s")
    with pytest.raises(TikTokAPIError):
        build_authorize_url("APP", "", "s")
    with pytest.raises(TikTokAPIError):
        build_authorize_url("APP", "https://x", "")


class _FakePostClient:
    """Cliente mínimo compatible con exchange_auth_code (solo .post, .close)."""
    def __init__(self, response):
        self._response = response
        self.calls = []
    def post(self, url, json=None):
        self.calls.append({"url": url, "json": json})
        return self._response
    def close(self):
        pass


def test_exchange_auth_code_happy_path():
    from app.services.integrations.tiktok_service import exchange_auth_code

    client = _FakePostClient(_FakeResponse(200, {
        "code": 0,
        "data": {
            "access_token":   "TOK-long-lived",
            "advertiser_ids": ["7000000000001", "7000000000002"],
            "scope":          [1, 2, 4],
        },
    }))
    result = exchange_auth_code("APP", "SECRET", "AC-123", client=client)
    assert result["access_token"] == "TOK-long-lived"
    assert result["advertiser_ids"] == ["7000000000001", "7000000000002"]
    body = client.calls[0]["json"]
    assert body == {"app_id": "APP", "secret": "SECRET", "auth_code": "AC-123"}


def test_exchange_auth_code_raises_on_api_error_code():
    from app.services.integrations.tiktok_service import exchange_auth_code, TikTokAPIError

    client = _FakePostClient(_FakeResponse(200, {
        "code": 40001, "message": "invalid auth_code",
    }))
    with pytest.raises(TikTokAPIError):
        exchange_auth_code("APP", "SECRET", "AC-bad", client=client)


def test_exchange_auth_code_raises_on_http_4xx():
    from app.services.integrations.tiktok_service import exchange_auth_code, TikTokAPIError

    client = _FakePostClient(_FakeResponse(400, text="bad request"))
    with pytest.raises(TikTokAPIError):
        exchange_auth_code("APP", "SECRET", "AC", client=client)


def test_exchange_auth_code_rejects_missing_inputs():
    from app.services.integrations.tiktok_service import exchange_auth_code, TikTokAPIError

    with pytest.raises(TikTokAPIError):
        exchange_auth_code("", "S", "C")
    with pytest.raises(TikTokAPIError):
        exchange_auth_code("A", "", "C")
    with pytest.raises(TikTokAPIError):
        exchange_auth_code("A", "S", "")


def test_save_oauth_result_persists_one_entry_per_advertiser(monkeypatch):
    from app.services.integrations import tiktok_service

    upserts: list = []
    monkeypatch.setattr(
        tiktok_service.credentials_repo, "upsert_credential",
        lambda **kw: upserts.append(kw) or {"ok": True},
    )
    events: list = []
    monkeypatch.setattr(
        tiktok_service.events_repo, "log_event",
        lambda **kw: events.append(kw),
    )

    saved = tiktok_service.save_oauth_result(
        oauth_result={
            "access_token":   "TOK",
            "advertiser_ids": ["adv-1", "adv-2"],
        },
        updated_by="admin-uuid",
    )
    assert saved == ["adv-1", "adv-2"]
    assert [u["account_id"] for u in upserts] == ["adv-1", "adv-2"]
    assert all(u["key"] == "access_token" and u["value"] == "TOK" for u in upserts)
    # Un evento oauth_connected por advertiser.
    assert sum(1 for e in events if e["event_type"] == "oauth_connected") == 2


def test_save_oauth_result_continues_on_single_failure(monkeypatch):
    from app.services.integrations import tiktok_service

    def _upsert(**kw):
        if kw["account_id"] == "adv-bad":
            raise RuntimeError("db down for this one")
        return {"ok": True}
    monkeypatch.setattr(
        tiktok_service.credentials_repo, "upsert_credential", _upsert,
    )
    events: list = []
    monkeypatch.setattr(
        tiktok_service.events_repo, "log_event",
        lambda **kw: events.append(kw),
    )

    saved = tiktok_service.save_oauth_result(
        oauth_result={
            "access_token":   "TOK",
            "advertiser_ids": ["adv-1", "adv-bad", "adv-3"],
        },
    )
    assert saved == ["adv-1", "adv-3"]
    # oauth_error para adv-bad + oauth_connected para adv-1 y adv-3.
    errors = [e for e in events if e["event_type"] == "oauth_error"]
    connected = [e for e in events if e["event_type"] == "oauth_connected"]
    assert len(errors) == 1 and errors[0]["account_id"] == "adv-bad"
    assert len(connected) == 2


def test_save_oauth_result_rejects_empty_response():
    from app.services.integrations.tiktok_service import save_oauth_result, TikTokAPIError

    with pytest.raises(TikTokAPIError):
        save_oauth_result(oauth_result={})
    with pytest.raises(TikTokAPIError):
        save_oauth_result(oauth_result={"access_token": "TOK"})  # sin advertiser_ids


def test_save_oauth_result_error_message_includes_diagnostic():
    """Cuando falta advertiser_ids, el error debe incluir scope/keys visibles
    en la UI del historial de eventos — ayuda al admin a diagnosticar sin
    mirar logs del backend."""
    from app.services.integrations.tiktok_service import save_oauth_result, TikTokAPIError

    with pytest.raises(TikTokAPIError) as exc_info:
        save_oauth_result(oauth_result={
            "access_token": "very-long-token-xxxxxxxxxxxxxxxxxxxx",
            "scope":        [4, 100007],
            "bc_id":        "BC-42",
        })
    msg = str(exc_info.value)
    assert "scope" in msg
    assert "bc_id" in msg
    assert "keys" in msg
    # El token nunca debe aparecer en claro en el mensaje.
    assert "very-long-token-xxxxxxxxxxxxxxxxxxxx" not in msg


def test_summarize_oauth_result_masks_token():
    from app.services.integrations.tiktok_service import summarize_oauth_result

    out = summarize_oauth_result({
        "access_token":     "abcdef1234567890ZZZZ",
        "advertiser_ids":   ["a1", "a2"],
        "scope":            [4],
        "bc_id":            "BC-1",
        "token_expired_at": 1234567890,
    })
    assert out["token_preview"] == "abcdef...ZZZZ"
    assert "access_token" not in str(out["token_preview"])
    assert out["advertiser_count"] == 2
    assert out["scope"] == [4]
    assert out["bc_id"] == "BC-1"
    assert "access_token" in out["keys"]


def test_summarize_oauth_result_handles_short_token_and_non_dict():
    from app.services.integrations.tiktok_service import summarize_oauth_result

    # Token corto → no se puede hacer preview, expone solo longitud.
    out_short = summarize_oauth_result({"access_token": "abc"})
    assert "len=" in out_short["token_preview"]
    assert out_short["advertiser_count"] is None

    # Input que no es dict (edge case, TikTok API rara).
    out_bad = summarize_oauth_result("not-a-dict")
    assert out_bad == {"type": "str"}


# ── Router: POST /tiktok/oauth/authorize ────────────────────────────────────

def test_oauth_authorize_returns_url_and_state(client, auth_headers_admin, monkeypatch):
    from app.services.integrations import tiktok_service, credentials_repo

    def _get_plain(provider, key, account_id="_global"):
        if key == "app_id": return "APP123"
        return None
    monkeypatch.setattr(credentials_repo, "get_plaintext", _get_plain)

    captured: dict = {}
    def _fake_build(app_id, redirect_uri, state, **_):
        captured["app_id"] = app_id
        captured["redirect_uri"] = redirect_uri
        captured["state"] = state
        return f"https://business-api.tiktok.com/portal/auth?app_id={app_id}&state={state}"
    monkeypatch.setattr(tiktok_service, "build_authorize_url", _fake_build)

    res = client.post(
        "/api/integrations/tiktok/oauth/authorize",
        headers=auth_headers_admin,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["authorize_url"].startswith("https://business-api.tiktok.com/portal/auth?")
    assert body["state"] and isinstance(body["state"], str)
    assert body["redirect_uri"].endswith("/api/integrations/tiktok/oauth/callback")
    # El state que recibe build_authorize_url es el mismo que el que retornamos
    assert captured["state"] == body["state"]


def test_oauth_authorize_fails_without_app_id(client, auth_headers_admin, monkeypatch):
    from app.services.integrations import credentials_repo
    monkeypatch.setattr(
        credentials_repo, "get_plaintext",
        lambda *a, **kw: None,
    )
    res = client.post(
        "/api/integrations/tiktok/oauth/authorize",
        headers=auth_headers_admin,
    )
    assert res.status_code == 400
    assert "app_id" in (res.json().get("detail") or "").lower()


def test_oauth_authorize_requires_admin(client, auth_headers_asesor):
    res = client.post(
        "/api/integrations/tiktok/oauth/authorize",
        headers=auth_headers_asesor,
    )
    assert res.status_code in (401, 403)


# ── Router: GET /tiktok/oauth/callback ──────────────────────────────────────

def _issue_state_for_test(user_id="00000000-0000-0000-0000-000000000001",
                          email="admin@test.local", role="admin",
                          purpose="tiktok_oauth", exp_delta_s=300):
    """Emite un state JWT compatible con _verify_state_token del router."""
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.config import settings
    now = datetime.now(timezone.utc)
    payload = {
        "sub":     user_id,
        "email":   email,
        "role":    role,
        "purpose": purpose,
        "nonce":   "test-nonce",
        "iat":     int(now.timestamp()),
        "exp":     int((now + timedelta(seconds=exp_delta_s)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def test_oauth_callback_happy_path_saves_and_redirects(client, monkeypatch):
    from app.services.integrations import tiktok_service, credentials_repo

    def _get_plain(provider, key, account_id="_global"):
        if key == "app_id": return "APP"
        if key == "app_secret": return "SEC"
        return None
    monkeypatch.setattr(credentials_repo, "get_plaintext", _get_plain)

    captured: dict = {}
    def _fake_exchange(app_id, app_secret, auth_code, **_):
        captured["auth_code"] = auth_code
        return {"access_token": "TOK", "advertiser_ids": ["7001", "7002"]}
    monkeypatch.setattr(tiktok_service, "exchange_auth_code", _fake_exchange)

    saved_calls: list = []
    def _fake_save(*, oauth_result, updated_by=None):
        saved_calls.append({"oauth_result": oauth_result, "updated_by": updated_by})
        return [str(a) for a in oauth_result["advertiser_ids"]]
    monkeypatch.setattr(tiktok_service, "save_oauth_result", _fake_save)

    state = _issue_state_for_test()
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"auth_code": "AC-OK", "state": state},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303, 307)
    loc = res.headers["location"]
    assert "oauth=ok" in loc
    assert "advertisers=2" in loc
    assert captured["auth_code"] == "AC-OK"
    assert saved_calls and saved_calls[0]["updated_by"] == "00000000-0000-0000-0000-000000000001"


def test_oauth_callback_accepts_code_param_alias(client, monkeypatch):
    """TikTok a veces manda `code` en vez de `auth_code`."""
    from app.services.integrations import tiktok_service, credentials_repo

    monkeypatch.setattr(
        credentials_repo, "get_plaintext",
        lambda provider, key, account_id="_global": "X",
    )
    monkeypatch.setattr(
        tiktok_service, "exchange_auth_code",
        lambda **kw: {"access_token": "T", "advertiser_ids": ["adv-1"]},
    )
    monkeypatch.setattr(
        tiktok_service, "save_oauth_result",
        lambda **kw: ["adv-1"],
    )

    state = _issue_state_for_test()
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"code": "AC-ALT", "state": state},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303, 307)
    assert "oauth=ok" in res.headers["location"]


def test_oauth_callback_with_error_param_redirects_to_ui(client):
    """Si el usuario cancela o TikTok devuelve error, redirige sin exchange."""
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"error": "access_denied",
                "error_description": "user cancelled"},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303, 307)
    loc = res.headers["location"]
    assert "oauth=error" in loc
    assert "access_denied" in loc


def test_oauth_callback_rejects_bad_state(client):
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"auth_code": "AC", "state": "not-a-jwt"},
    )
    assert res.status_code == 400


def test_oauth_callback_rejects_state_with_wrong_purpose(client):
    state = _issue_state_for_test(purpose="some_other_flow")
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"auth_code": "AC", "state": state},
    )
    assert res.status_code == 400


def test_oauth_callback_rejects_state_from_non_admin(client):
    state = _issue_state_for_test(role="asesor")
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"auth_code": "AC", "state": state},
    )
    assert res.status_code == 403


def test_oauth_callback_redirects_on_missing_app_credentials(client, monkeypatch):
    from app.services.integrations import credentials_repo
    monkeypatch.setattr(
        credentials_repo, "get_plaintext",
        lambda *a, **kw: None,
    )
    state = _issue_state_for_test()
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"auth_code": "AC", "state": state},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303, 307)
    loc = res.headers["location"]
    assert "oauth=error" in loc
    assert "missing_app_credentials" in loc


def test_oauth_callback_requires_auth_code_or_code(client):
    state = _issue_state_for_test()
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"state": state},
    )
    assert res.status_code == 400


def test_oauth_callback_redirects_when_exchange_fails(client, monkeypatch):
    from app.services.integrations import tiktok_service, credentials_repo

    monkeypatch.setattr(
        credentials_repo, "get_plaintext",
        lambda provider, key, account_id="_global": "X",
    )
    def _raise(**kw):
        raise tiktok_service.TikTokAPIError("upstream 502")
    monkeypatch.setattr(tiktok_service, "exchange_auth_code", _raise)

    state = _issue_state_for_test()
    res = client.get(
        "/api/integrations/tiktok/oauth/callback",
        params={"auth_code": "AC", "state": state},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303, 307)
    assert "oauth=error" in res.headers["location"]
    assert "exchange_failed" in res.headers["location"]

"""
Tests del cuerpo del endpoint POST /api/ingest/leads.

Estrategia: usamos app.dependency_overrides para reemplazar
authenticate_ingest con un mock que devuelve un IngestAuth controlado.
Esto evita tocar la DB en el Depends.

Cubre:
  - Schema validation: body sin telefono -> 422.
  - Fuente resolution: body vacio + client sin default -> 400.
  - Idempotency: misma key devuelve cache sin re-procesar (200/201).
"""
import pytest

from app.routers.ingest import IngestAuth, authenticate_ingest


HEADERS = {"X-Api-Key": "cli_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}


@pytest.fixture()
def override_auth(app_instance):
    """Override de authenticate_ingest. Caller pasa el client dict deseado;
    la fixture limpia el override al final del test."""
    def _override(**client_overrides):
        client = {
            "id":                     "00000000-0000-0000-0000-000000000001",
            "api_key_prefix":         "cli_test",
            "fuente_id":              None,
            "sede_id_default":        None,
            "rate_limit_per_minute":  60,
            "webhook_url":            None,
            "webhook_enabled":        False,
            "webhook_secret":         "",
            "webhook_events":         [],
        }
        client.update(client_overrides)
        app_instance.dependency_overrides[authenticate_ingest] = (
            lambda: IngestAuth(client=client, key_prefix="cli_test")
        )
        return client
    yield _override
    app_instance.dependency_overrides.pop(authenticate_ingest, None)


@pytest.mark.ingest
@pytest.mark.unit
def test_ingest_body_missing_telefono_returns_422(client, override_auth):
    """Pydantic exige 'telefono'. Sin ese campo -> 422 antes de tocar logica."""
    override_auth()

    response = client.post(
        "/api/ingest/leads",
        headers=HEADERS,
        json={"fuente": "facebook"},  # falta telefono
    )
    assert response.status_code == 422
    # Pydantic indica que telefono es required
    body = response.json()
    assert any("telefono" in str(err).lower() for err in body.get("detail", []))


@pytest.mark.ingest
@pytest.mark.unit
def test_ingest_body_missing_fuente_and_no_default_returns_400(
    client, override_auth,
):
    """Body sin 'fuente' Y client sin fuente_id default -> 400 con mensaje
    procesable por el provider."""
    override_auth(fuente_id=None)

    response = client.post(
        "/api/ingest/leads",
        headers=HEADERS,
        json={"fuente": "", "telefono": "+51999888777"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "fuente" in detail


@pytest.mark.ingest
@pytest.mark.unit
@pytest.mark.regression
def test_ingest_accepts_fuente_form_id_and_campaign_name(
    client, override_auth, monkeypatch,
):
    """V096 — Bug ID: pre-PR Wedo. Wedo manda fuente_form_id y campaign_name
    pero el schema IngestLead no los declaraba, Pydantic los descartaba
    silenciosamente y Juan no veia el formulario en el CRM.

    Regresion: capturamos el IngestPayload que el router pasa al core y
    verificamos que los 2 campos llegan con su valor exacto.
    """
    override_auth()

    captured = {}

    def fake_core(cur, payload):
        captured["payload"] = payload
        return {
            "duplicated": False, "id": 7821, "mode": "rotacion",
            "asesor_id": None, "supervisor_id": "fake",
            "nombres": "Cesar", "apellidos": "Enriquez",
        }

    monkeypatch.setattr(
        "app.routers.ingest.ingest_lead_core", fake_core,
    )
    monkeypatch.setattr(
        "app.routers.ingest.api_clients.log_request",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.routers.ingest.api_clients.increment_metrics",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "app.routers.ingest.get_db",
        lambda: _NoopDb(),
    )
    # Mute push notification (no es el SUT)
    monkeypatch.setattr(
        "app.services.notification_service.notify_new_lead",
        lambda *a, **kw: False,
    )

    response = client.post(
        "/api/ingest/leads",
        headers=HEADERS,
        json={
            "fuente": "ig",
            "telefono": "+51998069935",
            "nombres": "Cesar",
            "apellidos": "Enriquez",
            "campana": "120211234567890",
            "campaign_name": "Camp. Segunda Vivienda & Estilo de Vida",
            "fuente_form_id": "1234567890123456",
            "form_name": "We do - Segunda Vivienda - V 4",
            "fuente_externa_id": "881958194328318",
        },
    )

    assert response.status_code == 201
    p = captured["payload"]
    assert p.fuente_form_id == "1234567890123456"
    assert p.campaign_name  == "Camp. Segunda Vivienda & Estilo de Vida"
    assert p.form_name      == "We do - Segunda Vivienda - V 4"
    assert p.campana        == "120211234567890"
    assert p.fuente_externa_id == "881958194328318"


@pytest.mark.ingest
@pytest.mark.unit
def test_ingest_without_new_fields_still_works(
    client, override_auth, monkeypatch,
):
    """V096 — backwards compatibility: drivers que NO mandan fuente_form_id
    ni campaign_name (Meta nativo, TikTok, n8n legacy) siguen funcionando
    sin cambios. Los campos llegan al core como None."""
    override_auth()

    captured = {}
    def fake_core(cur, payload):
        captured["payload"] = payload
        return {
            "duplicated": False, "id": 1, "mode": "rotacion",
            "asesor_id": None, "supervisor_id": "fake",
            "nombres": "Test", "apellidos": "",
        }
    monkeypatch.setattr("app.routers.ingest.ingest_lead_core", fake_core)
    monkeypatch.setattr("app.routers.ingest.api_clients.log_request", lambda **k: None)
    monkeypatch.setattr("app.routers.ingest.api_clients.increment_metrics", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.ingest.get_db", lambda: _NoopDb())
    monkeypatch.setattr(
        "app.services.notification_service.notify_new_lead", lambda *a, **k: False,
    )

    response = client.post(
        "/api/ingest/leads",
        headers=HEADERS,
        json={"fuente": "facebook", "telefono": "+51987654321"},
    )

    assert response.status_code == 201
    p = captured["payload"]
    assert p.fuente_form_id is None
    assert p.campaign_name  is None


class _NoopDb:
    """Context manager dummy para get_db(). El router lo usa solo para
    el UPDATE de api_client_id post-ingest cuando es multi-tenant."""
    def __enter__(self):
        class _Conn:
            def cursor(self, **kw):
                class _Cur:
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                    def execute(self, *a, **kw): pass
                    def fetchone(self): return None
                return _Cur()
            def commit(self): pass
        return _Conn()
    def __exit__(self, *a): return False


@pytest.mark.ingest
@pytest.mark.unit
def test_ingest_idempotency_replay_returns_cached_response(
    client, override_auth, monkeypatch,
):
    """Idempotency-Key dentro de la ventana 24h -> devuelve el body cacheado
    sin reprocesar el lead."""
    override_auth()

    cached = {
        "duplicated": False,
        "id": 999,
        "mode": "new",
        "asesor_id": None,
        "supervisor_id": "fake",
    }
    monkeypatch.setattr(
        "app.routers.ingest.api_clients.get_idempotent_response",
        lambda client_id, key: cached,
    )
    monkeypatch.setattr(
        "app.routers.ingest.api_clients.log_request",
        lambda **kwargs: None,
    )

    response = client.post(
        "/api/ingest/leads",
        headers={**HEADERS, "Idempotency-Key": "test-key-abc"},
        json={"fuente": "facebook", "telefono": "+51999888777"},
    )

    assert response.status_code == 201   # decorator del router
    assert response.json() == cached

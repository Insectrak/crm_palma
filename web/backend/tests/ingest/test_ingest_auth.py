"""
Tests de la autenticacion del endpoint POST /api/ingest/leads.

Cubre el dual mode de auth:
  - Modo 1 (multi-tenant): X-Api-Key: cli_<prefix>_<secret> contra api_clients.
  - Modo 2 (legacy): X-Api-Key: <INGEST_API_KEY> del .env.

Y los helpers de IP extraction:
  - _get_client_ip respeta X-Forwarded-For
  - _get_client_ip respeta CF-Connecting-IP (Cloudflare)
  - Fallback a request.client.host
"""
from unittest.mock import MagicMock

import pytest


@pytest.mark.ingest
@pytest.mark.unit
def test_get_client_ip_uses_x_forwarded_for_first():
    """Si hay X-Forwarded-For, devuelve el primer IP de la cadena
    (el cliente original antes de los proxies)."""
    from app.routers.ingest import _get_client_ip
    request = MagicMock()
    request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8, 9.10.11.12"}
    request.client = MagicMock(host="127.0.0.1")  # ignorado si XFF presente

    assert _get_client_ip(request) == "1.2.3.4"


@pytest.mark.ingest
@pytest.mark.unit
def test_get_client_ip_uses_cf_connecting_ip_when_no_xff():
    """Cloudflare envia el IP real en CF-Connecting-IP."""
    from app.routers.ingest import _get_client_ip
    request = MagicMock()
    request.headers = {"CF-Connecting-IP": "203.0.113.10"}
    request.client = MagicMock(host="127.0.0.1")

    assert _get_client_ip(request) == "203.0.113.10"


@pytest.mark.ingest
@pytest.mark.unit
def test_get_client_ip_falls_back_to_request_client():
    """Sin headers de proxy, usa request.client.host."""
    from app.routers.ingest import _get_client_ip
    request = MagicMock()
    request.headers = {}
    request.client = MagicMock(host="192.168.1.1")

    assert _get_client_ip(request) == "192.168.1.1"


@pytest.mark.ingest
@pytest.mark.unit
def test_get_client_ip_returns_none_when_no_client():
    """Si request.client tambien es None (caso edge), devuelve None."""
    from app.routers.ingest import _get_client_ip
    request = MagicMock()
    request.headers = {}
    request.client = None

    assert _get_client_ip(request) is None


@pytest.mark.ingest
@pytest.mark.unit
def test_ingest_without_api_key_returns_401(client):
    """Sin X-Api-Key header, el endpoint rechaza con 401."""
    response = client.post("/api/ingest/leads", json={
        "fuente": "facebook", "telefono": "+51999888777",
    })
    assert response.status_code == 401
    assert "api key" in response.json()["detail"].lower()


@pytest.mark.ingest
@pytest.mark.unit
def test_ingest_with_wrong_legacy_key_returns_401(client, monkeypatch):
    """Legacy mode (no empieza con 'cli_'): si la key no matchea
    settings.ingest_api_key, devuelve 401."""
    monkeypatch.setattr("app.routers.ingest.settings.ingest_api_key", "la-key-real")

    response = client.post(
        "/api/ingest/leads",
        headers={"X-Api-Key": "key-incorrecta"},
        json={"fuente": "facebook", "telefono": "+51999888777"},
    )
    assert response.status_code == 401
    assert "invalida" in response.json()["detail"].lower()


@pytest.mark.ingest
@pytest.mark.unit
def test_ingest_without_ingest_api_key_configured_returns_500(client, monkeypatch):
    """Si el server no tiene INGEST_API_KEY seteada y alguien intenta
    el modo legacy, devuelve 500 (config error explicito)."""
    monkeypatch.setattr("app.routers.ingest.settings.ingest_api_key", "")

    response = client.post(
        "/api/ingest/leads",
        headers={"X-Api-Key": "cualquier-key"},
        json={"fuente": "facebook", "telefono": "+51999888777"},
    )
    assert response.status_code == 500
    assert "ingest_api_key" in response.json()["detail"].lower()

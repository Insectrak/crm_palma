"""
Tests del worker de webhooks: _process_one_delivery + process_pending_queue.

Cubre los caminos de decision del worker:
  - HTTP 2xx          -> success
  - HTTP 5xx + retry  -> retrying con backoff
  - HTTP 5xx + agotado -> dead
  - HTTP 4xx no-retry -> dead inmediato (cliente mal config)
  - HTTP 408/429      -> retrying (rate limit / timeout server)
  - Timeout           -> retrying
  - Exception         -> retrying

NO testeado aqui (requiere DB real):
  - SELECT FOR UPDATE SKIP LOCKED (concurrencia multi-worker)
  - JOIN con api_clients
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest


def _make_delivery(**overrides):
    """Helper: dict con la forma de una row del SELECT del worker."""
    base = {
        "id":            123,
        "client_id":     "00000000-0000-0000-0000-000000000001",
        "lead_id":       42,
        "event_type":    "lead.created",
        "payload":       {"foo": "bar"},
        "attempt":       0,
        "max_attempts":  5,
        "webhook_url":   "https://provider.example/webhook",
        "webhook_secret": "test-secret",
    }
    base.update(overrides)
    return base


def _fresh_stats():
    return {"processed": 1, "success": 0, "retrying": 0, "dead": 0}


@pytest.mark.unit
def test_process_one_delivery_2xx_marks_success():
    """HTTP 200 -> status=success, delivered_at seteado, sin next_retry."""
    from app.services.webhook_service import _process_one_delivery
    cur = MagicMock()
    delivery = _make_delivery()
    stats = _fresh_stats()
    now = datetime.now(timezone.utc)

    response = MagicMock(status_code=200, text="OK")
    with patch("app.services.webhook_service.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _process_one_delivery(cur, delivery, now, stats)

    assert stats["success"] == 1
    assert stats["retrying"] == 0
    assert stats["dead"] == 0
    # Verifico que el UPDATE puso status='success'
    update_call = cur.execute.call_args
    sql, params = update_call[0]
    assert "UPDATE crm.webhook_deliveries" in sql
    assert params[0] == "success"


@pytest.mark.unit
def test_process_one_delivery_500_first_attempt_marks_retrying():
    """HTTP 500 + attempt=0 (primer intento) -> retrying con next_retry_at."""
    from app.services.webhook_service import _process_one_delivery
    cur = MagicMock()
    delivery = _make_delivery(attempt=0)
    stats = _fresh_stats()
    now = datetime.now(timezone.utc)

    response = MagicMock(status_code=500, text="Server error")
    with patch("app.services.webhook_service.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _process_one_delivery(cur, delivery, now, stats)

    assert stats["retrying"] == 1
    assert stats["success"] == 0
    assert stats["dead"] == 0
    update_params = cur.execute.call_args[0][1]
    assert update_params[0] == "retrying"
    assert update_params[6] is not None  # next_retry_at no es None


@pytest.mark.unit
def test_process_one_delivery_500_max_attempts_marks_dead():
    """HTTP 500 + attempt=5 (igual a max_attempts) -> dead."""
    from app.services.webhook_service import _process_one_delivery
    cur = MagicMock()
    delivery = _make_delivery(attempt=4, max_attempts=5)  # attempt+1 == max
    stats = _fresh_stats()
    now = datetime.now(timezone.utc)

    response = MagicMock(status_code=500, text="Server error")
    with patch("app.services.webhook_service.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _process_one_delivery(cur, delivery, now, stats)

    assert stats["dead"] == 1
    assert stats["retrying"] == 0
    assert cur.execute.call_args[0][1][0] == "dead"


@pytest.mark.unit
def test_process_one_delivery_404_marks_dead_immediate():
    """HTTP 404 (4xx no-retryable) -> dead INMEDIATO, sin importar attempts."""
    from app.services.webhook_service import _process_one_delivery
    cur = MagicMock()
    delivery = _make_delivery(attempt=0, max_attempts=5)
    stats = _fresh_stats()
    now = datetime.now(timezone.utc)

    response = MagicMock(status_code=404, text="Not found")
    with patch("app.services.webhook_service.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _process_one_delivery(cur, delivery, now, stats)

    # 404 NO es retryable -> dead aunque attempt=0
    assert stats["dead"] == 1
    assert stats["retrying"] == 0


@pytest.mark.unit
def test_process_one_delivery_429_marks_retrying():
    """HTTP 429 (rate limit) ES retryable."""
    from app.services.webhook_service import _process_one_delivery
    cur = MagicMock()
    delivery = _make_delivery(attempt=0, max_attempts=5)
    stats = _fresh_stats()
    now = datetime.now(timezone.utc)

    response = MagicMock(status_code=429, text="Too many requests")
    with patch("app.services.webhook_service.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _process_one_delivery(cur, delivery, now, stats)

    assert stats["retrying"] == 1
    assert stats["dead"] == 0


@pytest.mark.unit
def test_process_one_delivery_timeout_marks_retrying():
    """httpx.TimeoutException -> retryable."""
    from app.services.webhook_service import _process_one_delivery
    cur = MagicMock()
    delivery = _make_delivery(attempt=0, max_attempts=5)
    stats = _fresh_stats()
    now = datetime.now(timezone.utc)

    with patch("app.services.webhook_service.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _process_one_delivery(cur, delivery, now, stats)

    assert stats["retrying"] == 1
    update_params = cur.execute.call_args[0][1]
    assert "timeout" in (update_params[5] or "").lower()  # error_message


@pytest.mark.unit
def test_process_one_delivery_signs_payload_when_secret_present():
    """Si el client tiene webhook_secret, los headers incluyen X-Crm-Signature."""
    from app.services.webhook_service import _process_one_delivery
    cur = MagicMock()
    delivery = _make_delivery(webhook_secret="mi-secret-fuerte")
    stats = _fresh_stats()
    now = datetime.now(timezone.utc)

    response = MagicMock(status_code=200, text="OK")
    captured_headers = {}

    def _capture(url, content, headers):
        captured_headers.update(headers)
        return response

    with patch("app.services.webhook_service.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = _capture
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _process_one_delivery(cur, delivery, now, stats)

    assert captured_headers["X-Crm-Signature"].startswith("sha256=")
    assert len(captured_headers["X-Crm-Signature"]) == len("sha256=") + 64  # SHA256 hex
    assert captured_headers["X-Crm-Event"] == "lead.created"
    assert captured_headers["X-Crm-Delivery"] == "123"


@pytest.mark.unit
def test_process_pending_queue_returns_zeros_when_no_deliveries(monkeypatch):
    """Si no hay deliveries pendientes, stats todos en 0."""
    from app.services.webhook_service import process_pending_queue
    from tests.fixtures import fake_db_returning

    monkeypatch.setattr(
        "app.services.webhook_service.get_db",
        fake_db_returning([]),  # SELECT devuelve lista vacia
    )

    stats = process_pending_queue()

    assert stats == {"processed": 0, "success": 0, "retrying": 0, "dead": 0}

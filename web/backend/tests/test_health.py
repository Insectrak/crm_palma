"""
Tests del endpoint de health check.
Verifica que el sistema responda correctamente en modo demo
(sin depender de una base de datos real).
"""


def test_health_returns_200_in_demo_mode(client):
    res = client.get("/api/health")
    assert res.status_code == 200


def test_health_payload_shape(client):
    res = client.get("/api/health")
    body = res.json()
    assert body.get("status") == "ok"
    assert "db" in body
    # En modo demo, la DB debe reportarse como demo_mode
    assert body.get("db") == "demo_mode"
    assert body.get("demo") is True


def test_health_is_public(client):
    """Health check nunca debe requerir autenticación."""
    res = client.get("/api/health")
    assert res.status_code != 401
    assert res.status_code != 403

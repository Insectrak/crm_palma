"""
Tests del endpoint POST /auth/emergency-reset.

Este endpoint es PODEROSO — permite resetear cualquier password sin login
si conoces el EMERGENCY_SECRET. Por eso debe estar BLINDADO.

Defensas en profundidad:
  1. EMERGENCY_SECRET vacio en .env -> endpoint devuelve 404 (no existe).
  2. Rate limit 3/hora (no testeamos aqui, es integration).
  3. Comparacion en tiempo constante (secrets.compare_digest) anti-timing.
"""
import pytest


@pytest.mark.auth
@pytest.mark.unit
def test_emergency_reset_without_secret_configured_returns_404(client, monkeypatch):
    """Si EMERGENCY_SECRET no esta seteado en el settings, endpoint devuelve
    404 como si no existiera. Defensa de "off by default"."""
    # Arrange — settings.emergency_secret vacio
    monkeypatch.setattr("app.auth.router.settings.emergency_secret", "")

    # Act
    response = client.post("/auth/emergency-reset", json={
        "secret": "cualquier",
        "email": "x@y.com",
        "new_password": "supersecret",
    })

    # Assert — 404 (no 403) para no revelar que el endpoint existe
    assert response.status_code == 404


@pytest.mark.auth
@pytest.mark.unit
def test_emergency_reset_with_wrong_secret_returns_403(client, monkeypatch):
    """Secret incorrecto -> 403 explicito (ya estabamos protegidos por el
    rate limit que aqui no testeamos)."""
    # Arrange
    monkeypatch.setattr("app.auth.router.settings.emergency_secret", "el-secret-real")

    # Act
    response = client.post("/auth/emergency-reset", json={
        "secret": "secret-equivocado",
        "email": "x@y.com",
        "new_password": "supersecret",
    })

    # Assert
    assert response.status_code == 403
    assert "secret" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_emergency_reset_with_weak_password_returns_400(client, monkeypatch):
    """Secret correcto pero password <6 chars."""
    monkeypatch.setattr("app.auth.router.settings.emergency_secret", "el-secret-real")

    response = client.post("/auth/emergency-reset", json={
        "secret": "el-secret-real",
        "email": "x@y.com",
        "new_password": "abc",
    })
    assert response.status_code == 400

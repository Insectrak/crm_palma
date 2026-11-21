"""
Fixtures especificas del modulo auth.

Sobre conftest global agrega helpers para:
  - Mockear el bcrypt password check sin tener que generar hashes reales.
  - Helper para mockear get_db con un user dict listo.
"""
from __future__ import annotations

import pytest

from tests.fixtures import make_user, fake_db_returning


@pytest.fixture()
def patch_bcrypt(monkeypatch):
    """Permite controlar el resultado de bcrypt.checkpw sin generar hashes.

    Uso:
        def test_login(client, patch_bcrypt):
            patch_bcrypt(returns=True)   # toda comparacion pasa
            patch_bcrypt(returns=False)  # toda comparacion falla
    """
    def _patch(*, returns: bool):
        monkeypatch.setattr(
            "app.auth.router.bcrypt.checkpw",
            lambda plain, hashed: returns,
        )
    return _patch


@pytest.fixture()
def mock_user_in_db(monkeypatch):
    """Hace que app.auth.router.get_db devuelva un user especifico.

    Uso:
        def test_x(client, mock_user_in_db):
            mock_user_in_db(make_user(email="ana@palma.com", role="admin"))
            response = client.post("/auth/login", ...)
    """
    def _mock(user_dict: dict | None):
        monkeypatch.setattr(
            "app.auth.router.get_db",
            fake_db_returning(user_dict),
        )
    return _mock


@pytest.fixture()
def disable_rate_limit(monkeypatch):
    """Desactiva slowapi rate limiter en tests para que no falsen 429.

    Algunos endpoints (/auth/login, /auth/change-password) tienen rate limit
    estricto que puede disparar 429 si corremos muchos tests seguidos.
    """
    # Reemplazamos el decorador @limiter.limit(...) por no-op via setattr al
    # objeto limiter. La forma mas robusta es desactivar el limiter global.
    monkeypatch.setattr("app.auth.router.limiter.enabled", False, raising=False)

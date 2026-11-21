"""Tests para configuracion editable de FCM (V040.1).

Cubre:
- load_fcm_config: defaults from env, override desde DB, decrypt, fallback
- invalidate_fcm_config_cache: tear down de firebase_app + reset de _init_*
- get_init_status: refleja correctamente el estado
- Endpoints:
    GET  /fcm  → enmascara la credencial, nunca plaintext
    PUT  /fcm  → valida JSON, requiere type=service_account, encripta y persiste
    POST /fcm/test → fuerza re-init y devuelve resultado
"""
from contextlib import contextmanager

from app.config import settings as app_settings


# ── load_fcm_config ───────────────────────────────────────────────────────

def test_load_fcm_config_defaults_from_env(monkeypatch):
    from app.services import fcm_service
    fcm_service.invalidate_fcm_config_cache()

    monkeypatch.setattr(app_settings, "fcm_enabled", True)
    monkeypatch.setattr(app_settings, "fcm_service_account_b64", "envvalue123")

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self): return None  # sin row → usa env
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.fcm_service.get_db", fake_get_db)

    cfg = fcm_service.load_fcm_config()
    assert cfg["enabled"] is True
    assert cfg["service_account_b64"] == "envvalue123"
    assert cfg["source"] == "env"


def test_load_fcm_config_db_overrides_env(monkeypatch):
    from app.services import fcm_service
    fcm_service.invalidate_fcm_config_cache()

    monkeypatch.setattr(app_settings, "fcm_enabled", False)
    monkeypatch.setattr(app_settings, "fcm_service_account_b64", "envvalue")

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self):
                        return ({
                            "enabled": True,
                            "service_account_b64_encrypted": "enc-fake",
                        },)
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.fcm_service.get_db", fake_get_db)
    monkeypatch.setattr(
        "app.services.secrets_service.decrypt",
        lambda x: "decrypted-from-db" if x == "enc-fake" else None,
    )

    cfg = fcm_service.load_fcm_config()
    assert cfg["enabled"] is True   # DB override
    assert cfg["service_account_b64"] == "decrypted-from-db"
    assert cfg["source"] == "db"


def test_load_fcm_config_db_decrypt_failure_falls_back_to_env(monkeypatch):
    """Si decrypt falla (ej. SECRET_KEY cambio), fallback al env var.
    Defensa en profundidad — preferimos pushes activos a un crash silencioso."""
    from app.services import fcm_service
    fcm_service.invalidate_fcm_config_cache()

    monkeypatch.setattr(app_settings, "fcm_enabled", True)
    monkeypatch.setattr(app_settings, "fcm_service_account_b64", "env-fallback")

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self):
                        return ({"enabled": True, "service_account_b64_encrypted": "broken"},)
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.fcm_service.get_db", fake_get_db)

    def _fail_decrypt(_x):
        raise RuntimeError("decrypt failed")
    monkeypatch.setattr("app.services.secrets_service.decrypt", _fail_decrypt)

    cfg = fcm_service.load_fcm_config()
    assert cfg["service_account_b64"] == "env-fallback"
    assert cfg["source"] == "env"


def test_invalidate_fcm_config_cache_resets_init_state(monkeypatch):
    from app.services import fcm_service

    # Simular un app inicializado
    fcm_service._firebase_app = "fake-app-instance"
    fcm_service._init_attempted = True
    fcm_service._init_error = None
    fcm_service._FCM_CONFIG_CACHE["value"] = {"x": 1}

    # Stub firebase_admin.delete_app para no llamar al SDK real
    import sys
    fake_module = type(sys)("firebase_admin")
    deleted_apps = []
    fake_module.delete_app = lambda app: deleted_apps.append(app)
    monkeypatch.setitem(sys.modules, "firebase_admin", fake_module)

    fcm_service.invalidate_fcm_config_cache()

    assert fcm_service._firebase_app is None
    assert fcm_service._init_attempted is False
    assert fcm_service._FCM_CONFIG_CACHE["value"] is None
    assert deleted_apps == ["fake-app-instance"]


# ── get_init_status ───────────────────────────────────────────────────────

def test_get_init_status_reflects_current_state(monkeypatch):
    from app.services import fcm_service
    fcm_service.invalidate_fcm_config_cache()

    monkeypatch.setattr(app_settings, "fcm_enabled", True)
    monkeypatch.setattr(app_settings, "fcm_service_account_b64", "envb64")

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self): return None
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.fcm_service.get_db", fake_get_db)

    status = fcm_service.get_init_status()
    assert status["enabled"] is True
    assert status["has_credentials"] is True
    assert status["credential_source"] == "env"
    assert status["initialized"] is False  # no intentamos init aqui


# ── Endpoints ──────────────────────────────────────────────────────────────

def test_get_fcm_requires_admin(client, auth_headers_asesor):
    res = client.get("/api/settings/fcm", headers=auth_headers_asesor)
    assert res.status_code == 403


def test_get_fcm_demo_mode(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.get("/api/settings/fcm", headers=auth_headers_admin)
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert body["initialized"] is True
    # Nunca devolvemos plaintext — solo preview enmascarado
    assert "*" in body["credential_preview"]


def test_put_fcm_rejects_non_json(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", False)
    res = client.put(
        "/api/settings/fcm",
        headers=auth_headers_admin,
        json={"enabled": True, "service_account_json": "esto no es json"},
    )
    assert res.status_code == 400
    assert "JSON" in res.json()["detail"]


def test_put_fcm_rejects_wrong_service_account(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", False)
    res = client.put(
        "/api/settings/fcm",
        headers=auth_headers_admin,
        json={
            "enabled": True,
            "service_account_json": '{"type": "user_account", "project_id": "x"}',
        },
    )
    assert res.status_code == 400
    assert "service_account" in res.json()["detail"]


def test_put_fcm_rejects_missing_required_fields(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", False)
    res = client.put(
        "/api/settings/fcm",
        headers=auth_headers_admin,
        json={
            "enabled": True,
            "service_account_json": '{"type": "service_account"}',
        },
    )
    assert res.status_code == 400


def test_put_fcm_demo_mode_short_circuits(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.put(
        "/api/settings/fcm",
        headers=auth_headers_admin,
        json={"enabled": True, "service_account_json": ""},
    )
    assert res.status_code == 200
    assert res.json()["demo"] is True


def test_test_fcm_endpoint_requires_admin(client, auth_headers_asesor):
    res = client.post("/api/settings/fcm/test", headers=auth_headers_asesor)
    assert res.status_code == 403


def test_test_fcm_endpoint_demo(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.post("/api/settings/fcm/test", headers=auth_headers_admin)
    assert res.status_code == 200
    body = res.json()
    assert body["demo"] is True
    assert body["initialized"] is True

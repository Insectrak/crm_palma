"""
Tests del endpoint público de marca (GET /api/settings/brand)
y del guard de admin en PUT /api/settings/brand.
"""


# ─── GET /api/settings/brand ───────────────────────────────────────────────

def test_brand_get_is_public(client):
    """El login debe poder leer la marca sin token."""
    res = client.get("/api/settings/brand")
    assert res.status_code == 200


def test_brand_returns_defaults_in_demo_mode(client):
    res = client.get("/api/settings/brand")
    body = res.json()
    assert "company_name" in body
    assert "primary_color" in body
    assert "sidebar_bg" in body
    assert body["primary_color"].startswith("#")


def test_brand_has_all_expected_fields(client):
    expected = {
        "company_name",
        "company_subtitle",
        "logo_data_url",
        "favicon_data_url",
        "primary_color",
        "primary_hover",
        "sidebar_bg",
        "accent_color",
    }
    body = client.get("/api/settings/brand").json()
    assert expected.issubset(set(body.keys()))


# ─── PUT /api/settings/brand — autorización ───────────────────────────────

def test_brand_put_requires_auth(client):
    res = client.put("/api/settings/brand", json={"company_name": "Test"})
    assert res.status_code in (401, 403)


def test_brand_put_rejects_asesor(client, auth_headers_asesor):
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_asesor,
        json={"company_name": "Hackeada"},
    )
    assert res.status_code == 403


def test_brand_put_rejects_supervisor(client, auth_headers_supervisor):
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_supervisor,
        json={"company_name": "Hackeada"},
    )
    assert res.status_code == 403


def test_brand_put_accepts_admin_in_demo_mode(client, auth_headers_admin):
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_admin,
        json={
            "company_name": "Cliente Nuevo",
            "primary_color": "#EC7016",
            "primary_hover": "#C55B00",
            "sidebar_bg": "#1F1D5C",
            "accent_color": "#F4A343",
        },
    )
    assert res.status_code == 200
    assert res.json().get("ok") is True


def test_brand_put_rejects_oversized_logo(client, auth_headers_admin, monkeypatch):
    """Logo > 700 KB debe rechazarse con 400."""
    # Desactivamos demo_mode solo para este test (donde la ruta del límite se evalúa)
    from app.routers import settings as settings_router
    # En demo_mode la validación se ejecuta ANTES del early-return de DB
    # Si no, forzamos demo=False temporalmente:
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "demo_mode", False)

    # Mockeamos get_db para no tocar DB real
    class _FakeCursor:
        def execute(self, *a, **k): pass
        def fetchone(self): return None
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _FakeConn:
        def cursor(self, **kwargs): return _FakeCursor()
        def commit(self): pass

    from contextlib import contextmanager
    @contextmanager
    def fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr("app.database.get_db", fake_get_db)

    huge_logo = "data:image/png;base64," + ("A" * 800_000)
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_admin,
        json={"company_name": "X", "logo_data_url": huge_logo},
    )
    assert res.status_code == 400
    assert "demasiado grande" in res.json().get("detail", "").lower()


# ─── Favicon ───────────────────────────────────────────────────────────────

def _patch_db(monkeypatch):
    """Helper: desactiva demo_mode y mockea get_db para tests de PUT."""
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "demo_mode", False)

    class _FakeCursor:
        def execute(self, *a, **k): pass
        def fetchone(self): return None
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _FakeConn:
        def cursor(self, **kwargs): return _FakeCursor()
        def commit(self): pass

    from contextlib import contextmanager
    @contextmanager
    def fake_get_db():
        yield _FakeConn()

    monkeypatch.setattr("app.database.get_db", fake_get_db)


def test_brand_put_accepts_valid_favicon(client, auth_headers_admin, monkeypatch):
    """Un favicon PNG pequeño debe aceptarse."""
    _patch_db(monkeypatch)
    small_png = "data:image/png;base64," + ("A" * 1000)
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_admin,
        json={"company_name": "X", "favicon_data_url": small_png},
    )
    assert res.status_code == 200


def test_brand_put_rejects_oversized_favicon(client, auth_headers_admin, monkeypatch):
    """Favicon > 140 KB debe rechazarse con 400."""
    _patch_db(monkeypatch)
    huge_favicon = "data:image/png;base64," + ("A" * 200_000)
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_admin,
        json={"company_name": "X", "favicon_data_url": huge_favicon},
    )
    assert res.status_code == 400
    assert "demasiado grande" in res.json().get("detail", "").lower()


def test_brand_put_rejects_favicon_with_invalid_mime(client, auth_headers_admin, monkeypatch):
    """Solo se aceptan ICO/PNG/SVG como favicon."""
    _patch_db(monkeypatch)
    bad = "data:image/gif;base64," + ("A" * 500)
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_admin,
        json={"company_name": "X", "favicon_data_url": bad},
    )
    assert res.status_code == 400
    detail = res.json().get("detail", "").lower()
    assert "favicon" in detail and "image/gif" in detail


def test_brand_put_accepts_ico_favicon(client, auth_headers_admin, monkeypatch):
    """ICO debe aceptarse (formato clásico de favicon)."""
    _patch_db(monkeypatch)
    ico = "data:image/x-icon;base64," + ("A" * 500)
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_admin,
        json={"company_name": "X", "favicon_data_url": ico},
    )
    assert res.status_code == 200


def test_brand_put_accepts_null_favicon(client, auth_headers_admin, monkeypatch):
    """Quitar el favicon (null) debe aceptarse — vuelve al default."""
    _patch_db(monkeypatch)
    res = client.put(
        "/api/settings/brand",
        headers=auth_headers_admin,
        json={"company_name": "X", "favicon_data_url": None},
    )
    assert res.status_code == 200


# ─── GET /api/settings/brand/logo y /favicon (binario público) ─────────────

def test_brand_logo_endpoint_404_when_no_asset(client, monkeypatch):
    """Sin logo configurado → 404. Gmail no recibe un placeholder binario,
    el template del email cae al fallback inicial.
    """
    # Simulamos que get_brand() devuelve un dict sin logo_data_url
    from app.routers import settings as settings_router

    def _no_asset():
        return {"company_name": "Test"}

    monkeypatch.setattr(settings_router, "get_brand", _no_asset)
    res = client.get("/api/settings/brand/logo")
    assert res.status_code == 404


def test_brand_logo_endpoint_serves_binary(client, monkeypatch):
    """Con un data URL válido en brand, /brand/logo devuelve los bytes
    decodificados y el content-type correcto. Esto es lo que Gmail
    necesita para renderizar el header del email de invitación.
    """
    import base64

    from app.routers import settings as settings_router

    png_magic = bytes.fromhex("89504e470d0a1a0a")
    data_url = "data:image/png;base64," + base64.b64encode(png_magic).decode()
    monkeypatch.setattr(
        settings_router, "get_brand",
        lambda: {"logo_data_url": data_url, "company_name": "X"},
    )

    res = client.get("/api/settings/brand/logo")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/png")
    assert res.content == png_magic
    # Cache-Control para que Gmail no rebaje la imagen en cada apertura.
    assert "max-age" in res.headers.get("cache-control", "")
    assert res.headers.get("etag")


def test_brand_logo_endpoint_is_public(client, monkeypatch):
    """No requiere auth — los emails que el cliente abre en Gmail/Outlook
    necesitan acceso sin headers de autorización.
    """
    from app.routers import settings as settings_router
    import base64

    data_url = "data:image/png;base64," + base64.b64encode(b"fake").decode()
    monkeypatch.setattr(
        settings_router, "get_brand",
        lambda: {"logo_data_url": data_url, "company_name": "X"},
    )
    # SIN headers — debería pasar (público)
    res = client.get("/api/settings/brand/logo")
    assert res.status_code == 200


def test_brand_favicon_endpoint_serves_binary(client, monkeypatch):
    import base64

    from app.routers import settings as settings_router

    ico_bytes = b"\x00\x00\x01\x00"  # cabecera ICO
    data_url = "data:image/x-icon;base64," + base64.b64encode(ico_bytes).decode()
    monkeypatch.setattr(
        settings_router, "get_brand",
        lambda: {"favicon_data_url": data_url, "company_name": "X"},
    )
    res = client.get("/api/settings/brand/favicon")
    assert res.status_code == 200
    assert "icon" in res.headers["content-type"]
    assert res.content == ico_bytes

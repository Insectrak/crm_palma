"""
Tests del factory check_permission (Sprint 2, ADR-0011).

Verifica los 4 caminos del dependency:
1. Rol legacy admin → bypass (compat con sistema actual).
2. Flag `_all` en permissions del JWT → bypass.
3. Permission key concreta en TRUE → permite.
4. Permission key ausente o FALSE → 403.
+ Sin auth → 401 (chequeo de get_current_user, no del factory).
"""
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.auth.permissions import check_permission, has_permission
from app.auth.jwt import create_access_token
from app.auth.schemas import TokenData


# ─── Helpers de tokens ─────────────────────────────────────────────────────

def _token(**extra) -> str:
    """Construye un JWT con los campos pedidos. Resto vienen vacíos."""
    payload = {
        "sub": "00000000-0000-0000-0000-000000000099",
        "email": "test@local",
        "role": "asesor",
    }
    payload.update(extra)
    return create_access_token(payload)


def _h(**extra) -> dict:
    """Header Authorization con el token armado por _token."""
    return {"Authorization": f"Bearer {_token(**extra)}"}


# ─── Mini app para probar el dependency ────────────────────────────────────

def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/reportes")
    def reportes(_user=Depends(check_permission("reportes.view"))):
        return {"ok": True}

    return app


# ─── Tests ─────────────────────────────────────────────────────────────────

def test_no_auth_returns_401():
    client = TestClient(_build_test_app())
    r = client.get("/reportes")
    assert r.status_code in (401, 403)  # 403 si Bearer schema lo gatea


def test_admin_legacy_bypasses_check():
    """Usuario con role='admin' (legacy) pasa aunque permissions esté vacío."""
    client = TestClient(_build_test_app())
    r = client.get("/reportes", headers=_h(role="admin"))
    assert r.status_code == 200


def test_all_flag_bypasses_check():
    """Cualquier usuario con permissions._all=true pasa."""
    client = TestClient(_build_test_app())
    r = client.get(
        "/reportes",
        headers=_h(role="asesor", permissions={"_all": True}),
    )
    assert r.status_code == 200


def test_permission_true_allows():
    """Permission key concreta en TRUE → permite."""
    client = TestClient(_build_test_app())
    r = client.get(
        "/reportes",
        headers=_h(role="asesor", permissions={"reportes.view": True}),
    )
    assert r.status_code == 200


def test_permission_false_rejects_with_403():
    """Permission key explícita FALSE → 403."""
    client = TestClient(_build_test_app())
    r = client.get(
        "/reportes",
        headers=_h(role="asesor", permissions={"reportes.view": False}),
    )
    assert r.status_code == 403
    assert "reportes.view" in r.json()["detail"]


def test_permission_missing_rejects_with_403():
    """Sin la key en el dict → 403 (default deny)."""
    client = TestClient(_build_test_app())
    r = client.get(
        "/reportes",
        headers=_h(role="asesor", permissions={"leads.view": True}),  # otra key
    )
    assert r.status_code == 403


def test_supervisor_legacy_without_permissions_rejects():
    """Rol legacy 'supervisor' sin permissions custom → 403 (no es admin).

    Decisión: el factory NO mapea roles legacy a permisos automáticamente.
    Para que un supervisor existente acceda a un endpoint nuevo con
    check_permission, debe migrarse a un rol custom o agregarse el
    permiso a su rol legacy via UI. Esto fuerza la migración explícita
    (Strangler) en lugar de magia silenciosa."""
    client = TestClient(_build_test_app())
    r = client.get("/reportes", headers=_h(role="supervisor", permissions={}))
    assert r.status_code == 403


# ─── has_permission helper ─────────────────────────────────────────────────

def test_has_permission_admin_legacy():
    user = TokenData(user_id="x", email="a@b", role="admin")
    assert has_permission(user, "anything") is True


def test_has_permission_all_flag():
    user = TokenData(user_id="x", email="a@b", role="asesor", permissions={"_all": True})
    assert has_permission(user, "reportes.view") is True


def test_has_permission_explicit_true():
    user = TokenData(
        user_id="x", email="a@b", role="asesor",
        permissions={"leads.view": True},
    )
    assert has_permission(user, "leads.view") is True
    assert has_permission(user, "leads.delete") is False


def test_token_data_defaults_for_legacy_tokens():
    """Tokens emitidos antes de Sprint 2 (sin permissions/role_id) deben
    decodificarse sin error con defaults seguros."""
    from app.auth.jwt import verify_token
    token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000099",
        "email": "legacy@local",
        "role": "admin",
        # No incluye permissions, role_id, etc — simula token pre-V078
    })
    data = verify_token(token)
    assert data.role == "admin"
    assert data.permissions == {}
    assert data.role_id is None
    assert data.role_is_external is False
    assert data.api_client_id is None


def test_can_view_all_data():
    from app.auth.permissions import can_view_all_data
    
    # 1. Admin always sees all
    admin_user = TokenData(user_id="u1", email="admin@test", role="admin")
    assert can_view_all_data(admin_user, "leads") is True
    assert can_view_all_data(admin_user, "dashboards") is True
    
    # 2. _all flag sees all
    all_user = TokenData(user_id="u2", email="all@test", role="asesor", permissions={"_all": True})
    assert can_view_all_data(all_user, "leads") is True
    assert can_view_all_data(all_user, "dashboards") is True
    
    # 3. data.view_all master switch sees all
    master_user = TokenData(user_id="u3", email="master@test", role="asesor", permissions={"data.view_all": True})
    assert can_view_all_data(master_user, "leads") is True
    assert can_view_all_data(master_user, "dashboards") is True
    assert can_view_all_data(master_user, "chat") is True
    
    # 4. Granular permissions
    leads_only_user = TokenData(user_id="u4", email="leads@test", role="asesor", permissions={"leads.view_all": True})
    assert can_view_all_data(leads_only_user, "leads") is True
    assert can_view_all_data(leads_only_user, "dashboards") is False
    
    dash_only_user = TokenData(user_id="u5", email="dash@test", role="asesor", permissions={"dashboards.view_all": True})
    assert can_view_all_data(dash_only_user, "leads") is False
    assert can_view_all_data(dash_only_user, "dashboards") is True
    
    # 5. Default asesor / custom role without view_all sees only own data
    regular_user = TokenData(user_id="u6", email="reg@test", role="asesor", permissions={"leads.view": True, "dashboards.view": True})
    assert can_view_all_data(regular_user, "leads") is False
    assert can_view_all_data(regular_user, "dashboards") is False
    assert can_view_all_data(regular_user, "chat") is False
    assert can_view_all_data(regular_user, "agenda") is False
    assert can_view_all_data(regular_user, "reportes") is False

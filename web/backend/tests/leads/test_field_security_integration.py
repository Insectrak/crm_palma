"""
Tests de integracion del FLS con el router de leads (ADR-0011 Sprint 5).

Cubre:
- GET /api/leads/{id} enmascara fields no readable
- GET /api/leads (list) enmascara fields en cada item
- PATCH /api/leads/{id} rechaza con 403 si el rol no puede editar el field
- Admin bypasea todo
- Field no en catalogo permanece intacto

Estos tests pegan a los endpoints reales con DEMO_MODE=true (no DB).
Mockear el resultado del repository para inyectar el lead con todos los
fields visibles, despues confirmar que la respuesta esta enmascarada.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.auth.jwt import create_access_token


def _build_token(role="asesor", permissions=None, user_id=None):
    """Genera un JWT con permissions custom para testear FLS."""
    return create_access_token({
        "sub": user_id or "00000000-0000-0000-0000-000000000003",
        "email": f"{role}@palma.test",
        "role": role,
        "permissions": permissions or {},
    })


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _fake_lead():
    """Lead con todos los fields enmascarables presentes."""
    return {
        "id": 42,
        "nombres": "Juan",
        "apellidos": "Test",
        "telefono": "+51987654321",
        "email": "juan@test.com",
        "observaciones": "Lead caliente, llamar lunes",
        "presupuesto": 250000,
        "estado_id": 1,
        "estado_nombre": "Nuevo",
        "fuente_id": 1,
        "asesor_id": None,
        "supervisor_id": None,
        "ciudad": "Lima",
        "trabajo": "Ingeniero",
        "calidad": "TIBIO",
        "fecha_ingreso": "2026-06-15T10:00:00",
        "updated_at": "2026-06-15T10:00:00",
    }


# ── GET /api/leads/{id} ────────────────────────────────────────────────────

@pytest.mark.unit
def test_get_lead_admin_sees_everything(client, monkeypatch):
    """Admin legacy bypassa FLS aunque tenga restricciones explicitas."""
    token = _build_token(role="admin", permissions={"field.leads.telefono.read": False})

    # Mock del SELECT principal del router. role_filter para admin no agrega
    # restricciones, asi que con el fetchone devolviendo el lead alcanza.
    with patch("app.routers.leads.get_db") as mock_db:
        mock_conn = mock_db.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        mock_cur.fetchone.side_effect = [_fake_lead(), {"referido_por": None}]
        # Las segundas conexiones (referido_por) tambien necesitan mock.
        # Reusar el mismo conn cubre ambas.
        r = client.get("/api/leads/42", headers=_headers(token))

    assert r.status_code == 200
    data = r.json()
    assert data["telefono"] == "+51987654321"
    assert data["email"] == "juan@test.com"


@pytest.mark.unit
def test_get_lead_masks_unreadable_fields(client, monkeypatch):
    """Asesor con field.leads.telefono.read=false NO debe ver el telefono."""
    token = _build_token(
        role="asesor",
        permissions={"field.leads.telefono.read": False, "field.leads.email.read": False},
    )

    with patch("app.routers.leads.get_db") as mock_db:
        mock_conn = mock_db.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        mock_cur.fetchone.side_effect = [_fake_lead(), {"referido_por": None}]
        r = client.get("/api/leads/42", headers=_headers(token))

    assert r.status_code == 200
    data = r.json()
    assert "telefono" not in data
    assert "email" not in data
    # Fields no restringidos permanecen
    assert data["nombres"] == "Juan"
    assert data["observaciones"] == "Lead caliente, llamar lunes"
    assert data["presupuesto"] == 250000


@pytest.mark.unit
def test_get_lead_compat_no_perms_full_visibility(client, monkeypatch):
    """Rol sin restricciones FLS ve todo (compat con roles existentes)."""
    token = _build_token(role="asesor", permissions={})

    with patch("app.routers.leads.get_db") as mock_db:
        mock_conn = mock_db.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        mock_cur.fetchone.side_effect = [_fake_lead(), {"referido_por": None}]
        r = client.get("/api/leads/42", headers=_headers(token))

    assert r.status_code == 200
    data = r.json()
    assert data["telefono"] == "+51987654321"
    assert data["email"] == "juan@test.com"


# ── GET /api/leads (lista) ─────────────────────────────────────────────────

@pytest.mark.unit
def test_list_leads_masks_each_item(client, monkeypatch):
    token = _build_token(
        role="asesor",
        permissions={"field.leads.telefono.read": False},
    )

    # Mock leads_repository.find_paginated devuelve (rows, total)
    leads = [_fake_lead(), {**_fake_lead(), "id": 43, "telefono": "+51000000000"}]
    monkeypatch.setattr(
        "app.routers.leads.leads_repository.find_paginated",
        lambda *a, **kw: (leads, len(leads)),
    )

    r = client.get("/api/leads", headers=_headers(token))

    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    for item in data["items"]:
        assert "telefono" not in item
        # email queda visible (no se restringio)
        assert item["email"] == "juan@test.com"


@pytest.mark.unit
def test_list_leads_admin_sees_everything(client, monkeypatch):
    token = _build_token(role="admin", permissions={"field.leads.telefono.read": False})
    leads = [_fake_lead()]
    monkeypatch.setattr(
        "app.routers.leads.leads_repository.find_paginated",
        lambda *a, **kw: (leads, 1),
    )

    r = client.get("/api/leads", headers=_headers(token))

    assert r.status_code == 200
    assert r.json()["items"][0]["telefono"] == "+51987654321"


# ── PATCH /api/leads/{id} ──────────────────────────────────────────────────

@pytest.mark.unit
def test_patch_lead_blocks_uneditable_field(client, monkeypatch):
    """Asesor con field.leads.telefono.edit=false NO puede modificar telefono."""
    token = _build_token(
        role="asesor",
        permissions={"field.leads.telefono.edit": False},
    )

    r = client.patch(
        "/api/leads/42",
        headers=_headers(token),
        json={"telefono": "+51999999999"},
    )

    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "telefono" in detail


@pytest.mark.unit
def test_patch_lead_blocks_multiple_fields_in_single_request(client):
    token = _build_token(
        role="asesor",
        permissions={
            "field.leads.telefono.edit": False,
            "field.leads.email.edit": False,
        },
    )

    r = client.patch(
        "/api/leads/42",
        headers=_headers(token),
        json={"telefono": "x", "email": "y"},
    )

    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "telefono" in detail
    assert "email" in detail


@pytest.mark.unit
def test_patch_lead_admin_bypasses_field_restrictions(client, monkeypatch):
    """Admin no debe ser bloqueado por FLS aunque las keys digan que si."""
    token = _build_token(
        role="admin",
        permissions={"field.leads.telefono.edit": False},
    )

    # Mock la query del UPDATE para que no toque DB. El admin NO debe ser
    # rechazado en el chequeo FLS antes del UPDATE. Como la query real
    # requiere context complejo, basta con probar que NO devuelve 403.
    with patch("app.routers.leads.get_db") as mock_db:
        mock_conn = mock_db.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        # leads.SELECT prev (en el flujo de update) puede devolver None y
        # el endpoint devuelve algo distinto a 403 (probablemente 404).
        mock_cur.fetchone.return_value = None
        r = client.patch(
            "/api/leads/42",
            headers=_headers(token),
            json={"telefono": "+51999000000"},
        )

    # El test pasa si NO recibimos 403 con mensaje de FLS.
    # Aceptamos 200, 404, 500 — todos ellos indican que el guard FLS pasó.
    assert r.status_code != 403 or "Tu rol no puede editar" not in r.json().get("detail", "")


@pytest.mark.unit
def test_patch_lead_field_not_in_catalog_passes(client):
    """Modificar un field que NO esta en el catalogo (ej. nombres) NO
    deberia ser bloqueado por FLS."""
    token = _build_token(
        role="asesor",
        permissions={"field.leads.telefono.edit": False},
    )

    # Mock la query del UPDATE para que no toque DB real. El guard FLS deberia
    # pasar (nombres no esta en catalogo), pero luego el endpoint intenta el
    # UPDATE que requiere DB. Lo mockeamos para confirmar que SI pasa el FLS.
    with patch("app.routers.leads.get_db") as mock_db:
        mock_conn = mock_db.return_value.__enter__.return_value
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        mock_cur.fetchone.return_value = None  # update no encuentra lead

        r = client.patch(
            "/api/leads/42",
            headers=_headers(token),
            json={"nombres": "Juan Modificado"},
        )

    # El test pasa si NO recibimos 403 con mensaje FLS de telefono.
    # Aceptamos 200/404/500 — todo eso indica que el guard FLS dejo pasar.
    assert r.status_code != 403 or "telefono" not in r.json().get("detail", "")

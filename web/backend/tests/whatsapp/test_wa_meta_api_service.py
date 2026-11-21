"""
Tests de wa_meta_api_service.py — cliente Meta Cloud API.

Cubre las 4 funciones de resolucion:
  - resolve_access_token: prioridad multi-WABA + fallback env.
  - meta_headers: Authorization Bearer correcto.
  - meta_send_url: armado de URL Graph API.
  - resolve_sending_number: prioridad numero envio (5 niveles).

NO cubre (requiere DB real con wa_conversations):
  - Lookup de wa_number_id desde una conversacion existente (path 2 de
    resolve_sending_number requiere mock DB que complica el test).
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException


# ── resolve_access_token ─────────────────────────────────────────────────

@pytest.mark.unit
def test_resolve_access_token_uses_baba_for_phone_when_provided():
    """Prioridad 1: token de la WABA del phone_number_id especifico."""
    from app.services.wa_meta_api_service import resolve_access_token

    baba = {"id": "uuid-1"}
    with patch(
        "app.services.wa_babas_service.get_baba_for_phone", return_value=baba,
    ), patch(
        "app.services.wa_babas_service.get_access_token", return_value="token-baba",
    ):
        result = resolve_access_token(phone_number_id="phone-123")

    assert result == "token-baba"


@pytest.mark.unit
def test_resolve_access_token_falls_back_to_default_baba():
    """Prioridad 2: si no hay baba_for_phone, usa la default activa."""
    from app.services.wa_meta_api_service import resolve_access_token

    default_baba = {"id": "uuid-default"}
    with patch(
        "app.services.wa_babas_service.get_baba_for_phone", return_value=None,
    ), patch(
        "app.services.wa_babas_service.get_default_baba", return_value=default_baba,
    ), patch(
        "app.services.wa_babas_service.get_access_token", return_value="token-default",
    ):
        result = resolve_access_token()

    assert result == "token-default"


@pytest.mark.unit
def test_resolve_access_token_falls_back_to_env_legacy(monkeypatch):
    """Prioridad 3: si no hay WABAs, usa settings.meta_wa_access_token."""
    from app.services.wa_meta_api_service import resolve_access_token

    monkeypatch.setattr(
        "app.services.wa_meta_api_service.settings.meta_wa_access_token",
        "token-env-legacy",
    )
    with patch(
        "app.services.wa_babas_service.get_baba_for_phone", return_value=None,
    ), patch(
        "app.services.wa_babas_service.get_default_baba", return_value=None,
    ):
        result = resolve_access_token()

    assert result == "token-env-legacy"


@pytest.mark.unit
def test_resolve_access_token_raises_500_when_nothing_available(monkeypatch):
    """Sin WABAs Y sin env -> HTTPException 500 con mensaje accionable."""
    from app.services.wa_meta_api_service import resolve_access_token

    monkeypatch.setattr(
        "app.services.wa_meta_api_service.settings.meta_wa_access_token",
        "",
    )
    with patch(
        "app.services.wa_babas_service.get_baba_for_phone", return_value=None,
    ), patch(
        "app.services.wa_babas_service.get_default_baba", return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_access_token()

    assert exc.value.status_code == 500
    assert "Configuracion" in exc.value.detail or "configuración" in exc.value.detail.lower()


# ── meta_headers ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_meta_headers_includes_bearer_authorization():
    """Headers tienen Authorization: Bearer <token>."""
    from app.services.wa_meta_api_service import meta_headers

    with patch(
        "app.services.wa_meta_api_service.resolve_access_token",
        return_value="mi-token",
    ):
        headers = meta_headers()

    assert headers["Authorization"] == "Bearer mi-token"
    assert headers["Content-Type"] == "application/json"


# ── meta_send_url ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_meta_send_url_uses_explicit_phone_number_id():
    """Si pasas phone_number_id, se usa ese."""
    from app.services.wa_meta_api_service import meta_send_url, META_GRAPH_BASE

    url = meta_send_url(phone_number_id="999888")
    assert url == f"{META_GRAPH_BASE}/999888/messages"


@pytest.mark.unit
def test_meta_send_url_falls_back_to_env_when_no_param(monkeypatch):
    """Sin param, usa settings.meta_wa_phone_number_id."""
    from app.services.wa_meta_api_service import meta_send_url, META_GRAPH_BASE

    monkeypatch.setattr(
        "app.services.wa_meta_api_service.settings.meta_wa_phone_number_id",
        "env-phone-id",
    )
    url = meta_send_url()
    assert "env-phone-id" in url
    assert url.endswith("/messages")
    assert META_GRAPH_BASE in url


@pytest.mark.unit
def test_meta_send_url_raises_500_when_no_phone_id_available(monkeypatch):
    """Sin param y sin env -> HTTPException 500."""
    from app.services.wa_meta_api_service import meta_send_url

    monkeypatch.setattr(
        "app.services.wa_meta_api_service.settings.meta_wa_phone_number_id",
        "",
    )
    with pytest.raises(HTTPException) as exc:
        meta_send_url()

    assert exc.value.status_code == 500


# ── resolve_sending_number ───────────────────────────────────────────────

@pytest.mark.unit
def test_resolve_sending_number_with_active_explicit_wa_number_id():
    """Prioridad 1: wa_number_id explicito devuelve esa pareja."""
    from app.services.wa_meta_api_service import resolve_sending_number

    num = {"id": 42, "phone_number_id": "phone-meta-42", "activo": True}
    with patch("app.services.wa_numbers_service.get_by_id", return_value=num):
        wa_id, phone_id = resolve_sending_number(wa_number_id=42)

    assert wa_id == 42
    assert phone_id == "phone-meta-42"


@pytest.mark.unit
def test_resolve_sending_number_with_inactive_explicit_raises_400():
    """wa_number_id explicito pero inactivo -> 400 con nombre amigable."""
    from app.services.wa_meta_api_service import resolve_sending_number

    num = {"id": 42, "phone_number_id": "x", "activo": False, "display_name": "Linea Vieja"}
    with patch("app.services.wa_numbers_service.get_by_id", return_value=num):
        with pytest.raises(HTTPException) as exc:
            resolve_sending_number(wa_number_id=42)

    assert exc.value.status_code == 400
    assert "inactiva" in exc.value.detail.lower()
    assert "Linea Vieja" in exc.value.detail


@pytest.mark.unit
def test_resolve_sending_number_with_nonexistent_explicit_raises_404():
    """wa_number_id que no existe -> 404."""
    from app.services.wa_meta_api_service import resolve_sending_number

    with patch("app.services.wa_numbers_service.get_by_id", return_value=None):
        with pytest.raises(HTTPException) as exc:
            resolve_sending_number(wa_number_id=999)

    assert exc.value.status_code == 404


@pytest.mark.unit
def test_resolve_sending_number_uses_advisor_default():
    """Prioridad 3: default del asesor (advisor_default_wa_number_id)."""
    from app.services.wa_meta_api_service import resolve_sending_number

    num = {"id": 5, "phone_number_id": "phone-asesor", "activo": True}
    with patch(
        "app.services.wa_numbers_service.get_by_id", return_value=num,
    ), patch(
        "app.services.wa_numbers_service.get_default", return_value=None,
    ):
        wa_id, phone_id = resolve_sending_number(
            wa_number_id=None, to_phone=None, advisor_default_wa_number_id=5,
        )

    assert wa_id == 5
    assert phone_id == "phone-asesor"


@pytest.mark.unit
def test_resolve_sending_number_uses_global_default():
    """Prioridad 4: default global del catalogo wa_numbers."""
    from app.services.wa_meta_api_service import resolve_sending_number

    default_num = {"id": 99, "phone_number_id": "phone-default", "activo": True}
    with patch(
        "app.services.wa_numbers_service.get_by_id", return_value=None,
    ), patch(
        "app.services.wa_numbers_service.get_default", return_value=default_num,
    ):
        wa_id, phone_id = resolve_sending_number(wa_number_id=None)

    assert wa_id == 99
    assert phone_id == "phone-default"


@pytest.mark.unit
def test_resolve_sending_number_falls_back_to_env_legacy(monkeypatch):
    """Prioridad 5: ningun numero registrado, fallback a env."""
    from app.services.wa_meta_api_service import resolve_sending_number

    monkeypatch.setattr(
        "app.services.wa_meta_api_service.settings.meta_wa_phone_number_id",
        "env-phone-legacy",
    )
    with patch(
        "app.services.wa_numbers_service.get_by_id", return_value=None,
    ), patch(
        "app.services.wa_numbers_service.get_default", return_value=None,
    ):
        wa_id, phone_id = resolve_sending_number(wa_number_id=None)

    assert wa_id is None  # no hay registro
    assert phone_id == "env-phone-legacy"


@pytest.mark.unit
def test_resolve_sending_number_raises_409_with_actionable_code(monkeypatch):
    """Ningun numero disponible Y sin env -> 409 con code WHATSAPP_NOT_CONFIGURED."""
    from app.services.wa_meta_api_service import resolve_sending_number

    monkeypatch.setattr(
        "app.services.wa_meta_api_service.settings.meta_wa_phone_number_id",
        "",
    )
    with patch(
        "app.services.wa_numbers_service.get_by_id", return_value=None,
    ), patch(
        "app.services.wa_numbers_service.get_default", return_value=None,
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_sending_number(wa_number_id=None)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "WHATSAPP_NOT_CONFIGURED"
    assert "WhatsApp" in exc.value.detail["message"]

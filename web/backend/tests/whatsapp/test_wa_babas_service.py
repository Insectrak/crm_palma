"""
Tests de wa_babas_service.py — catalogo multi-WABA con secretos cifrados.

Cubre funciones puras + helpers de cache + getters de secretos.

NO cubre (requiere DB real con extension pgcrypto + secrets_service):
  - create/update/delete (escriben en DB con encriptacion)
  - list_all/get_by_id (requieren rows reales con secretos cifrados)
"""
from unittest.mock import patch

import pytest


# ── invalidate_cache ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_invalidate_cache_clears_both_caches():
    """invalidate_cache() vacia ambos diccionarios de cache module-level."""
    from app.services import wa_babas_service

    # Llenar caches con datos dummy
    wa_babas_service._CACHE_BY_ID[1] = {"id": 1}
    wa_babas_service._CACHE_PHONE_TO_BABA["phone-x"] = {"id": 2}

    wa_babas_service.invalidate_cache()

    assert len(wa_babas_service._CACHE_BY_ID) == 0
    assert len(wa_babas_service._CACHE_PHONE_TO_BABA) == 0


# ── _row_to_public_dict (sin secretos) ───────────────────────────────────

@pytest.mark.unit
def test_row_to_public_dict_masks_access_token():
    """La version publica enmascara el access_token (nunca expone plaintext)."""
    from app.services.wa_babas_service import _row_to_public_dict

    row = {
        "id": 1,
        "waba_id": "waba-123",
        "display_name": "Palma WhatsApp",
        "is_default": True,
        "activo": True,
        "notes": "test",
        "access_token_encrypted": "encrypted-blob",
        "app_secret_encrypted": "secret-encrypted",
        "webhook_verify_token_encrypted": "verify-encrypted",
        "created_at": None,
        "updated_at": None,
    }
    with patch(
        "app.services.wa_babas_service.decrypt",
        side_effect=lambda x: f"plain-{x}" if x else "",
    ), patch(
        "app.services.wa_babas_service.mask", return_value="****1234",
    ), patch(
        "app.services.wa_babas_service.fingerprint", return_value="abcd",
    ):
        result = _row_to_public_dict(row)

    assert result["access_token_mask"] == "****1234"
    # NO debe haber 'access_token' pelado en el dict
    assert "access_token" not in result
    assert "access_token_encrypted" not in result
    assert result["has_app_secret"] is True
    assert result["has_verify_token"] is True


@pytest.mark.unit
def test_row_to_public_dict_marks_missing_secrets_as_false():
    """Si app_secret_encrypted esta vacio, has_app_secret=False."""
    from app.services.wa_babas_service import _row_to_public_dict

    row = {
        "id": 1, "waba_id": "x", "display_name": "x",
        "is_default": False, "activo": True, "notes": None,
        "access_token_encrypted": "enc-token",
        "app_secret_encrypted": "",            # vacio
        "webhook_verify_token_encrypted": "",  # vacio
        "created_at": None, "updated_at": None,
    }
    with patch("app.services.wa_babas_service.decrypt", side_effect=lambda x: x), \
         patch("app.services.wa_babas_service.mask", return_value="m"), \
         patch("app.services.wa_babas_service.fingerprint", return_value="f"):
        result = _row_to_public_dict(row)

    assert result["has_app_secret"] is False
    assert result["has_verify_token"] is False


# ── _row_to_cache_dict (con ciphertexts internos) ────────────────────────

@pytest.mark.unit
def test_row_to_cache_dict_keeps_ciphertexts_with_underscore_prefix():
    """La version interna tiene los blobs cifrados con prefix _ (no expose)."""
    from app.services.wa_babas_service import _row_to_cache_dict

    row = {
        "id": 1, "waba_id": "x", "display_name": "x",
        "is_default": False, "activo": True,
        "access_token_encrypted": "enc-token",
        "app_secret_encrypted": "enc-secret",
        "webhook_verify_token_encrypted": "enc-verify",
    }
    result = _row_to_cache_dict(row)

    assert result["_access_enc"] == "enc-token"
    assert result["_app_secret_enc"] == "enc-secret"
    assert result["_verify_token_enc"] == "enc-verify"
    # SIN campos planos de secretos
    assert "access_token" not in result
    assert "app_secret" not in result


# ── Getters de secretos (descifran) ──────────────────────────────────────

@pytest.mark.unit
def test_get_access_token_decrypts_from_cache_dict():
    from app.services.wa_babas_service import get_access_token

    baba = {"_access_enc": "encrypted-token"}
    with patch(
        "app.services.wa_babas_service.decrypt",
        return_value="plain-token",
    ):
        result = get_access_token(baba)

    assert result == "plain-token"


@pytest.mark.unit
def test_get_app_secret_decrypts_from_cache_dict():
    from app.services.wa_babas_service import get_app_secret

    baba = {"_app_secret_enc": "encrypted-secret"}
    with patch(
        "app.services.wa_babas_service.decrypt",
        return_value="plain-secret",
    ):
        result = get_app_secret(baba)

    assert result == "plain-secret"


@pytest.mark.unit
def test_get_verify_token_decrypts_from_cache_dict():
    from app.services.wa_babas_service import get_verify_token

    baba = {"_verify_token_enc": "encrypted-verify"}
    with patch(
        "app.services.wa_babas_service.decrypt",
        return_value="plain-verify",
    ):
        result = get_verify_token(baba)

    assert result == "plain-verify"


@pytest.mark.unit
def test_get_access_token_missing_key_returns_none():
    """Si el dict NO tiene _access_enc, decrypt(None) -> None."""
    from app.services.wa_babas_service import get_access_token

    with patch("app.services.wa_babas_service.decrypt", return_value=None):
        assert get_access_token({}) is None


# ── find_baba_by_verify_token ────────────────────────────────────────────

@pytest.mark.unit
def test_find_baba_by_verify_token_empty_returns_none():
    """Token vacio -> None (no consulta DB)."""
    from app.services.wa_babas_service import find_baba_by_verify_token

    assert find_baba_by_verify_token("") is None
    assert find_baba_by_verify_token(None) is None


@pytest.mark.unit
def test_find_baba_by_verify_token_matches_baba_with_token(monkeypatch):
    """Token incoming matchea (constant-time) con uno descifrado -> devuelve baba."""
    from app.services import wa_babas_service
    from tests.fixtures import fake_db_returning

    # 2 babas, segunda matchea
    rows = [
        {
            "id": 1, "waba_id": "w1", "display_name": "B1",
            "is_default": False, "activo": True,
            "access_token_encrypted": "x", "app_secret_encrypted": "",
            "webhook_verify_token_encrypted": "wrong-enc",
        },
        {
            "id": 2, "waba_id": "w2", "display_name": "B2",
            "is_default": False, "activo": True,
            "access_token_encrypted": "y", "app_secret_encrypted": "",
            "webhook_verify_token_encrypted": "match-enc",
        },
    ]
    monkeypatch.setattr(
        "app.services.wa_babas_service.get_db",
        fake_db_returning(rows),
    )

    def _decrypt(blob):
        if blob == "match-enc": return "the-correct-token"
        if blob == "wrong-enc": return "other-token"
        return ""

    monkeypatch.setattr("app.services.wa_babas_service.decrypt", _decrypt)

    result = wa_babas_service.find_baba_by_verify_token("the-correct-token")

    assert result is not None
    assert result["id"] == 2
    assert "_access_enc" in result  # cache dict


@pytest.mark.unit
def test_find_baba_by_verify_token_no_match_returns_none(monkeypatch):
    """Si ningun verify_token matchea, devuelve None."""
    from app.services import wa_babas_service
    from tests.fixtures import fake_db_returning

    rows = [
        {
            "id": 1, "waba_id": "w", "display_name": "B",
            "is_default": False, "activo": True,
            "access_token_encrypted": "x", "app_secret_encrypted": "",
            "webhook_verify_token_encrypted": "wrong-enc",
        },
    ]
    monkeypatch.setattr(
        "app.services.wa_babas_service.get_db",
        fake_db_returning(rows),
    )
    monkeypatch.setattr(
        "app.services.wa_babas_service.decrypt",
        lambda blob: "other-token",
    )

    assert wa_babas_service.find_baba_by_verify_token("incoming-token") is None

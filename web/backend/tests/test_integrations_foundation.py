"""Tests de la fundación de integraciones.

Cubren:
  - Registry: whitelist de proveedores/keys.
  - Crypto roundtrip de credentials_repo (via secrets_service).
  - Mask / fingerprint helpers.
  - Normalización de teléfonos en ingest_core.clean_phone.
  - Auth de endpoints /api/integrations/* (admin obligatorio).

No tocan DB real — CI corre con DEMO_MODE=true. Las operaciones de
repositorio que sí tocan DB se validan en entornos con Postgres real.
"""
from __future__ import annotations


# ── Registry ────────────────────────────────────────────────────────────────

def test_registry_lists_meta_and_tiktok():
    from app.services.integrations.registry import list_providers

    ids = [p.provider for p in list_providers()]
    assert "meta" in ids
    assert "tiktok" in ids


def test_registry_validates_keys():
    from app.services.integrations.registry import is_valid_key

    assert is_valid_key("meta", "app_secret") is True
    assert is_valid_key("meta", "nonexistent_key") is False
    assert is_valid_key("unknown_provider", "app_secret") is False


def test_registry_key_spec_marks_secrets_correctly():
    from app.services.integrations.registry import key_spec

    assert key_spec("meta", "app_secret").is_secret is True
    assert key_spec("meta", "app_id").is_secret is False
    assert key_spec("tiktok", "access_token").per_account is True


# ── Crypto ──────────────────────────────────────────────────────────────────

def test_secrets_service_roundtrip_preserves_value():
    from app.services.secrets_service import encrypt, decrypt

    plaintext = "EAAG1234567890supersecret"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_secrets_service_mask_hides_full_value():
    from app.services.secrets_service import mask

    assert mask("EAAG1234567890abc").endswith("0abc")
    assert "EAAG" not in mask("EAAG1234567890abc")


def test_secrets_service_fingerprint_is_deterministic_and_short():
    from app.services.secrets_service import fingerprint

    fp1 = fingerprint("my-token")
    fp2 = fingerprint("my-token")
    assert fp1 == fp2
    assert len(fp1) == 8
    assert fingerprint("other-token") != fp1


# ── ingest_core helpers ─────────────────────────────────────────────────────

def test_clean_phone_normalizes_peru_9_digits():
    from app.services.integrations.ingest_core import clean_phone

    assert clean_phone("987654321") == "+51987654321"
    assert clean_phone("51987654321") == "+51987654321"
    assert clean_phone("+51 987 654 321") == "+51987654321"


def test_clean_phone_rejects_invalid_inputs():
    from app.services.integrations.ingest_core import clean_phone

    assert clean_phone("") is None
    assert clean_phone(None) is None
    assert clean_phone("000000000") is None
    assert clean_phone("123") is None  # menos de 7 dígitos


# ── Endpoints: auth ────────────────────────────────────────────────────────

def test_providers_requires_admin_auth(client):
    # Sin token → 401/403
    resp = client.get("/api/integrations/providers")
    assert resp.status_code in (401, 403)


def test_providers_rejects_non_admin(client, auth_headers_asesor):
    resp = client.get("/api/integrations/providers", headers=auth_headers_asesor)
    assert resp.status_code == 403


def test_providers_rejects_supervisor(client, auth_headers_supervisor):
    resp = client.get("/api/integrations/providers", headers=auth_headers_supervisor)
    assert resp.status_code == 403


def test_credentials_endpoints_reject_unknown_provider(client, auth_headers_admin):
    resp = client.get(
        "/api/integrations/unknown_provider/credentials",
        headers=auth_headers_admin,
    )
    assert resp.status_code == 404

    resp = client.get(
        "/api/integrations/unknown_provider/events",
        headers=auth_headers_admin,
    )
    assert resp.status_code == 404


# ── credentials_repo: errores de negocio sin DB ─────────────────────────────

def test_upsert_rejects_unknown_key():
    from app.services.integrations.credentials_repo import (
        CredentialsRepoError,
        upsert_credential,
    )
    import pytest

    with pytest.raises(CredentialsRepoError):
        upsert_credential("meta", "i_do_not_exist", "val")


def test_upsert_rejects_global_only_key_with_account_id():
    from app.services.integrations.credentials_repo import (
        CredentialsRepoError,
        upsert_credential,
    )
    import pytest

    # app_secret es global — no admite account_id específico
    with pytest.raises(CredentialsRepoError):
        upsert_credential("meta", "app_secret", "val", account_id="page_123")


def test_upsert_rejects_empty_value():
    from app.services.integrations.credentials_repo import (
        CredentialsRepoError,
        upsert_credential,
    )
    import pytest

    with pytest.raises(CredentialsRepoError):
        upsert_credential("meta", "app_secret", "")


# ── events_repo: validaciones que no tocan DB ──────────────────────────────

def test_list_events_clamps_limit():
    """Clampeo de limit debe ser puro — no llegar a DB para validar."""
    import inspect
    from app.services.integrations import events_repo

    src = inspect.getsource(events_repo.list_events)
    # Defensa explícita en el source
    assert "min(limit, 500)" in src

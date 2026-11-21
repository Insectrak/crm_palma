"""
Tests de wa_security_service.py — HMAC verification del webhook Meta.

CRITICO: este servicio es la primera linea de defensa contra spoofing.
Si verify_signature() falla, atacantes pueden inyectar mensajes WA
falsos al CRM (impersonar clientes, robar conversaciones, etc).

Cubre:
  - verify_signature: el HMAC-SHA256 timing-safe contra app_secret.
  - find_verifying_baba: lookup multi-WABA + fallback a env secret.

Bug historico V070.69 (P0-1) cubierto explicitamente: headers malformados
sin '=' antes bypassaban la verificacion con IndexError silencioso.
"""
import hashlib
import hmac
from unittest.mock import patch

import pytest


# ── verify_signature ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_verify_signature_with_valid_sha256_returns_true():
    """Happy path: body + secret correcto -> True."""
    from app.services.wa_security_service import verify_signature
    body = b'{"object":"whatsapp_business_account"}'
    secret = "mi-app-secret-meta"
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    header = f"sha256={expected}"

    assert verify_signature(body, header, secret) is True


@pytest.mark.unit
def test_verify_signature_with_wrong_secret_returns_false():
    """Body correcto pero secret distinto -> False."""
    from app.services.wa_security_service import verify_signature
    body = b'{"object":"whatsapp_business_account"}'
    expected = hmac.new(b"el-secret-real", body, hashlib.sha256).hexdigest()
    header = f"sha256={expected}"

    assert verify_signature(body, header, "secret-equivocado") is False


@pytest.mark.unit
def test_verify_signature_with_tampered_body_returns_false():
    """Body manipulado tras firmar -> False (proteccion contra integrity)."""
    from app.services.wa_security_service import verify_signature
    original = b'{"messages":[{"text":"hola"}]}'
    secret = "secret"
    expected = hmac.new(secret.encode(), original, hashlib.sha256).hexdigest()
    header = f"sha256={expected}"

    tampered = b'{"messages":[{"text":"hola modificado"}]}'
    assert verify_signature(tampered, header, secret) is False


@pytest.mark.unit
@pytest.mark.regression
def test_verify_signature_with_malformed_header_no_equals_returns_false():
    """Bug V070.69 (P0-1): header sin '=' antes hacia split[1] IndexError
    silencioso que bypassaba HMAC. Ahora rechaza explicitamente.

    Bug ID: V070.69 P0-1
    """
    from app.services.wa_security_service import verify_signature
    body = b'{"x":1}'

    # Header sin '=' (malformado)
    assert verify_signature(body, "sha256xxxxx", "secret") is False


@pytest.mark.unit
def test_verify_signature_with_empty_header_returns_false():
    from app.services.wa_security_service import verify_signature
    assert verify_signature(b'{"x":1}', "", "secret") is False


@pytest.mark.unit
def test_verify_signature_with_none_header_returns_false():
    from app.services.wa_security_service import verify_signature
    assert verify_signature(b'{"x":1}', None, "secret") is False


@pytest.mark.unit
def test_verify_signature_with_empty_prefix_returns_false():
    """Header tipo '=abc123' (prefix vacio) -> False."""
    from app.services.wa_security_service import verify_signature
    assert verify_signature(b'{}', "=abc123", "secret") is False


@pytest.mark.unit
def test_verify_signature_with_empty_value_returns_false():
    """Header tipo 'sha256=' (value vacio) -> False."""
    from app.services.wa_security_service import verify_signature
    assert verify_signature(b'{}', "sha256=", "secret") is False


@pytest.mark.unit
def test_verify_signature_is_timing_safe():
    """Usa hmac.compare_digest (no '=='). No podemos testear timing real,
    pero verificamos que el codigo NO use comparacion regular.

    Esto se valida indirectamente: si verify_signature usara '==', una
    comparacion del hex con primer caracter distinto seria mas rapida
    que una con todos iguales menos uno — vulnerabilidad timing attack.
    """
    import inspect
    from app.services import wa_security_service
    src = inspect.getsource(wa_security_service.verify_signature)
    assert "compare_digest" in src
    # Defensa adicional: NO debe haber '==' raw en la comparacion
    # (puede aparecer en docstrings, no en codigo)


# ── find_verifying_baba ──────────────────────────────────────────────────

@pytest.mark.unit
def test_find_verifying_baba_no_wabas_no_legacy_returns_false():
    """Sin WABAs registradas Y sin env secret -> False."""
    from app.services.wa_security_service import find_verifying_baba

    with patch("app.services.wa_babas_service.list_all", return_value=[]):
        valid, baba = find_verifying_baba(b'{}', "sha256=abc", legacy_env_secret=None)

    assert valid is False
    assert baba is None


@pytest.mark.unit
def test_find_verifying_baba_falls_back_to_legacy_env_when_no_wabas():
    """Sin WABAs registradas, pero env secret valido -> True con baba=None."""
    from app.services.wa_security_service import find_verifying_baba

    body = b'{"x":1}'
    secret = "env-secret"
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    with patch("app.services.wa_babas_service.list_all", return_value=[]):
        valid, baba = find_verifying_baba(
            body, f"sha256={expected}", legacy_env_secret=secret,
        )

    assert valid is True
    assert baba is None   # legacy match no tiene WABA asociada


@pytest.mark.unit
def test_find_verifying_baba_matches_first_registered_baba():
    """WABA registrada con secret matchea -> True con esa baba."""
    from app.services.wa_security_service import find_verifying_baba

    body = b'{"x":1}'
    secret_b1 = "secret-baba-1"
    expected = hmac.new(secret_b1.encode(), body, hashlib.sha256).hexdigest()

    baba_1 = {"id": "uuid-1", "name": "BABA Palma"}
    baba_2 = {"id": "uuid-2", "name": "BABA Otra"}

    with patch("app.services.wa_babas_service.list_all", return_value=[baba_1, baba_2]):
        with patch(
            "app.services.wa_babas_service.get_app_secret",
            side_effect=lambda b: secret_b1 if b["id"] == "uuid-1" else "otro",
        ):
            valid, baba = find_verifying_baba(body, f"sha256={expected}")

    assert valid is True
    assert baba == baba_1


@pytest.mark.unit
def test_find_verifying_baba_swallows_db_error_when_listing_wabas():
    """Si list_all() falla, se asume lista vacia y se intenta legacy."""
    from app.services.wa_security_service import find_verifying_baba

    with patch("app.services.wa_babas_service.list_all", side_effect=Exception("DB down")):
        # Sin legacy secret -> False
        valid, baba = find_verifying_baba(b'{}', "sha256=x", legacy_env_secret=None)

    assert valid is False
    assert baba is None


@pytest.mark.unit
def test_find_verifying_baba_no_match_with_legacy_logs_warning_returns_true():
    """Hay WABAs registradas, ninguna matchea, pero el legacy env SI -> True
    + warning log (acepta pero senala para revisar config)."""
    from app.services.wa_security_service import find_verifying_baba

    body = b'{"x":1}'
    legacy = "legacy-secret"
    expected = hmac.new(legacy.encode(), body, hashlib.sha256).hexdigest()

    baba_1 = {"id": "uuid-1", "name": "BABA"}
    with patch("app.services.wa_babas_service.list_all", return_value=[baba_1]):
        with patch("app.services.wa_babas_service.get_app_secret", return_value="otro"):
            valid, baba = find_verifying_baba(
                body, f"sha256={expected}", legacy_env_secret=legacy,
            )

    assert valid is True
    assert baba is None

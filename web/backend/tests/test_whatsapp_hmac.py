"""Tests para `_signature_matches` del webhook WhatsApp.

V070.69 (Bundle A — P0-1): regresion del bug donde un header HMAC malformado
provocaba IndexError que se propagaba arriba del bloque de validacion,
permitiendo bypass de la firma.
"""
import hashlib
import hmac as _hmac

import pytest

from app.routers.whatsapp import _signature_matches


SECRET = "test-app-secret-32-chars-long-xx"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


def _valid_signature() -> str:
    digest = _hmac.new(SECRET.encode("utf-8"), BODY, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestSignatureMatches:
    def test_firma_valida_se_acepta(self):
        assert _signature_matches(BODY, _valid_signature(), SECRET) is True

    def test_firma_invalida_se_rechaza(self):
        # Mismo formato pero hex tampered
        bad = "sha256=" + ("0" * 64)
        assert _signature_matches(BODY, bad, SECRET) is False

    @pytest.mark.regression
    def test_header_sin_igual_no_levanta_index_error(self):
        """Bug ID: Bundle A P0-1 (auditoria 2026-05).

        Antes: `signature_header.split("=", 1)[1]` levantaba IndexError
        si el header no tenia '=', propagandose arriba del bloque de seguridad.
        Ahora: rechazo explicito.
        """
        result = _signature_matches(BODY, "sha256-no-equals-sign", SECRET)
        assert result is False

    @pytest.mark.regression
    def test_header_vacio_se_rechaza(self):
        assert _signature_matches(BODY, "", SECRET) is False

    @pytest.mark.regression
    def test_header_solo_igual_se_rechaza(self):
        # Header "=" -> prefix vacio y received vacio
        assert _signature_matches(BODY, "=", SECRET) is False

    @pytest.mark.regression
    def test_header_sin_prefijo_se_rechaza(self):
        # Header "=valor" -> prefix vacio
        assert _signature_matches(BODY, "=abc123", SECRET) is False

    @pytest.mark.regression
    def test_header_sin_valor_se_rechaza(self):
        # Header "sha256=" -> received vacio
        assert _signature_matches(BODY, "sha256=", SECRET) is False

    def test_secret_distinto_se_rechaza(self):
        # Firma correcta con OTRO secret no debe pasar
        digest = _hmac.new(b"OTRO_SECRET_DISTINTO_32_CHARS!!", BODY, hashlib.sha256).hexdigest()
        assert _signature_matches(BODY, f"sha256={digest}", SECRET) is False

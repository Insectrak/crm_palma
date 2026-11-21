"""Tests para `app.pii_utils` — helpers de enmascarado de datos personales.

V070.69 (Bundle A — P1-3): cumplimiento Ley 29733 PE (minimizacion de PII
en logs). Cada cambio en mask_* debe pasar estos tests para mantener el
contrato (ultimos 4 chars visibles, fallback 'none', sin crashes).
"""
import pytest

from app.pii_utils import mask_dni, mask_email, mask_phone


class TestMaskPhone:
    def test_telefono_peruano_9_digitos(self):
        assert mask_phone("987654321") == "***4321"

    def test_telefono_con_codigo_pais(self):
        assert mask_phone("+51987654321") == "***4321"

    def test_telefono_con_separadores(self):
        assert mask_phone("+51 987 654 321") == "***4321"
        assert mask_phone("(987) 654-321") == "***4321"

    def test_telefono_internacional_15_digitos(self):
        assert mask_phone("+12025550100") == "***0100"

    def test_telefono_vacio_o_none(self):
        assert mask_phone("") == "none"
        assert mask_phone(None) == "none"

    def test_telefono_muy_corto_no_enmascara(self):
        # Muy corto = ya ambiguo, no agregamos asteriscos.
        assert mask_phone("99") == "99"
        assert mask_phone("1234") == "1234"


class TestMaskEmail:
    def test_email_normal(self):
        # 'juan' -> 'j**n'
        assert mask_email("juan@test.com") == "j**n@test.com"

    def test_email_local_corto(self):
        # 'ab' (2 chars) → 'a*'
        assert mask_email("ab@test.com") == "a*@test.com"

    def test_email_local_1_char(self):
        assert mask_email("a@test.com") == "a*@test.com"

    def test_email_largo(self):
        assert mask_email("Soporte.bravo@crm.local") == "g***********o@crm.local"

    def test_email_vacio(self):
        assert mask_email("") == "none"
        assert mask_email(None) == "none"

    def test_email_sin_arroba_es_invalido(self):
        assert mask_email("noemail") == "***"


class TestMaskDni:
    def test_dni_peruano_8_digitos(self):
        # DNI peruano son 8 digitos -> '****3456'
        assert mask_dni("40123456") == "****3456"

    def test_dni_con_separadores(self):
        # 'DNI: 40-12-3456' → solo digitos cuentan
        assert mask_dni("DNI: 40-12-3456") == "****3456"

    def test_dni_corto_no_enmascara(self):
        assert mask_dni("123") == "123"
        assert mask_dni("1234") == "1234"

    def test_dni_vacio(self):
        assert mask_dni("") == "none"
        assert mask_dni(None) == "none"

"""Tests del PII scrubbing en observability.py — V070.99.

Antes de mandar eventos a Sentry, before_send() debe enmascarar PII
(telefonos, emails, DNI) y borrar secretos (passwords, api keys, tokens)
para cumplir Ley 29733 PE. Estos tests verifican que el scrubbing
funciona aunque el evento tenga estructura nested compleja.
"""
from app.observability import _scrub_value, _scrub_recursive, _before_send


class TestScrubValue:
    """V070.99 — _scrub_value() enmascara por nombre de campo."""

    def test_telefono_se_enmascara(self):
        assert _scrub_value("telefono", "+51987654321") == "***4321"
        assert _scrub_value("phone", "987654321") == "***4321"
        assert _scrub_value("wa_phone", "51987654321") == "***4321"

    def test_email_se_enmascara(self):
        assert _scrub_value("email", "juan@test.com") == "j**n@test.com"
        assert _scrub_value("correo", "ana@gmail.com") == "a*a@gmail.com"

    def test_dni_se_enmascara(self):
        assert _scrub_value("dni", "40123456") == "****3456"
        assert _scrub_value("documento", "12345678") == "****5678"

    def test_password_se_redacta(self):
        assert _scrub_value("password", "Secret123!") == "[REDACTED]"
        assert _scrub_value("api_key", "cli_xxx") == "[REDACTED]"
        assert _scrub_value("authorization", "Bearer eyJ...") == "[REDACTED]"

    def test_campo_neutro_pasa_intacto(self):
        assert _scrub_value("nombres", "Maria") == "Maria"
        assert _scrub_value("ciudad", "Arequipa") == "Arequipa"
        assert _scrub_value("id", 42) == 42

    def test_case_insensitive(self):
        assert _scrub_value("Telefono", "+51987654321") == "***4321"
        # mask_email con local "x" (1 char) → "*" + "*" = "**"... ver pii_utils
        # local "x" => "x*" (primer char + asterisco). Solo verificamos que enmascara.
        result = _scrub_value("EMAIL", "anita@y.com")
        assert "@y.com" in result and result != "anita@y.com"

    def test_none_value_se_preserva(self):
        assert _scrub_value("telefono", None) is None


class TestScrubRecursive:
    """V070.99 — recorre dicts y listas nested aplicando scrubbing."""

    def test_dict_simple(self):
        out = _scrub_recursive({"telefono": "+51987654321", "nombres": "Ana"})
        assert out["telefono"] == "***4321"
        assert out["nombres"] == "Ana"

    def test_dict_nested(self):
        evento = {
            "request": {
                "data": {
                    "telefono": "+51987654321",
                    "email": "x@y.com",
                    "password": "secret",
                }
            }
        }
        out = _scrub_recursive(evento)
        assert out["request"]["data"]["telefono"] == "***4321"
        # email enmascarado: contiene "@y.com" pero NO el local original
        masked_email = out["request"]["data"]["email"]
        assert "@y.com" in masked_email and masked_email != "x@y.com"
        assert out["request"]["data"]["password"] == "[REDACTED]"

    def test_lista_de_dicts(self):
        out = _scrub_recursive([
            {"telefono": "+51987654321"},
            {"telefono": "+51986777920"},
        ])
        assert out[0]["telefono"] == "***4321"
        assert out[1]["telefono"] == "***7920"

    def test_depth_cap_no_infinito(self):
        # Estructura profunda no debe crashear ni colgar.
        obj = {"a": {"a": {"a": {"a": {"a": {"a": {"a": {"a": {"a": "x"}}}}}}}}}
        _scrub_recursive(obj)  # no exception


class TestBeforeSend:
    """V070.99 — before_send filtra ruido y scrubbea PII."""

    def test_descarta_health_check(self):
        event = {"transaction": "/health"}
        assert _before_send(event, {}) is None

    def test_descarta_metrics_endpoint(self):
        event = {"transaction": "/metrics"}
        assert _before_send(event, {}) is None

    def test_descarta_webhook_whatsapp(self):
        event = {"transaction": "/api/whatsapp/webhook"}
        assert _before_send(event, {}) is None

    def test_descarta_422(self):
        class FakeExc(Exception):
            status_code = 422
        hint = {"exc_info": (FakeExc, FakeExc(), None)}
        assert _before_send({}, hint) is None

    def test_descarta_429(self):
        class FakeExc(Exception):
            status_code = 429
        hint = {"exc_info": (FakeExc, FakeExc(), None)}
        assert _before_send({}, hint) is None

    def test_scrubbea_request_body(self):
        event = {
            "transaction": "/api/leads",
            "request": {
                "data": {
                    "telefono": "+51987654321",
                    "email": "ana@test.com",
                    "nombres": "Ana",
                }
            }
        }
        out = _before_send(event, {})
        assert out is not None
        assert out["request"]["data"]["telefono"] == "***4321"
        assert "@test.com" in out["request"]["data"]["email"]
        assert out["request"]["data"]["nombres"] == "Ana"

    def test_scrubbea_headers_authorization(self):
        event = {
            "transaction": "/api/leads",
            "request": {
                "headers": {
                    "authorization": "Bearer eyJsecret...",
                    "x-api-key": "cli_secret_xxx",
                    "content-type": "application/json",
                }
            }
        }
        out = _before_send(event, {})
        assert out["request"]["headers"]["authorization"] == "[REDACTED]"
        assert out["request"]["headers"]["x-api-key"] == "[REDACTED]"
        assert out["request"]["headers"]["content-type"] == "application/json"

    def test_scrubbea_breadcrumbs(self):
        event = {
            "transaction": "/api/leads",
            "breadcrumbs": {
                "values": [
                    {"data": {"telefono": "+51987654321"}},
                    {"data": {"password": "secret"}},
                ]
            }
        }
        out = _before_send(event, {})
        assert out["breadcrumbs"]["values"][0]["data"]["telefono"] == "***4321"
        assert out["breadcrumbs"]["values"][1]["data"]["password"] == "[REDACTED]"

    def test_evento_neutro_pasa(self):
        event = {"transaction": "/api/leads", "message": "Lead creado"}
        assert _before_send(event, {}) is event


class TestInitSentryNoCrashSinDsn:
    """V070.66 — init_sentry sin DSN debe ser no-op sin excepcion."""

    def test_sin_dsn_devuelve_false(self):
        from app.observability import init_sentry
        assert init_sentry(dsn="") is False
        assert init_sentry(dsn=None) is False
        assert init_sentry(dsn="   ") is False

    def test_set_tenant_context_sin_sentry_es_noop(self):
        # Si sentry_sdk no inicializado, no debe crashear.
        from app.observability import set_tenant_context
        set_tenant_context(tenant="test.com", user_id="u1")
        # Llega aqui sin excepcion → OK

"""
Tests del servicio de formularios publicos — validacion, canonicalizacion y anti-spam.
"""
import pytest
from unittest.mock import patch
from fastapi import HTTPException


# ── Helpers de normalize/canonicalize (funciones puras, sin I/O) ────────────

from app.services.public_forms_service import (
    _normalize_phone,
    _canonicalize_name,
    _canonicalize_observaciones,
    _check_antispam,
    _check_form_availability,
    _validate_config,
    HONEYPOT_FIELD,
)


# ── _normalize_phone ────────────────────────────────────────────────────────

class TestNormalizePhone:
    def test_nine_digit_mobile(self):
        assert _normalize_phone("941468455") == "+51941468455"

    def test_with_country_code_no_plus(self):
        assert _normalize_phone("51941468455") == "+51941468455"

    def test_already_e164(self):
        assert _normalize_phone("+51941468455") == "+51941468455"

    def test_with_formatting(self):
        assert _normalize_phone("+51 941-468-455") == "+51941468455"

    def test_foreign_number_preserved(self):
        assert _normalize_phone("+1234567890") == "+1234567890"

    def test_empty_string(self):
        assert _normalize_phone("") == ""

    def test_short_landline(self):
        result = _normalize_phone("2345678")
        assert result.startswith("+51")


# ── _canonicalize_name ──────────────────────────────────────────────────────

class TestCanonicalizeName:
    def test_title_case(self):
        assert _canonicalize_name("  juan  PEDRO ") == "Juan Pedro"

    def test_preserves_accents(self):
        assert _canonicalize_name("maría") == "María"

    def test_empty_returns_empty(self):
        assert _canonicalize_name("   ") == ""

    def test_single_name(self):
        assert _canonicalize_name("carlos") == "Carlos"


# ── _canonicalize_observaciones ─────────────────────────────────────────────

class TestCanonicalizeObservaciones:
    def test_trims_whitespace(self):
        assert _canonicalize_observaciones("  hello  ") == "hello"

    def test_collapses_newlines(self):
        result = _canonicalize_observaciones("line1\n\n\n\nline2")
        assert result == "line1\n\nline2"

    def test_preserves_double_newline(self):
        result = _canonicalize_observaciones("paragraph1\n\nparagraph2")
        assert result == "paragraph1\n\nparagraph2"


# ── _check_antispam ────────────────────────────────────────────────────────

class TestCheckAntispam:
    def _make_form(self, form_id="test-form-id"):
        return {"id": form_id, "activo": True}

    def test_honeypot_triggers_rejection(self):
        form = self._make_form()
        payload = {HONEYPOT_FIELD: "spambot-value"}
        with pytest.raises(HTTPException) as exc:
            _check_antispam(form, payload, elapsed_seconds=10.0, ip_address="1.2.3.4")
        assert exc.value.status_code == 400

    def test_clean_honeypot_passes(self):
        form = self._make_form()
        payload = {HONEYPOT_FIELD: ""}
        # No debe lanzar excepcion (min_time OK, sin IP check)
        _check_antispam(form, payload, elapsed_seconds=10.0, ip_address=None)

    def test_min_time_triggers_rejection(self):
        form = self._make_form()
        payload = {}
        with pytest.raises(HTTPException) as exc:
            _check_antispam(form, payload, elapsed_seconds=0.5, ip_address=None)
        assert exc.value.status_code == 400

    @patch("app.services.public_forms_service.repo.count_recent_submissions_by_ip", return_value=100)
    def test_ip_rate_limit_triggers_429(self, mock_count):
        form = self._make_form()
        payload = {}
        with pytest.raises(HTTPException) as exc:
            _check_antispam(form, payload, elapsed_seconds=10.0, ip_address="1.2.3.4")
        assert exc.value.status_code == 429

    @patch("app.services.public_forms_service.repo.count_recent_submissions_by_ip", return_value=0)
    def test_ip_under_limit_passes(self, mock_count):
        form = self._make_form()
        payload = {}
        _check_antispam(form, payload, elapsed_seconds=10.0, ip_address="1.2.3.4")


# ── _check_form_availability ───────────────────────────────────────────────

class TestCheckFormAvailability:
    def test_inactive_form_raises_410(self):
        form = {"activo": False}
        with pytest.raises(HTTPException) as exc:
            _check_form_availability(form)
        assert exc.value.status_code == 410

    def test_active_form_passes(self):
        form = {"activo": True, "expires_at": None, "max_submissions": None}
        _check_form_availability(form)

    def test_expired_form_raises_410(self):
        from datetime import datetime, timezone, timedelta
        form = {
            "activo": True,
            "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
            "max_submissions": None,
        }
        with pytest.raises(HTTPException) as exc:
            _check_form_availability(form)
        assert exc.value.status_code == 410

    def test_max_submissions_reached_raises_410(self):
        form = {
            "activo": True,
            "expires_at": None,
            "max_submissions": 10,
            "submission_count": 10,
        }
        with pytest.raises(HTTPException) as exc:
            _check_form_availability(form)
        assert exc.value.status_code == 410

    def test_under_max_submissions_passes(self):
        form = {
            "activo": True,
            "expires_at": None,
            "max_submissions": 10,
            "submission_count": 5,
        }
        _check_form_availability(form)


# ── _validate_config ───────────────────────────────────────────────────────

class TestValidateConfig:
    def test_valid_config(self):
        config = {
            "campos": [
                {"key": "nombres", "label": "Nombre", "required": True, "type": "text"},
                {"key": "telefono", "label": "Telefono", "required": True, "type": "tel"},
            ]
        }
        result = _validate_config(config)
        assert len(result["campos"]) == 2
        assert result["mensaje_exito"] is not None

    def test_empty_campos_raises_422(self):
        with pytest.raises(HTTPException) as exc:
            _validate_config({"campos": []})
        assert exc.value.status_code == 422

    def test_unknown_fields_ignored(self):
        config = {
            "campos": [
                {"key": "nombres", "required": True},
                {"key": "telefono", "required": True},
                {"key": "unknown_field", "required": True},
            ]
        }
        result = _validate_config(config)
        keys = [c["key"] for c in result["campos"]]
        assert "unknown_field" not in keys

    def test_no_contact_field_required_raises_422(self):
        config = {
            "campos": [
                {"key": "nombres", "required": True},
            ]
        }
        with pytest.raises(HTTPException) as exc:
            _validate_config(config)
        assert exc.value.status_code == 422

    def test_duplicate_field_raises_422(self):
        config = {
            "campos": [
                {"key": "telefono", "required": True},
                {"key": "telefono", "required": False},
            ]
        }
        with pytest.raises(HTTPException) as exc:
            _validate_config(config)
        assert exc.value.status_code == 422

    def test_non_dict_config_raises_422(self):
        with pytest.raises(HTTPException) as exc:
            _validate_config("not a dict")
        assert exc.value.status_code == 422

"""
Tests de safe_set_clause — validacion de columnas en queries dinamicas.
"""
import pytest
from app.sql_utils import safe_set_clause


class TestSafeSetClause:
    def test_valid_fields(self):
        allowed = {"nombre", "email", "telefono"}
        fields = {"nombre": "Juan", "email": "j@test.com"}
        clause, params = safe_set_clause(fields, allowed)
        assert "nombre = %s" in clause
        assert "email = %s" in clause
        assert params == ["Juan", "j@test.com"]

    def test_rejects_unknown_column(self):
        allowed = {"nombre", "email"}
        fields = {"nombre": "Juan", "password_hash": "evil"}
        with pytest.raises(ValueError, match="no permitidas"):
            safe_set_clause(fields, allowed)

    def test_rejects_invalid_column_name(self):
        allowed = {"nombre", "1invalid"}
        fields = {"1invalid": "val"}
        with pytest.raises(ValueError, match="invalido"):
            safe_set_clause(fields, allowed)

    def test_single_field(self):
        allowed = {"nombre"}
        fields = {"nombre": "Test"}
        clause, params = safe_set_clause(fields, allowed)
        assert clause == "nombre = %s"
        assert params == ["Test"]

    def test_empty_fields_returns_empty(self):
        allowed = {"nombre"}
        clause, params = safe_set_clause({}, allowed)
        assert clause == ""
        assert params == []

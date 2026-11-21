"""
Tests unitarios para la búsqueda de leads por teléfono con dígitos separados:
Verifica que apply_lead_filters normalice correctamente números telefónicos con
espacios, guiones, símbolos o formato internacional (paridad con Históricos),
manteniendo la compatibilidad con búsquedas de nombres, DNI y correos electrónicos.
"""
from unittest.mock import MagicMock

from app.constants import Role
from app.filters.lead_filters import LeadFilters, apply_lead_filters


def _admin_user():
    user = MagicMock()
    user.role = Role.ADMIN
    user.user_id = "admin-uuid"
    return user


def test_busqueda_digitos_separados_por_espacios():
    """Ej: '9 5 1 2 3 4 5 6 7' debe normalizarse a '%951234567%' y usar REGEXP_REPLACE."""
    filters = LeadFilters(search="9 5 1 2 3 4 5 6 7")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g') LIKE %s" in where
    assert "l.telefono ILIKE %s" in where
    assert "l.dni ILIKE %s" in where
    assert "%951234567%" in params


def test_busqueda_telefono_bloques_espaciados():
    """Ej: '951 234 567' debe normalizarse a '%951234567%'."""
    filters = LeadFilters(search="951 234 567")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g') LIKE %s" in where
    assert "%951234567%" in params


def test_busqueda_telefono_con_codigo_pais():
    """Ej: '+51 951 234 567' debe extraer los últimos 9 dígitos ('%951234567%')."""
    filters = LeadFilters(search="+51 951 234 567")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g') LIKE %s" in where
    assert "%951234567%" in params


def test_busqueda_telefono_con_guiones():
    """Ej: '951-234-567' debe normalizarse a '%951234567%'."""
    filters = LeadFilters(search="951-234-567")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "%951234567%" in params


def test_busqueda_telefono_parcial_separado():
    """Ej: '9 5 1 2' (4 dígitos separados) debe buscar '%9512%'."""
    filters = LeadFilters(search="9 5 1 2")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "%9512%" in params


def test_busqueda_dni_ocho_digitos():
    """Ej: '45678901' debe permitir matchear tanto por DNI como por teléfono."""
    filters = LeadFilters(search="45678901")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "l.dni ILIKE %s" in where
    assert "%45678901%" in params


def test_busqueda_nombre_no_activa_rama_solo_numerica():
    """Ej: 'Flor Olazabal' no contiene dígitos, debe mantener la búsqueda multi-token por nombres."""
    filters = LeadFilters(search="Flor Olazabal")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "l.nombres ILIKE %s" in where
    assert "%Flor%" in params
    assert "%Olazabal%" in params


def test_busqueda_email_con_digitos():
    """Ej: 'usuario1234@empresa.com' contiene letras y dígitos; debe buscar por email también."""
    filters = LeadFilters(search="usuario1234@empresa.com")
    where, params = apply_lead_filters(filters, _admin_user())

    assert "l.email ILIKE %s" in where
    assert "%usuario1234@empresa.com%" in params

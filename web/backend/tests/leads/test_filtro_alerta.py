"""
Tests unitarios para filtro_alerta en apply_lead_filters:
Verifica que las alertas operacionales de llamada ('urgentes' y 'sla_15m')
generen las cláusulas WHERE y condiciones SQL correctas.
"""
from unittest.mock import MagicMock
from app.constants import Role
from app.filters.lead_filters import LeadFilters, apply_lead_filters, lead_filters_query


def _admin_user():
    user = MagicMock()
    user.role = Role.ADMIN
    user.user_id = "admin-uuid"
    return user


def test_filtro_alerta_urgentes_genera_clausula_48h_y_sin_contacto():
    filters = LeadFilters(filtro_alerta="urgentes")
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "l.created_at < NOW() - INTERVAL '48 hours'" in where
    assert "crm.contactos" in where
    assert "crm.llamadas" in where
    assert "NOT EXISTS" in where


def test_filtro_alerta_sla_15m_genera_clausula_sla():
    filters = LeadFilters(filtro_alerta="sla_15m")
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "l.sla_15m_cumplido = FALSE" in where
    assert "l.sla_15m_notificado_at IS NOT NULL" in where
    assert "crm.contactos" in where
    assert "crm.llamadas" in where
    assert "NOT EXISTS" in where


def test_lead_filters_query_parses_filtro_alerta():
    f = lead_filters_query(filtro_alerta="urgentes")
    assert f.filtro_alerta == "urgentes"


def test_filtro_alerta_pendientes_genera_clausula_seguimiento():
    filters = LeadFilters(filtro_alerta="pendientes")
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "NOW() - INTERVAL '48 hours'" in where
    assert "CALIENTE" in where
    assert "NOW() - INTERVAL '24 hours'" in where
    assert "crm.estados_lead" in where
    assert "Ganado" in where


"""
Tests unitarios para verificar que un supervisor puede filtrarse a sí mismo
como asesor en el endpoint de leads.
"""
from app.auth.schemas import TokenData
from app.constants import Role
from app.filters.lead_filters import LeadFilters, apply_lead_filters

SUP_ID = "00000000-0000-0000-0000-000000000001"


def _supervisor_user(user_id: str = SUP_ID) -> TokenData:
    return TokenData(
        user_id=user_id,
        email="sup@crm.com",
        role=Role.SUPERVISOR,
        is_active=True,
    )


def test_supervisor_can_filter_leads_assigned_to_self_as_advisor():
    user = _supervisor_user()
    filters = LeadFilters(asesor_id=SUP_ID)

    sql, params = apply_lead_filters(filters, user)

    # Verificar que el clause de rol de supervisor está presente
    assert "l.supervisor_id = %s::uuid" in sql
    # Verificar que se inyecta la restricción por asesor_id = SUP_ID
    assert "l.asesor_id = %s::uuid" in sql
    # SUP_ID debe estar en params tanto para el role_clause como para la restricción de asesor_id
    assert SUP_ID in params
    assert params.count(SUP_ID) >= 7


def test_filter_by_supervisor_id_includes_team_and_queue():
    user = TokenData(user_id="admin-uuid", email="admin@crm.com", role=Role.ADMIN, is_active=True)
    filters = LeadFilters(supervisor_id=SUP_ID)

    sql, params = apply_lead_filters(filters, user)

    assert "crm.equipos" in sql
    assert "eq.supervisor_id = %s::uuid" in sql
    assert "l.supervisor_id = %s::uuid" in sql
    assert "l.asesor_id = %s::uuid" in sql
    assert params.count(SUP_ID) == 3


def test_filter_by_origen_tiktok_and_facebook():
    user = TokenData(user_id="admin-uuid", email="admin@crm.com", role=Role.ADMIN, is_active=True)

    # Test TikTok origen
    filters_tt = LeadFilters(origen="tiktok")
    sql_tt, params_tt = apply_lead_filters(filters_tt, user)
    assert "l.api_client_legacy_slug = 'tiktok'" in sql_tt
    assert "1870%" in params_tt
    assert "%tiktok%" in params_tt

    # Test Facebook origen
    filters_fb = LeadFilters(origen="facebook")
    sql_fb, params_fb = apply_lead_filters(filters_fb, user)
    assert "l.leadgen_id IS NOT NULL" in sql_fb
    assert "1202%" in params_fb
    assert "%facebook%" in params_fb

    # Test custom origen (e.g. Mercado Natural)
    filters_custom = LeadFilters(origen="mercado natural")
    sql_custom, params_custom = apply_lead_filters(filters_custom, user)
    assert "LOWER(f.nombre) = %s" in sql_custom
    assert "mercado natural" in params_custom




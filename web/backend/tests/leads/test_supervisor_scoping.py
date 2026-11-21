"""
Tests unitarios del scoping estricto de leads para supervisores y jerarquías de equipos.

Cubre:
  1. role_filter para rol SUPERVISOR (Normal): incluye leads del supervisor + asesores de su equipo.
  2. role_filter para rol SUPERVISOR (Jefe): incluye leads del supervisor jefe + subordinados + asesores de subordinados.
  3. apply_lead_filters con sin_asesor / en_cola no desactiva role_filter para supervisores.
  4. _authorize_source previene reasignar/liberar leads de otros equipos.
"""
from unittest.mock import MagicMock
import pytest

from app.auth.schemas import TokenData
from app.constants import Role
from app.filters.lead_filters import role_filter, apply_lead_filters, LeadFilters
from app.services.assignments_service import _authorize_source
from fastapi import HTTPException


SUP_SUB_ID = "00000000-0000-0000-0000-000000000001"
SUP_JEFE_ID = "00000000-0000-0000-0000-000000000002"
OTHER_SUP_ID = "00000000-0000-0000-0000-000000000009"


def _token_user(role: Role, user_id: str) -> TokenData:
    return TokenData(
        user_id=user_id,
        email="test@crm.com",
        role=role,
        is_active=True,
    )


@pytest.mark.leads
@pytest.mark.unit
def test_role_filter_supervisor_generates_strict_team_and_hierarchy_sql():
    user = _token_user(Role.SUPERVISOR, SUP_SUB_ID)
    sql, params = role_filter(user)

    assert "l.asesor_id = %s::uuid" in sql
    assert "l.supervisor_id = %s::uuid" in sql
    assert "supervisor_jefe_id = %s::uuid" in sql
    assert len(params) == 6
    assert all(p == SUP_SUB_ID for p in params)


@pytest.mark.leads
@pytest.mark.unit
def test_apply_lead_filters_sin_asesor_retains_supervisor_role_clause():
    user = _token_user(Role.SUPERVISOR, SUP_SUB_ID)
    filters = LeadFilters(sin_asesor=True)

    sql, params = apply_lead_filters(filters, user)

    # NO debe reemplazar por "(TRUE)"
    assert "(TRUE)" not in sql
    assert "l.supervisor_id = %s::uuid" in sql
    assert "l.asesor_id IS NULL" in sql


@pytest.mark.leads
@pytest.mark.unit
def test_authorize_source_raises_403_for_supervisor_on_other_team_lead(mocker):
    user = _token_user(Role.SUPERVISOR, SUP_SUB_ID)

    # Mock _supervisor_owns_asesor returns False
    mocker.patch("app.services.assignments_service._supervisor_owns_asesor", return_value=False)
    mock_db = mocker.patch("app.services.assignments_service.get_db")
    mock_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        _authorize_source(user, current_asesor_id="other-advisor", lead_supervisor_id=OTHER_SUP_ID)

    assert exc_info.value.status_code == 403
    assert "no pertenece a tu equipo" in exc_info.value.detail


@pytest.mark.leads
@pytest.mark.unit
def test_get_lead_query_escaping(mocker):
    """Verifica que get_lead ejecute su query SQL sin errores de interpolación de parámetros en psycopg2."""
    import re
    from app.routers.leads import get_lead
    user = _token_user(Role.SUPERVISOR, SUP_SUB_ID)

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        "id": 1,
        "nombres": "Test",
        "is_respaldo_supervision": False,
        "telefono": "123456789",
    }
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
    mocker.patch("app.routers.leads.get_db", return_value=mock_conn)
    mocker.patch("app.routers.leads.audit_service.record_detail")

    res = get_lead(lead_id=1, request=None, current_user=user)
    assert res["id"] == 1

    executed_sql = mock_cursor.execute.call_args[0][0]
    assert not re.search(r"ILIKE\s+'%[^%]+%'", executed_sql), "El SQL contiene comodines '%' sin escapar que rompen psycopg2"


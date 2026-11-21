"""
V084: filtros por atribucion del recontacto sobre `crm.leads`.

Cubre el caso reportado por proveedor: poder buscar "leads que volvieron
por MI campaña de Meta Promo Verano 2026" desde la pagina de Leads.

Tests unitarios sobre apply_lead_filters: chequean que el WHERE generado
incluya la subquery EXISTS sobre crm.lead_recontactos con los criterios
correctos y los params en orden.
"""
from unittest.mock import MagicMock

import pytest

from app.constants import Role
from app.filters.lead_filters import LeadFilters, apply_lead_filters


def _admin_user():
    """TokenData mock con rol admin para que role_filter no aplique restricciones."""
    user = MagicMock()
    user.role = Role.ADMIN
    user.user_id = "admin-uuid"
    return user


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_recontacto_campana_genera_exists_clause():
    """Bug ID: V084 — el filtro por campaña del recontacto debe traducirse a
    EXISTS sobre crm.lead_recontactos con r.campana ILIKE %s."""
    filters = LeadFilters(recontacto_campana="Promo Verano 2026")
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "EXISTS (SELECT 1 FROM crm.lead_recontactos r" in where
    assert "r.campana ILIKE %s" in where
    assert "%Promo Verano 2026%" in params


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_recontacto_anuncio_y_conjunto_combinados():
    """Cuando se pasan multiples criterios de recontacto, todos deben ANDearse
    DENTRO de la MISMA subquery EXISTS (no como EXISTS separados)."""
    filters = LeadFilters(
        recontacto_anuncio="Ad_X",
        recontacto_conjunto="AdSet_Y",
    )
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    # Un solo EXISTS — no dos.
    assert where.count("EXISTS (SELECT 1 FROM crm.lead_recontactos r") == 1
    assert "r.anuncio ILIKE %s" in where
    assert "r.conjunto ILIKE %s" in where
    assert "%Ad_X%" in params
    assert "%AdSet_Y%" in params


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_recontacto_fuente_id_es_entero():
    """fuente_id debe compararse con %s (entero), no ILIKE."""
    filters = LeadFilters(recontacto_fuente_id=5)
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "r.fuente_id = %s" in where
    assert 5 in params


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_recontacto_fecha_desde_hasta_inclusivo():
    """recontacto_desde inclusive, recontacto_hasta inclusive (suma 1 dia)."""
    filters = LeadFilters(
        recontacto_desde="2026-06-01",
        recontacto_hasta="2026-06-15",
    )
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "r.created_at >= %s::date" in where
    assert "r.created_at < (%s::date + INTERVAL '1 day')" in where
    assert "2026-06-01" in params
    assert "2026-06-15" in params


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_recontacto_api_client_id_cast_uuid():
    """El api_client_id se castea a uuid para evitar inyeccion."""
    filters = LeadFilters(recontacto_api_client_id="00000000-0000-0000-0000-000000000001")
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "r.api_client_id = %s::uuid" in where
    assert "00000000-0000-0000-0000-000000000001" in params


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_sin_filtros_recontacto_no_aparece_exists_sobre_lead_recontactos():
    """Si ningun filtro recontacto_* esta seteado, no se debe agregar el EXISTS
    sobre crm.lead_recontactos (perf: evitar subquery innecesaria)."""
    filters = LeadFilters()
    where, _ = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "crm.lead_recontactos r" not in where


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_con_antecedentes_es_independiente_de_filtros_recontacto():
    """con_antecedentes (booleano) y recontacto_campana coexisten — son
    queries distintas sobre la misma tabla."""
    filters = LeadFilters(
        con_antecedentes=True,
        recontacto_campana="Meta",
    )
    where, _ = apply_lead_filters(filters, _admin_user(), include_estado=False)

    # con_antecedentes: EXISTS sin alias `r` (su query no usa filtros)
    assert "EXISTS (SELECT 1 FROM crm.lead_recontactos WHERE lead_id = l.id)" in where
    # recontacto_campana: EXISTS con alias `r`
    assert "EXISTS (SELECT 1 FROM crm.lead_recontactos r" in where


# ── V086: filtro unificado "tocado por proveedor" ─────────────────────────

@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_tocado_por_api_client_id_genera_clausula_OR():
    """Bug ID: V086 — el filtro debe generar OR entre origen y recontacto.
    Si el SQL termina como AND, devolveria interseccion (solo leads que
    fueron originales DE wedo Y tambien tuvieron un recontacto de wedo).
    Debe ser UNION."""
    filters = LeadFilters(tocado_por_api_client_id="00000000-0000-0000-0000-000000000001")
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    # La clave: `OR` entre la igualdad y el EXISTS.
    assert "l.api_client_id = %s::uuid" in where
    assert "EXISTS (SELECT 1 FROM crm.lead_recontactos r2" in where
    assert " OR " in where
    # El UUID se pasa dos veces (una para cada lado del OR).
    assert params.count("00000000-0000-0000-0000-000000000001") == 2


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_tocado_por_api_client_id_coexiste_con_filtros_recontacto():
    """tocado_por_X (union) y recontacto_X (interseccion) son independientes.
    Si se combinan, se ANDean entre si — el resultado es "tocado por X Y
    ademas el recontacto tiene campaña Y"."""
    filters = LeadFilters(
        tocado_por_api_client_id="00000000-0000-0000-0000-000000000001",
        recontacto_campana="Promo Verano",
    )
    where, _ = apply_lead_filters(filters, _admin_user(), include_estado=False)

    # Aparecen las dos clausulas separadas.
    assert "r2.api_client_id = %s::uuid" in where  # union (alias r2)
    assert "r.campana ILIKE %s" in where           # interseccion (alias r)


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_sin_filtro_tocado_no_aparece_clausula_or():
    """Si tocado_por_api_client_id no se setea, el WHERE no debe incluir
    la subquery con alias r2 — evita perf hit innecesario."""
    filters = LeadFilters()
    where, _ = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "lead_recontactos r2" not in where


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_filtro_asesor_historico_id():
    """El filtro asesor_historico_id debe buscar en crm.asignaciones_log y
    l.previous_asesor_id, excluyendo leads que actualmente sigan asignados
    a ese asesor."""
    advisor_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    filters = LeadFilters(asesor_historico_id=advisor_uuid)
    where, params = apply_lead_filters(filters, _admin_user(), include_estado=False)

    assert "EXISTS (SELECT 1 FROM crm.asignaciones_log al" in where
    assert "al.asesor_anterior = %s::uuid" in where
    assert "al.asesor_nuevo = %s::uuid" in where
    assert "l.previous_asesor_id = %s::uuid" in where
    assert "l.asesor_id IS DISTINCT FROM %s::uuid" in where
    assert params.count(advisor_uuid) == 4


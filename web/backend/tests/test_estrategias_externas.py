"""Tests unitarios para el módulo de Estrategias Externas."""
import pytest
from fastapi import HTTPException

from app.auth.jwt import require_supervisor_or_admin
from app.auth.schemas import TokenData
from app.routers.estrategias_externas import (
    CONSIDERACION_LABELS,
    SOCIAL_CORE_NAMES,
    WHATSAPP_SOCIAL_NAMES,
    _annotate_lead_consideracion,
    _build_external_base_filters,
)


@pytest.mark.unit
def test_estrategias_externas_bloquea_asesor_permite_admin_y_supervisor():
    asesor = TokenData(user_id="00000000-0000-0000-0000-000000000003", email="a@test.com", role="asesor")
    sup = TokenData(user_id="00000000-0000-0000-0000-000000000002", email="s@test.com", role="supervisor")
    adm = TokenData(user_id="00000000-0000-0000-0000-000000000001", email="admin@test.com", role="admin")

    with pytest.raises(HTTPException) as exc:
        require_supervisor_or_admin(asesor)
    assert exc.value.status_code == 403

    assert require_supervisor_or_admin(sup).role == "supervisor"
    assert require_supervisor_or_admin(adm).role == "admin"


@pytest.mark.unit
def test_build_external_filters_excluye_redes_sociales():
    adm = TokenData(user_id="00000000-0000-0000-0000-000000000001", email="admin@test.com", role="admin")
    sql_def, params_def = _build_external_base_filters(current_user=adm, incluir_whatsapp=False)
    flat_excluded = next(p for p in params_def if isinstance(p, list))
    for red in ("fb", "ig", "tiktok", "tt mensaje", "wa mensaje", "whatsapp"):
        assert red in flat_excluded
    assert "COALESCE(l.fuente_pre_reciclaje_id, l.fuente_id) IS NOT NULL" in sql_def

    _, params_wa = _build_external_base_filters(current_user=adm, incluir_whatsapp=True)
    flat_wa = next(p for p in params_wa if isinstance(p, list))
    for social in SOCIAL_CORE_NAMES:
        assert social in flat_wa
    for wa in WHATSAPP_SOCIAL_NAMES:
        assert wa not in flat_wa


@pytest.mark.unit
def test_annotate_lead_consideracion_etiquetas():
    row_venta = _annotate_lead_consideracion({"consideracion_codigo": "considerado_venta", "valor_venta": None})
    assert row_venta["es_considerado"] is True
    assert "Venta concretada" in row_venta["consideracion_label"]

    row_inv = _annotate_lead_consideracion({"consideracion_codigo": "excluido_invalido"})
    assert row_inv["es_considerado"] is False
    assert "No considerado" in row_inv["consideracion_label"]
    assert set(CONSIDERACION_LABELS.keys()) >= {
        "considerado_venta",
        "considerado_cita",
        "considerado_gestion",
        "considerado_nuevo",
        "excluido_invalido",
        "excluido_perdido",
        "excluido_bolsa",
        "excluido_inactivo",
    }

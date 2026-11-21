"""
Tests de wa_router_service.py — funciones puras del router de
conversaciones WhatsApp.

Cubre:
  - _is_ctwa_sourced: deteccion de Click-to-WhatsApp Ad source.
  - _build_observations: render del bloque de info IA para el asesor.
  - _json_dumps_safe: serializacion tolerante.

NO cubre (requiere DB + mocks complejos):
  - route_classified_conversation (orquestador principal)
  - _create_lead_and_rotate
  - create_lead_from_take_action
  - _archive, _update_status, _send_to_manual_review (requieren DB)
"""
import json
from datetime import datetime, timezone

import pytest


# ── _is_ctwa_sourced ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_is_ctwa_sourced_with_campaign_name_returns_true():
    """Si hay campaign_name (JOIN con wa_campaigns), vino de un ad."""
    from app.services.wa_router_service import _is_ctwa_sourced
    ctx = {"campaign_name": "Promo Mayo 2026"}
    assert _is_ctwa_sourced(ctx) is True


@pytest.mark.unit
def test_is_ctwa_sourced_with_referral_source_type_returns_true():
    """Si el primer mensaje incluye referral.source_type, vino de un ad."""
    from app.services.wa_router_service import _is_ctwa_sourced
    ctx = {"referral": {"source_type": "ad"}}
    assert _is_ctwa_sourced(ctx) is True


@pytest.mark.unit
def test_is_ctwa_sourced_with_referral_source_id_returns_true():
    """referral.source_id solo (sin source_type) tambien cuenta."""
    from app.services.wa_router_service import _is_ctwa_sourced
    ctx = {"referral": {"source_id": "ad_123"}}
    assert _is_ctwa_sourced(ctx) is True


@pytest.mark.unit
def test_is_ctwa_sourced_with_empty_dict_returns_false():
    """Sin campaign ni referral -> NO es CTWA, es WhatsApp directo."""
    from app.services.wa_router_service import _is_ctwa_sourced
    assert _is_ctwa_sourced({}) is False


@pytest.mark.unit
def test_is_ctwa_sourced_with_none_returns_false():
    """Defensa: input None no debe romper, devuelve False."""
    from app.services.wa_router_service import _is_ctwa_sourced
    assert _is_ctwa_sourced(None) is False


@pytest.mark.unit
def test_is_ctwa_sourced_with_non_dict_returns_false():
    """Tipo invalido -> False (no levanta)."""
    from app.services.wa_router_service import _is_ctwa_sourced
    assert _is_ctwa_sourced("string") is False
    assert _is_ctwa_sourced(42) is False
    assert _is_ctwa_sourced([1, 2, 3]) is False


@pytest.mark.unit
def test_is_ctwa_sourced_empty_referral_dict_returns_false():
    """referral={} (sin source_type ni source_id) -> False."""
    from app.services.wa_router_service import _is_ctwa_sourced
    assert _is_ctwa_sourced({"referral": {}}) is False


# ── _build_observations ──────────────────────────────────────────────────

@pytest.mark.unit
def test_build_observations_with_empty_result_returns_fallback():
    """Sin info de IA, mensaje por defecto."""
    from app.services.wa_router_service import _build_observations
    text = _build_observations({}, {})
    assert "automaticamente" in text.lower() or "automáticamente" in text.lower()


@pytest.mark.unit
def test_build_observations_includes_resumen():
    """resumen aparece con prefijo [IA]."""
    from app.services.wa_router_service import _build_observations
    result = {"resumen": "Cliente pregunta por departamento"}
    text = _build_observations(result, {})
    assert "[IA]" in text
    assert "Cliente pregunta por departamento" in text


@pytest.mark.unit
def test_build_observations_includes_interes_when_set():
    from app.services.wa_router_service import _build_observations
    result = {"interes": "compra"}
    text = _build_observations(result, {})
    assert "Interes: compra" in text


@pytest.mark.unit
def test_build_observations_skips_urgencia_when_media():
    """urgencia='media' es el default, no se incluye para reducir ruido."""
    from app.services.wa_router_service import _build_observations
    result = {"urgencia": "media"}
    text = _build_observations(result, {})
    assert "Urgencia" not in text


@pytest.mark.unit
def test_build_observations_uppercase_urgencia_when_alta():
    """urgencia='alta' o 'baja' aparece en MAYUSCULAS para destacar."""
    from app.services.wa_router_service import _build_observations
    text = _build_observations({"urgencia": "alta"}, {})
    assert "ALTA" in text
    text = _build_observations({"urgencia": "baja"}, {})
    assert "BAJA" in text


@pytest.mark.unit
def test_build_observations_includes_presupuesto_zona():
    from app.services.wa_router_service import _build_observations
    result = {
        "presupuesto_mencionado": "150000 USD",
        "zona_mencionada": "Miraflores",
    }
    text = _build_observations(result, {})
    assert "150000 USD" in text
    assert "Miraflores" in text


@pytest.mark.unit
def test_build_observations_includes_campaign_from_ctx():
    """campaign_name del ctx aparece para que el asesor sepa por que llego."""
    from app.services.wa_router_service import _build_observations
    ctx = {"campaign_name": "Promo Mayo 2026"}
    text = _build_observations({}, ctx)
    assert "Promo Mayo 2026" in text


@pytest.mark.unit
def test_build_observations_includes_confianza_as_percentage():
    """confianza=0.85 -> '85%'."""
    from app.services.wa_router_service import _build_observations
    result = {"confianza": 0.85}
    text = _build_observations(result, {})
    assert "85%" in text


@pytest.mark.unit
def test_build_observations_combines_all_fields_in_order():
    """Output combina todos los campos disponibles, separados por newlines."""
    from app.services.wa_router_service import _build_observations
    result = {
        "resumen": "Quiere comprar",
        "interes": "compra",
        "urgencia": "alta",
        "presupuesto_mencionado": "100k",
        "zona_mencionada": "Lima",
        "confianza": 0.9,
    }
    ctx = {"campaign_name": "Promo"}
    text = _build_observations(result, ctx)
    lines = text.split("\n")
    assert len(lines) == 7  # resumen + interes + urgencia + presup + zona + campaña + confianza
    assert lines[0].startswith("[IA]")
    assert "Confianza" in lines[-1]


# ── _json_dumps_safe ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_json_dumps_safe_with_plain_dict_returns_valid_json():
    from app.services.wa_router_service import _json_dumps_safe
    result = _json_dumps_safe({"foo": "bar", "n": 42})
    assert json.loads(result) == {"foo": "bar", "n": 42}


@pytest.mark.unit
def test_json_dumps_safe_with_datetime_uses_str_repr():
    """datetime no es JSON-serializable, default=str la convierte."""
    from app.services.wa_router_service import _json_dumps_safe
    dt = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    result = _json_dumps_safe({"created_at": dt})
    parsed = json.loads(result)
    assert "2026-05-01" in parsed["created_at"]


@pytest.mark.unit
def test_json_dumps_safe_with_unicode_preserved():
    """ensure_ascii=False mantiene caracteres no-ASCII."""
    from app.services.wa_router_service import _json_dumps_safe
    result = _json_dumps_safe({"nombre": "Cinthía"})
    # NO debe haber escapes í
    assert "Cinth" in result
    assert "\\u" not in result

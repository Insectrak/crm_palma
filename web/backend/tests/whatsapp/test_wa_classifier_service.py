"""
Tests de wa_classifier_service.py — funciones puras del clasificador IA.

Cubre:
  - _normalize_result: sanitiza output del LLM contra valores validos.
  - _format_history: convierte messages a string para prompt.
  - _build_prompt: substitucion de variables en template.
  - is_configured: detecta si hay config IA activa.

NO cubre (requiere mock pesado de Ollama/OpenAI + DB):
  - clasificar() (la funcion principal)
  - _call_ollama()
  - _fetch_context() (requiere DB)
"""
from unittest.mock import patch

import pytest


# ── _normalize_result ────────────────────────────────────────────────────

@pytest.mark.unit
def test_normalize_result_with_valid_complete_dict():
    from app.services.wa_classifier_service import _normalize_result
    raw = {
        "categoria": "cliente_potencial",
        "confianza": 0.85,
        "interes": "compra",
        "urgencia": "alta",
        "resumen": "Cliente pregunta por departamento de 3 dormitorios",
        "nombre_sugerido": "Juan",
        "presupuesto_mencionado": "200000 USD",
        "zona_mencionada": "Miraflores",
    }
    result = _normalize_result(raw)

    assert result["categoria"] == "cliente_potencial"
    assert result["confianza"] == 0.85
    assert result["interes"] == "compra"
    assert result["urgencia"] == "alta"
    assert result["resumen"].startswith("Cliente pregunta")
    assert result["nombre_sugerido"] == "Juan"
    assert result["presupuesto_mencionado"] == "200000 USD"


@pytest.mark.unit
def test_normalize_result_invalid_categoria_falls_back_to_consulta_general():
    """Si el LLM inventa una categoria nueva, fallback al safe default."""
    from app.services.wa_classifier_service import _normalize_result
    result = _normalize_result({"categoria": "categoria_inventada"})
    assert result["categoria"] == "consulta_general"


@pytest.mark.unit
def test_normalize_result_missing_categoria_defaults_to_consulta_general():
    from app.services.wa_classifier_service import _normalize_result
    result = _normalize_result({})
    assert result["categoria"] == "consulta_general"


@pytest.mark.unit
def test_normalize_result_clamps_confianza_to_0_1():
    """Confianza fuera de [0, 1] se clampa. NaN/strings -> 0."""
    from app.services.wa_classifier_service import _normalize_result
    assert _normalize_result({"confianza": 1.5})["confianza"] == 1.0
    assert _normalize_result({"confianza": -0.5})["confianza"] == 0.0
    assert _normalize_result({"confianza": "abc"})["confianza"] == 0.0


@pytest.mark.unit
def test_normalize_result_invalid_interes_returns_none():
    """Interes invalido -> None (no es valor critico)."""
    from app.services.wa_classifier_service import _normalize_result
    assert _normalize_result({"interes": "vender"})["interes"] is None
    # Pero interes valido se mantiene
    assert _normalize_result({"interes": "alquiler"})["interes"] == "alquiler"


@pytest.mark.unit
def test_normalize_result_urgencia_defaults_to_media():
    """Urgencia invalida o vacia -> 'media' (default safe)."""
    from app.services.wa_classifier_service import _normalize_result
    assert _normalize_result({})["urgencia"] == "media"
    assert _normalize_result({"urgencia": "critica"})["urgencia"] == "media"
    # Valida se mantiene
    assert _normalize_result({"urgencia": "alta"})["urgencia"] == "alta"


@pytest.mark.unit
def test_normalize_result_truncates_resumen_at_500_chars():
    """Si el LLM se desboca con el resumen, truncamos a 500."""
    from app.services.wa_classifier_service import _normalize_result
    long_text = "A" * 1000
    result = _normalize_result({"resumen": long_text})
    assert len(result["resumen"]) == 500


@pytest.mark.unit
def test_normalize_result_truncates_nombre_at_120_chars():
    from app.services.wa_classifier_service import _normalize_result
    long_name = "X" * 200
    result = _normalize_result({"nombre_sugerido": long_name})
    assert len(result["nombre_sugerido"]) == 120


@pytest.mark.unit
def test_normalize_result_preserves_raw_for_debugging():
    """El dict original siempre se conserva en 'raw' para debugging."""
    from app.services.wa_classifier_service import _normalize_result
    raw = {"categoria": "cliente_potencial", "foo": "bar"}
    result = _normalize_result(raw)
    assert result["raw"] == raw


@pytest.mark.unit
def test_normalize_result_case_insensitive_categoria():
    """LLM puede devolver mayusculas. Normalizamos a lowercase."""
    from app.services.wa_classifier_service import _normalize_result
    assert _normalize_result({"categoria": "CLIENTE_POTENCIAL"})["categoria"] == "cliente_potencial"
    assert _normalize_result({"categoria": "  SPAM  "})["categoria"] == "spam"


# ── _format_history ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_format_history_with_empty_messages_returns_placeholder():
    from app.services.wa_classifier_service import _format_history
    result = _format_history([])
    assert "sin historial" in result.lower()


@pytest.mark.unit
def test_format_history_with_one_inbound_message():
    from app.services.wa_classifier_service import _format_history
    msgs = [{"direction": "inbound", "content": "Hola, quiero info"}]
    result = _format_history(msgs)
    assert "Cliente:" in result
    assert "Hola, quiero info" in result


@pytest.mark.unit
def test_format_history_marks_outbound_as_asesor():
    from app.services.wa_classifier_service import _format_history
    msgs = [{"direction": "outbound", "content": "Buenas tardes"}]
    result = _format_history(msgs)
    assert "Asesor:" in result


@pytest.mark.unit
def test_format_history_limits_to_last_n_messages():
    """limit=2 trae solo los 2 ultimos."""
    from app.services.wa_classifier_service import _format_history
    msgs = [
        {"direction": "inbound", "content": "Msg 1"},
        {"direction": "inbound", "content": "Msg 2"},
        {"direction": "inbound", "content": "Msg 3"},
    ]
    result = _format_history(msgs, limit=2)
    assert "Msg 1" not in result
    assert "Msg 2" in result
    assert "Msg 3" in result


@pytest.mark.unit
def test_format_history_truncates_long_content_at_200_chars():
    """Mensajes muy largos se truncan a 200 chars c/u para no explotar tokens."""
    from app.services.wa_classifier_service import _format_history
    long_content = "X" * 500
    msgs = [{"direction": "inbound", "content": long_content}]
    result = _format_history(msgs)
    # El "X" * 200 esta presente, pero no "X" * 500
    assert "X" * 200 in result
    assert "X" * 201 not in result


@pytest.mark.unit
def test_format_history_skips_empty_content():
    """Mensajes sin content (ej: solo imagen) se saltan en el render."""
    from app.services.wa_classifier_service import _format_history
    msgs = [
        {"direction": "inbound", "content": ""},
        {"direction": "inbound", "content": "Tengo interes"},
    ]
    result = _format_history(msgs)
    # Solo aparece el segundo
    assert "Tengo interes" in result
    # Y no hay placeholder de vacio
    lines = [l for l in result.split("\n") if "Cliente:" in l]
    assert len(lines) == 1

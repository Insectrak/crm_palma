"""
Tests de phishing_detector — funciones puras.

El modulo combina:
  - Capa 1: reglas heuristicas (URLs sospechosas, TLDs raros, typosquatting,
    palabras clave de phishing, brand impersonation).
  - Capa 2: LLM (Ollama) opcional para casos ambiguos.

Estos tests cubren solo la Capa 1 (funciones puras), que es donde vive
la mayor parte de la logica de deteccion.
"""
import pytest


# ── _extract_urls ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_extract_urls_empty_text_returns_empty_list():
    from app.services.phishing_detector import _extract_urls
    assert _extract_urls("") == []
    assert _extract_urls(None) == []


@pytest.mark.unit
def test_extract_urls_single_url_returns_it():
    from app.services.phishing_detector import _extract_urls
    text = "Visita https://palmadelrio.com para mas info"
    urls = _extract_urls(text)
    assert "https://palmadelrio.com" in urls


@pytest.mark.unit
def test_extract_urls_strips_trailing_punctuation():
    """URLs con puntuacion final (. , ; etc) se limpian."""
    from app.services.phishing_detector import _extract_urls
    text = "Click aqui: https://palmadelrio.com, gracias."
    urls = _extract_urls(text)
    assert any(u == "https://palmadelrio.com" for u in urls)
    # NO debe quedar con la coma o el punto
    assert not any(u.endswith(",") or u.endswith(".") for u in urls)


@pytest.mark.unit
def test_extract_urls_multiple_urls_returns_all():
    from app.services.phishing_detector import _extract_urls
    text = "Mira https://link1.com y http://link2.org/path"
    urls = _extract_urls(text)
    assert len(urls) >= 2


# ── _domain_of ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_domain_of_https_url_returns_lowercase_domain():
    from app.services.phishing_detector import _domain_of
    assert _domain_of("https://Example.com/path") == "example.com"


@pytest.mark.unit
def test_domain_of_empty_returns_none():
    """Empty string -> None (regex no matchea)."""
    from app.services.phishing_detector import _domain_of
    assert _domain_of("") is None


@pytest.mark.unit
def test_domain_of_strips_www_subdomain():
    """www. se considera prefijo de display y se stripea."""
    from app.services.phishing_detector import _domain_of
    result = _domain_of("https://www.palmadelrio.com/page")
    assert result == "palmadelrio.com"


@pytest.mark.unit
def test_domain_of_keeps_non_www_subdomain():
    """Subdomain distinto a www se conserva."""
    from app.services.phishing_detector import _domain_of
    result = _domain_of("https://api.palmadelrio.com/v1")
    assert result == "api.palmadelrio.com"


# ── _tld_of ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_tld_of_simple_domain_returns_tld():
    from app.services.phishing_detector import _tld_of
    assert _tld_of("palmadelrio.com") == "com"
    assert _tld_of("example.org") == "org"


@pytest.mark.unit
def test_tld_of_no_dot_returns_none():
    from app.services.phishing_detector import _tld_of
    assert _tld_of("localhost") is None


# ── _similar_but_not_equal (Levenshtein) ──────────────────────────────────

@pytest.mark.unit
def test_similar_but_not_equal_identical_returns_false():
    """Si los strings son iguales, no es typosquat."""
    from app.services.phishing_detector import _similar_but_not_equal
    assert _similar_but_not_equal("paypal.com", "paypal.com") is False


@pytest.mark.unit
def test_similar_but_not_equal_one_char_diff_returns_true():
    """1 char de diferencia en palabras largas = typosquat."""
    from app.services.phishing_detector import _similar_but_not_equal
    assert _similar_but_not_equal("paypal.com", "paypa1.com") is True


@pytest.mark.unit
def test_similar_but_not_equal_completely_different_returns_false():
    """Strings muy distintos NO matchean (distancia >2)."""
    from app.services.phishing_detector import _similar_but_not_equal
    assert _similar_but_not_equal("paypal.com", "google.com") is False


@pytest.mark.unit
def test_similar_but_not_equal_too_short_returns_false():
    """Palabras de <5 chars no se consideran typosquat (demasiado generico)."""
    from app.services.phishing_detector import _similar_but_not_equal
    assert _similar_but_not_equal("abc", "abd") is False


# ── _match_any ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_match_any_no_patterns_returns_empty():
    from app.services.phishing_detector import _match_any
    assert _match_any([], "cualquier texto") == []


@pytest.mark.unit
def test_match_any_pattern_in_text_returns_match():
    from app.services.phishing_detector import _match_any
    hits = _match_any([r"\bpassword\b", r"\bcredit card\b"], "tu password expiro")
    assert hits == [r"\bpassword\b"]


@pytest.mark.unit
def test_match_any_is_case_insensitive():
    """re.IGNORECASE: PASSWORD = password."""
    from app.services.phishing_detector import _match_any
    hits = _match_any([r"password"], "Tu PASSWORD se vence")
    assert hits == ["password"]


# ── _apply_rules ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_apply_rules_empty_text_returns_zero_score():
    from app.services.phishing_detector import _apply_rules
    result = _apply_rules("")
    assert result["score"] == 0
    assert result["urls"] == []
    assert result["needs_llm"] is False


@pytest.mark.unit
def test_apply_rules_benign_text_low_score():
    """Texto sin URLs sospechosas ni patterns -> score bajo."""
    from app.services.phishing_detector import _apply_rules
    result = _apply_rules("Hola, te confirmo la cita para mañana a las 10am.")
    assert result["score"] < 30  # safe-ish


# ── _normalize_llm ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_normalize_llm_with_complete_dict():
    from app.services.phishing_detector import _normalize_llm
    raw = {
        "is_phishing": True,
        "confidence": 0.85,
        "risk_level": "high",
        "reason": "Suspicious URL",
    }
    result = _normalize_llm(raw)
    assert result["is_phishing"] is True
    assert result["confidence"] == 0.85
    assert result["risk_level"] == "high"
    assert result["reason"] == "Suspicious URL"


@pytest.mark.unit
def test_normalize_llm_clamps_confidence_to_0_1():
    """confidence > 1 se clampa a 1.0, <0 a 0.0."""
    from app.services.phishing_detector import _normalize_llm
    assert _normalize_llm({"confidence": 5.0})["confidence"] == 1.0
    assert _normalize_llm({"confidence": -0.5})["confidence"] == 0.0


@pytest.mark.unit
def test_normalize_llm_invalid_risk_level_falls_back_to_low():
    from app.services.phishing_detector import _normalize_llm
    result = _normalize_llm({"risk_level": "extreme"})  # no valido
    assert result["risk_level"] == "low"


@pytest.mark.unit
def test_normalize_llm_with_invalid_confidence_uses_zero():
    """confidence no numerico -> 0.0."""
    from app.services.phishing_detector import _normalize_llm
    assert _normalize_llm({"confidence": "abc"})["confidence"] == 0.0
    assert _normalize_llm({})["confidence"] == 0.0


# ── _final_level ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_final_level_safe_when_no_rules_no_llm():
    from app.services.phishing_detector import _final_level
    assert _final_level(0, None) == "safe"


@pytest.mark.unit
def test_final_level_high_when_rules_score_above_60():
    from app.services.phishing_detector import _final_level
    assert _final_level(60, None) == "high"
    assert _final_level(100, None) == "high"


@pytest.mark.unit
def test_final_level_medium_when_rules_score_30_to_59():
    from app.services.phishing_detector import _final_level
    assert _final_level(30, None) == "medium"
    assert _final_level(59, None) == "medium"


@pytest.mark.unit
def test_final_level_low_when_rules_score_1_to_29():
    from app.services.phishing_detector import _final_level
    assert _final_level(1, None) == "low"
    assert _final_level(29, None) == "low"


@pytest.mark.unit
def test_final_level_llm_high_overrides_low_rules_to_high():
    """LLM dice high con confidence > threshold -> high aunque rules bajo."""
    from app.services.phishing_detector import _final_level
    llm = {"is_phishing": True, "risk_level": "high"}
    assert _final_level(5, llm) == "high"


@pytest.mark.unit
def test_final_level_llm_phishing_with_low_rules_returns_medium():
    """LLM dice phishing pero risk_level=medium y rules bajo -> medium."""
    from app.services.phishing_detector import _final_level
    llm = {"is_phishing": True, "risk_level": "medium"}
    assert _final_level(10, llm) == "medium"

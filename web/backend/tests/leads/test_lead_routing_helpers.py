"""
Tests de funciones helpers puras del modulo lead_routing.

Estas funciones no tocan DB ni red — son logica pura sobre datetime y dicts.
Por eso son los tests MAS RAPIDOS y MAS VALIOSOS:
  - Cero setup (no mocks)
  - Determinismo absoluto
  - Coverage 100% facil

Funciones cubiertas:
  - _esta_en_horario(now, inicio, fin) — incluye cruce de medianoche
  - _esta_en_dias_semana(now, dias)
  - _esta_en_ausencia(now, desde, hasta)
  - _regla_matchea(regla, lead, now)
  - _now_lima()
"""
from datetime import date, datetime, time as dtime, timezone, timedelta

import pytest

from app.services.lead_routing import (
    _esta_en_horario,
    _esta_en_dias_semana,
    _esta_en_ausencia,
    _regla_matchea,
    _now_lima,
)


LIMA_TZ = timezone(timedelta(hours=-5))


def _at(hour, minute=0, day=1):
    """Helper: crear datetime Lima a una hora especifica."""
    return datetime(2026, 5, day, hour, minute, tzinfo=LIMA_TZ)


# ── _esta_en_horario ──────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_horario_dentro_del_rango_simple_returns_true():
    """Rango 09:00-18:00, hora actual 12:00 -> True."""
    result = _esta_en_horario(_at(12, 0), dtime(9, 0), dtime(18, 0))
    assert result is True


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_horario_fuera_del_rango_simple_returns_false():
    """Rango 09:00-18:00, hora actual 20:00 -> False."""
    result = _esta_en_horario(_at(20, 0), dtime(9, 0), dtime(18, 0))
    assert result is False


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_horario_cruza_medianoche_madrugada_returns_true():
    """Rango 22:00-06:00 (cruza medianoche), hora 02:00 -> True."""
    result = _esta_en_horario(_at(2, 0), dtime(22, 0), dtime(6, 0))
    assert result is True


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_horario_cruza_medianoche_tarde_returns_false():
    """Rango 22:00-06:00, hora 15:00 -> False."""
    result = _esta_en_horario(_at(15, 0), dtime(22, 0), dtime(6, 0))
    assert result is False


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_horario_sin_limites_returns_true():
    """Si inicio/fin es None, asume horario 24/7."""
    assert _esta_en_horario(_at(3, 0), None, None) is True
    assert _esta_en_horario(_at(3, 0), dtime(9, 0), None) is True
    assert _esta_en_horario(_at(3, 0), None, dtime(18, 0)) is True


# ── _esta_en_dias_semana ──────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_dias_semana_lunes_en_lista_returns_true():
    """2026-05-04 fue lunes. dias=[1,3,5] (L-M-V) -> True."""
    lunes = datetime(2026, 5, 4, 12, 0, tzinfo=LIMA_TZ)
    assert _esta_en_dias_semana(lunes, [1, 3, 5]) is True


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_dias_semana_martes_no_en_lista_returns_false():
    """2026-05-05 fue martes (=2). dias=[1,3,5] -> False."""
    martes = datetime(2026, 5, 5, 12, 0, tzinfo=LIMA_TZ)
    assert _esta_en_dias_semana(martes, [1, 3, 5]) is False


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_dias_semana_lista_vacia_returns_true():
    """dias=None o [] significa 'todos los dias' -> siempre True."""
    cualquier = datetime(2026, 5, 5, 12, 0, tzinfo=LIMA_TZ)
    assert _esta_en_dias_semana(cualquier, None) is True
    assert _esta_en_dias_semana(cualquier, []) is True


# ── _esta_en_ausencia ─────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_ausencia_dia_dentro_del_rango_returns_true():
    """Ausencia 2026-05-10 a 2026-05-15. Hoy 2026-05-12 -> True."""
    hoy = datetime(2026, 5, 12, 12, 0, tzinfo=LIMA_TZ)
    assert _esta_en_ausencia(hoy, date(2026, 5, 10), date(2026, 5, 15)) is True


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_ausencia_dia_fuera_returns_false():
    """Ausencia 10-15. Hoy 20 -> False."""
    hoy = datetime(2026, 5, 20, 12, 0, tzinfo=LIMA_TZ)
    assert _esta_en_ausencia(hoy, date(2026, 5, 10), date(2026, 5, 15)) is False


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_ausencia_sin_fechas_returns_false():
    """Sin ausencia configurada -> nunca en ausencia."""
    hoy = datetime(2026, 5, 20, 12, 0, tzinfo=LIMA_TZ)
    assert _esta_en_ausencia(hoy, None, None) is False
    assert _esta_en_ausencia(hoy, date(2026, 5, 1), None) is False


@pytest.mark.leads
@pytest.mark.unit
def test_esta_en_ausencia_dia_exacto_borde_returns_true():
    """Bordes inclusivos: ausencia 10-15 incluye 10 y 15."""
    inicio = datetime(2026, 5, 10, 23, 0, tzinfo=LIMA_TZ)
    fin    = datetime(2026, 5, 15, 0,  0, tzinfo=LIMA_TZ)
    assert _esta_en_ausencia(inicio, date(2026, 5, 10), date(2026, 5, 15)) is True
    assert _esta_en_ausencia(fin,    date(2026, 5, 10), date(2026, 5, 15)) is True


# ── _regla_matchea ────────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_fuente_correcta_returns_true():
    """Regla para fuente_id=1, lead con fuente_id=1 -> matchea."""
    regla = {"fuente_id": 1}
    lead = {"fuente_id": 1, "api_client_id": None, "campana": "x", "observaciones": ""}
    assert _regla_matchea(regla, lead, _at(12)) is True


@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_fuente_distinta_returns_false():
    """Regla para fuente_id=1, lead con fuente_id=2 -> NO matchea."""
    regla = {"fuente_id": 1}
    lead = {"fuente_id": 2, "api_client_id": None, "campana": "x", "observaciones": ""}
    assert _regla_matchea(regla, lead, _at(12)) is False


@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_campana_pattern_substring_returns_true():
    """Sin wildcard, pattern 'Promo' matchea por substring en 'Promo Mayo 2026'."""
    regla = {"campana_pattern": "Promo"}
    lead = {"fuente_id": None, "api_client_id": None,
            "campana": "Promo Mayo 2026", "observaciones": ""}
    assert _regla_matchea(regla, lead, _at(12)) is True


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_regla_matchea_campana_pattern_with_wildcard_suffix_returns_true():
    """Bug ID: lead_routing.py:443 (commit d6f6d92) — el wildcard SQL-LIKE
    no funcionaba por bug en re.escape + replace. Arreglado con split/join.
    Pattern 'Promo%' debe matchear 'Promo Mayo 2026'."""
    regla = {"campana_pattern": "Promo%"}
    lead = {"fuente_id": None, "api_client_id": None,
            "campana": "Promo Mayo 2026", "observaciones": ""}
    assert _regla_matchea(regla, lead, _at(12)) is True


@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_campana_pattern_with_wildcard_prefix_returns_true():
    """Pattern '%2026' matchea 'Promo Mayo 2026'."""
    regla = {"campana_pattern": "%2026"}
    lead = {"fuente_id": None, "api_client_id": None,
            "campana": "Promo Mayo 2026", "observaciones": ""}
    assert _regla_matchea(regla, lead, _at(12)) is True


@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_campana_pattern_with_wildcard_middle_returns_true():
    """Pattern '%Mayo%' matchea cualquier campana que contenga 'mayo'."""
    regla = {"campana_pattern": "%Mayo%"}
    lead = {"fuente_id": None, "api_client_id": None,
            "campana": "Promo Mayo 2026", "observaciones": ""}
    assert _regla_matchea(regla, lead, _at(12)) is True


@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_campana_pattern_with_wildcard_no_match_returns_false():
    """Pattern 'TikTok%' NO matchea 'Promo Mayo 2026'."""
    regla = {"campana_pattern": "TikTok%"}
    lead = {"fuente_id": None, "api_client_id": None,
            "campana": "Promo Mayo 2026", "observaciones": ""}
    assert _regla_matchea(regla, lead, _at(12)) is False


@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_palabra_clave_en_observaciones_returns_true():
    """Palabra clave 'urgente' en observaciones del lead -> matchea."""
    regla = {"palabras_clave": ["urgente", "vip"]}
    lead = {"fuente_id": None, "api_client_id": None, "campana": "",
            "observaciones": "Cliente URGENTE, llamar ya"}
    assert _regla_matchea(regla, lead, _at(12)) is True


@pytest.mark.leads
@pytest.mark.unit
def test_regla_matchea_sin_filtros_returns_true():
    """Regla vacia (sin condiciones) matchea cualquier lead."""
    regla = {}
    lead = {"fuente_id": 99, "api_client_id": "anything",
            "campana": "x", "observaciones": "y"}
    assert _regla_matchea(regla, lead, _at(12)) is True


# ── _now_lima ─────────────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_now_lima_returns_aware_datetime_with_lima_offset():
    """_now_lima() siempre devuelve datetime tz-aware con offset -05:00."""
    now = _now_lima()
    assert now.tzinfo is not None
    # Lima sin DST -> siempre UTC-5
    assert now.utcoffset() == timedelta(hours=-5)

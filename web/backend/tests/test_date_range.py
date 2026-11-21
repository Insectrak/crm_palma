"""
V096: tests del helper date_range usado por el dashboard time-windowed.

Cubre:
- Parse de fechas validas / invalidas
- Default = ultimos 7 dias cuando no se pasan params
- Periodo anterior simetrico
- Bounds inclusivos (start 00:00 Lima, end 23:59:59 Lima)
- end < start lanza 422
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.utils.date_range import DateRange, parse_date_range

# Lima TZ — la funcion usa America/Lima para resolver "hoy". El test debe
# usar la MISMA zona para no romper en CI cuando UTC ya cruzo medianoche
# pero Lima sigue en el dia anterior (UTC-5 sin DST).
_LIMA_TZ = timezone(timedelta(hours=-5))


@pytest.mark.unit
def test_default_es_ultimos_7_dias():
    dr = parse_date_range(start_date=None, end_date=None)
    expected_duration = 7
    assert dr.duration_days == expected_duration
    assert (dr.label_end - dr.label_start).days == expected_duration - 1


@pytest.mark.unit
def test_parse_fechas_validas():
    dr = parse_date_range(start_date="2026-06-01", end_date="2026-06-07")
    assert dr.label_start == date(2026, 6, 1)
    assert dr.label_end   == date(2026, 6, 7)
    assert dr.duration_days == 7


@pytest.mark.unit
def test_periodo_anterior_simetrico():
    """Si actual = [13 jun, 19 jun] (7 dias), prev = [6 jun, 12 jun]."""
    dr = parse_date_range(start_date="2026-06-13", end_date="2026-06-19")
    assert dr.label_prev_start == date(2026, 6,  6)
    assert dr.label_prev_end   == date(2026, 6, 12)
    assert (dr.label_prev_end - dr.label_prev_start).days == dr.duration_days - 1


@pytest.mark.unit
def test_periodo_de_1_dia_tiene_prev_de_1_dia():
    """Edge case: 'hoy' = 1 dia, prev = ayer (1 dia)."""
    dr = parse_date_range(start_date="2026-06-19", end_date="2026-06-19")
    assert dr.duration_days == 1
    assert dr.label_prev_start == date(2026, 6, 18)
    assert dr.label_prev_end   == date(2026, 6, 18)


@pytest.mark.unit
def test_periodo_largo():
    """Trimestre = ~90 dias, prev = otros 90 dias atras."""
    dr = parse_date_range(start_date="2026-04-01", end_date="2026-06-30")
    assert dr.duration_days == 91
    # prev = 31 dic 2025 .. 31 mar 2026
    assert dr.label_prev_end == date(2026, 3, 31)
    assert (dr.label_prev_end - dr.label_prev_start).days == 90


@pytest.mark.unit
def test_end_anterior_a_start_lanza_422():
    with pytest.raises(HTTPException) as exc_info:
        parse_date_range(start_date="2026-06-19", end_date="2026-06-13")
    assert exc_info.value.status_code == 422


@pytest.mark.unit
def test_start_date_invalida_lanza_422():
    with pytest.raises(HTTPException) as exc_info:
        parse_date_range(start_date="no-es-fecha", end_date=None)
    assert exc_info.value.status_code == 422


@pytest.mark.unit
def test_end_date_invalida_lanza_422():
    with pytest.raises(HTTPException) as exc_info:
        parse_date_range(start_date=None, end_date="32-13-2026")
    assert exc_info.value.status_code == 422


@pytest.mark.unit
def test_bounds_utc_son_lima_aware():
    """start = 00:00 Lima = 05:00 UTC. end = 23:59:59 Lima = 04:59:59 UTC del dia siguiente."""
    dr = parse_date_range(start_date="2026-06-15", end_date="2026-06-15")
    # Lima es UTC-5, sin DST
    assert dr.start.hour == 5  # 00:00 Lima -> 05:00 UTC
    assert dr.end.hour == 4    # 23:59:59 Lima -> 04:59:59 UTC del 16 jun
    assert dr.end.day == 16    # cruza medianoche UTC


@pytest.mark.unit
def test_as_dict_serializable():
    dr = parse_date_range(start_date="2026-06-13", end_date="2026-06-19")
    d = dr.as_dict()
    assert d == {
        "start":         "2026-06-13",
        "end":           "2026-06-19",
        "duration_days": 7,
        "prev_start":    "2026-06-06",
        "prev_end":      "2026-06-12",
    }


@pytest.mark.unit
def test_solo_start_date_usa_today_como_end():
    """Si solo se pasa start, end default = hoy. Verificamos que la duracion sea sensata.

    Bug ID: pre-fix CI restore — usaba date.today() (TZ del servidor) cuando
    la funcion usa America/Lima. En CI Linux corriendo entre 00:00-05:00 UTC
    (= 19:00-23:59 Lima del dia anterior), UTC daba dia siguiente y Lima
    daba dia anterior: assert fallaba con (jun 23 != jun 24).
    """
    today = datetime.now(_LIMA_TZ).date()
    week_ago_iso = (today - timedelta(days=6)).isoformat()
    dr = parse_date_range(start_date=week_ago_iso, end_date=None)
    assert dr.label_start == today - timedelta(days=6)
    assert dr.label_end == today
    assert dr.duration_days == 7


@pytest.mark.unit
def test_solo_end_date_usa_default_start():
    """Si solo se pasa end, start default = 6 dias atras."""
    dr = parse_date_range(start_date=None, end_date="2026-06-19")
    # default start = hace 6 dias desde HOY, no desde end_date.
    # En este test solo verificamos que no falle y que end este OK.
    assert dr.label_end == date(2026, 6, 19)


@pytest.mark.unit
def test_daterange_constructor_directo():
    """DateRange tambien se puede construir directo (uso en tests + scripts)."""
    dr = DateRange(date(2026, 6, 1), date(2026, 6, 30))
    assert dr.duration_days == 30
    assert dr.label_prev_start == date(2026, 5, 2)
    assert dr.label_prev_end   == date(2026, 5, 31)

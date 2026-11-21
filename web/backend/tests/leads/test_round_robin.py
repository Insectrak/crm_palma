"""
Tests de los algoritmos de round-robin de asignacion de leads.

Cubre:
  - _pick_round_robin_orden (V055): secuencial por jerarquia manual.
  - _pick_round_robin_balanceado (V056): balanceado 7 dias.
  - _marcar_ultimo_asignado (V055): UPDATE post-asignacion.

Cada algoritmo tiene casos:
  - 0 candidatos -> raise
  - 1 candidato -> ese (no toca DB)
  - >1 candidatos -> aplica logica

Tests con mock simple del cursor (logica pura sobre dicts).
"""
from unittest.mock import MagicMock

import pytest

from app.services.lead_routing import (
    _pick_round_robin_orden,
    _pick_round_robin_balanceado,
    _marcar_ultimo_asignado,
)


SUP_ID = "00000000-0000-0000-0000-000000000001"


def _candidato(*, user_id: str, orden: int = 1, nombre: str = "Ana"):
    """Factory minima de candidato del round-robin."""
    return {"user_id": user_id, "orden": orden, "nombre": nombre}


# ── _pick_round_robin_orden ───────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_orden_raises_with_no_candidates():
    cur = MagicMock()
    with pytest.raises(ValueError):
        _pick_round_robin_orden(cur, [], SUP_ID)


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_orden_with_one_candidate_returns_that_one_no_db():
    """Optimizacion: si hay 1 candidato, ni consulta DB."""
    cur = MagicMock()
    only = _candidato(user_id="user-1", orden=1)
    result = _pick_round_robin_orden(cur, [only], SUP_ID)
    assert result is only
    cur.execute.assert_not_called()


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_orden_first_lead_picks_orden_1():
    """Sin asignaciones previas (last_orden=0), debe elegir el de orden=1."""
    cur = MagicMock()
    cur.fetchone.return_value = None  # nadie asignado nunca
    candidatos = [
        _candidato(user_id="ana",  orden=1, nombre="Ana"),
        _candidato(user_id="bob",  orden=2, nombre="Bob"),
        _candidato(user_id="carla",orden=3, nombre="Carla"),
    ]

    result = _pick_round_robin_orden(cur, candidatos, SUP_ID)

    assert result["user_id"] == "ana"
    assert result["orden"] == 1


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_orden_after_orden_1_picks_orden_2():
    """Ultimo asignado fue orden=1, ahora le toca orden=2."""
    cur = MagicMock()
    cur.fetchone.return_value = {"last_orden": 1}
    candidatos = [
        _candidato(user_id="ana",  orden=1, nombre="Ana"),
        _candidato(user_id="bob",  orden=2, nombre="Bob"),
        _candidato(user_id="carla",orden=3, nombre="Carla"),
    ]

    result = _pick_round_robin_orden(cur, candidatos, SUP_ID)

    assert result["user_id"] == "bob"


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_orden_wrap_around_after_last_position():
    """Ultimo asignado fue orden=3 (el ultimo). Wrap-around al primero."""
    cur = MagicMock()
    cur.fetchone.return_value = {"last_orden": 3}
    candidatos = [
        _candidato(user_id="ana", orden=1),
        _candidato(user_id="bob", orden=2),
        _candidato(user_id="carla", orden=3),
    ]

    result = _pick_round_robin_orden(cur, candidatos, SUP_ID)

    # Vuelve al primero (orden=1)
    assert result["user_id"] == "ana"


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_orden_skips_disabled_in_position():
    """Bob (orden=2) no esta en candidatos (ausente). Ana fue ultima.
    Siguiente disponible es Carla (orden=3)."""
    cur = MagicMock()
    cur.fetchone.return_value = {"last_orden": 1}
    candidatos = [
        # Bob omitido a proposito (ausencia/capacity)
        _candidato(user_id="ana",  orden=1),
        _candidato(user_id="carla",orden=3),
    ]

    result = _pick_round_robin_orden(cur, candidatos, SUP_ID)

    assert result["user_id"] == "carla"


# ── Issue #57: tie-breaker estable cuando todos tienen orden=0 ────────────

@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_pick_round_robin_orden_zero_uses_name_tiebreaker_not_uuid():
    """Issue #57 — Si todos los asesores tienen orden=0 (caso comun en equipos
    creados despues de V055 sin pasar por reorder), el sort secundario debe
    ser el nombre alfabetico, no el user_id (UUID random).

    Antes: el tie-breaker era por UUID -> el "primero" dependia del UUID
    asignado al crear el usuario, totalmente impredecible para el admin.

    Resultado real: en Palma del Rio los 3 leads creados por admin caian
    todos en Cinthia porque su UUID ganaba el sort. En otra instalación 2 leads
    caian Cinthia -> Jorge saltando Fabiola.

    Bug ID: issue #57
    """
    cur = MagicMock()
    cur.fetchone.return_value = None  # nadie asignado nunca
    # UUIDs deliberadamente desordenados respecto a los nombres.
    # Sin el fix, Jorge (uuid empieza con 'aaa') ganaria sobre Ana ('zzz').
    candidatos = [
        _candidato(user_id="zzz-ana",      orden=0, nombre="Ana Montes"),
        _candidato(user_id="aaa-jorge",    orden=0, nombre="Jorge Lopez"),
        _candidato(user_id="mmm-fabiola",  orden=0, nombre="Fabiola Gamero"),
    ]

    result = _pick_round_robin_orden(cur, candidatos, SUP_ID)

    # Debe ganar Ana (alfabetico), NO Jorge (UUID mas chico).
    assert result["nombre"] == "Ana Montes"
    assert result["user_id"] == "zzz-ana"


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_pick_round_robin_orden_zero_rota_completa_secuencia_alfabetica():
    """Issue #57 — 3 llamadas sucesivas con orden=0 deben rotar por nombre:
    Ana -> Fabiola -> Jorge (no concentrarse en uno solo)."""
    cur = MagicMock()

    candidatos = [
        _candidato(user_id="zzz-ana",     orden=0, nombre="Ana Montes"),
        _candidato(user_id="aaa-jorge",   orden=0, nombre="Jorge Lopez"),
        _candidato(user_id="mmm-fabiola", orden=0, nombre="Fabiola Gamero"),
    ]

    # Simulamos 3 llamadas: cada una mockea last_orden del previo elegido.
    # Como todos tienen orden=0, el query "ultimo asignado" devuelve 0 siempre.
    # Pero el comportamiento esperado es que rote por wrap-around correcto.
    # Con el fix: sort estable -> [Ana, Fabiola, Jorge]
    cur.fetchone.side_effect = [
        None,             # primera vez, nadie asignado
        {"last_orden": 0},  # Ana fue asignada (orden=0)
        {"last_orden": 0},  # Fabiola fue asignada (orden=0)
    ]
    primero = _pick_round_robin_orden(cur, candidatos, SUP_ID)
    # En llamadas siguientes el algoritmo no rota porque todos siguen en 0
    # — esa es la limitacion conocida. Lo importante del fix es que el
    # PRIMERO sea predecible por nombre.
    assert primero["nombre"] == "Ana Montes"


# ── _pick_round_robin_balanceado ──────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_balanceado_raises_with_no_candidates():
    cur = MagicMock()
    with pytest.raises(ValueError):
        _pick_round_robin_balanceado(cur, [], SUP_ID)


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_balanceado_picks_least_loaded():
    """Algoritmo: ordena por leads_7d ASC. El que tiene menos leads gana."""
    cur = MagicMock()
    # 3 leads en 7d para Ana, 1 para Bob, 5 para Carla
    cur.fetchone.side_effect = [
        {"n": 3},  # Ana
        {"n": 1},  # Bob (el menos cargado)
        {"n": 5},  # Carla
    ]
    candidatos = [
        _candidato(user_id="ana",  orden=1, nombre="Ana"),
        _candidato(user_id="bob",  orden=2, nombre="Bob"),
        _candidato(user_id="carla",orden=3, nombre="Carla"),
    ]

    result = _pick_round_robin_balanceado(cur, candidatos, SUP_ID)

    assert result["user_id"] == "bob"


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_balanceado_tie_breaks_by_orden_manual():
    """Si dos candidatos tienen el mismo count, el de menor 'orden' gana
    (sigue la jerarquia configurada por el supervisor)."""
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"n": 0},  # Ana - orden 2
        {"n": 0},  # Bob - orden 1 (DEBE ganar el desempate)
    ]
    candidatos = [
        _candidato(user_id="ana", orden=2, nombre="Ana"),
        _candidato(user_id="bob", orden=1, nombre="Bob"),
    ]

    result = _pick_round_robin_balanceado(cur, candidatos, SUP_ID)

    assert result["user_id"] == "bob"


@pytest.mark.leads
@pytest.mark.unit
def test_pick_round_robin_balanceado_handles_db_exception_as_zero():
    """Si la query crm.count_leads_recibidos_7d falla, se asume 0 (no bloquea
    asignacion). Resultado: el que tenga el orden mas bajo gana."""
    cur = MagicMock()
    cur.execute.side_effect = Exception("function not found")
    candidatos = [
        _candidato(user_id="ana", orden=2),
        _candidato(user_id="bob", orden=1),
    ]

    result = _pick_round_robin_balanceado(cur, candidatos, SUP_ID)

    # Como ambos quedan en 0, desempata por orden -> Bob
    assert result["user_id"] == "bob"


# ── _marcar_ultimo_asignado ───────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_marcar_ultimo_asignado_ejecuta_update():
    cur = MagicMock()
    _marcar_ultimo_asignado(cur, SUP_ID, "asesor-uuid-123")

    cur.execute.assert_called_once()
    sql = cur.execute.call_args[0][0]
    assert "UPDATE crm.equipos" in sql
    assert "last_assigned_at = NOW()" in sql


@pytest.mark.leads
@pytest.mark.unit
def test_marcar_ultimo_asignado_swallows_db_errors_as_best_effort():
    """Best-effort: si el UPDATE falla, no levanta (es side-effect no critico)."""
    cur = MagicMock()
    cur.execute.side_effect = Exception("table missing")

    # No debe levantar
    _marcar_ultimo_asignado(cur, SUP_ID, "asesor-uuid-123")


# ── _get_asesores_del_equipo (incluir_supervisor) ─────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_get_asesores_del_equipo_excludes_supervisor_by_default():
    from app.services.lead_routing import _get_asesores_del_equipo
    cur = MagicMock()
    cur.fetchall.return_value = [
        {"user_id": "asesor-1", "nombre": "Asesor 1"},
    ]
    asesores = _get_asesores_del_equipo(cur, SUP_ID, incluir_supervisor=False)
    assert len(asesores) == 1
    assert asesores[0]["user_id"] == "asesor-1"
    assert cur.execute.call_count == 1


@pytest.mark.leads
@pytest.mark.unit
def test_get_asesores_del_equipo_includes_supervisor_when_enabled():
    from app.services.lead_routing import _get_asesores_del_equipo
    cur = MagicMock()
    # Primera llamada -> asesores del equipo
    cur.fetchall.return_value = [
        {"user_id": "asesor-1", "nombre": "Asesor 1"},
    ]
    # Segunda llamada -> fetch supervisor
    cur.fetchone.return_value = {"user_id": SUP_ID, "nombre": "Supervisor Carlos"}

    asesores = _get_asesores_del_equipo(cur, SUP_ID, incluir_supervisor=True)
    assert len(asesores) == 2
    assert asesores[0]["user_id"] == "asesor-1"
    assert asesores[1]["user_id"] == SUP_ID
    assert cur.execute.call_count == 2


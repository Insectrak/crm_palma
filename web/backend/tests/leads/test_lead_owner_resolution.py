"""
Tests de _resolve_lead_owner (leads.py) — quien queda como duenio del lead
segun el rol del creador y los hints del payload.

Cubre la matriz completa:
  - asesor crea sin hints -> auto-asignado a si mismo + su supervisor
  - supervisor crea sin hints -> su propia cola
  - admin crea sin hints -> _next_supervisor() round-robin (issue #43)
  - admin con asesor_id explicito -> respeta el hint
  - admin con supervisor_id explicito -> respeta el hint
  - edge: admin sin hints + sin supervisor activo -> limbo (preservado)

bump_rotation (4to valor del tuple): True solo cuando admin sin hints uso
el round-robin. El caller debe llamar _bump_rotacion despues del INSERT.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.constants import Role
from app.routers.leads import _resolve_lead_owner


# UUIDs deterministicos para los tests.
ADMIN_ID      = "00000000-0000-0000-0000-000000000001"
SUPERVISOR_ID = "00000000-0000-0000-0000-000000000002"
ASESOR_ID     = "00000000-0000-0000-0000-000000000003"
OTRO_SUP_ID   = "00000000-0000-0000-0000-000000000099"
SUP_PAOLA     = "00000000-0000-0000-0000-0000000000a0"


def _user(role: Role, user_id: str):
    """Fake current_user con la forma minima usada por _resolve_lead_owner."""
    return SimpleNamespace(role=role, user_id=user_id)


# ── Issue #43: admin sin hints usa round-robin ────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_admin_sin_hints_usa_next_supervisor_round_robin():
    """Admin crea lead sin hints -> el lead va al supervisor que devuelve
    _next_supervisor() (round-robin diario con circuit breaker).

    Antes del fix #43: usaba ORDER BY created_at ASC LIMIT 1 que siempre
    devolvia el mismo supervisor (Diego, el mas antiguo). 3 leads admin
    en entorno de pruebas cayeron los 3 en Diego, ninguno en Paola.

    Bug ID: issue #43 (regresion del fix #42)
    """
    cur = MagicMock()
    with patch(
        "app.services.integrations.ingest_core._next_supervisor",
        return_value=SUPERVISOR_ID,
    ) as mock_next:
        sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
            cur,
            payload_asesor_id=None,
            payload_supervisor_id=None,
            current_user=_user(Role.ADMIN, ADMIN_ID),
        )

    mock_next.assert_called_once_with(cur)
    assert sup_id == SUPERVISOR_ID
    assert asesor_id is None
    assert fecha_cola is not None
    assert isinstance(fecha_cola, datetime)
    assert fecha_cola.tzinfo == timezone.utc
    # bump_rotation=True señaliza al caller que actualice el contador diario.
    assert bump_rotation is True


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_admin_sin_hints_rota_entre_distintos_supervisores_en_llamadas_sucesivas():
    """Llamadas sucesivas devuelven supervisores distintos (round-robin real).

    Esto es lo que fallaba: _resolve_lead_owner antes devolvia siempre el
    mismo. Ahora delega en _next_supervisor que rota.

    Bug ID: issue #43
    """
    cur = MagicMock()
    secuencia_rotacion = [SUPERVISOR_ID, SUP_PAOLA, SUPERVISOR_ID, SUP_PAOLA]

    resultados = []
    with patch(
        "app.services.integrations.ingest_core._next_supervisor",
        side_effect=secuencia_rotacion,
    ):
        for _ in range(4):
            sup_id, _, _, _ = _resolve_lead_owner(
                cur,
                payload_asesor_id=None,
                payload_supervisor_id=None,
                current_user=_user(Role.ADMIN, ADMIN_ID),
            )
            resultados.append(sup_id)

    assert resultados == secuencia_rotacion


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_admin_sin_hints_sin_supervisor_activo_queda_en_limbo():
    """Edge: _next_supervisor() devuelve None (no hay supervisores activos
    o todos sin rotacion). Preservamos el comportamiento limbo (todos NULL,
    bump_rotation=False) — no se puede asignar a algo que no existe.

    Bug ID: issue #43
    """
    cur = MagicMock()
    with patch(
        "app.services.integrations.ingest_core._next_supervisor",
        return_value=None,
    ):
        sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
            cur,
            payload_asesor_id=None,
            payload_supervisor_id=None,
            current_user=_user(Role.ADMIN, ADMIN_ID),
        )

    assert sup_id is None
    assert asesor_id is None
    assert fecha_cola is None
    assert bump_rotation is False


# ── Casos pre-existentes — la firma ahora tiene 4 valores ────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_admin_con_supervisor_id_explicito_va_a_esa_cola():
    """Admin pasa supervisor_id en el payload -> esa es la cola destino.
    NO entra al round-robin (no bump_rotation)."""
    cur = MagicMock()

    sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
        cur,
        payload_asesor_id=None,
        payload_supervisor_id=OTRO_SUP_ID,
        current_user=_user(Role.ADMIN, ADMIN_ID),
    )

    assert sup_id == OTRO_SUP_ID
    assert asesor_id is None
    assert fecha_cola is not None
    assert bump_rotation is False
    cur.fetchone.assert_not_called()


@pytest.mark.leads
@pytest.mark.unit
def test_admin_con_asesor_id_explicito_se_resuelve_su_supervisor():
    """Admin pasa asesor_id apuntando a un asesor -> se busca su supervisor
    en crm.equipos y queda asignado directo (no cola). No bump_rotation."""
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"role": "asesor"},                  # rol del asesor_id pasado
        {"supervisor_id": SUPERVISOR_ID},    # supervisor del equipo
    ]

    sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
        cur,
        payload_asesor_id=ASESOR_ID,
        payload_supervisor_id=None,
        current_user=_user(Role.ADMIN, ADMIN_ID),
    )

    assert sup_id == SUPERVISOR_ID
    assert asesor_id == ASESOR_ID
    assert fecha_cola is None  # directo, no cola
    assert bump_rotation is False


@pytest.mark.leads
@pytest.mark.unit
def test_admin_con_asesor_id_apuntando_a_supervisor_lo_trata_como_cola():
    """Admin pasa asesor_id pero apunta a un supervisor -> se trata como
    cola del supervisor (supervisor_id=ese, asesor_id=NULL). No bump_rotation."""
    cur = MagicMock()
    cur.fetchone.return_value = {"role": "supervisor"}

    sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
        cur,
        payload_asesor_id=SUPERVISOR_ID,
        payload_supervisor_id=None,
        current_user=_user(Role.ADMIN, ADMIN_ID),
    )

    assert sup_id == SUPERVISOR_ID
    assert asesor_id is None
    assert fecha_cola is not None
    assert bump_rotation is False


@pytest.mark.leads
@pytest.mark.unit
def test_supervisor_crea_lead_sin_hints_va_a_su_propia_cola():
    """Supervisor crea lead sin hints -> queda en SU cola. No bump_rotation."""
    cur = MagicMock()

    sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
        cur,
        payload_asesor_id=None,
        payload_supervisor_id=None,
        current_user=_user(Role.SUPERVISOR, SUPERVISOR_ID),
    )

    assert sup_id == SUPERVISOR_ID
    assert asesor_id is None
    assert fecha_cola is not None
    assert bump_rotation is False
    cur.fetchone.assert_not_called()


@pytest.mark.leads
@pytest.mark.unit
def test_asesor_crea_lead_sin_hints_se_autoasigna():
    """Asesor crea lead sin hints -> queda asignado a si mismo + su supervisor
    del equipo activo. No bump_rotation."""
    cur = MagicMock()
    cur.fetchone.return_value = {"supervisor_id": SUPERVISOR_ID}

    sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
        cur,
        payload_asesor_id=None,
        payload_supervisor_id=None,
        current_user=_user(Role.ASESOR, ASESOR_ID),
    )

    assert sup_id == SUPERVISOR_ID
    assert asesor_id == ASESOR_ID
    assert fecha_cola is None  # directo, no cola
    assert bump_rotation is False


@pytest.mark.leads
@pytest.mark.unit
def test_asesor_sin_equipo_activo_supervisor_queda_null():
    """Asesor sin equipo asignado -> supervisor_id=None, asesor_id=self.

    No es el caso tipico (todos deberian tener equipo) pero existe en data
    legacy. No debe romper el insert. No bump_rotation."""
    cur = MagicMock()
    cur.fetchone.return_value = None  # no hay fila en crm.equipos

    sup_id, asesor_id, fecha_cola, bump_rotation = _resolve_lead_owner(
        cur,
        payload_asesor_id=None,
        payload_supervisor_id=None,
        current_user=_user(Role.ASESOR, ASESOR_ID),
    )

    assert sup_id is None
    assert asesor_id == ASESOR_ID
    assert fecha_cola is None
    assert bump_rotation is False

"""Tests para V075.1 — la cola pendiente debe acumular pushes para enviarlas
post-commit en el caller.

Cubre la regresion del bug pre-V075.1: process_pending_queue asignaba leads
desde la cola pero NUNCA notificaba al asesor → asesores ciegos. El fix:
acumular pushes en una lista y retornarlas en stats; el scheduler las
envia despues del commit.
"""
from unittest.mock import MagicMock, patch


def _mock_cur(rows=None):
    cur = MagicMock()
    cur.fetchall.return_value = rows or []
    cur.rowcount = 0
    return cur


@patch("app.services.lead_routing.get_config")
def test_empty_queue_returns_pushes_pendientes_key(mock_config):
    """Aun cuando no hay filas, el dict de retorno debe traer la key
    pushes_pendientes — el scheduler la lee sin asumir presencia."""
    from app.services.lead_routing import process_pending_queue
    mock_config.return_value = {"auto_asignar_enabled": True}

    cur = _mock_cur(rows=[])
    result = process_pending_queue(cur)

    assert "pushes_pendientes" in result
    assert result["pushes_pendientes"] == []


@patch("app.services.lead_routing.get_config")
def test_auto_disabled_returns_skipped_no_pushes(mock_config):
    """Si auto_asignar_enabled=False, retorna estructura skipped sin
    pushes (la key puede estar ausente o vacia — el scheduler lo maneja)."""
    from app.services.lead_routing import process_pending_queue
    mock_config.return_value = {"auto_asignar_enabled": False}

    cur = _mock_cur(rows=[])
    result = process_pending_queue(cur)

    assert result["asignados"] == 0
    # Skipped path no necesita pushes_pendientes (no hubo asignaciones)
    assert result.get("pushes_pendientes", []) == []


@patch("app.services.lead_routing.log_decision")
@patch("app.services.lead_routing.try_auto_assign")
@patch("app.services.lead_routing.get_config")
def test_successful_assignment_accumulates_push(mock_config, mock_try, mock_log):
    """Cuando try_auto_assign devuelve un asesor distinto al supervisor,
    debe quedar registrada la push en pushes_pendientes con todos los
    campos que notify_new_lead necesita."""
    from app.services.lead_routing import process_pending_queue
    mock_config.return_value = {"auto_asignar_enabled": True}

    asesor_uuid = "11111111-2222-3333-4444-555555555555"
    supervisor_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    decision = MagicMock()
    decision.asignado_a_id = asesor_uuid
    mock_try.return_value = decision

    row = {
        "id": 1, "lead_id": 42, "supervisor_id": supervisor_uuid,
        "motivo": "round_robin", "intentos": 0,
        "fuente_id": 1, "campana": "Promo X",
        "observaciones": "", "api_client_id": None,
        "nombres": "Juan Carlos", "apellidos": "Ramirez Quispe",
        "fuente_nombre": "facebook",
    }
    cur = _mock_cur(rows=[row])

    result = process_pending_queue(cur)

    assert result["asignados"] == 1
    assert len(result["pushes_pendientes"]) == 1
    p = result["pushes_pendientes"][0]
    assert p["asesor_id"] == asesor_uuid
    assert p["lead_id"] == 42
    assert p["lead_name"] == "Juan Carlos Ramirez Quispe"
    assert p["fuente"] == "facebook"


@patch("app.services.lead_routing.log_decision")
@patch("app.services.lead_routing.try_auto_assign")
@patch("app.services.lead_routing.get_config")
def test_no_push_when_decision_falls_back_to_supervisor(mock_config, mock_try, mock_log):
    """Si try_auto_assign devuelve el mismo supervisor (no encontro asesor),
    NO se acumula push — el lead se queda en la cola para el proximo tick."""
    from app.services.lead_routing import process_pending_queue
    mock_config.return_value = {"auto_asignar_enabled": True}

    supervisor_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    decision = MagicMock()
    decision.asignado_a_id = supervisor_uuid  # Mismo supervisor = no asesor disponible
    mock_try.return_value = decision

    row = {
        "id": 1, "lead_id": 42, "supervisor_id": supervisor_uuid,
        "motivo": "round_robin", "intentos": 5,
        "fuente_id": 1, "campana": "X", "observaciones": "",
        "api_client_id": None, "nombres": "X", "apellidos": "Y",
        "fuente_nombre": "instagram",
    }
    cur = _mock_cur(rows=[row])

    result = process_pending_queue(cur)

    assert result["asignados"] == 0
    assert result["reagendados"] == 1
    assert result["pushes_pendientes"] == []

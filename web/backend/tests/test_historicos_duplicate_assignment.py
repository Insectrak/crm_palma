"""
test_historicos_duplicate_assignment.py — Tests para chequeo de duplicados en asignación y 3 pestañas en Históricos.
"""
from unittest.mock import MagicMock, patch

from app.auth.schemas import TokenData
from app.routers.historicos import (
    ReasignarHistoricosRequest,
    reasignar_historicos,
    list_historicos,
    historicos_stats,
)


def test_reasignar_historicos_omits_duplicates_and_returns_details():
    """
    Si un lead histórico colisiona con un lead activo de crm.leads,
    se omite su asignación, se marca como duplicado y se reporta en la respuesta.
    """
    mock_admin_user = TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="admin@test.local",
        role="admin",
    )
    cur = MagicMock()

    def mock_fetchone():
        last_sql = str(cur.execute.call_args[0][0]) if cur.execute.call_args else ""
        if "FROM crm.leads" in last_sql:
            params = cur.execute.call_args[0][1]
            val = str(params[0])
            if "987654321" in val or "dup@test.local" in val or "12345678" in val:
                return {
                    "id": 999,
                    "nombres": "Lead",
                    "apellidos": "Existente CRM",
                    "telefono": "987654321",
                    "email": "dup@test.local",
                    "dni": "12345678",
                    "asesor_id": "33333333-3333-3333-3333-333333333333",
                    "asesor_nombre": "Otro Asesor",
                    "estado_nombre": "En seguimiento",
                    "created_at": "2026-08-01 10:00:00",
                }
            return None
        if "auth.users" in last_sql:
            return {"id": "22222222-2222-2222-2222-222222222222", "nombre": "Asesor Test"}
        if "crm_legacy.leads_historico" in last_sql and "WHERE id = %s" in last_sql:
            lid = cur.execute.call_args[0][1][0]
            if lid == 101:
                return {
                    "id": 101,
                    "nombre": "Lead Duplicado",
                    "telefono": "987654321",
                    "telefono_norm": "987654321",
                    "email": "dup@test.local",
                    "dni": "12345678",
                    "lead_crm_id": None,
                }
            elif lid == 102:
                return {
                    "id": 102,
                    "nombre": "Lead Unico",
                    "telefono": "911222333",
                    "telefono_norm": "911222333",
                    "email": "unique@test.local",
                    "dni": "87654321",
                    "lead_crm_id": None,
                }
        if "crm.fuentes" in last_sql:
            return {"id": 5}
        if "crm.estados_lead" in last_sql:
            return {"id": 1}
        if "INSERT INTO crm.leads" in last_sql:
            return {"id": 1002}
        return None

    cur.fetchone.side_effect = mock_fetchone

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = ReasignarHistoricosRequest(
        lead_ids=[101, 102],
        asesor_id="22222222-2222-2222-2222-222222222222",
    )

    with patch("app.routers.historicos.get_db", return_value=db_cm):
        res = reasignar_historicos(body=req, current_user=mock_admin_user)

    assert res["success"] is True
    assert res["total_solicitados"] == 2
    assert res["promoted"] == 1
    assert res["duplicates_count"] == 1
    assert len(res["duplicates"]) == 1

    dup = res["duplicates"][0]
    assert dup["historico_id"] == 101
    assert dup["crm_lead_id"] == 999
    assert "987654321" in dup["motivo"]
    assert dup["crm_asesor_nombre"] == "Otro Asesor"
    assert conn.commit.called


def test_list_historicos_tab_filters():
    """
    list_historicos debe aplicar el filtro WHERE según la pestaña activa (sin_asignar, asignados, duplicados).
    """
    mock_admin_user = TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="admin@test.local",
        role="admin",
    )
    cur = MagicMock()
    cur.fetchone.return_value = {"total": 5}
    cur.fetchall.return_value = [
        {"id": 1, "nombre": "Test 1", "es_duplicado": False},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.historicos.get_db", return_value=db_cm):
        # 1. Pestaña sin_asignar
        res_sin = list_historicos(tab="sin_asignar", current_user=mock_admin_user)
        assert res_sin["tab"] == "sin_asignar"
        query_sin = cur.execute.call_args_list[0][0][0]
        assert "h.es_duplicado IS NOT TRUE" in query_sin

        # 2. Pestaña asignados
        res_asig = list_historicos(tab="asignados", current_user=mock_admin_user)
        assert res_asig["tab"] == "asignados"
        query_asig = cur.execute.call_args_list[2][0][0]
        assert "h.lead_crm_id IS NOT NULL" in query_asig

        # 3. Pestaña duplicados
        res_dup = list_historicos(tab="duplicados", current_user=mock_admin_user)
        assert res_dup["tab"] == "duplicados"
        query_dup = cur.execute.call_args_list[4][0][0]
        assert "h.es_duplicado IS TRUE" in query_dup


def test_historicos_stats_includes_all_three_tabs():
    """
    historicos_stats debe retornar contadores para sin_asignar, asignados y duplicados.
    """
    mock_admin_user = TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="admin@test.local",
        role="admin",
    )
    cur = MagicMock()
    cur.fetchone.return_value = {
        "total": 150,
        "sin_asignar": 100,
        "asignados": 40,
        "duplicados": 10,
        "telefonos_unicos": 145,
        "proyectos": 3,
        "asignados_crm": 40,
        "no_registrados": 0,
    }

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.historicos.get_db", return_value=db_cm):
        stats = historicos_stats(current_user=mock_admin_user)

    assert stats["total"] == 150
    assert stats["sin_asignar"] == 100
    assert stats["asignados"] == 40
    assert stats["duplicados"] == 10
    query = cur.execute.call_args[0][0]
    assert "sin_asignar" in query
    assert "asignados" in query
    assert "duplicados" in query


if __name__ == "__main__":
    print("Ejecutando test_reasignar_historicos_omits_duplicates_and_returns_details...")
    test_reasignar_historicos_omits_duplicates_and_returns_details()
    print("✓ test_reasignar_historicos_omits_duplicates_and_returns_details PASÓ")

    print("Ejecutando test_list_historicos_tab_filters...")
    test_list_historicos_tab_filters()
    print("✓ test_list_historicos_tab_filters PASÓ")

    print("Ejecutando test_historicos_stats_includes_all_three_tabs...")
    test_historicos_stats_includes_all_three_tabs()
    print("✓ test_historicos_stats_includes_all_three_tabs PASÓ")

    print("\nTodos los tests pasaron exitosamente.")

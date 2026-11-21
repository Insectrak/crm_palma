"""
test_agenda_citas_improvements.py — Tests para las mejoras de Agenda y Respaldo de Matrículas:
1. Filtro por supervisor en GET /api/agenda/citas.
2. Inclusión de supervisor_id y supervisor_nombre en la proyección de citas.
3. Respaldo de matrículas en role_filter para supervisores.
"""
from unittest.mock import MagicMock, patch

from app.auth.schemas import TokenData
from app.routers.agenda import get_citas
from app.filters.lead_filters import role_filter


def test_get_citas_supervisor_filter_applied():
    """get_citas con supervisor_id añade la cláusula y parámetros correspondientes."""
    admin_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@test.local",
        role="admin",
        permissions={},
    )
    sup_target_id = "22222222-2222-2222-2222-222222222222"

    executed_sql = None
    executed_params = None

    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        {
            "id": 1,
            "lead_id": 10,
            "tipo_contacto": "cita",
            "resultado": "cita_agendada",
            "tipo_cita": "cita virtual",
            "url_reunion": None,
            "notas": "⭐ Alto potencial de cierre",
            "proxima_accion": None,
            "fecha_evento": "2026-09-20T10:00:00",
            "fecha_dia": "2026-09-20",
            "asesor_id": "33333333-3333-3333-3333-333333333333",
            "asesor_nombre": "Carlos Asesor",
            "supervisor_id": sup_target_id,
            "supervisor_nombre": "Diego Supervisor",
            "lead_nombre": "Ana Gomez",
            "lead_telefono": "999888777",
            "lead_estado_id": 1,
            "lead_estado_nombre": "Nuevo",
            "lead_estado_color": "#3B82F6",
            "cita_estado_id": 1,
            "cita_estado_codigo": "pendiente",
            "cita_estado_nombre": "Pendiente",
            "cita_estado_color": "#3B82F6",
        }
    ]

    def mock_execute(sql, params):
        nonlocal executed_sql, executed_params
        executed_sql = sql
        executed_params = params

    mock_cur.execute = mock_execute

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("app.routers.agenda.get_db") as mock_get_db, \
         patch("app.routers.agenda._has_cita_estado_column", return_value=True):
        mock_get_db.return_value.__enter__.return_value = mock_conn

        res = get_citas(
            mes="2026-09",
            supervisor_id=sup_target_id,
            current_user=admin_user,
        )

    assert res["total"] == 1
    assert len(res["citas"]) == 1
    cita = res["citas"][0]
    assert cita["supervisor_id"] == sup_target_id
    assert cita["supervisor_nombre"] == "Diego Supervisor"
    assert cita["notas"] == "⭐ Alto potencial de cierre"

    # Verificar que el SQL incluye la proyección de supervisor, el filtro y la unión de seguimientos/oportunidad futura
    assert "supervisor_id" in executed_sql
    assert "supervisor_nombre" in executed_sql
    assert "l.supervisor_id = %s::uuid OR eq_sup.supervisor_id = %s::uuid" in executed_sql
    assert "UNION ALL" in executed_sql
    assert "fecha_proxima_gestion" in executed_sql
    assert "item_kind" in executed_sql
    assert sup_target_id in executed_params


def test_supervisor_role_filter_includes_matriculas_backup():
    """El role_filter del supervisor debe conservar matrículas/cierres aunque el asesor haya salido del equipo."""
    sup_user = TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="supervisor@test.local",
        role="supervisor",
        permissions={},
    )
    sql, params = role_filter(sup_user)

    # Verifica que el filtro no solo busque `asesor_id IS NULL` sino también matrículas
    assert "nombre ILIKE '%%matr%%'" in sql or "nombre ILIKE '%matr%'" in sql
    assert "l.tipo_cierre IS NOT NULL" in sql
    assert len(params) == 6
    assert all(p == sup_user.user_id for p in params)

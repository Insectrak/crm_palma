"""
Tests unitarios para lead_history_service:
Verifica el registro detallado de cambios de campos en leads, normalización de valores,
resolución de nombres para claves foráneas (estado, fuente, asesor, sede) y ficha técnica.
"""
from unittest.mock import MagicMock
from app.services import lead_history_service


def test_record_field_change_inserts_when_different():
    cur = MagicMock()
    user = MagicMock()
    user.user_id = "00000000-0000-0000-0000-000000000001"
    user.nombre_completo = "Carlos Admin"
    user.role = "admin"

    lead_history_service.record_field_change(
        cur=cur,
        lead_id=123,
        user=user,
        campo="telefono",
        campo_label="Teléfono",
        valor_anterior="987654321",
        valor_nuevo="912345678",
        origen="edicion_ficha",
    )

    assert cur.execute.called
    sql = cur.execute.call_args[0][0]
    args = cur.execute.call_args[0][1]

    assert "INSERT INTO crm.lead_historial_cambios" in sql
    assert args[0] == 123  # lead_id
    assert args[1] == "00000000-0000-0000-0000-000000000001"  # usuario_id
    assert args[2] == "Carlos Admin"  # usuario_nombre
    assert args[3] == "admin"  # usuario_rol
    assert args[4] == "telefono"  # campo
    assert args[5] == "Teléfono"  # campo_label
    assert args[6] == "987654321"  # valor_anterior
    assert args[7] == "912345678"  # valor_nuevo
    assert args[8] == "edicion_ficha"  # origen


def test_record_field_change_ignores_identical_values():
    cur = MagicMock()
    user = MagicMock()

    lead_history_service.record_field_change(
        cur=cur,
        lead_id=123,
        user=user,
        campo="ciudad",
        campo_label="Ciudad",
        valor_anterior="Arequipa",
        valor_nuevo=" Arequipa ",  # identical after strip
        origen="edicion_ficha",
    )

    assert not cur.execute.called


def test_record_lead_updates_detects_multiple_changes():
    cur = MagicMock()
    # Mocking for state / user name queries
    cur.fetchone.return_value = {"nombre": "En Seguimiento"}
    user = MagicMock()
    user.user_id = "00000000-0000-0000-0000-000000000001"
    user.nombre_completo = "Supervisor Juan"
    user.role = "supervisor"

    old_lead = {
        "nombres": "Pedro",
        "apellidos": "Gomez",
        "telefono": "987654321",
        "ciudad": "Lima",
        "calidad": "FRIO",
    }

    new_fields = {
        "telefono": "999888777",
        "ciudad": "Arequipa",
        "calidad": "CALIENTE",
        "apellidos": "Gomez",  # unchanged
    }

    lead_history_service.record_lead_updates(
        cur=cur,
        lead_id=456,
        user=user,
        old_lead=old_lead,
        new_fields=new_fields,
        origin="edicion_ficha",
    )

    # 3 fields changed: telefono, ciudad, calidad
    executed_sqls = [call[0][0] for call in cur.execute.call_args_list if "INSERT INTO crm.lead_historial_cambios" in call[0][0]]
    assert len(executed_sqls) == 3


def test_record_lead_updates_ficha_tecnica_diff():
    cur = MagicMock()
    user = MagicMock()
    user.user_id = "00000000-0000-0000-0000-000000000001"
    user.nombre_completo = "Asesor Maria"
    user.role = "asesor"

    old_lead = {
        "ficha_tecnica": {
            "motivacion": "Aprender inglés básico",
            "ubicacion": "Arequipa",
        }
    }

    new_fields = {
        "ficha_tecnica": {
            "motivacion": "Inglés avanzado para trabajo",
            "ubicacion": "Arequipa",  # unchanged
            "beneficiario": "Para sí mismo",  # new answer
        }
    }

    lead_history_service.record_lead_updates(
        cur=cur,
        lead_id=789,
        user=user,
        old_lead=old_lead,
        new_fields=new_fields,
        origin="ficha_tecnica",
    )

    executed_args = [call[0][1] for call in cur.execute.call_args_list if "INSERT INTO crm.lead_historial_cambios" in call[0][0]]
    campos_registrados = [arg[4] for arg in executed_args]

    assert "ficha_tecnica.motivacion" in campos_registrados
    assert "ficha_tecnica.beneficiario" in campos_registrados
    assert "ficha_tecnica.ubicacion" not in campos_registrados


def test_record_status_change():
    cur = MagicMock()
    cur.fetchone.side_effect = [{"nombre": "Nuevo"}, {"nombre": "Matriculado"}]
    user = MagicMock()
    user.user_id = "00000000-0000-0000-0000-000000000001"
    user.nombre_completo = "Admin Sistema"
    user.role = "admin"

    lead_history_service.record_status_change(
        cur=cur,
        lead_id=101,
        user=user,
        old_estado_id=1,
        new_estado_id=5,
        extra_details="Cierre autónomo",
        origen="cambio_estado",
    )

    assert cur.execute.called
    last_insert_call = [call for call in cur.execute.call_args_list if "INSERT INTO crm.lead_historial_cambios" in call[0][0]][-1]
    args = last_insert_call[0][1]

    assert args[0] == 101
    assert args[4] == "estado_id"
    assert args[5] == "Estado"
    assert "Nuevo" in args[6]
    assert "Matriculado" in args[7]
    assert "Cierre autónomo" in args[7]


def test_record_reassignment():
    cur = MagicMock()
    cur.fetchone.side_effect = [{"nombre": "Juan Asesor", "email": "juan@test.com"}, {"nombre": "Carlos Nuevo", "email": "carlos@test.com"}]
    user = MagicMock()
    user.user_id = "00000000-0000-0000-0000-000000000001"
    user.nombre_completo = "Supervisor Ana"
    user.role = "supervisor"

    lead_history_service.record_reassignment(
        cur=cur,
        lead_id=202,
        user=user,
        old_asesor_id="11111111-1111-1111-1111-111111111111",
        new_asesor_id="22222222-2222-2222-2222-222222222222",
        motivo="manual_supervisor",
    )

    last_insert_call = [call for call in cur.execute.call_args_list if "INSERT INTO crm.lead_historial_cambios" in call[0][0]][-1]
    args = last_insert_call[0][1]

    assert args[0] == 202
    assert args[4] == "asesor_id"
    assert args[5] == "Asesor asignado"
    assert "Juan Asesor" in args[6]
    assert "Carlos Nuevo" in args[7]
    assert "Reasignación" in args[7]


"""
test_reciclaje_tmk.py — Tests unitarios para endpoints de Bolsa de Reciclaje TMK.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.auth.schemas import TokenData
from app.routers.reciclaje_tmk import (
    ReasignarLoteRequest,
    RevertirTmkRequest,
    get_resumen_bolsa,
    list_leads_reciclables,
    reasignar_lote_tmk,
    list_lotes_reciclaje,
    revertir_leads_tmk,
)


@pytest.fixture
def mock_admin_user():
    return TokenData(
        user_id="11111111-1111-1111-1111-111111111111",
        email="supervisor@test.local",
        role="supervisor",
    )


def test_reasignar_lote_tmk_success(mock_admin_user):
    cur = MagicMock()
    # Mock fetching fuente_tmk, nuevo_estado, and RETURNING lote id
    cur.fetchone.side_effect = [
        {"id": 99},  # fuente_tmk row
        {"id": 1},   # nuevo estado row
        {"id": "22222222-2222-2222-2222-222222222222"},  # RETURNING id de lote
    ]
    # Mock fetching candidatos
    cur.fetchall.return_value = [
        {"id": 101, "asesor_anterior_id": "33333333-3333-3333-3333-333333333333", "fuente_anterior_id": 1, "estado_anterior_id": 2},
        {"id": 102, "asesor_anterior_id": None, "fuente_anterior_id": 1, "estado_anterior_id": 2},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = ReasignarLoteRequest(
        nombre_lote="Campaña Reactivación Agosto",
        criterio="no_contesta",
        limite_leads=50,
        asesores_ids=[
            "44444444-4444-4444-4444-444444444444",
            "55555555-5555-5555-5555-555555555555",
        ],
        sede_id="66666666-6666-6666-6666-666666666666",
        descripcion="Reasignando leads que no contestan",
    )

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = reasignar_lote_tmk(body=req, current_user=mock_admin_user)

    assert res["ok"] is True
    assert res["leads_reasignados"] == 2
    assert res["asesores_involucrados"] == 2
    assert conn.commit.called

    # Verificar que el INSERT de lotes_reciclaje use los campos correctos
    queries = [call[0][0] for call in cur.execute.call_args_list]
    lote_insert_query = [q for q in queries if "INSERT INTO crm.lotes_reciclaje" in q][0]
    assert "criterio," in lote_insert_query or "criterio\n" in lote_insert_query
    assert "descripcion" in lote_insert_query
    assert "asesores_asignados" in lote_insert_query

    # Verificar que el UPDATE de leads actualice fuente_id, origen_reciclaje y estado_id
    lead_update_query = [q for q in queries if "UPDATE crm.leads" in q][0]
    assert "estado_id = COALESCE(%s, estado_id)" in lead_update_query
    assert "fuente_id = COALESCE(%s, fuente_id)" in lead_update_query
    assert "origen_reciclaje = %s" in lead_update_query

    # Verificar que se inserte en asignaciones_log
    assert any("INSERT INTO crm.asignaciones_log" in q for q in queries)

    # Verificar que el SELECT de estados_lead no filtre por columna inexistente 'activo'
    estado_queries = [q for q in queries if "FROM crm.estados_lead" in q]
    for eq in estado_queries:
        assert "activo" not in eq

    # Verificar que se inserte en contactos con asesor_id (no usuario_id)
    contacto_insert_query = [q for q in queries if "INSERT INTO crm.contactos" in q][0]
    assert "asesor_id" in contacto_insert_query
    assert "usuario_id" not in contacto_insert_query


def test_list_lotes_reciclaje_success(mock_admin_user):
    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "nombre": "Lote 1",
            "criterio": "no_contesta",
            "descripcion": "Notas",
            "total_leads": 10,
            "asesores_asignados": ["44444444-4444-4444-4444-444444444444"],
            "created_at": "2026-08-24T12:00:00Z",
            "creado_por_nombre": "Supervisor Test",
            "sede_nombre": "Sede Central",
        }
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = list_lotes_reciclaje(limit=10, current_user=mock_admin_user)

    assert len(res["lotes"]) == 1
    queries = [call[0][0] for call in cur.execute.call_args_list]
    assert any("criterio_origen" not in q and "lr.criterio" in q for q in queries)


def test_revertir_leads_tmk_success(mock_admin_user):
    cur = MagicMock()
    # Simular lead reciclado recuperado
    cur.fetchall.return_value = [
        {
            "id": 101,
            "asesor_actual_id": "33333333-3333-3333-3333-333333333333",
            "previous_asesor_id": "22222222-2222-2222-2222-222222222222",
            "fuente_id": 99,
            "fuente_pre_reciclaje_id": 1,
            "estado_id": 1,
            "estado_pre_reciclaje_id": 4,
            "lote_reciclaje_id": "44444444-4444-4444-4444-444444444444",
            "origen_reciclaje": "Bolsa TMK",
        }
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = RevertirTmkRequest(ids=[101])

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = revertir_leads_tmk(body=req, current_user=mock_admin_user)

    assert res["ok"] is True
    assert res["revertidos"] == 1

    queries = [call[0][0] for call in cur.execute.call_args_list]

    # Verificar que el UPDATE de leads devuelva los valores originales y limpie flags de reciclaje
    lead_update = [q for q in queries if "UPDATE crm.leads" in q][0]
    assert "es_reciclado = FALSE" in lead_update
    assert "origen_reciclaje = NULL" in lead_update
    assert "lote_reciclaje_id = NULL" in lead_update

    # Verificar auditoría en asignaciones_log
    assert any("INSERT INTO crm.asignaciones_log" in q for q in queries)
    # Verificar auditoría en contactos
    assert any("INSERT INTO crm.contactos" in q for q in queries)
    # Verificar sincronización con WhatsApp
    assert any("UPDATE crm.wa_conversations" in q for q in queries)


def test_list_leads_reciclables_pagination(mock_admin_user):
    cur = MagicMock()
    cur.fetchone.return_value = {"total": 120}
    cur.fetchall.return_value = [
        {
            "id": 1,
            "nombre_completo": "Lead Uno",
            "telefono": "999888777",
            "email": "lead1@test.local",
            "campana": "Facebook",
            "estado_id": 2,
            "estado_nombre": "No Contesta",
            "estado_color": "#e11d48",
            "fuente_nombre": "Bolsa TMK",
            "asesor_actual_id": "33333333-3333-3333-3333-333333333333",
            "asesor_actual": "Asesor Test",
            "previous_asesor_id": None,
            "previous_asesor_nombre": None,
            "sede_id": None,
            "sede_nombre": None,
            "fecha_ingreso": "2026-08-01T10:00:00Z",
            "es_reciclado": False,
            "fecha_reciclaje": None,
            "origen_reciclaje": None,
            "historial_asignaciones": [],
        }
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = list_leads_reciclables(
            criterio="no_contesta",
            limit=50,
            page=2,
            search="Lead",
            current_user=mock_admin_user,
        )

    assert res["total"] == 120
    assert res["page"] == 2
    assert res["total_pages"] == 3
    assert res["limit"] == 50
    assert len(res["leads"]) == 1

    queries = [call[0][0] for call in cur.execute.call_args_list]
    count_query = [q for q in queries if "SELECT COUNT(*)" in q][0]
    list_query = [q for q in queries if "LIMIT %s OFFSET %s" in q][0]
    assert "LIMIT %s OFFSET %s" in list_query
    assert "historial_asignaciones" in list_query


def test_reasignar_lead_individual_success(mock_admin_user):
    from app.routers.reciclaje_tmk import ReasignarIndividualRequest, reasignar_lead_individual

    cur = MagicMock()
    # Mock fuente_tmk, lead fetch, nuevo_estado
    cur.fetchone.side_effect = [
        {"id": 99},  # fuente_tmk row
        {"id": 101, "asesor_id": "33333333-3333-3333-3333-333333333333", "fuente_id": 1, "estado_id": 4},  # lead row
        {"id": 1},   # nuevo_estado row
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = ReasignarIndividualRequest(
        lead_id=101,
        asesor_id="44444444-4444-4444-4444-444444444444",
        estado_id=1,
        criterio="no_contesta",
    )

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = reasignar_lead_individual(body=req, current_user=mock_admin_user)

    assert res["ok"] is True
    assert res["lead_id"] == 101
    assert conn.commit.called

    queries = [call[0][0] for call in cur.execute.call_args_list]
    assert any("UPDATE crm.leads" in q for q in queries)
    assert any("INSERT INTO crm.asignaciones_log" in q for q in queries)
    assert any("INSERT INTO crm.contactos" in q for q in queries)
    assert any("UPDATE crm.wa_conversations" in q for q in queries)


def test_build_criterio_where_no_contesta():
    from app.routers.reciclaje_tmk import _build_criterio_where

    where_clause = _build_criterio_where("no_contesta")
    assert "No contesta / Bolsa TMK" in where_clause
    assert "No contesta / Bolsa de reciclaje" in where_clause
    assert "Bolsa TMK" in where_clause
    assert "Bolsa de reciclaje" in where_clause
    # Asegurar que no incluya estados genéricos no deseados como 'sin respuesta' o 'apagado'
    assert "sin respuesta" not in where_clause
    assert "apagado" not in where_clause


def test_desasignar_leads_tmk_individual(mock_admin_user):
    from app.routers.reciclaje_tmk import DesasignarTmkRequest, desasignar_leads_tmk

    cur = MagicMock()
    cur.fetchall.return_value = [
        {"id": 101, "asesor_actual": "33333333-3333-3333-3333-333333333333"},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = DesasignarTmkRequest(ids=[101])

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = desasignar_leads_tmk(body=req, current_user=mock_admin_user)

    assert res["ok"] is True
    assert res["desasignados"] == 1
    assert conn.commit.called

    queries = [call[0][0] for call in cur.execute.call_args_list]
    assert any("UPDATE crm.leads" in q and "asesor_id = NULL" in q for q in queries)
    assert any("INSERT INTO crm.asignaciones_log" in q for q in queries)
    assert any("UPDATE crm.wa_conversations" in q and "asesor_id = NULL" in q for q in queries)
    assert any("INSERT INTO crm.contactos" in q for q in queries)


def test_desasignar_leads_tmk_bulk_filter(mock_admin_user):
    from app.routers.reciclaje_tmk import DesasignarTmkRequest, desasignar_leads_tmk

    cur = MagicMock()
    cur.fetchall.return_value = [
        {"id": 201, "asesor_actual": "33333333-3333-3333-3333-333333333333"},
        {"id": 202, "asesor_actual": "44444444-4444-4444-4444-444444444444"},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    req = DesasignarTmkRequest(
        criterio="no_contesta",
        desasignar_todos_en_filtro=True,
    )

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = desasignar_leads_tmk(body=req, current_user=mock_admin_user)

    assert res["ok"] is True
    assert res["desasignados"] == 2
    assert conn.commit.called


def test_exportar_leads_bolsa_todos(mock_admin_user):
    import io
    import openpyxl
    from datetime import datetime
    from app.routers.reciclaje_tmk import exportar_leads_bolsa
    from fastapi import Request

    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "id": 101,
            "nombre_completo": "Juan Perez",
            "telefono": "+51987654321",
            "dni": "12345678",
            "email": "juan@test.local",
            "ciudad": "Lima",
            "segmento_bolsa": "No Contesta",
            "estado_nombre": "No contesta / Bolsa TMK",
            "asesor_actual": "Sin asesor",
            "asesor_actual_email": "",
            "ultimo_asesor_previo": "Carlos Asesor",
            "ultimo_asesor_email": "carlos@test.local",
            "sede_nombre": "Sede Central",
            "fuente_nombre": "Bolsa TMK",
            "campana": "Campaña Facebook",
            "anuncio": "Anuncio 1",
            "fecha_ingreso": datetime(2026, 8, 1, 10, 30),
            "fecha_reasignacion": None,
            "es_reciclado": "No",
            "fecha_reciclaje": None,
            "origen_reciclaje": "—",
            "lote_reciclaje_nombre": "—",
            "intentos_contacto": 4,
            "ultima_actividad": datetime(2026, 8, 10, 15, 0),
            "ultimo_tipo_contacto": "llamada",
            "ultimo_resultado": "No contesta",
            "observaciones": "Se le llamó 4 veces sin respuesta",
        }
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    mock_req = MagicMock(spec=Request)

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = exportar_leads_bolsa(
            request=mock_req,
            criterio="todos",
            sede_id=None,
            search=None,
            ids=None,
            current_user=mock_admin_user,
        )

    assert res.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    content_disp = res.headers["Content-Disposition"]
    assert "attachment" in content_disp
    assert "contactos_bolsa_tmk_todos_" in content_disp
    assert ".xlsx" in content_disp

    # Leer el stream de salida con openpyxl
    file_bytes = res.body
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
    ws = wb.active
    assert ws.title == "Bolsa TMK"
    assert ws.cell(row=1, column=1).value == "ID Lead"
    assert ws.cell(row=1, column=2).value == "Nombre Completo"
    assert ws.cell(row=2, column=1).value == 101
    assert ws.cell(row=2, column=2).value == "Juan Perez"
    assert ws.cell(row=2, column=3).value == "+51987654321"


def test_exportar_leads_bolsa_selected_ids(mock_admin_user):
    import io
    import openpyxl
    from app.routers.reciclaje_tmk import exportar_leads_bolsa
    from fastapi import Request

    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "id": 999,
            "nombre_completo": "Ana Gomez",
            "telefono": "+51999888777",
            "dni": "87654321",
            "email": "ana@test.local",
            "ciudad": "Arequipa",
            "segmento_bolsa": "Inactivo > 30 días",
            "estado_nombre": "Contactado",
            "asesor_actual": "Maria Lopez",
            "asesor_actual_email": "maria@test.local",
            "ultimo_asesor_previo": "—",
            "ultimo_asesor_email": "",
            "sede_nombre": "Sede Arequipa",
            "fuente_nombre": "Google Ads",
            "campana": "Camp Sur",
            "anuncio": "Ad 2",
            "fecha_ingreso": None,
            "fecha_reasignacion": None,
            "es_reciclado": "Sí",
            "fecha_reciclaje": None,
            "origen_reciclaje": "Bolsa TMK",
            "lote_reciclaje_nombre": "Lote Agosto",
            "intentos_contacto": 2,
            "ultima_actividad": None,
            "ultimo_tipo_contacto": "whatsapp",
            "ultimo_resultado": "Leído",
            "observaciones": "Interesada para próximo mes",
        }
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    mock_req = MagicMock(spec=Request)

    with patch("app.routers.reciclaje_tmk.get_db", return_value=db_cm):
        res = exportar_leads_bolsa(
            request=mock_req,
            criterio="todos",
            sede_id=None,
            search=None,
            ids="999",
            current_user=mock_admin_user,
        )

    content_disp = res.headers["Content-Disposition"]
    assert "contactos_bolsa_tmk_seleccionados_" in content_disp
    assert ".xlsx" in content_disp

    file_bytes = res.body
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
    ws = wb.active
    assert ws.cell(row=2, column=1).value == 999
    assert ws.cell(row=2, column=2).value == "Ana Gomez"




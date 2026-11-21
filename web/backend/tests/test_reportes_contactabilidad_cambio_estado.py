"""
Tests unitarios para verificar que los cambios de estado NO se contabilicen como contactibilidad
en los reportes (por asesor, fuentes, campanas, ranking asesores, ranking equipos,
leads detalle y dashboard resumen).
"""
import pytest
from unittest.mock import MagicMock, patch
from app.auth.jwt import create_access_token

ADMIN_ID = "00000000-0000-0000-0000-000000000001"
ASESOR_ID = "00000000-0000-0000-0000-000000000003"


@pytest.fixture
def auth_headers_admin():
    token = create_access_token(
        data={"sub": ADMIN_ID, "email": "admin@test.com", "role": "admin"}
    )
    return {"Authorization": f"Bearer {token}"}


class MockDB:
    def __init__(self, fetchall_data=None, fetchone_data=None):
        self.cursor_mock = MagicMock()
        self.executed_queries = []
        self.fetchall_data = fetchall_data if fetchall_data is not None else []
        self.fetchone_data = fetchone_data if fetchone_data is not None else {}

        def mock_execute(sql, params=None):
            self.executed_queries.append((sql, params))

        def mock_fetchall():
            if isinstance(self.fetchall_data, list) and self.fetchall_data and isinstance(self.fetchall_data[0], list):
                return self.fetchall_data.pop(0)
            return self.fetchall_data

        def mock_fetchone():
            if isinstance(self.fetchone_data, list):
                return self.fetchone_data.pop(0) if self.fetchone_data else {}
            return self.fetchone_data

        self.cursor_mock.execute.side_effect = mock_execute
        self.cursor_mock.fetchall.side_effect = mock_fetchall
        self.cursor_mock.fetchone.side_effect = mock_fetchone
        self.cursor_mock.__enter__.return_value = self.cursor_mock
        self.cursor_mock.__exit__.return_value = None

    def cursor(self, *a, **kw):
        return self.cursor_mock

    def commit(self):
        pass

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.mark.unit
def test_por_asesor_excluye_cambio_estado(client, auth_headers_admin):
    """
    Verifica que /api/reportes/por-asesor use LATERAL JOIN excluyendo 'cambio_estado',
    'cambio_fuente', 'sistema', 'reasignacion' y no 'WHERE e.nombre != Nuevo'.
    """
    mock_db = MockDB(
        fetchall_data=[
            {
                "asesor_id": ASESOR_ID,
                "nombre_completo": "Juan Asesor",
                "rol": "asesor",
                "total_leads": 10,
                "leads_contactados": 3,
                "leads_calificados": 2,
                "leads_en_negociacion": 1,
                "leads_ganados": 1,
                "leads_perdidos": 1,
                "leads_sin_contactar": 7,
                "tasa_conversion_pct": 10.0,
                "tasa_contactabilidad_pct": 30.0,
            }
        ],
        fetchone_data={"total": 1},
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/por-asesor?fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert len(data["rows"]) == 1
    assert data["rows"][0]["leads_contactados"] == 3
    assert data["rows"][0]["leads_sin_contactar"] == 7
    assert data["rows"][0]["tasa_contactabilidad_pct"] == 30.0

    # Verificar la consulta SQL ejecutada
    assert len(mock_db.executed_queries) >= 1
    sql, params = mock_db.executed_queries[0]

    # No debe evaluar contactados comparando e.nombre != 'Nuevo'
    assert "WHERE e.nombre != 'Nuevo'" not in sql
    assert "WHERE e.nombre NOT IN ('Nuevo')" not in sql

    # Debe filtrar lc.contactado IS NOT NULL y excluir cambio_estado
    assert "WHERE lc.contactado IS NOT NULL" in sql
    assert "WHERE lc.contactado IS NULL" in sql
    assert "cambio_estado" in sql
    assert "crm.llamadas" in sql


@pytest.mark.unit
def test_por_fuente_excluye_cambio_estado(client, auth_headers_admin):
    """
    Verifica que /api/reportes/por-fuente use LATERAL JOIN excluyendo tipos no reales.
    """
    mock_db = MockDB(fetchall_data=[
        {
            "fuente": "Facebook",
            "total_leads": 20,
            "leads_contactados": 10,
            "leads_calificados": 5,
            "leads_en_negociacion": 3,
            "leads_ganados": 2,
            "leads_perdidos": 2,
            "tasa_conversion_pct": 10.0,
            "tasa_contactabilidad_pct": 50.0,
        }
    ])

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/por-fuente?fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert len(data["rows"]) == 1

    sql, params = mock_db.executed_queries[0]
    assert "WHERE e.nombre != 'Nuevo'" not in sql
    assert "WHERE lc.contactado IS NOT NULL" in sql
    assert "cambio_estado" in sql


@pytest.mark.unit
def test_ranking_asesores_excluye_cambio_estado(client, auth_headers_admin):
    """
    Verifica que /api/reportes/ranking con metrica contactabilidad use lc.contactado.
    """
    mock_db = MockDB(fetchall_data=[
        {
            "asesor_id": ASESOR_ID,
            "nombre_completo": "Ana Asesora",
            "rol": "asesor",
            "total_leads": 15,
            "leads_ganados": 3,
            "leads_calificados": 5,
            "leads_en_negociacion": 2,
            "leads_contactados": 12,
            "leads_sin_contactar": 3,
            "tasa_conversion_pct": 20.0,
            "tasa_contactabilidad_pct": 80.0,
            "llamadas_totales": 20,
            "llamadas_contestadas": 15,
            "citas_agendadas": 4,
            "citas_realizadas": 3,
        }
    ])

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking?metrica=contactabilidad&fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert len(data["ranking"]) == 1

    sql, params = mock_db.executed_queries[0]
    assert "WHERE e.nombre != 'Nuevo'" not in sql
    assert "WHERE lc.contactado IS NOT NULL" in sql
    assert "cambio_estado" in sql


@pytest.mark.unit
def test_ranking_equipos_excluye_cambio_estado(client, auth_headers_admin):
    """
    Verifica que /api/reportes/ranking-equipos use lc.contactado y excluya cambio_estado.
    """
    mock_db = MockDB(fetchall_data=[
        {
            "supervisor_id": ADMIN_ID,
            "supervisor_nombre": "Supervisor Alpha",
            "email": "sup@test.com",
            "num_asesores": 3,
            "team_size": 3,
            "total_leads": 30,
            "leads_ganados": 5,
            "leads_calificados": 10,
            "leads_en_negociacion": 4,
            "leads_contactados": 24,
            "leads_sin_contactar": 6,
            "tasa_conversion_pct": 16.7,
            "tasa_contactabilidad_pct": 80.0,
            "llamadas_totales": 40,
            "llamadas_contestadas": 30,
            "citas_agendadas": 8,
            "citas_realizadas": 6,
        }
    ])

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking-equipos?metrica=contactabilidad&fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert len(data["ranking"]) == 1

    sql, params = mock_db.executed_queries[0]
    assert "WHERE e.nombre != 'Nuevo'" not in sql
    assert "WHERE lc.contactado IS NOT NULL" in sql
    assert "cambio_estado" in sql


@pytest.mark.unit
def test_leads_detalle_contactados_excluye_cambio_estado(client, auth_headers_admin):
    """
    Verifica que /api/reportes/leads-detalle?tipo_metrica=contactados NO filtre por e.nombre != 'Nuevo'
    sino por existencia de contacto real en crm.contactos (sin cambio_estado) o crm.llamadas.
    """
    mock_db = MockDB(
        fetchone_data={"total": 1},
        fetchall_data=[
            {
                "id": 101,
                "nombres": "Lead",
                "apellidos": "Prueba",
                "nombre_completo": "Lead Prueba",
                "telefono": "999888777",
                "email": "lead@test.com",
                "dni": "12345678",
                "origen": "Facebook",
                "campana": "Campaña 1",
                "calidad": "alta",
                "intentos_contacto": 2,
                "tipo_cierre": None,
                "segunda_voz": None,
                "motivo_perdida": None,
                "motivo_perdida_otro": None,
                "fecha_ingreso": "2026-03-05 10:00:00",
                "fecha_ultimo_contacto": "2026-03-05 11:00:00",
                "estado_id": 2,
                "estado_nombre": "Contactado",
                "estado_color": "#22c55e",
                "fuente_id": 1,
                "fuente_nombre": "Facebook",
                "asesor_id": ASESOR_ID,
                "asesor_nombre": "Juan Asesor",
            }
        ],
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/leads-detalle?tipo_metrica=contactados&fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1

    # Revisar count_sql y items_sql
    assert len(mock_db.executed_queries) == 2
    count_sql, _ = mock_db.executed_queries[0]
    assert "e.nombre != 'Nuevo'" not in count_sql
    assert "cambio_estado" in count_sql
    assert "EXISTS (SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id" in count_sql


@pytest.mark.unit
def test_leads_detalle_sin_contactar_excluye_cambio_estado(client, auth_headers_admin):
    """
    Verifica que /api/reportes/leads-detalle?tipo_metrica=sin_contactar incluya leads aunque
    hayan cambiado de estado si no tuvieron contacto real (NOT EXISTS contacto real).
    """
    mock_db = MockDB(
        fetchone_data={"total": 2},
        fetchall_data=[
            {
                "id": 102,
                "nombres": "Lead Sin",
                "apellidos": "Contacto",
                "nombre_completo": "Lead Sin Contacto",
                "telefono": "999111222",
                "email": None,
                "dni": None,
                "origen": "Web",
                "campana": None,
                "calidad": None,
                "intentos_contacto": 0,
                "tipo_cierre": None,
                "segunda_voz": None,
                "motivo_perdida": "No contesta",
                "motivo_perdida_otro": None,
                "fecha_ingreso": "2026-03-05 10:00:00",
                "fecha_ultimo_contacto": None,
                "estado_id": 6,
                "estado_nombre": "Perdido",
                "estado_color": "#ef4444",
                "fuente_id": 2,
                "fuente_nombre": "Web",
                "asesor_id": ASESOR_ID,
                "asesor_nombre": "Juan Asesor",
            }
        ],
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/leads-detalle?tipo_metrica=sin_contactar&fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1

    count_sql, _ = mock_db.executed_queries[0]
    assert "e.nombre = 'Nuevo'" not in count_sql
    assert "cambio_estado" in count_sql
    assert "NOT EXISTS (SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id" in count_sql


@pytest.mark.unit
def test_dashboard_resumen_excluye_cambio_estado(client, auth_headers_admin):
    """
    Verifica que /api/dashboard/resumen use contactado LATERAL JOIN y no 'WHERE e.nombre NOT IN (Nuevo)'.
    """
    fake_snapshot = {
        "total_leads": 100,
        "nuevos": 20,
        "contactados": 30,
        "calificados": 20,
        "tibios": 10,
        "calientes": 5,
        "en_negociacion": 10,
        "en_seguimiento": 5,
        "ganados": 5,
        "matriculas": 5,
        "perdidos": 10,
        "no_interesados": 5,
        "cod": 0,
        "leads_hoy": 2,
        "leads_7dias": 15,
        "tasa_conversion_pct": 5.0,
    }
    fake_flow = {
        "leads_creados": 10,
        "leads_contactados": 4,
        "nuevos": 6,
        "contactados": 2,
        "calificados": 2,
        "tibios": 1,
        "calientes": 1,
        "en_negociacion": 1,
        "en_seguimiento": 0,
        "leads_ganados": 1,
        "ganados": 1,
        "matriculas": 1,
        "perdidos": 1,
        "leads_perdidos": 1,
        "cod": 0,
        "tasa_conversion_pct": 10.0,
        "tasa_contactabilidad_pct": 40.0,
    }

    mock_db = MockDB(fetchone_data=[
        fake_snapshot,  # snapshot query
        fake_flow,      # period query
        fake_flow,      # prev_period query
    ])

    with patch("app.routers.dashboard.get_db", return_value=mock_db):
        res = client.get(
            "/api/dashboard/resumen?fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert "period_metrics" in data
    assert data["period_metrics"]["leads_contactados"] == 4

    # Verificar que las queries ejecutadas no usen e.nombre NOT IN ('Nuevo')
    found_period_query = False
    for sql, _ in mock_db.executed_queries:
        if "leads_contactados" in sql:
            found_period_query = True
            assert "WHERE e.nombre NOT IN ('Nuevo')" not in sql
            assert "WHERE lc.contactado IS NOT NULL" in sql
            assert "cambio_estado" in sql

    assert found_period_query, "No se encontró la consulta de leads_contactados en las ejecutadas"


@pytest.mark.unit
def test_ranking_asesores_filtro_fuente_nombre(client, auth_headers_admin):
    """
    Verifica que /api/reportes/ranking acepte ?fuente=Meta y lo aplique en la cláusula SQL
    dentro del LEFT JOIN de leads.
    """
    mock_db = MockDB(
        fetchall_data=[
            {
                "asesor_id": ASESOR_ID,
                "nombre_completo": "Juan Asesor",
                "rol": "asesor",
                "total_leads": 5,
                "leads_ganados": 1,
                "leads_calificados": 1,
                "leads_en_negociacion": 0,
                "leads_contactados": 4,
                "leads_sin_contactar": 1,
                "tasa_conversion_pct": 20.0,
                "tasa_contactabilidad_pct": 80.0,
            }
        ]
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking?fecha_desde=2026-03-01&fecha_hasta=2026-03-15&fuente=Meta",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert data["fuente"] == "Meta"
    assert len(data["ranking"]) == 1

    sql, params = mock_db.executed_queries[0]
    assert "crm.fuentes WHERE LOWER(nombre) = %s" in sql
    assert "meta" in params


@pytest.mark.unit
def test_ranking_asesores_filtro_fuente_sin_fuente(client, auth_headers_admin):
    """
    Verifica que /api/reportes/ranking acepte ?fuente=sin fuente y filtre por l.fuente_id IS NULL.
    """
    mock_db = MockDB(
        fetchall_data=[
            {
                "asesor_id": ASESOR_ID,
                "nombre_completo": "Juan Asesor",
                "rol": "asesor",
                "total_leads": 2,
                "leads_ganados": 0,
                "leads_calificados": 0,
                "leads_en_negociacion": 0,
                "leads_contactados": 1,
                "leads_sin_contactar": 1,
                "tasa_conversion_pct": 0.0,
                "tasa_contactabilidad_pct": 50.0,
            }
        ]
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking?fecha_desde=2026-03-01&fecha_hasta=2026-03-15&fuente=sin%20fuente",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert data["fuente"] == "sin fuente"
    sql, params = mock_db.executed_queries[0]
    assert "l.fuente_id IS NULL" in sql


@pytest.mark.unit
def test_ranking_equipos_filtro_fuente(client, auth_headers_admin):
    """
    Verifica que /api/reportes/ranking-equipos aplique el filtro por fuente en el JOIN de leads.
    """
    mock_db = MockDB(
        fetchall_data=[
            {
                "supervisor_id": ADMIN_ID,
                "supervisor_nombre": "Carlos Supervisor",
                "email": "sup@test.com",
                "num_asesores": 3,
                "team_size": 4,
                "total_leads": 12,
                "leads_ganados": 2,
                "leads_calificados": 2,
                "leads_en_negociacion": 1,
                "leads_contactados": 10,
                "leads_sin_contactar": 2,
                "tasa_conversion_pct": 16.67,
                "tasa_contactabilidad_pct": 83.3,
            }
        ]
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking-equipos?fecha_desde=2026-03-01&fecha_hasta=2026-03-15&fuente=TikTok",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    sql, params = mock_db.executed_queries[0]
    assert "crm.fuentes WHERE LOWER(nombre) = %s" in sql
    assert "tiktok" in params


@pytest.mark.unit
def test_exportar_ranking_con_fuente(client, auth_headers_admin):
    """
    Verifica que /api/reportes/exportar?tipo=ranking acepte fuente y genere un archivo Excel válido.
    """
    fake_ranking_data = {
        "ranking": [
            {
                "posicion": 1,
                "nombre_completo": "Juan Asesor",
                "rol": "asesor",
                "total_leads": 10,
                "leads_contactados": 8,
                "leads_calificados": 3,
                "leads_en_negociacion": 1,
                "leads_ganados": 2,
                "tasa_conversion_pct": 20.0,
                "tasa_contactabilidad_pct": 80.0,
            }
        ],
        "metrica": "matriculas",
        "fuente": "Meta",
    }

    with patch("app.routers.reportes.ranking_asesores", return_value=fake_ranking_data) as mock_rank:
        res = client.get(
            "/api/reportes/exportar?tipo=ranking&metrica=matriculas&fuente=Meta&fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    mock_rank.assert_called_once()
    assert mock_rank.call_args.kwargs.get("fuente") == "Meta"


@pytest.mark.unit
def test_ranking_asesores_con_fuente_excluida(client, auth_headers_admin):
    """
    Verifica que /api/reportes/ranking aplique la regla de excepción fuente_excluida
    en el WHERE/JOIN excluyendo la fuente indicada.
    """
    mock_db = MockDB(
        fetchall_data=[
            {
                "asesor_id": ASESOR_ID,
                "nombre_completo": "Juan Asesor",
                "rol": "asesor",
                "total_leads": 15,
                "leads_ganados": 3,
                "leads_calificados": 5,
                "leads_en_negociacion": 2,
                "leads_contactados": 12,
                "leads_sin_contactar": 3,
                "tasa_conversion_pct": 20.0,
                "tasa_contactabilidad_pct": 80.0,
            }
        ]
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking?fecha_desde=2026-03-01&fecha_hasta=2026-03-15&metrica=matriculas&fuente_excluida=Referidos",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert data.get("fuente_excluida") == "Referidos"
    sql, params = mock_db.executed_queries[0]
    assert "NOT IN (SELECT id FROM crm.fuentes WHERE LOWER(nombre) = %s)" in sql
    assert "referidos" in params


@pytest.mark.unit
def test_ranking_asesores_con_fuente_excluida_sin_fuente(client, auth_headers_admin):
    """
    Verifica que fuente_excluida='sin fuente' filtre leads con fuente_id IS NOT NULL.
    """
    mock_db = MockDB(fetchall_data=[])

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking?fecha_desde=2026-03-01&fecha_hasta=2026-03-15&fuente_excluida=sin fuente",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    sql, params = mock_db.executed_queries[0]
    assert "l.fuente_id IS NOT NULL" in sql


@pytest.mark.unit
def test_ranking_equipos_con_fuente_excluida(client, auth_headers_admin):
    """
    Verifica que /api/reportes/ranking-equipos aplique fuente_excluida en los JOINs.
    """
    mock_db = MockDB(
        fetchall_data=[
            {
                "supervisor_id": ADMIN_ID,
                "supervisor_nombre": "Carlos Supervisor",
                "email": "sup@test.com",
                "num_asesores": 2,
                "team_size": 3,
                "total_leads": 8,
                "leads_ganados": 1,
                "leads_calificados": 2,
                "leads_en_negociacion": 1,
                "leads_contactados": 6,
                "leads_sin_contactar": 2,
                "tasa_conversion_pct": 12.5,
                "tasa_contactabilidad_pct": 75.0,
            }
        ]
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/ranking-equipos?fecha_desde=2026-03-01&fecha_hasta=2026-03-15&fuente_excluida=Web,TikTok",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    data = res.json()
    assert data.get("fuente_excluida") == "Web,TikTok"
    sql, params = mock_db.executed_queries[0]
    assert "web" in params
    assert "tiktok" in params


@pytest.mark.unit
def test_leads_detalle_con_fuente_excluida(client, auth_headers_admin):
    """
    Verifica que /api/reportes/leads-detalle excluya las fuentes indicadas en WHERE.
    """
    mock_db = MockDB(
        fetchall_data=[
            [{"total": 5}],
            [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "nombres": "Ana",
                    "apellidos": "Gómez",
                    "nombre_completo": "Ana Gómez",
                    "telefono": "999888777",
                    "email": "ana@test.com",
                    "dni": "12345678",
                    "origen": "Meta",
                    "campana": "Campaña 1",
                    "calidad": "alta",
                    "intentos_contacto": 2,
                    "tipo_cierre": None,
                    "segunda_voz": None,
                    "motivo_perdida": None,
                    "motivo_perdida_otro": None,
                    "fecha_ingreso": "2026-03-02 10:00:00",
                    "fecha_ultimo_contacto": "2026-03-02 11:00:00",
                    "estado_id": 1,
                    "estado_nombre": "Nuevo",
                    "estado_color": "#3B82F6",
                    "fuente_id": 1,
                    "fuente_nombre": "Meta",
                    "asesor_id": ASESOR_ID,
                    "asesor_nombre": "Juan Asesor",
                }
            ],
        ],
        fetchone_data={"total": 5},
    )

    with patch("app.routers.reportes.get_db", return_value=mock_db):
        res = client.get(
            "/api/reportes/leads-detalle?fecha_desde=2026-03-01&fecha_hasta=2026-03-15&tipo_metrica=total&fuente_excluida=Referidos",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    sql, params = mock_db.executed_queries[0]
    assert "LOWER(COALESCE(f.nombre, '')) != %s" in sql
    assert "referidos" in params


@pytest.mark.unit
def test_exportar_ranking_con_fuente_excluida(client, auth_headers_admin):
    """
    Verifica que /api/reportes/exportar?tipo=ranking reciba y propague fuente_excluida.
    """
    fake_ranking_data = {
        "ranking": [
            {
                "posicion": 1,
                "nombre_completo": "Juan Asesor",
                "rol": "asesor",
                "total_leads": 10,
                "leads_contactados": 8,
                "leads_calificados": 3,
                "leads_en_negociacion": 1,
                "leads_ganados": 2,
                "tasa_conversion_pct": 20.0,
                "tasa_contactabilidad_pct": 80.0,
            }
        ],
        "metrica": "matriculas",
        "fuente": None,
        "fuente_excluida": "Organico",
    }

    with patch("app.routers.reportes.ranking_asesores", return_value=fake_ranking_data) as mock_rank:
        res = client.get(
            "/api/reportes/exportar?tipo=ranking&metrica=matriculas&fuente_excluida=Organico&fecha_desde=2026-03-01&fecha_hasta=2026-03-15",
            headers=auth_headers_admin,
        )

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    mock_rank.assert_called_once()
    assert mock_rank.call_args.kwargs.get("fuente_excluida") == "Organico"


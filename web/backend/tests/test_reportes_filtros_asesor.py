"""
Tests unitarios para el filtrado por asesor en reportes de Fuentes y Campañas.
"""
from unittest.mock import MagicMock, patch
import pytest
from app.auth.jwt import create_access_token

ADMIN_ID = "00000000-0000-0000-0000-000000000001"
ASESOR_ID = "00000000-0000-0000-0000-000000000003"


class MockReportesCursor:
    def __init__(self):
        self.executed_queries = []
        self.last_query = ""

    def execute(self, sql, params=None):
        self.last_query = sql.strip().lower()
        self.executed_queries.append((sql, params))

    def fetchall(self):
        if "primer_c" in self.last_query:
            return [
                {
                    "campana": "Campaña Verano",
                    "fuente": "Facebook",
                    "total_leads": 5,
                    "leads_contactados": 4,
                    "leads_calificados": 3,
                    "leads_ganados": 1,
                    "leads_perdidos": 0,
                    "pct_contactados": 80.0,
                    "pct_calificados": 60.0,
                    "pct_ganados": 20.0,
                    "horas_primer_contacto": 1.5,
                }
            ]
        if "crm.fuentes" in self.last_query:
            return [
                {
                    "fuente": "Facebook",
                    "total_leads": 10,
                    "leads_contactados": 8,
                    "leads_calificados": 5,
                    "leads_en_negociacion": 3,
                    "leads_ganados": 2,
                    "leads_perdidos": 1,
                    "tasa_conversion_pct": 20.0,
                    "tasa_contactabilidad_pct": 80.0,
                }
            ]
        return []

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class MockReportesConn:
    def __init__(self):
        self.cursor_mock = MockReportesCursor()

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


@pytest.fixture
def mock_reportes_db():
    conn = MockReportesConn()
    with patch("app.routers.reportes.get_db", return_value=conn):
        yield conn


@pytest.mark.unit
def test_por_fuente_sin_asesor(client, auth_headers_admin, mock_reportes_db):
    """Verifica que /api/reportes/por-fuente sin asesor no agregue filtro de asesor_id."""
    res = client.get("/api/reportes/por-fuente?fecha_desde=2026-01-01&fecha_hasta=2026-01-31", headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert len(data["rows"]) == 1
    assert data["rows"][0]["fuente"] == "Facebook"

    queries = mock_reportes_db.cursor_mock.executed_queries
    sql, params = queries[-1]
    assert "l.asesor_id = %s::uuid" not in sql
    assert ASESOR_ID not in params


@pytest.mark.unit
def test_por_fuente_con_asesor(client, auth_headers_admin, mock_reportes_db):
    """Verifica que /api/reportes/por-fuente con asesor_id inyecte la condición en el WHERE."""
    res = client.get(
        f"/api/reportes/por-fuente?fecha_desde=2026-01-01&fecha_hasta=2026-01-31&asesor_id={ASESOR_ID}",
        headers=auth_headers_admin,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["rows"]) == 1

    queries = mock_reportes_db.cursor_mock.executed_queries
    sql, params = queries[-1]
    assert "l.asesor_id = %s::uuid" in sql
    assert ASESOR_ID in params


@pytest.mark.unit
def test_campanas_sin_asesor(client, auth_headers_admin, mock_reportes_db):
    """Verifica que /api/reportes/campanas sin asesor use HAVING >= 5 y sin filtro de asesor."""
    res = client.get("/api/reportes/campanas?fecha_desde=2026-01-01&fecha_hasta=2026-01-31", headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert len(data["rows"]) == 1

    queries = mock_reportes_db.cursor_mock.executed_queries
    sql, params = queries[-1]
    assert "l.asesor_id = %s::uuid" not in sql
    assert "having count(l.id) >= 5" in sql.lower()
    assert ASESOR_ID not in params


@pytest.mark.unit
def test_campanas_con_asesor(client, auth_headers_admin, mock_reportes_db):
    """Verifica que /api/reportes/campanas con asesor_id use HAVING >= 1 y filtre por asesor_id."""
    res = client.get(
        f"/api/reportes/campanas?fecha_desde=2026-01-01&fecha_hasta=2026-01-31&asesor_id={ASESOR_ID}",
        headers=auth_headers_admin,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["rows"]) == 1

    queries = mock_reportes_db.cursor_mock.executed_queries
    sql, params = queries[-1]
    assert "l.asesor_id = %s::uuid" in sql
    assert "having count(l.id) >= 1" in sql.lower()
    assert ASESOR_ID in params

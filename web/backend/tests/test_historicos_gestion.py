import pytest
from unittest.mock import MagicMock, patch

ADMIN_ID = "00000000-0000-0000-0000-000000000001"
ASESOR_ID = "00000000-0000-0000-0000-000000000003"


class MockHistoricosCursor:
    def __init__(self):
        self.executed = []
        self.last_query = ""

    def execute(self, sql, params=None):
        self.last_query = sql.strip().lower()
        self.executed.append((sql, params))

    def fetchone(self):
        if "telefonos_unicos" in self.last_query and "asignados_crm" in self.last_query:
            return {
                "total": 5000,
                "telefonos_unicos": 4800,
                "proyectos": 12,
                "asignados_crm": 150,
                "no_registrados": 20,
            }
        if "count(*) as total" in self.last_query:
            return {"total": 2}
        if "from crm.fuentes" in self.last_query or "insert into crm.fuentes" in self.last_query:
            return {"id": 99, "nombre": "Historico"}
        if "from crm.estados_lead" in self.last_query:
            return {"id": 1, "nombre": "Nuevo"}
        if "for update" in self.last_query:
            return {
                "id": 1,
                "nombre": "Carlos Mendoza",
                "telefono": "+51987654321",
                "telefono_norm": "+51987654321",
                "email": "carlos@example.com",
                "dni": "45678912",
                "proyecto": "Residencial Sol",
                "canal": "Facebook",
                "asesor_id": None,
                "asesor_nombre": None,
                "estado": "Nuevo",
                "observaciones": "Nota",
                "ciudad": "Lima",
                "fecha_ingreso": "2025-10-15",
                "fecha_creacion": "2025-10-15",
                "fecha_asignacion": None,
                "fecha_ultimo_contacto": None,
                "lead_crm_id": None,
            }
        if "insert into crm.leads" in self.last_query or "update crm.leads" in self.last_query:
            return {"id": 101}
        if "from crm.leads" in self.last_query:
            return None
        if "from crm_legacy.leads_historico h" in self.last_query:
            return None
        if "auth.users" in self.last_query:
            return {"id": ASESOR_ID, "nombre": "Asesor Test"}
        if "cargas_historico_historial" in self.last_query and "where id =" in self.last_query:
            return {
                "id": 1,
                "uploaded_by_nombre": "Admin Test",
                "filename": "historicos.xlsx",
                "total_rows": 10,
                "inserted": 8,
                "duplicates": 1,
                "promoted_to_crm": 0,
                "errors": 1,
                "uploaded_at": None,
                "duplicates_details": [{"row": 2, "telefono": "+51987654321", "motivo": "Duplicado en CRM"}],
                "error_details": [{"row": 3, "telefono": "", "error": "Teléfono inválido"}],
            }
        if "insert into crm_legacy.leads_historico" in self.last_query:
            return {
                "id": 1,
                "nombre": "Carlos Mendoza",
                "telefono": "+51987654321",
                "email": "carlos@example.com",
                "dni": "45678912",
                "proyecto": "Residencial Sol",
                "canal": "Facebook",
                "asesor_id": ASESOR_ID,
                "asesor_nombre": "Asesor Test",
                "estado": "Nuevo",
                "ciudad": "Lima",
                "fecha_ingreso": "2025-10-15",
                "origen_tabla": "individual",
            }
        if "from crm.leads" in self.last_query:
            return None
        return {"total": 0}

    def fetchall(self):
        if "as mes" in self.last_query:
            return [
                {"mes": "2026-08", "count": 15},
                {"mes": "2026-07", "count": 25},
            ]
        if "select distinct proyecto from crm_legacy.leads_historico" in self.last_query:
            return [{"proyecto": "Proyecto Alfa"}]
        if "select distinct canal from crm_legacy.leads_historico" in self.last_query:
            return [{"canal": "Facebook"}]
        if "select distinct estado from crm_legacy.leads_historico" in self.last_query:
            return [{"estado": "Historico"}]
        if "auth.users" in self.last_query:
            return [{"id": ASESOR_ID, "nombre": "Asesor Test", "email": "asesor@test.local", "role": "asesor"}]
        if "select distinct telefono_norm from crm_legacy.leads_historico" in self.last_query:
            return []
        if "select\n                    h.id, h.nombre" in self.last_query or "select h.id, h.nombre" in self.last_query or "from crm_legacy.leads_historico h" in self.last_query:
            return [
                {
                    "id": 1,
                    "nombre": "Carlos Mendoza",
                    "telefono": "+51987654321",
                    "email": "carlos@example.com",
                    "dni": "45678912",
                    "proyecto": "Residencial Sol",
                    "canal": "Facebook",
                    "asesor_id": ASESOR_ID,
                    "asesor_nombre": "Asesor Test",
                    "estado": "Nuevo",
                    "seguimiento": None,
                    "observaciones": "Trabajo: Ingeniero civil | Referido por: Juan Perez",
                    "ciudad": "Lima",
                    "fecha_ingreso": "2025-10-15",
                    "origen_tabla": "individual",
                }
            ]
        return []

    @property
    def rowcount(self):
        return 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockHistoricosConn:
    def __init__(self):
        self.cur = MockHistoricosCursor()

    def cursor(self, **kwargs):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def mock_historicos_db(monkeypatch):
    conn = MockHistoricosConn()
    monkeypatch.setattr("app.routers.historicos.get_db", lambda: conn)
    return conn


@pytest.mark.unit
def test_historicos_admin_only_access(client, auth_headers_admin, auth_headers_asesor, auth_headers_supervisor, mock_historicos_db):
    """Verifica que solo los usuarios administradores puedan acceder al router de Históricos."""
    # Asesor -> 403
    res_asesor = client.get("/api/historicos", headers=auth_headers_asesor)
    assert res_asesor.status_code == 403

    # Supervisor -> 403
    res_sup = client.get("/api/historicos", headers=auth_headers_supervisor)
    assert res_sup.status_code == 403

    # Admin -> 200
    res_admin = client.get("/api/historicos", headers=auth_headers_admin)
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert "items" in data
    assert "total" in data
    assert data["page_size"] == 50


@pytest.mark.unit
def test_create_lead_historico_with_full_lead_fields(client, auth_headers_admin, mock_historicos_db):
    """Prueba la creación individual de un lead histórico con todos los campos de NuevoLead."""
    payload = {
        "nombres": "Carlos",
        "apellidos": "Mendoza",
        "telefono": "987654321",
        "email": "carlos@example.com",
        "tipo_documento": "DNI",
        "dni": "45678912",
        "campana": "Residencial Sol",
        "fuente_id": 1,
        "estado_id": 1,
        "ciudad": "Lima",
        "trabajo": "Ingeniero civil",
        "referido_por": "Juan Perez",
        "asesor_id": ASESOR_ID,
        "observaciones": "Cliente antiguo de feria 2025",
        "fecha_ingreso": "2025-10-15",
    }
    res = client.post("/api/historicos", json=payload, headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert data["message"] == "Lead histórico creado exitosamente"
    assert data["lead"]["telefono"] == "+51987654321"


@pytest.mark.unit
def test_historicos_desglose_meses(client, auth_headers_admin, mock_historicos_db):
    """Prueba el endpoint de desglose por meses /api/historicos/meses."""
    res = client.get("/api/historicos/meses", headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert "meses" in data
    assert len(data["meses"]) >= 2
    assert data["meses"][0]["mes"] == "2026-08"
    assert "Agosto 2026" in data["meses"][0]["label"]


@pytest.mark.unit
def test_historicos_reasignar(client, auth_headers_admin, mock_historicos_db):
    """Prueba la reasignación de leads históricos a un asesor activo."""
    payload = {
        "lead_ids": [1, 2, 3],
        "asesor_id": ASESOR_ID,
    }
    res = client.post("/api/historicos/reasignar", json=payload, headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["updated"] == 3
    assert data["asesor_nombre"] == "Asesor Test"


@pytest.mark.unit
def test_historicos_desasignar(client, auth_headers_admin, mock_historicos_db):
    """Prueba quitar la asignación de leads históricos para dejarlos esperando reasignación."""
    payload = {
        "lead_ids": [1, 2],
        "asesor_id": "unassign",
    }
    res = client.post("/api/historicos/reasignar", json=payload, headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["updated"] == 2
    assert data["asesor_nombre"] == "Sin asesor"
    assert "removió" in data["message"].lower() or "quitó" in data["message"].lower() or "espera" in data["message"].lower()


@pytest.mark.unit
def test_historicos_plantilla_download(client, auth_headers_admin):
    """Prueba la descarga de la plantilla Excel para carga masiva de históricos."""
    res = client.get("/api/historicos/plantilla", headers=auth_headers_admin)
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument" in res.headers["content-type"]


@pytest.mark.unit
def test_promote_historico_assigns_fuente_historico(mock_historicos_db):
    """Verifica que al promover/asignar un lead de histórico a crm.leads, se asigne la fuente 'Historico'."""
    from app.routers.historicos import _promote_historico_to_crm
    cur = mock_historicos_db.cursor()
    crm_id = _promote_historico_to_crm(cur, 1, ASESOR_ID, "Asesor Test")
    assert crm_id == 101

    lead_inserts = [
        (sql, params) for sql, params in cur.executed
        if "insert into crm.leads" in sql.lower()
    ]
    assert len(lead_inserts) == 1
    sql, params = lead_inserts[0]
    # params[0] es fuente_id, que debe corresponder a la fuente 'Historico' (99 en mock)
    assert params[0] == 99


@pytest.mark.unit
def test_historicos_cargas_historial_detalles(client, auth_headers_admin, mock_historicos_db):
    """Prueba el endpoint de detalles de historial de carga de históricos."""
    res = client.get("/api/historicos/cargas-historial/1/detalles", headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == 1
    assert "duplicates_details" in data
    assert "error_details" in data
    assert len(data["duplicates_details"]) == 1
    assert len(data["error_details"]) == 1


@pytest.mark.unit
def test_historicos_stats(client, auth_headers_admin, mock_historicos_db):
    """Prueba que el endpoint /api/historicos/stats devuelva asignados_crm correctamente."""
    res = client.get("/api/historicos/stats", headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5000
    assert data["asignados_crm"] == 150
    assert data["telefonos_unicos"] == 4800







import json
from unittest.mock import patch, MagicMock
import pytest
from app.auth.jwt import create_access_token
from app.routers.carga_masiva import _FakeConn

# UUIDs correspondientes a MockCursor
ADMIN_ID = "00000000-0000-0000-0000-000000000001"
SUPERVISOR_ID = "00000000-0000-0000-0000-000000000002"
ASESOR_JUAN_ID = "00000000-0000-0000-0000-000000000003"
ASESOR_MARIA_ID = "00000000-0000-0000-0000-000000000004"


class MockCursor:
    def __init__(self, current_user_role="admin"):
        self.current_user_role = current_user_role
        self.executed_queries = []
        self.last_query = ""

    def execute(self, sql, params=None):
        self.last_query = sql.strip().lower()
        self.executed_queries.append((sql, params))

    def fetchone(self):
        if "crm.estados_lead" in self.last_query:
            return {"id": 10}
        if "crm.carga_masiva_historial" in self.last_query and "where id =" in self.last_query:
            return {
                "id": 1,
                "uploaded_by_nombre": "Admin User",
                "filename": "test.csv",
                "total_rows": 2,
                "inserted": 1,
                "duplicates": 1,
                "errors": 0,
                "uploaded_at": None,
                "duplicates_details": [{"row": 2, "telefono": "987654321", "motivo": "Duplicado"}],
                "error_details": [],
            }
        return None

    def fetchall(self):
        if "crm.fuentes" in self.last_query:
            return [{"id": 1, "nombre": "activacion"}]
        elif "auth.users" in self.last_query and "is_active = true" in self.last_query:
            if "crm.equipos" in self.last_query:
                # Si es la consulta de equipos para supervisor, devolver Juan Perez y el supervisor mismo
                return [
                    {"id": SUPERVISOR_ID},
                    {"id": ASESOR_JUAN_ID}
                ]
            else:
                return [
                    {"id": SUPERVISOR_ID, "nombre": "Supervisor Test", "email": "supervisor@test.local"},
                    {"id": ASESOR_JUAN_ID, "nombre": "Juan Perez", "email": "juan@test.local"},
                    {"id": ASESOR_MARIA_ID, "nombre": "Maria Lopez", "email": "maria@test.local"},
                ]
        elif "crm.catalogo_calidad" in self.last_query:
            return [("FRIO", "FRIO"), ("TIBIO", "TIBIO"), ("CALIENTE", "CALIENTE")]
        elif "crm.sedes" in self.last_query:
            return [{"id": "00000000-0000-0000-0000-000000000099", "codigo": "arequipa", "nombre": "Arequipa"}]
        elif "select distinct telefono from crm.leads" in self.last_query:
            return []
        return []

    @property
    def rowcount(self):
        return 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class MockConn:
    def __init__(self, current_user_role="admin"):
        self.cursor_mock = MockCursor(current_user_role)

    def cursor(self, **k):
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
def mock_get_db(monkeypatch):
    conn = MockConn()
    monkeypatch.setattr("app.routers.carga_masiva.get_db", lambda: conn)
    return conn


@pytest.mark.unit
@patch("app.routers.carga_masiva._parse_file")
def test_preview_validated_with_asesor_valid_resolves(mock_parse, client, auth_headers_admin, mock_get_db):
    """Prueba que el dry-run resuelva un asesor existente por nombre."""
    mock_parse.return_value = (
        ['telefono', 'nombres', 'asesor'],
        [{'telefono': '987654321', 'nombres': 'Carlos', 'asesor': 'Juan Perez'}]
    )

    column_map = {"telefono": "telefono", "nombres": "nombres", "asesor": "asesor"}
    payload = {
        "column_map": json.dumps(column_map)
    }

    files = {
        "file": ("test.csv", b"dummy content", "text/csv")
    }

    res = client.post(
        "/api/leads/carga-masiva/preview-validated",
        headers=auth_headers_admin,
        data=payload,
        files=files
    )

    assert res.status_code == 200
    data = res.json()
    assert data["summary"]["valid"] == 1
    assert data["summary"]["errors"] == 0
    assert data["rows"][0]["status"] == "valid"
    assert data["rows"][0]["asesor"] == "Juan Perez"


@pytest.mark.unit
@patch("app.routers.carga_masiva._parse_file")
def test_preview_validated_with_asesor_invalid_returns_error(mock_parse, client, auth_headers_admin, mock_get_db):
    """Prueba que el dry-run marque error si el asesor no existe."""
    mock_parse.return_value = (
        ['telefono', 'nombres', 'asesor'],
        [{'telefono': '987654321', 'nombres': 'Carlos', 'asesor': 'Asesor Inexistente'}]
    )

    column_map = {"telefono": "telefono", "nombres": "nombres", "asesor": "asesor"}
    payload = {
        "column_map": json.dumps(column_map)
    }

    files = {
        "file": ("test.csv", b"dummy content", "text/csv")
    }

    res = client.post(
        "/api/leads/carga-masiva/preview-validated",
        headers=auth_headers_admin,
        data=payload,
        files=files
    )

    assert res.status_code == 200
    data = res.json()
    assert data["summary"]["valid"] == 0
    assert data["summary"]["errors"] == 1
    assert data["rows"][0]["status"] == "error"
    assert "no reconocido o inactivo" in data["rows"][0]["errors"][0]


@pytest.mark.unit
@patch("app.routers.carga_masiva._parse_file")
def test_preview_validated_supervisor_scope(mock_parse, client, auth_headers_supervisor, mock_get_db):
    """Prueba que un supervisor solo pueda asignar a asesores de su propio equipo."""
    # 1. Asesor permitido (Juan Perez)
    mock_parse.return_value = (
        ['telefono', 'nombres', 'asesor'],
        [{'telefono': '987654321', 'nombres': 'Carlos', 'asesor': 'Juan Perez'}]
    )
    column_map = {"telefono": "telefono", "nombres": "nombres", "asesor": "asesor"}
    payload = {"column_map": json.dumps(column_map)}
    files = {"file": ("test.csv", b"dummy content", "text/csv")}

    res = client.post(
        "/api/leads/carga-masiva/preview-validated",
        headers=auth_headers_supervisor,
        data=payload,
        files=files
    )
    assert res.json()["summary"]["valid"] == 1

    # 2. Asesor no permitido (Maria Lopez no está en su equipo)
    mock_parse.return_value = (
        ['telefono', 'nombres', 'asesor'],
        [{'telefono': '987654322', 'nombres': 'Ana', 'asesor': 'Maria Lopez'}]
    )
    res = client.post(
        "/api/leads/carga-masiva/preview-validated",
        headers=auth_headers_supervisor,
        data=payload,
        files=files
    )
    assert res.json()["summary"]["errors"] == 1
    assert "no está dentro de tu equipo permitido" in res.json()["rows"][0]["errors"][0]


@pytest.mark.unit
@patch("app.routers.carga_masiva._parse_file")
def test_importar_assigns_correct_asesor_id_and_fallback(mock_parse, client, auth_headers_admin, mock_get_db):
    """Prueba la asignación per-fila y el fallback en el endpoint de importación real."""
    mock_parse.return_value = (
        ['telefono', 'nombres', 'asesor'],
        [
            {'telefono': '987654321', 'nombres': 'Carlos', 'asesor': 'Juan Perez'},
            {'telefono': '987654322', 'nombres': 'Ana', 'asesor': ''}  # Debe usar fallback
        ]
    )

    column_map = {"telefono": "telefono", "nombres": "nombres", "asesor": "asesor"}
    payload = {
        "column_map": json.dumps(column_map),
        "target_asesor_id": ASESOR_MARIA_ID  # fallback
    }

    files = {
        "file": ("test.csv", b"dummy content", "text/csv")
    }

    res = client.post(
        "/api/leads/carga-masiva",
        headers=auth_headers_admin,
        data=payload,
        files=files
    )

    assert res.status_code == 200
    data = res.json()
    assert data["inserted"] == 2
    assert data["errors"] == 0

    # Verificar las inserciones ejecutadas en base_payload / cursor
    queries = mock_get_db.cursor_mock.executed_queries
    insert_params = [params for sql, params in queries if "insert into crm.leads" in sql.lower()]
    assert len(insert_params) == 2

    # Carlos: asignado a Juan Perez
    assert insert_params[0][13] == ASESOR_JUAN_ID
    # Ana: asignada a Maria Lopez (fallback)
    assert insert_params[1][13] == ASESOR_MARIA_ID


@pytest.mark.unit
def test_carga_masiva_historial_detalles(client, auth_headers_admin, mock_get_db):
    """Prueba el endpoint de detalles estructurados de historial de carga masiva."""
    res = client.get("/api/leads/carga-masiva/historial/1/detalles", headers=auth_headers_admin)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == 1
    assert "duplicates_details" in data
    assert "error_details" in data
    assert len(data["duplicates_details"]) == 1


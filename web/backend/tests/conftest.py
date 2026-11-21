"""
Fixtures globales de pytest para la suite de tests del CRM.

Estrategia: todos los tests corren con `demo_mode=True`, lo que evita
requerir una base de datos real y permite ejecutarlos en CI sin
infraestructura.

Los endpoints que tocan la DB se mockearán por test cuando sea
necesario, usando monkeypatch sobre `app.database.get_db` o sobre
funciones específicas del router.
"""
import os
import sys
import pytest

# Variables de entorno necesarias ANTES de importar la app
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-pytest-min-32-chars-long")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")

# Asegura que `app` sea importable cuando pytest se ejecuta desde `web/backend/`
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


@pytest.fixture(scope="session")
def app_instance():
    """Instancia única de la app FastAPI para toda la sesión de tests."""
    from app.main import app
    return app


@pytest.fixture()
def client(app_instance):
    """TestClient de FastAPI — un cliente nuevo por test para aislar estado."""
    from fastapi.testclient import TestClient
    with TestClient(app_instance) as c:
        yield c


@pytest.fixture()
def auth_token_admin():
    """Genera un JWT válido con rol admin para tests autenticados."""
    from app.auth.jwt import create_access_token
    return create_access_token({
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "admin@test.local",
        "role": "admin",
    })


@pytest.fixture()
def auth_token_supervisor():
    """Genera un JWT válido con rol supervisor."""
    from app.auth.jwt import create_access_token
    return create_access_token({
        "sub": "00000000-0000-0000-0000-000000000002",
        "email": "supervisor@test.local",
        "role": "supervisor",
    })


@pytest.fixture()
def auth_token_asesor():
    """Genera un JWT válido con rol asesor."""
    from app.auth.jwt import create_access_token
    return create_access_token({
        "sub": "00000000-0000-0000-0000-000000000003",
        "email": "asesor@test.local",
        "role": "asesor",
    })


@pytest.fixture()
def auth_headers_admin(auth_token_admin):
    return {"Authorization": f"Bearer {auth_token_admin}"}


@pytest.fixture()
def auth_headers_supervisor(auth_token_supervisor):
    return {"Authorization": f"Bearer {auth_token_supervisor}"}


@pytest.fixture()
def auth_headers_asesor(auth_token_asesor):
    return {"Authorization": f"Bearer {auth_token_asesor}"}

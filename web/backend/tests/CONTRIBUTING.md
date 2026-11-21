# Guía de testing — CRM Palma Río

Estándares profesionales para escribir y mantener tests en el backend.
Aplicar SIEMPRE al agregar tests nuevos o modificar existentes.

## 1. Filosofía

> Los tests sirven para dar **confianza** al refactorear y desplegar.
> Un test que no falla cuando el código rompe NO sirve.
> Un test que falla sin que el código rompa (flaky) DESTRUYE confianza.

Tres reglas inviolables:

1. **Determinístico**: el test debe pasar (o fallar) siempre por la misma razón.
2. **Aislado**: cada test corre solo, no depende de otros.
3. **Rápido**: si tarda >5s, va marcado `@pytest.mark.slow` (excluido en CI rápido).

## 2. Naming convention

Patrón obligatorio:

```python
def test_<componente>_<escenario>_<resultado_esperado>():
    ...
```

Ejemplos buenos:

```python
def test_login_with_valid_credentials_returns_token():
def test_login_with_wrong_password_returns_401():
def test_update_user_as_non_admin_returns_403():
def test_role_change_to_admin_by_supervisor_is_forbidden():
```

Ejemplos malos (rechazados en review):

```python
def test_login():                        # vago
def test_login_works():                  # qué significa "works"?
def test1():                             # ilegible
def test_TC_001_login_validation():      # no es test case ID, es comportamiento
```

## 3. Patrón AAA (Arrange, Act, Assert)

Cada test tiene 3 secciones claras, separadas con línea en blanco:

```python
def test_login_with_wrong_password_returns_401(client, mock_db_user):
    # Arrange — setup del escenario
    mock_db_user(email="ana@palma.com", password="correcta")

    # Act — ejecutar la acción bajo prueba
    response = client.post("/auth/login", json={
        "email": "ana@palma.com",
        "password": "incorrecta",
    })

    # Assert — verificar resultado
    assert response.status_code == 401
    assert response.json()["detail"] == "Credenciales incorrectas"
```

Si un test mezcla las 3 secciones sin separarlas, refactorizar.

## 4. Markers

Registrados en `pytest.ini`. Usar siempre uno (o más) por test:

| Marker | Cuándo usar |
|---|---|
| `@pytest.mark.unit` | Test unitario puro (función aislada, sin DB ni HTTP). |
| `@pytest.mark.auth` | Tests del módulo de autenticación. |
| `@pytest.mark.leads` | Tests del módulo de leads. |
| `@pytest.mark.ingest` | Tests del endpoint multi-tenant `/api/ingest/leads`. |
| `@pytest.mark.integration` | Requiere DB real o servicios externos. Excluido en CI rápido. |
| `@pytest.mark.slow` | Tarda >5s. Excluido en CI rápido. |
| `@pytest.mark.regression` | Test de bug arreglado. **Obligatorio incluir Bug ID en docstring**. |

Ejemplo combinado:

```python
@pytest.mark.auth
@pytest.mark.regression
def test_session_expiration_does_not_leak_to_next_user():
    """Bug ID: V070.81 — sesión vieja se mostraba al siguiente login en el mismo device."""
    ...
```

## 5. Mock policy

**Mockear:** SOLO el sistema externo (DB, HTTP outbound, filesystem).

```python
# Bien — mockea la capa externa (DB)
def test_login_calls_password_hash_check(monkeypatch):
    mock_user = {"id": "...", "password_hash": "...", "is_active": True, ...}
    monkeypatch.setattr("app.auth.router.get_db", _fake_db_returning(mock_user))
    ...
```

**NO mockear:** lógica interna del código bajo prueba.

```python
# Mal — mockea la función que estás testeando
def test_login_returns_token(monkeypatch):
    monkeypatch.setattr("app.auth.router.login", lambda x: {"token": "fake"})  # ❌ no testea nada
    ...
```

Si necesitás mockear demasiado, el código probablemente está mal acoplado.
Refactorizar antes de mockear más.

## 6. Fixtures

### Globales (`tests/conftest.py`)

Disponibles en TODOS los tests. Para infraestructura general:
- `client` — TestClient de FastAPI
- `auth_token_admin`, `auth_token_supervisor`, `auth_token_asesor` — JWT por rol
- `app_instance` — instancia de la app

### Por dominio (`tests/<dominio>/conftest.py`)

Específicas de un módulo. Ej: `tests/auth/conftest.py` tiene fixtures de auth.

### Factories (`tests/fixtures/`)

Helpers reutilizables para crear test data. Patrón factory:

```python
from tests.fixtures import make_user, make_lead

# make_user con overrides
user = make_user(email="ana@palma.com", role="admin")
# {"id": "uuid-fake", "email": "ana@palma.com", "role": "admin", "is_active": True, ...}
```

NO hardcodear payloads en cada test. Si lo haces 3 veces, factorizar.

## 7. Estructura de carpetas

Tests organizados por dominio:

```
tests/
├── conftest.py                  # fixtures globales
├── CONTRIBUTING.md              # este archivo
├── fixtures/                    # factory helpers
│   └── __init__.py
├── auth/                        # tests del módulo auth
│   ├── conftest.py             # fixtures de auth
│   ├── test_jwt.py
│   ├── test_login.py
│   ├── test_me.py
│   ├── test_users_crud.py
│   └── test_roles.py
├── leads/                       # tests del módulo leads (futuro)
├── ingest/                      # tests del módulo ingest (futuro)
└── ... otros tests legacy mientras se reorganizan
```

## 8. Coverage targets (objetivos por módulo)

| Módulo | Target | Razón |
|---|---|---|
| `app/auth/` | 80% | Puerta de entrada — si rompe, todo cae |
| `app/services/lead_routing.py` | 70% | Asignación crítica |
| `app/services/notification_coalescer.py` | 70% | Spam control de pushes |
| `app/routers/ingest.py` | 75% | Entrada de leads multi-tenant |
| `app/services/webhook_service.py` | 70% | Outbound a proveedores |
| Resto | 50% | Coverage decente |
| **Global** | **50%** | Meta a 3 meses |

CI rechaza PRs que bajen coverage global por debajo del threshold actual.

## 9. Antes de pushear

```bash
cd web/backend
ruff check app/ tests/                     # lint pasa
python -m pytest tests/ -q --tb=short      # tests pasan
python -m pytest tests/ --cov=app          # coverage no baja
```

El pre-push hook hace lint automático; para tests + coverage es manual.

## 10. Anti-patrones (rechazados en review)

- ❌ Tests que tocan internet (sin marker `integration`)
- ❌ Tests que dependen del orden (un test pasa solo si otro corrió antes)
- ❌ Tests con `time.sleep(N)` — usar mock de tiempo (`freezegun`) o eventos
- ❌ Tests sin assert (`response = client.get(...)` y nada más)
- ❌ Mockear lo que se testea (over-mocking, ver §5)
- ❌ Cambiar tests para que pasen sin entender por qué rompían
- ❌ Marcar como `xfail` o `skip` sin razón documentada con Bug ID

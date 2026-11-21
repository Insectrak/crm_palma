# Plataforma CRM — Portal Web

> Backend FastAPI + Frontend React (Vite + Tailwind) del CRM multi-industria.

Para la documentación completa del proyecto (arquitectura, reglas de
trabajo, deploy, integraciones, modelo de datos), ver
[CLAUDE.md](../CLAUDE.md) en la raíz del repo.

---

## Setup Local — Backend

```bash
cd web/backend

# 1. Entorno virtual e instalar dependencias
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

pip install -r requirements-dev.txt

# 2. Variables de entorno
cp .env.example .env
# Editar .env con los valores reales (DATABASE_URL, SECRET_KEY, etc.)

# 3. Servidor de desarrollo
uvicorn app.main:app --reload --port 8000
```

La API queda en http://localhost:8000 — docs interactivos en
http://localhost:8000/docs.

Las migraciones SQL se aplican solas al arrancar (ver
[`app/db_migrator.py`](backend/app/db_migrator.py)). El primer usuario
admin se crea desde la pantalla Setup del frontend (`/setup`).

---

## Setup Local — Frontend

```bash
cd web/frontend

npm install
cp .env.example .env             # VITE_API_URL apunta a http://localhost:8000 por default
npm run dev
```

La SPA queda en http://localhost:5173.

---

## Tests

```bash
# Backend
cd web/backend
pytest -q                                                # rápido, DEMO_MODE
pytest --cov=app --cov-report=term-missing --cov-fail-under=39

# Frontend
cd web/frontend
npm run test                     # vitest
npm run lint                     # eslint
```

---

## Variables de Entorno

### Backend (`web/backend/.env`)

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | Cadena de conexión PostgreSQL (`postgresql://user:<password>@host:5432/db`) |
| `SECRET_KEY` | Clave secreta para JWT (mínimo 32 caracteres) |
| `ALGORITHM` | Algoritmo JWT (default: HS256) |
| `ACCESS_TOKEN_EXPIRE_HOURS` | Expiración del token (default: 8) |
| `ALLOWED_ORIGINS` | Orígenes CORS permitidos (separados por coma) |
| `FCM_ENABLED` | `true` para activar push notifications |
| `FCM_SERVICE_ACCOUNT_B64` | Service account FCM en base64 |
| `INGEST_API_KEY` | API key para ingest legacy de n8n (modo multi-tenant usa `cli_*`) |

Ver [CLAUDE.md](../CLAUDE.md#credenciales) para la lista completa por
servicio.

### Frontend (`web/frontend/.env`)

| Variable | Descripción |
|---|---|
| `VITE_API_URL` | URL del backend FastAPI (default: `http://localhost:8000`) |

---

## Deploy

El CRM se despliega **por cliente** en servidores separados (Hetzner +
EasyPanel self-hosted). Cada cliente tiene su propio dominio canónico y
su propia base de datos. EasyPanel detecta el push a la branch de
release del cliente y permite redeploy con el botón **Implementar**.

| Cliente / entorno | Release branch | EasyPanel |
|---|---|---|
| Palma del Río (prod) | `release/palma-prod` | EasyPanel del cliente |
| Lab (dev) | `release/lab-dev` | EasyPanel Lab |

Detalles completos en [CLAUDE.md — URLs y Servicios](../CLAUDE.md#urls-y-servicios-multi-tenant)
y [docs/runbooks/](../docs/runbooks/).

---

## Estructura del módulo

```
web/
├── backend/                  # FastAPI + psycopg2
│   ├── app/
│   │   ├── main.py                  # Entry point + CORS + routers
│   │   ├── config.py                # Settings (pydantic-settings)
│   │   ├── database.py              # Pool de conexiones
│   │   ├── db_migrator.py           # Auto-apply migrations al startup
│   │   ├── auth/                    # Login, JWT, sesiones
│   │   ├── routers/                 # leads, dashboard, agenda, …
│   │   └── services/                # Lógica de negocio
│   ├── migrations/                  # DDL versionado V0NN_*.sql
│   ├── tests/
│   ├── docs_static/                 # Doc pública de la API de ingest
│   └── requirements*.txt
├── frontend/                 # React + Vite + Tailwind
│   └── src/
│       ├── pages/                   # Login, Dashboard, Leads, …
│       ├── components/
│       ├── store/                   # Zustand
│       └── lib/                     # api.js (axios) + utils
├── Dockerfile                # Imagen unificada backend + frontend
├── docker-compose.yml
└── docker-compose.cert.yml   # Entorno de certificación
```

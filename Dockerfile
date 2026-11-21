# ============================================================
# Dockerfile (raiz del repo) — Build "clase mundial" para deploy
# automatico desde EasyPanel/GitHub.
#
# Diferencia vs web/Dockerfile (que se mantiene para
# docker-compose.standalone): este copia tambien database/ y scripts/
# adentro del contenedor, lo que permite que el backend ejecute
# auto-bootstrap del schema base (DDL + V001-V039) en fresh installs
# via app/schema_bootstrap.py.
#
# Configuracion en EasyPanel:
#   - Ruta de compilacion: /        (NO /web — contexto raiz del repo)
#   - Compilacion: Dockerfile
#   - Puerto: 8002
#
# Stage 1: build del frontend React.
# Stage 2: backend FastAPI con frontend compilado + legacy_ddl/migrations.
# ============================================================

# ─── Stage 1: Compilar React ────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY web/frontend/package*.json ./
RUN npm ci

COPY web/frontend/ .

# API en la misma URL base (sin prefijo externo).
ARG VITE_API_URL=/
ENV VITE_API_URL=$VITE_API_URL

# Sentry/GlitchTip build-args (opcionales).
ARG VITE_SENTRY_DSN=
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
ARG VITE_SENTRY_ENVIRONMENT=production
ENV VITE_SENTRY_ENVIRONMENT=$VITE_SENTRY_ENVIRONMENT
ARG VITE_SENTRY_TRACES_SAMPLE_RATE=0.1
ENV VITE_SENTRY_TRACES_SAMPLE_RATE=$VITE_SENTRY_TRACES_SAMPLE_RATE
ARG VITE_SENTRY_REPLAYS_ON_ERROR_RATE=1.0
ENV VITE_SENTRY_REPLAYS_ON_ERROR_RATE=$VITE_SENTRY_REPLAYS_ON_ERROR_RATE
ARG VITE_APP_VERSION=dev
ENV VITE_APP_VERSION=$VITE_APP_VERSION

RUN npm run build


# ─── Stage 2: Backend Python con frontend incluido ──────────────────
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements primero (mejor cache de Docker layers)
COPY web/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codigo del backend
COPY web/backend/ .

# Frontend compilado
COPY --from=frontend-builder /frontend/dist /app/static_frontend

# ─── NUEVO: schema base para fresh-install auto-bootstrap ────────────
# app/schema_bootstrap.py lee de estos paths al startup. Si la DB es
# fresh, aplica DDL + V001-V039 automaticamente. Ver el modulo para
# detalles.
COPY database/ddl/        /app/legacy_ddl/
COPY database/migrations/ /app/legacy_migrations/

# Scripts auxiliares (provision_tenant, bootstrap_fresh_install) — utiles
# para correr desde la consola del contenedor en operaciones manuales
# (debugging, re-bootstrap forzado, etc.).
COPY scripts/ /app/scripts/

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8002/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]

# ============================================================
# Imagen unificada: React (build) + FastAPI (serve)
# Un solo contenedor sirve el frontend estático y la API.
# ============================================================

# Stage 1 — Compilar React
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ .

# API en la misma URL base — no necesita prefijo externo
ARG VITE_API_URL=/
ENV VITE_API_URL=$VITE_API_URL

# V070.99 — Sentry/GlitchTip (build-time, OPCIONAL).
# En produccion EasyPanel no pasa build-args, asi que la config real
# se inyecta en runtime via window.__APP_CONFIG__ desde el backend.
# Estos ARGs sirven para dev/docker-compose local con .env.
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


# Stage 2 — Backend Python con frontend incluido
FROM python:3.13-slim

# Desactivar bytecode cache — Python SIEMPRE lee .py directamente
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código del backend — sin cache, siempre fresco
COPY backend/ .

# Copiar frontend compilado al directorio que FastAPI servirá
COPY --from=frontend-builder /frontend/dist /app/static_frontend

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8002/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]

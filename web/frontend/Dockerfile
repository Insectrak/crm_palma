# Stage 1: build React
FROM node:20-slim AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# VITE_API_URL = "/" porque nginx hace el proxy internamente
# Se puede sobreescribir con build-arg para cert/dev
ARG VITE_API_URL=/
ENV VITE_API_URL=$VITE_API_URL

# V070.99 — Sentry/GlitchTip frontend (opcional, baked at build time).
# Si VITE_SENTRY_DSN esta vacio, el init es no-op (no carga el SDK).
# Para activar: pasar como build-arg en EasyPanel o docker build.
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

# Stage 2: nginx para servir la SPA + proxy al backend
FROM nginx:alpine

# Config nginx con proxy a carlos-backend:8001
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

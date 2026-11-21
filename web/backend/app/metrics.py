"""Metrics module — Prometheus instrumentation para SLIs del CRM.

V070.72 (Bundle Observability — `docs/SLO.md`).

Provee dos cosas:

1. **Auto-instrumentation HTTP** (via `prometheus-fastapi-instrumentator`):
   - `http_requests_total{handler, method, status}` — count
   - `http_request_duration_seconds_*{handler, method}` — histogram
   - `up` — liveness (Prometheus lo agrega automatico al scrape)

2. **Metricas custom de negocio** (SLI de WhatsApp webhook, backup,
   FCM push, ingest leads, auth) — instrumentables desde los modulos
   que las generan via `from app.metrics import wa_webhook_processed`.

## Uso

En `main.py` durante el lifespan:

```python
from app.metrics import setup_metrics
setup_metrics(app)
```

Esto expone `/metrics` (texto Prometheus) protegido por IP allowlist
o token segun la config. En desarrollo es publico.

En cualquier handler:

```python
from app.metrics import wa_webhook_processed
wa_webhook_processed.labels(status="ok").inc()
```

## Cumplimiento

Cubre los 5 SLOs definidos en `docs/SLO.md`:

| SLO | Metrica |
|---|---|
| SLO-1 Availability | `up` (automatic) + `http_requests_total` |
| SLO-2 Latencia | `http_request_duration_seconds` histogram → quantile p95 |
| SLO-3 Error rate | `http_requests_total{status=~"5.."}` / total |
| SLO-4 WhatsApp webhook | `wa_webhook_processed_total{status}` |
| SLO-5 Backup freshness | `crm_backup_last_success_timestamp_seconds` (gauge) |

Vertical-agnostic: ninguna metrica lleva el nombre de un cliente,
solo dimensiones tecnicas. El tenant se identifica via el dominio del
Prometheus scrape target, no via label.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Metricas custom — instanciadas a nivel modulo para que sean singletons.
# Llamar `.labels(...).inc()` o `.set(...)` desde el codigo.
# ──────────────────────────────────────────────────────────────────────

# SLO-4 — WhatsApp webhook processing rate
wa_webhook_processed = Counter(
    "wa_webhook_processed_total",
    "Webhooks de Meta WhatsApp procesados",
    labelnames=("status",),  # 'ok', 'invalid_signature', 'parse_error', 'persist_error'
)

# SLO-5 — Backup freshness
crm_backup_last_success_timestamp_seconds = Gauge(
    "crm_backup_last_success_timestamp_seconds",
    "Timestamp UNIX del ultimo backup exitoso de Postgres",
)

crm_backup_size_bytes = Gauge(
    "crm_backup_size_bytes",
    "Tamaño en bytes del ultimo backup generado",
)

# Monitoring de FCM push (informativo, NO atado a SLO formal)
fcm_push_sent = Counter(
    "fcm_push_sent_total",
    "Push notifications enviadas via Firebase Cloud Messaging",
    labelnames=("result",),  # 'success', 'token_invalid', 'fcm_error', 'rate_limited'
)

# Monitoring de ingest API (informativo, util para diagnostico de proveedores)
ingest_leads = Counter(
    "ingest_leads_total",
    "Leads recibidos via /api/ingest/leads",
    labelnames=("api_client_prefix", "fuente", "result"),
    # api_client_prefix: ej 'cli_acme_xxx' → 'acme' (sin la key secreta)
    # fuente: 'facebook', 'instagram', 'tiktok', 'whatsapp', ...
    # result: 'created', 'duplicated', 'reactivated', 'rejected'
)

# Auditoria de logins (no es SLO, es security signal)
auth_login_attempts = Counter(
    "auth_login_attempts_total",
    "Intentos de login (auditable para detectar brute force)",
    labelnames=("result",),  # 'success', 'invalid_credentials', 'rate_limited', 'locked'
)

# DB pool monitoring (preventivo, util si se acaban las conexiones)
db_pool_connections_active = Gauge(
    "db_pool_connections_active",
    "Conexiones activas del pool psycopg2",
)

db_pool_connections_max = Gauge(
    "db_pool_connections_max",
    "Limite maximo de conexiones del pool",
)

# Conversaciones WhatsApp inbound (informativo, complementa SLO-4)
wa_messages_processed = Counter(
    "wa_messages_processed_total",
    "Mensajes WhatsApp procesados (inbound/outbound)",
    labelnames=("direction", "result"),
    # direction: 'inbound', 'outbound'
    # result: 'persisted', 'duplicated', 'failed'
)

# ── Team circuit breaker (V070.78 — ADR-0010) ─────────────────────────────
crm_team_blocked_total = Counter(
    "crm_team_blocked_total",
    "Veces que un equipo paso a estado 'blocked' (>=80% asesores pausados)",
    labelnames=("supervisor_id",),
)

crm_team_unblocked_total = Counter(
    "crm_team_unblocked_total",
    "Veces que un equipo salio de 'blocked' a 'active'/'at_risk'",
    labelnames=("supervisor_id",),
)

crm_lead_rerouted_total = Counter(
    "crm_lead_rerouted_total",
    "Leads que fueron desviados a otro equipo por circuit breaker",
    labelnames=("reason",),
    # reason: 'team_blocked', 'no_healthy_team_fallback_admin'
)


# ──────────────────────────────────────────────────────────────────────
# Setup de auto-instrumentation HTTP
# ──────────────────────────────────────────────────────────────────────

_instrumentator: Optional["object"] = None  # se setea en setup_metrics


def setup_metrics(app: FastAPI) -> None:
    """Instala Prometheus auto-instrumentation y expone /metrics.

    Debe llamarse UNA vez durante el startup (lifespan o al construir
    el FastAPI()). Idempotente: llamadas repetidas son no-op.

    Configuracion via env vars:
      - METRICS_ENABLED=false: skip el setup (default true).
      - METRICS_ENDPOINT_PROTECTED=true: requiere header X-Metrics-Token
        igual a METRICS_TOKEN. Recomendado en produccion.
      - METRICS_TOKEN=<secret>: token requerido si ENDPOINT_PROTECTED=true.
    """
    global _instrumentator
    if _instrumentator is not None:
        logger.warning("metrics: setup_metrics() llamado mas de una vez, skip")
        return

    if os.environ.get("METRICS_ENABLED", "true").lower() == "false":
        logger.info("metrics: deshabilitado por METRICS_ENABLED=false")
        return

    try:
        from prometheus_fastapi_instrumentator import Instrumentator
    except ImportError:
        logger.warning(
            "metrics: prometheus-fastapi-instrumentator no instalado, "
            "skip auto-instrumentation. Instalar con: "
            "pip install prometheus-fastapi-instrumentator"
        )
        return

    inst = Instrumentator(
        should_group_status_codes=False,    # diferencia 200/201/204
        should_ignore_untemplated=True,     # ignora 404s a paths no registrados
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers=[
            "/metrics",                     # no instrumentar el endpoint propio
            "/api/health",                  # health checks generan ruido en metricas
        ],
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    )
    inst.instrument(app)

    # Endpoint /metrics — protegido por token si esta configurado.
    protected = os.environ.get("METRICS_ENDPOINT_PROTECTED", "false").lower() == "true"
    if protected:
        token_expected = os.environ.get("METRICS_TOKEN")
        if not token_expected:
            logger.error(
                "metrics: METRICS_ENDPOINT_PROTECTED=true pero METRICS_TOKEN no "
                "esta seteado. /metrics quedara INACCESIBLE."
            )

        # V070.72 — handler manual con auth guard.
        # Importante: NO usar `request: Request` con type hint si el modulo
        # tiene `from __future__ import annotations` Y los imports estan
        # dentro de funciones — FastAPI no resuelve el hint y trata `request`
        # como query param (devuelve 422). Por eso `Request` esta importado
        # a nivel de modulo.
        @app.get("/metrics", include_in_schema=False)
        async def metrics_endpoint(request: Request):
            # V070.75 — aceptamos DOS formatos de auth para flexibilidad
            # con clientes estandar tipo Prometheus:
            #   1. X-Metrics-Token: <token>           (custom — recomendado)
            #   2. Authorization: Bearer <token>      (RFC 6750 — estandar)
            # Prometheus solo soporta nativamente el formato 2 via su config
            # bearer_token, asi que aceptar ambos evita tener que poner
            # un proxy intermedio.
            token_received = request.headers.get("X-Metrics-Token")
            if not token_received:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token_received = auth_header[len("Bearer "):].strip()
            if not token_received or token_received != token_expected:
                raise HTTPException(401, "metrics token invalido")
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    else:
        # Sin proteccion (dev / local) — el instrumentator expone /metrics solo.
        inst.expose(app, endpoint="/metrics", include_in_schema=False)

    _instrumentator = inst
    logger.info(
        "metrics: instrumentation activa. /metrics expuesto (protected=%s)",
        protected,
    )

"""
Punto de entrada principal del CRM multi-tenant (vertical-agnostico).

El nombre comercial visible al usuario (tab del navegador, /docs, emails,
exports) se resuelve dinamicamente en `app.services.brand_service` — este
modulo es agnostico a cualquier cliente especifico.
"""
import os
import logging
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import init_db_pool, close_db_pool
from app.bootstrap import run_startup_bootstrap
from app.observability import init_sentry

# V070.66 — Inicializar Sentry ANTES de crear la app FastAPI para que
# capture errores del propio startup (init_db_pool, bootstrap, etc).
# Si SENTRY_DSN está vacío en .env, no se inicializa (no-op).
init_sentry(
    dsn=settings.sentry_dsn,
    environment=settings.sentry_environment,
    traces_sample_rate=settings.sentry_traces_sample_rate,
    release=settings.app_version,
)
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.auth.rate_limit import limiter
from app.auth.router import router as auth_router
from app.routers.health import router as health_router
from app.routers.setup import router as setup_router
from app.routers.leads import router as leads_router
from app.routers.contactos import router as contactos_router
from app.routers.llamadas import router as llamadas_router
from app.routers.dashboard import router as dashboard_router
from app.routers.catalogs import router as catalogs_router
from app.routers.settings import router as settings_router
from app.routers.reportes import router as reportes_router
from app.routers.reportes_v2 import router as reportes_v2_router
from app.routers.metas import router as metas_router
from app.routers.carga_masiva import router as carga_masiva_router
from app.routers.agenda import router as agenda_router
from app.routers.ingest import router as ingest_router
from app.routers.greeting import router as greeting_router
from app.routers.notifications import router as notifications_router
from app.routers.audit import router as audit_router
from app.routers.team_health import router as team_health_router
from app.routers.public_forms import private_router as public_forms_private_router
from app.routers.public_forms import public_router as public_forms_public_router
from app.routers.whatsapp import router as whatsapp_router
from app.routers.tags import router as tags_router
from app.routers.historicos import router as historicos_router
from app.routers.integrations import router as integrations_router
from app.routers.integrations_meta import router as integrations_meta_router
from app.routers.integrations_tiktok import router as integrations_tiktok_router
from app.routers.field_mappings import router as field_mappings_router
from app.routers.api_clients import router as api_clients_router, public_router as api_clients_public_router
from app.routers.assignment import router as assignment_router
from app.routers.roles import router as roles_router
from app.routers.permission_audit import router as permission_audit_router
from app.routers.sharing_rules import router as sharing_rules_router
from app.routers.docs import router as docs_router
from app.routers.equipos import router as equipos_router
from app.routers.user_views import router as user_views_router
from app.routers.sedes import (
    admin_router as sedes_admin_router,
    lookup_router as sedes_lookup_router,
)
from app.routers.lead_merge import router as lead_merge_router
from app.routers.campaign_assignments import router as campaign_assignments_router
from app.routers.pixel import router as pixel_router
from app.routers.dashboard_jefatura import router as dashboard_jefatura_router
from app.routers.dashboard_supervision import router as dashboard_supervision_router
from app.routers.reciclaje_tmk import router as reciclaje_tmk_router
from app.routers.leads_inactivos import router as leads_inactivos_router
from app.routers.reportes_especiales import router as reportes_especiales_router

FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "static_frontend")
)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_started = False
    try:
        init_db_pool()
    except Exception as e:
        logger.warning("No se pudo conectar a la base de datos: %s", e)
    else:
        # Bootstrap de schemas idempotentes (features auto-contenidas).
        # Solo se ejecuta si el pool se inicializó correctamente.
        try:
            run_startup_bootstrap()
        except Exception as e:  # noqa: BLE001
            logger.warning("Bootstrap falló: %s", e)

        # Scheduler de pollers de integraciones (TikTok, futuros).
        # Solo arranca si hay DB + DEMO_MODE off — en tests no queremos
        # que el loop haga tráfico real.
        if not settings.demo_mode:
            try:
                from app.services.integrations import scheduler as integrations_scheduler
                integrations_scheduler.start()
                scheduler_started = True
            except Exception as e:  # noqa: BLE001
                logger.warning("Scheduler integraciones no arrancó: %s", e)
    try:
        yield
    finally:
        if scheduler_started:
            try:
                from app.services.integrations import scheduler as integrations_scheduler
                await integrations_scheduler.stop()
            except Exception as e:  # noqa: BLE001
                logger.warning("Scheduler integraciones no se detuvo limpio: %s", e)
        close_db_pool()


# V070.68 — Bundle B (vertical-agnostic).
# El title se resuelve al arranque desde brand_service para que /docs y
# OpenAPI muestren el nombre real del tenant. La descripcion y version
# son genericas del producto, no del cliente.
from app.services.brand_service import get_company_name as _get_company_name

try:
    _tenant_company = _get_company_name()
except Exception:
    # Si la DB no esta disponible al import (CI / demo / boot temprano),
    # caemos a "CRM" sin nombre — se actualiza con el siguiente reload.
    _tenant_company = "CRM"

app = FastAPI(
    title=f"CRM — {_tenant_company}",
    description="API del CRM — Gestion de leads y comercial",
    version=settings.app_version,
    lifespan=lifespan,
)

# Rate limiting (slowapi) — protege /auth/* contra brute force
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Security headers (OWASP) — se aplica a todas las respuestas, incluyendo la SPA
app.add_middleware(SecurityHeadersMiddleware)

# API versioning headers — inyecta X-Api-Version: v0-stable | v1 | v2 ...
# segun el path. Ver docs/API_VERSIONING.md + docs/adr/0009.
from app.middleware.api_version import ApiVersionMiddleware
app.add_middleware(ApiVersionMiddleware)

# CORS — explícito en métodos y headers (antes era wildcard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With", "X-Api-Key", "Idempotency-Key", "*"],
    expose_headers=["Content-Disposition"],  # necesario para descargas (xlsx)
    max_age=3600,
)

# V070.99 — Sentry multi-tenant tagging middleware.
# Cada request etiqueta el scope de Sentry con el host (= tenant del cliente)
# para que en el dashboard se puedan filtrar errores por cliente cuando
# onboardeemos Doctor Muelita y futuros tenants. patrón estándar.
from app.observability import set_tenant_context as _set_sentry_tenant


@app.middleware("http")
async def sentry_tenant_tag_middleware(request: Request, call_next):
    try:
        host = (request.headers.get("host") or "unknown").split(":")[0].lower()
        _set_sentry_tenant(tenant=host)
    except Exception:  # noqa: BLE001
        pass
    return await call_next(request)


# V070.72 — Observabilidad: Prometheus metrics + /metrics endpoint.
# Cubre los 5 SLOs definidos en docs/SLO.md. Auto-instrumenta requests HTTP
# y expone metricas custom de negocio (WhatsApp webhook, FCM, ingest, backup).
# Configuracion via env vars: METRICS_ENABLED, METRICS_ENDPOINT_PROTECTED,
# METRICS_TOKEN. Ver app/metrics.py para detalles.
from app.metrics import setup_metrics as _setup_metrics
_setup_metrics(app)

# Routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(leads_router)
app.include_router(contactos_router)
app.include_router(llamadas_router)
app.include_router(dashboard_router)
app.include_router(catalogs_router)
app.include_router(settings_router)
app.include_router(reportes_router)
app.include_router(reportes_v2_router)
app.include_router(metas_router)
app.include_router(carga_masiva_router)
app.include_router(agenda_router)
app.include_router(ingest_router)
app.include_router(greeting_router)
app.include_router(notifications_router)
app.include_router(audit_router)
app.include_router(team_health_router)
app.include_router(public_forms_private_router)
app.include_router(public_forms_public_router)
app.include_router(whatsapp_router)
app.include_router(tags_router)
app.include_router(historicos_router)
app.include_router(integrations_router)
app.include_router(integrations_meta_router)
app.include_router(integrations_tiktok_router)
app.include_router(pixel_router)
app.include_router(field_mappings_router)
app.include_router(api_clients_router)
app.include_router(api_clients_public_router)
app.include_router(assignment_router)
app.include_router(roles_router)
app.include_router(permission_audit_router)
app.include_router(sharing_rules_router)
app.include_router(docs_router)
app.include_router(equipos_router)
app.include_router(user_views_router)
app.include_router(sedes_admin_router)
app.include_router(sedes_lookup_router)
app.include_router(lead_merge_router)
app.include_router(dashboard_jefatura_router)
app.include_router(dashboard_supervision_router)
app.include_router(reciclaje_tmk_router)
app.include_router(campaign_assignments_router)
app.include_router(leads_inactivos_router)
app.include_router(reportes_especiales_router)

# V070.99 — Runtime config injection para el SPA.
# Lee env vars frontend (VITE_*) y las inyecta en el HTML al servir como
# <script id="__app_config__" type="application/json">. El frontend lee de
# ahi en lugar de import.meta.env (que requeriria build-args, que EasyPanel
# no pasa). Patron patrón estándar/patrón estándar para SaaS multi-tenant.
_INDEX_HTML_CACHE: Optional[str] = None  # cache del template


def _get_public_config() -> dict:
    """Config publica para inyectar en window.__APP_CONFIG__. Sin secretos."""
    return {
        "sentry": {
            "dsn":                  os.environ.get("VITE_SENTRY_DSN", "").strip(),
            "environment":          os.environ.get("VITE_SENTRY_ENVIRONMENT", "production").strip() or "production",
            "tracesSampleRate":     float(os.environ.get("VITE_SENTRY_TRACES_SAMPLE_RATE", "0.1") or "0.1"),
            "replaysOnErrorRate":   float(os.environ.get("VITE_SENTRY_REPLAYS_ON_ERROR_RATE", "1.0") or "1.0"),
            "release":              os.environ.get("VITE_APP_VERSION", "").strip() or (settings.app_version or "dev"),
        },
        "appVersion": os.environ.get("VITE_APP_VERSION", "").strip() or (settings.app_version or "dev"),
    }


def _serve_spa_index(index_path: str):
    """Lee index.html del cache, inyecta __APP_CONFIG__ y devuelve HTMLResponse."""
    global _INDEX_HTML_CACHE
    if _INDEX_HTML_CACHE is None:
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                _INDEX_HTML_CACHE = f.read()
        except OSError:
            return FileResponse(index_path)  # fallback raw

    # XSS-safe: type="application/json" no se ejecuta como JS; igual escapamos </
    config_json = json.dumps(_get_public_config()).replace("</", "<\\/")
    script_tag = (
        f'<script id="__app_config__" type="application/json">{config_json}</script>'
    )

    html = _INDEX_HTML_CACHE
    if "</head>" in html:
        html = html.replace("</head>", f"  {script_tag}\n  </head>", 1)
    else:
        # Fallback: prepender al body si no hay </head>
        html = script_tag + html
    return HTMLResponse(content=html)


# Servir SPA si el directorio existe (imagen Docker unificada)
if os.path.isdir(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    @app.get("/favicon.ico", include_in_schema=False)
    def serve_root_static(request: Request):
        filename = request.url.path.lstrip("/")
        fp = os.path.join(FRONTEND_DIR, filename)
        if os.path.isfile(fp):
            mt = "image/svg+xml" if filename.endswith(".svg") else None
            return FileResponse(fp, media_type=mt)
        from fastapi import HTTPException
        raise HTTPException(status_code=404)

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str = ""):
        if full_path.startswith(("api/", "auth/", "docs", "openapi")):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)

        # Si el path corresponde a un archivo real del frontend (manifest.json,
        # robots.txt, sw.js, icons/*, etc.), lo servimos con su Content-Type
        # correcto. Antes esto caia al SPA fallback y devolvia index.html con
        # text/html, lo que rompia el manifest PWA y similares.
        if full_path:
            candidate = os.path.normpath(os.path.join(FRONTEND_DIR, full_path))
            if (
                candidate.startswith(FRONTEND_DIR)  # evita path traversal
                and os.path.isfile(candidate)
            ):
                return FileResponse(candidate)

        index = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.isfile(index):
            # V070.99 — Inyectar __APP_CONFIG__ runtime para Sentry/GlitchTip.
            return _serve_spa_index(index)
        return {
            "message": f"CRM API — {_get_company_name()}",
            "version": settings.app_version,
        }
else:
    @app.get("/")
    def root():
        return {
            "message": f"CRM API — {_get_company_name()}",
            "version": settings.app_version,
            "docs":    "/docs",
        }

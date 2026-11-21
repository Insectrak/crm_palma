import logging
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(tags=["Sistema"])
logger = logging.getLogger(__name__)


# ─── SLI metrics endpoints (callable from n8n / external observers) ─────────

class BackupReportPayload(BaseModel):
    """Payload del n8n workflow de backup tras cada ejecucion exitosa."""
    timestamp:   int  = Field(..., description="Unix timestamp del backup exitoso")
    size_bytes:  int  = Field(..., ge=0, description="Tamaño del archivo .sql.gz generado")
    tenant_slug: str  = Field(..., min_length=1, max_length=64,
                              description="Slug del tenant (para auditoria)")


@router.post("/api/internal/metrics/backup-success",
             status_code=204,
             include_in_schema=False)
def report_backup_success(
    payload: BackupReportPayload,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Recibe el reporte de backup exitoso desde el workflow n8n.

    V070.72 — SLO-5 (backup freshness). El workflow llama este endpoint
    DESPUES del pg_dump local exitoso, con el timestamp y tamaño.
    Prometheus scrapea el gauge actualizado.

    Auth: header `X-Internal-Token` debe matchear env var `N8N_INTERNAL_KEY`.
    """
    expected_token = os.environ.get("N8N_INTERNAL_KEY")
    if not expected_token:
        raise HTTPException(503, "N8N_INTERNAL_KEY no configurado")
    if not x_internal_token or x_internal_token != expected_token:
        raise HTTPException(401, "Token interno invalido")

    # Actualizar gauges de Prometheus
    try:
        from app.metrics import (
            crm_backup_last_success_timestamp_seconds,
            crm_backup_size_bytes,
        )
        crm_backup_last_success_timestamp_seconds.set(payload.timestamp)
        crm_backup_size_bytes.set(payload.size_bytes)
        logger.info(
            "[metrics] backup report: tenant=%s ts=%s size=%d bytes",
            payload.tenant_slug, payload.timestamp, payload.size_bytes,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[metrics] no se pudo actualizar gauges: %s", exc)


@router.get("/api/health")
def health_check():
    """Endpoint de health check para load balancers y monitoreo.

    V070.67 — version ya NO es hardcoded "4.7.0". Ahora se lee de
    settings.app_version (env var APP_VERSION). Default 'dev' si no se
    inyecta. En CI/build de Docker se debe setear con el SHA del commit:
        ENV APP_VERSION=$(git rev-parse --short HEAD)
    Asi los dashboards de uptime (UptimeRobot, BetterUptime, etc.) y
    Sentry releases muestran la version REALMENTE deployada.
    """
    if settings.demo_mode:
        return {
            "status":  "ok",
            "db":      "demo_mode",
            "demo":    True,
            "version": settings.app_version,
        }

    from app.database import check_db_connection
    db_status = "connected" if check_db_connection() else "disconnected"
    return {
        "status":  "ok",
        "db":      db_status,
        "version": settings.app_version,
    }


# ─── API v1 — ejemplo del patron documentado en docs/API_VERSIONING.md ─────

@router.get("/api/v1/health")
def health_check_v1():
    """Health check version 1 — schema enriquecido vs v0.

    V070.73 (Bundle API Versioning — ADR-0009). Sirve dos propositos:

    1. Demostrar el patron de versioning para que los siguientes
       endpoints nuevos lo adopten (`/api/v1/<recurso>`).
    2. Devolver un schema mas estructurado, util para dashboards de
       uptime externos (UptimeRobot, BetterUptime, StatusCake).

    Schema v1:
      - status: 'ok' | 'degraded' | 'down' (mas granular que v0)
      - components: dict con el estado de cada subsistema
      - version: SHA del commit deployado
      - api_version: la version de la API que respondio

    El endpoint v0 (`/api/health`) sigue funcionando sin cambios — los
    consumers existentes (load balancers, monitoring) no se rompen.
    """
    from app.database import check_db_connection

    components: dict = {"database": "unknown"}
    overall_status = "ok"

    if settings.demo_mode:
        components["database"] = "demo_mode"
    else:
        db_ok = check_db_connection()
        components["database"] = "connected" if db_ok else "disconnected"
        if not db_ok:
            overall_status = "down"

    return {
        "status":      overall_status,
        "components":  components,
        "version":     settings.app_version,
        "api_version": "v1",
        "demo":        settings.demo_mode,
    }


@router.get("/api/health/build", include_in_schema=False)
def health_build():
    """Diagnostico de runtime: que migraciones aplicaron, que eventos
    soporta el webhook system, etc. Sin auth (info no sensible — solo
    nombres de columnas y eventos).

    V084 — agregado para diagnosticar deploys donde V084 no aplico
    correctamente (caso del entorno de pruebas 2026-06-16: el frontend mostraba
    el checkbox 'Lead recontacto' pero el backend no encolaba el evento
    porque el deploy quedo cacheado en una imagen anterior).
    """
    info: dict = {
        "version": settings.app_version,
        "demo":    settings.demo_mode,
    }

    if settings.demo_mode:
        info["note"] = "DEMO_MODE activo — sin DB para diagnosticar"
        return info

    # Eventos soportados en runtime (lo que ALL_EVENTS tiene en el binario
    # actualmente corriendo). Si lead.recontacto no esta aqui, el binario
    # es pre-V084 y hay que re-deployar.
    try:
        from app.services import webhook_service
        info["webhook_events_supported"] = sorted(webhook_service.ALL_EVENTS)
    except Exception as exc:  # noqa: BLE001
        info["webhook_events_supported_error"] = str(exc)

    # Verificar columnas V084 en crm.lead_recontactos. Si falta alguna,
    # la migracion V084 no se aplico (deploy parcial).
    try:
        from app.database import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'lead_recontactos'
                      AND column_name IN ('anuncio','conjunto','fuente_form_id')
                    ORDER BY column_name
                    """
                )
                cols = [r[0] for r in cur.fetchall()]
                info["v084_columns_present"] = cols
                info["v084_applied"] = sorted(cols) == ["anuncio", "conjunto", "fuente_form_id"]
                # Conteo de api_clients con lead.recontacto suscripto (sanity check)
                # V085.1 — webhook_events es text[] (no jsonb). Usar ANY()
                # en vez del operador `?` (que es solo jsonb).
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE webhook_enabled = TRUE) AS webhook_enabled_count,
                        COUNT(*) FILTER (
                            WHERE webhook_enabled = TRUE
                              AND 'lead.recontacto' = ANY(webhook_events)
                        ) AS subscribed_recontacto_count
                    FROM crm.api_clients
                    WHERE activo = TRUE AND revoked_at IS NULL
                    """
                )
                row = cur.fetchone()
                if row:
                    info["api_clients_webhook_enabled"] = row[0]
                    info["api_clients_subscribed_recontacto"] = row[1]
    except Exception as exc:  # noqa: BLE001
        info["v084_check_error"] = str(exc)

    return info

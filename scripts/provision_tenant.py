#!/usr/bin/env python3
"""
provision_tenant.py - Genera config completa para un nuevo tenant del CRM.

Casos de uso:

  1. Interactivo (recomendado la primera vez):
       python scripts/provision_tenant.py

  2. No-interactivo (CI / automation):
       python scripts/provision_tenant.py \\
           --tenant doctormuelita \\
           --company "Doctor Muelita" \\
           --industry dental \\
           --country Peru \\
           --pg-host pdr_postgres \\
           --pg-password "<password>" \\
           --output deploy/doctormuelita/.env

Lo que hace:
  - Genera 5 secrets criptográficos (SECRET_KEY, INGEST_API_KEY,
    EMERGENCY_SECRET, METRICS_TOKEN, N8N_INTERNAL_KEY).
  - Renderiza un .env completo con todos los valores del tenant.
  - Imprime resumen + bloque listo para pegar en EasyPanel.
  - Avisos de seguridad por vars sensibles aún pendientes (Meta WA, FCM,
    Sentry).

Sin dependencias externas — solo stdlib. Compatible con Python 3.10+.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from textwrap import dedent

# Forzar UTF-8 en stdout/stderr (necesario en Windows cp1252).
# Python 3.7+ tiene reconfigure(); en versiones viejas no rompe.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, Exception):
    pass


# ────────────────────────────────────────────────────────────────────
# Generadores de secrets
# ────────────────────────────────────────────────────────────────────

def gen_hex(n_bytes: int = 32) -> str:
    """SECRET_KEY, N8N_INTERNAL_KEY, METRICS_TOKEN — 64 chars hex."""
    return secrets.token_hex(n_bytes)


def gen_urlsafe(n_bytes: int = 32) -> str:
    """INGEST_API_KEY, EMERGENCY_SECRET — URL-safe base64."""
    return secrets.token_urlsafe(n_bytes)


# ────────────────────────────────────────────────────────────────────
# Modelo del tenant
# ────────────────────────────────────────────────────────────────────

@dataclass
class TenantConfig:
    # Identidad
    tenant_slug: str          # snake_case, e.g. "doctormuelita"
    company_name: str         # display name, e.g. "Doctor Muelita"
    industry: str             # "inmobiliaria", "dental", "hotelero", ...
    country: str = "Peru"
    support_email: str = ""

    # Postgres
    pg_host: str = "postgres"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = ""
    db_name: str = ""

    # URLs
    domain: str = ""          # "crm.cliente.com" — opcional al inicio
    backend_url: str = ""     # se autocompleta de domain o IP

    # Secrets (auto-generados)
    secret_key: str = field(default_factory=gen_hex)
    ingest_api_key: str = field(default_factory=gen_urlsafe)
    emergency_secret: str = field(default_factory=gen_urlsafe)
    metrics_token: str = field(default_factory=gen_hex)
    n8n_internal_key: str = field(default_factory=gen_hex)
    # Nota: NO generamos meta_wa_* — WhatsApp se configura por UI multi-WABA

    def __post_init__(self):
        if not self.db_name:
            self.db_name = f"crm_{self.tenant_slug}"
        if not self.support_email:
            domain_part = self.domain.replace("crm.", "") if self.domain else "ejemplo.com"
            self.support_email = f"soporte@{domain_part}"
        if not self.backend_url:
            self.backend_url = f"https://{self.domain}" if self.domain else ""


# ────────────────────────────────────────────────────────────────────
# Render del .env
# ────────────────────────────────────────────────────────────────────

ENV_TEMPLATE = dedent("""\
    # ============================================================
    # CRM — Tenant: {company_name}
    # Generado: {timestamp}
    # NUNCA commitear este archivo. Guardar los secrets en un
    # password manager (Bitwarden, 1Password, etc.).
    # ============================================================

    # ─── Base de datos ───────────────────────────────────────────
    DATABASE_URL=postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{db_name}

    # ─── JWT / Auth ──────────────────────────────────────────────
    SECRET_KEY={secret_key}
    ALGORITHM=HS256
    ACCESS_TOKEN_EXPIRE_HOURS=8

    # ─── CORS ────────────────────────────────────────────────────
    # Cuando tengas dominio público, agregalo separado por coma.
    ALLOWED_ORIGINS={allowed_origins}

    # ─── Tenant (branding + IA prompts) ──────────────────────────
    TENANT_COMPANY_NAME={company_name}
    TENANT_INDUSTRY={industry}
    TENANT_COUNTRY={country}
    TENANT_SUPPORT_EMAIL={support_email}

    # ─── Modo + versión ──────────────────────────────────────────
    DEMO_MODE=false
    APP_VERSION=v1.0.0-{tenant_slug}

    # ─── n8n (red interna) ───────────────────────────────────────
    N8N_WEBHOOK_BASE=http://n8n:5678
    N8N_INTERNAL_KEY={n8n_internal_key}

    # ─── Multi-tenant ingest (drivers externos / Wedo / IA) ──────
    INGEST_API_KEY={ingest_api_key}

    # ─── IA / Ollama (opcional, comentar si no se usa) ──────────
    # OLLAMA_BASE_URL=http://ollama:11434
    # OLLAMA_MODEL=qwen2.5:7b

    # ─── Emergencia / Reset admin sin login ─────────────────────
    EMERGENCY_SECRET={emergency_secret}

    # ─── Prometheus metrics ─────────────────────────────────────
    METRICS_ENABLED=true
    METRICS_ENDPOINT_PROTECTED=true
    METRICS_TOKEN={metrics_token}
    CRM_BACKEND_URL={backend_url_or_placeholder}

    # ─── Formularios públicos — anti-spam ───────────────────────
    PUBLIC_FORM_MIN_SUBMIT_SECONDS=2
    PUBLIC_FORM_IP_MAX_SUBMISSIONS=5
    PUBLIC_FORM_IP_WINDOW_MINUTES=10
    PUBLIC_FORM_RATE_LIMIT_SUBMIT=10/minute
    PUBLIC_FORM_RATE_LIMIT_GET=60/minute
    PUBLIC_FORM_DEFAULT_COUNTRY_CODE=51

    # ─── WhatsApp Business Cloud API ────────────────────────────
    # Configurar desde la UI del CRM:
    #   Integraciones -> WhatsApp -> Cuentas Empresariales (WABA)
    #   Integraciones -> WhatsApp -> Lineas WhatsApp Business
    # Multi-WABA nativo, multi-linea, tokens cifrados en DB.
    # NO requiere variables en este .env.

    # ─── FCM Push Mobile (cuando se tenga el service account) ───
    # FCM_ENABLED=true
    # FCM_SERVICE_ACCOUNT_B64=<base64 del JSON service account>

    # ─── Sentry / GlitchTip (recomendado, crear proyecto nuevo) ─
    # SENTRY_DSN=https://<dsn>@glitchtip.crm.local/<project_id>
    # SENTRY_ENVIRONMENT=production
    # SENTRY_TRACES_SAMPLE_RATE=0.0
    #
    # Frontend (build-time):
    # VITE_SENTRY_DSN=https://<dsn-frontend>@glitchtip.crm.local/<other_project_id>
    # VITE_SENTRY_ENVIRONMENT=production
    # VITE_SENTRY_TRACES_SAMPLE_RATE=0.1
    # VITE_SENTRY_REPLAYS_ON_ERROR_RATE=1.0
    # VITE_APP_VERSION=v1.0.0-{tenant_slug}
""")


def render_env(cfg: TenantConfig) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Default CORS: localhost + dominio si está + IP si no
    origins = ["http://localhost:5173", "http://localhost:3002"]
    if cfg.domain:
        origins.append(f"https://{cfg.domain}")
    allowed_origins = ",".join(origins)

    return ENV_TEMPLATE.format(
        company_name=cfg.company_name,
        timestamp=timestamp,
        pg_user=cfg.pg_user,
        pg_password=cfg.pg_password,
        pg_host=cfg.pg_host,
        pg_port=cfg.pg_port,
        db_name=cfg.db_name,
        secret_key=cfg.secret_key,
        allowed_origins=allowed_origins,
        industry=cfg.industry,
        country=cfg.country,
        support_email=cfg.support_email,
        tenant_slug=cfg.tenant_slug,
        n8n_internal_key=cfg.n8n_internal_key,
        ingest_api_key=cfg.ingest_api_key,
        emergency_secret=cfg.emergency_secret,
        metrics_token=cfg.metrics_token,
        backend_url_or_placeholder=cfg.backend_url or f"http://localhost:8002  # cambiar cuando tengas dominio",
    )


# ────────────────────────────────────────────────────────────────────
# CLI + interactivo
# ────────────────────────────────────────────────────────────────────

def prompt(label: str, default: str = "", required: bool = False) -> str:
    """Lee input con default. Si required=True, no permite vacío."""
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"  {label}{suffix}: ").strip()
        if not val and default:
            return default
        if not val and required:
            print("  ⚠️  Este campo es obligatorio.")
            continue
        return val


def interactive_config() -> TenantConfig:
    print()
    print("═" * 60)
    print("  Provisioning de nuevo tenant del CRM")
    print("═" * 60)
    print()
    print("Vas a generar la config completa para un cliente nuevo.")
    print("Los secrets se generan automáticamente — NO los pierdas.")
    print()

    print("── Identidad del cliente ──")
    tenant_slug = prompt("Tenant slug (snake_case, sin espacios)", required=True)
    company_name = prompt("Nombre comercial", default=tenant_slug.replace("_", " ").title())
    industry = prompt("Industria (inmobiliaria/dental/hotelero/...)", default="generico")
    country = prompt("País", default="Peru")
    support_email_default = f"soporte@{tenant_slug.replace('_', '')}.com"
    support_email = prompt("Email de soporte", default=support_email_default)

    print()
    print("── PostgreSQL ──")
    pg_host = prompt("Host interno Postgres (red Docker)", default="postgres")
    pg_port_str = prompt("Puerto Postgres", default="5432")
    pg_user = prompt("Usuario Postgres", default="postgres")
    pg_password = prompt("Password Postgres", required=True)
    db_name = prompt("Nombre de la DB", default=f"crm_{tenant_slug}")

    print()
    print("── Dominio (opcional, puedes dejar vacío y configurarlo después) ──")
    domain = prompt("Dominio público (sin https://)", default="")

    return TenantConfig(
        tenant_slug=tenant_slug,
        company_name=company_name,
        industry=industry,
        country=country,
        support_email=support_email,
        pg_host=pg_host,
        pg_port=int(pg_port_str),
        pg_user=pg_user,
        pg_password=pg_password,
        db_name=db_name,
        domain=domain,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Genera config (.env + secrets) para un tenant nuevo del CRM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tenant", help="Slug del tenant (snake_case)")
    p.add_argument("--company", help="Nombre comercial del cliente")
    p.add_argument("--industry", default="generico", help="Industria")
    p.add_argument("--country", default="Peru")
    p.add_argument("--support-email", default="")

    p.add_argument("--pg-host", default="postgres")
    p.add_argument("--pg-port", type=int, default=5432)
    p.add_argument("--pg-user", default="postgres")
    p.add_argument("--pg-password", default="", help="Password Postgres (sino se pregunta)")
    p.add_argument("--db-name", default="", help="Nombre DB (default: crm_<tenant>)")

    p.add_argument("--domain", default="", help="Dominio público (sin https://)")

    p.add_argument(
        "-o", "--output",
        default="",
        help="Archivo .env de salida (sino imprime a stdout)",
    )
    p.add_argument(
        "--print-only",
        action="store_true",
        help="Solo imprime el .env, no escribe archivo (útil para EasyPanel copy-paste)",
    )

    return p.parse_args()


# ────────────────────────────────────────────────────────────────────
# Output formatting
# ────────────────────────────────────────────────────────────────────

def print_summary(cfg: TenantConfig, env_path: Path | None) -> None:
    """Resumen post-provisioning con next steps."""
    print()
    print("═" * 60)
    print(f"  ✅ Tenant {cfg.company_name!r} listo")
    print("═" * 60)
    print()

    if env_path:
        print(f"📄 Archivo generado: {env_path}")
    print()
    print("🔐 Secrets generados (guardalos en tu password manager AHORA):")
    print(f"   SECRET_KEY              = {cfg.secret_key[:8]}…{cfg.secret_key[-8:]}")
    print(f"   INGEST_API_KEY          = {cfg.ingest_api_key[:8]}…{cfg.ingest_api_key[-8:]}")
    print(f"   EMERGENCY_SECRET        = {cfg.emergency_secret[:8]}…{cfg.emergency_secret[-8:]}")
    print(f"   METRICS_TOKEN           = {cfg.metrics_token[:8]}…{cfg.metrics_token[-8:]}")
    print(f"   N8N_INTERNAL_KEY        = {cfg.n8n_internal_key[:8]}…{cfg.n8n_internal_key[-8:]}")
    print()
    print("📱 WhatsApp Business Cloud API:")
    print("   NO incluido en este .env. Se configura desde la UI:")
    print("     Integraciones → WhatsApp → Cuentas Empresariales (WABA)")
    print("     Integraciones → WhatsApp → Líneas WhatsApp Business")
    print("   Tokens, verify_token y app_secret se guardan cifrados en DB,")
    print("   nunca en variables de entorno ni accesibles desde EasyPanel.")
    print()

    print("📋 Próximos pasos:")
    print()
    print("  EasyPanel:")
    print(f"    1. Crear DB Postgres '{cfg.db_name}' (vacía — el backend corre las migraciones)")
    print( "    2. Crear servicio 'app' con build path /web desde GitHub")
    print(f"    3. Copy-paste el bloque del .env en Environment")
    print( "    4. Implementar — las 35 migraciones se aplican solas al primer arranque")
    print(f"    5. Verificar: GET https://{cfg.domain or '<dominio>'}/api/health")
    print( "    6. POST /api/setup/create-admin para crear el primer admin")
    print()
    print("  Docker standalone (cualquier servidor con Docker):")
    print( "    1. cp <output>.env .env  (en la carpeta del docker-compose.standalone.yml)")
    print( "    2. docker compose -f docker-compose.standalone.yml up -d")
    print( "    3. Verificar: curl http://localhost:8002/api/health")
    print()

    print("⚠️  Pendientes manuales (no autogeneables):")
    print("   - WhatsApp Cloud API: tokens reales después de verificar Meta Business")
    print("   - FCM: descargar service-account.json y convertir a base64")
    print("   - Sentry/GlitchTip: crear proyecto nuevo para este tenant")
    print("   - DNS: apuntar el dominio al servidor")
    print()


def main() -> int:
    args = parse_args()

    # Decisión: interactivo vs CLI
    if not args.tenant:
        cfg = interactive_config()
    else:
        if not args.pg_password:
            print("❌ ERROR: --pg-password es obligatorio en modo no-interactivo")
            return 1
        cfg = TenantConfig(
            tenant_slug=args.tenant,
            company_name=args.company or args.tenant.replace("_", " ").title(),
            industry=args.industry,
            country=args.country,
            support_email=args.support_email,
            pg_host=args.pg_host,
            pg_port=args.pg_port,
            pg_user=args.pg_user,
            pg_password=args.pg_password,
            db_name=args.db_name,
            domain=args.domain,
        )

    env_content = render_env(cfg)

    if args.print_only:
        print()
        print("─── COPY-PASTE EN EASYPANEL ENVIRONMENT ───")
        print(env_content)
        print("─── FIN ───")
        return 0

    output_path = Path(args.output) if args.output else Path(f".env.{cfg.tenant_slug}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        resp = input(f"⚠️  {output_path} ya existe. ¿Sobrescribir? [y/N]: ").strip().lower()
        if resp != "y":
            print("Abortado. El .env existente NO fue modificado.")
            return 1

    output_path.write_text(env_content, encoding="utf-8")

    print_summary(cfg, output_path)
    print("👉 Para imprimir el bloque listo para EasyPanel (sin escribir archivo):")
    print(f"   python scripts/provision_tenant.py --tenant {cfg.tenant_slug} \\")
    print(f"       --pg-password '<pass>' --print-only")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Brand service — single source of truth del branding por tenant.

Este modulo centraliza la resolucion del nombre comercial, descripcion de
industria, keywords y otros campos que dependen del cliente final. Cualquier
texto visible al usuario (emails, excel exports, push notifications, prompts
IA) debe pasar por aqui — no hardcodear nombres de clientes en codigo.

## Fallback chain

1. `app_settings` table (BrandConfig persistido por admin via UI).
2. Env vars (`TENANT_COMPANY_NAME`, `TENANT_INDUSTRY`, etc.) — inyectadas
   por el deployment de cada cliente.
3. Defaults neutros ("Mi CRM", sin industria especifica). NUNCA un cliente
   especifico — eso seria reintroducir el bug de Palma Rio hardcoded.

## Cache

Resultado se cachea 60s para evitar hit a DB en cada email / export.
TTL corto porque el branding cambia poco y los cambios deben propagar
"casi en tiempo real" cuando el admin edita la marca.

## Uso

```python
from app.services.brand_service import get_brand

brand = get_brand()
subject = f"Bienvenido a {brand['company_name']}"
filename = f"leads_{brand['filename_slug']}_{date.today()}.xlsx"
```
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Optional

from app.config import settings

# ── Defaults Palma del Río — marca del tenant ──────────────────────────
# Cualquier install limpio sin TENANT_COMPANY_NAME ni branding en
# public.app_settings arranca con la marca Palma del Río. El admin puede
# sobrescribir estos defaults desde "Configuracion -> Marca" en runtime.
_NEUTRAL_DEFAULTS: dict = {
    "company_name":         "Palma del Río",
    "legal_name":           "Palma del Río Inmobiliaria",
    "subtitle":             "Plataforma de Gestión de Leads",
    "industry":             "inmobiliaria",
    "industry_description": "Inmobiliaria y comercialización de proyectos inmobiliarios",
    "relevant_keywords":    "departamento,lote,casa,inmobiliaria,proyecto,visita,cita",
    "country":              "Peru",
    "support_email":        "soporte@palmadelrioinmobiliaria.org",
    "known_domains":        ["palmadelrioinmobiliaria.org", "azoramind.com"],
    "tagline":              "Palma del Río — Plataforma CRM",
}

# Cache simple en memoria por proceso. Multi-worker:
# cada Uvicorn worker tiene su propia copia (aceptable con TTL 60s).
_CACHE_TTL_SECONDS = 60
_cache_value: Optional[dict] = None
_cache_loaded_at: float = 0.0
_cache_lock = threading.Lock()


def _load_from_env() -> dict:
    """Sobreescritura via env vars. Util para deploys que no quieren
    mantener el branding en DB (por ejemplo, scripts CLI o jobs)."""
    overrides = {}
    mapping = {
        "TENANT_COMPANY_NAME":       "company_name",
        "TENANT_LEGAL_NAME":         "legal_name",
        "TENANT_SUBTITLE":           "subtitle",
        "TENANT_INDUSTRY":           "industry",
        "TENANT_INDUSTRY_DESC":      "industry_description",
        "TENANT_KEYWORDS":           "relevant_keywords",
        "TENANT_COUNTRY":            "country",
        "TENANT_SUPPORT_EMAIL":      "support_email",
        "TENANT_TAGLINE":            "tagline",
    }
    for env_var, key in mapping.items():
        val = os.environ.get(env_var)
        if val:
            overrides[key] = val
    # known_domains soporta lista separada por comas
    domains_csv = os.environ.get("TENANT_KNOWN_DOMAINS", "").strip()
    if domains_csv:
        overrides["known_domains"] = [d.strip() for d in domains_csv.split(",") if d.strip()]
    return overrides


def _load_from_db() -> dict:
    """Lee el BrandConfig persistido en app_settings."""
    if settings.demo_mode:
        return {}
    try:
        from app.database import get_db
        from psycopg2.extras import RealDictCursor
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'brand_config'"
                )
                row = cur.fetchone()
                if row and row.get("value"):
                    return dict(row["value"])
    except Exception:
        # Si la tabla no existe aun (ambiente nuevo), devolver vacio.
        # No es error: es ausencia de configuracion.
        pass
    return {}


def _compute_filename_slug(company_name: str) -> str:
    """Convierte 'Doctor Muelita' -> 'doctor_muelita' para nombres de archivo."""
    slug = company_name.lower().strip()
    # Reemplaza acentos y caracteres no ASCII por equivalentes simples
    slug = re.sub(r"[áàäâã]", "a", slug)
    slug = re.sub(r"[éèëê]", "e", slug)
    slug = re.sub(r"[íìïî]", "i", slug)
    slug = re.sub(r"[óòöôõ]", "o", slug)
    slug = re.sub(r"[úùüû]", "u", slug)
    slug = re.sub(r"[ñ]", "n", slug)
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "tenant"


def _resolve() -> dict:
    """Combina los 3 niveles: defaults → env → DB."""
    result = dict(_NEUTRAL_DEFAULTS)
    result.update(_load_from_env())
    result.update(_load_from_db())
    # Asegura que filename_slug siempre exista (derivado de company_name)
    result["filename_slug"] = _compute_filename_slug(result["company_name"])
    return result


def get_brand(*, force_refresh: bool = False) -> dict:
    """Devuelve la configuracion de marca del tenant actual.

    Es thread-safe y cacheado por 60s. Llamar con force_refresh=True para
    invalidar el cache manualmente (ej: despues de PUT /api/settings/brand).
    """
    global _cache_value, _cache_loaded_at
    now = time.monotonic()
    with _cache_lock:
        if (
            not force_refresh
            and _cache_value is not None
            and (now - _cache_loaded_at) < _CACHE_TTL_SECONDS
        ):
            return dict(_cache_value)
        _cache_value = _resolve()
        _cache_loaded_at = now
        return dict(_cache_value)


def invalidate_cache() -> None:
    """Fuerza recarga en el proximo get_brand(). Llamar despues de cambios
    en app_settings."""
    global _cache_value, _cache_loaded_at
    with _cache_lock:
        _cache_value = None
        _cache_loaded_at = 0.0


# ── Helpers de conveniencia ───────────────────────────────────────────────


def get_company_name() -> str:
    """Atajo: nombre comercial. Usado en emails, headers de Excel, etc."""
    return get_brand()["company_name"]


def get_filename_slug() -> str:
    """Atajo: slug seguro para nombres de archivo (sin espacios ni acentos)."""
    return get_brand()["filename_slug"]


def is_ai_classifier_configured() -> bool:
    """True si la industria + keywords estan configuradas para el clasificador.

    Si retorna False, el clasificador IA debe negarse a procesar mensajes
    porque no tiene contexto del negocio del tenant. Esto evita el bug de
    Palma Rio: clasificar mensajes de Doctor Muelita como si fueran de
    inmobiliaria.
    """
    brand = get_brand()
    return bool(brand.get("industry_description") and brand.get("relevant_keywords"))

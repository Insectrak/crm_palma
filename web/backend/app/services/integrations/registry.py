"""Catálogo estático de proveedores de integración.

Define, para cada proveedor:
  - Keys permitidas (whitelist defensiva contra payloads arbitrarios).
  - Cuáles de esas keys son secretas (se cifran) vs config plana.
  - Metadata de UI (label, descripción, icono).

Agregar un proveedor nuevo = agregar una entrada acá + implementar su
driver. La fundación (repo, eventos, router) no necesita cambios.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class CredentialKeySpec:
    """Define una key válida para un proveedor."""
    key: str
    is_secret: bool
    label: str
    help: str = ""
    # Si es True, puede repetirse por account_id distintos (ej. access_token
    # por cada page_id de Meta). Si es False, solo existe en '_global'.
    per_account: bool = False


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    label: str
    description: str
    keys: Dict[str, CredentialKeySpec] = field(default_factory=dict)


# Whitelist de proveedores. Cualquier POST con provider fuera de esta
# lista se rechaza en el router.
_PROVIDERS: Dict[str, ProviderSpec] = {
    "meta": ProviderSpec(
        provider="meta",
        label="Meta (Facebook & Instagram)",
        description="Lead Ads via webhook — Meta empuja eventos cuando un usuario envía un form.",
        keys={
            "app_id":                CredentialKeySpec("app_id",                False, "App ID",                "ID público del Meta App."),
            "app_secret":            CredentialKeySpec("app_secret",            True,  "App Secret",            "Se usa para validar la firma HMAC-SHA256 de los webhooks."),
            "verify_token":          CredentialKeySpec("verify_token",          True,  "Verify Token",          "Token arbitrario que Meta envía al verificar la suscripción del webhook."),
            "page_access_token":     CredentialKeySpec("page_access_token",     True,  "Page Access Token",     "Token long-lived por página, usado para fetch de detalle del lead.", per_account=True),
            "page_name":             CredentialKeySpec("page_name",             False, "Nombre de la página",   "Etiqueta visible en la UI.", per_account=True),
            "ads_access_token":      CredentialKeySpec("ads_access_token",      True,  "Ads Access Token",      "System User Token con scope ads_read. Se usa solo para resolver nombres de ad/adset/campaign de CTWA."),
            "pixel_id":              CredentialKeySpec("pixel_id",              False, "Meta Pixel ID",         "ID del píxel de Meta para seguimiento de conversiones en formularios públicos."),
            "ad_account_id":         CredentialKeySpec("ad_account_id",         False, "Ad Account ID",         "ID de cuenta publicitaria (ej. act_1234567890) para el Dashboard de Pixel."),
        },
    ),
    "tiktok": ProviderSpec(
        provider="tiktok",
        label="TikTok Ads",
        description="Lead Generation — polling periódico al Marketing API (TikTok no expone webhooks).",
        keys={
            "app_id":                  CredentialKeySpec("app_id",                  False, "App ID",                  "ID del app en TikTok Marketing API."),
            "app_secret":              CredentialKeySpec("app_secret",              True,  "App Secret"),
            "access_token":            CredentialKeySpec("access_token",            True,  "Access Token",            "Long-lived token por advertiser. Se usa para crear/poll/descargar tasks de leads.", per_account=True),
            "pages_access_token":      CredentialKeySpec("pages_access_token",      True,  "Pages Access Token",      "Token alternativo SOLO para /page/get/. Llenar si la app que emitio access_token no tiene scope para listar pages.", per_account=True),
            "advertiser_name":         CredentialKeySpec("advertiser_name",         False, "Nombre del advertiser",   "", per_account=True),
            "polling_interval_min":    CredentialKeySpec("polling_interval_min",    False, "Intervalo polling (min)", "Entre 5 y 30 minutos."),
            "pixel_id":                CredentialKeySpec("pixel_id",                False, "TikTok Pixel ID",       "ID del píxel de TikTok para seguimiento de conversiones en formularios públicos."),
        },
    ),
}


def get_provider(provider: str) -> ProviderSpec | None:
    return _PROVIDERS.get((provider or "").strip().lower())


def list_providers() -> list[ProviderSpec]:
    return list(_PROVIDERS.values())


def is_valid_key(provider: str, key: str) -> bool:
    p = get_provider(provider)
    return bool(p and key in p.keys)


def key_spec(provider: str, key: str) -> CredentialKeySpec | None:
    p = get_provider(provider)
    return p.keys.get(key) if p else None

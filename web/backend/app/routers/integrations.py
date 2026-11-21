"""Endpoints admin para gestionar integraciones externas (Meta, TikTok, ...).

Diseño:
  - Todo es admin-only (super-sensible: tokens de terceros).
  - GET nunca devuelve plaintext de secretos — solo mask + fingerprint.
  - PUT/DELETE validan provider + key contra el registry para no aceptar
    campos arbitrarios. Defensa-en-profundidad aunque la UI ya los valide.
  - Cada cambio emite un evento `credential_updated` / `credential_deleted`
    en `crm.integrations_events` — trazabilidad sin tocar logs del servidor.

Este router es fundación: NO implementa webhooks ni polling. Eso vive en
routers/services propios de cada proveedor (PRs siguientes).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.services.integrations import credentials_repo, events_repo
from app.services.integrations.credentials_repo import (
    CredentialsRepoError,
    GLOBAL_ACCOUNT,
)
from app.services.integrations.registry import (
    get_provider,
    list_providers,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrations", tags=["Integraciones"])


# ── Providers ────────────────────────────────────────────────────────────────

@router.get("/providers")
def api_list_providers(_: TokenData = Depends(check_permission("integraciones.manage"))):
    """Lista proveedores disponibles + resumen de estado últimas 24h."""
    out = []
    for p in list_providers():
        counts = events_repo.count_events_24h(p.provider)
        out.append({
            "provider":    p.provider,
            "label":       p.label,
            "description": p.description,
            "keys": [
                {
                    "key":         k.key,
                    "label":       k.label,
                    "help":        k.help,
                    "is_secret":   k.is_secret,
                    "per_account": k.per_account,
                }
                for k in p.keys.values()
            ],
            "events_24h": counts,
        })
    return {"items": out}


# ── Credenciales ─────────────────────────────────────────────────────────────

class CredentialUpsert(BaseModel):
    key:        str = Field(..., min_length=1, max_length=60)
    value:      str = Field(..., min_length=1, max_length=4096)
    account_id: Optional[str] = Field(None, max_length=120)


@router.get("/{provider}/credentials")
def api_list_credentials(
    provider: str,
    account_id: Optional[str] = Query(None),
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    if not get_provider(provider):
        raise HTTPException(404, f"Provider desconocido: {provider}")
    return {
        "provider": provider.lower(),
        "items":    credentials_repo.list_credentials(provider, account_id),
        "accounts": credentials_repo.list_accounts(provider),
    }


@router.put("/{provider}/credentials")
def api_upsert_credential(
    provider: str,
    payload: CredentialUpsert,
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    if not get_provider(provider):
        raise HTTPException(404, f"Provider desconocido: {provider}")
    account_id = (payload.account_id or GLOBAL_ACCOUNT).strip() or GLOBAL_ACCOUNT
    try:
        row = credentials_repo.upsert_credential(
            provider=provider,
            key=payload.key,
            value=payload.value,
            account_id=account_id,
            updated_by=admin.user_id,
        )
    except CredentialsRepoError as exc:
        raise HTTPException(400, str(exc)) from exc

    events_repo.log_event(
        provider=provider,
        event_type="credential_updated",
        status="ok",
        account_id=account_id,
        raw_payload={"key": payload.key, "by": admin.email},
    )
    return row


@router.delete("/{provider}/credentials/{key}")
def api_delete_credential(
    provider: str,
    key: str,
    account_id: str = Query(GLOBAL_ACCOUNT),
    admin: TokenData = Depends(check_permission("integraciones.manage")),
):
    if not get_provider(provider):
        raise HTTPException(404, f"Provider desconocido: {provider}")
    try:
        existed = credentials_repo.delete_credential(
            provider=provider,
            key=key,
            account_id=account_id,
            deleted_by=admin.user_id,
        )
    except CredentialsRepoError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not existed:
        raise HTTPException(404, "Credencial no encontrada.")

    events_repo.log_event(
        provider=provider,
        event_type="credential_deleted",
        status="ok",
        account_id=account_id,
        raw_payload={"key": key, "by": admin.email},
    )
    return {"message": "Credencial eliminada."}


# ── Eventos / Historial ──────────────────────────────────────────────────────

@router.get("/{provider}/events")
def api_list_events(
    provider: str,
    account_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(ok|error|skipped)$"),
    event_type: Optional[str] = Query(None, max_length=60),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: TokenData = Depends(check_permission("integraciones.manage")),
):
    if not get_provider(provider):
        raise HTTPException(404, f"Provider desconocido: {provider}")
    return {
        "provider": provider.lower(),
        "items": events_repo.list_events(
            provider=provider,
            account_id=account_id,
            status=status,
            event_type=event_type,
            limit=limit,
            offset=offset,
        ),
    }

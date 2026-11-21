"""Repository de credenciales de integraciones externas.

Diseño:
  - Single Responsibility: solo CRUD + cifrado/descifrado. No conoce Meta,
    TikTok ni HTTP.
  - Cifrado at-rest con `secrets_service.encrypt` (Fernet derivado de
    SECRET_KEY). Las keys no-secretas (config plana: nombres, intervalos)
    viajan en claro para poder exponerlas sin descifrar.
  - Las reads NUNCA devuelven el plaintext de un secreto — solo un dict
    público con `has_value`, `mask`, `fingerprint`, `updated_at`.
    Los consumidores que necesitan el plaintext deben llamar
    `get_plaintext()` explícitamente (solo en capa de servicio del
    proveedor, nunca en un router).
  - Trazabilidad: cada upsert registra `updated_by` con el user_id del
    admin y emite una línea de log con el fingerprint del valor — así se
    puede auditar cambios sin exponer el secreto.
"""
from __future__ import annotations

import logging
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db
from app.services.secrets_service import encrypt, decrypt, mask, fingerprint
from app.services.integrations.registry import (
    get_provider,
    is_valid_key,
    key_spec,
)

logger = logging.getLogger(__name__)

GLOBAL_ACCOUNT = "_global"


class CredentialsRepoError(Exception):
    """Errores de negocio del repositorio (no de DB)."""


# ── Lecturas públicas (seguras, sin plaintext) ──────────────────────────────

def _row_to_public(row: dict) -> dict:
    """Serializa una fila para exponer a la UI. Jamás incluye plaintext."""
    is_secret = bool(row["is_secret"])
    if is_secret:
        plain = decrypt(row.get("value_encrypted")) or ""
        return {
            "provider":    row["provider"],
            "account_id":  row["account_id"],
            "key":         row["key"],
            "is_secret":   True,
            "has_value":   bool(plain),
            "mask":        mask(plain) if plain else "",
            "fingerprint": fingerprint(plain) if plain else "",
            "value":       None,
            "updated_at":  row["updated_at"].isoformat() if row["updated_at"] else None,
        }
    return {
        "provider":    row["provider"],
        "account_id":  row["account_id"],
        "key":         row["key"],
        "is_secret":   False,
        "has_value":   row.get("value_plain") is not None,
        "value":       row.get("value_plain"),
        "updated_at":  row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def list_credentials(provider: str, account_id: Optional[str] = None) -> list[dict]:
    """Lista credenciales de un proveedor. No devuelve plaintext."""
    params: list = [provider]
    where = "provider = %s"
    if account_id:
        where += " AND account_id = %s"
        params.append(account_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT provider, account_id, key, is_secret,
                       value_encrypted, value_plain, updated_at
                FROM crm.integrations_credentials
                WHERE {where}
                ORDER BY account_id, key
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row_to_public(r) for r in rows]


def list_accounts(provider: str) -> list[str]:
    """Lista los account_id distintos para un proveedor (para dibujar la UI)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT account_id FROM crm.integrations_credentials "
                "WHERE provider = %s ORDER BY account_id",
                (provider,),
            )
            return [r[0] for r in cur.fetchall()]


# ── Acceso a plaintext (para drivers, nunca para routers) ───────────────────

def get_plaintext(
    provider: str,
    key: str,
    account_id: str = GLOBAL_ACCOUNT,
) -> Optional[str]:
    """Devuelve el plaintext de una credencial. Uso exclusivo de drivers
    del proveedor (meta_service, tiktok_service, ...). Nunca devolverlo
    en respuestas HTTP.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT is_secret, value_encrypted, value_plain
                FROM crm.integrations_credentials
                WHERE provider = %s AND account_id = %s AND key = %s
                """,
                (provider, account_id, key),
            )
            row = cur.fetchone()
    if not row:
        return None
    if row["is_secret"]:
        return decrypt(row["value_encrypted"])
    return row["value_plain"]


# ── Escrituras ──────────────────────────────────────────────────────────────

def upsert_credential(
    provider: str,
    key: str,
    value: Optional[str],
    account_id: str = GLOBAL_ACCOUNT,
    updated_by: Optional[str] = None,
) -> dict:
    """Crea o actualiza una credencial. Valida contra el registry."""
    provider = (provider or "").strip().lower()
    key = (key or "").strip()
    account_id = (account_id or GLOBAL_ACCOUNT).strip() or GLOBAL_ACCOUNT

    spec = key_spec(provider, key)
    if spec is None:
        raise CredentialsRepoError(
            f"Key '{key}' no está permitida para provider '{provider}'."
        )
    if not spec.per_account and account_id != GLOBAL_ACCOUNT:
        raise CredentialsRepoError(
            f"Key '{key}' es global y no admite account_id '{account_id}'."
        )

    # Normalizar value
    v = (value or "").strip() if value is not None else None
    if not v:
        raise CredentialsRepoError("El valor no puede estar vacío. Usa delete para borrar.")

    value_enc: Optional[str] = None
    value_plain: Optional[str] = None
    if spec.is_secret:
        value_enc = encrypt(v)
    else:
        value_plain = v

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO crm.integrations_credentials
                    (provider, account_id, key, value_encrypted, value_plain, is_secret, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s::uuid)
                ON CONFLICT (provider, account_id, key) DO UPDATE SET
                    value_encrypted = EXCLUDED.value_encrypted,
                    value_plain     = EXCLUDED.value_plain,
                    is_secret       = EXCLUDED.is_secret,
                    updated_at      = NOW(),
                    updated_by      = EXCLUDED.updated_by
                RETURNING provider, account_id, key, is_secret,
                          value_encrypted, value_plain, updated_at
                """,
                (provider, account_id, key, value_enc, value_plain, spec.is_secret, updated_by),
            )
            row = cur.fetchone()
        conn.commit()

    # Log con fingerprint — nunca el plaintext
    logger.info(
        "integrations.credentials upsert: provider=%s account=%s key=%s fp=%s by=%s",
        provider, account_id, key, fingerprint(v), updated_by,
    )
    return _row_to_public(row)


def delete_credential(
    provider: str,
    key: str,
    account_id: str = GLOBAL_ACCOUNT,
    deleted_by: Optional[str] = None,
) -> bool:
    """Borra una credencial. Devuelve True si existía."""
    provider = (provider or "").strip().lower()
    account_id = (account_id or GLOBAL_ACCOUNT).strip() or GLOBAL_ACCOUNT
    if not get_provider(provider):
        raise CredentialsRepoError(f"Provider desconocido: '{provider}'.")
    if not is_valid_key(provider, key):
        raise CredentialsRepoError(f"Key '{key}' no permitida para '{provider}'.")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM crm.integrations_credentials "
                "WHERE provider = %s AND account_id = %s AND key = %s RETURNING id",
                (provider, account_id, key),
            )
            existed = cur.fetchone() is not None
        conn.commit()
    logger.info(
        "integrations.credentials delete: provider=%s account=%s key=%s existed=%s by=%s",
        provider, account_id, key, existed, deleted_by,
    )
    return existed

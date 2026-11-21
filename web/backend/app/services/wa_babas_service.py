"""
wa_babas_service.py — Gestion de cuentas empresariales WhatsApp (WABA).

Responsabilidad:
  - CRUD de WABAs con credenciales cifradas (access_token, app_secret,
    webhook verify_token).
  - Resolver credenciales a partir de phone_number_id (para webhook y send).
  - Verificar que un verify_token recibido corresponde a alguna WABA
    registrada (sin ejecutar comparaciones vulnerables a timing).

Clean Code / SOLID:
  - SRP: solo gestiona WABAs. No toca numeros ni Meta API directamente.
  - Cache LRU en memoria — WABAs cambian muy raramente (altas manuales).
  - Decrypt on demand — las credenciales se descifran solo cuando se van
    a usar; la cache guarda ciphertext (menos exposicion en heap).
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db
from app.services.secrets_service import decrypt, encrypt, fingerprint, mask

logger = logging.getLogger(__name__)

# Cache: baba_id (int) -> dict con ciphertexts (no plaintext)
_CACHE_BY_ID: dict[int, dict] = {}
# Cache: phone_number_id (str) -> baba_id (int) para lookup rapido desde webhook
_CACHE_PHONE_TO_BABA: dict[str, int] = {}


def invalidate_cache() -> None:
    """Llamar tras INSERT/UPDATE/DELETE en wa_babas o wa_numbers."""
    _CACHE_BY_ID.clear()
    _CACHE_PHONE_TO_BABA.clear()


def _row_to_public_dict(row) -> dict:
    """Version segura para exponer al frontend — sin ciphertexts ni plaintext."""
    return {
        "id":                 row["id"],
        "waba_id":            row["waba_id"],
        "display_name":       row["display_name"],
        "is_default":         row["is_default"],
        "activo":             row["activo"],
        "notes":              row["notes"],
        "access_token_mask":  mask(decrypt(row["access_token_encrypted"])),
        "has_app_secret":     bool(decrypt(row["app_secret_encrypted"] or "")),
        "has_verify_token":   bool(decrypt(row["webhook_verify_token_encrypted"] or "")),
        "access_token_fp":    fingerprint(decrypt(row["access_token_encrypted"])),
        "created_at":         row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at":         row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _row_to_cache_dict(row) -> dict:
    """Version interna con ciphertexts — para cache, no exponer."""
    return {
        "id":                 row["id"],
        "waba_id":            row["waba_id"],
        "display_name":       row["display_name"],
        "is_default":         row["is_default"],
        "activo":             row["activo"],
        "_access_enc":        row["access_token_encrypted"],
        "_app_secret_enc":    row["app_secret_encrypted"] or "",
        "_verify_token_enc":  row["webhook_verify_token_encrypted"] or "",
    }


def list_all(only_active: bool = False) -> list[dict]:
    """Lista todas las WABAs (version publica — sin secretos)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if only_active:
                cur.execute(
                    """
                    SELECT * FROM crm.wa_babas
                    WHERE activo = TRUE
                    ORDER BY is_default DESC, display_name ASC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM crm.wa_babas
                    ORDER BY is_default DESC, activo DESC, display_name ASC
                    """
                )
            return [_row_to_public_dict(r) for r in cur.fetchall()]


def get_by_id(baba_id: int) -> Optional[dict]:
    """Retorna la version publica (sin secretos) para UI."""
    if not baba_id:
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM crm.wa_babas WHERE id = %s", (baba_id,))
            row = cur.fetchone()
    return _row_to_public_dict(row) if row else None


def _get_cache_by_id(baba_id: int) -> Optional[dict]:
    """Version interna con ciphertexts — cacheada."""
    if baba_id in _CACHE_BY_ID:
        return _CACHE_BY_ID[baba_id]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM crm.wa_babas WHERE id = %s", (baba_id,))
            row = cur.fetchone()
    if not row:
        return None
    data = _row_to_cache_dict(row)
    _CACHE_BY_ID[baba_id] = data
    return data


def get_baba_for_phone(phone_number_id: str) -> Optional[dict]:
    """Dado un phone_number_id de Meta, retorna la WABA que lo aloja.

    Version interna (con ciphertexts) — usada por webhook y send para
    resolver credenciales. Cachea el lookup phone→baba_id.
    """
    if not phone_number_id:
        return None
    cached_baba_id = _CACHE_PHONE_TO_BABA.get(phone_number_id)
    if cached_baba_id:
        return _get_cache_by_id(cached_baba_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT b.*
                FROM crm.wa_numbers n
                JOIN crm.wa_babas b ON b.id = n.waba_id_ref
                WHERE n.phone_number_id = %s
                """,
                (phone_number_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    _CACHE_PHONE_TO_BABA[phone_number_id] = row["id"]
    data = _row_to_cache_dict(row)
    _CACHE_BY_ID[row["id"]] = data
    return data


def get_baba_by_wa_number_id(wa_number_id: int) -> Optional[dict]:
    """Dado el id local de un numero (crm.wa_numbers.id), retorna la WABA
    asociada. Diferente a get_baba_for_phone(phone_number_id) — este recibe
    el ID interno de la tabla, no el phone_number_id de Meta.

    Pensado para endpoints de UI donde el frontend pasa el wa_number_id
    de la conversacion (entero local, no el string de Meta).
    """
    if not wa_number_id:
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT b.*
                FROM crm.wa_numbers n
                JOIN crm.wa_babas b ON b.id = n.waba_id_ref
                WHERE n.id = %s
                """,
                (wa_number_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    data = _row_to_cache_dict(row)
    _CACHE_BY_ID[row["id"]] = data
    return data


def get_default_baba() -> Optional[dict]:
    """WABA default activa (para envios sin contexto de numero). Con ciphertexts."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM crm.wa_babas
                WHERE activo = TRUE
                ORDER BY is_default DESC, id ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    if not row:
        return None
    data = _row_to_cache_dict(row)
    _CACHE_BY_ID[row["id"]] = data
    return data


def get_access_token(baba: dict) -> Optional[str]:
    """Descifra el access_token de un baba dict (cache dict)."""
    return decrypt(baba.get("_access_enc"))


def get_app_secret(baba: dict) -> Optional[str]:
    """Descifra el app_secret."""
    return decrypt(baba.get("_app_secret_enc"))


def get_verify_token(baba: dict) -> Optional[str]:
    """Descifra el webhook verify_token."""
    return decrypt(baba.get("_verify_token_enc"))


def find_baba_by_verify_token(incoming_token: str) -> Optional[dict]:
    """Escanea todas las WABAs activas y retorna la que tenga ese verify_token.

    Usado en el endpoint GET /webhook cuando Meta verifica. No cacheamos por
    token para no exponer el mapa en memoria — este path se invoca una sola
    vez por registro de webhook.
    """
    if not incoming_token:
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM crm.wa_babas
                WHERE activo = TRUE
                """
            )
            rows = cur.fetchall()
    for row in rows:
        stored = decrypt(row["webhook_verify_token_encrypted"] or "")
        if stored and hmac.compare_digest(stored, incoming_token):
            return _row_to_cache_dict(row)
    return None


def create(
    waba_id: str,
    display_name: str,
    access_token: str,
    app_secret: str = "",
    webhook_verify_token: str = "",
    notes: Optional[str] = None,
    set_as_default: bool = False,
) -> int:
    """Registra una WABA nueva. Retorna el id creado."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if set_as_default:
                cur.execute(
                    "UPDATE crm.wa_babas SET is_default = FALSE WHERE is_default = TRUE"
                )
            cur.execute(
                """
                INSERT INTO crm.wa_babas
                    (waba_id, display_name, access_token_encrypted,
                     app_secret_encrypted, webhook_verify_token_encrypted,
                     is_default, activo, notes)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                RETURNING id
                """,
                (
                    waba_id.strip(),
                    display_name.strip(),
                    encrypt(access_token),
                    encrypt(app_secret),
                    encrypt(webhook_verify_token),
                    set_as_default,
                    notes,
                ),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
    invalidate_cache()
    return new_id


def update(
    baba_id: int,
    *,
    display_name: Optional[str] = None,
    access_token: Optional[str] = None,
    app_secret: Optional[str] = None,
    webhook_verify_token: Optional[str] = None,
    activo: Optional[bool] = None,
    notes: Optional[str] = None,
) -> bool:
    """Update parcial. Si un secreto es None se preserva, si es string vacio
    se borra, si trae valor se re-cifra.
    """
    fields = []
    values = []
    if display_name is not None:
        fields.append("display_name = %s")
        values.append(display_name.strip())
    if access_token is not None:
        fields.append("access_token_encrypted = %s")
        values.append(encrypt(access_token))
    if app_secret is not None:
        fields.append("app_secret_encrypted = %s")
        values.append(encrypt(app_secret))
    if webhook_verify_token is not None:
        fields.append("webhook_verify_token_encrypted = %s")
        values.append(encrypt(webhook_verify_token))
    if activo is not None:
        fields.append("activo = %s")
        values.append(activo)
    if notes is not None:
        fields.append("notes = %s")
        values.append(notes)
    if not fields:
        return False

    fields.append("updated_at = NOW()")
    values.append(baba_id)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE crm.wa_babas SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )
            updated = cur.rowcount
        conn.commit()
    invalidate_cache()
    return updated > 0


def set_default(baba_id: int) -> bool:
    """Marca una WABA como default (atomico — desmarca las demas)."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE crm.wa_babas SET is_default = FALSE "
                    "WHERE is_default = TRUE AND id <> %s",
                    (baba_id,),
                )
                cur.execute(
                    "UPDATE crm.wa_babas SET is_default = TRUE, updated_at = NOW() "
                    "WHERE id = %s AND activo = TRUE",
                    (baba_id,),
                )
                updated = cur.rowcount
            conn.commit()
        invalidate_cache()
        return updated > 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("wa_babas: fallo set_default(%s): %s", baba_id, exc)
        return False


def count_numbers(baba_id: int) -> int:
    """Cuantos numeros propios pertenecen a esta WABA."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM crm.wa_numbers WHERE waba_id_ref = %s",
                (baba_id,),
            )
            return cur.fetchone()[0]


def delete(baba_id: int) -> bool:
    """Elimina una WABA. La DB bloquea el delete si tiene numeros asociados
    (ON DELETE RESTRICT) — el admin debe reasignar/eliminar numeros primero.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm.wa_babas WHERE id = %s", (baba_id,))
            deleted = cur.rowcount
        conn.commit()
    invalidate_cache()
    return deleted > 0

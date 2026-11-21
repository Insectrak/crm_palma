"""
api_clients_service.py — gestion segura de API keys multi-tenant.

Patron patrón estándar Private Apps:
- Key format: cli_<8charPrefix>_<32charSecret>
- Storage: solo SHA-256 hex de la key completa (nunca plain).
- Validation: timing-safe (hmac.compare_digest), prefix-indexed lookup.
- Revoke: soft (set revoked_at), reusable para audit/forensics.

Tambien provee:
- Rate limit por client (in-memory sliding window 60s).
- Idempotency-Key dedup (cache en DB, 24h).
- IP whitelist check (CIDR support).
- Audit logging (tabla crm.api_client_logs).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)


# ─── Generacion + hash de keys ─────────────────────────────────────────────

KEY_PREFIX = "cli_"
PREFIX_LEN = 8        # chars random despues de "cli_"
SECRET_LEN = 32       # chars random del secret
TOTAL_KEY_LEN = len(KEY_PREFIX) + PREFIX_LEN + 1 + SECRET_LEN   # 'cli_' + 8 + '_' + 32 = 45


def generate_key() -> tuple[str, str, str]:
    """Genera una API key nueva. Devuelve (key_completa, prefix_publico, hash_sha256).

    El prefix_publico incluye 'cli_<8chars>' y se guarda visible en DB/logs.
    El hash es SHA-256 hex de la key completa.
    La key plain se devuelve UNA SOLA VEZ al admin que la crea — luego
    desaparece del backend.
    """
    prefix_random = secrets.token_urlsafe(PREFIX_LEN)[:PREFIX_LEN]
    secret_random = secrets.token_urlsafe(SECRET_LEN * 2)[:SECRET_LEN]
    key_full      = f"{KEY_PREFIX}{prefix_random}_{secret_random}"
    key_prefix    = f"{KEY_PREFIX}{prefix_random}"
    key_hash      = hashlib.sha256(key_full.encode("utf-8")).hexdigest()
    return key_full, key_prefix, key_hash


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_prefix(key: str) -> Optional[str]:
    """Extrae el prefix publico ('cli_xxxxxxxx') de una key recibida.
    Devuelve None si el formato no coincide."""
    if not key or not key.startswith(KEY_PREFIX):
        return None
    parts = key.split("_")
    if len(parts) < 3:
        return None
    return f"{KEY_PREFIX}{parts[1]}"


# ─── Validacion (lookup + timing-safe compare) ──────────────────────────────

class ApiClientAuthError(Exception):
    """Auth fallo: key invalida, expirada, revocada, IP no permitida."""
    def __init__(self, msg: str, code: int = 401):
        super().__init__(msg)
        self.code = code


def authenticate(key: str, request_ip: Optional[str] = None) -> dict:
    """Valida la key recibida contra la DB.

    Retorna el row del api_client si todo OK.
    Raises ApiClientAuthError con codigo HTTP apropiado en cualquier fallo.
    """
    prefix = parse_prefix(key)
    if not prefix:
        raise ApiClientAuthError("API key con formato invalido.", 401)

    incoming_hash = hash_key(key)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Lookup por prefix (indexed) — devuelve a lo mas 1-2 candidatos
            cur.execute(
                "SELECT * FROM crm.api_clients WHERE api_key_prefix = %s",
                (prefix,),
            )
            candidates = cur.fetchall()

    if not candidates:
        raise ApiClientAuthError("API key invalida.", 401)

    # Timing-safe compare contra cada candidato (raro tener mas de 1)
    matched = None
    for c in candidates:
        if hmac.compare_digest(c["api_key_hash"], incoming_hash):
            matched = c
            break

    if not matched:
        raise ApiClientAuthError("API key invalida.", 401)

    # Estado del client
    if matched.get("revoked_at"):
        raise ApiClientAuthError("API key revocada.", 401)
    if not matched.get("activo"):
        raise ApiClientAuthError("API key desactivada.", 401)
    expires_at = matched.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise ApiClientAuthError("API key expirada.", 401)

    # IP whitelist (si esta configurada)
    whitelist = matched.get("ip_whitelist")
    if whitelist is not None and len(whitelist) > 0:
        if not request_ip:
            raise ApiClientAuthError("IP no detectada (whitelist activa).", 403)
        if not _ip_in_any_cidr(request_ip, whitelist):
            raise ApiClientAuthError(f"IP {request_ip} no esta en la whitelist.", 403)

    return dict(matched)


def _ip_in_any_cidr(ip: str, whitelist: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in whitelist:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if addr == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False


# ─── Rate limit por client (sliding window in-memory) ──────────────────────
# Para load balancing real conviene Redis, pero en single-instance esto basta.

_rate_buckets: dict[str, list[float]] = {}


def check_rate_limit(client_id: str, limit_per_minute: int) -> tuple[bool, int]:
    """Devuelve (permitido, requests_restantes).
    Sliding window de 60 segundos."""
    now = time.time()
    cutoff = now - 60
    bucket = _rate_buckets.setdefault(client_id, [])
    # Drop entradas viejas (mantenemos lista chica)
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit_per_minute:
        return False, 0
    bucket.append(now)
    return True, max(0, limit_per_minute - len(bucket))


# ─── Idempotency-Key (DB cache, 24h) ───────────────────────────────────────

def get_idempotent_response(client_id: str, idem_key: str) -> Optional[dict]:
    """Si ya existe una respuesta cacheada para esta key + client en las ultimas
    24h, devuelve el dict. Sino None."""
    if not idem_key:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT response_json FROM crm.api_client_idempotency
                WHERE api_client_id = %s::uuid AND idempotency_key = %s
                  AND created_at >= %s
                LIMIT 1
                """,
                (client_id, idem_key, cutoff),
            )
            row = cur.fetchone()
            return row["response_json"] if row else None


def store_idempotent_response(client_id: str, idem_key: str, response: dict) -> None:
    if not idem_key:
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crm.api_client_idempotency
                    (api_client_id, idempotency_key, response_json)
                VALUES (%s::uuid, %s, %s::jsonb)
                ON CONFLICT (api_client_id, idempotency_key) DO NOTHING
                """,
                (client_id, idem_key, json.dumps(response)),
            )
        conn.commit()


# ─── Audit log ─────────────────────────────────────────────────────────────

def log_request(
    *,
    client_id: Optional[str],
    api_key_prefix: Optional[str],
    ip: Optional[str],
    method: str,
    path: str,
    status_code: int,
    lead_id: Optional[int] = None,
    duplicated: bool = False,
    error_msg: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    request_size: Optional[int] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Persiste una linea de audit para forensics / deteccion de abuso.
    Best-effort: si falla, no rompe el flujo principal."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm.api_client_logs
                        (api_client_id, api_key_prefix, ip, method, path, status_code,
                         lead_id, duplicated, error_msg, idempotency_key,
                         request_size, user_agent)
                    VALUES (%s, %s, %s::inet, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s)
                    """,
                    (
                        client_id, api_key_prefix, ip, method, path[:200], status_code,
                        lead_id, duplicated, (error_msg or "")[:500] or None, idempotency_key,
                        request_size, (user_agent or "")[:300] or None,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("api_client_logs insert fallo: %s", exc)


# ─── Metricas ──────────────────────────────────────────────────────────────

def increment_metrics(
    client_id: str,
    *,
    leads: int = 0,
    duplicados: int = 0,
    rechazados: int = 0,
) -> None:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT crm.increment_api_client_metric(%s::uuid, %s, %s, %s)",
                    (client_id, leads, duplicados, rechazados),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("increment_api_client_metric fallo: %s", exc)

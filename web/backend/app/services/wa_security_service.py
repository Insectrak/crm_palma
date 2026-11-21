"""Servicio de validacion HMAC de webhooks WhatsApp Cloud API.

V070.70 (Bundle C — split de whatsapp.py).

Extrae las funciones de seguridad del router para:
  1. SRP — esta capa SOLO sabe de HMAC + multi-WABA lookup.
  2. Testabilidad — los tests de regresion del HMAC (P0-1) viven aqui.
  3. Reusabilidad — si en el futuro hay otro webhook firmado por Meta,
     usa la misma funcion.

API publica:
  - verify_signature(raw_body, header, secret) -> bool
  - find_verifying_baba(raw_body, header) -> (valido, baba_dict | None)

Las funciones privadas del router (`_signature_matches`, `_find_verifying_baba`)
se mantienen como wrappers delgados que delegan aqui — los callers internos
no cambian. Strangler Pattern para refactor sin breaking changes.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def verify_signature(raw_body: bytes, signature_header: Optional[str], secret: str) -> bool:
    """Compara HMAC-SHA256 contra un app_secret concreto (timing-safe).

    V070.69 (Bundle A — P0-1): defensa contra headers malformados.
    Antes el `.split("=", 1)[1]` levantaba IndexError silencioso si Meta
    enviaba un header sin '=', lo que bypassaba la verificacion HMAC
    (la excepcion se propagaba arriba del bloque de seguridad).
    Ahora rechazamos explicitamente cualquier header invalido.

    Args:
        raw_body: bytes exactos del body recibido (NO el dict parseado —
                  Meta firma sobre el JSON serializado, cualquier reorden
                  invalida la firma).
        signature_header: valor del header `X-Hub-Signature-256` enviado
                          por Meta. Formato esperado: `sha256=<hex>`.
        secret: app_secret de la WABA contra la que comparar.

    Returns:
        True si el HMAC coincide; False en cualquier otro caso (header
        ausente, malformado, secret incorrecto, etc).
    """
    if not signature_header or "=" not in signature_header:
        return False
    prefix, _, received = signature_header.partition("=")
    if not prefix or not received:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def find_verifying_baba(
    raw_body: bytes,
    signature_header: Optional[str],
    *,
    legacy_env_secret: Optional[str] = None,
) -> tuple[bool, Optional[dict]]:
    """Identifica cual WABA registrada firmo este webhook.

    Estrategia (defense in depth para multi-WABA):

    1. Si no hay WABAs registradas: cae a `legacy_env_secret` (env var
       META_WA_APP_SECRET) — soporte para deployments pre-V034 antes
       de la introduccion del catalogo de WABAs.
    2. Si hay WABAs, prueba la firma contra el app_secret de cada una
       (lookup secuencial, hoy O(N) — aceptable con <10 WABAs por tenant).
    3. Si ninguna matchea pero el env tiene app_secret, lo prueba como
       fallback durante migracion.

    Args:
        raw_body: bytes del webhook body.
        signature_header: valor de X-Hub-Signature-256.
        legacy_env_secret: app_secret del env var. Si es None, no se
                           intenta el fallback legacy.

    Returns:
        Tupla (valido, baba_dict). `baba_dict` puede ser None si se
        acepto por el fallback legacy (no hay WABA asociada en DB).
    """
    from app.services import wa_babas_service

    try:
        babas = wa_babas_service.list_all(only_active=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo listar WABAs activas: %s", exc)
        babas = []

    if not babas:
        if legacy_env_secret and verify_signature(raw_body, signature_header, legacy_env_secret):
            return True, None
        return False, None

    for baba in babas:
        app_secret = wa_babas_service.get_app_secret(baba)
        if app_secret and verify_signature(raw_body, signature_header, app_secret):
            return True, baba

    if legacy_env_secret and verify_signature(raw_body, signature_header, legacy_env_secret):
        logger.warning(
            "Webhook valido por env app_secret pero ninguna WABA registrada matcheo. "
            "Revisar config de WABAs en panel."
        )
        return True, None

    return False, None

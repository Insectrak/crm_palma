"""
secrets_service.py — Cifrado simetrico de secretos guardados en DB.

Uso primario:
  - Access tokens, app_secrets y verify_tokens de multiples WhatsApp Business
    Accounts (WABAs) gestionados desde la UI (V034).

Diseño:
  - Clave Fernet derivada de settings.secret_key (HKDF-SHA256). Asi el admin
    no necesita configurar un nuevo env var — cifrado queda atado a la misma
    SECRET_KEY que ya protege los JWT.
  - Si rota SECRET_KEY, los tokens cifrados quedan inservibles. Es el
    trade-off esperado: rotar SECRET_KEY implica re-ingresar los tokens desde
    la UI (que es lo mismo que haria un admin por higiene de seguridad).
  - Fernet usa AES-128-CBC + HMAC-SHA256 (authenticated encryption).

Clean Code / SOLID:
  - SRP: solo cifra/descifra. No conoce WABAs, users, ni DB.
  - Cache de la instancia Fernet (derivada es constante para la vida del proceso).
"""
from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

logger = logging.getLogger(__name__)

# Contexto fijo para el HKDF — nunca cambiar sin plan de migracion,
# cambiarlo invalida todos los tokens cifrados.
#
# V070.68 (Bundle B): el nombre "palmario" en el contexto es legacy historico
# (se eligio cuando el unico cliente era Palma del Rio). NO es un leak de
# multi-tenancy: cada cliente tiene su propio SECRET_KEY (.env por tenant),
# por lo que la clave derivada es unica por deployment. Si cambiamos este
# string ahora, todos los tokens cifrados en `crm.secrets_storage` se vuelven
# indescifrables — requeriria una migracion con re-cipher (leer con KDF viejo,
# re-cifrar con KDF nuevo). No vale el costo: cero impacto funcional y zero
# riesgo de seguridad.
_KDF_INFO = b"crm-palmario:wa-babas:v1"


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Deriva la clave Fernet a partir de SECRET_KEY. Cachea la instancia."""
    raw = (settings.secret_key or "").encode("utf-8")
    if len(raw) < 32:
        # Settings ya valida longitud >= 32, pero defensivamente:
        raise RuntimeError(
            "secrets_service: SECRET_KEY demasiado corta (<32). "
            "Configura una SECRET_KEY robusta en .env."
        )
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"",                 # HKDF sin salt es OK porque la entrada ya es secreta
        info=_KDF_INFO,
    )
    derived = kdf.derive(raw)
    # Fernet requiere la clave en base64 urlsafe de 32 bytes
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(plaintext: str) -> str:
    """Cifra un string UTF-8 y devuelve el token urlsafe listo para DB."""
    if plaintext is None:
        return None
    if not plaintext:
        return ""
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """Descifra. Retorna None si el ciphertext esta vacio o es invalido."""
    if not ciphertext:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error(
            "secrets_service: ciphertext invalido — posible rotacion de "
            "SECRET_KEY o dato corrupto. Re-ingresa el secreto desde la UI."
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception("secrets_service: fallo al descifrar: %s", exc)
        return None


def mask(value: Optional[str], keep: int = 4) -> str:
    """Devuelve una version enmascarada del valor para exponer en logs/UI.

    Ejemplo: 'EAAbcd1234567890xyz' -> '••••7890xyz' (muestra los ultimos `keep`).
    Nunca exponer el plaintext completo en respuestas API.
    """
    if not value:
        return ""
    if len(value) <= keep:
        return "•" * len(value)
    return "•" * 8 + value[-keep:]


def fingerprint(value: Optional[str]) -> str:
    """Huella SHA-256 de 8 chars — sirve para comparar si un secreto cambio
    sin exponerlo. Usado en el endpoint de diagnostico.
    """
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]

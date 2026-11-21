"""Servicio del modo IA del CRM (auto / manual).

V070.70 (Bundle C — split de whatsapp.py).

El modo IA controla si el clasificador automatico actua sobre cada
mensaje entrante o si se requiere intervencion manual del asesor:

  - 'auto'   → el clasificador IA procesa cada mensaje y puede tomar
               acciones (calificar lead, archivar, etc).
  - 'manual' → ningun mensaje se clasifica automaticamente. El asesor
               decide manualmente que hacer con cada conversacion.

El valor se persiste en `public.app_settings` y se cachea en memoria
con TTL 60s para evitar 100 SELECT/min al webhook (un select por mensaje
entrante).

## Multi-worker

El cache es por proceso. Con 2 workers Uvicorn cada uno tiene su propia
copia — un cambio de modo puede tardar hasta 60s en propagarse a todos.
Aceptado: el SLA de cambio de modo no es estricto y un cambio rapido
solo se requiere en emergencias raras.

API publica:
  - load_ia_mode() -> 'auto' | 'manual'
  - invalidate_ia_mode_cache()
"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Constantes que tambien usa whatsapp.py (re-exportadas).
DEFAULT_IA_MODE = "auto"
IA_MODE_KEY = "wa_ia_mode"
VALID_IA_MODES = {"auto", "manual"}
IA_MODE_TTL_SEC = 60

# Cache simple por proceso. Multi-worker: cada uno tiene su copia.
_cache: dict = {"value": None, "expires_at": 0.0}


def load_ia_mode() -> str:
    """Lee el modo actual desde public.app_settings. Default: 'auto'.

    Falla silenciosamente al default si la tabla no existe o hay error —
    preferimos perder una decision de 'manual' antes que tumbar el webhook
    cuando entra un mensaje del cliente final.
    """
    now = time.time()
    cached_value = _cache.get("value")
    if cached_value and now < _cache["expires_at"]:
        return cached_value

    mode = DEFAULT_IA_MODE
    try:
        from app.database import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = %s",
                    (IA_MODE_KEY,),
                )
                row = cur.fetchone()
                if row and isinstance(row[0], dict):
                    candidate = row[0].get("mode")
                    if candidate in VALID_IA_MODES:
                        mode = candidate
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("No se pudo leer wa_ia_mode: %s", exc)

    _cache["value"] = mode
    _cache["expires_at"] = now + IA_MODE_TTL_SEC
    return mode


def invalidate_ia_mode_cache() -> None:
    """Fuerza reload en el proximo load_ia_mode().

    Llamar despues de un PUT /api/whatsapp/ia-mode para que el cambio
    se vea inmediato (no tras esperar 60s del TTL).
    """
    _cache["value"] = None
    _cache["expires_at"] = 0.0

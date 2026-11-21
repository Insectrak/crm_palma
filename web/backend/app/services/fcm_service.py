"""
fcm_service.py — Push instantaneo via Firebase Cloud Messaging.

Responsabilidad:
  - Inicializar Firebase Admin SDK (lazy, una sola vez)
  - Registrar/desregistrar tokens FCM por usuario
  - Enviar notificaciones a todos los dispositivos de un usuario
  - Limpiar tokens invalidos automaticamente

Requiere:
  - FCM_ENABLED=true en .env
  - FCM_SERVICE_ACCOUNT_B64=service account JSON codificado en base64
  - Tabla auth.user_fcm_tokens (V022_fcm_tokens.sql)
"""
import json
import logging
from typing import Optional

from app.config import settings
from app.database import get_db
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_firebase_app = None
_init_attempted = False
_init_error: Optional[str] = None  # ultima razon de fallo (visible al admin)

# Cache de config (TTL 60s, invalidable en hot-reload por PUT)
_FCM_CONFIG_CACHE: dict = {"value": None, "fetched_at": 0.0}
_FCM_CONFIG_TTL_SECONDS = 60.0


def load_fcm_config() -> dict:
    """Carga la config FCM desde public.app_settings con cache TTL.

    Devuelve {enabled, service_account_b64} con la credencial DECRIPTADA.
    Override pattern: si la DB tiene credencial → la usa; sino → fallback al
    env var (settings.fcm_*). Asi el admin puede pisar la config del .env
    desde la UI sin tocar EasyPanel."""
    import time
    now = time.monotonic()
    cached = _FCM_CONFIG_CACHE["value"]
    if cached is not None and (now - _FCM_CONFIG_CACHE["fetched_at"]) < _FCM_CONFIG_TTL_SECONDS:
        return cached

    out = {
        "enabled":              bool(settings.fcm_enabled),
        "service_account_b64":  (settings.fcm_service_account_b64 or "").strip(),
        "source":               "env",
    }
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'fcm_credentials'"
                )
                row = cur.fetchone()
                if row and isinstance(row[0], dict):
                    saved = row[0]
                    if "enabled" in saved:
                        out["enabled"] = bool(saved.get("enabled"))
                    enc = (saved.get("service_account_b64_encrypted") or "").strip()
                    if enc:
                        try:
                            from app.services.secrets_service import decrypt
                            plain = decrypt(enc) or ""
                            if plain:
                                out["service_account_b64"] = plain
                                out["source"] = "db"
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("FCM: decrypt fallo (uso env como fallback): %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_fcm_config: fallback a env (%s)", exc)

    _FCM_CONFIG_CACHE["value"] = out
    _FCM_CONFIG_CACHE["fetched_at"] = now
    return out


def invalidate_fcm_config_cache() -> None:
    """Invalida cache de config + fuerza re-init de Firebase Admin SDK
    en el proximo send. Llamar desde PUT /api/settings/fcm cuando se
    cambia la credencial — sino el contenedor seguiria usando la app
    inicializada con la credencial vieja hasta restart."""
    global _firebase_app, _init_attempted, _init_error
    _FCM_CONFIG_CACHE["value"] = None
    _FCM_CONFIG_CACHE["fetched_at"] = 0.0
    # Tear down de la app vieja para que la nueva credencial entre
    if _firebase_app is not None:
        try:
            import firebase_admin
            firebase_admin.delete_app(_firebase_app)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FCM: delete_app fallo: %s", exc)
    _firebase_app = None
    _init_attempted = False
    _init_error = None


def _init_firebase() -> bool:
    """Inicializa Firebase Admin SDK con la credencial actual (DB > env).
    Retorna True si esta listo. Cachea fallos via _init_attempted para
    no reintentar en cada push hasta que se invalide el cache."""
    global _firebase_app, _init_attempted, _init_error
    if _firebase_app is not None:
        return True
    if _init_attempted:
        return False
    _init_attempted = True

    cfg = load_fcm_config()
    if not cfg["enabled"] or not cfg["service_account_b64"]:
        _init_error = "FCM deshabilitado o sin service account configurado"
        logger.info(_init_error)
        return False

    try:
        import base64
        import firebase_admin
        from firebase_admin import credentials

        decoded = base64.b64decode(cfg["service_account_b64"]).decode("utf-8")
        service_account = json.loads(decoded)
        cred = credentials.Certificate(service_account)
        _firebase_app = firebase_admin.initialize_app(cred)
        _init_error = None
        logger.info(
            "Firebase Admin SDK inicializado correctamente (source=%s)",
            cfg.get("source", "unknown"),
        )
        return True
    except Exception as e:
        _init_error = f"{type(e).__name__}: {str(e)[:200]}"
        logger.error("Error inicializando Firebase Admin SDK: %s", e)
        return False


def get_init_status() -> dict:
    """Devuelve el estado actual de init (para health check del UI)."""
    cfg = load_fcm_config()
    return {
        "enabled":            cfg["enabled"],
        "has_credentials":    bool(cfg["service_account_b64"]),
        "credential_source":  cfg.get("source", "env"),
        "initialized":        _firebase_app is not None,
        "last_error":         _init_error,
    }


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def register_token(user_id: str, fcm_token: str, device_info: str = "") -> bool:
    """Registra o actualiza un token FCM para un usuario.

    Si el token ya existe para otro usuario (cambio de sesion en el mismo
    dispositivo), se reasigna al nuevo usuario.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.user_fcm_tokens (user_id, fcm_token, device_info, updated_at)
                    VALUES (%s::uuid, %s, %s, NOW())
                    ON CONFLICT (fcm_token)
                    DO UPDATE SET user_id = EXCLUDED.user_id,
                                  device_info = EXCLUDED.device_info,
                                  updated_at = NOW()
                    """,
                    (user_id, fcm_token, device_info),
                )
            conn.commit()
        logger.info("FCM token registrado para user %s", user_id[:8])
        return True
    except Exception as e:
        logger.warning("Error registrando FCM token: %s", e)
        return False


def unregister_token(fcm_token: str) -> bool:
    """Elimina un token FCM (logout)."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM auth.user_fcm_tokens WHERE fcm_token = %s",
                    (fcm_token,),
                )
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Error eliminando FCM token: %s", e)
        return False


def _get_tokens(user_id: str) -> list[str]:
    """Obtiene todos los tokens FCM activos de un usuario."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT fcm_token FROM auth.user_fcm_tokens WHERE user_id = %s::uuid",
                    (user_id,),
                )
                return [row["fcm_token"] for row in cur.fetchall()]
    except Exception as e:
        logger.warning("Error obteniendo FCM tokens para %s: %s", user_id[:8], e)
        return []


def _remove_invalid_token(token: str) -> None:
    """Elimina un token que Firebase reporto como invalido."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM auth.user_fcm_tokens WHERE fcm_token = %s",
                    (token,),
                )
            conn.commit()
        logger.info("FCM token invalido eliminado: %s...", token[:20])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send(user_id: str, title: str, body: str, data: Optional[dict] = None) -> bool:
    """Envia push FCM a todos los dispositivos del usuario.

    Retorna True si al menos un envio fue exitoso.
    Limpia automaticamente tokens invalidos.

    Config para meet "estandar internacional" de delivery realtime:
      - priority="high"         → bypass battery saver / Doze (Android 6+)
      - direct_boot_ok=True     → entrega aun antes del unlock post-reboot
      - ttl=1h                  → si el dispositivo esta offline >1h, descartar
                                  (no acumular notifs viejas que aparecen
                                  todas juntas cuando el user abre la app)
      - notification.priority="max" → max importance al render
    """
    import time as _time
    t0 = _time.perf_counter()

    if not _init_firebase():
        # V070.76 — SLI counter para Grafana panel "FCM Push Notifications".
        try:
            from app.metrics import fcm_push_sent
            fcm_push_sent.labels(result="not_configured").inc()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("FCM: send abortado — Firebase no inicializado (user=%s)", user_id[:8])
        return False

    tokens = _get_tokens(user_id)
    if not tokens:
        try:
            from app.metrics import fcm_push_sent
            fcm_push_sent.labels(result="no_token").inc()
        except Exception:  # noqa: BLE001
            pass
        logger.info("FCM: skip send — sin tokens para user=%s", user_id[:8])
        return False

    try:
        from datetime import timedelta as _td
        from firebase_admin import messaging

        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            tokens=tokens,
            android=messaging.AndroidConfig(
                priority="high",
                ttl=_td(hours=1),
                direct_boot_ok=True,
                notification=messaging.AndroidNotification(
                    channel_id="crm-leads",
                    priority="max",
                    default_sound=True,
                    default_vibrate_timings=True,
                ),
            ),
        )

        response = messaging.send_each_for_multicast(message)
        elapsed_ms = int((_time.perf_counter() - t0) * 1000)

        # Limpiar tokens invalidos
        invalid_count = 0
        for i, send_response in enumerate(response.responses):
            if send_response.exception:
                exc = send_response.exception
                # Token expirado, invalido o desregistrado
                code = getattr(exc, "code", "")
                if code in (
                    "NOT_FOUND",
                    "UNREGISTERED",
                    "INVALID_ARGUMENT",
                    "messaging/registration-token-not-registered",
                ):
                    _remove_invalid_token(tokens[i])
                    invalid_count += 1

        # V070.76 — SLI counter por cada token individual del multicast,
        # asi sabemos exacto en Grafana cuantos pushes salieron y cuantos
        # fallaron por que motivo.
        try:
            from app.metrics import fcm_push_sent
            fcm_push_sent.labels(result="success").inc(response.success_count)
            if invalid_count > 0:
                fcm_push_sent.labels(result="token_invalid").inc(invalid_count)
            other_failures = (
                response.failure_count - invalid_count
                if response.failure_count > invalid_count else 0
            )
            if other_failures > 0:
                fcm_push_sent.labels(result="fcm_error").inc(other_failures)
        except Exception:  # noqa: BLE001
            pass

        if response.success_count > 0:
            logger.info(
                "FCM enviado: user=%s tokens=%d ok=%d invalid=%d elapsed=%dms",
                user_id[:8], len(tokens), response.success_count,
                invalid_count, elapsed_ms,
            )
            return True
        else:
            logger.warning(
                "FCM falla: 0/%d enviados user=%s invalid=%d elapsed=%dms",
                len(tokens), user_id[:8], invalid_count, elapsed_ms,
            )
            return False

    except Exception as e:
        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        try:
            from app.metrics import fcm_push_sent
            fcm_push_sent.labels(result="exception").inc()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "FCM send error user=%s elapsed=%dms err=%s",
            user_id[:8], elapsed_ms, e,
        )
        return False

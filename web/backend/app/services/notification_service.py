"""
notification_service.py — Envio de notificaciones push via FCM.

Capas:
  - Storage: templates persistidos en public.app_settings (key=notifications_config).
    Cada evento tiene title + body con variables tipo {lead_name}, {fuente}.
  - Render: substitucion segura de variables (no usa .format directo —
    keys faltantes no rompen).
  - Send: delega a fcm_service.send (que ya maneja init lazy + token cleanup).

Eventos soportados:
  - lead_created     → asesor recibio un lead nuevo
  - lead_reassigned  → asesor recibio un lead reasignado
  - wa_message_inbound → cliente respondio en un chat asignado al asesor

API publica:
  - notify_new_lead       (legacy wrapper)
  - notify_lead_reassigned(legacy wrapper)
  - notify_wa_message_inbound (nuevo, V040)
  - notify(event_type, recipient_user_id, context, sound=True) — generica
  - load_templates() / invalidate_templates_cache() — config IO
"""
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.database import get_db
from app.services import fcm_service

logger = logging.getLogger(__name__)

# V070.52 — Rate limiter sliding-window con tail-aggregation.
# Patron patrón estándar para evitar avalancha de pushes cuando la
# rotacion automatica reparte muchos leads al mismo asesor en segundos.
# Comportamiento:
#   - Permite hasta MAX_PER_WINDOW pushes en una ventana de WINDOW_SECONDS
#   - Los pushes excedentes se suprimen y se cuentan en `suppressed`
#   - Al pasar la ventana, el siguiente push permitido incluye un sufijo
#     "(+N notificaciones mas en cola)" para que el asesor sepa que
#     hay mas leads esperando en la app.
_BURST_LOCK = threading.Lock()
_BURST_STATE: dict = {}  # user_id -> {"ts": [monotonic], "suppressed": int}
_BURST_WINDOW_SECONDS = 60.0
_BURST_MAX_PER_WINDOW = 3


# ── Templates por evento — defaults seguros ──────────────────────────────

_TEMPLATE_DEFAULTS: dict = {
    "lead_created": {
        "enabled": True,
        "title":   "Nuevo lead asignado",
        "body":    "{lead_name}",  # opcional: " ({fuente})" se agrega si fuente
    },
    # V075 — push agregada cuando llegan >=3 leads en ventana corta.
    # Enviada por notification_coalescer.flush_due() (no por notify_new_lead).
    # Patron patrón premium/correo profesional anti-spam.
    "leads_batch": {
        "enabled": True,
        "title":   "{count} leads nuevos asignados",
        "body":    "{breakdown}",  # ej. "3 Facebook · 2 Instagram"
    },
    "lead_reassigned": {
        "enabled": True,
        "title":   "Lead reasignado",
        "body":    "{lead_name}",
    },
    "lead_recontacto": {
        "enabled": True,
        "title":   "{lead_name} volvió a interesarse",
        "body":    "Vino de nuevo via {fuente}",
    },
    "wa_message_inbound": {
        "enabled": True,
        "title":   "Nuevo mensaje de {contact_name}",
        "body":    "{message_preview}",
    },
    # V070.78 (ADR-0010) — Team Circuit Breaker
    "team_blocked": {
        "enabled": True,
        "title":   "Tu equipo esta BLOQUEADO",
        "body":    "{asesores_pausados}/{total_asesores} asesores pausados. Los nuevos leads van a otros equipos. Activa asesores para volver a recibir.",
    },
    "team_unblocked": {
        "enabled": True,
        "title":   "Tu equipo volvio a estar ACTIVO",
        "body":    "{asesores_pausados}/{total_asesores} asesores pausados. Ya estas recibiendo leads nuevos.",
    },
    # Alerta inmediata a supervisores cuando ingresa un lead a su equipo
    "lead_created_supervisor": {
        "enabled": True,
        "title":   "Nuevo lead en tu equipo",
        "body":    "{lead_name} asignado a {asesor_name}",
    },
    # Alerta de llamada programada (1 hora de anticipación)
    "llamada_programada": {
        "enabled": True,
        "title":   "📞 Llamada programada en 1 hora",
        "body":    "{lead_name} · {hora} ({detalle})",
    },
    # Alerta de cita programada (1 hora de anticipación)
    "cita_programada": {
        "enabled": True,
        "title":   "📅 Cita programada en 1 hora",
        "body":    "{lead_name} · {hora} ({detalle})",
    },
}

# V070.51 — Quiet hours: rango horario donde NO se envia push para no
# perturbar al asesor fuera del horario laboral. Paridad CRMs profesionales.
# Default: 21:00 a 08:00 hora Lima. Los eventos en URGENT_EVENTS son
# excepcion (cliente esperando respuesta — debe llegar siempre).
_QUIET_HOURS_DEFAULT = {
    "enabled": True,
    "start": "21:00",  # 9pm
    "end":   "08:00",  # 8am
}
# V070.87 — 'lead_created' tambien es URGENT (paridad con CRMs profesionales).
# Razon: un lead nuevo es una oportunidad comercial fresca cuyo valor
# decae rapido (estudios de Harvard Business Review y Lead Connect: las
# probabilidades de cerrar caen >80% si la primera respuesta tarda mas
# de 1 hora; >97% si tarda mas de 24h). Si el lead llega a las 23:00 y
# el asesor se entera al dia siguiente 08:00, la conversion se desploma.
# Trade-off: el asesor puede recibir push de madrugada. Mitigacion:
#   - Kill switch personal (load_user_prefs.push_enabled = False)
#   - Opt-out solo de 'lead_created' (events_disabled incluye el evento)
#   - El sistema operativo agrupa visualmente notifs de la misma app
#     (no spam real al lock screen, sino un solo grupo expandible)
URGENT_EVENTS = frozenset({
    "wa_message_inbound",       # cliente esperando respuesta en chat
    "lead_created",             # oportunidad comercial fresca - cada minuto cuenta
    "lead_created_supervisor",  # alerta al supervisor sobre nuevo lead en su equipo
    "leads_batch",              # V075 — bundle de oportunidades igual de urgent
    "llamada_programada",       # compromiso agendado con cliente en 1 hora
    "cita_programada",          # cita agendada con cliente en 1 hora
})

LIMA_TZ = timezone(timedelta(hours=-5))

# Variables disponibles por evento — el frontend las muestra en el editor
_TEMPLATE_VARIABLES: dict = {
    "lead_created":            ["lead_name", "fuente"],
    "lead_created_supervisor": ["lead_name", "asesor_name", "fuente"],
    "leads_batch":             ["count", "breakdown"],
    "lead_reassigned":         ["lead_name"],
    "lead_recontacto":         ["lead_name", "lead_id", "fuente", "campana"],
    "wa_message_inbound":      ["contact_name", "message_preview", "wa_phone"],
    "team_blocked":            ["total_asesores", "asesores_pausados", "pct_pausados"],
    "team_unblocked":          ["total_asesores", "asesores_pausados", "pct_pausados"],
    "llamada_programada":      ["lead_name", "lead_id", "hora", "detalle", "telefono"],
    "cita_programada":         ["lead_name", "lead_id", "hora", "detalle", "telefono"],
}

_CONFIG_CACHE: dict = {"value": None, "fetched_at": 0.0}
_CONFIG_TTL_SECONDS = 60.0


def load_templates() -> dict:
    """Carga templates desde public.app_settings con cache TTL.

    Devuelve dict {event_type: {enabled, title, body}}, mergeando los
    valores guardados sobre los defaults (asi nuevos eventos quedan
    activos por default sin migracion manual).
    """
    now = time.monotonic()
    cached = _CONFIG_CACHE["value"]
    if cached is not None and (now - _CONFIG_CACHE["fetched_at"]) < _CONFIG_TTL_SECONDS:
        return cached

    # Deep-copy defaults (no mutar)
    out = {k: dict(v) for k, v in _TEMPLATE_DEFAULTS.items()}
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'notifications_config'"
                )
                row = cur.fetchone()
                if row and isinstance(row[0], dict):
                    saved_events = (row[0] or {}).get("events") or {}
                    for event_type, tpl in saved_events.items():
                        if event_type in out and isinstance(tpl, dict):
                            out[event_type].update(tpl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_templates: fallback a defaults (%s)", exc)

    _CONFIG_CACHE["value"] = out
    _CONFIG_CACHE["fetched_at"] = now
    return out


def load_quiet_hours() -> dict:
    """Devuelve {enabled, start, end} de horarios silenciosos.

    Se persiste en public.app_settings.notifications_config bajo la key
    'quiet_hours'. Default: 21:00-08:00 Lima.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'notifications_config'"
                )
                row = cur.fetchone()
                if row and isinstance(row[0], dict):
                    qh = (row[0] or {}).get("quiet_hours")
                    if isinstance(qh, dict):
                        return {**_QUIET_HOURS_DEFAULT, **qh}
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_quiet_hours: fallback a defaults (%s)", exc)
    return dict(_QUIET_HOURS_DEFAULT)


def _is_quiet_hour_now(quiet_cfg: Optional[dict] = None) -> bool:
    """True si la hora actual (Lima) cae dentro del rango quiet_hours.

    Soporta rangos cruzando medianoche (ej: start=21:00 end=08:00). Si
    quiet_hours.enabled es False, siempre retorna False.
    """
    cfg = quiet_cfg if quiet_cfg is not None else load_quiet_hours()
    if not cfg.get("enabled", True):
        return False
    try:
        s_h, s_m = (int(x) for x in (cfg.get("start") or "21:00").split(":"))
        e_h, e_m = (int(x) for x in (cfg.get("end") or "08:00").split(":"))
    except (ValueError, AttributeError):
        return False
    now = datetime.now(LIMA_TZ)
    now_min = now.hour * 60 + now.minute
    start_min = s_h * 60 + s_m
    end_min = e_h * 60 + e_m
    if start_min == end_min:
        return False
    if start_min < end_min:
        # Rango simple dentro del mismo dia
        return start_min <= now_min < end_min
    # Rango cruza medianoche (ej 21:00 - 08:00)
    return now_min >= start_min or now_min < end_min


# V070.53 — Preferencias por usuario (fase 3).
# Cada asesor puede override:
#   - push_enabled: kill switch personal
#   - quiet_hours_*: rango horario propio (NULL = heredar global)
#   - events_disabled: lista de event_types donde no quiere push

def load_user_prefs(user_id: str) -> dict:
    """Carga preferencias del usuario. Si no existe fila, devuelve defaults
    'use el global'. Nunca levanta — robusto a tabla ausente."""
    if not user_id:
        return _user_prefs_defaults()
    # V070.64 — RealDictCursor explicito + acceso por nombre de columna.
    # Antes usaba row[0], row[1], etc. que rompe si alguien cambia el
    # cursor factory. Mismo bug que cazamos en lead_recapture (KeyError: 0).
    # V073 — Incluye urgent_events_disabled (override del bypass URGENT).
    try:
        from psycopg2.extras import RealDictCursor
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT push_enabled, quiet_hours_enabled,
                           quiet_hours_start, quiet_hours_end,
                           events_disabled,
                           urgent_events_disabled
                      FROM auth.user_notification_prefs
                     WHERE user_id = %s::uuid
                    """,
                    (str(user_id),),
                )
                row = cur.fetchone()
                if not row:
                    return _user_prefs_defaults()
                events_disabled = row["events_disabled"] or []
                if not isinstance(events_disabled, list):
                    events_disabled = []
                urgent_events_disabled = row.get("urgent_events_disabled") or []
                if not isinstance(urgent_events_disabled, list):
                    urgent_events_disabled = []
                return {
                    "push_enabled":           bool(row["push_enabled"]),
                    "quiet_hours_enabled":    row["quiet_hours_enabled"],  # bool o None
                    "quiet_hours_start":      row["quiet_hours_start"],    # HH:MM o None
                    "quiet_hours_end":        row["quiet_hours_end"],      # HH:MM o None
                    "events_disabled":        events_disabled,
                    "urgent_events_disabled": urgent_events_disabled,
                }
    except Exception as exc:  # noqa: BLE001
        # V073 — fallback robusto: si la columna no existe aun (migracion
        # V073 no aplicada), reintentamos sin ella.
        if "urgent_events_disabled" in str(exc):
            return _load_user_prefs_legacy(user_id)
        logger.warning("load_user_prefs fallback (%s)", exc, exc_info=True)
        return _user_prefs_defaults()


def _load_user_prefs_legacy(user_id: str) -> dict:
    """Fallback pre-V073: query sin urgent_events_disabled. Permite que el
    backend nuevo corra contra DB vieja (durante el deploy)."""
    try:
        from psycopg2.extras import RealDictCursor
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT push_enabled, quiet_hours_enabled,
                           quiet_hours_start, quiet_hours_end, events_disabled
                      FROM auth.user_notification_prefs
                     WHERE user_id = %s::uuid
                    """,
                    (str(user_id),),
                )
                row = cur.fetchone()
                if not row:
                    return _user_prefs_defaults()
                events_disabled = row["events_disabled"] or []
                if not isinstance(events_disabled, list):
                    events_disabled = []
                return {
                    "push_enabled":           bool(row["push_enabled"]),
                    "quiet_hours_enabled":    row["quiet_hours_enabled"],
                    "quiet_hours_start":      row["quiet_hours_start"],
                    "quiet_hours_end":        row["quiet_hours_end"],
                    "events_disabled":        events_disabled,
                    "urgent_events_disabled": [],
                }
    except Exception:  # noqa: BLE001
        return _user_prefs_defaults()


def _user_prefs_defaults() -> dict:
    """Defaults usados cuando el user no tiene fila — 'usar el global'."""
    return {
        "push_enabled":           True,
        "quiet_hours_enabled":    None,
        "quiet_hours_start":      None,
        "quiet_hours_end":        None,
        "events_disabled":        [],
        "urgent_events_disabled": [],
    }


def effective_quiet_hours_for_user(user_id: str) -> dict:
    """Combina prefs personales del user con la config global. Las llaves
    no-NULL del user override al global. Devuelve {enabled, start, end}."""
    global_qh = load_quiet_hours()
    user_prefs = load_user_prefs(user_id)
    effective = dict(global_qh)
    if user_prefs.get("quiet_hours_enabled") is not None:
        effective["enabled"] = bool(user_prefs["quiet_hours_enabled"])
    if user_prefs.get("quiet_hours_start"):
        effective["start"] = user_prefs["quiet_hours_start"]
    if user_prefs.get("quiet_hours_end"):
        effective["end"] = user_prefs["quiet_hours_end"]
    return effective


def save_user_prefs(user_id: str, prefs: dict) -> dict:
    """UPSERT prefs del usuario. Sanitiza inputs. Devuelve la fila final.

    V073 — Incluye urgent_events_disabled: lista whitelisted contra
    URGENT_EVENTS global (no permite agregar eventos no-urgent al
    bypass, esa direccion seria upgrade y queda como feature futura)."""
    import re
    if not user_id:
        raise ValueError("user_id requerido")
    _hhmm = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

    push_enabled = bool(prefs.get("push_enabled", True))

    qh_enabled_in = prefs.get("quiet_hours_enabled")
    qh_enabled = None if qh_enabled_in is None else bool(qh_enabled_in)

    def _clean_hhmm(v):
        return v if isinstance(v, str) and _hhmm.match(v) else None

    qh_start = _clean_hhmm(prefs.get("quiet_hours_start"))
    qh_end   = _clean_hhmm(prefs.get("quiet_hours_end"))

    events_disabled_in = prefs.get("events_disabled") or []
    if not isinstance(events_disabled_in, list):
        events_disabled_in = []
    # Whitelist: solo eventos conocidos
    valid_events = set(_TEMPLATE_DEFAULTS.keys())
    events_disabled = sorted({
        str(e) for e in events_disabled_in if str(e) in valid_events
    })

    # V073 — Solo permitimos en urgent_events_disabled los que SI son
    # urgent globalmente. Si alguien manda un evento no-urgent, se ignora
    # (no tiene sentido "deshabilitar el bypass" de algo que no bypass).
    urgent_disabled_in = prefs.get("urgent_events_disabled") or []
    if not isinstance(urgent_disabled_in, list):
        urgent_disabled_in = []
    urgent_events_disabled = sorted({
        str(e) for e in urgent_disabled_in if str(e) in URGENT_EVENTS
    })

    import json
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth.user_notification_prefs (
                    user_id, push_enabled, quiet_hours_enabled,
                    quiet_hours_start, quiet_hours_end,
                    events_disabled, urgent_events_disabled, updated_at
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    push_enabled           = EXCLUDED.push_enabled,
                    quiet_hours_enabled    = EXCLUDED.quiet_hours_enabled,
                    quiet_hours_start      = EXCLUDED.quiet_hours_start,
                    quiet_hours_end        = EXCLUDED.quiet_hours_end,
                    events_disabled        = EXCLUDED.events_disabled,
                    urgent_events_disabled = EXCLUDED.urgent_events_disabled,
                    updated_at             = NOW()
                """,
                (str(user_id), push_enabled, qh_enabled,
                 qh_start, qh_end,
                 json.dumps(events_disabled),
                 json.dumps(urgent_events_disabled)),
            )
        conn.commit()

    return {
        "push_enabled":           push_enabled,
        "quiet_hours_enabled":    qh_enabled,
        "quiet_hours_start":      qh_start,
        "quiet_hours_end":        qh_end,
        "events_disabled":        events_disabled,
        "urgent_events_disabled": urgent_events_disabled,
    }


def invalidate_templates_cache() -> None:
    """Llamar desde PUT /notifications para forzar refetch al proximo notify()."""
    _CONFIG_CACHE["value"] = None
    _CONFIG_CACHE["fetched_at"] = 0.0


def get_available_variables() -> dict:
    """Devuelve las variables que el editor puede sugerir por evento."""
    return dict(_TEMPLATE_VARIABLES)


# ── Render seguro ────────────────────────────────────────────────────────

def _safe_format(template: str, context: dict) -> str:
    """Substituye {var} en `template` con `context`. Keys faltantes quedan
    como literal `{var}` en vez de explotar — robusto a templates mal
    escritos. Tambien colapsa espacios duplicados resultantes de campos
    vacios al limpiar el resultado."""
    if not template:
        return ""
    result = template
    for key, val in (context or {}).items():
        if val is None:
            val = ""
        result = result.replace("{" + str(key) + "}", str(val))
    # Colapsa espacios multiples, trim
    return " ".join(result.split()).strip()


# ── API publica ──────────────────────────────────────────────────────────

def notify(
    event_type: str,
    recipient_user_id: str,
    context: Optional[dict] = None,
    *,
    data: Optional[dict] = None,
    performed_by: Optional[str] = None,
) -> bool:
    """Envia push para `event_type` al usuario `recipient_user_id`.

    V070.51 — Reglas anti-ruido (paridad con CRMs profesionales):
      - Skip self-action: si performed_by == recipient_user_id, no envia.
        Razon: el actor ya sabe lo que hizo (ej: asesor que toma lead
        de cola, supervisor que se asigna a si mismo, etc).
      - Quiet hours: si la hora actual cae en rango quiet_hours y el
        evento no esta en URGENT_EVENTS, no envia. Default 21:00-08:00
        Lima. Evita despertar al asesor de noche por leads no criticos.
      - WhatsApp inbound es excepcion a quiet hours — cliente esperando.

    Si el evento esta deshabilitado (toggle global off) o el template
    queda vacio tras render, no envia. Devuelve True si FCM acepto al
    menos un envio. Nunca levanta — best-effort.
    """
    if not recipient_user_id or not event_type:
        return False

    # Anti-noise rule #1: skip self-action.
    if performed_by and str(performed_by) == str(recipient_user_id):
        logger.debug("notify(%s): skip self-action (%s)", event_type, recipient_user_id)
        return False

    # V070.53 — Anti-noise rule #2a: preferencias personales del usuario.
    # Kill switch + opt-out por evento. Aplica a TODO incluyendo urgentes
    # (si el user quiere silenciar WhatsApp, es su derecho).
    user_prefs = load_user_prefs(recipient_user_id)
    if not user_prefs.get("push_enabled", True):
        logger.info(
            "notify(%s): user %s tiene push deshabilitado (kill switch personal)",
            event_type, recipient_user_id,
        )
        return False
    if event_type in (user_prefs.get("events_disabled") or []):
        logger.info(
            "notify(%s): user %s opto-out de este evento",
            event_type, recipient_user_id,
        )
        return False

    # Anti-noise rule #2b: quiet hours.
    # V073 — Override personal del bypass URGENT (patrón estándar DND-style).
    # Un evento bypassea quiet hours SI Y SOLO SI:
    #   - Es URGENT globalmente, Y
    #   - El user NO lo agrego a su urgent_events_disabled.
    # Asi cada user decide si lead_created (urgent global) lo despierta o no.
    user_bypass_disabled = set(user_prefs.get("urgent_events_disabled") or [])
    is_urgent_for_user = (
        event_type in URGENT_EVENTS and event_type not in user_bypass_disabled
    )
    if not is_urgent_for_user:
        effective_qh = effective_quiet_hours_for_user(recipient_user_id)
        if _is_quiet_hour_now(effective_qh):
            reason = "quiet_hours_user_override" if event_type in URGENT_EVENTS else "quiet_hours"
            logger.info(
                "notify(%s): suprimido por %s (recipient=%s, rango=%s-%s)",
                event_type, reason, recipient_user_id,
                effective_qh.get("start"), effective_qh.get("end"),
            )
            return False

    # Anti-noise rule #3: burst rate-limit (mismo override que quiet hours).
    suppressed_count = 0
    if not is_urgent_for_user:
        now = time.monotonic()
        with _BURST_LOCK:
            state = _BURST_STATE.setdefault(
                str(recipient_user_id), {"ts": [], "suppressed": 0}
            )
            # Sliding window: drop timestamps fuera de la ventana
            state["ts"] = [t for t in state["ts"] if (now - t) < _BURST_WINDOW_SECONDS]
            if len(state["ts"]) >= _BURST_MAX_PER_WINDOW:
                state["suppressed"] += 1
                logger.info(
                    "notify(%s): rate-limited recipient=%s (pendientes=%d)",
                    event_type, recipient_user_id, state["suppressed"],
                )
                return False
            state["ts"].append(now)
            # Tail-aggregation: si hay suprimidos previos, los incluimos
            # como '+N mas' en el primer push permitido tras la ventana.
            suppressed_count = state["suppressed"]
            state["suppressed"] = 0

    templates = load_templates()
    tpl = templates.get(event_type)
    if not tpl or not tpl.get("enabled", True):
        return False

    title = _safe_format(tpl.get("title") or "", context or {})
    body  = _safe_format(tpl.get("body") or "", context or {})
    if not title and not body:
        logger.debug("notify(%s): template vacio post-render, skip", event_type)
        return False

    # Tail-aggregation: el primer push permitido tras una ventana de
    # supresion lleva un sufijo informativo. Asi el asesor sabe que hay
    # mas en cola sin recibir N pushes individuales.
    if suppressed_count > 0:
        body = f"{body} (+{suppressed_count} más en cola)".strip()

    try:
        return fcm_service.send(recipient_user_id, title, body, data=data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify(%s) fallo: %s", event_type, exc)
        return False


# ── Wrappers legacy (compat con codigo existente) ────────────────────────

def notify_new_lead(
    asesor_id: str,
    lead_name: str,
    fuente: str = "",
    *,
    performed_by: Optional[str] = None,
    lead_id: Optional[int] = None,
    calidad: Optional[str] = None,
):
    """Notifica al asesor que recibio un nuevo lead. (Legacy wrapper.)

    V070.91 — Si se provee lead_id, va en el `data` payload del push para
    que el mobile pueda navegar directo al detalle del lead al tap
    (patron estandar de la industria 'deep-link by record id'). Sin lead_id
    el cliente cae al fallback de la lista de Leads.

    V075 — Coalescing anti-spam (patron premium/correo profesional):
      - Si llegan >=3 leads al mismo asesor en ventana de 30s, manda 1
        push agregada en vez de N individuales.
      - Bypass CALIENTE: leads marcados CALIENTE se envian instantaneos
        sin pasar por el buffer (velocidad > silencio para hot leads).
      - Bypass sin lead_id: si el caller no provee id, va inmediato
        (no podemos persistirlo bien en el buffer).
      - Si la migracion V075 no esta aplicada o falla, el coalescer hace
        fallback a inmediato — best-effort, mejor spam que cero pushes.

    El parametro `calidad` es opcional: si no se pasa, el coalescer la
    busca en crm.leads. Pasarla explicita ahorra 1 query.
    """
    from app.services import notification_coalescer
    return notification_coalescer.enqueue(
        asesor_id=asesor_id,
        lead_id=lead_id,
        lead_name=lead_name,
        fuente=fuente,
        performed_by=performed_by,
        calidad=calidad,
    )


def notify_supervisor_new_lead(
    supervisor_id: str,
    lead_name: str,
    asesor_name: str,
    *,
    fuente: Optional[str] = None,
    lead_id: Optional[int] = None,
    performed_by: Optional[str] = None,
) -> bool:
    """Notifica al supervisor de forma inmediata que un lead nuevo fue asignado a su equipo.

    Permite que los supervisores estén al tanto en tiempo real de nuevos leads asignados
    a sus asesores a cargo, sin tener que esperar 24h/48h.
    """
    if not supervisor_id:
        return False
    if performed_by and str(performed_by) == str(supervisor_id):
        return False
    data = {"type": "lead_created_supervisor"}
    if lead_id is not None:
        data["lead_id"] = str(lead_id)
    return notify(
        "lead_created_supervisor",
        supervisor_id,
        {
            "lead_name": lead_name or "Lead",
            "asesor_name": asesor_name or "un asesor",
            "fuente": fuente or "web",
        },
        data=data,
        performed_by=performed_by,
    )


def notify_lead_reassigned(
    asesor_id: str,
    lead_name: str,
    *,
    performed_by: Optional[str] = None,
    lead_id: Optional[int] = None,
):
    """Notifica al asesor que le reasignaron un lead. (Legacy wrapper.)

    V070.91 — Tap → deep-link al detalle si lead_id provisto."""
    data = {"type": "lead_reassigned"}
    if lead_id is not None:
        data["lead_id"] = str(lead_id)
    return notify(
        "lead_reassigned", asesor_id,
        {"lead_name": lead_name or ""},
        data=data, performed_by=performed_by,
    )


def notify_lead_recontacto(asesor_id: str, lead_id: int, lead_name: str,
                           fuente: str = "", campana: Optional[str] = None):
    """Notifica al asesor que un lead que ya tenia volvio a interesarse
    (V048 — Lead Re-engagement).

    Texto contextual: 'Juan Perez volvio a interesarse via Facebook
    (campaña Palmeras 25)'. Si no hay template configurado, hace fallback
    a un mensaje hardcodeado en castellano peruano.

    V070.91 — Tap → deep-link al detalle del lead.
    """
    contexto = {
        "lead_name": lead_name or "Un lead",
        "lead_id":   str(lead_id) if lead_id else "",
        "fuente":    fuente or "otra fuente",
        "campana":   campana or "",
    }
    data = {"type": "lead_recontacto"}
    if lead_id:
        data["lead_id"] = str(lead_id)
    return notify("lead_recontacto", asesor_id, contexto, data=data)


def notify_wa_message_inbound(
    asesor_id: str,
    contact_name: str,
    message_preview: str,
    *,
    wa_phone: str = "",
    conversation_id: Optional[int] = None,
) -> bool:
    """Notifica al asesor que llego un mensaje WhatsApp en uno de sus chats.

    El payload incluye conversation_id en `data` para que el cliente movil
    pueda navegar directo al chat al tocar la notificacion.
    """
    return notify(
        "wa_message_inbound",
        asesor_id,
        {
            "contact_name":    contact_name or "Cliente",
            "message_preview": (message_preview or "")[:120],
            "wa_phone":        wa_phone or "",
        },
        data={
            "type":            "wa_message_inbound",
            "conversation_id": str(conversation_id) if conversation_id else "",
        },
    )

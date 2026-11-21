"""Team health service — circuit breaker a nivel equipo (ADR-0010).

V070.78 — Bundle Team Circuit Breaker.

Patron implementado por CRMs profesionales: cuando un equipo entero
esta colapsado (mayoria de asesores pausados/ausentes/llenos), el
sistema lo aisla automaticamente — NUEVOS leads van a otros equipos
sanos en vez de acumularse en la cola del supervisor.

## Estados de un equipo

- **active**:    <60% de asesores pausados/ausentes/llenos, o auto-asignacion desactivada. Recibe normal.
- **at_risk**:   >=60% pausados pero con AL MENOS 1 asesor disponible. Sigue recibiendo, con alerta visible.
- **blocked**:   0 asesores disponibles (100% pausados o sin asesores con auto-asignacion activa).
                 NO recibe nuevos leads — se redirigen a otro equipo disponible.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Umbrales del circuit breaker ──────────────────────────────────────────
AT_RISK_THRESHOLD = 0.60   # >=60% pausados con al menos 1 disponible → at_risk (visible pero recibe)
UNBLOCK_THRESHOLD = 0.60   # <=60% → vuelve a active


def _is_asesor_paused(a: dict, now: datetime, *, count_cap_full: bool = True) -> bool:
    """Helper: decide si un asesor cuenta como 'pausado' para el calculo.

    Tres caminos lo cuentan como pausado:
      1. disponible_rotacion = FALSE  (pausado manual)
      2. ausencia activa             (desde <= now <= hasta)
      3. cap individual lleno        (leads_abiertos >= max_leads)
         — SOLO si count_cap_full=True. Si la estrategia global es
         'ignorar_capacity', cap-lleno NO descalifica al asesor (el motor
         de routing lo asigna igual), asi que tampoco debe contar como
         pausado aqui (coherencia con ADR-0010).

    Importante: el asesor solo cuenta como NO pausado si esta efectivamente
    listo para recibir leads ahora mismo.
    """
    if not a.get("disponible_rotacion", True):
        return True
    # Ausencia programada
    ausencia_desde = a.get("ausencia_desde")
    ausencia_hasta = a.get("ausencia_hasta")
    if ausencia_desde and ausencia_hasta:
        # Comparacion con date (no datetime) — la ausencia es por dia.
        today = now.date()
        if ausencia_desde <= today <= ausencia_hasta:
            return True
    # Cap individual (omitido cuando la estrategia es ignorar_capacity)
    if count_cap_full:
        cap = a.get("max_leads_abiertos") or a.get("cap_default", 200)
        leads_abiertos = a.get("leads_abiertos", 0)
        if cap and leads_abiertos >= cap:
            return True
    return False


def _load_assignment_config(cur) -> dict:
    """Lee crm.assignment_config singleton."""
    try:
        cur.execute(
            """
            SELECT
                auto_asignar_enabled,
                max_leads_abiertos_default,
                estrategia_sin_disponibles,
                COALESCE(incluir_supervisor_en_rotacion, FALSE) AS incluir_supervisor_en_rotacion
            FROM crm.assignment_config
            WHERE id = 1
            """
        )
        row = cur.fetchone()
        if row:
            if isinstance(row, dict):
                return {
                    "auto_asignar_enabled": bool(row.get("auto_asignar_enabled", False)),
                    "max_leads_abiertos_default": row.get("max_leads_abiertos_default") or 200,
                    "estrategia_sin_disponibles": row.get("estrategia_sin_disponibles") or "asignar_supervisor",
                    "incluir_supervisor_en_rotacion": bool(row.get("incluir_supervisor_en_rotacion", False)),
                }
            return {
                "auto_asignar_enabled": bool(row[0]),
                "max_leads_abiertos_default": row[1] or 200,
                "estrategia_sin_disponibles": row[2] or "asignar_supervisor",
                "incluir_supervisor_en_rotacion": bool(row[3]),
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("No se pudo leer assignment_config: %s", exc)
    return {
        "auto_asignar_enabled": False,
        "max_leads_abiertos_default": 200,
        "estrategia_sin_disponibles": "asignar_supervisor",
        "incluir_supervisor_en_rotacion": False,
    }


def _is_team_auto_asignar_enabled(cur, supervisor_id: str, global_auto_enabled: bool) -> bool:
    """Si la auto-asignacion a asesores esta habilitada para este equipo.
    Requiere que este activa globalmente Y para este equipo especifico."""
    if not global_auto_enabled:
        return False
    try:
        cur.execute(
            """
            SELECT COALESCE(BOOL_OR(auto_asignar_enabled), TRUE) AS enabled
            FROM crm.equipos
            WHERE supervisor_id IN (
                SELECT %s::uuid
                UNION
                SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
            ) AND activo = TRUE
            """,
            (supervisor_id, supervisor_id),
        )
        row = cur.fetchone()
        if not row:
            return True
        val = row["enabled"] if isinstance(row, dict) else row[0]
        return bool(val) if val is not None else True
    except Exception as exc:  # noqa: BLE001
        logger.debug("equipo auto_enabled lookup fallo: %s", exc)
        return True


def _is_supervisor_available(
    cur,
    supervisor_id: str,
    now: datetime,
    *,
    count_cap_full: bool = True,
    cap_default: int = 200,
) -> bool:
    """Si el supervisor esta activo en rotacion y no esta pausado/ausente/lleno."""
    try:
        cur.execute(
            """
            SELECT
                u.id::text AS user_id,
                u.is_active,
                u.activo_rotacion,
                COALESCE(u.login_blocked, FALSE) AS login_blocked,
                COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
                s.max_leads_abiertos,
                s.ausencia_desde,
                s.ausencia_hasta,
                crm.count_leads_abiertos(u.id, 'todos_activos') AS leads_abiertos
            FROM auth.users u
            LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
            WHERE u.id = %s::uuid
            """,
            (supervisor_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        sup = dict(row) if isinstance(row, dict) else {
            "user_id": row[0], "is_active": row[1], "activo_rotacion": row[2],
            "login_blocked": row[3], "disponible_rotacion": row[4],
            "max_leads_abiertos": row[5], "ausencia_desde": row[6],
            "ausencia_hasta": row[7], "leads_abiertos": row[8],
        }
        if not sup.get("is_active") or sup.get("login_blocked") or not sup.get("activo_rotacion", True):
            return False
        sup["cap_default"] = cap_default
        return not _is_asesor_paused(sup, now, count_cap_full=count_cap_full)
    except Exception as exc:  # noqa: BLE001
        logger.debug("supervisor availability lookup fallo: %s", exc)
        return False


def _status_from_pct(pct_pausados: float) -> str:
    """Decide el estado del equipo en base al porcentaje de pausados.

    NOTA: este helper solo clasifica por porcentaje. Para la decision completa
    con disponibilidad de asesores y auto-asignacion, ver `compute_team_status`.
    """
    if pct_pausados >= 1.0:
        return "blocked"
    if pct_pausados >= AT_RISK_THRESHOLD:
        return "at_risk"
    return "active"


def _compute_pct_pausados(cur, supervisor_id: str, now: datetime) -> tuple[float, int, int]:
    """Devuelve (pct_pausados, total_asesores, asesores_pausados)."""
    config = _load_assignment_config(cur)
    cap_default = config.get("max_leads_abiertos_default", 200)
    estrategia_sd = config.get("estrategia_sin_disponibles", "asignar_supervisor")
    count_cap_full = (estrategia_sd != "ignorar_capacity")

    # Asesores del equipo + sus settings + leads abiertos
    cur.execute(
        """
        SELECT
            u.id::text AS user_id,
            COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
            s.max_leads_abiertos,
            s.ausencia_desde,
            s.ausencia_hasta,
            crm.count_leads_abiertos(u.id, 'todos_activos') AS leads_abiertos
        FROM crm.equipos eq
        JOIN auth.users u ON u.id = eq.asesor_id
        LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
        WHERE eq.supervisor_id = %s::uuid
          AND eq.activo = TRUE
          AND u.is_active = TRUE
          AND COALESCE(u.login_blocked, FALSE) = FALSE
          AND u.role = 'asesor'
        """,
        (supervisor_id,),
    )
    asesores = [dict(r) for r in cur.fetchall()]

    total = len(asesores)
    if total == 0:
        return 0.0, 0, 0

    pausados = 0
    for a in asesores:
        a["cap_default"] = cap_default
        if _is_asesor_paused(a, now, count_cap_full=count_cap_full):
            pausados += 1

    return pausados / total, total, pausados


def compute_team_status(cur, supervisor_id: str, *, now: Optional[datetime] = None) -> dict:
    """Devuelve el estado actual del equipo de un supervisor.

    Reglas de negocio:
      1. Si la reparticion de leads a asesores NO esta activa (auto_asignar_enabled=FALSE
         global o para el equipo): los leads llegan al supervisor directamente.
         El equipo NO se bloquea por falta/pausa de asesores -> status='active'.
      2. Si la reparticion de leads a asesores SI esta activa:
         - Si el equipo tiene AL MENOS UN asesor disponible (o supervisor incluido disponible):
           el equipo NO se bloquea (status='active' o 'at_risk' si pct_pausados >= 60%).
         - Solo si NO queda NINGUN asesor disponible (0 disponibles): status='blocked'.

    Returns:
        dict con:
          - status: 'active' | 'at_risk' | 'blocked'
          - total_asesores: int
          - asesores_pausados: int
          - pct_pausados: float (0.0 a 1.0)
          - supervisor_id: str
          - auto_asignar_enabled: bool
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    config = _load_assignment_config(cur)
    cap_default = config.get("max_leads_abiertos_default", 200)
    estrategia_sd = config.get("estrategia_sin_disponibles", "asignar_supervisor")
    count_cap_full = (estrategia_sd != "ignorar_capacity")
    global_auto = config.get("auto_asignar_enabled", False)
    incluir_sup = config.get("incluir_supervisor_en_rotacion", False)

    team_auto = _is_team_auto_asignar_enabled(cur, supervisor_id, global_auto)

    # Asesores del equipo + sus settings + leads abiertos
    cur.execute(
        """
        SELECT
            u.id::text AS user_id,
            COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
            s.max_leads_abiertos,
            s.ausencia_desde,
            s.ausencia_hasta,
            crm.count_leads_abiertos(u.id, 'todos_activos') AS leads_abiertos
        FROM crm.equipos eq
        JOIN auth.users u ON u.id = eq.asesor_id
        LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
        WHERE eq.supervisor_id = %s::uuid
          AND eq.activo = TRUE
          AND u.is_active = TRUE
          AND COALESCE(u.login_blocked, FALSE) = FALSE
          AND u.role = 'asesor'
        """,
        (supervisor_id,),
    )
    asesores = [dict(r) for r in cur.fetchall()]
    total = len(asesores)

    pausados = 0
    for a in asesores:
        a["cap_default"] = cap_default
        if _is_asesor_paused(a, now, count_cap_full=count_cap_full):
            pausados += 1

    disponibles = total - pausados

    # Si el supervisor participa en la rotacion y esta disponible, suma como receptor disponible
    if incluir_sup and _is_supervisor_available(cur, supervisor_id, now, count_cap_full=count_cap_full, cap_default=cap_default):
        disponibles += 1

    pct_pausados = (pausados / total) if total > 0 else 0.0

    # Decision de estado operacional:
    if not team_auto:
        # Reparticion a asesores apagada -> supervisor recibe directamente -> equipo siempre activo
        status = "active"
    else:
        # Reparticion a asesores activa:
        if disponibles == 0:
            status = "blocked"
            if total == 0:
                pct_pausados = 1.0
        elif pct_pausados >= AT_RISK_THRESHOLD:
            status = "at_risk"
        else:
            status = "active"

    return {
        "supervisor_id":        supervisor_id,
        "status":               status,
        "total_asesores":       total,
        "asesores_pausados":    pausados,
        "pct_pausados":         round(pct_pausados, 4),
        "auto_asignar_enabled": team_auto,
    }


def _get_last_status(cur, supervisor_id: str) -> Optional[str]:
    """Ultimo estado conocido del equipo segun team_status_history.
    None si no hay historial (primer calculo)."""
    try:
        cur.execute(
            """
            SELECT new_status FROM crm.team_status_history
            WHERE supervisor_id = %s::uuid
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (supervisor_id,),
        )
        row = cur.fetchone()
        if row:
            return row["new_status"] if isinstance(row, dict) else row[0]
    except Exception as exc:  # noqa: BLE001
        # Tabla puede no existir aun (migracion V072 no aplicada).
        logger.debug("team_status_history no disponible: %s", exc)
    return None


def compute_team_status_with_hysteresis(
    cur,
    supervisor_id: str,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Calcula el estado del equipo aplicando histeresis con el estado previo.

    Reglas de transicion:
      - Si auto_asignar_enabled=FALSE: siempre 'active' (supervisor recibe directo).
      - Si auto_asignar_enabled=TRUE:
        - Bloqueo solo cuando disponibles == 0 (status = 'blocked').
        - Si estaba 'blocked' y ahora disponibles > 0:
          se desbloquea inmediatamente a 'active' o 'at_risk' segun el porcentaje.
    """
    raw = compute_team_status(cur, supervisor_id, now=now)
    last_status = _get_last_status(cur, supervisor_id)
    raw["previous_status"] = last_status
    return raw


def _record_status_transition(
    cur,
    *,
    supervisor_id: str,
    previous: Optional[str],
    new: str,
    snapshot: dict,
    triggering_user_id: Optional[str] = None,
    nota: Optional[str] = None,
) -> None:
    """Persiste una transicion de estado en team_status_history."""
    try:
        cur.execute(
            """
            INSERT INTO crm.team_status_history
                (supervisor_id, previous_status, new_status,
                 total_asesores, asesores_pausados, pct_pausados,
                 triggering_user_id, nota)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s)
            """,
            (
                supervisor_id, previous, new,
                snapshot["total_asesores"], snapshot["asesores_pausados"],
                snapshot["pct_pausados"] * 100,  # almacenamos 0-100 no 0-1
                triggering_user_id, nota,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo registrar team_status_history: %s", exc)


def evaluate_and_record_transition(
    cur,
    supervisor_id: str,
    *,
    triggering_user_id: Optional[str] = None,
    nota: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Calcula el estado actual y registra la transicion si cambio.

    Llamar desde:
      - Cambio de `disponible_rotacion` de un asesor (pause/unpause manual).
      - Cambio de ausencia.
      - Asignacion de nuevo lead (puede llenar el cap).
      - Cierre de lead (puede liberar cap).
      - Cron periodico (defensivo, cada N min).

    Returns:
        dict resultado de compute_team_status_with_hysteresis +
              campo 'transitioned' (bool) que dice si hubo cambio.
    """
    status = compute_team_status_with_hysteresis(cur, supervisor_id, now=now)
    transitioned = status["status"] != status["previous_status"]
    if transitioned:
        _record_status_transition(
            cur,
            supervisor_id=supervisor_id,
            previous=status["previous_status"],
            new=status["status"],
            snapshot=status,
            triggering_user_id=triggering_user_id,
            nota=nota,
        )
        # Metricas Prometheus (best-effort)
        try:
            from app.metrics import crm_team_blocked_total, crm_team_unblocked_total
            if status["status"] == "blocked":
                crm_team_blocked_total.labels(supervisor_id=supervisor_id).inc()
            elif status["previous_status"] == "blocked":
                crm_team_unblocked_total.labels(supervisor_id=supervisor_id).inc()
        except Exception:  # noqa: BLE001
            pass

        # Push notification al supervisor (best-effort, no debe romper flujo)
        try:
            _notify_supervisor_status_change(supervisor_id, status)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo notificar al supervisor %s: %s", supervisor_id, exc)

        logger.info(
            "[team-health] supervisor=%s transition %s → %s (pct_pausados=%.2f%%, %d/%d pausados)",
            supervisor_id, status["previous_status"], status["status"],
            status["pct_pausados"] * 100,
            status["asesores_pausados"], status["total_asesores"],
        )
    status["transitioned"] = transitioned
    return status


def _notify_supervisor_status_change(supervisor_id: str, status: dict) -> None:
    """Dispara push al supervisor cuando su equipo cambia de estado.

    Solo dos transiciones generan notificacion (ruido minimo):
      - cualquier → blocked    : "Tu equipo esta bloqueado, accion urgente"
      - blocked   → cualquier  : "Tu equipo volvio a estar activo"

    Transiciones active <-> at_risk NO disparan push (seria ruidoso).
    """
    new = status["status"]
    prev = status["previous_status"]
    event_type = None
    if new == "blocked" and prev != "blocked":
        event_type = "team_blocked"
    elif prev == "blocked" and new != "blocked":
        event_type = "team_unblocked"
    if not event_type:
        return

    context = {
        "total_asesores":    str(status["total_asesores"]),
        "asesores_pausados": str(status["asesores_pausados"]),
        "pct_pausados":      f"{status['pct_pausados'] * 100:.0f}",
    }
    try:
        from app.services.notification_service import notify
        notify(event_type, supervisor_id, context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify(%s, %s) fallo: %s", event_type, supervisor_id, exc)


def get_healthy_supervisor_ids(cur, *, now: Optional[datetime] = None) -> list[str]:
    """Devuelve los IDs de supervisores cuyo equipo NO esta blocked.

    Filtra primero por `auth.users.activo_rotacion = TRUE` (el supervisor
    debe estar activo en la rotacion global) y luego excluye los que
    tienen su equipo bloqueado.

    Si NINGUN equipo esta sano (todos bloqueados o ningun supervisor
    activo), devuelve lista vacia. El caller decide que hacer (fallback
    al admin, etc).
    """
    cur.execute(
        """
        SELECT id::text AS id
        FROM auth.users
        WHERE role = 'supervisor'
          AND is_active = TRUE
          AND activo_rotacion = TRUE
        ORDER BY created_at, id
        """
    )
    rows = cur.fetchall()
    all_supervisors = [
        (r["id"] if isinstance(r, dict) else r[0]) for r in rows
    ]

    healthy = []
    for sid in all_supervisors:
        status = compute_team_status_with_hysteresis(cur, sid, now=now)
        if status["status"] != "blocked":
            healthy.append(sid)
    return healthy


def pick_supervisor_with_most_capacity(
    cur,
    candidate_supervisor_ids: list[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """De una lista de supervisores, elige el que tiene mas capacity
    disponible en su equipo (menor pct_pausados).

    Tie-breaker: el supervisor con MAS asesores activos absolutos
    (mas capacidad bruta).

    Devuelve None si la lista esta vacia o no hay nadie con capacity.
    """
    if not candidate_supervisor_ids:
        return None
    if len(candidate_supervisor_ids) == 1:
        return candidate_supervisor_ids[0]

    scores = []
    for sid in candidate_supervisor_ids:
        s = compute_team_status(cur, sid, now=now)
        activos = s["total_asesores"] - s["asesores_pausados"]
        # Ordenamos por: menor pct pausados, mayor #activos
        scores.append((s["pct_pausados"], -activos, sid))

    scores.sort()
    return scores[0][2]


def get_team_health_summary(cur, *, now: Optional[datetime] = None) -> list[dict]:
    """Devuelve el estado de cada equipo (uno por supervisor) para
    el endpoint GET /api/v1/team-health.

    Cada entrada incluye nombre del supervisor + status + metricas.
    """
    cur.execute(
        """
        SELECT id::text AS id,
               first_name || ' ' || COALESCE(last_name, '') AS nombre,
               email
        FROM auth.users
        WHERE role = 'supervisor'
          AND is_active = TRUE
        ORDER BY first_name, last_name
        """
    )
    supervisores = [dict(r) for r in cur.fetchall()]
    result = []
    for sup in supervisores:
        status = compute_team_status_with_hysteresis(cur, sup["id"], now=now)
        status["supervisor_nombre"] = sup["nombre"]
        status["supervisor_email"] = sup["email"]
        result.append(status)
    return result

"""
lead_routing.py — Motor de auto-asignacion de leads.

Patron Lead Assignment Engine: dado un lead recien creado y el supervisor
que tocó por round-robin, decide a que asesor especifico se asigna
aplicando (en orden):

  1. Reglas de routing configurables (crm.lead_assignment_rules)
  2. Round-robin del equipo del supervisor (con capacity y horario)
  3. Fallback al supervisor (comportamiento actual)

Este modulo NO toca el ingest. Lo invoca ingest_core via try_auto_assign().

FAIL-SAFE: si algo falla aqui, el caller ignora y deja el lead en el
supervisor (comportamiento actual). Nunca bloqueamos la ingesta.
"""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo

from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
LIMA_TZ = ZoneInfo("America/Lima")


# ─── Tipos ────────────────────────────────────────────────────────────────

class AssignmentDecision:
    """Resultado del motor: a quien se asigna y por que."""

    def __init__(
        self,
        *,
        asignado_a_id: str,
        estrategia: str,
        regla_id: Optional[int] = None,
        razon: str = "",
        candidatos: Optional[list] = None,
        duracion_ms: int = 0,
    ):
        self.asignado_a_id = asignado_a_id
        self.estrategia = estrategia
        self.regla_id = regla_id
        self.razon = razon
        self.candidatos = candidatos or []
        self.duracion_ms = duracion_ms


# ─── Helpers ──────────────────────────────────────────────────────────────

def _now_lima() -> datetime:
    return datetime.now(LIMA_TZ)


def _esta_en_horario(now: datetime, inicio: Optional[dtime], fin: Optional[dtime]) -> bool:
    """True si la hora actual esta dentro del rango. Soporta cruces de medianoche."""
    if inicio is None or fin is None:
        return True
    hora_actual = now.time()
    if inicio <= fin:
        return inicio <= hora_actual <= fin
    # Rango cruza medianoche (ej. 22:00 - 06:00)
    return hora_actual >= inicio or hora_actual <= fin


def _esta_en_dias_semana(now: datetime, dias: Optional[list]) -> bool:
    """dias: array de 1..7 (lunes=1). NULL/vacio = todos los dias."""
    if not dias:
        return True
    # Python: patrón premium=0, Sunday=6  →  convertimos a 1..7 con patrón premium=1
    dia_actual = now.isoweekday()
    return dia_actual in dias


def _esta_en_ausencia(now: datetime, desde, hasta) -> bool:
    """True si el dia actual cae en una ausencia programada."""
    if not desde or not hasta:
        return False
    hoy = now.date()
    return desde <= hoy <= hasta


# ─── Carga de configuracion ───────────────────────────────────────────────

def get_config(cur) -> dict:
    """Devuelve la fila singleton de assignment_config. Si no existe (V046
    no aplicada), devuelve defaults seguros que dejan auto-asignacion OFF."""
    try:
        cur.execute("SELECT * FROM crm.assignment_config WHERE id = 1")
        row = cur.fetchone()
        if row:
            d = dict(row)
            d["incluir_supervisor_en_rotacion"] = bool(d.get("incluir_supervisor_en_rotacion", False))
            return d
    except Exception as exc:  # noqa: BLE001
        logger.debug("assignment_config no disponible: %s", exc)
    return {
        "auto_asignar_enabled": False,
        "estrategia_default": "manual",
        "max_leads_abiertos_default": 50,
        "horario_inicio": None,
        "horario_fin": None,
        "estrategia_fuera_horario": "asignar_supervisor",
        "estrategia_sin_disponibles": "asignar_supervisor",
        "capacity_definicion": "todos_activos",
        "notificar_supervisor_auto": True,
        "incluir_supervisor_en_rotacion": False,
    }


def _get_asesores_del_equipo(cur, supervisor_id: str, incluir_supervisor: bool = False) -> list[dict]:
    """Devuelve los asesores activos del equipo del supervisor con su
    settings + leads_abiertos. Si incluir_supervisor es True, tambien
    incluye al supervisor como candidato en la rotacion."""
    cur.execute(
        """
        SELECT
            u.id::text AS user_id,
            TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre,
            u.email,
            u.is_active,
            COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
            s.max_leads_abiertos,
            s.horario_inicio,
            s.horario_fin,
            s.dias_semana,
            s.ausencia_desde,
            s.ausencia_hasta,
            s.motivo_ausencia,
            COALESCE(s.peso_rotacion, 1.0)::float AS peso_rotacion,
            eq.orden AS orden,                              -- V055: posicion manual
            eq.last_assigned_at AS last_assigned_at         -- V055: tracking RR orden
        FROM crm.equipos eq
        JOIN auth.users u ON u.id = eq.asesor_id
        LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
        WHERE eq.supervisor_id IN (
            SELECT %s::uuid
            UNION
            SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
        )
          AND eq.activo = TRUE
          AND u.is_active = TRUE
          AND COALESCE(u.login_blocked, FALSE) = FALSE  -- V094.6 — patrón estándar "Freeze": auto-routing salta usuarios con login bloqueado
          AND u.role = 'asesor'
        """,
        (supervisor_id, supervisor_id),
    )
    asesores = [dict(r) for r in cur.fetchall()]

    if incluir_supervisor and supervisor_id:
        existing_ids = {a["user_id"] for a in asesores}
        if supervisor_id not in existing_ids:
            cur.execute(
                """
                SELECT
                    u.id::text AS user_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre,
                    u.email,
                    u.is_active,
                    COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
                    s.max_leads_abiertos,
                    s.horario_inicio,
                    s.horario_fin,
                    s.dias_semana,
                    s.ausencia_desde,
                    s.ausencia_hasta,
                    s.motivo_ausencia,
                    COALESCE(s.peso_rotacion, 1.0)::float AS peso_rotacion,
                    COALESCE(eq.orden, 0) AS orden,
                    eq.last_assigned_at AS last_assigned_at
                FROM auth.users u
                LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
                LEFT JOIN crm.equipos eq ON eq.supervisor_id = u.id AND eq.asesor_id = u.id AND eq.activo = TRUE
                WHERE u.id = %s::uuid
                  AND u.is_active = TRUE
                  AND COALESCE(u.login_blocked, FALSE) = FALSE
                  AND u.role = 'supervisor'
                """,
                (supervisor_id,),
            )
            sup_row = cur.fetchone()
            if sup_row:
                asesores.append(dict(sup_row))

    return asesores


def _count_leads_abiertos(cur, asesor_id: str, modo: str) -> int:
    cur.execute("SELECT crm.count_leads_abiertos(%s::uuid, %s)", (asesor_id, modo))
    row = cur.fetchone()
    if row is None:
        return 0
    # Soporta ambos cursors (RealDict y default)
    if isinstance(row, dict):
        return next(iter(row.values())) or 0
    return row[0] or 0


def _equipo_auto_enabled(cur, supervisor_id: str) -> bool:
    """Si el equipo del supervisor o alguno de sus equipos subordinados tiene auto_asignar_enabled=TRUE."""
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
        logger.debug("equipo auto_enabled lookup falló: %s", exc)
        return True



# ─── Filtros de elegibilidad ──────────────────────────────────────────────

def _filtrar_elegibles(
    asesores: list[dict],
    cur,
    config: dict,
    now: datetime,
) -> tuple[list[dict], list[dict]]:
    """Aplica filtros: disponible, horario, ausencia, capacity.
    Devuelve (elegibles, descartados_con_motivo)."""
    elegibles: list[dict] = []
    descartados: list[dict] = []
    capacity_modo = config.get("capacity_definicion", "todos_activos")
    cap_default = config.get("max_leads_abiertos_default", 50) or 50

    for a in asesores:
        motivo = None

        if not a["disponible_rotacion"]:
            motivo = "marcado como no disponible"
        elif _esta_en_ausencia(now, a.get("ausencia_desde"), a.get("ausencia_hasta")):
            motivo = f"en ausencia ({a.get('motivo_ausencia') or 'programada'})"
        else:
            # Horario individual del asesor (si esta seteado)
            ind_inicio = a.get("horario_inicio")
            ind_fin = a.get("horario_fin")
            if ind_inicio and ind_fin and not _esta_en_horario(now, ind_inicio, ind_fin):
                motivo = f"fuera de su horario ({ind_inicio.strftime('%H:%M')}-{ind_fin.strftime('%H:%M')})"
            elif not _esta_en_dias_semana(now, a.get("dias_semana")):
                motivo = "no trabaja este dia de la semana"

        if motivo is None:
            # Capacity check
            cap_individual = a.get("max_leads_abiertos") or cap_default
            leads_abiertos = _count_leads_abiertos(cur, a["user_id"], capacity_modo)
            a["leads_abiertos"] = leads_abiertos
            a["max_leads"] = cap_individual
            if leads_abiertos >= cap_individual:
                motivo = f"capacity llena ({leads_abiertos}/{cap_individual})"

        if motivo:
            descartados.append({
                "user_id": a["user_id"],
                "nombre": a["nombre"],
                "motivo_descarte": motivo,
            })
        else:
            elegibles.append(a)

    return elegibles, descartados


# ─── Round-robin ponderado ─────────────────────────────────────────────────

def _pick_round_robin_orden(
    cur,
    candidatos: list[dict],
    supervisor_id: str,
) -> dict:
    """Round-robin SECUENCIAL por orden manual (V055).

    Patron patrón estándar Workflow Rotation / patrón estándar Queue Round Robin:
    cada equipo tiene una jerarquia 1..N configurada por el supervisor
    (o admin). Al primer lead que cae al equipo le toca la posicion 1,
    al siguiente la 2, etc. Wrap-around al final.

    El "siguiente" se calcula a partir del MAX(last_assigned_at) del
    equipo: tomamos la posicion de quien fue asignado mas reciente y
    elegimos al primer candidato cuyo `orden` sea mayor. Si no hay
    nadie con orden mayor (todos ya pasaron), wrap a la posicion mas
    chica de los elegibles.

    Esta funcion NO modifica DB — el caller llama a `_marcar_ultimo_asignado`
    despues de confirmar la asignacion.
    """
    if not candidatos:
        raise ValueError("_pick_round_robin_orden requiere al menos 1 candidato")
    if len(candidatos) == 1:
        return candidatos[0]

    # Sort por orden ASC. Asesores con orden=0 (no inicializado) van al final.
    # Issue #57 — tie-breaker secundario por NOMBRE alfabetico, no user_id.
    # El UUID es random y no matchea lo que el admin ve en la UI; un sort
    # estable por nombre garantiza comportamiento previsible (Cinthia, luego
    # Fabiola, luego Jorge, luego Rosmary) incluso si el orden quedo en 0
    # por algun bug futuro de inserción.
    candidatos_ord = sorted(
        candidatos,
        key=lambda c: (
            c.get("orden") or 999_999,
            (c.get("nombre") or "").lower(),
            c["user_id"],
        ),
    )

    # Posicion del ultimo asignado en el equipo (incluye asesores que ahora
    # estan inactivos — solo para saber el cursor del round-robin).
    cur.execute(
        """
        SELECT eq.orden AS last_orden
        FROM crm.equipos eq
        WHERE eq.supervisor_id = %s::uuid
          AND eq.last_assigned_at IS NOT NULL
        ORDER BY eq.last_assigned_at DESC
        LIMIT 1
        """,
        (supervisor_id,),
    )
    row = cur.fetchone()
    last_orden = 0
    if row:
        val = row.get("last_orden") if isinstance(row, dict) else row[0]
        last_orden = val or 0

    # Buscar el primer candidato con orden > last_orden
    siguientes = [c for c in candidatos_ord if (c.get("orden") or 0) > last_orden]
    if siguientes:
        return siguientes[0]

    # Wrap-around: ya pasamos por todos, volver al primero
    logger.info(
        "[routing/orden] last_orden=%s, candidatos=[%s], wrap=%s",
        last_orden,
        ", ".join(f"#{c.get('orden')}={c.get('nombre')}" for c in candidatos_ord),
        not bool(siguientes),
    )
    return candidatos_ord[0]


def _pick_round_robin_balanceado(
    cur,
    candidatos: list[dict],
    supervisor_id: str,
) -> dict:
    """V056: Round-robin balanceado a 7 dias.

    Compensa skips por LLENO/ausente del modo orden puro: si un asesor
    se salto su turno por capacity, su contador 7d queda mas bajo y la
    proxima vez que sea elegible es su turno preferente.

    Algoritmo:
      1. Trae count de leads recibidos en ultimos 7 dias por candidato
      2. Toma a quienes tienen el MENOR count (tier mas justo)
      3. Si hay empate dentro del tier -> desempata por orden manual
         (asi si todos tienen 0 leads, sigue la jerarquia 1,2,3...).
    """
    if not candidatos:
        raise ValueError("_pick_round_robin_balanceado requiere al menos 1 candidato")
    if len(candidatos) == 1:
        return candidatos[0]

    enriched: list[tuple[int, int, dict]] = []
    for c in candidatos:
        try:
            cur.execute(
                "SELECT crm.count_leads_recibidos_7d(%s::uuid) AS n",
                (c["user_id"],),
            )
            row = cur.fetchone()
            n7d = (row["n"] if isinstance(row, dict) else row[0]) or 0
        except Exception:
            n7d = 0
        orden = c.get("orden") or 999_999
        enriched.append((n7d, orden, c))

    enriched.sort(key=lambda t: (t[0], t[1], t[2]["user_id"]))

    logger.info(
        "[routing/balanceado] tier_min=%d candidatos=[%s]",
        enriched[0][0],
        ", ".join(f"{e[2].get('nombre')}#{e[1]}={e[0]}leads/7d" for e in enriched),
    )
    return enriched[0][2]


def _marcar_ultimo_asignado(cur, supervisor_id: str, asesor_id: str) -> None:
    """Marca crm.equipos.last_assigned_at = NOW() para el ganador del
    round-robin orden. El caller debe llamar a esto despues del UPDATE
    del lead (asegurando que la asignacion fue confirmada)."""
    try:
        cur.execute(
            """
            UPDATE crm.equipos
            SET last_assigned_at = clock_timestamp()
            WHERE supervisor_id = %s::uuid
              AND asesor_id = %s::uuid
              AND activo = TRUE
            """,
            (supervisor_id, asesor_id),
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("_marcar_ultimo_asignado fallo: %s", exc)


def _pick_round_robin_ponderado(cur, candidatos: list[dict]) -> dict:
    """Elige el asesor con menos leads asignados HOY (ajustado por peso).
    Empate → random. Patron usado por patrón estándar y patrón estándar."""
    if len(candidatos) == 1:
        return candidatos[0]

    # Cuenta leads asignados hoy por asesor (en zona Lima)
    cur.execute(
        """
        SELECT al.asignado_a_id::text AS uid, COUNT(*)::int AS hoy
        FROM crm.assignment_log al
        WHERE DATE(al.fecha AT TIME ZONE 'America/Lima') = (NOW() AT TIME ZONE 'America/Lima')::date
          AND al.asignado_a_id = ANY(%s::uuid[])
        GROUP BY al.asignado_a_id
        """,
        ([c["user_id"] for c in candidatos],),
    )
    hoy_por_asesor = {r["uid"]: r["hoy"] for r in cur.fetchall()}

    # Score = leads_hoy / peso. Menor es mejor.
    scored = []
    for c in candidatos:
        peso = c.get("peso_rotacion") or 1.0
        leads_hoy = hoy_por_asesor.get(c["user_id"], 0)
        score = leads_hoy / peso if peso > 0 else float("inf")
        c["leads_hoy"] = leads_hoy
        scored.append((score, c))

    min_score = min(s for s, _ in scored)
    ganadores = [c for s, c in scored if abs(s - min_score) < 0.001]
    return random.choice(ganadores)


# ─── Match de reglas ──────────────────────────────────────────────────────

def _evaluar_reglas(cur, lead: dict, now: datetime) -> Optional[dict]:
    """Devuelve la primera regla activa que matchea el lead (orden por
    prioridad ASC). None si ninguna matchea."""
    try:
        cur.execute(
            """
            SELECT * FROM crm.lead_assignment_rules
            WHERE activo = TRUE
            ORDER BY prioridad ASC
            """
        )
        reglas = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.debug("lead_assignment_rules no disponible: %s", exc)
        return None

    for r in reglas:
        regla = dict(r)
        if not _regla_matchea(cur, regla, lead, now):
            continue
        return regla
    return None


def _match_single_pattern(pat: str, text: str) -> bool:
    """Verifica si text matchea un único patrón (soporta % wildcard SQL LIKE)."""
    if not pat or not text:
        return False
    campana = text.lower()
    pat_lower = pat.lower().strip()
    if not pat_lower:
        return False
    if "%" in pat_lower:
        import re
        parts = [re.escape(p) for p in pat_lower.split("%")]
        regex = "^" + ".*".join(parts) + "$"
        return bool(re.match(regex, campana))
    return pat_lower in campana


def _match_pattern(pat: str, text: str) -> bool:
    """Verifica si text matchea alguno de los patrones especificados (separados por coma)."""
    if not pat or not text:
        return False
    patterns = [p.strip() for p in pat.split(",") if p.strip()]
    return any(_match_single_pattern(p, text) for p in patterns)


def _resolve_campana_texto(cur, lead: dict) -> str:
    c = str(lead.get("campana") or "")
    if not c:
        return ""
    try:
        cur.execute(
            "SELECT name FROM crm.meta_catalog_cache WHERE entity_type = 'campaign' AND entity_id = %s LIMIT 1",
            (c,),
        )
        row = cur.fetchone()
        if row:
            name = row["name"] if isinstance(row, dict) else row[0]
            if name:
                return f"{c} {name}"
    except Exception:
        pass
    return c


def _regla_matchea(cur, regla: dict, lead: dict, now: datetime) -> bool:
    # Fuente
    if regla.get("fuente_id") and lead.get("fuente_id") != regla["fuente_id"]:
        return False
    # API client
    if regla.get("api_client_id"):
        if str(lead.get("api_client_id") or "") != str(regla["api_client_id"]):
            return False

    campana_texto = _resolve_campana_texto(cur, lead)
    # Campaña pattern (incluir)
    pat = regla.get("campana_pattern")
    if pat:
        if not _match_pattern(pat, campana_texto):
            return False
    # Campaña exclude pattern (excluir)
    ex_pat = regla.get("campana_exclude_pattern")
    if ex_pat:
        if _match_pattern(ex_pat, campana_texto):
            return False
    # Palabras clave en observaciones
    if regla.get("palabras_clave"):
        obs = (lead.get("observaciones") or "").lower()
        if not any(kw.lower() in obs for kw in regla["palabras_clave"]):
            return False
    # Horario de la regla
    if regla.get("horario_inicio") and regla.get("horario_fin"):
        if not _esta_en_horario(now, regla["horario_inicio"], regla["horario_fin"]):
            return False
    # Dias de semana
    if regla.get("dias_semana"):
        if not _esta_en_dias_semana(now, regla["dias_semana"]):
            return False
    return True


# ─── Punto de entrada principal ───────────────────────────────────────────

def try_auto_assign(
    cur,
    *,
    lead_id: int,
    lead: dict,
    supervisor_id: str,
) -> Optional[AssignmentDecision]:
    """Intenta auto-asignar un lead. Devuelve None si la auto-asignacion
    no aplica (config OFF, equipo OFF, sin candidatos sin reglas) — el
    caller debe dejar el lead en el supervisor.

    Devuelve AssignmentDecision si se asigno a un asesor — el caller debe
    actualizar lead.asesor_id y persistir el log.

    NUNCA levanta excepcion: en caso de fallo interno devuelve None y se
    loguea. Esto preserva el comportamiento actual ante fallas.
    """
    t0 = time.perf_counter()
    try:
        config = get_config(cur)
        if not config.get("auto_asignar_enabled"):
            return None

        # Toggle por equipo
        if not _equipo_auto_enabled(cur, supervisor_id):
            return None

        now = _now_lima()
        lead_enriched = dict(lead)
        lead_enriched["id"] = lead_id

        # 1) Evaluar reglas configurables
        regla = _evaluar_reglas(cur, lead_enriched, now)
        if regla:
            decision = _aplicar_regla(cur, regla, supervisor_id, config, now)
            if decision:
                decision.duracion_ms = int((time.perf_counter() - t0) * 1000)
                return decision
            # Regla matcheo pero su target no fue elegible → segun fallback_si_lleno
            fallback = regla.get("fallback_si_lleno", "siguiente_regla")
            if fallback == "siguiente_regla":
                # Intentar siguientes reglas (recursion controlada)
                # Por ahora, simplificamos: pasamos a estrategia default
                pass
            elif fallback == "asignar_igual":
                # Forzar asignacion al target ignorando capacity
                decision = _aplicar_regla(
                    cur, regla, supervisor_id, config, now, ignorar_capacity=True
                )
                if decision:
                    decision.duracion_ms = int((time.perf_counter() - t0) * 1000)
                    return decision
            # 'estrategia_default' o fallback fallido → cae al round-robin

        # 2) Estrategia default
        if config.get("estrategia_default") == "manual":
            return None

        # round_robin_equipo
        decision = _round_robin_equipo(cur, supervisor_id, config, now, lead_id=lead_id)
        if decision:
            decision.duracion_ms = int((time.perf_counter() - t0) * 1000)
        return decision

    except Exception as exc:  # noqa: BLE001
        logger.warning("try_auto_assign fallo (lead_id=%s): %s", lead_id, exc)
        return None


def _round_robin_equipo(
    cur,
    supervisor_id: str,
    config: dict,
    now: datetime,
    *,
    lead_id: Optional[int] = None,
    skip_horario_check: bool = False,
) -> Optional[AssignmentDecision]:
    asesores = _get_asesores_del_equipo(
        cur, supervisor_id, incluir_supervisor=config.get("incluir_supervisor_en_rotacion", False)
    )
    if not asesores:
        return None

    # Horario global (si hay y la estrategia es 'asignar_supervisor' fuera de horario)
    inicio_g = config.get("horario_inicio")
    fin_g = config.get("horario_fin")
    en_horario_global = _esta_en_horario(now, inicio_g, fin_g)
    estrategia_fh = config.get("estrategia_fuera_horario", "asignar_igual")

    if not skip_horario_check:
        if not en_horario_global and estrategia_fh == "asignar_supervisor":
            return None
        if not en_horario_global and estrategia_fh == "cola_proximo_dia":
            # V047: encolar para que el job lo reintente al volver al horario.
            # Si lead_id es None, es un simulate() y no encolamos.
            if lead_id:
                _enqueue_pending(cur, lead_id, supervisor_id, motivo="fuera_horario")
            return None

    estrategia_cfg = config.get("estrategia_default", "round_robin_equipo")

    # V056: el modo 'estricto' siempre IGNORA cap. Solo respeta
    # disponible_rotacion + horario + ausencia + dias_semana.
    if estrategia_cfg == "round_robin_orden_estricto":
        elegibles_estricto = []
        descartados_estricto = []
        for a in asesores:
            motivo = None
            if not a["disponible_rotacion"]:
                motivo = "marcado como no disponible"
            elif _esta_en_ausencia(now, a.get("ausencia_desde"), a.get("ausencia_hasta")):
                motivo = f"en ausencia ({a.get('motivo_ausencia') or 'programada'})"
            else:
                ind_inicio = a.get("horario_inicio")
                ind_fin = a.get("horario_fin")
                if ind_inicio and ind_fin and not _esta_en_horario(now, ind_inicio, ind_fin):
                    motivo = f"fuera de su horario ({ind_inicio.strftime('%H:%M')}-{ind_fin.strftime('%H:%M')})"
                elif not _esta_en_dias_semana(now, a.get("dias_semana")):
                    motivo = "no trabaja este dia de la semana"
            if motivo:
                descartados_estricto.append({
                    "user_id": a["user_id"],
                    "nombre": a["nombre"],
                    "motivo_descarte": motivo,
                })
            else:
                elegibles_estricto.append(a)
        elegibles, descartados = elegibles_estricto, descartados_estricto
    else:
        elegibles, descartados = _filtrar_elegibles(asesores, cur, config, now)

    if not elegibles:
        # Aplicar estrategia_sin_disponibles
        estrategia_sd = config.get("estrategia_sin_disponibles", "asignar_supervisor")
        if estrategia_sd == "ignorar_capacity":
            # Reintenta solo con filtro de disponible+horario+ausencia, sin capacity
            disponibles_no_lleno = []
            for a in asesores:
                if not a["disponible_rotacion"]:
                    continue
                if _esta_en_ausencia(now, a.get("ausencia_desde"), a.get("ausencia_hasta")):
                    continue
                disponibles_no_lleno.append(a)
            if disponibles_no_lleno:
                elegibles = disponibles_no_lleno
            else:
                return None
        else:
            return None

    # V055/V056: dispatch segun estrategia configurada.
    logger.info(
        "[routing] supervisor=%s estrategia_cfg=%s elegibles=%d descartados=%d",
        supervisor_id, estrategia_cfg, len(elegibles), len(descartados),
    )

    if estrategia_cfg in ("round_robin_orden", "round_robin_orden_estricto"):
        elegido = _pick_round_robin_orden(cur, elegibles, supervisor_id)
        estrategia_aplicada = estrategia_cfg
        logger.info(
            "[routing/%s] elegido=%s (orden=%s) entre [%s]",
            estrategia_cfg, elegido.get("nombre"), elegido.get("orden"),
            ", ".join(f"{e.get('nombre')}#{e.get('orden')}" for e in elegibles),
        )
        # Marcamos el ganador despues del UPDATE del lead — pero como aqui
        # solo decidimos, hacemos el marcado ahora. Si el caller falla
        # despues, el cursor de last_assigned_at queda movido — aceptable
        # (peor caso: salta una posicion en el round-robin, no genera bug).
        _marcar_ultimo_asignado(cur, supervisor_id, elegido["user_id"])
    elif estrategia_cfg == "round_robin_balanceado":
        elegido = _pick_round_robin_balanceado(cur, elegibles, supervisor_id)
        estrategia_aplicada = "round_robin_balanceado"
        # Tambien actualizamos el cursor para que el modo balanceado pueda
        # caer en orden cuando haya empate de 0 leads (consistencia con UI).
        _marcar_ultimo_asignado(cur, supervisor_id, elegido["user_id"])
    else:
        elegido = _pick_round_robin_ponderado(cur, elegibles)
        estrategia_aplicada = "round_robin_equipo"
        logger.info(
            "[routing/carga] elegido=%s leads_hoy=%s peso=%s",
            elegido.get("nombre"), elegido.get("leads_hoy"), elegido.get("peso_rotacion"),
        )

    candidatos_evaluados = [
        {
            "user_id": e["user_id"],
            "nombre": e["nombre"],
            "orden": e.get("orden"),
            "leads_abiertos": e.get("leads_abiertos"),
            "leads_hoy": e.get("leads_hoy"),
            "peso": e.get("peso_rotacion"),
            "elegido": e["user_id"] == elegido["user_id"],
        }
        for e in elegibles
    ] + descartados

    if estrategia_aplicada == "round_robin_orden":
        razon = (
            f"Round-robin por orden: {elegido['nombre']} (posicion "
            f"{elegido.get('orden') or '?'}) entre {len(elegibles)} "
            f"elegibles ({len(descartados)} descartados)."
        )
    elif estrategia_aplicada == "round_robin_orden_estricto":
        razon = (
            f"Round-robin estricto: {elegido['nombre']} (posicion "
            f"{elegido.get('orden') or '?'}) — cap ignorado por configuracion."
        )
    elif estrategia_aplicada == "round_robin_balanceado":
        razon = (
            f"Round-robin balanceado: {elegido['nombre']} (posicion "
            f"{elegido.get('orden') or '?'}) — menor carga en ultimos 7 dias."
        )
    else:
        razon = (
            f"Round-robin por carga: {elegido['nombre']} elegido entre "
            f"{len(elegibles)} elegibles ({len(descartados)} descartados)."
        )
    return AssignmentDecision(
        asignado_a_id=elegido["user_id"],
        estrategia=estrategia_aplicada,
        razon=razon,
        candidatos=candidatos_evaluados,
    )


def _aplicar_regla(
    cur,
    regla: dict,
    supervisor_id: str,
    config: dict,
    now: datetime,
    ignorar_capacity: bool = False,
) -> Optional[AssignmentDecision]:
    tipo = regla["asignar_a_tipo"]

    if tipo == "asesor_especifico":
        target_id = str(regla["asignar_a_id"])
        if not target_id:
            return None
        # Verificar elegibilidad del target (a menos que ignoremos capacity)
        if not ignorar_capacity:
            elegible = _es_elegible_individual(cur, target_id, config, now)
            if not elegible:
                return None
        return AssignmentDecision(
            asignado_a_id=target_id,
            estrategia="regla",
            regla_id=regla["id"],
            razon=f"Regla #{regla['id']} '{regla['nombre']}' → asesor especifico.",
            candidatos=[{"user_id": target_id, "elegido": True}],
        )

    if tipo == "equipo_round_robin":
        sup_objetivo = str(regla["asignar_a_id"]) if regla.get("asignar_a_id") else supervisor_id
        sub = _round_robin_equipo(cur, sup_objetivo, config, now)
        if sub:
            sub.estrategia = "regla"
            sub.regla_id = regla["id"]
            sub.razon = f"Regla #{regla['id']} '{regla['nombre']}' → equipo: " + sub.razon
        return sub

    if tipo == "asesor_round_robin_global":
        decision = _round_robin_global(cur, config, now)
        if decision:
            decision.estrategia = "regla"
            decision.regla_id = regla["id"]
            decision.razon = f"Regla #{regla['id']} '{regla['nombre']}' → global: " + decision.razon
        return decision

    return None


def _es_elegible_individual(cur, asesor_id: str, config: dict, now: datetime) -> bool:
    cur.execute(
        """
        SELECT
            u.id::text AS user_id, u.is_active,
            COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
            s.max_leads_abiertos, s.horario_inicio, s.horario_fin,
            s.dias_semana, s.ausencia_desde, s.ausencia_hasta,
            COALESCE(s.peso_rotacion, 1.0)::float AS peso_rotacion,
            TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre
        FROM auth.users u
        LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
        WHERE u.id = %s::uuid
          AND u.is_active = TRUE
          AND COALESCE(u.login_blocked, FALSE) = FALSE  -- V094.6 — patrón estándar "Freeze"
        """,
        (asesor_id,),
    )
    row = cur.fetchone()
    if not row:
        return False
    asesor = dict(row)
    elegibles, _ = _filtrar_elegibles([asesor], cur, config, now)
    return len(elegibles) > 0


def _round_robin_global(
    cur,
    config: dict,
    now: datetime,
) -> Optional[AssignmentDecision]:
    """Round-robin entre TODOS los asesores activos (no limitado por equipo)."""
    cur.execute(
        """
        SELECT
            u.id::text AS user_id,
            TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre,
            u.email, u.is_active,
            COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
            s.max_leads_abiertos,
            s.horario_inicio, s.horario_fin, s.dias_semana,
            s.ausencia_desde, s.ausencia_hasta, s.motivo_ausencia,
            COALESCE(s.peso_rotacion, 1.0)::float AS peso_rotacion
        FROM auth.users u
        LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
        WHERE u.role = 'asesor'
          AND u.is_active = TRUE
          AND COALESCE(u.login_blocked, FALSE) = FALSE  -- V094.6 — patrón estándar "Freeze"
        """
    )
    asesores = [dict(r) for r in cur.fetchall()]
    if not asesores:
        return None

    elegibles, descartados = _filtrar_elegibles(asesores, cur, config, now)
    if not elegibles:
        return None

    elegido = _pick_round_robin_ponderado(cur, elegibles)
    candidatos = [
        {"user_id": e["user_id"], "nombre": e["nombre"], "elegido": e["user_id"] == elegido["user_id"]}
        for e in elegibles
    ] + descartados
    return AssignmentDecision(
        asignado_a_id=elegido["user_id"],
        estrategia="round_robin_global",
        razon=f"Round-robin global: {elegido['nombre']} ({len(elegibles)} elegibles).",
        candidatos=candidatos,
    )


# ─── Persistencia del log ─────────────────────────────────────────────────

def log_decision(
    cur,
    *,
    lead_id: int,
    supervisor_id: str,
    decision: AssignmentDecision,
) -> None:
    try:
        cur.execute(
            """
            INSERT INTO crm.assignment_log
                (lead_id, estrategia, regla_aplicada_id, supervisor_id,
                 asignado_a_id, candidatos_evaluados, razon, duracion_ms)
            VALUES (%s, %s, %s, %s::uuid, %s::uuid, %s::jsonb, %s, %s)
            """,
            (
                lead_id, decision.estrategia, decision.regla_id,
                supervisor_id, decision.asignado_a_id,
                json.dumps(decision.candidatos, default=str),
                decision.razon, decision.duracion_ms,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("assignment_log insert fallo: %s", exc)


# ─── Cola de pendientes (V047): encolar + procesar ────────────────────────

def _enqueue_pending(cur, lead_id: int, supervisor_id: str, motivo: str) -> None:
    """Encola un lead que el motor difirió. Best-effort: si la tabla no
    existe (V047 no aplicada todavía), no rompe el flujo principal."""
    try:
        cur.execute(
            """
            INSERT INTO crm.assignment_pending (lead_id, supervisor_id, motivo)
            VALUES (%s, %s::uuid, %s)
            ON CONFLICT (lead_id) DO UPDATE
            SET intentos = crm.assignment_pending.intentos + 1,
                proximo_intento = NOW() + INTERVAL '15 minutes',
                updated_at = NOW()
            """,
            (lead_id, supervisor_id, motivo),
        )
        logger.info("[auto-assign] lead=%s encolado motivo=%s", lead_id, motivo)
    except Exception as exc:  # noqa: BLE001
        logger.debug("assignment_pending no disponible: %s", exc)


MAX_INTENTOS = 96  # 96 * 15 min = 24 horas


def process_pending_queue(cur) -> dict:
    """Procesa la cola de leads pendientes. Llamado por el job cada 15 min.

    Para cada fila con proximo_intento <= NOW():
      - Reintenta la auto-asignación con el motor existente.
      - Si éxito → asigna al asesor, loguea, borra de la cola.
      - Si falla → incrementa intentos y reagenda en +15 min.
      - Si llega a MAX_INTENTOS (24 h) → descarta y queda al supervisor.

    Devuelve estadísticas: {total, asignados, reagendados, descartados}.
    """
    config = get_config(cur)
    if not config.get("auto_asignar_enabled"):
        return {"total": 0, "asignados": 0, "reagendados": 0, "descartados": 0,
                "skipped_reason": "auto_asignar_enabled=False"}

    # V075.1 — Bring nombres/apellidos/fuente_nombre para poder armar el
    # texto del push al asesor que se asigna desde la cola. Antes este
    # query solo traia campos para la decision de routing, sin texto
    # humano-readable. Ahora notify_new_lead recibe nombre completo y
    # fuente igual que el flujo de ingest inmediato → comportamiento
    # uniforme + coalescer aplica naturalmente.
    cur.execute(
        """
        SELECT ap.id, ap.lead_id, ap.supervisor_id::text AS supervisor_id,
               ap.motivo, ap.intentos,
               l.fuente_id, l.campana, l.observaciones, l.api_client_id::text AS api_client_id,
               l.nombres, l.apellidos,
               COALESCE(f.nombre, '') AS fuente_nombre
        FROM crm.assignment_pending ap
        JOIN crm.leads l    ON l.id = ap.lead_id
        LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
        WHERE ap.proximo_intento <= NOW()
          AND ap.intentos < %s
          AND l.activo = TRUE
          AND l.asesor_id IS NULL
        ORDER BY ap.proximo_intento ASC
        LIMIT 100
        """,
        (MAX_INTENTOS,),
    )
    rows = cur.fetchall()
    if not rows:
        # Limpieza de filas descartadas con muchos intentos
        cur.execute(
            "DELETE FROM crm.assignment_pending WHERE intentos >= %s OR "
            "lead_id IN (SELECT id FROM crm.leads WHERE asesor_id IS NOT NULL OR activo = FALSE)",
            (MAX_INTENTOS,),
        )
        return {"total": 0, "asignados": 0, "reagendados": 0, "descartados": cur.rowcount,
                "pushes_pendientes": []}

    asignados = 0
    reagendados = 0
    descartados = 0
    # V075.1 — Acumular pushes para enviarlas DESPUES del commit en el
    # caller (scheduler._run_assignment_queue_cycle). Patron tomado de
    # assignments_service.reassign_one: nunca disparar push antes de que
    # la DB confirme la asignacion. Si el commit falla, no se manda el
    # push y el siguiente tick reintenta la asignacion limpio.
    pushes_pendientes: list[dict] = []

    for row in rows:
        row_d = dict(row)
        lead_id = row_d["lead_id"]
        supervisor_id = row_d["supervisor_id"]
        lead_dict = {
            "fuente_id":     row_d.get("fuente_id"),
            "api_client_id": row_d.get("api_client_id"),
            "campana":       row_d.get("campana"),
            "observaciones": row_d.get("observaciones"),
        }
        try:
            decision = try_auto_assign(
                cur, lead_id=lead_id, lead=lead_dict, supervisor_id=supervisor_id,
            )
            if decision and decision.asignado_a_id and decision.asignado_a_id != supervisor_id:
                # Éxito → actualiza lead y borra de la cola
                cur.execute(
                    "UPDATE crm.leads SET asesor_id = %s::uuid WHERE id = %s",
                    (decision.asignado_a_id, lead_id),
                )
                log_decision(cur, lead_id=lead_id, supervisor_id=supervisor_id, decision=decision)
                cur.execute(
                    "DELETE FROM crm.assignment_pending WHERE lead_id = %s",
                    (lead_id,),
                )
                asignados += 1
                logger.info("[auto-assign-queue] lead=%s asignado a %s", lead_id, decision.asignado_a_id)

                # V075.1 — Acumular push para post-commit. Lead name se
                # arma igual que en ingest.py:408 (paridad).
                lead_name = f"{row_d.get('nombres') or ''} {row_d.get('apellidos') or ''}".strip()
                pushes_pendientes.append({
                    "asesor_id": decision.asignado_a_id,
                    "lead_id":   lead_id,
                    "lead_name": lead_name,
                    "fuente":    row_d.get("fuente_nombre") or "",
                })
            else:
                # Falló → reagendar
                new_intentos = row_d["intentos"] + 1
                if new_intentos >= MAX_INTENTOS:
                    cur.execute(
                        "DELETE FROM crm.assignment_pending WHERE lead_id = %s", (lead_id,),
                    )
                    descartados += 1
                    logger.info("[auto-assign-queue] lead=%s descartado tras %d intentos", lead_id, new_intentos)
                else:
                    cur.execute(
                        """
                        UPDATE crm.assignment_pending
                        SET intentos = %s,
                            proximo_intento = NOW() + INTERVAL '15 minutes',
                            updated_at = NOW(),
                            ultimo_error = NULL
                        WHERE lead_id = %s
                        """,
                        (new_intentos, lead_id),
                    )
                    reagendados += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[auto-assign-queue] error lead=%s: %s", lead_id, exc)
            cur.execute(
                """
                UPDATE crm.assignment_pending
                SET intentos = intentos + 1,
                    proximo_intento = NOW() + INTERVAL '30 minutes',
                    ultimo_error = %s,
                    updated_at = NOW()
                WHERE lead_id = %s
                """,
                (str(exc)[:500], lead_id),
            )
            reagendados += 1

    return {
        "total": len(rows),
        "asignados": asignados,
        "reagendados": reagendados,
        "descartados": descartados,
        # V075.1 — Lista de pushes a enviar DESPUES del commit del caller.
        # Si esta lista es no-vacia, el caller debe iterar y llamar
        # notify_new_lead por cada item. El coalescer (V075) se encarga
        # de agrupar si son >=3 leads para el mismo asesor.
        "pushes_pendientes": pushes_pendientes,
    }


# ─── Preview / simulador (para UI) ────────────────────────────────────────

def simulate(cur, lead_dict: dict, supervisor_id: str) -> dict:
    """Simula una decision sin persistir nada. Util para el preview en la UI."""
    config = get_config(cur)
    if not config.get("auto_asignar_enabled"):
        return {"asignado_a_id": None, "estrategia": "config_off", "razon": "Auto-asignacion deshabilitada globalmente."}
    if not _equipo_auto_enabled(cur, supervisor_id):
        return {"asignado_a_id": None, "estrategia": "equipo_off", "razon": "Equipo del supervisor no tiene auto-asignacion activada."}

    decision = try_auto_assign(cur, lead_id=0, lead=lead_dict, supervisor_id=supervisor_id)
    if not decision:
        return {"asignado_a_id": None, "estrategia": "fallback_supervisor", "razon": "Sin candidatos elegibles. Fallback al supervisor."}
    return {
        "asignado_a_id": decision.asignado_a_id,
        "estrategia": decision.estrategia,
        "regla_id": decision.regla_id,
        "razon": decision.razon,
        "candidatos": decision.candidatos,
        "duracion_ms": decision.duracion_ms,
    }

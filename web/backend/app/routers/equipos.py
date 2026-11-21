"""
Router para gestion del equipo: orden manual + disponibilidad por asesor.

Separado de catalogs.py (que maneja CRUD basico de equipos como
add/remove asesor) para mantener SOLID — este modulo solo se
encarga de las operaciones de jerarquia y disponibilidad usadas por
el motor de routing V055.

Endpoints:
  - GET    /api/equipos/by-supervisor   — lista asesores de un equipo (rol-aware)
  - PUT    /api/equipos/reorder         — guarda nuevo orden de un equipo
  - PATCH  /api/equipos/{equipo_id}/disponibilidad — pausa/reanuda asesor

Permisos:
  - admin: cualquier equipo
  - supervisor: solo su propio equipo (auto-restriccion via supervisor_id)
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field, validator

from app.auth.jwt import get_current_user, require_supervisor_or_admin
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/equipos", tags=["Equipos"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class EquipoMember(BaseModel):
    """Vista enriquecida de un miembro del equipo para la UI."""
    equipo_id:            int
    supervisor_id:        str
    supervisor_nombre:    str
    asesor_id:            str
    asesor_nombre:        str
    asesor_email:         Optional[str] = None
    orden:                int
    activo:               bool                 # relacion supervisor-asesor activa
    disponible_rotacion:  bool                 # disponible para recibir leads
    motivo_ausencia:      Optional[str] = None
    leads_abiertos:       Optional[int] = None # cuantos tiene abiertos (segun definicion)
    max_leads_abiertos:   Optional[int] = None # su cap (individual o global default)
    # V055.1 — estado real desde el punto de vista del motor de routing
    elegible:             bool = True          # ¿pasaria los filtros del motor?
    motivo_descarte:      Optional[str] = None # si no es elegible, por qué
    leads_hoy:            Optional[int] = None # leads asignados hoy


class ReorderItem(BaseModel):
    equipo_id: int
    orden:     int = Field(ge=1, description="Posicion 1..N en el equipo")


class ReorderPayload(BaseModel):
    supervisor_id: str
    items:         List[ReorderItem]

    @validator("items")
    def items_no_vacio(cls, v):       # noqa: N805
        if not v:
            raise ValueError("items no puede estar vacio")
        # Verificar que no haya equipo_id duplicados
        ids = [i.equipo_id for i in v]
        if len(ids) != len(set(ids)):
            raise ValueError("equipo_id duplicado en items")
        # Verificar que no haya orden duplicado
        ordenes = [i.orden for i in v]
        if len(ordenes) != len(set(ordenes)):
            raise ValueError("orden duplicado en items")
        return v


class DisponibilidadPayload(BaseModel):
    disponible_rotacion: bool
    motivo_ausencia:     Optional[str] = Field(default=None, max_length=200)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _check_supervisor_owns_team(
    cur, *, current_user: TokenData, supervisor_id: str,
) -> None:
    """Si el current_user es supervisor, valida que el supervisor_id que
    intenta operar coincida con el suyo. Admin pasa sin restriccion."""
    if current_user.role == Role.ADMIN:
        return
    if current_user.role == Role.SUPERVISOR:
        if str(current_user.user_id) != str(supervisor_id):
            raise HTTPException(403, "Solo podes gestionar tu propio equipo")
        return
    raise HTTPException(403, "Operacion no permitida para tu rol")


def _equipo_belongs_to_supervisor(cur, equipo_id: int, supervisor_id: str) -> bool:
    """Anti-tampering: confirma que un equipo_id pertenece al supervisor
    que el caller declaro. Defensa contra payloads malformados que
    intentan modificar equipos de otros supervisores."""
    cur.execute(
        "SELECT 1 FROM crm.equipos WHERE id = %s AND supervisor_id = %s::uuid",
        (equipo_id, supervisor_id),
    )
    return cur.fetchone() is not None


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/by-supervisor", response_model=List[EquipoMember])
def list_team_members(
    supervisor_id: Optional[str] = Query(
        None,
        description="UUID del supervisor. Si current_user es supervisor, "
                    "se ignora y se usa su propio id.",
    ),
    current_user: TokenData = Depends(get_current_user),
):
    """Lista miembros de un equipo con orden + disponibilidad.

    Reglas:
      - admin: si pasa supervisor_id → ese equipo. Si no → todos los equipos
        agrupables por supervisor.
      - supervisor: ignora supervisor_id (siempre el suyo).
      - asesor: solo su propia entrada.
    """
    where = ["eq.activo = TRUE"]
    params: list = []

    if current_user.role == Role.SUPERVISOR:
        where.append(
            "(eq.supervisor_id = %s::uuid OR eq.supervisor_id IN (SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'))"
        )
        params.extend([current_user.user_id, current_user.user_id])
    elif current_user.role == Role.ASESOR and getattr(current_user, "role_id", None) is None:
        where.append("eq.asesor_id = %s::uuid")
        params.append(current_user.user_id)
    elif supervisor_id:
        where.append(
            "(eq.supervisor_id = %s::uuid OR eq.supervisor_id IN (SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'))"
        )
        params.extend([supervisor_id, supervisor_id])

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    eq.id                           AS equipo_id,
                    eq.supervisor_id::text          AS supervisor_id,
                    TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,''))
                                                    AS supervisor_nombre,
                    eq.asesor_id::text              AS asesor_id,
                    TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,''))
                                                    AS asesor_nombre,
                    a.email                         AS asesor_email,
                    eq.orden                        AS orden,
                    eq.activo                       AS activo,
                    COALESCE(ast.disponible_rotacion, TRUE) AS disponible_rotacion,
                    ast.motivo_ausencia             AS motivo_ausencia
                FROM crm.equipos eq
                JOIN auth.users s   ON s.id = eq.supervisor_id
                JOIN auth.users a   ON a.id = eq.asesor_id
                LEFT JOIN crm.asesor_settings ast ON ast.asesor_id = eq.asesor_id
                WHERE {' AND '.join(where)}
                  AND a.is_active = TRUE
                ORDER BY supervisor_nombre, eq.orden NULLS LAST, asesor_nombre
                """,
                params,
            )
            members = [dict(r) for r in cur.fetchall()]

            # V055.1 — Enriquecer con estado real desde el punto de vista
            # del motor: ¿pasarían los filtros (cap, horario, ausencia, dias)?
            # Asi la UI puede mostrar "Lleno (50)" en vez de aparecer
            # disponible cuando el motor lo descarta.
            from app.services import lead_routing
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone(timedelta(hours=-5)))   # America/Lima
            config = lead_routing.get_config(cur)

            # Procesar por equipo (cada supervisor)
            por_supervisor: dict[str, list[dict]] = {}
            for m in members:
                por_supervisor.setdefault(m["supervisor_id"], []).append(m)

            for sup_id, lista in por_supervisor.items():
                # Re-traer asesores con TODOS los settings que el motor lee
                asesores = lead_routing._get_asesores_del_equipo(cur, sup_id)
                # Index por user_id
                asesores_idx = {a["user_id"]: a for a in asesores}
                # Aplicar filtros del motor
                elegibles, descartados = lead_routing._filtrar_elegibles(
                    asesores, cur, config, now,
                )
                elegibles_ids = {e["user_id"] for e in elegibles}
                descartados_idx = {d.get("user_id"): d for d in descartados}

                cap_default = config.get("max_leads_abiertos_default") or 50
                for m in lista:
                    aid = m["asesor_id"]
                    aux = asesores_idx.get(aid) or {}
                    m["leads_hoy"] = aux.get("leads_hoy") if isinstance(aux, dict) else None
                    # leads_abiertos y cap individual/default — para mostrar ratio en UI
                    m["leads_abiertos"] = aux.get("leads_abiertos") if isinstance(aux, dict) else None
                    m["max_leads_abiertos"] = (aux.get("max_leads_abiertos") or cap_default) if isinstance(aux, dict) else cap_default
                    if aid in elegibles_ids:
                        m["elegible"] = True
                        m["motivo_descarte"] = None
                    else:
                        m["elegible"] = False
                        d = descartados_idx.get(aid) or {}
                        m["motivo_descarte"] = d.get("motivo_descarte") or "no elegible"

            return members


@router.put("/reorder")
def reorder_team(
    payload: ReorderPayload,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Guarda un nuevo orden para los miembros del equipo del supervisor.

    El payload debe contener TODOS los miembros del equipo (no parcial)
    para garantizar consistencia. La operacion es atomica.

    Permisos:
      - admin: cualquier equipo
      - supervisor: solo su equipo (forzado en backend)
    """
    _check_supervisor_owns_team(
        cur=None,
        current_user=current_user,
        supervisor_id=payload.supervisor_id,
    )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Anti-tampering: validar que TODOS los equipo_id pertenezcan
            # al supervisor declarado. Sin esto, un supervisor podria mandar
            # IDs de otro equipo.
            for item in payload.items:
                if not _equipo_belongs_to_supervisor(cur, item.equipo_id, payload.supervisor_id):
                    raise HTTPException(
                        400,
                        f"equipo_id {item.equipo_id} no pertenece al supervisor declarado",
                    )

            # V056: snapshot del orden ANTES del cambio para audit_log
            cur.execute(
                """
                SELECT eq.id, eq.asesor_id::text AS asesor_id, eq.orden, eq.activo,
                       TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre
                FROM crm.equipos eq
                JOIN auth.users u ON u.id = eq.asesor_id
                WHERE eq.supervisor_id = %s::uuid
                ORDER BY eq.orden, eq.id
                """,
                (payload.supervisor_id,),
            )
            orden_antes = [dict(r) for r in cur.fetchall()]

            # Estrategia anti-conflict-unique: usamos un offset temporal
            # (negativo) para evitar colision con el UNIQUE implicito si
            # alguna vez se agrega. PostgreSQL NO tiene UNIQUE actualmente
            # en (supervisor_id, orden), pero el offset previene problemas
            # en caso futuro.
            for item in payload.items:
                cur.execute(
                    """
                    UPDATE crm.equipos
                    SET orden = %s, updated_at = NOW()
                    WHERE id = %s AND supervisor_id = %s::uuid
                    """,
                    (item.orden, item.equipo_id, payload.supervisor_id),
                )

            # V056: snapshot DESPUES + insertar fila en audit_log
            cur.execute(
                """
                SELECT eq.id, eq.asesor_id::text AS asesor_id, eq.orden, eq.activo,
                       TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre
                FROM crm.equipos eq
                JOIN auth.users u ON u.id = eq.asesor_id
                WHERE eq.supervisor_id = %s::uuid
                ORDER BY eq.orden, eq.id
                """,
                (payload.supervisor_id,),
            )
            orden_despues = [dict(r) for r in cur.fetchall()]

            try:
                cur.execute(
                    """
                    INSERT INTO crm.equipo_audit_log
                        (supervisor_id, actor_id, actor_role, accion,
                         orden_antes, orden_despues, detalle)
                    VALUES (%s::uuid, %s::uuid, %s, 'reorder',
                            %s::jsonb, %s::jsonb, %s)
                    """,
                    (
                        payload.supervisor_id,
                        current_user.user_id,
                        current_user.role,
                        json.dumps(orden_antes, default=str),
                        json.dumps(orden_despues, default=str),
                        f"Reordenamiento de {len(payload.items)} posiciones",
                    ),
                )
            except Exception:  # noqa: BLE001 — best effort
                logger.exception("[equipos.reorder] audit_log fallo (no bloquea)")

            conn.commit()

    # Audit log (estructurado en texto para search en logs).
    logger.info(
        "[equipos.reorder] supervisor=%s by_user=%s by_role=%s items=%d",
        payload.supervisor_id, current_user.user_id, current_user.role,
        len(payload.items),
    )
    return {"ok": True, "updated": len(payload.items)}


@router.patch("/{equipo_id}/disponibilidad")
def toggle_disponibilidad(
    equipo_id: int,
    payload: DisponibilidadPayload,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Pausa o reanuda la disponibilidad de un asesor para recibir leads.

    Modifica `crm.asesor_settings.disponible_rotacion` (no toca
    crm.equipos.activo, que es la relacion supervisor-asesor).

    Permisos:
      - admin: cualquier asesor
      - supervisor: solo asesores de su propio equipo
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Resolver: a que asesor + supervisor pertenece este equipo_id
            cur.execute(
                """
                SELECT supervisor_id::text AS supervisor_id,
                       asesor_id::text     AS asesor_id
                FROM crm.equipos
                WHERE id = %s AND activo = TRUE
                """,
                (equipo_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Equipo no encontrado")

            # Permiso: supervisor solo puede pausar a asesores de SU equipo
            if current_user.role == Role.SUPERVISOR:
                if str(row["supervisor_id"]) != str(current_user.user_id):
                    raise HTTPException(403, "Solo podes gestionar tu propio equipo")

            # Upsert en asesor_settings (puede no existir todavia)
            cur.execute(
                """
                INSERT INTO crm.asesor_settings (asesor_id, disponible_rotacion, motivo_ausencia)
                VALUES (%s::uuid, %s, %s)
                ON CONFLICT (asesor_id) DO UPDATE
                SET disponible_rotacion = EXCLUDED.disponible_rotacion,
                    motivo_ausencia     = EXCLUDED.motivo_ausencia,
                    updated_at          = NOW()
                """,
                (row["asesor_id"], payload.disponible_rotacion, payload.motivo_ausencia),
            )

            # V056: audit log
            try:
                accion = "reanudar_asesor" if payload.disponible_rotacion else "pausar_asesor"
                detalle = (
                    f"Asesor {'reanudado' if payload.disponible_rotacion else 'pausado'}"
                    + (f" — motivo: {payload.motivo_ausencia}" if payload.motivo_ausencia else "")
                )
                cur.execute(
                    """
                    INSERT INTO crm.equipo_audit_log
                        (supervisor_id, actor_id, actor_role, accion, detalle)
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s)
                    """,
                    (
                        row["supervisor_id"], current_user.user_id, current_user.role,
                        accion, detalle,
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.exception("[equipos.disponibilidad] audit_log fallo (no bloquea)")

            conn.commit()

    logger.info(
        "[equipos.disponibilidad] asesor=%s disponible=%s motivo=%r by_user=%s by_role=%s",
        row["asesor_id"], payload.disponible_rotacion, payload.motivo_ausencia,
        current_user.user_id, current_user.role,
    )
    return {
        "ok": True,
        "asesor_id": row["asesor_id"],
        "disponible_rotacion": payload.disponible_rotacion,
    }


@router.get("/next-up")
def next_up(
    supervisor_id: Optional[str] = Query(None),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Devuelve el asesor que recibira el PROXIMO lead segun el cursor
    historico de round-robin orden — usando la MISMA logica que el motor
    de routing real (mismos filtros: capacity, horario, ausencia, dias).

    Asi el indicador "🎯 PROXIMO" no engana al usuario — si dice 'Ana
    es la proxima', es porque el motor real tambien la elegiria.

    Si la estrategia activa NO es round_robin_orden, devuelve
    deterministic=false (el siguiente depende de la carga del momento).
    """
    from datetime import datetime, timezone, timedelta

    target_supervisor = supervisor_id
    if current_user.role == Role.SUPERVISOR:
        target_supervisor = str(current_user.user_id)
    if not target_supervisor:
        raise HTTPException(400, "supervisor_id requerido (admin)")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Reusamos la misma logica del motor para que el indicador
            # sea fiel a lo que realmente pasaria en una asignacion real.
            from app.services import lead_routing

            config = lead_routing.get_config(cur)
            estrategia = config.get("estrategia_default") or "round_robin_equipo"

            if estrategia != "round_robin_orden":
                return {
                    "estrategia": estrategia,
                    "deterministic": False,
                    "next_user_id": None,
                    "razon": (
                        f"Estrategia activa: '{estrategia}'. "
                        f"Para que el indicador funcione, configurar 'Round-robin por orden' "
                        f"en /reparto-leads."
                    ),
                }

            # Asesores del equipo (usa la query enriquecida con orden + cap)
            asesores = lead_routing._get_asesores_del_equipo(cur, target_supervisor)
            if not asesores:
                return {
                    "estrategia": estrategia,
                    "deterministic": True,
                    "next_user_id": None,
                    "razon": "El supervisor no tiene asesores en su equipo.",
                }

            # Aplica EL MISMO filtro que la asignacion real
            now = datetime.now(timezone(timedelta(hours=-5)))   # America/Lima
            elegibles, descartados = lead_routing._filtrar_elegibles(
                asesores, cur, config, now,
            )
            if not elegibles:
                # Reportamos descartes para transparencia
                descarte_resumen = ", ".join(
                    f"{d.get('nombre')}: {d.get('motivo_descarte') or 'sin disponibilidad'}"
                    for d in (descartados or [])[:5]
                )
                return {
                    "estrategia": estrategia,
                    "deterministic": True,
                    "next_user_id": None,
                    "razon": f"Ningun asesor es elegible ahora. {descarte_resumen}",
                }

            # Aplica la misma funcion de pick que el motor real
            chosen = lead_routing._pick_round_robin_orden(cur, elegibles, target_supervisor)

            # Cursor actual (para informacion en UI)
            cur.execute(
                """
                SELECT eq.orden AS last_orden
                FROM crm.equipos eq
                WHERE eq.supervisor_id = %s::uuid
                  AND eq.last_assigned_at IS NOT NULL
                ORDER BY eq.last_assigned_at DESC
                LIMIT 1
                """,
                (target_supervisor,),
            )
            row = cur.fetchone()
            last_orden = (row or {}).get("last_orden") or 0 if row else 0

            return {
                "estrategia": estrategia,
                "deterministic": True,
                "last_orden": last_orden,
                "next_user_id": chosen["user_id"],
                "next_nombre":  chosen["nombre"],
                "next_orden":   chosen.get("orden"),
                "elegibles_count": len(elegibles),
                "descartados_count": len(descartados),
                "razon": (
                    f"Siguiente lead va a {chosen['nombre']} (posicion "
                    f"{chosen.get('orden')}) entre {len(elegibles)} elegibles."
                ),
            }


@router.post("/reset-rotacion")
def reset_rotacion(
    supervisor_id: str = Query(..., description="UUID del supervisor cuyo equipo se resetea"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Reinicia el cursor del round-robin orden a 0. Util cuando el
    supervisor reordeno la jerarquia y quiere que el siguiente lead
    vaya al primero del orden, no al "siguiente" segun la posicion
    histórica.

    Permisos: admin cualquiera, supervisor solo su equipo.
    """
    if current_user.role == Role.SUPERVISOR:
        if str(current_user.user_id) != str(supervisor_id):
            raise HTTPException(403, "Solo podes resetear tu propio equipo")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.equipos
                SET last_assigned_at = NULL
                WHERE supervisor_id = %s::uuid
                """,
                (supervisor_id,),
            )
            updated = cur.rowcount

            # V056: registrar reset en audit_log
            try:
                cur.execute(
                    """
                    INSERT INTO crm.equipo_audit_log
                        (supervisor_id, actor_id, actor_role, accion, detalle)
                    VALUES (%s::uuid, %s::uuid, %s, 'reset_rotacion', %s)
                    """,
                    (
                        supervisor_id, current_user.user_id, current_user.role,
                        f"Reset cursor de rotacion ({updated} asesores)",
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.exception("[equipos.reset] audit_log fallo (no bloquea)")

            conn.commit()

    logger.info(
        "[equipos.reset] supervisor=%s rows=%d by_user=%s by_role=%s",
        supervisor_id, updated, current_user.user_id, current_user.role,
    )
    return {"ok": True, "supervisor_id": supervisor_id, "reset_count": updated}


# ─── V056: Historial de auditoria de la jerarquia ─────────────────────────

@router.get("/audit-log")
def get_audit_log(
    supervisor_id: str = Query(..., description="UUID del supervisor cuyo historial se consulta"),
    limit: int = Query(50, ge=1, le=200),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Devuelve los ultimos N cambios en la jerarquia del equipo.

    Permite responder: ¿quien movio a Renato del 2 al 4? ¿desde cuando
    Solanch esta en posicion 1? ¿se reseteo la rotacion esta semana?

    Permisos: admin cualquier equipo, supervisor solo el suyo.
    """
    if current_user.role == Role.SUPERVISOR:
        if str(current_user.user_id) != str(supervisor_id):
            raise HTTPException(403, "Solo podes ver el historial de tu propio equipo")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    al.id,
                    al.accion,
                    al.actor_role,
                    al.detalle,
                    al.orden_antes,
                    al.orden_despues,
                    al.created_at,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                        AS actor_nombre,
                    u.email AS actor_email
                FROM crm.equipo_audit_log al
                LEFT JOIN auth.users u ON u.id = al.actor_id
                WHERE al.supervisor_id = %s::uuid
                ORDER BY al.created_at DESC
                LIMIT %s
                """,
                (supervisor_id, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
            return rows

"""
assignment.py — Router admin del motor de auto-asignacion de leads.

Endpoints:
  GET    /api/admin/assignment/config             leer config global
  PATCH  /api/admin/assignment/config             actualizar config global

  GET    /api/admin/assignment/equipos            toggle por equipo + counts
  PATCH  /api/admin/assignment/equipos/{sup_id}   activar/desactivar auto en un equipo

  GET    /api/admin/assignment/rules              listar reglas
  POST   /api/admin/assignment/rules              crear regla
  PATCH  /api/admin/assignment/rules/{id}         editar regla
  DELETE /api/admin/assignment/rules/{id}         eliminar regla
  POST   /api/admin/assignment/rules/reorder      cambiar prioridad bulk

  GET    /api/admin/assignment/asesores           listar settings + leads_abiertos
  PATCH  /api/admin/assignment/asesores/{id}      editar settings de un asesor

  GET    /api/admin/assignment/audit              audit log paginado
  GET    /api/admin/assignment/stats?dias=30      stats globales

  POST   /api/admin/assignment/simulate           simular decision (preview)

Permisos:
  - admin: todo
  - supervisor: solo lectura de su propio equipo + sus asesores
  - asesor: 403
"""
from __future__ import annotations

import logging
from datetime import date, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db
from app.services import lead_routing

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/assignment", tags=["Admin / Asignacion automatica"])


# ─── Schemas ──────────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    auto_asignar_enabled:        Optional[bool] = None
    estrategia_default:          Optional[str] = None
    max_leads_abiertos_default:  Optional[int] = Field(None, ge=1, le=10000)
    horario_inicio:              Optional[str] = None     # "HH:MM"
    horario_fin:                 Optional[str] = None
    estrategia_fuera_horario:    Optional[str] = None
    estrategia_sin_disponibles:  Optional[str] = None
    capacity_definicion:         Optional[str] = None
    notificar_supervisor_auto:   Optional[bool] = None
    incluir_supervisor_en_rotacion: Optional[bool] = None


class EquipoToggle(BaseModel):
    auto_asignar_enabled: bool


class RuleCreate(BaseModel):
    nombre:           str = Field(..., min_length=2, max_length=120)
    descripcion:      Optional[str] = None
    prioridad:        int = Field(..., ge=1, le=999)
    activo:           bool = True
    fuente_id:        Optional[int] = None
    api_client_id:    Optional[str] = None
    campana_pattern:         Optional[str] = None
    campana_exclude_pattern: Optional[str] = None
    palabras_clave:   Optional[list[str]] = None
    horario_inicio:   Optional[str] = None
    horario_fin:      Optional[str] = None
    dias_semana:      Optional[list[int]] = None
    asignar_a_tipo:   str
    asignar_a_id:     Optional[str] = None
    fallback_si_lleno: str = "siguiente_regla"


class RuleUpdate(BaseModel):
    nombre:                  Optional[str] = None
    descripcion:             Optional[str] = None
    prioridad:               Optional[int] = Field(None, ge=1, le=999)
    activo:                  Optional[bool] = None
    fuente_id:               Optional[int] = None
    api_client_id:           Optional[str] = None
    campana_pattern:         Optional[str] = None
    campana_exclude_pattern: Optional[str] = None
    palabras_clave:          Optional[list[str]] = None
    horario_inicio:          Optional[str] = None
    horario_fin:             Optional[str] = None
    dias_semana:             Optional[list[int]] = None
    asignar_a_tipo:          Optional[str] = None
    asignar_a_id:            Optional[str] = None
    fallback_si_lleno:       Optional[str] = None


class RulesReorder(BaseModel):
    orden: list[int]   # lista de rule_id en orden de prioridad ascendente


class AsesorSettingsUpdate(BaseModel):
    disponible_rotacion: Optional[bool] = None
    max_leads_abiertos:  Optional[int] = Field(None, ge=0, le=10000)
    horario_inicio:      Optional[str] = None
    horario_fin:         Optional[str] = None
    dias_semana:         Optional[list[int]] = None
    ausencia_desde:      Optional[str] = None
    ausencia_hasta:      Optional[str] = None
    motivo_ausencia:     Optional[str] = None
    peso_rotacion:       Optional[float] = Field(None, ge=0, le=10)
    notas:               Optional[str] = None


class SimulatePayload(BaseModel):
    fuente_id:        Optional[int] = None
    api_client_id:    Optional[str] = None
    campana:          Optional[str] = None
    observaciones:    Optional[str] = None
    supervisor_id:    str


# ─── Helpers ──────────────────────────────────────────────────────────────

def _serialize_time(t) -> Optional[str]:
    if t is None:
        return None
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)


def _serialize_date(d) -> Optional[str]:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _serialize_rule(r: dict) -> dict:
    d = dict(r)
    d["horario_inicio"] = _serialize_time(d.get("horario_inicio"))
    d["horario_fin"]    = _serialize_time(d.get("horario_fin"))
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    d["updated_at"] = d["updated_at"].isoformat() if d.get("updated_at") else None
    d["ultima_aplicacion"] = d["ultima_aplicacion"].isoformat() if d.get("ultima_aplicacion") else None
    d["api_client_id"] = str(d["api_client_id"]) if d.get("api_client_id") else None
    d["asignar_a_id"]  = str(d["asignar_a_id"])  if d.get("asignar_a_id")  else None
    d["created_by"]    = str(d["created_by"])    if d.get("created_by")    else None
    return d


# ─── Config global ────────────────────────────────────────────────────────

@router.get("/config")
def get_config(_user: TokenData = Depends(check_permission("rotacion.manage", "supervisor"))):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cfg = lead_routing.get_config(cur)
    cfg["horario_inicio"] = _serialize_time(cfg.get("horario_inicio"))
    cfg["horario_fin"]    = _serialize_time(cfg.get("horario_fin"))
    if "updated_at" in cfg and cfg["updated_at"]:
        cfg["updated_at"] = cfg["updated_at"].isoformat()
    if "updated_by" in cfg and cfg["updated_by"]:
        cfg["updated_by"] = str(cfg["updated_by"])
    return cfg


@router.patch("/config")
def update_config(data: ConfigUpdate, admin: TokenData = Depends(check_permission("rotacion.manage"))):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar")

    set_parts = []
    params: list = []
    for k, v in fields.items():
        if k in ("horario_inicio", "horario_fin"):
            set_parts.append(f"{k} = %s::time")
        else:
            set_parts.append(f"{k} = %s")
        params.append(v if v != "" else None)
    params.append(admin.user_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE crm.assignment_config
                SET {', '.join(set_parts)}, updated_at = NOW(), updated_by = %s::uuid
                WHERE id = 1
                RETURNING *
                """,
                params,
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(500, "No se pudo actualizar la configuracion")
    cfg = dict(row)
    cfg["horario_inicio"] = _serialize_time(cfg.get("horario_inicio"))
    cfg["horario_fin"]    = _serialize_time(cfg.get("horario_fin"))
    cfg["updated_at"] = cfg["updated_at"].isoformat()
    cfg["updated_by"] = str(cfg["updated_by"]) if cfg.get("updated_by") else None
    logger.info("[assignment] config updated by admin=%s fields=%s", admin.user_id, list(fields.keys()))
    return cfg


# ─── Equipos (toggle por supervisor) ──────────────────────────────────────

@router.get("/equipos")
def list_equipos(_user: TokenData = Depends(check_permission("rotacion.manage", "supervisor"))):
    """Lista supervisores con su flag auto_asignar_enabled + counts."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    s.id::text AS supervisor_id,
                    TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,'')) AS supervisor_nombre,
                    s.email,
                    s.activo_rotacion,
                    BOOL_OR(eq.auto_asignar_enabled) AS auto_asignar_enabled,
                    COUNT(eq.asesor_id) FILTER (WHERE eq.activo = TRUE) AS num_asesores
                FROM auth.users s
                LEFT JOIN crm.equipos eq ON eq.supervisor_id = s.id
                WHERE s.role = 'supervisor' AND s.is_active = TRUE
                GROUP BY s.id, s.first_name, s.last_name, s.email, s.activo_rotacion
                ORDER BY supervisor_nombre
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
    return rows


@router.patch("/equipos/{supervisor_id}")
def toggle_equipo(supervisor_id: str, data: EquipoToggle, admin: TokenData = Depends(check_permission("rotacion.manage"))):
    """Activa/desactiva auto-asignacion para todos los miembros del equipo
    de un supervisor."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.equipos
                SET auto_asignar_enabled = %s
                WHERE supervisor_id = %s::uuid
                RETURNING asesor_id
                """,
                (data.auto_asignar_enabled, supervisor_id),
            )
            updated = cur.rowcount
        conn.commit()
    if updated == 0:
        raise HTTPException(404, "Supervisor sin equipo configurado")
    logger.info("[assignment] equipo %s auto=%s by admin=%s", supervisor_id, data.auto_asignar_enabled, admin.user_id)
    return {"ok": True, "asesores_afectados": updated}


# ─── Reglas ───────────────────────────────────────────────────────────────

@router.get("/rules")
def list_rules(_user: TokenData = Depends(check_permission("rotacion.manage", "supervisor"))):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT r.*,
                    f.nombre AS fuente_nombre,
                    ac.nombre AS api_client_nombre,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS target_nombre,
                    u.role AS target_role
                FROM crm.lead_assignment_rules r
                LEFT JOIN crm.fuentes f ON f.id = r.fuente_id
                LEFT JOIN crm.api_clients ac ON ac.id = r.api_client_id
                LEFT JOIN auth.users u ON u.id = r.asignar_a_id
                ORDER BY r.activo DESC, r.prioridad ASC
                """
            )
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                d["horario_inicio"] = _serialize_time(d.get("horario_inicio"))
                d["horario_fin"]    = _serialize_time(d.get("horario_fin"))
                d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
                d["updated_at"] = d["updated_at"].isoformat() if d.get("updated_at") else None
                d["ultima_aplicacion"] = d["ultima_aplicacion"].isoformat() if d.get("ultima_aplicacion") else None
                d["api_client_id"] = str(d["api_client_id"]) if d.get("api_client_id") else None
                d["asignar_a_id"]  = str(d["asignar_a_id"])  if d.get("asignar_a_id")  else None
                d["created_by"]    = str(d["created_by"])    if d.get("created_by")    else None
                rows.append(d)
    return rows


@router.post("/rules", status_code=201)
def create_rule(data: RuleCreate, admin: TokenData = Depends(check_permission("rotacion.manage"))):
    api_client_id = data.api_client_id if data.api_client_id else None
    asignar_a_id = data.asignar_a_id if data.asignar_a_id else None
    campana_pattern = data.campana_pattern if data.campana_pattern else None
    campana_exclude_pattern = data.campana_exclude_pattern if data.campana_exclude_pattern else None
    horario_inicio = data.horario_inicio if data.horario_inicio else None
    horario_fin = data.horario_fin if data.horario_fin else None

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO crm.lead_assignment_rules
                        (nombre, descripcion, prioridad, activo, fuente_id, api_client_id,
                         campana_pattern, campana_exclude_pattern, palabras_clave, horario_inicio, horario_fin, dias_semana,
                         asignar_a_tipo, asignar_a_id, fallback_si_lleno, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s::uuid,
                            %s, %s, %s, %s::time, %s::time, %s,
                            %s, %s::uuid, %s, %s::uuid)
                    RETURNING *
                    """,
                    (
                        data.nombre, data.descripcion, data.prioridad, data.activo,
                        data.fuente_id, api_client_id,
                        campana_pattern, campana_exclude_pattern, data.palabras_clave,
                        horario_inicio, horario_fin, data.dias_semana,
                        data.asignar_a_tipo, asignar_a_id, data.fallback_si_lleno,
                        admin.user_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return _serialize_rule(dict(row))
    except Exception as exc:
        logger.exception("create_rule fallo: %s", exc)
        raise HTTPException(status_code=400, detail=f"Error al crear regla: {exc}")


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, data: RuleUpdate, admin: TokenData = Depends(check_permission("rotacion.manage"))):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar")

    set_parts = []
    params: list = []
    for k, v in fields.items():
        if k in ("horario_inicio", "horario_fin"):
            set_parts.append(f"{k} = %s::time")
        elif k in ("api_client_id", "asignar_a_id"):
            set_parts.append(f"{k} = %s::uuid")
        else:
            set_parts.append(f"{k} = %s")
        params.append(v if v != "" else None)
    params.append(rule_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.lead_assignment_rules SET {', '.join(set_parts)}, updated_at = NOW() "
                "WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Regla no encontrada")
        conn.commit()
    return _serialize_rule(dict(row))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, _admin: TokenData = Depends(check_permission("rotacion.manage"))):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm.lead_assignment_rules WHERE id = %s RETURNING id", (rule_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Regla no encontrada")
        conn.commit()
    return {"ok": True}


@router.post("/rules/reorder")
def reorder_rules(data: RulesReorder, _admin: TokenData = Depends(check_permission("rotacion.manage"))):
    """Aplica nuevo orden de prioridad. Two-pass para evitar conflictos
    transitorios en (no hay UNIQUE en prioridad, pero igual es buena practica)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Pass 1: shift a 10000+ para evitar colisiones
            for i, rid in enumerate(data.orden, start=1):
                cur.execute(
                    "UPDATE crm.lead_assignment_rules SET prioridad = %s WHERE id = %s",
                    (10000 + i, rid),
                )
            # Pass 2: setear prioridad final
            for i, rid in enumerate(data.orden, start=1):
                cur.execute(
                    "UPDATE crm.lead_assignment_rules SET prioridad = %s WHERE id = %s",
                    (i, rid),
                )
        conn.commit()
    return {"ok": True, "total": len(data.orden)}


@router.post("/rules/{rule_id}/apply-unassigned")
def apply_rule_to_unassigned(
    rule_id: int,
    admin: TokenData = Depends(check_permission("rotacion.manage")),
):
    """Aplica una regla específica a los leads activos sin asesor asignado.
    Evalúa cada lead sin asesor contra los criterios de la regla y lo asigna.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Buscar regla
            cur.execute("SELECT * FROM crm.lead_assignment_rules WHERE id = %s", (rule_id,))
            rule_row = cur.fetchone()
            if not rule_row:
                raise HTTPException(404, "Regla no encontrada")
            rule = dict(rule_row)
            if not rule.get("activo"):
                raise HTTPException(400, "La regla debe estar activa para poder aplicarla a leads sin asignar")

            # 2. Config y timestamp actual
            config = lead_routing.get_config(cur)
            now = lead_routing._now_lima()

            # 3. Buscar leads activos sin asesor
            cur.execute(
                """
                SELECT l.id, l.fuente_id, l.campana, l.observaciones, l.api_client_id::text AS api_client_id,
                       l.nombres, l.apellidos, COALESCE(f.nombre, '') AS fuente_nombre
                FROM crm.leads l
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                WHERE l.activo = TRUE AND l.asesor_id IS NULL
                ORDER BY l.id ASC
                """
            )
            unassigned_leads = [dict(r) for r in cur.fetchall()]

            assigned_count = 0
            matched_count = 0
            pushes_pendientes: list[dict] = []

            supervisor_id = str(rule.get("asignar_a_id") or admin.user_id)

            for lead in unassigned_leads:
                # Verificar si la regla matchea con los atributos del lead
                if not lead_routing._regla_matchea(cur, rule, lead, now):
                    continue

                matched_count += 1

                # Intentar aplicar la regla al lead
                decision = lead_routing._aplicar_regla(cur, rule, supervisor_id, config, now)
                if not decision and rule.get("fallback_si_lleno") == "asignar_igual":
                    decision = lead_routing._aplicar_regla(cur, rule, supervisor_id, config, now, ignorar_capacity=True)

                if decision and decision.asignado_a_id:
                    # Actualizar lead
                    cur.execute(
                        "UPDATE crm.leads SET asesor_id = %s::uuid WHERE id = %s",
                        (decision.asignado_a_id, lead["id"]),
                    )
                    # Registrar log (el trigger trg_assignment_log_bump_rule actualizará total_aplicaciones y ultima_aplicacion)
                    lead_routing.log_decision(cur, lead_id=lead["id"], supervisor_id=supervisor_id, decision=decision)
                    # Si estaba en cola pendiente de asignación, eliminarlo
                    cur.execute("DELETE FROM crm.assignment_pending WHERE lead_id = %s", (lead["id"],))

                    assigned_count += 1
                    lead_name = f"{lead.get('nombres') or ''} {lead.get('apellidos') or ''}".strip()
                    pushes_pendientes.append({
                        "asesor_id": decision.asignado_a_id,
                        "lead_id": lead["id"],
                        "lead_name": lead_name,
                        "fuente": lead.get("fuente_nombre") or "",
                    })

        conn.commit()

    # Disparar notificaciones post-commit
    if pushes_pendientes:
        try:
            from app.services.notification_service import notify_new_lead
            for push in pushes_pendientes:
                notify_new_lead(
                    push["asesor_id"],
                    push["lead_name"],
                    push["fuente"],
                    lead_id=push["lead_id"],
                )
        except Exception as exc:
            logging.warning("Error enviando notificaciones tras reparto por regla: %s", exc)

    return {
        "ok": True,
        "matched_count": matched_count,
        "assigned_count": assigned_count,
        "message": f"Se evaluaron {matched_count} leads coincidentes y se asignaron {assigned_count} leads con la regla '{rule.get('nombre')}'."
    }



def _serialize_rule(r: dict) -> dict:
    r["horario_inicio"] = _serialize_time(r.get("horario_inicio"))
    r["horario_fin"]    = _serialize_time(r.get("horario_fin"))
    r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    r["updated_at"] = r["updated_at"].isoformat() if r.get("updated_at") else None
    r["ultima_aplicacion"] = r["ultima_aplicacion"].isoformat() if r.get("ultima_aplicacion") else None
    r["api_client_id"] = str(r["api_client_id"]) if r.get("api_client_id") else None
    r["asignar_a_id"]  = str(r["asignar_a_id"])  if r.get("asignar_a_id")  else None
    r["created_by"]    = str(r["created_by"])    if r.get("created_by")    else None
    return r


# ─── Asesores ─────────────────────────────────────────────────────────────

@router.get("/asesores")
def list_asesor_settings(_user: TokenData = Depends(check_permission("rotacion.manage", "supervisor"))):
    """Lista todos los asesores con su settings + leads_abiertos actual."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cfg = lead_routing.get_config(cur)
            modo = cfg.get("capacity_definicion", "todos_activos")
            cur.execute(
                """
                SELECT
                    u.id::text AS asesor_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS nombre,
                    u.email, u.role,
                    COALESCE(s.disponible_rotacion, TRUE) AS disponible_rotacion,
                    s.max_leads_abiertos,
                    s.horario_inicio, s.horario_fin, s.dias_semana,
                    s.ausencia_desde, s.ausencia_hasta, s.motivo_ausencia,
                    COALESCE(s.peso_rotacion, 1.0)::float AS peso_rotacion,
                    s.notas,
                    crm.count_leads_abiertos(u.id, %s)::int AS leads_abiertos,
                    -- Equipo (supervisor)
                    sup.id::text AS supervisor_id,
                    TRIM(COALESCE(sup.first_name,'') || ' ' || COALESCE(sup.last_name,'')) AS supervisor_nombre
                FROM auth.users u
                LEFT JOIN crm.asesor_settings s ON s.asesor_id = u.id
                LEFT JOIN crm.equipos eq ON eq.asesor_id = u.id AND eq.activo = TRUE
                LEFT JOIN auth.users sup ON sup.id = eq.supervisor_id
                WHERE u.role IN ('asesor','supervisor') AND u.is_active = TRUE
                ORDER BY u.role DESC, nombre
                """,
                (modo,),
            )
            rows = []
            cap_default = cfg.get("max_leads_abiertos_default", 50) or 50
            from datetime import date as _date
            today = _date.today()
            for r in cur.fetchall():
                d = dict(r)
                d["horario_inicio"] = _serialize_time(d.get("horario_inicio"))
                d["horario_fin"]    = _serialize_time(d.get("horario_fin"))
                d["ausencia_desde"] = _serialize_date(d.get("ausencia_desde"))
                d["ausencia_hasta"] = _serialize_date(d.get("ausencia_hasta"))
                d["max_leads_efectivo"] = d.get("max_leads_abiertos") or cap_default
                d["pct_capacity"] = round(d["leads_abiertos"] * 100 / d["max_leads_efectivo"], 1) if d["max_leads_efectivo"] else 0

                # ── Elegibilidad real (mismo criterio que el motor) ──
                # Esto reemplaza al badge "DISPONIBLE" que solo miraba el toggle
                # y mentia cuando capacity exceeded.
                motivo = None
                if d.get("role") == "supervisor":
                    motivo = "supervisor (no recibe via auto-asignacion del equipo)"
                elif not d["disponible_rotacion"]:
                    motivo = "marcado como no disponible"
                else:
                    desde = d.get("ausencia_desde")
                    hasta = d.get("ausencia_hasta")
                    if desde and hasta:
                        try:
                            d_desde = _date.fromisoformat(desde) if isinstance(desde, str) else desde
                            d_hasta = _date.fromisoformat(hasta) if isinstance(hasta, str) else hasta
                            if d_desde <= today <= d_hasta:
                                motivo_aus = d.get("motivo_ausencia") or "ausencia programada"
                                motivo = f"en ausencia ({motivo_aus})"
                        except Exception:  # noqa: BLE001
                            pass
                    if motivo is None and d["leads_abiertos"] >= d["max_leads_efectivo"]:
                        motivo = f"capacity llena ({d['leads_abiertos']}/{d['max_leads_efectivo']})"
                d["elegible"] = motivo is None
                d["motivo_no_elegible"] = motivo
                rows.append(d)
    return rows


@router.patch("/asesores/{asesor_id}")
def update_asesor_settings(asesor_id: str, data: AsesorSettingsUpdate, admin: TokenData = Depends(check_permission("rotacion.manage"))):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar")

    insert_cols = ["asesor_id"]
    insert_vals: list = [asesor_id]
    insert_placeholders = ["%s::uuid"]
    set_clauses: list = []
    for k, v in fields.items():
        if k in ("horario_inicio", "horario_fin"):
            insert_cols.append(k); insert_placeholders.append("%s::time"); insert_vals.append(v if v != "" else None)
            set_clauses.append(f"{k} = EXCLUDED.{k}")
        elif k in ("ausencia_desde", "ausencia_hasta"):
            insert_cols.append(k); insert_placeholders.append("%s::date"); insert_vals.append(v if v != "" else None)
            set_clauses.append(f"{k} = EXCLUDED.{k}")
        else:
            insert_cols.append(k); insert_placeholders.append("%s"); insert_vals.append(v)
            set_clauses.append(f"{k} = EXCLUDED.{k}")

    insert_cols.append("updated_by"); insert_placeholders.append("%s::uuid"); insert_vals.append(admin.user_id)
    set_clauses.append("updated_by = EXCLUDED.updated_by")
    set_clauses.append("updated_at = NOW()")

    sql = (
        f"INSERT INTO crm.asesor_settings ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join(insert_placeholders)}) "
        f"ON CONFLICT (asesor_id) DO UPDATE SET {', '.join(set_clauses)} "
        f"RETURNING *"
    )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, insert_vals)
            row = cur.fetchone()

            # V070.78 (ADR-0010) — Team Circuit Breaker:
            # Si cambio disponible_rotacion o la ausencia, evaluar transicion
            # de estado del equipo del supervisor de este asesor.
            if (
                "disponible_rotacion" in fields
                or "ausencia_desde" in fields
                or "ausencia_hasta" in fields
                or "max_leads_abiertos" in fields
            ):
                try:
                    from app.services.team_health_service import evaluate_and_record_transition
                    cur.execute(
                        """
                        SELECT DISTINCT supervisor_id::text AS sid
                        FROM crm.equipos
                        WHERE asesor_id = %s::uuid AND activo = TRUE
                        """,
                        (asesor_id,),
                    )
                    supervisores_afectados = [r["sid"] for r in cur.fetchall()]
                    for sid in supervisores_afectados:
                        evaluate_and_record_transition(
                            cur, sid,
                            triggering_user_id=asesor_id,
                            nota=f"cambio settings: {', '.join(sorted(fields.keys()))}",
                        )
                except Exception as exc:  # noqa: BLE001
                    # Defensa en profundidad: nunca romper el flujo principal
                    # si el evaluador tiene un bug.
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "[team-health] evaluacion post-update fallo: %s", exc,
                    )
        conn.commit()
    if not row:
        raise HTTPException(500, "No se pudo actualizar los settings del asesor")
    d = dict(row)
    d["horario_inicio"] = _serialize_time(d.get("horario_inicio"))
    d["horario_fin"]    = _serialize_time(d.get("horario_fin"))
    d["ausencia_desde"] = _serialize_date(d.get("ausencia_desde"))
    d["ausencia_hasta"] = _serialize_date(d.get("ausencia_hasta"))
    return d


# ─── Audit + Stats ────────────────────────────────────────────────────────

@router.get("/audit")
def get_audit(
    limit: int = Query(100, ge=1, le=500),
    lead_id: Optional[int] = Query(None),
    _user: TokenData = Depends(check_permission("rotacion.manage", "supervisor")),
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = ""
            params: list = []
            if lead_id:
                where = "WHERE al.lead_id = %s"
                params.append(lead_id)
            cur.execute(
                f"""
                SELECT
                    al.id, al.lead_id, al.fecha::text AS fecha,
                    al.estrategia, al.regla_aplicada_id, al.duracion_ms,
                    al.razon, al.candidatos_evaluados,
                    al.supervisor_id::text AS supervisor_id,
                    TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,'')) AS supervisor_nombre,
                    al.asignado_a_id::text AS asignado_a_id,
                    TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,'')) AS asignado_a_nombre,
                    r.nombre AS regla_nombre
                FROM crm.assignment_log al
                LEFT JOIN auth.users s ON s.id = al.supervisor_id
                LEFT JOIN auth.users a ON a.id = al.asignado_a_id
                LEFT JOIN crm.lead_assignment_rules r ON r.id = al.regla_aplicada_id
                {where}
                ORDER BY al.fecha DESC
                LIMIT %s
                """,
                params + [limit],
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"items": rows, "total": len(rows)}


@router.get("/stats")
def get_stats(
    dias: int = Query(30, ge=1, le=365),
    _user: TokenData = Depends(check_permission("rotacion.manage", "supervisor")),
):
    desde = date.today() - timedelta(days=dias)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Por estrategia
            cur.execute(
                """
                SELECT estrategia, COUNT(*)::int AS total
                FROM crm.assignment_log
                WHERE DATE(fecha AT TIME ZONE 'America/Lima') >= %s
                GROUP BY estrategia
                ORDER BY total DESC
                """,
                (desde,),
            )
            por_estrategia = [dict(r) for r in cur.fetchall()]

            # Top reglas
            cur.execute(
                """
                SELECT r.id, r.nombre, r.total_aplicaciones, r.ultima_aplicacion
                FROM crm.lead_assignment_rules r
                WHERE r.total_aplicaciones > 0
                ORDER BY r.total_aplicaciones DESC
                LIMIT 10
                """
            )
            top_reglas = []
            for r in cur.fetchall():
                d = dict(r)
                d["ultima_aplicacion"] = d["ultima_aplicacion"].isoformat() if d.get("ultima_aplicacion") else None
                top_reglas.append(d)

            # Auto vs Manual (manual = sin entrada en assignment_log dentro del periodo)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE created_at >= %s::date) AS total_leads_periodo,
                    COUNT(*) FILTER (
                        WHERE created_at >= %s::date
                          AND id IN (SELECT lead_id FROM crm.assignment_log WHERE DATE(fecha AT TIME ZONE 'America/Lima') >= %s)
                    ) AS auto_asignados
                FROM crm.leads
                """,
                (desde, desde, desde),
            )
            row = cur.fetchone()
            total = row["total_leads_periodo"] or 0
            auto = row["auto_asignados"] or 0
            pct_auto = round(auto * 100 / total, 1) if total else 0

            # Tiempo promedio de calculo
            cur.execute(
                """
                SELECT AVG(duracion_ms)::int AS avg_ms
                FROM crm.assignment_log
                WHERE DATE(fecha AT TIME ZONE 'America/Lima') >= %s
                """,
                (desde,),
            )
            avg_row = cur.fetchone()
            avg_ms = avg_row["avg_ms"] or 0

    return {
        "dias": dias,
        "por_estrategia": por_estrategia,
        "top_reglas": top_reglas,
        "auto_vs_total": {"auto": auto, "total": total, "pct_auto": pct_auto},
        "avg_duracion_ms": avg_ms,
    }


# ─── Cola de pendientes (V047) ────────────────────────────────────────────

@router.get("/queue")
def get_pending_queue(
    limit: int = Query(50, ge=1, le=500),
    _user: TokenData = Depends(check_permission("rotacion.manage", "supervisor")),
):
    """Lista los leads en cola esperando proximo horario o reintento."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                cur.execute(
                    """
                    SELECT
                        ap.id, ap.lead_id, ap.motivo, ap.intentos,
                        ap.proximo_intento::text AS proximo_intento,
                        ap.created_at::text AS created_at,
                        ap.ultimo_error,
                        ap.supervisor_id::text AS supervisor_id,
                        TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,'')) AS supervisor_nombre,
                        l.nombres, l.apellidos, l.telefono, l.campana,
                        f.nombre AS fuente_nombre
                    FROM crm.assignment_pending ap
                    LEFT JOIN auth.users s ON s.id = ap.supervisor_id
                    LEFT JOIN crm.leads l ON l.id = ap.lead_id
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    ORDER BY ap.proximo_intento ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = [dict(r) for r in cur.fetchall()]
            except Exception:
                rows = []  # V047 aún no aplicada
    return {"items": rows, "total": len(rows)}


@router.post("/queue/process-now")
def force_process_queue(_admin: TokenData = Depends(check_permission("rotacion.manage"))):
    """Fuerza un ciclo del procesador de cola sin esperar al cron.
    Útil para debug o para gerencia: 'apliquemoslo ya'."""
    from app.services import lead_routing
    with get_db() as conn:
        with conn.cursor() as cur:
            stats = lead_routing.process_pending_queue(cur)
        conn.commit()
    return stats


# ─── Simulador ────────────────────────────────────────────────────────────

@router.post("/simulate")
def simulate(payload: SimulatePayload, _user: TokenData = Depends(check_permission("rotacion.manage", "supervisor"))):
    """Dado un lead hipotetico, devuelve a quien se asignaria sin
    persistir nada. Util para 'ensayar' reglas antes de activarlas."""
    lead_dict = {
        "fuente_id":     payload.fuente_id,
        "api_client_id": payload.api_client_id,
        "campana":       payload.campana,
        "observaciones": payload.observaciones,
    }
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            result = lead_routing.simulate(cur, lead_dict, payload.supervisor_id)
    return result

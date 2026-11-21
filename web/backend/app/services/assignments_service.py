"""
Servicio de asignación / reasignación de leads.

Responsabilidad única:
  - Decidir QUIÉN puede reasignar QUÉ a QUIÉN (autorización).
  - Inferir el `motivo` del log a partir del rol y la transición.
  - Orquestar repositorio + notificaciones.

NO toca SQL directo (eso lo hace `leads_repository`) ni HTTP (eso lo hace
el router). De esa forma respetamos SRP y DIP: el router depende de esta
abstracción, no de psycopg2.
"""
from typing import Optional
import logging

from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from app.auth.schemas import TokenData
from app.auth.permissions import get_assignment_scope
from app.constants import Role, KEEP_SUPERVISOR, MAX_BULK_REASSIGN
from app.database import get_db
from app.repositories import leads_repository
from app.services.notification_service import (
    notify_lead_reassigned,
    notify_new_lead,
    notify_supervisor_new_lead,
)

logger = logging.getLogger(__name__)


# Catálogo cerrado de motivos. Se persiste en `crm.asignaciones_log.motivo`.
MOTIVO_INICIAL = "inicial"
MOTIVO_LIBERACION = "liberacion"
MOTIVO_MANUAL_ADMIN = "manual_admin"
MOTIVO_MANUAL_SUPERVISOR = "manual_supervisor"
MOTIVO_ROUND_ROBIN = "round_robin"
# Supervisor deriva el lead a otro supervisor (cross-equipo).
MOTIVO_DERIVACION_SUPERVISOR = "derivacion_supervisor"
# Supervisor devuelve el lead al asesor que lo trabajo originalmente
# (detectado via card de Antecedentes).
MOTIVO_DERIVACION_ANTECEDENTE = "derivacion_antecedente"


# ---------------------------------------------------------------------------
# Reglas puras (testeables sin DB)
# ---------------------------------------------------------------------------

def infer_motivo(
    role: str,
    previous_asesor_id: Optional[str],
    new_asesor_id: Optional[str],
    *,
    is_cross_supervisor: bool = False,
) -> str:
    """Devuelve el motivo canónico según rol y transición.

    - sin previo + nuevo                         → 'inicial'
    - previo + sin nuevo                         → 'liberacion'
    - supervisor → otro supervisor (cross-team)  → 'derivacion_supervisor'
    - resto                                      → manual_(admin|supervisor)
    """
    if previous_asesor_id is None and new_asesor_id is not None:
        return MOTIVO_INICIAL
    if new_asesor_id is None:
        return MOTIVO_LIBERACION
    if role == Role.SUPERVISOR and is_cross_supervisor:
        return MOTIVO_DERIVACION_SUPERVISOR
    return MOTIVO_MANUAL_ADMIN if role == Role.ADMIN else MOTIVO_MANUAL_SUPERVISOR


# ---------------------------------------------------------------------------
# Autorización (consulta SQL puntual)
# ---------------------------------------------------------------------------

def _supervisor_owns_asesor(supervisor_id: str, asesor_id: Optional[str]) -> bool:
    """¿El asesor pertenece al equipo activo del supervisor (o es él mismo o de su equipo subordinado)?

    `None` se considera válido — un supervisor puede liberar leads o tomar
    leads sin asignar de su cola.
    """
    if asesor_id is None or str(asesor_id) == str(supervisor_id):
        return True
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Es un supervisor subordinado
            cur.execute(
                "SELECT 1 FROM auth.users WHERE id = %s::uuid AND supervisor_jefe_id = %s::uuid AND is_active = TRUE",
                (asesor_id, supervisor_id),
            )
            if cur.fetchone() is not None:
                return True

            cur.execute(
                """
                SELECT 1
                FROM crm.equipos
                WHERE (
                    supervisor_id = %s::uuid
                    OR supervisor_id IN (
                        SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
                    )
                )
                  AND asesor_id = %s::uuid
                  AND activo    = TRUE
                """,
                (supervisor_id, supervisor_id, asesor_id),
            )
            return cur.fetchone() is not None


def _is_active_supervisor(user_id: str) -> bool:
    """¿El usuario es un supervisor activo? Permite cross-derivation."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 1
                FROM auth.users
                WHERE id = %s::uuid
                  AND role = 'supervisor'
                  AND is_active = TRUE
                """,
                (user_id,),
            )
            return cur.fetchone() is not None


# Sentinel para distinguir "no tocar supervisor_id" de "ponerlo en NULL".
_KEEP_SUPERVISOR = KEEP_SUPERVISOR


def _resolve_target_supervisor_id(new_asesor_id: Optional[str]):
    """Calcula a qué supervisor_id debe quedar el lead tras una reasignación."""
    if new_asesor_id is None:
        return None  # Liberar a sin asignar: quita asesor_id y supervisor_id (sale del supervisor y supervisor jefe)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT role FROM auth.users WHERE id = %s::uuid",
                (new_asesor_id,),
            )
            row = cur.fetchone()
            if row and row["role"] == "supervisor":
                return new_asesor_id
            cur.execute(
                "SELECT supervisor_id::text AS supervisor_id "
                "FROM crm.equipos WHERE asesor_id = %s::uuid AND activo = TRUE LIMIT 1",
                (new_asesor_id,),
            )
            row = cur.fetchone()
            if row and row["supervisor_id"]:
                return row["supervisor_id"]
    return KEEP_SUPERVISOR


def can_assign_leads(user: TokenData) -> bool:
    """Verifica si el usuario tiene permiso para asignar leads."""
    if user.role in (Role.ADMIN, Role.ADMIN.value, "admin"):
        return True
    perms = user.permissions or {}
    if perms.get("_all") is True:
        return True
    if perms.get("asignacion.manage") is True:
        return True
    if user.role in (Role.SUPERVISOR, Role.SUPERVISOR.value, "supervisor"):
        return True
    return False


def _is_active_assignable_user(user_id: str) -> bool:
    """Verifica si el usuario existe y está activo."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM auth.users WHERE id = %s::uuid AND is_active = TRUE",
                (user_id,),
            )
            return cur.fetchone() is not None


def _is_in_user_team(current_user_id: str, current_role: str, target_id: Optional[str]) -> bool:
    """Valida si target_id pertenece al equipo activo de current_user_id.

    - target_id is None: liberar / desasignar es siempre válido.
    - target_id == current_user_id: asignarse a sí mismo es siempre válido.
    - Si el usuario es supervisor: verifica con _supervisor_owns_asesor.
    - Si el usuario es asesor (o rol no supervisor):
        * target_id es el supervisor de su equipo (o supervisor jefe) -> Válido ("sea supervisor o no").
        * target_id es un compañero asesor del mismo equipo -> Válido.
    """
    if target_id is None or str(target_id) == str(current_user_id):
        return True

    if current_role in (Role.SUPERVISOR, Role.SUPERVISOR.value, "supervisor"):
        return _supervisor_owns_asesor(current_user_id, target_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. ¿El destino es el supervisor del equipo del asesor o su supervisor jefe?
            cur.execute(
                """
                SELECT 1
                FROM crm.equipos eq
                JOIN auth.users s ON s.id = eq.supervisor_id
                WHERE eq.asesor_id = %s::uuid
                  AND eq.activo = TRUE
                  AND s.is_active = TRUE
                  AND (
                      eq.supervisor_id = %s::uuid
                      OR s.supervisor_jefe_id = %s::uuid
                  )
                LIMIT 1
                """,
                (current_user_id, target_id, target_id),
            )
            if cur.fetchone() is not None:
                return True

            # 2. ¿El destino es un compañero asesor del mismo equipo?
            cur.execute(
                """
                SELECT 1
                FROM crm.equipos eq1
                JOIN crm.equipos eq2 ON eq1.supervisor_id = eq2.supervisor_id
                JOIN auth.users a ON a.id = eq2.asesor_id
                WHERE eq1.asesor_id = %s::uuid
                  AND eq2.asesor_id = %s::uuid
                  AND eq1.activo = TRUE
                  AND eq2.activo = TRUE
                  AND a.is_active = TRUE
                LIMIT 1
                """,
                (current_user_id, target_id),
            )
            return cur.fetchone() is not None


def _authorize_target(current_user: TokenData, new_asesor_id: Optional[str]) -> None:
    """El destino es válido para el rol y configuración de permisos del usuario actual."""
    if not can_assign_leads(current_user):
        raise HTTPException(status_code=403, detail="No tienes permiso para reasignar leads.")

    if new_asesor_id is None:
        return

    scope, allowed_users = get_assignment_scope(current_user)

    if scope == "global":
        if not _is_active_assignable_user(new_asesor_id):
            raise HTTPException(status_code=400, detail="El usuario destino no existe o está inactivo.")
        return

    if scope == "personalizado":
        target_str = str(new_asesor_id)
        if target_str in allowed_users or target_str == str(current_user.user_id):
            if not _is_active_assignable_user(new_asesor_id):
                raise HTTPException(status_code=400, detail="El usuario destino no existe o está inactivo.")
            return
        raise HTTPException(
            status_code=403,
            detail="El destino no es válido: no está en la lista de usuarios autorizados para tu rol.",
        )

    # scope == "equipo" (default encapsulado a su equipo)
    if _is_in_user_team(current_user.user_id, current_user.role, new_asesor_id):
        return

    # Cross-derivation para supervisores legacy sin scope explícito configurado
    perms = current_user.permissions or {}
    if current_user.role in (Role.SUPERVISOR, Role.SUPERVISOR.value, "supervisor") and not perms.get("asignacion.scope"):
        if _is_active_supervisor(new_asesor_id):
            return

    raise HTTPException(
        status_code=403,
        detail="El destino no es valido: no pertenece a tu equipo ni es supervisor activo.",
    )


def _authorize_source(
    current_user: TokenData,
    current_asesor_id: Optional[str],
    lead_supervisor_id: Optional[str] = None,
) -> None:
    """El lead actual es manipulable por el usuario actual."""
    if not can_assign_leads(current_user):
        raise HTTPException(status_code=403, detail="No tienes permiso para reasignar leads.")

    scope, allowed_users = get_assignment_scope(current_user)
    if scope == "global":
        return

    # Si el lead está asignado al usuario actual, siempre lo puede reasignar
    if current_asesor_id and str(current_asesor_id) == str(current_user.user_id):
        return

    # Si el usuario actual es el supervisor asignado al lead
    if lead_supervisor_id and str(lead_supervisor_id) == str(current_user.user_id):
        return

    # Si el usuario actual es supervisor jefe del supervisor del lead
    if lead_supervisor_id:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT 1 FROM auth.users WHERE id = %s::uuid AND supervisor_jefe_id = %s::uuid AND is_active = TRUE",
                    (lead_supervisor_id, current_user.user_id),
                )
                if cur.fetchone() is not None:
                    return

    if scope == "personalizado":
        if current_asesor_id and (str(current_asesor_id) in allowed_users or _is_in_user_team(current_user.user_id, current_user.role, current_asesor_id)):
            return
        if lead_supervisor_id and (str(lead_supervisor_id) in allowed_users or _is_in_user_team(current_user.user_id, current_user.role, lead_supervisor_id)):
            return

    # scope == "equipo" (o fallback de personalizado):
    if current_asesor_id and _is_in_user_team(current_user.user_id, current_user.role, current_asesor_id):
        return
    if current_asesor_id is None and lead_supervisor_id and _is_in_user_team(current_user.user_id, current_user.role, lead_supervisor_id):
        return

    raise HTTPException(status_code=403, detail="Este lead no pertenece a tu equipo.")


# ---------------------------------------------------------------------------
# Casos de uso
# ---------------------------------------------------------------------------

def reassign_one(
    *,
    lead_id: int,
    new_asesor_id: Optional[str],
    current_user: TokenData,
) -> dict:
    """Reasigna un único lead. Lanza HTTPException si no autoriza.

    Retorna `{"changed": bool, "previous_asesor_id": str|None, "lead_name": str}`.
    """
    lead = leads_repository.fetch_lead_for_assignment(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    # Short-circuit no-op: si el lead ya está donde queremos, no hay
    # transición que autorizar ni que loguear. Esto permite que un asesor
    # guarde su propio lead enviando su propio `asesor_id` sin recibir 403.
    if lead["asesor_id"] == new_asesor_id:
        return {
            "changed": False,
            "previous_asesor_id": lead["asesor_id"],
            "lead_name": lead["lead_name"],
        }

    _authorize_source(current_user, lead["asesor_id"], lead.get("supervisor_id"))
    _authorize_target(current_user, new_asesor_id)

    cross = (
        current_user.role == Role.SUPERVISOR
        and new_asesor_id is not None
        and new_asesor_id != current_user.user_id
        and not _supervisor_owns_asesor(current_user.user_id, new_asesor_id)
        and _is_active_supervisor(new_asesor_id)
    )
    motivo = infer_motivo(
        current_user.role,
        lead["asesor_id"],
        new_asesor_id,
        is_cross_supervisor=cross,
    )

    new_supervisor_id = _resolve_target_supervisor_id(new_asesor_id)
    result = leads_repository.reassign_one(
        lead_id=lead_id,
        new_asesor_id=new_asesor_id,
        new_supervisor_id=new_supervisor_id,
        performed_by=current_user.user_id,
        motivo=motivo,
    )

    # Notificación push fuera de la transacción. Errores no deben revertir
    # la asignación: el lead ya está reasignado en la DB.
    # V070.51 — pasa performed_by para skip self-action (asesor que se
    # autoasigna desde cola no recibe push de si mismo).
    if result["changed"] and new_asesor_id:
        try:
            notify_fn = (
                notify_new_lead if motivo == MOTIVO_INICIAL else notify_lead_reassigned
            )
            # V070.91 — lead_id para deep-link al tap en mobile.
            notify_fn(
                new_asesor_id, result["lead_name"],
                performed_by=current_user.user_id,
                lead_id=lead_id,
            )

            # Notificar al supervisor si es asignación inicial y el asesor pertenece a su equipo
            if (
                motivo == MOTIVO_INICIAL
                and new_supervisor_id
                and str(new_supervisor_id) != str(new_asesor_id)
                and str(new_supervisor_id) != str(current_user.user_id)
            ):
                asesor_name = "un asesor"
                try:
                    with get_db() as conn:
                        with conn.cursor(cursor_factory=RealDictCursor) as cur:
                            cur.execute(
                                "SELECT TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre "
                                "FROM auth.users WHERE id = %s::uuid",
                                (new_asesor_id,),
                            )
                            u_row = cur.fetchone()
                            if u_row and u_row["nombre"]:
                                asesor_name = u_row["nombre"]
                except Exception:
                    pass
                notify_supervisor_new_lead(
                    str(new_supervisor_id),
                    result["lead_name"],
                    asesor_name,
                    lead_id=lead_id,
                    performed_by=current_user.user_id,
                )
        except Exception as exc:  # noqa: BLE001 — el push es best-effort
            logger.warning("push fallido tras reasignar lead %s: %s", lead_id, exc)

    # V058: webhook outbound al proveedor (api_client_id) con el evento
    # lead.assigned (primera vez) o lead.reassigned (cambio). Best-effort:
    # se encola en una conexion nueva, fuera de la transaccion principal.
    if result["changed"]:
        try:
            _enqueue_assignment_webhook(
                lead_id=lead_id,
                previous_asesor_id=result.get("previous_asesor_id"),
                new_asesor_id=new_asesor_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("webhook enqueue fallo tras reasignar lead %s", lead_id)

    return result


def _enqueue_assignment_webhook(
    *,
    lead_id: int,
    previous_asesor_id: Optional[str],
    new_asesor_id: Optional[str],
) -> None:
    """Encola el evento de webhook correcto: assigned (sin previo) o
    reassigned (con previo). Skip si el lead no tiene api_client_id."""
    from app.database import get_db
    from app.services import webhook_service
    from psycopg2.extras import RealDictCursor

    if not new_asesor_id:
        return  # desasignar a NULL no se notifica (no util para el proveedor)

    delivery_id = None
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT api_client_id::text AS api_client_id FROM crm.leads WHERE id = %s",
                (lead_id,),
            )
            row = cur.fetchone()
            if not row or not row.get("api_client_id"):
                return  # lead sin proveedor externo

            event = (
                webhook_service.EVENT_LEAD_REASSIGNED
                if previous_asesor_id
                else webhook_service.EVENT_LEAD_ASSIGNED
            )
            payload_evt = webhook_service.build_lead_payload(
                cur, lead_id=lead_id, event_type=event,
                previous_asesor_id=previous_asesor_id,
                client_id=row["api_client_id"],
            )
            if payload_evt:
                delivery_id = webhook_service.enqueue_event(
                    cur, client_id=row["api_client_id"],
                    lead_id=lead_id, event_type=event, payload=payload_evt,
                )
            conn.commit()

    # V060.2: dispatch INMEDIATO post-commit (latencia P50 ~150-300ms)
    if delivery_id:
        webhook_service.dispatch_async(delivery_id)


def reassign_bulk(
    *,
    lead_ids: list[int],
    new_asesor_id: Optional[str],
    current_user: TokenData,
) -> dict:
    """Reasigna masivamente. Una sola transacción + filtro de rol como
    salvaguarda final en el repo.

    Retorna `{"changed": int, "skipped": int}`.
    """
    if not lead_ids:
        raise HTTPException(status_code=400, detail="Sin IDs para reasignar")
    if len(lead_ids) > MAX_BULK_REASSIGN:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {MAX_BULK_REASSIGN} leads por operación.",
        )

    _authorize_target(current_user, new_asesor_id)

    # Filtro de rol = defensa en profundidad. Si el cliente envía un ID
    # ajeno, se descarta sin escribir nada.
    from app.filters.lead_filters import role_filter  # import local: evita ciclo
    role_clause, role_params = role_filter(current_user)

    # `role_filter` retorna SQL con alias `l.` (vista vw_leads_dashboard).
    # En el repo lo aplicamos sobre `crm.leads l` directamente, sigue siendo
    # válido porque las columnas referenciadas (`asesor_id`) viven ahí.

    motivo = (
        MOTIVO_MANUAL_ADMIN if current_user.role == Role.ADMIN else MOTIVO_MANUAL_SUPERVISOR
    )
    if new_asesor_id is None:
        motivo = MOTIVO_LIBERACION
    elif (
        current_user.role == Role.SUPERVISOR
        and new_asesor_id != current_user.user_id
        and not _supervisor_owns_asesor(current_user.user_id, new_asesor_id)
        and _is_active_supervisor(new_asesor_id)
    ):
        motivo = MOTIVO_DERIVACION_SUPERVISOR

    new_supervisor_id = _resolve_target_supervisor_id(new_asesor_id)
    try:
        result = leads_repository.reassign_bulk(
            lead_ids=lead_ids,
            new_asesor_id=new_asesor_id,
            new_supervisor_id=new_supervisor_id,
            performed_by=current_user.user_id,
            motivo=motivo,
            role_clause=role_clause,
            role_params=role_params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Notificación agregada: 1 push con el total, no N pushes.
    # V070.51 — performed_by para skip self-action (supervisor que se
    # asigna leads masivamente a si mismo no recibe spam).
    if result["changed"] and new_asesor_id:
        try:
            count = result["changed"]
            preview = ", ".join(result["lead_names"][:3])
            extra = f" (+{count - 3} más)" if count > 3 else ""
            notify_lead_reassigned(
                new_asesor_id,
                f"{count} leads: {preview}{extra}",
                performed_by=current_user.user_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("push masivo fallido: %s", exc)

    return {"changed": result["changed"], "skipped": result["skipped"]}


# ---------------------------------------------------------------------------
# Derivacion al asesor original (Opcion B — botón en card de Antecedentes)
# ---------------------------------------------------------------------------

def _asesor_aparece_en_antecedentes(lead_id: int, asesor_id: str) -> bool:
    """Valida que `asesor_id` haya trabajado historicamente al cliente del
    `lead_id` (via match de telefono por ultimos 9 digitos).

    Es la salvaguarda anti-abuso: sin esto, un supervisor podria mandar
    cualquier lead a cualquier asesor de cualquier equipo solo invocando
    /derivar-antecedente. Aqui restringimos a asesores que el sistema
    mismo identificaria como "antecedente" del lead.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 1
                FROM crm.leads cur_l
                JOIN crm.leads other_l
                  ON RIGHT(REGEXP_REPLACE(other_l.telefono, '\\D', '', 'g'), 9) =
                     RIGHT(REGEXP_REPLACE(cur_l.telefono,   '\\D', '', 'g'), 9)
                 AND other_l.id <> cur_l.id
                WHERE cur_l.id      = %s
                  AND other_l.asesor_id = %s::uuid
                LIMIT 1
                """,
                (lead_id, asesor_id),
            )
            return cur.fetchone() is not None


def derive_to_original_asesor(
    *,
    lead_id: int,
    target_asesor_id: str,
    current_user: TokenData,
) -> dict:
    """Devuelve el lead al asesor que lo trabajo previamente segun antecedentes.

    Bypass del check de equipo (`_authorize_target`) — pero solo si el
    `target_asesor_id` realmente aparece en los antecedentes del lead.

    Solo admin y supervisor pueden invocar este flujo. Los asesores no.
    """
    if current_user.role not in (Role.ADMIN, Role.SUPERVISOR):
        raise HTTPException(status_code=403, detail="No tienes permiso para derivar leads.")

    lead = leads_repository.fetch_lead_for_assignment(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    # El supervisor debe poder manipular el lead actual (el lead esta en
    # su equipo, en sus manos, o sin asignar a nadie de otro equipo).
    _authorize_source(current_user, lead["asesor_id"])

    if lead["asesor_id"] == target_asesor_id:
        return {
            "changed": False,
            "previous_asesor_id": lead["asesor_id"],
            "lead_name": lead["lead_name"],
        }

    if not _asesor_aparece_en_antecedentes(lead_id, target_asesor_id):
        raise HTTPException(
            status_code=400,
            detail="El asesor destino no aparece en los antecedentes de este lead.",
        )

    new_supervisor_id = _resolve_target_supervisor_id(target_asesor_id)
    result = leads_repository.reassign_one(
        lead_id=lead_id,
        new_asesor_id=target_asesor_id,
        new_supervisor_id=new_supervisor_id,
        performed_by=current_user.user_id,
        motivo=MOTIVO_DERIVACION_ANTECEDENTE,
    )

    if result["changed"]:
        try:
            notify_lead_reassigned(
                target_asesor_id,
                result["lead_name"],
                performed_by=current_user.user_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("push fallido tras derivar lead %s: %s", lead_id, exc)

    return result

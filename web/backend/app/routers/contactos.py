"""
Contactos router — historial de interacciones por lead.
- GET  /api/leads/{lead_id}/contactos       — listar contactos
- POST /api/leads/{lead_id}/contactos       — registrar contacto
"""
import logging
from functools import lru_cache
from fastapi import APIRouter, HTTPException, Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional
from app.auth.jwt import get_current_user, require_supervisor_or_admin
from app.auth.permissions import has_permission
from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/leads/{lead_id}/contactos", tags=["Contactos"])


@lru_cache(maxsize=1)
def _has_proxima_gestion_notificada_column() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'leads'
                      AND column_name  = 'proxima_gestion_notificada_at'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def _has_gestion_especial_admin_column() -> bool:
    try:
        from app.database import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'leads'
                      AND column_name  = 'gestion_especial_admin'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def _can_access_lead(lead_id: int, user: TokenData, cur) -> bool:
    """Verifica que el usuario tiene acceso al lead según su rol."""
    if user.role == "admin" or (getattr(user, "role_id", None) is not None and not getattr(user, "role_is_external", False)):
        cur.execute("SELECT id FROM crm.leads WHERE id = %s AND activo = TRUE", (lead_id,))
    elif user.role == "supervisor":
        # V035/V041: incluye leads en cola del supervisor (asesor_id IS NULL,
        # supervisor_id = self). El AND asesor_id IS NULL al final evita
        # acceso a leads que otro ya tomo pero que conservan supervisor_id
        # historicamente apuntando al supervisor original.
        cur.execute(
            """
            SELECT l.id FROM crm.leads l
            WHERE l.id = %s AND l.activo = TRUE
              AND (l.asesor_id IN (
                  SELECT asesor_id FROM crm.equipos
                  WHERE supervisor_id = %s::uuid AND activo = TRUE
              ) OR l.asesor_id = %s::uuid
                OR (l.asesor_id IS NULL AND l.supervisor_id = %s::uuid))
            """,
            (lead_id, user.user_id, user.user_id, user.user_id),
        )
    else:
        cur.execute(
            "SELECT id FROM crm.leads WHERE id = %s AND asesor_id = %s::uuid AND activo = TRUE",
            (lead_id, user.user_id),
        )
    return cur.fetchone() is not None


@router.get("")
def list_contactos(lead_id: int, current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _can_access_lead(lead_id, current_user, cur):
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            # V042 — Single SQL, sin conditionals defensivos. La migracion
            # V042 ya se aplico (auto-migrator + verificado en logs del
            # PATCH con has_column=True). Si por algun motivo no esta,
            # preferimos un 500 explicito que un silencio que confunde.
            #
            # COALESCE garantiza que aunque ce sea null (FK rota), seguimos
            # devolviendo algo razonable para el frontend.
            cur.execute(
                """
                SELECT
                    c.id, COALESCE(NULLIF(c.tipo_cita, ''), c.tipo_contacto) AS tipo_contacto, c.resultado, c.notas,
                    c.proxima_accion, c.fecha_proxima_accion::text,
                    c.fecha_cita::text, c.tipo_cita, c.url_reunion, c.duracion_minutos,
                    c.created_at::text,
                    c.asesor_id::text,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
                    c.cita_estado_id,
                    ce.codigo    AS cita_estado_codigo,
                    ce.nombre    AS cita_estado_nombre,
                    ce.color_hex AS cita_estado_color
                FROM crm.contactos c
                LEFT JOIN auth.users u           ON u.id = c.asesor_id
                LEFT JOIN crm.cita_estados ce    ON ce.id = c.cita_estado_id
                WHERE c.lead_id = %s
                ORDER BY c.created_at DESC
                """,
                (lead_id,),
            )
            rows = cur.fetchall()
            logger.info(
                "[contactos] GET lead=%s rows=%s sample_cita_estado=%s",
                lead_id, len(rows),
                rows[0].get('cita_estado_id') if rows else None,
            )
            return rows


class ContactoCreate(BaseModel):
    tipo_contacto: str = "llamada"   # llamada | whatsapp | email | presencial | nota
    resultado: Optional[str] = None
    notas: Optional[str] = None
    proxima_accion: Optional[str] = None
    fecha_proxima_accion: Optional[str] = None
    fecha_cita: Optional[str] = None
    tipo_cita: Optional[str] = None
    url_reunion: Optional[str] = None
    duracion_minutos: Optional[int] = None
    # Si se envía, actualiza también el estado del lead
    nuevo_estado_id: Optional[int] = None
    # V070.42 — Soporte para cita_estado_id (Pendiente/Reprogramacion/etc).
    # Antes este endpoint no lo aceptaba y la cita perdia el estado al crear
    # desde mobile.
    cita_estado_id: Optional[int] = None


@router.post("", status_code=201)
def create_contacto(
    lead_id: int,
    data: ContactoCreate,
    current_user: TokenData = Depends(get_current_user),
):
    if getattr(current_user, "role_id", None) is not None and not (has_permission(current_user, "agenda.edit") or has_permission(current_user, "leads.edit")):
        raise HTTPException(status_code=403, detail="No tienes permiso para registrar contactos o citas.")

    # V070.41 — AUTO-FIX en lugar de rechazo. Despues de 3 horas de bug
    # reproducible con clientes que mandan resultado=cita_agendada sin
    # fecha_cita (cause root no identificada en cliente — posible APK
    # vieja, race condition, payload corrupto), el backend YA NO rechaza
    # con 400 sino que AUTO-COMPLETA fecha_cita con NOW+1h en hora Lima.
    #
    # Razon: el usuario marca cita_agendada con INTENCION clara de tener
    # una cita. Si no envia fecha, defaultear es mejor UX que rechazar:
    # el supervisor ve la cita marcada y puede editar la hora exacta.
    # Antes el rechazo confundia al asesor que no entendia el error.
    #
    # Tradeoff aceptado: una cita con fecha default (NOW+1h) en lugar de
    # una cita sin fecha. El supervisor puede ajustar via editor.
    es_cita = (
        (data.resultado or '').strip().lower() == 'cita_agendada'
        or (data.tipo_contacto or '').strip().lower() == 'cita'
    )
    if es_cita and not (data.fecha_cita and data.fecha_cita.strip()):
        from datetime import datetime, timezone, timedelta
        default_dt = datetime.now(timezone(timedelta(hours=-5))) + timedelta(hours=1)
        # Redondear a hora exacta (minutos a 0).
        default_dt = default_dt.replace(minute=0, second=0, microsecond=0)
        data.fecha_cita = default_dt.strftime("%Y-%m-%dT%H:%M:00")
        logger.warning(
            "AUTO-FIX cita_agendada sin fecha_cita lead=%s user=%s → defaulted to %s",
            lead_id, current_user.user_id, data.fecha_cita
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _can_access_lead(lead_id, current_user, cur):
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            logger.info(
                "CREATE contacto lead_id=%s fecha_cita=%s tipo_cita=%s cita_estado_id=%s",
                lead_id, data.fecha_cita, data.tipo_cita, data.cita_estado_id
            )
            # V070.42 — Si es cita y no vino cita_estado_id, defaultear a
            # 'pendiente' del catalogo (paridad con agenda.py POST).
            cita_estado_id_final = data.cita_estado_id
            if es_cita and cita_estado_id_final is None:
                cur.execute(
                    "SELECT id FROM crm.cita_estados WHERE codigo = 'pendiente' LIMIT 1"
                )
                row_pe = cur.fetchone()
                cita_estado_id_final = row_pe["id"] if row_pe else None

            cur.execute(
                """
                INSERT INTO crm.contactos
                    (lead_id, asesor_id, tipo_contacto, resultado, notas,
                     proxima_accion, fecha_proxima_accion, fecha_cita, tipo_cita,
                     url_reunion, duracion_minutos, cita_estado_id)
                VALUES (%s, %s::uuid, %s, %s, %s, %s,
                        %s::timestamptz, %s::timestamptz, %s, %s, %s, %s)
                RETURNING id, fecha_cita::text
                """,
                (
                    lead_id, current_user.user_id,
                    data.tipo_contacto, data.resultado, data.notas,
                    data.proxima_accion, data.fecha_proxima_accion,
                    data.fecha_cita, data.tipo_cita,
                    data.url_reunion.strip() if data.url_reunion else None,
                    data.duracion_minutos,
                    cita_estado_id_final,
                ),
            )
            row = cur.fetchone()
            new_id = row["id"]

            # Registrar evento inicial de cita en historial de cambios
            if es_cita or (data.fecha_cita and str(data.fecha_cita).strip()) or cita_estado_id_final is not None:
                try:
                    from app.services import lead_history_service
                    lead_history_service.record_cita_event(
                        cur,
                        lead_id=lead_id,
                        user=current_user,
                        action="create",
                        contacto_id=new_id,
                        new_fecha_cita=data.fecha_cita,
                        new_cita_estado_id=cita_estado_id_final,
                        new_tipo_cita=data.tipo_cita or data.tipo_contacto,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[contactos] historial cita create fallo lead=%s: %s", lead_id, exc)

            # Actualizar estado del lead si se indicó
            if data.nuevo_estado_id:
                cur.execute(
                    """
                    SELECT l.estado_id, e.nombre AS previous_estado_nombre
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.id = %s
                    """,
                    (lead_id,),
                )
                prev_lead = cur.fetchone()
                prev_estado_id = prev_lead["estado_id"] if prev_lead else None
                prev_estado_nombre = prev_lead.get("previous_estado_nombre") if prev_lead else None

                cur.execute(
                    "UPDATE crm.leads SET estado_id = %s, updated_at = NOW() WHERE id = %s",
                    (data.nuevo_estado_id, lead_id),
                )

                # V119: si quien cambia el estado es admin y el lead cumple reglas de no contesta, activar gestion especial
                is_admin = getattr(current_user, "role", None) in ("admin",)
                activar_ga = False
                if is_admin and _has_gestion_especial_admin_column():
                    from app.services.lead_automation_service import lead_cumple_reglas_no_contesta
                    if lead_cumple_reglas_no_contesta(cur, lead_id, prev_estado_nombre):
                        activar_ga = True
                        cur.execute(
                            """
                            UPDATE crm.leads
                            SET gestion_especial_admin = TRUE,
                                gestion_admin_at = NOW(),
                                gestion_admin_user_id = %s::uuid
                            WHERE id = %s
                            """,
                            (current_user.user_id, lead_id),
                        )

                if prev_estado_id != data.nuevo_estado_id and data.tipo_contacto != "cambio_estado":
                    cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (data.nuevo_estado_id,))
                    ne_row = cur.fetchone()
                    ne_nombre = ne_row["nombre"] if ne_row else str(data.nuevo_estado_id)
                    prox_act = str(data.fecha_proxima_accion).strip() if (data.fecha_proxima_accion and str(data.fecha_proxima_accion).strip()) else None
                    nota_cambio = f"Estado → {ne_nombre}"
                    if activar_ga:
                        nota_cambio += " · 🛡️ Caso especial: Gestión por Administración (se ha apagado el cambio automático para este lead)"
                    cur.execute(
                        """
                        INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas, fecha_proxima_accion)
                        VALUES (%s, %s::uuid, 'cambio_estado', %s, %s::timestamptz)
                        """,
                        (lead_id, current_user.user_id, nota_cambio, prox_act),
                    )
                    try:
                        from app.services import lead_history_service
                        lead_history_service.record_status_change(
                            cur,
                            lead_id=lead_id,
                            user=current_user,
                            old_estado_id=prev_estado_id,
                            new_estado_id=data.nuevo_estado_id,
                            origen="cambio_estado",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[contactos] historial estado create fallo lead=%s: %s", lead_id, exc)

            if data.fecha_proxima_accion and str(data.fecha_proxima_accion).strip():
                set_clause = "fecha_proxima_gestion = %s::timestamptz, updated_at = NOW()"
                if _has_proxima_gestion_notificada_column():
                    set_clause = "fecha_proxima_gestion = %s::timestamptz, proxima_gestion_notificada_at = NULL, updated_at = NOW()"
                cur.execute(
                    f"""
                    UPDATE crm.leads
                    SET {set_clause}
                    WHERE id = %s
                    """,
                    (str(data.fecha_proxima_accion).strip(), lead_id),
                )

            # Actualizar timestamp del lead
            cur.execute(
                "UPDATE crm.leads SET updated_at = NOW() WHERE id = %s",
                (lead_id,),
            )

        conn.commit()

    # V103 — Evaluar y cerrar SLA de primer contacto si aplica
    if data.tipo_contacto != "cambio_estado":
        try:
            from app.services import sla_service
            sla_service.registrar_primer_contacto_sla(lead_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SLA] Error evaluando SLA tras contacto lead=%s: %s", lead_id, exc)

        # V109 — Evaluar cambio automático a No contesta Día 1/2/3 si no vino nuevo_estado_id manual
        if not data.nuevo_estado_id:
            try:
                from app.services import lead_automation_service
                lead_automation_service.evaluar_lead_individual_no_contesta(lead_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[Auto-Estado] Error evaluando lead=%s tras contacto: %s", lead_id, exc)

    return {"id": new_id, "message": "Contacto registrado", "fecha_cita_saved": row["fecha_cita"]}


class ContactoUpdate(BaseModel):
    tipo_contacto:        Optional[str] = None
    resultado:            Optional[str] = None
    notas:                Optional[str] = None
    fecha_cita:           Optional[str] = None   # ISO datetime string
    # V042: estado de la cita (Pendiente / Completada / Reprogramada / ...)
    cita_estado_id:       Optional[int] = None
    # V070.97 — patrón estándar: al editar un contacto, el asesor puede
    # tambien cambiar el estado del lead en la misma operacion. Antes
    # solo CREATE lo aceptaba; el PATCH lo ignoraba silenciosamente y
    # mobile bloqueaba el envio condicionalmente. Bug B reportado.
    nuevo_estado_id:      Optional[int] = None
    # Campos que existian en CREATE pero faltaban en PATCH (paridad total).
    proxima_accion:       Optional[str] = None
    fecha_proxima_accion: Optional[str] = None
    tipo_cita:            Optional[str] = None
    url_reunion:          Optional[str] = None
    duracion_minutos:     Optional[int] = None


def _get_contact_permissions(cur):
    """Lee permisos de contactos desde app_settings."""
    cur.execute("SELECT value FROM public.app_settings WHERE key = 'contact_permissions'")
    row = cur.fetchone()
    return row["value"] if row else {"asesor_can_edit": False, "asesor_can_delete": False}


@router.patch("/{contacto_id}", status_code=200)
def update_contacto(
    lead_id: int,
    contacto_id: int,
    data: ContactoUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    if getattr(current_user, "role_id", None) is not None and not (has_permission(current_user, "agenda.edit") or has_permission(current_user, "leads.edit")):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar contactos o citas.")

    """Edita campos de un contacto. Permisos configurables para asesores."""
    set_parts  = []
    params     = []

    if data.tipo_contacto is not None:
        set_parts.append("tipo_contacto = %s"); params.append(data.tipo_contacto)
    if data.resultado is not None:
        set_parts.append("resultado = %s");     params.append(data.resultado)
    if data.notas is not None:
        set_parts.append("notas = %s");         params.append(data.notas or None)
    if data.fecha_cita is not None:
        set_parts.append("fecha_cita = %s::timestamptz")
        params.append(data.fecha_cita if data.fecha_cita.strip() else None)
    # V070.97 — paridad total con CREATE: aceptar todos los campos editables.
    if data.proxima_accion is not None:
        set_parts.append("proxima_accion = %s"); params.append(data.proxima_accion or None)
    if data.fecha_proxima_accion is not None:
        set_parts.append("fecha_proxima_accion = %s::timestamptz")
        params.append(data.fecha_proxima_accion if data.fecha_proxima_accion.strip() else None)
    if data.tipo_cita is not None:
        set_parts.append("tipo_cita = %s");      params.append(data.tipo_cita or None)
    if data.url_reunion is not None:
        set_parts.append("url_reunion = %s");    params.append(data.url_reunion.strip() if data.url_reunion and data.url_reunion.strip() else None)
    if data.duracion_minutos is not None:
        set_parts.append("duracion_minutos = %s"); params.append(data.duracion_minutos)
    # V042: estado de la cita — solo si la columna existe (V042 aplicada).
    # Logueamos para poder diagnosticar si el dato se ignora silenciosamente
    # (sintoma reportado: el estado no persiste al editar).
    from app.routers.agenda import _has_cita_estado_column
    has_col = _has_cita_estado_column()
    if data.cita_estado_id is not None:
        logger.info(
            "[contactos] PATCH lead=%s contacto=%s cita_estado_id=%s has_column=%s",
            lead_id, contacto_id, data.cita_estado_id, has_col,
        )
        if has_col:
            set_parts.append("cita_estado_id = %s")
            params.append(data.cita_estado_id)
    elif has_col and data.fecha_cita and data.fecha_cita.strip():
        # Safety net: si llega un PATCH con fecha_cita pero sin cita_estado_id,
        # garantizamos que el row queda con al menos 'pendiente' usando
        # COALESCE — preserva el valor existente, solo escribe Pendiente
        # cuando es null. Cubre clientes viejos / cache del browser.
        set_parts.append(
            "cita_estado_id = COALESCE(cita_estado_id, "
            "(SELECT id FROM crm.cita_estados WHERE codigo = 'pendiente' LIMIT 1))"
        )
        logger.info(
            "[contactos] PATCH lead=%s contacto=%s safety-net default Pendiente",
            lead_id, contacto_id,
        )

    if not set_parts and data.nuevo_estado_id is None:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar existencia del contacto
            cur.execute(
                "SELECT id, tipo_contacto, resultado, notas, fecha_cita, tipo_cita, cita_estado_id "
                "FROM crm.contactos WHERE id = %s AND lead_id = %s",
                (contacto_id, lead_id),
            )
            contacto_existente = cur.fetchone()
            if not contacto_existente:
                raise HTTPException(status_code=404, detail="Contacto no encontrado")

            # Verificar permiso para asesores:
            # Los asesores siempre pueden editar citas (para reprogramar fecha, cambiar estado de cita, tipo, etc.).
            # Para contactos que NO son citas, requieren el permiso configurable 'asesor_can_edit'.
            if current_user.role == "asesor":
                perms = _get_contact_permissions(cur)
                if not perms.get("asesor_can_edit"):
                    es_cita = (
                        bool(contacto_existente.get("fecha_cita"))
                        or bool(contacto_existente.get("tipo_cita"))
                        or bool(contacto_existente.get("cita_estado_id"))
                        or "cita" in (contacto_existente.get("resultado") or "").lower()
                        or "cita" in (contacto_existente.get("tipo_contacto") or "").lower()
                        or bool(data.fecha_cita and data.fecha_cita.strip())
                        or bool(data.tipo_cita and data.tipo_cita.strip())
                        or bool(data.cita_estado_id)
                        or ("cita" in (data.resultado or "").lower())
                        or ("cita" in (data.tipo_contacto or "").lower())
                    )
                    if not es_cita:
                        raise HTTPException(status_code=403, detail="No tienes permiso para editar contactos")

            # Update del contacto (si hay campos del contacto a tocar)
            if set_parts:
                contacto_params = params + [contacto_id, lead_id]
                cur.execute(
                    f"UPDATE crm.contactos SET {', '.join(set_parts)} "
                    f"WHERE id = %s AND lead_id = %s RETURNING id",
                    contacto_params,
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Contacto no encontrado")

                # Registrar cambios de cita (estado_cita, fecha_cita, tipo_cita) en historial de cambios
                if (
                    data.cita_estado_id is not None
                    or data.fecha_cita is not None
                    or data.tipo_cita is not None
                ):
                    try:
                        from app.services import lead_history_service
                        lead_history_service.record_cita_event(
                            cur,
                            lead_id=lead_id,
                            user=current_user,
                            action="update",
                            contacto_id=contacto_id,
                            old_fecha_cita=contacto_existente.get("fecha_cita"),
                            new_fecha_cita=data.fecha_cita,
                            old_cita_estado_id=contacto_existente.get("cita_estado_id"),
                            new_cita_estado_id=data.cita_estado_id,
                            old_tipo_cita=contacto_existente.get("tipo_cita"),
                            new_tipo_cita=data.tipo_cita,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[contactos] historial cita patch fallo lead=%s: %s", lead_id, exc)

                # V096.8 — Reset de recordatorios al reprogramar la cita.
                # Bug ID: bug visto en vivo 2026-06-24 sobre contacto 2822.
                # Cuando un asesor reprograma una cita cuyo recordatorio ya
                # se envio (o quedo marcado como "sin_telefono"), el flag en
                # crm.recordatorios_enviados sigue ahi y bloquea cualquier
                # nuevo recordatorio. Borrarlo aqui hace que el siguiente
                # poll de n8n vuelva a evaluar la cita con su nueva fecha.
                # Best-effort dentro de la misma transaccion: si la tabla
                # no existe o falla por algo raro, no rompe el PATCH (el
                # usuario igual ve la cita reprogramada en la UI).
                if data.fecha_cita is not None:
                    try:
                        cur.execute(
                            "DELETE FROM crm.recordatorios_enviados "
                            "WHERE contacto_id = %s AND tipo IN ('whatsapp_cita', 'push_llamada_1h', 'push_cita_1h')",
                            (contacto_id,),
                        )
                        if cur.rowcount:
                            logger.info(
                                "[contactos] reprograma lead=%s contacto=%s — reset %d recordatorio(s)",
                                lead_id, contacto_id, cur.rowcount,
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "[contactos] reset recordatorios fallo lead=%s contacto=%s: %s",
                            lead_id, contacto_id, exc,
                        )

            # V070.97 — patrón estándar: actualizar estado del lead si se
            # pidio en el mismo PATCH.
            if data.nuevo_estado_id is not None:
                cur.execute("SELECT estado_id FROM crm.leads WHERE id = %s", (lead_id,))
                prev_lead = cur.fetchone()
                prev_estado_id = prev_lead["estado_id"] if prev_lead else None

                cur.execute(
                    "UPDATE crm.leads SET estado_id = %s, updated_at = NOW() WHERE id = %s",
                    (data.nuevo_estado_id, lead_id),
                )
                if prev_estado_id != data.nuevo_estado_id:
                    cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (data.nuevo_estado_id,))
                    ne_row = cur.fetchone()
                    ne_nombre = ne_row["nombre"] if ne_row else str(data.nuevo_estado_id)
                    cur.execute(
                        """
                        INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas)
                        VALUES (%s, %s::uuid, 'cambio_estado', %s)
                        """,
                        (lead_id, current_user.user_id, f"Estado → {ne_nombre}"),
                    )
                    try:
                        from app.services import lead_history_service
                        lead_history_service.record_status_change(
                            cur,
                            lead_id=lead_id,
                            user=current_user,
                            old_estado_id=prev_estado_id,
                            new_estado_id=data.nuevo_estado_id,
                            origen="cambio_estado",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[contactos] historial estado patch fallo lead=%s: %s", lead_id, exc)
                logger.info(
                    "[contactos] PATCH lead=%s nuevo_estado_id=%s aplicado al lead",
                    lead_id, data.nuevo_estado_id,
                )
        conn.commit()
    return {"message": "Contacto actualizado"}


@router.delete("/{contacto_id}", status_code=200)
def delete_contacto(
    lead_id: int,
    contacto_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    if getattr(current_user, "role_id", None) is not None and not (has_permission(current_user, "agenda.edit") or has_permission(current_user, "leads.delete")):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar contactos.")

    """Elimina un contacto del historial. Permisos configurables para asesores."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if current_user.role == "asesor" and getattr(current_user, "role_id", None) is None:
                perms = _get_contact_permissions(cur)
                if not perms.get("asesor_can_delete"):
                    raise HTTPException(status_code=403, detail="No tienes permiso para eliminar contactos")
            cur.execute(
                "DELETE FROM crm.contactos WHERE id = %s AND lead_id = %s RETURNING id",
                (contacto_id, lead_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Contacto no encontrado")
        conn.commit()
    return {"message": "Contacto eliminado"}

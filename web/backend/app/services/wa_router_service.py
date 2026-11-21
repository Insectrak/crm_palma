"""
wa_router_service.py — Ruteo inteligente de conversaciones WhatsApp clasificadas.

Responsabilidad:
  Una vez que wa_classifier_service termino de clasificar, decidimos que
  hacer con la conversacion segun categoria + confianza:

  +-----------------------+-----------+------------------------------------+
  | categoria             | confianza | accion                             |
  +-----------------------+-----------+------------------------------------+
  | cliente_potencial     | >= 0.8    | crear lead + rotacion supervisor   |
  | cliente_potencial     | < 0.8     | manual_review                      |
  | cliente_existente     | *         | manual_review (matcheo manual)     |
  | consulta_general      | >= 0.8    | archived (reason=not_a_lead)       |
  | consulta_general      | < 0.8    | manual_review                       |
  | spam                  | >= 0.85   | archived (reason=spam)             |
  | no_relacionado        | >= 0.85   | archived (reason=not_a_lead)       |
  | cualquier             | < 0.8 spam| manual_review                      |
  +-----------------------+-----------+------------------------------------+

  EXCEPCION CTWA: si la conversacion vino de un Click-to-WhatsApp Ad
  (referral o wa_campaign_id presente), NUNCA se auto-archiva. El cliente
  clickeo un anuncio — pago dinero de marketing para que llegue — entonces
  por definicion es un lead a revisar. La IA puede equivocarse leyendo
  "Hola" generico como consulta_general; el contexto del anuncio manda.
  En ese caso bajamos a manual_review en vez de archivar.

Reusa helpers de routers.ingest (misma rotacion que usan los webhooks de
n8n para FB/TikTok/WhatsApp via Evolution). Asi la rotacion WA sigue el
mismo reparto que el resto de leads — no duplicamos logica.

Clean Code / SOLID:
  - SRP: solo rutea. No clasifica, no llama IA. Recibe el resultado ya
    normalizado del classifier.
  - DIP: depende de `notify_new_lead` y de los helpers de ingest, no de
    psycopg2 directo (excepto para el UPDATE final de wa_conversations,
    que es logica propia de este modulo).
"""
from __future__ import annotations

import logging
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db
from app.services.notification_service import notify_new_lead

logger = logging.getLogger(__name__)

# Threshold para auto-asignar (consultado con el product owner: 0.8)
_AUTO_ASSIGN_THRESHOLD = 0.80

# Threshold para archivar spam/no_relacionado (mas alto para no perder leads
# reales mal clasificados). A 0.85 forzamos al modelo a estar muy seguro
# antes de silenciar la conversacion.
_ARCHIVE_THRESHOLD = 0.85

# Estados terminales — dedupe IGNORA leads en estos estados, asi un cliente
# que vuelve a escribir despues de cerrado crea un caso nuevo (nueva rotacion).
_TERMINAL_LEAD_STATES = ('Ganado', 'Perdido', 'No interesado')


# ─────────────────────────────────────────────────────────────────────────────
# Punto de entrada
# ─────────────────────────────────────────────────────────────────────────────

def route_classified_conversation(
    conversation_id: int,
    result: dict,
    ctx: dict,
    force_new_lead: bool = False,
) -> None:
    """Decide accion segun categoria y confianza. No levanta excepciones.

    force_new_lead: cuando viene de /new_case (usuario pidio caso nuevo
    explicitamente), saltamos todo el gating categoria/confianza y vamos
    directo a crear lead con rotacion. La IA sigue corriendo para poblar
    category/interest/summary, pero no decide si hay lead o no.
    """
    categoria = result.get("categoria", "consulta_general")
    confianza = float(result.get("confianza") or 0)
    came_from_ad = _is_ctwa_sourced(ctx)

    # Thresholds dinamicos desde config (editables en /Configuracion → IA).
    # Fallback a constantes si config falla por algun motivo. Defensive:
    # clamp a [0, 1] y verifica tipo numerico para evitar prompts malicioso.
    try:
        from app.services.wa_classifier_service import load_ai_config
        cfg = load_ai_config()
        auto_assign = max(0.0, min(float(cfg.get("auto_assign_threshold") or _AUTO_ASSIGN_THRESHOLD), 1.0))
        auto_archive = max(0.0, min(float(cfg.get("auto_archive_threshold") or _ARCHIVE_THRESHOLD), 1.0))
    except Exception:  # noqa: BLE001
        auto_assign = _AUTO_ASSIGN_THRESHOLD
        auto_archive = _ARCHIVE_THRESHOLD

    try:
        if force_new_lead:
            _create_lead_and_rotate(
                conversation_id, result, ctx, force_new_lead=True,
            )
            return

        if categoria == "cliente_potencial" and confianza >= auto_assign:
            _create_lead_and_rotate(conversation_id, result, ctx)
            return

        # CTWA override: si vino de un anuncio, jamas auto-archivamos —
        # marketing ya pago por traerlo, el contexto manda sobre el texto
        # generico que el cliente escribio.
        if came_from_ad:
            logger.info(
                "wa_router: conv=%s cat=%s conf=%.2f vino de CTWA — "
                "manual_review (override de auto-archive)",
                conversation_id, categoria, confianza,
            )
            _send_to_manual_review(conversation_id)
            return

        if categoria == "spam" and confianza >= auto_archive:
            _archive(conversation_id, reason="spam",
                     notes=f"Auto-archivado: IA spam conf={confianza:.2f}")
            return

        if categoria == "no_relacionado" and confianza >= auto_archive:
            _archive(conversation_id, reason="not_a_lead",
                     notes=f"Auto-archivado: IA no_relacionado conf={confianza:.2f}")
            return

        # V036: consulta_general con confianza alta = no es lead comercial.
        # Auto-archivo evita ensuciar inbox del supervisor. Reversible via
        # /reclassify si la IA se equivoco.
        if categoria == "consulta_general" and confianza >= auto_assign:
            _archive(conversation_id, reason="not_a_lead",
                     notes=f"Auto-archivado: IA consulta_general conf={confianza:.2f}")
            return

        # Todo lo demas (cliente_existente, consulta_general baja conf, etc.)
        _send_to_manual_review(conversation_id)

    except Exception as exc:  # noqa: BLE001 — best effort
        logger.exception(
            "wa_router: excepcion ruteando conv=%s cat=%s: %s",
            conversation_id, categoria, exc,
        )
        # En caso de error, mandar a bandeja manual — nada se pierde
        _send_to_manual_review(conversation_id)


# ─────────────────────────────────────────────────────────────────────────────
# Acciones
# ─────────────────────────────────────────────────────────────────────────────

def _create_lead_and_rotate(
    conversation_id: int,
    result: dict,
    ctx: dict,
    force_new_lead: bool = False,
) -> None:
    """Crea (o reutiliza) lead en crm.leads y lo asigna al proximo supervisor
    segun rotacion diaria. Persiste lead_id + asesor_id en wa_conversations
    y envia push notification.

    force_new_lead: salta el dedupe por telefono. Usado por /new_case cuando
    el cliente vuelve por un lote distinto y el asesor quiere un caso y
    lead completamente nuevos (no quiere arrastrar el historial del lead
    activo viejo).
    """
    # Reuso helpers privados del router de ingest para no duplicar logica
    # de rotacion. Es intencional — los helpers viven alli porque fueron
    # escritos primero. Si se deja caer ingest.py habria que mover los
    # helpers a un modulo compartido; por ahora la dependencia es clara.
    from app.routers.ingest import (
        _bump_rotacion,
        _clean_phone,
        _FECHA_LIMA,
        _next_supervisor,
        _resolve_fuente_id,
    )

    wa_phone = ctx.get("wa_phone") or ""
    telefono = _clean_phone(wa_phone) or wa_phone

    # Nombre: prefiero el sugerido por IA, sino el del perfil WhatsApp
    full_name = (
        result.get("nombre_sugerido")
        or ctx.get("contact_name")
        or "Lead WhatsApp"
    ).strip()
    parts = full_name.split(" ", 1)
    nombres = parts[0] or "Lead"
    apellidos = parts[1] if len(parts) > 1 else None

    observaciones = _build_observations(result, ctx)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Dedupe por telefono — IGNORA leads en estado terminal para que
            # un cliente que vuelve despues de Ganado/Perdido/No interesado
            # genere un caso nuevo via rotacion (no reutiliza el viejo).
            # force_new_lead (venido de /new_case) salta el dedupe: el
            # asesor pidio un caso/lead nuevos aunque el telefono ya tenga
            # otro lead activo.
            if force_new_lead:
                existing = None
                logger.info(
                    "wa_router: conv=%s force_new_lead activo — skip dedupe",
                    conversation_id,
                )
            else:
                cur.execute(
                    """
                    SELECT l.id, l.asesor_id, e.nombre AS estado
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.telefono = %s
                      AND l.activo = TRUE
                      AND COALESCE(e.nombre, '') <> ALL(%s)
                    ORDER BY l.created_at DESC
                    LIMIT 1
                    """,
                    (telefono, list(_TERMINAL_LEAD_STATES)),
                )
                existing = cur.fetchone()

            if existing:
                lead_id = existing["id"]
                asesor_id = str(existing["asesor_id"]) if existing["asesor_id"] else None
                logger.info(
                    "wa_router: conv=%s lead existente id=%s (dedupe por telefono)",
                    conversation_id, lead_id,
                )
            else:
                # Crear lead nuevo con rotacion de supervisor
                fuente_id = _resolve_fuente_id(cur, "whatsapp")
                if not fuente_id:
                    logger.error("wa_router: fuente 'whatsapp' no existe en crm.fuentes")
                    _send_to_manual_review(conversation_id)
                    return

                cur.execute("SELECT id FROM crm.estados_lead WHERE nombre = 'Nuevo' LIMIT 1")
                estado_row = cur.fetchone()
                if not estado_row:
                    logger.error("wa_router: estado 'Nuevo' no existe en crm.estados_lead")
                    _send_to_manual_review(conversation_id)
                    return
                estado_id = estado_row["id"]

                # V110 + V113 — Asignación exclusiva por campaña publicitaria
                designated_sup_id = None
                camp_dist_mode = "supervisor"
                camp_assigned_asesor = None
                try:
                    from app.services.campaign_assignment_service import (
                        resolve_campaign_supervisor_assignment,
                        assign_to_supervisor_team_round_robin,
                    )
                    camp_rule = resolve_campaign_supervisor_assignment(
                        cur,
                        campana=ctx.get("campaign_name") or str(ctx.get("wa_campaign_id") or ""),
                        campaign_name=ctx.get("meta_campaign_name") or ctx.get("campaign_name"),
                        provider="meta",
                    )
                    if camp_rule:
                        designated_sup_id = camp_rule["supervisor_id"]
                        camp_dist_mode = camp_rule.get("distribution_mode") or "supervisor"
                        if camp_dist_mode in ("equipo", "todos"):
                            camp_assigned_asesor = assign_to_supervisor_team_round_robin(
                                cur,
                                designated_sup_id,
                                distribution_mode=camp_dist_mode,
                                cas_id=camp_rule.get("cas_id"),
                                member_percentages=camp_rule.get("member_percentages"),
                                member_counts=camp_rule.get("member_counts"),
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[campaign-assignment] wa_router error: %s", exc)

                supervisor_id = designated_sup_id or _next_supervisor(cur, _FECHA_LIMA)
                if not supervisor_id:
                    logger.warning(
                        "wa_router: no hay supervisores activos para rotacion, "
                        "conv=%s va a manual_review",
                        conversation_id,
                    )
                    _send_to_manual_review(conversation_id)
                    return

                # Si hubo reparto en equipo por campaña, asesor_id es el asesor ganador; si no, supervisor_id
                asesor_id = camp_assigned_asesor["user_id"] if camp_assigned_asesor else supervisor_id

                cur.execute(
                    """
                    INSERT INTO crm.leads
                        (nombres, apellidos, telefono, campana,
                         fuente_id, estado_id, asesor_id, supervisor_id,
                         observaciones, activo)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::uuid, %s::uuid, %s, TRUE)
                    RETURNING id
                    """,
                    (
                        nombres, apellidos, telefono, ctx.get("campaign_name"),
                        fuente_id, estado_id, asesor_id, supervisor_id, observaciones,
                    ),
                )
                lead_id = cur.fetchone()["id"]

                # Atribucion de campaña si vino por CTWA (ya se guardo en el webhook
                # si el lead_id existia; como es nuevo, lo escribimos ahora)
                referral = ctx.get("referral") or {}
                if referral:
                    cur.execute(
                        """
                        UPDATE crm.leads SET
                            wa_campaign_ad_id    = %s,
                            wa_campaign_headline = %s,
                            wa_ctwa_clid         = %s,
                            wa_referral_payload  = %s::jsonb
                        WHERE id = %s
                        """,
                        (
                            referral.get("source_id"),
                            referral.get("headline"),
                            referral.get("ctwa_clid"),
                            # Json() normalmente, pero aca pasamos dict via ::jsonb cast
                            _json_dumps_safe(referral),
                            lead_id,
                        ),
                    )

                if designated_sup_id:
                    try:
                        c_name = ctx.get("campaign_name") or "WhatsApp"
                        if camp_assigned_asesor:
                            cur.execute(
                                """
                                INSERT INTO crm.asignaciones_log
                                    (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                                VALUES (%s, NULL, %s::uuid, NULL, 'campana_reparto_equipo')
                                """,
                                (lead_id, asesor_id),
                            )
                            cur.execute(
                                """
                                INSERT INTO crm.contactos
                                    (lead_id, asesor_id, tipo_contacto, notas, created_at)
                                VALUES (%s, %s::uuid, 'sistema', %s, NOW())
                                """,
                                (
                                    lead_id,
                                    asesor_id,
                                    f"👥 Lead CTWA repartido equitativamente al asesor {camp_assigned_asesor['nombre']} por campaña ({c_name})",
                                ),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO crm.asignaciones_log
                                    (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                                VALUES (%s, NULL, %s::uuid, NULL, 'campana_supervisor_directo')
                                """,
                                (lead_id, designated_sup_id),
                            )
                            nota_sup = (
                                f"👤 Lead CTWA asignado directo al supervisor por regla de Leads Campañas ({c_name})"
                                if camp_dist_mode == "supervisor"
                                else f"🎯 Lead CTWA asignado a supervisor por regla de Leads Campañas ({c_name}) [Equipo sin asesores disponibles]"
                            )
                            cur.execute(
                                """
                                INSERT INTO crm.contactos
                                    (lead_id, asesor_id, tipo_contacto, notas, created_at)
                                VALUES (%s, %s::uuid, 'sistema', %s, NOW())
                                """,
                                (
                                    lead_id,
                                    designated_sup_id,
                                    nota_sup,
                                ),
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[campaign-assignment] wa_router log fallo: %s", exc)
                else:
                    _bump_rotacion(cur, _FECHA_LIMA, supervisor_id, lead_id)

                logger.info(
                    "wa_router: conv=%s lead nuevo id=%s asesor=%s",
                    conversation_id, lead_id, asesor_id,
                )

            # Atar la conversation al lead + asesor (ambos casos)
            cur.execute(
                """
                UPDATE crm.wa_conversations SET
                    lead_id   = %s,
                    asesor_id = CASE WHEN %s IS NULL THEN asesor_id ELSE %s::uuid END
                WHERE id = %s
                """,
                (lead_id, asesor_id, asesor_id, conversation_id),
            )

            # Registra el caso en el historial — V025. Si la tabla aun no
            # existe (deploy a medias), el INSERT falla y solo logueamos:
            # el lead ya esta atado a la conversacion, el historial es
            # auxiliar y se reconstruye al aplicar la migracion.
            try:
                cur.execute(
                    """
                    INSERT INTO crm.wa_conversation_leads
                        (conversation_id, lead_id, created_by)
                    VALUES (%s, %s, 'auto_classifier')
                    ON CONFLICT (conversation_id, lead_id) DO NOTHING
                    """,
                    (conversation_id, lead_id),
                )
            except Exception as exc:  # noqa: BLE001 — V025 puede no existir aun
                logger.warning(
                    "wa_router: no se pudo registrar caso en wa_conversation_leads: %s",
                    exc,
                )
        conn.commit()

    # Push FCM (fuera de la transaccion — no debe bloquear el commit)
    if asesor_id:
        lead_name = f"{nombres} {apellidos or ''}".strip()
        preview = (result.get("resumen") or "Nuevo chat WhatsApp")[:80]
        body = f"{lead_name} — {preview}"
        campaign = ctx.get("campaign_name") or "whatsapp"
        # V070.91 — lead_id para deep-link al tap.
        notify_new_lead(asesor_id, body, campaign, lead_id=result.get("lead_id"))


def _is_ctwa_sourced(ctx: dict) -> bool:
    """¿La conversacion vino de un Click-to-WhatsApp Ad?

    Detectamos por dos fuentes complementarias:
      - `referral`: payload del webhook de Meta (source_type/source_id) — se
        llena cuando el primer mensaje incluye el bloque referral.
      - `campaign_name`: viene del JOIN con wa_campaigns via lead.wa_campaign_id —
        si ya hay lead asociado y campaña, el origen es CTWA.

    Cualquiera de las dos basta. No miramos profundidad del payload — la
    mera presencia es prueba suficiente de que vino de un anuncio.
    """
    if not isinstance(ctx, dict):
        return False
    if ctx.get("campaign_name"):
        return True
    referral = ctx.get("referral")
    if isinstance(referral, dict) and (referral.get("source_type") or referral.get("source_id")):
        return True
    return False


def _archive(
    conversation_id: int,
    reason: str = "other",
    notes: Optional[str] = None,
) -> None:
    """Archiva la conversacion con auditoria (V036).

    archived_by queda NULL porque es accion automatica de la IA — solo
    se llena cuando un humano archiva via POST /conversations/{id}/archive.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.wa_conversations
                   SET classification_status = 'archived',
                       archived_reason       = %s,
                       archived_notes        = %s,
                       archived_at           = NOW()
                 WHERE id = %s
                """,
                (reason, notes, conversation_id),
            )
        conn.commit()
    logger.info(
        "wa_router: conv=%s archivada reason=%s", conversation_id, reason,
    )


def _send_to_manual_review(conversation_id: int) -> None:
    _update_status(conversation_id, "manual_review")
    logger.info("wa_router: conv=%s -> manual_review", conversation_id)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _update_status(conversation_id: int, new_status: str) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET classification_status = %s
                WHERE id = %s
                """,
                (new_status, conversation_id),
            )
        conn.commit()


def _build_observations(result: dict, ctx: dict) -> str:
    """Construye un bloque legible con la info extraida por IA para el asesor."""
    lines = []
    if result.get("resumen"):
        lines.append(f"[IA] {result['resumen']}")
    if result.get("interes"):
        lines.append(f"Interes: {result['interes']}")
    if result.get("urgencia") and result["urgencia"] != "media":
        lines.append(f"Urgencia: {result['urgencia'].upper()}")
    if result.get("presupuesto_mencionado"):
        lines.append(f"Presupuesto: {result['presupuesto_mencionado']}")
    if result.get("zona_mencionada"):
        lines.append(f"Zona: {result['zona_mencionada']}")
    if ctx.get("campaign_name"):
        lines.append(f"Campaña: {ctx['campaign_name']}")
    if result.get("confianza") is not None:
        lines.append(f"Confianza IA: {result['confianza']:.0%}")
    return "\n".join(lines) if lines else "Lead generado automaticamente desde WhatsApp."


def _json_dumps_safe(obj) -> str:
    """JSON dump tolerante a tipos no serializables."""
    import json
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return "{}"


# ─────────────────────────────────────────────────────────────────────────────
# Take action — crear lead manualmente cuando un asesor "toma" una conv
# ─────────────────────────────────────────────────────────────────────────────

def create_lead_from_take_action(
    conversation_id: int,
    taker_user_id: str,
    taker_role: str,
) -> dict:
    """Crea (o reutiliza) un lead cuando un usuario toma una conversacion.

    Diferencia clave con `_create_lead_and_rotate`:
      - No depende de resultado de IA — el humano decidio que es lead.
      - No usa rotacion — el asesor tomador queda como dueño directo.
      - Estado inicial 'Nuevo'.

    Reglas de asignacion de supervisor:
      - role=admin     → supervisor_id = NULL (admin no tiene supervisor jerarquico)
      - role=supervisor → supervisor_id = self (es el dueño del proceso)
      - role=asesor    → supervisor_id = supervisor del asesor en crm.equipos
                         (fallback NULL si no esta en ningun equipo)

    Devuelve:
      {ok: True, lead_id: int, lead_created: bool, lead_name: str}

    Atomico: todo en una transaccion. Si falla la creacion del lead, la
    conversacion no se actualiza.
    """
    from app.services.integrations.ingest_core import _resolve_fuente_id, clean_phone

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1) Leer datos de la conv (necesitamos wa_phone, contact_name)
            cur.execute(
                """
                SELECT id, wa_phone, contact_name, lead_id
                FROM crm.wa_conversations
                WHERE id = %s
                """,
                (conversation_id,),
            )
            conv = cur.fetchone()
            if not conv:
                raise ValueError(f"Conversacion {conversation_id} no existe")

            # Si ya tiene lead_id, no creamos otro — devolvemos el existente
            if conv["lead_id"]:
                cur.execute(
                    "SELECT nombres, apellidos FROM crm.leads WHERE id = %s",
                    (conv["lead_id"],),
                )
                lead = cur.fetchone() or {}
                lead_name = (
                    f"{lead.get('nombres') or ''} {lead.get('apellidos') or ''}".strip()
                    or f"Lead {conv['lead_id']}"
                )
                return {
                    "ok":           True,
                    "lead_id":      conv["lead_id"],
                    "lead_created": False,
                    "lead_name":    lead_name,
                }

            # 2) Normalizar telefono y datos
            wa_phone = conv["wa_phone"] or ""
            telefono = clean_phone(wa_phone) or wa_phone
            full_name = (conv["contact_name"] or "Lead WhatsApp").strip()
            parts = full_name.split(" ", 1)
            nombres = parts[0] or "Lead"
            apellidos = parts[1] if len(parts) > 1 else None

            # 3) Dedupe por telefono — IGNORA leads terminales para que un
            #    cliente que vuelve despues de Ganado/Perdido genere un caso
            #    nuevo. Solo bloqueamos si hay un lead activo no-terminal.
            cur.execute(
                """
                SELECT l.id, l.nombres, l.apellidos
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.telefono = %s
                  AND l.activo   = TRUE
                  AND COALESCE(e.nombre, '') <> ALL(%s)
                ORDER BY l.created_at DESC
                LIMIT 1
                """,
                (telefono, list(_TERMINAL_LEAD_STATES)),
            )
            existing = cur.fetchone()
            if existing:
                lead_id = existing["id"]
                lead_name = (
                    f"{existing['nombres'] or ''} {existing['apellidos'] or ''}".strip()
                    or f"Lead {lead_id}"
                )
                # Reasignar al taker via servicio (audit log + push)
                try:
                    from app.auth.schemas import TokenData
                    from app.services.assignments_service import (
                        reassign_one as svc_reassign_one,
                    )
                    fake_user = TokenData(
                        user_id=taker_user_id,
                        email="",
                        role=taker_role,
                    )
                    svc_reassign_one(
                        lead_id=lead_id,
                        new_asesor_id=taker_user_id,
                        current_user=fake_user,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "take.create_lead: reassign_one fallo lead=%s exc=%s "
                        "(continuamos con UPDATE directo)",
                        lead_id, exc,
                    )
                # Atar la conv al lead reasignado
                cur.execute(
                    """
                    UPDATE crm.wa_conversations
                    SET lead_id   = %s,
                        asesor_id = %s::uuid
                    WHERE id = %s
                    """,
                    (lead_id, taker_user_id, conversation_id),
                )
                conn.commit()
                logger.info(
                    "take.create_lead: conv=%s reuso lead existente id=%s "
                    "taker=%s (dedupe por telefono)",
                    conversation_id, lead_id, taker_user_id,
                )
                return {
                    "ok":           True,
                    "lead_id":      lead_id,
                    "lead_created": False,
                    "lead_name":    lead_name,
                }

            # 4) Crear lead nuevo asignado al taker
            fuente_id = _resolve_fuente_id(cur, "whatsapp")
            if not fuente_id:
                raise ValueError("Fuente 'whatsapp' no existe en crm.fuentes")

            cur.execute("SELECT id FROM crm.estados_lead WHERE nombre = 'Nuevo' LIMIT 1")
            estado_row = cur.fetchone()
            if not estado_row:
                raise ValueError("Estado 'Nuevo' no existe en crm.estados_lead")
            estado_id = estado_row["id"]

            # Resolver supervisor segun rol del taker
            supervisor_id = _resolve_supervisor_for_taker(cur, taker_user_id, taker_role)

            observaciones = (
                f"Lead creado al tomar el chat WhatsApp manualmente "
                f"(conv #{conversation_id}). Tomador: {taker_role}."
            )

            cur.execute(
                """
                INSERT INTO crm.leads
                    (nombres, apellidos, telefono, fuente_id, estado_id,
                     asesor_id, supervisor_id, observaciones, activo)
                VALUES (%s, %s, %s, %s, %s, %s::uuid,
                        CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                        %s, TRUE)
                RETURNING id
                """,
                (
                    nombres, apellidos, telefono, fuente_id, estado_id,
                    taker_user_id,
                    supervisor_id, supervisor_id,
                    observaciones,
                ),
            )
            lead_id = cur.fetchone()["id"]

            # 5) Atar la conv al lead nuevo
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET lead_id   = %s,
                    asesor_id = %s::uuid
                WHERE id = %s
                """,
                (lead_id, taker_user_id, conversation_id),
            )
            conn.commit()

            logger.info(
                "take.create_lead: conv=%s creo lead nuevo id=%s taker=%s rol=%s",
                conversation_id, lead_id, taker_user_id, taker_role,
            )

            # Push opcional al supervisor (no critico — best-effort)
            if supervisor_id and supervisor_id != taker_user_id:
                try:
                    # V070.91 — lead_id para deep-link al tap.
                    notify_new_lead(supervisor_id, full_name, "whatsapp", lead_id=lead_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("take.create_lead: notify push fallo: %s", exc)

            return {
                "ok":           True,
                "lead_id":      lead_id,
                "lead_created": True,
                "lead_name":    full_name,
            }


def _resolve_supervisor_for_taker(cur, user_id: str, role: str) -> Optional[str]:
    """Devuelve el supervisor_id que debe quedar en el lead segun el rol.

    - admin      → None
    - supervisor → self
    - asesor     → su supervisor en crm.equipos (None si no esta en ningun equipo)
    """
    if role == "admin":
        return None
    if role == "supervisor":
        return user_id
    # asesor
    cur.execute(
        """
        SELECT supervisor_id::text AS supervisor_id
        FROM crm.equipos
        WHERE asesor_id = %s::uuid AND activo = TRUE
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    return row["supervisor_id"] if row else None

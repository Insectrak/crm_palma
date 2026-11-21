"""
lead_recapture.py — Lead Re-engagement / Recapture (V048).

Patron patrón estándar 'Lead Recapture' / patrón estándar 'Re-engagement Workflow':
cuando un lead duplicado vuelve a entrar al CRM, el sistema:

  1. Registra el evento en crm.lead_recontactos (audit trail).
  2. Si el asesor original sigue activo (is_active=TRUE):
       - Mantiene el asesor (rapport > round-robin).
       - Le manda push: '{Cliente} volvio a interesarse via {fuente}'.
       - Si el lead estaba en estado terminal (Ganado/Perdido), lo
         deja igual + log; el asesor decide si reactivarlo.
  3. Si el asesor original ya no existe (is_active=FALSE):
       - Libera el lead → routing normal en el siguiente sprint.

PRINCIPIO DE DISENO:
  El asesor que invirtio tiempo en el lead NO se le quita por defecto.
  Solo se libera por razon operativa dura: el asesor ya no trabaja en
  la empresa.

FAIL-SAFE: si algo falla aqui, el caller cae al comportamiento legacy
(devolver duplicated:true sin recapture). Nunca bloqueamos la ingesta.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def handle_recontacto(
    cur,
    *,
    existing: dict,
    payload,
    telefono: str,
    email: Optional[str],
    nombres: str,
    apellidos: Optional[str],
    campana: Optional[str],
    fext: Optional[str],
) -> dict:
    """Procesa un lead duplicado entrante. Devuelve dict con la decision.

    El caller (ingest_core) hace commit. Aqui solo modificamos el cursor.
    """
    lead_id = existing["id"]
    asesor_id = existing.get("asesor_id")
    supervisor_id = existing.get("supervisor_id")
    estado_actual = existing.get("estado_nombre")
    lead_created_at = existing.get("created_at")

    # V068.4 — Backfill check: si el evento del proveedor (TikTok/Meta)
    # es ANTERIOR a la creacion del lead en el CRM, no es una reactivacion
    # — es backfill que el proveedor expuso tarde. Skip silencioso.
    external_created_at = getattr(payload, "external_created_at", None)
    if external_created_at is not None and lead_created_at is not None:
        try:
            if external_created_at <= lead_created_at:
                logger.info(
                    "[recapture] lead=%s evento backfill (ext_created=%s <= lead_created=%s) — skip",
                    lead_id, external_created_at, lead_created_at,
                )
                return {
                    "estrategia": "backfill_skip",
                    "asesor_id": asesor_id,
                    "asesor_inactivo": False,
                    "razon": "Evento del proveedor anterior a la creacion del lead — backfill, no reactivacion.",
                    "backfill_skip": True,
                }
        except TypeError:
            # Comparacion fallo (tz-aware vs naive); seguimos sin bloquear.
            pass

    # 1) Decidir estrategia
    estrategia, asesor_final, asesor_inactivo, razon = _decidir_estrategia(
        cur, asesor_id, supervisor_id,
    )

    # 2) Resolver fuente_id si vino en el payload
    fuente_id = _resolve_fuente_id(cur, getattr(payload, "fuente", None))
    api_client_id = _safe_uuid(getattr(payload, "api_client_id", None))

    # 3) Idempotency check (V052) — TikTok / n8n estaba reentregando el
    #    mismo lead 100+ veces, generando ruido. Patron CRMs profesionales:
    #    un evento de re-engagement por (lead, external_id). Si no hay
    #    external_id, cooldown de 24h por (lead, fuente).
    is_duplicate_event = _is_duplicate_recontacto_event(
        cur, lead_id=lead_id, fext=fext, fuente_id=fuente_id,
    )
    if is_duplicate_event:
        logger.info(
            "[recapture] lead=%s evento ya registrado (fext=%s fuente=%s) — skip insert",
            lead_id, fext, fuente_id,
        )
        return {
            "estrategia": estrategia,
            "asesor_id": asesor_final,
            "asesor_inactivo": asesor_inactivo,
            "razon": razon,
            "duplicate_event": True,
        }

    # V070.61 — INSERT robusto SIN dependencias de ON CONFLICT.
    #
    # Bug previo: usabamos ON CONFLICT (lead_id, fuente_externa_id)
    # WHERE fuente_externa_id IS NOT NULL DO NOTHING. PostgreSQL exige
    # que exista un partial unique index con EXACTAMENTE esa condicion
    # (uq_lead_recontactos_lead_fext de V052). Si la migracion V052 no
    # se aplico, el INSERT falla con "no unique constraint matching"
    # y el response decia 'insert_error: "0 | fallback: 0"' sin claridad
    # de que paso.
    #
    # Fix: SELECT antes del INSERT. Mas simple, mas robusto, no depende
    # de indices ni constraints. Patron clasico "check then write" con
    # SAVEPOINT para que cualquier error no rompa la tx principal.
    #
    # Detectamos al startup si la columna external_created_at existe via
    # ensure_lead_recontactos_external_created_at (bootstrap V070.60).
    # Si por algun motivo aun no existe (race condition en deploy), el
    # INSERT incluye un fallback adaptivo dentro del SAVEPOINT.
    recontacto_id = None
    insert_error = None
    try:
        # Check if record already exists (idempotency manual, sin ON CONFLICT).
        if fext:
            cur.execute(
                "SELECT id FROM crm.lead_recontactos "
                "WHERE lead_id = %s AND fuente_externa_id = %s LIMIT 1",
                (lead_id, fext),
            )
            existing_recontacto = cur.fetchone()
            if existing_recontacto:
                # V070.62 — cursor puede ser RealDictCursor (caller en
                # ingest_core.py usa ese). Soportamos ambos formatos.
                recontacto_id = (
                    existing_recontacto['id']
                    if isinstance(existing_recontacto, dict)
                    else existing_recontacto[0]
                )
                logger.info(
                    "[recapture] lead=%s fext=%s ya tenia recontacto_id=%s, no re-insertamos",
                    lead_id, fext, recontacto_id,
                )

        # V084 — Atribucion Meta-level del recontacto: anuncio, conjunto, form_id.
        # Si la DB todavia no tiene V084, el INSERT cae al fallback sin estos
        # campos (mismo patron que V068.4 con external_created_at).
        anuncio_in   = (getattr(payload, "anuncio", None) or "").strip() or None
        conjunto_in  = (getattr(payload, "conjunto", None) or "").strip() or None
        form_id_in   = (getattr(payload, "fuente_form_id", None) or "").strip() or None

        # Si no existe, intentar insertar con SAVEPOINT por seguridad.
        if recontacto_id is None:
            cur.execute("SAVEPOINT sp_recontacto")
            try:
                cur.execute(
                    """
                    INSERT INTO crm.lead_recontactos
                        (lead_id, fuente_id, api_client_id, campana, fuente_externa_id,
                         asesor_mantenido, asesor_anterior,
                         estrategia, estado_lead_anterior, razon,
                         external_created_at,
                         anuncio, conjunto, fuente_form_id)
                    VALUES (%s, %s, %s::uuid, %s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s,
                            %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        lead_id, fuente_id, api_client_id, campana, fext,
                        asesor_final, asesor_id,
                        estrategia, estado_actual, razon,
                        external_created_at,
                        anuncio_in, conjunto_in, form_id_in,
                    ),
                )
                row = cur.fetchone()
                recontacto_id = (row['id'] if isinstance(row, dict) else row[0]) if row else None
                cur.execute("RELEASE SAVEPOINT sp_recontacto")
                logger.info(
                    "[recapture] lead=%s insertado recontacto_id=%s (con meta-level attribution)",
                    lead_id, recontacto_id,
                )
            except Exception as exc:  # noqa: BLE001
                # ROLLBACK al savepoint para rescatar la tx principal.
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_recontacto")
                except Exception:  # noqa: BLE001
                    pass
                # repr() incluye tipo y args — mucho mas util que str() solo.
                err_repr = f"{type(exc).__name__}: {exc!s} (args={exc.args!r})"
                logger.warning(
                    "[recapture] INSERT con meta-level attribution fallo (lead=%s fext=%s): %s",
                    lead_id, fext, err_repr, exc_info=True,
                )
                insert_error = err_repr

                # Fallback: reintentar SIN external_created_at ni meta fields
                # (DB sin V068.4 o sin V084).
                cur.execute("SAVEPOINT sp_recontacto_fb")
                try:
                    cur.execute(
                        """
                        INSERT INTO crm.lead_recontactos
                            (lead_id, fuente_id, api_client_id, campana, fuente_externa_id,
                             asesor_mantenido, asesor_anterior,
                             estrategia, estado_lead_anterior, razon)
                        VALUES (%s, %s, %s::uuid, %s, %s, %s::uuid, %s::uuid, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            lead_id, fuente_id, api_client_id, campana, fext,
                            asesor_final, asesor_id,
                            estrategia, estado_actual, razon,
                        ),
                    )
                    row = cur.fetchone()
                    recontacto_id = (row['id'] if isinstance(row, dict) else row[0]) if row else None
                    cur.execute("RELEASE SAVEPOINT sp_recontacto_fb")
                    if recontacto_id:
                        insert_error = None  # fallback success
                        logger.info(
                            "[recapture] lead=%s insertado via fallback recontacto_id=%s",
                            lead_id, recontacto_id,
                        )
                except Exception as exc2:  # noqa: BLE001
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT sp_recontacto_fb")
                    except Exception:  # noqa: BLE001
                        pass
                    err2_repr = f"{type(exc2).__name__}: {exc2!s} (args={exc2.args!r})"
                    logger.error(
                        "[recapture] INSERT fallback TAMBIEN fallo (lead=%s): %s",
                        lead_id, err2_repr, exc_info=True,
                    )
                    insert_error = f"{insert_error} | fallback: {err2_repr}"
    except Exception as outer_exc:  # noqa: BLE001
        logger.error(
            "[recapture] SAVEPOINT/SELECT setup fallo (lead=%s): %s",
            lead_id, outer_exc, exc_info=True,
        )
        if insert_error is None:
            insert_error = f"setup: {type(outer_exc).__name__}: {outer_exc!s}"

    # 3.5) V096.5 — Write-through cache de campana/form que vino en el
    # payload del recontacto. Antes solo lo hacia ingest_core para leads
    # NUEVOS; los recontactos guardaban los IDs en lead_recontactos pero
    # nunca hidrataban meta_catalog_cache. Resultado: el panel Re-engagement
    # y el bloque `recontacto` del webhook devolvian solo IDs crudos en
    # lugar de los nombres legibles que el proveedor envio en el payload.
    # Best-effort: el helper silencia errores.
    if recontacto_id is not None:
        try:
            from app.services.integrations.meta_catalog import hydrate_from_provider
            hydrate_from_provider(
                cur, entity_type="campaign",
                entity_id=str(campana).strip() if campana else None,
                name=getattr(payload, "campaign_name", None),
            )
            hydrate_from_provider(
                cur, entity_type="form",
                entity_id=form_id_in,
                name=getattr(payload, "form_name", None),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[recapture] cache hydration fallo (lead=%s recontacto=%s)",
                lead_id, recontacto_id,
            )

    # 4) Si liberamos por inactivo, dejamos el asesor en NULL para que
    #    el siguiente flow de asignacion decida (router actual).
    if estrategia == "liberar_inactivo":
        try:
            cur.execute(
                "UPDATE crm.leads SET asesor_id = NULL WHERE id = %s",
                (lead_id,),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("lead_recapture: no se pudo liberar lead %s: %s", lead_id, exc)

    # 5) Rellenar campos vacios sin sobrescribir (B en la postura).
    # V086.1 — extendido con dni/ciudad/trabajo/resumen_ia del payload del
    # proveedor. Los campos que no llegan en el payload o que el lead ya
    # tiene poblados se ignoran (patrón conservador).
    _fill_empty_fields(
        cur, lead_id, existing,
        nombres=nombres, apellidos=apellidos, email=email,
        dni=getattr(payload, "dni", None),
        ciudad=getattr(payload, "ciudad", None),
        trabajo=getattr(payload, "trabajo", None),
        resumen_ia=getattr(payload, "resumen_ia", None),
    )

    # 5.5) V093 — marcar metadata del recontacto en crm.leads.
    # Antes de V093 `es_recontacto` solo se actualizaba via maintenance job
    # del bootstrap (delay de hasta 24h) y `fecha_ultimo_recontacto` no
    # existia. Ahora cada handle_recontacto que registro un evento
    # exitoso (recontacto_id no None, sea via insert normal o via fallback)
    # actualiza ambos campos en el momento, asi la UI los puede mostrar
    # de inmediato. Idempotente: si el lead ya estaba marcado, lo
    # re-marca con la fecha mas reciente.
    if recontacto_id is not None:
        try:
            cur.execute(
                """
                UPDATE crm.leads
                SET es_recontacto = TRUE,
                    fecha_ultimo_recontacto = NOW()
                WHERE id = %s
                """,
                (lead_id,),
            )
        except Exception as exc:  # noqa: BLE001
            # Best-effort: si la columna fecha_ultimo_recontacto no existe
            # (race condition durante deploy de V093), reintentamos solo
            # con es_recontacto para no perder esa parte.
            logger.warning(
                "[recapture] no se pudo actualizar fecha_ultimo_recontacto lead=%s: %s — fallback solo es_recontacto",
                lead_id, exc,
            )
            try:
                cur.execute(
                    "UPDATE crm.leads SET es_recontacto = TRUE WHERE id = %s",
                    (lead_id,),
                )
            except Exception:  # noqa: BLE001
                pass  # no bloqueamos el flow por metadata

    # 6) Push notification al asesor mantenido (si aplica)
    notificado = False
    if estrategia == "mantener_asesor" and asesor_final:
        notificado = _send_push_recontacto(
            cur, lead_id=lead_id, asesor_id=asesor_final,
            nombres=nombres, apellidos=apellidos,
            fuente=getattr(payload, "fuente", None) or "otra fuente",
            campana=campana,
        )
        if notificado:
            try:
                cur.execute(
                    """
                    UPDATE crm.lead_recontactos
                    SET notificado = TRUE, notificacion_enviada_at = NOW()
                    WHERE lead_id = %s AND created_at = (
                        SELECT MAX(created_at) FROM crm.lead_recontactos WHERE lead_id = %s
                    )
                    """,
                    (lead_id, lead_id),
                )
            except Exception:  # noqa: BLE001
                pass

    logger.info(
        "[recapture] lead=%s estrategia=%s asesor_final=%s notificado=%s recontacto_id=%s insert_error=%s",
        lead_id, estrategia, asesor_final, notificado, recontacto_id, insert_error,
    )

    # V070.59 — Devolvemos recontacto_id e insert_error para que el caller
    # sepa si REALMENTE se persistio el recontacto o solo se proceso a medias.
    return {
        "estrategia": estrategia,
        "asesor_id": asesor_final,
        "asesor_inactivo": asesor_inactivo,
        "razon": razon,
        "recontacto_id": recontacto_id,
        "insert_error": insert_error,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────

def _is_duplicate_recontacto_event(cur, *, lead_id, fext, fuente_id):
    """Idempotency check (V068).

    Devuelve True si este recontacto ya fue registrado y NO debe insertarse
    de nuevo. Reglas en orden de precedencia:

      1) (lead, fext) ya registrado → MISMO evento literal. Skip.
         Cubre retries inmediatos del mismo webhook/poll.

      2) **REGLA PRINCIPAL V068**: ya hay un recontacto para (lead, fuente_id)
         en el dia comercial actual (America/Lima) → skip.
         Reemplaza al cooldown 24h-rolling de V052 que NO bloqueaba leads
         re-importados diariamente por un cron/poll automatico cuando las
         horas variaban levemente entre dias (>24h pero <48h apart).

         Business rule: 1 cliente reactivandose multiples veces el mismo dia
         = 1 evento. 1 cron diario re-importando el mismo lead = 0 eventos
         despues del primer dia (porque no son reactivaciones reales).
    """
    try:
        if fext:
            cur.execute(
                """
                SELECT 1 FROM crm.lead_recontactos
                WHERE lead_id = %s AND fuente_externa_id = %s
                LIMIT 1
                """,
                (lead_id, fext),
            )
            if cur.fetchone() is not None:
                return True

        # V068: dedup por (lead, fuente, dia_comercial_lima).
        # AT TIME ZONE 'America/Lima' refleja la fecha de negocio peruana,
        # no UTC (sin esto, eventos a las 19:00 PE se cuentan como dia
        # siguiente). Si el indice idx_lead_recontactos_lead_fuente_day
        # esta presente (V068 aplicado), este lookup es O(log n).
        cur.execute(
            """
            SELECT 1 FROM crm.lead_recontactos
            WHERE lead_id = %s
              AND COALESCE(fuente_id, -1) = COALESCE(%s, -1)
              AND DATE(created_at AT TIME ZONE 'America/Lima')
                  = DATE(NOW() AT TIME ZONE 'America/Lima')
            LIMIT 1
            """,
            (lead_id, fuente_id),
        )
        return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        # Si falla el check, dejamos pasar (best-effort). Peor caso: inserta
        # un duplicado que el caller upstream filtrara.
        logger.debug("_is_duplicate_recontacto_event fallo: %s", exc)
        return False


def _decidir_estrategia(cur, asesor_id, supervisor_id):
    """Aplica el principio: el asesor mantiene su lead salvo que ya no
    exista operativamente. Devuelve (estrategia, asesor_final, asesor_inactivo, razon).
    """
    if not asesor_id:
        return ("sin_asesor_original", None, False,
                "El lead no tenia asesor asignado — se aplica routing normal.")

    cur.execute(
        "SELECT id, is_active FROM auth.users WHERE id = %s::uuid",
        (asesor_id,),
    )
    row = cur.fetchone()
    if not row:
        return ("liberar_inactivo", None, True,
                "El asesor original ya no existe en el sistema.")
    is_active = row.get("is_active") if isinstance(row, dict) else row[1]
    if not is_active:
        return ("liberar_inactivo", None, True,
                "El asesor original esta inactivo (is_active=FALSE).")

    # Caso default: mantener al asesor.
    return ("mantener_asesor", str(asesor_id), False,
            "Se mantiene al asesor original — rapport preservado.")


_CANONICAL_FUENTES = {
    "tiktok": "TikTok", "tt": "TikTok", "tt mensaje": "TikTok",
    "facebook": "Facebook", "fb": "Facebook", "meta": "Facebook",
    "instagram": "Instagram", "ig": "Instagram",
    "whatsapp": "WhatsApp", "wa": "WhatsApp", "wa mensaje": "WhatsApp",
    "web": "Web", "referido": "Referido", "manual": "Manual",
    "historico": "Historico", "histórico": "Historico",
}


def _resolve_fuente_id(cur, fuente_str):
    if not fuente_str:
        return None
    key = str(fuente_str).strip().lower()
    canonical = _CANONICAL_FUENTES.get(key, key.capitalize())
    try:
        cur.execute(
            "SELECT id FROM crm.fuentes WHERE LOWER(nombre) = LOWER(%s) OR LOWER(nombre) = LOWER(%s) ORDER BY id ASC LIMIT 1",
            (canonical, key),
        )
        row = cur.fetchone()
        if row:
            return row["id"] if isinstance(row, dict) else row[0]
        cur.execute(
            "INSERT INTO crm.fuentes (nombre, activo) VALUES (%s, TRUE) ON CONFLICT (nombre) DO UPDATE SET activo = TRUE RETURNING id",
            (canonical,),
        )
        created = cur.fetchone()
        if created:
            return created["id"] if isinstance(created, dict) else created[0]
    except Exception:  # noqa: BLE001
        return None
    return None


def _safe_uuid(value):
    if not value:
        return None
    s = str(value).strip()
    return s if len(s) >= 32 else None


def _fill_empty_fields(
    cur, lead_id, existing,
    *, nombres, apellidos, email,
    dni=None, ciudad=None, trabajo=None, resumen_ia=None,
):
    """Solo rellena campos vacios. Nunca sobrescribe info existente.

    V086.1 (2026-06-18) — Extendido para enriquecer leads viejos con
    datos que el proveedor (ej. wedo) trae en el recontacto: DNI,
    ciudad, trabajo, resumen_ia. El criterio es siempre el mismo:
    solo se actualiza si el campo del lead está vacío. Si un asesor
    humano ya completó alguno de esos campos, se respeta y el dato
    del proveedor se descarta silenciosamente — patrón conservador
    "no pisar info trabajada por humanos".

    Caso de uso: wedo manda un POST con teléfono de un lead viejo +
    DNI 12345678. El lead lo tenía NULL. Tras el recontacto, el lead
    queda con DNI poblado y el asesor lo ve al abrirlo.
    """
    sets = []
    params = []
    if email and not (existing.get("email") or "").strip():
        sets.append("email = %s")
        params.append(email)
    if nombres and (existing.get("nombres") or "").strip().lower() in ("", "sin nombre"):
        sets.append("nombres = %s")
        params.append(nombres)
    if apellidos and not (existing.get("apellidos") or "").strip():
        sets.append("apellidos = %s")
        params.append(apellidos)
    # V086.1 — Enriquecimiento de campos del proveedor IA.
    if dni and not (existing.get("dni") or "").strip():
        sets.append("dni = %s")
        params.append(dni)
    if ciudad and not (existing.get("ciudad") or "").strip():
        sets.append("ciudad = %s")
        params.append(ciudad)
    if trabajo and not (existing.get("trabajo") or "").strip():
        sets.append("trabajo = %s")
        params.append(trabajo)
    if resumen_ia and not (existing.get("resumen_ia") or "").strip():
        sets.append("resumen_ia = %s")
        params.append(resumen_ia)
    if not sets:
        return
    params.append(lead_id)
    try:
        cur.execute(
            f"UPDATE crm.leads SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s",
            params,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("lead_recapture _fill_empty_fields fallo: %s", exc)


def _send_push_recontacto(cur, *, lead_id, asesor_id, nombres, apellidos,
                          fuente, campana):
    """Envia push al asesor con mensaje contextual del re-engagement.
    Best-effort: si falla, devuelve False y la ingesta sigue."""
    try:
        from app.services.notification_service import notify_lead_recontacto
        nombre_completo = " ".join(filter(None, [nombres, apellidos])) or "Un lead"
        notify_lead_recontacto(
            asesor_id, lead_id, nombre_completo, fuente, campana,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("notify_lead_recontacto fallo: %s", exc)
        return False

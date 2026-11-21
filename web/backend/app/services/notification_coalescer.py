"""Coalescer de push notifications lead_created (V075).

Problema:
    Cuando entra un batch de leads (Postman bulk, dia intenso de Meta,
    redistribucion masiva), el asesor recibe N push individuales con
    sonido cada una. UX horrible y patron anti-CRM. Drena bateria.

Solucion (patron premium/correo profesional/patrón premium):
    notify_new_lead encola en crm.notification_buffer en vez de mandar
    push inmediato. Un worker corre cada FLUSH_INTERVAL_SEC y decide:
      - <BATCH_THRESHOLD leads pendientes para un asesor → push individual
      - >=BATCH_THRESHOLD pendientes → 1 push agregada
        "Tienes 5 leads nuevos asignados (3 Facebook · 2 Instagram)"
    Solo se flushean filas con enqueued_at < NOW() - WAIT_WINDOW_SEC.

Excepciones (bypass del buffer):
    - Leads marcados CALIENTE → push inmediato (velocidad importa)
    - Si lead_id es None (caso raro) → push inmediato (no podemos
      buffearlo bien sin id para deep-link)

Multi-worker safety:
    El flush corre solo en el worker lider (mismo advisory lock que
    integrations/scheduler.py). El enqueue es seguro multi-worker
    porque la tabla tiene UNIQUE parcial (asesor_id, lead_id) WHERE
    sent_at IS NULL.

API publica:
    - enqueue(asesor_id, lead_id, lead_name, fuente, performed_by) -> bool
    - flush_due() -> dict con stats — llamado por scheduler
    - notify_immediate(...) -> bool — usado por el bypass CALIENTE
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)

# Si llegan >= este numero de leads pendientes para un asesor, el flush
# manda 1 push agregada en vez de N individuales.
BATCH_THRESHOLD = 3

# Cuanto esperar antes de flushear un lead encolado. Da margen para que
# el burst termine antes de decidir individual vs batch. 30s da una
# ventana razonable; el asesor ve el push 30s despues del primer lead
# del batch (patrón premium/correo profesional usan ventanas similares: 15-60s).
WAIT_WINDOW_SEC = 30


# ── Helpers ───────────────────────────────────────────────────────────────

def _fetch_calidad(lead_id: int) -> Optional[str]:
    """Lee crm.leads.calidad para decidir bypass CALIENTE.

    Best-effort: si falla, devuelve None y el caller no bypassea.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT calidad FROM crm.leads WHERE id = %s LIMIT 1",
                    (lead_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("coalescer: fetch_calidad(%s) fallo: %s", lead_id, exc)
        return None


# ── API publica: enqueue + bypass inmediato ──────────────────────────────

def enqueue(
    *,
    asesor_id: str,
    lead_id: Optional[int],
    lead_name: str,
    fuente: str = "",
    performed_by: Optional[str] = None,
    calidad: Optional[str] = None,
) -> bool:
    """Encola el lead en el buffer. Si es CALIENTE o no tiene lead_id,
    bypassea y manda push inmediata.

    Devuelve True si el lead quedo encolado o si la push inmediata se
    envio. False en errores. Best-effort: nunca levanta.
    """
    if not asesor_id:
        return False

    # CALIENTE bypass — velocidad importa mas que silencio.
    # Si el caller no paso calidad explicita, la buscamos en DB.
    calidad_effective = calidad
    if calidad_effective is None and lead_id is not None:
        calidad_effective = _fetch_calidad(lead_id)

    is_caliente = (calidad_effective or "").upper() == "CALIENTE"
    if is_caliente or lead_id is None:
        return notify_immediate(
            asesor_id=asesor_id,
            lead_id=lead_id,
            lead_name=lead_name,
            fuente=fuente,
            performed_by=performed_by,
        )

    # Encolar en el buffer. UNIQUE parcial evita doble-encolado.
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm.notification_buffer
                        (asesor_id, lead_id, lead_name, fuente, performed_by)
                    VALUES (%s::uuid, %s, %s, %s, %s)
                    ON CONFLICT (asesor_id, lead_id) WHERE sent_at IS NULL
                        DO NOTHING
                    """,
                    (asesor_id, lead_id, lead_name or "", fuente or "",
                     performed_by),
                )
            conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        # Fallback: si la tabla no existe (migracion no aplicada) o falla
        # cualquier otra cosa, mandamos push inmediato. Mejor 50 pushes
        # que 0 pushes.
        logger.warning(
            "coalescer: enqueue fallo (lead=%s asesor=%s), fallback inmediato: %s",
            lead_id, asesor_id, exc,
        )
        return notify_immediate(
            asesor_id=asesor_id,
            lead_id=lead_id,
            lead_name=lead_name,
            fuente=fuente,
            performed_by=performed_by,
        )


def notify_immediate(
    *,
    asesor_id: str,
    lead_id: Optional[int],
    lead_name: str,
    fuente: str = "",
    performed_by: Optional[str] = None,
) -> bool:
    """Bypass del coalescer. Manda push individual instantanea.

    Usado por:
      - El bypass CALIENTE en enqueue()
      - El fallback de error si la DB falla
      - notify_new_lead cuando el caller pide explicitamente immediate=True
        (no implementado todavia, queda como hook futuro)
    """
    # Import diferido para evitar ciclo: notification_service ya importa
    # este modulo desde sus wrappers.
    from app.services import notification_service

    data = {"type": "lead_created"}
    if lead_id is not None:
        data["lead_id"] = str(lead_id)
    return notification_service.notify(
        "lead_created", asesor_id,
        {"lead_name": lead_name or "", "fuente": fuente or ""},
        data=data, performed_by=performed_by,
    )


# ── Flush worker (llamado por scheduler.py cada 15s) ─────────────────────

def flush_due() -> dict:
    """Procesa el buffer: por cada asesor con pendientes, decide individual
    o batch y envia. Solo flushea filas con enqueued_at < NOW() - WAIT_WINDOW.

    Devuelve stats: {asesores_procesados, pushes_individuales, pushes_batch,
    leads_flusheados}.

    Idempotente: marca sent_at = NOW() al enviar, asi el proximo ciclo no
    los reprocesa. Si el push falla, sent_at queda NULL y se reintenta en
    el proximo flush (lo cual es OK — best-effort, no perdemos info).
    """
    stats = {
        "asesores_procesados": 0,
        "pushes_individuales": 0,
        "pushes_batch":        0,
        "leads_flusheados":    0,
    }

    try:
        with get_db() as conn:
            # ── 1. Agrupar pendientes por asesor ──────────────────────────
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        asesor_id,
                        ARRAY_AGG(id ORDER BY enqueued_at)         AS row_ids,
                        ARRAY_AGG(lead_id ORDER BY enqueued_at)    AS lead_ids,
                        ARRAY_AGG(lead_name ORDER BY enqueued_at)  AS lead_names,
                        ARRAY_AGG(fuente ORDER BY enqueued_at)     AS fuentes,
                        ARRAY_AGG(performed_by ORDER BY enqueued_at) AS performed_bys,
                        COUNT(*)::int                              AS total
                    FROM crm.notification_buffer
                    WHERE sent_at IS NULL
                      AND enqueued_at < NOW() - (%s || ' seconds')::interval
                    GROUP BY asesor_id
                    """,
                    (str(WAIT_WINDOW_SEC),),
                )
                groups = cur.fetchall() or []

            if not groups:
                return stats

            # ── 2. Procesar cada grupo (asesor) ──────────────────────────
            for g in groups:
                asesor_id = str(g["asesor_id"])
                row_ids: list[int] = list(g["row_ids"] or [])
                lead_ids: list[int] = list(g["lead_ids"] or [])
                lead_names: list[str] = list(g["lead_names"] or [])
                fuentes: list[str] = list(g["fuentes"] or [])
                performed_bys = list(g["performed_bys"] or [])
                total = int(g["total"] or 0)

                if total == 0:
                    continue

                stats["asesores_procesados"] += 1
                batch_id = uuid.uuid4()

                if total < BATCH_THRESHOLD:
                    # ── Modo individual: 1 push por lead ──────────────
                    sent_row_ids: list[int] = []
                    for i, lead_id in enumerate(lead_ids):
                        ok = notify_immediate(
                            asesor_id=asesor_id,
                            lead_id=lead_id,
                            lead_name=lead_names[i] if i < len(lead_names) else "",
                            fuente=fuentes[i] if i < len(fuentes) else "",
                            performed_by=performed_bys[i] if i < len(performed_bys) else None,
                        )
                        if ok:
                            sent_row_ids.append(row_ids[i])
                            stats["pushes_individuales"] += 1
                    _mark_sent(conn, sent_row_ids, batch_id, "individual")
                    stats["leads_flusheados"] += len(sent_row_ids)

                else:
                    # ── Modo batch: 1 push agregada ──────────────────
                    breakdown = _format_fuente_breakdown(fuentes)
                    ok = _send_batch_push(
                        asesor_id=asesor_id,
                        count=total,
                        breakdown=breakdown,
                        lead_ids=lead_ids,
                    )
                    if ok:
                        _mark_sent(conn, row_ids, batch_id, "batch")
                        stats["pushes_batch"] += 1
                        stats["leads_flusheados"] += len(row_ids)

            conn.commit()
        return stats

    except Exception as exc:  # noqa: BLE001
        logger.exception("coalescer: flush_due fallo: %s", exc)
        return stats


def _mark_sent(conn, row_ids: list[int], batch_id: uuid.UUID, send_mode: str) -> None:
    """Marca filas como enviadas. Misma conn = misma transaccion."""
    if not row_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE crm.notification_buffer
            SET sent_at   = NOW(),
                batch_id  = %s::uuid,
                send_mode = %s
            WHERE id = ANY(%s::bigint[])
              AND sent_at IS NULL
            """,
            (str(batch_id), send_mode, row_ids),
        )


def _format_fuente_breakdown(fuentes: list[str]) -> str:
    """De ['facebook','instagram','facebook','tiktok','facebook'] devuelve
    '3 facebook · 1 instagram · 1 tiktok' (ordenado por frecuencia DESC,
    nombre ASC para tie-break estable). Solo top 3 para no saturar el body."""
    from collections import Counter
    counts = Counter((f or "").strip().lower() or "otra" for f in fuentes)
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    parts = [f"{c} {name.capitalize()}" for name, c in items]
    return " · ".join(parts)


def _send_batch_push(
    *, asesor_id: str, count: int, breakdown: str, lead_ids: list[int],
) -> bool:
    """Envia la push agregada usando el template 'leads_batch'.

    El payload `data` lleva type='lead_batch' (sin id, abre lista Leads
    filtrada) + lead_ids[] para que el mobile pueda hacer prefetch.
    """
    from app.services import notification_service

    data = {
        "type":  "lead_batch",
        "count": str(count),
        # Limit lead_ids serializados para no exceder limites FCM (~4KB).
        # 20 ids como tope razonable; el mobile siempre puede hacer fetch.
        "lead_ids": ",".join(str(lid) for lid in lead_ids[:20]),
    }
    return notification_service.notify(
        "leads_batch", asesor_id,
        {"count": str(count), "breakdown": breakdown},
        data=data,
    )

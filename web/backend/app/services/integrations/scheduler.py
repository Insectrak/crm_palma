"""Scheduler asincrónico para pollers de integraciones.

Diseño:
  - Una sola tarea asyncio por tipo de poller (TikTok por ahora).
  - Arranca en FastAPI lifespan y se cancela limpiamente al apagar.
  - Si no hay credenciales registradas aún, la tarea sigue viva pero no
    hace trabajo — así la UI puede añadir advertisers sin reiniciar el
    proceso.
  - Cada ciclo lee la lista de advertisers vigente y corre `poll_advertiser`
    para cada uno en un thread (porque ingest_lead_core es sync).

Leader election (multi-worker):
  - Uvicorn se despliega con `--workers 2`, así que cada proceso arranca
    su propio scheduler. Sin coordinación, ambos workers pollearían el
    mismo advertiser → doble quota + race en `integrations_checkpoint`.
  - Solución: `pg_try_advisory_lock(_LEADER_LOCK_KEY)` en una conexión
    dedicada (fuera del pool, para que la sesión viva tanto como el
    proceso). Solo el worker que obtiene el lock corre el ciclo; los
    demás quedan en modo standby, reintentando cada IDLE_SLEEP.
  - Si el líder muere, su sesión de Postgres termina → el lock se libera
    automáticamente y otro worker lo toma en el siguiente tick. Auto-
    recuperación sin supervisor externo.

Clean Code / SOLID:
  - SRP: acá vive solo el "cuándo y con qué cadencia". El "qué hacer" está
    en `tiktok_service.poll_advertiser`.
  - Observabilidad: arranque / parada / ciclos / cambios de liderazgo se
    loggean sin ruido.
  - Apagado cooperativo: espera a terminar el ciclo actual antes de cerrar.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import psycopg2

from app.config import settings

logger = logging.getLogger(__name__)

_tiktok_task: Optional[asyncio.Task] = None
_assignment_task: Optional[asyncio.Task] = None
_webhook_task: Optional[asyncio.Task] = None
_notif_coalescer_task: Optional[asyncio.Task] = None
_sla_task: Optional[asyncio.Task] = None

# Cada cuánto corre el procesador de la cola de auto-asignación.
# 15 min es razonable: balance entre latencia y carga. Si gerencia pide
# más rápido, bajar a 5 min sin problemas.
_ASSIGNMENT_QUEUE_INTERVAL_SEC = 15 * 60

# V103: Cada cuánto corre el chequeo de SLA (15 min y 24 horas).
# 60s garantiza alerta oportuna al superar 15 min.
_SLA_CHECK_INTERVAL_SEC = 60

# V058: Cada cuánto corre el procesador de webhook deliveries.
# 60s es razonable: balance entre latencia (proveedor recibe rapido) y
# carga de DB. El primer attempt sale casi inmediato (status=pending,
# next_retry_at = NOW() en el insert).
_WEBHOOK_QUEUE_INTERVAL_SEC = 60

# V075: Cada cuanto corre el flush del coalescer de push notifications.
# 15s da granularidad fina pero sin saturar la DB. La ventana de
# coalescing es 30s (WAIT_WINDOW_SEC en notification_coalescer.py),
# asi que con 15s de tick una nueva push entra al buffer y sale 30-45s
# despues — latencia aceptable para el usuario y consolidacion efectiva.
_NOTIF_COALESCER_INTERVAL_SEC = 15

# Cuando no hay advertisers configurados, usamos este intervalo para
# evaluar el estado; evita busy-loop y permite detectar nuevas cuentas
# sin reiniciar el servidor.
_IDLE_SLEEP_SEC = 60

# Clave del advisory lock de Postgres que designa al worker "líder" del
# scheduler. Es un int64 arbitrario pero estable — cambiar este valor
# rompería la coordinación entre workers en un deploy rolling, así que
# no tocarlo salvo migración planificada.
_LEADER_LOCK_KEY = 873_241_501

# Conexión dedicada (NO del pool) que sostiene el advisory lock mientras
# el proceso es líder. Si la ponemos en el pool, vuelve a estar libre en
# el siguiente get_db() y el lock se libera — anulando la elección.
_leader_conn: Optional[psycopg2.extensions.connection] = None


def _is_leader_conn_healthy() -> bool:
    if _leader_conn is None:
        return False
    try:
        with _leader_conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


def _try_become_leader() -> bool:
    """Intenta adquirir el advisory lock. True si este worker es líder.

    Idempotente: si ya somos líder y la conexión sigue viva, no hace nada.
    Si la conexión murió, la descarta y reintenta.
    """
    global _leader_conn

    if _leader_conn is not None:
        if _is_leader_conn_healthy():
            return True
        # Conexión perdida — descartar y reintentar.
        try:
            _leader_conn.close()
        except Exception:  # noqa: BLE001
            pass
        _leader_conn = None

    try:
        conn = psycopg2.connect(settings.database_url)
        conn.autocommit = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduler: no se pudo abrir conexión leader: %s", exc)
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_LEADER_LOCK_KEY,))
            got = bool(cur.fetchone()[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduler: fallo al intentar advisory lock: %s", exc)
        conn.close()
        return False

    if not got:
        conn.close()
        return False

    _leader_conn = conn
    logger.info("scheduler: este worker tomó el liderazgo (advisory lock ok).")
    return True


def _release_leader_lock() -> None:
    """Libera la conexión dedicada (y con ella el advisory lock)."""
    global _leader_conn
    if _leader_conn is None:
        return
    try:
        _leader_conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduler: error cerrando conexión leader: %s", exc)
    _leader_conn = None
    logger.info("scheduler: liderazgo liberado.")


async def _run_tiktok_poll_cycle() -> None:
    """Corre una corrida para cada advertiser configurado en paralelo
    acotado (cada `poll_advertiser` en su propio to_thread)."""
    from app.services.integrations import tiktok_service

    try:
        advertisers = tiktok_service.list_configured_advertisers()
    except Exception as exc:  # noqa: BLE001
        logger.exception("scheduler tiktok: fallo listando advertisers: %s", exc)
        return

    if not advertisers:
        return

    tasks = [
        asyncio.to_thread(tiktok_service.poll_advertiser, adv)
        for adv in advertisers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for adv, res in zip(advertisers, results):
        if isinstance(res, Exception):
            logger.exception("scheduler tiktok: advertiser=%s exc=%s", adv, res)
        else:
            logger.info("scheduler tiktok: advertiser=%s result=%s", adv, res)


async def _tiktok_loop() -> None:
    """Loop principal del poller de TikTok. Solo corre trabajo efectivo
    cuando este proceso es líder (advisory lock); si no, espera IDLE y
    reintenta — así si el líder muere otro worker toma el relevo."""
    from app.services.integrations import tiktok_service

    logger.info("scheduler tiktok: loop iniciado.")
    try:
        while True:
            is_leader = await asyncio.to_thread(_try_become_leader)

            if is_leader:
                try:
                    await _run_tiktok_poll_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("scheduler tiktok: error en ciclo: %s", exc)

                # Determinar cuánto dormir — si no hay advertisers, usa IDLE.
                try:
                    advertisers = tiktok_service.list_configured_advertisers()
                except Exception:  # noqa: BLE001
                    advertisers = []

                if not advertisers:
                    sleep_sec = _IDLE_SLEEP_SEC
                else:
                    try:
                        sleep_sec = tiktok_service.get_polling_interval_minutes() * 60
                    except Exception:  # noqa: BLE001
                        sleep_sec = 600  # 10 min fallback
            else:
                # Standby: otro worker es líder. Dormimos IDLE y reintentamos.
                sleep_sec = _IDLE_SLEEP_SEC

            await asyncio.sleep(sleep_sec)
    except asyncio.CancelledError:
        logger.info("scheduler tiktok: loop cancelado, saliendo limpiamente.")
        raise


# ─── Loop: cola de auto-asignacion (V047) ──────────────────────────────────

async def _run_assignment_queue_cycle() -> None:
    """Procesa la cola crm.assignment_pending. Best-effort: si la tabla no
    existe (migracion V047 no aplicada), el motor lo maneja silenciosamente.

    V075.1 — Despues del commit, dispara push notifications a los asesores
    que recibieron leads desde la cola. Antes de V075.1, la cola asignaba
    leads pero NUNCA notificaba al asesor — bug pre-existente que dejaba
    a los asesores ciegos de leads asignados via reintento (caso comun
    cuando todos los asesores estan ocupados al momento de la ingesta).

    Las pushes se envian DESPUES del commit (no dentro): si la DB falla
    el commit, no spammeamos a alguien con un lead que no quedo asignado.
    """
    def _do_cycle():
        from app.database import get_db
        from app.services import lead_routing
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    stats = lead_routing.process_pending_queue(cur)
                conn.commit()
            return stats
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler assignment-queue: error en ciclo: %s", exc)
            return None

    stats = await asyncio.to_thread(_do_cycle)
    if not stats:
        return

    # V075.1 — Disparar pushes POST-COMMIT. Best-effort por push: una
    # falla no bloquea a las siguientes. El coalescer (V075) agrupa si
    # un mismo asesor recibe >=3 leads en este tick.
    pushes = stats.get("pushes_pendientes") or []
    if pushes:
        def _send_all_pushes():
            from app.services.notification_service import notify_new_lead
            sent = 0
            for p in pushes:
                try:
                    notify_new_lead(
                        p["asesor_id"], p["lead_name"], p.get("fuente") or "",
                        lead_id=p.get("lead_id"),
                    )
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "scheduler assignment-queue: push fallido lead=%s asesor=%s: %s",
                        p.get("lead_id"), p.get("asesor_id"), exc,
                    )
            return sent

        sent = await asyncio.to_thread(_send_all_pushes)
        logger.info(
            "scheduler assignment-queue: pushes post-commit total=%s sent=%s",
            len(pushes), sent,
        )

    if stats.get("total"):
        logger.info(
            "scheduler assignment-queue: total=%s asignados=%s reagendados=%s descartados=%s",
            stats["total"], stats["asignados"], stats["reagendados"], stats["descartados"],
        )


async def _assignment_queue_loop() -> None:
    """Loop del procesador de cola de auto-asignacion. Solo corre en el
    worker lider (mismo advisory lock que TikTok). Cada 15 min."""
    logger.info("scheduler assignment-queue: loop iniciado.")
    try:
        while True:
            is_leader = await asyncio.to_thread(_try_become_leader)
            if is_leader:
                try:
                    await _run_assignment_queue_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("scheduler assignment-queue: error: %s", exc)
                sleep_sec = _ASSIGNMENT_QUEUE_INTERVAL_SEC
            else:
                sleep_sec = _IDLE_SLEEP_SEC
            await asyncio.sleep(sleep_sec)
    except asyncio.CancelledError:
        logger.info("scheduler assignment-queue: loop cancelado, saliendo limpiamente.")
        raise


# ─── Loop: cola de outbound webhooks (V058) ───────────────────────────────

async def _run_webhook_queue_cycle() -> None:
    """Procesa la cola crm.webhook_deliveries. Best-effort: si la tabla
    no existe o el servicio falla, log y reintenta en el proximo tick."""
    def _do_cycle():
        from app.services import webhook_service
        try:
            return webhook_service.process_pending_queue()
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler webhook-queue: error en ciclo: %s", exc)
            return None

    stats = await asyncio.to_thread(_do_cycle)
    if stats and stats.get("processed"):
        logger.info(
            "scheduler webhook-queue: processed=%s success=%s retrying=%s dead=%s",
            stats["processed"], stats.get("success", 0),
            stats.get("retrying", 0), stats.get("dead", 0),
        )


async def _webhook_queue_loop() -> None:
    """Loop del worker de webhooks. Solo corre en el lider (mismo
    advisory lock). Cada 60s."""
    logger.info("scheduler webhook-queue: loop iniciado.")
    try:
        while True:
            is_leader = await asyncio.to_thread(_try_become_leader)
            if is_leader:
                try:
                    await _run_webhook_queue_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("scheduler webhook-queue: error: %s", exc)
                sleep_sec = _WEBHOOK_QUEUE_INTERVAL_SEC
            else:
                sleep_sec = _IDLE_SLEEP_SEC
            await asyncio.sleep(sleep_sec)
    except asyncio.CancelledError:
        logger.info("scheduler webhook-queue: loop cancelado, saliendo limpiamente.")
        raise


# ─── Loop: coalescer de push notifications (V075) ─────────────────────────

async def _run_notif_coalescer_cycle() -> None:
    """Flush del buffer de notificaciones. Best-effort: si la tabla no
    existe (V075 no aplicada), el servicio lo loggea y devuelve stats vacios."""
    def _do_cycle():
        from app.services import notification_coalescer
        try:
            return notification_coalescer.flush_due()
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler notif-coalescer: error en ciclo: %s", exc)
            return None

    stats = await asyncio.to_thread(_do_cycle)
    if stats and stats.get("leads_flusheados"):
        logger.info(
            "scheduler notif-coalescer: asesores=%s individuales=%s batch=%s leads=%s",
            stats["asesores_procesados"], stats["pushes_individuales"],
            stats["pushes_batch"], stats["leads_flusheados"],
        )


async def _notif_coalescer_loop() -> None:
    """Loop del coalescer de pushes. Solo corre en el lider (mismo
    advisory lock). Cada 15s."""
    logger.info("scheduler notif-coalescer: loop iniciado.")
    try:
        while True:
            is_leader = await asyncio.to_thread(_try_become_leader)
            if is_leader:
                try:
                    await _run_notif_coalescer_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("scheduler notif-coalescer: error: %s", exc)
                sleep_sec = _NOTIF_COALESCER_INTERVAL_SEC
            else:
                sleep_sec = _IDLE_SLEEP_SEC
            await asyncio.sleep(sleep_sec)
    except asyncio.CancelledError:
        logger.info("scheduler notif-coalescer: loop cancelado, saliendo limpiamente.")
        raise


async def _run_sla_cycle() -> None:
    """Ejecuta el chequeo periódico de SLA (15m y 24h), recordatorios de llamadas/citas y automatizaciones de flujo en un thread."""
    def _do_cycle():
        from app.services import sla_service, lead_automation_service, call_reminder_service
        try:
            sla_service.check_sla_alerts()
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler sla: error en ciclo: %s", exc)

        try:
            call_reminder_service.check_scheduled_call_reminders()
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler call-reminders: error en ciclo: %s", exc)

        try:
            lead_automation_service.procesar_automatizaciones_estados_no_contesta()
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler automatizaciones: error en ciclo: %s", exc)

    await asyncio.to_thread(_do_cycle)


async def _sla_loop() -> None:
    """Loop de monitorización de SLA y alertas de tiempos de gestión."""
    logger.info("scheduler sla: loop iniciado.")
    try:
        while True:
            is_leader = await asyncio.to_thread(_try_become_leader)
            if is_leader:
                try:
                    await _run_sla_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.exception("scheduler sla: error: %s", exc)
                sleep_sec = _SLA_CHECK_INTERVAL_SEC
            else:
                sleep_sec = _IDLE_SLEEP_SEC
            await asyncio.sleep(sleep_sec)
    except asyncio.CancelledError:
        logger.info("scheduler sla: loop cancelado, saliendo limpiamente.")
        raise


def start() -> None:
    """Arranca los loops de scheduling (idempotente)."""
    global _tiktok_task, _assignment_task, _webhook_task, _notif_coalescer_task, _sla_task
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        logger.warning("scheduler: sin event loop, no se arranca.")
        return
    if _tiktok_task is None or _tiktok_task.done():
        _tiktok_task = loop.create_task(_tiktok_loop(), name="integrations-tiktok-poller")
    if _assignment_task is None or _assignment_task.done():
        _assignment_task = loop.create_task(_assignment_queue_loop(), name="assignment-queue-processor")
    if _webhook_task is None or _webhook_task.done():
        _webhook_task = loop.create_task(_webhook_queue_loop(), name="webhook-queue-processor")
    if _notif_coalescer_task is None or _notif_coalescer_task.done():
        _notif_coalescer_task = loop.create_task(_notif_coalescer_loop(), name="notif-coalescer-flusher")
    if _sla_task is None or _sla_task.done():
        _sla_task = loop.create_task(_sla_loop(), name="sla-alerts-monitor")
    logger.info("scheduler: tareas registradas (tiktok + assignment-queue + webhook-queue + notif-coalescer + sla).")


async def stop() -> None:
    """Cancela las tareas en curso y espera su terminación."""
    global _tiktok_task, _assignment_task, _webhook_task, _notif_coalescer_task, _sla_task
    tasks = []
    if _tiktok_task is not None:
        _tiktok_task.cancel()
        tasks.append(("tiktok", _tiktok_task))
    if _assignment_task is not None:
        _assignment_task.cancel()
        tasks.append(("assignment-queue", _assignment_task))
    if _webhook_task is not None:
        _webhook_task.cancel()
        tasks.append(("webhook-queue", _webhook_task))
    if _notif_coalescer_task is not None:
        _notif_coalescer_task.cancel()
        tasks.append(("notif-coalescer", _notif_coalescer_task))
    if _sla_task is not None:
        _sla_task.cancel()
        tasks.append(("sla", _sla_task))
    for name, task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("scheduler %s: excepción al detener: %s", name, exc)
    _tiktok_task = None
    _assignment_task = None
    _webhook_task = None
    _notif_coalescer_task = None
    _sla_task = None
    _release_leader_lock()
    logger.info("scheduler: tareas detenidas.")

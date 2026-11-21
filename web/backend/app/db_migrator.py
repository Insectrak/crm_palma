"""
db_migrator.py — Auto-aplicador de migraciones SQL al startup.

Escanea web/backend/migrations/V*.sql, las aplica en orden alfabetico
(V040 antes que V041, etc) y registra las aplicadas en
`crm.schema_migrations`. Re-runs son no-op gracias al tracker.

Diseno:
- Single source of truth: web/backend/migrations/. Archivos en
  database/migrations/ son archivo historico (migraciones aplicadas
  manualmente antes de existir este sistema, V001..V039) y el
  migrador NO las toca.
- Idempotente: cada migracion debe ser segura de re-ejecutar (los
  V040+ del proyecto ya usan IF NOT EXISTS / OR REPLACE / CASE).
- Per-migration transaction: si una falla, rollback + stop. Las
  siguientes no se aplican hasta que el admin arregle la fallada.
- Fail-soft: errores se loguean pero no tumban la app — el
  resto del CRM sigue arrancando. Healthcheck del backend sigue
  verde y el admin ve el error en logs.
- BEGIN/COMMIT del SQL se strippan antes de execute() para evitar
  conflicto con el manejo de transacciones de psycopg2.

Para agregar una migracion nueva:
  1. Crear web/backend/migrations/V0XX_descripcion.sql
  2. Push → en el proximo deploy se aplica sola al levantar el backend
  3. Verificar en logs: "[migrator] OK V0XX"
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.database import get_db

logger = logging.getLogger(__name__)


# Captura solo archivos con prefijo VNNN_*.sql (e.g., V040_xxx.sql).
# Otros archivos (README, scripts ad-hoc, etc) se ignoran sin warning
# para no ensuciar logs.
# V070.60 — Bug histórico: el regex anterior `(V\d+)_.+` colapsaba
# `V068`, `V068_3`, `V068_4_external_created_at` todos en la version
# "V068". Como el tracker (crm.schema_migrations) guarda 1 fila por
# version, solo se aplicaba la PRIMERA alfabéticamente y las demas se
# silenciaban con "already applied". Resultado: la columna
# external_created_at en lead_recontactos NUNCA se creó en produccion.
#
# Nuevo regex: captura V<num>[_<num>...] para diferenciar subversiones.
# Ejemplos:
#   V068                              → "V068"
#   V068_3_clean_same_day            → "V068_3"
#   V068_4_external_created_at       → "V068_4"
#   V068_lead_recontactos_daily_dedup → "V068"
# Las que no tienen subnúmero (terminan con letra después del primer _)
# quedan como V<num>. Las que tienen subnúmero quedan como V<num>_<sub>.
_VERSION_RE = re.compile(r"^(V\d+(?:_\d+)*)_[A-Za-z].*\.sql$", re.IGNORECASE)
_TX_LINE_RE = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;\s*$", re.IGNORECASE)

# Filenames exclusivos de la rama anterior de Palma (V097..V149) que colisionan
# por numero de version con las migraciones V097..V111 de esta base unificada.
_PALMA_LEGACY_DIVERGENT_FILENAMES = (
    "V097_lead_valor_venta.sql",
    "V098_public_forms_auto_distribuir.sql",
    "V099_wa_bot_knowledge_base.sql",
    "V100_kb_hybrid_search.sql",
    "V101_wa_bot_flows.sql",
    "V102_wa_bot_supervisor_auto_assign.sql",
    "V103_wa_bot_handoff_triggers.sql",
    "V104_wa_bot_takeover.sql",
    "V105_wa_bot_trigger_sets.sql",
    "V106_wa_media_processed.sql",
    "V107_leads_carga_masiva_id.sql",
    "V107_2_backfill_carga_masiva_id.sql",
    "V108_estados_display_visibility.sql",
    "V109_cita_estados_es_sistema.sql",
    "V110_calidad_es_sistema.sql",
    "V111_wa_messages_soft_delete_edit.sql",
    "V140_leads_field_history.sql",
    "V143_tipos_contacto_color.sql",
    "V149_backfill_previous_asesor.sql",
)


def _migrations_dir() -> Path:
    """web/backend/migrations/ — al lado del paquete `app/`."""
    here = Path(__file__).resolve().parent.parent  # .../web/backend
    return here / "migrations"


def _strip_tx_markers(sql: str) -> str:
    """Quita BEGIN/COMMIT/ROLLBACK aislados — psycopg2 maneja la tx."""
    return "\n".join(line for line in sql.splitlines() if not _TX_LINE_RE.match(line))


def _list_migrations() -> list[tuple[str, Path]]:
    """Lista [(version, path)] ordenada alfabeticamente. Solo VNNN_*.sql.

    V070.64 — Defense in depth contra colisiones de version (bug
    historico: V068, V068_3, V068_4 colisionaban en "V068"). Si dos
    archivos producen la misma version (ej: alguien crea
    V071_nueva_feature.sql cuando ya existe V071_legacy.sql), lanzamos
    error CRITICO al cargar — antes de aplicar cualquier migracion.

    Mejor fallar fuerte aqui que silenciosamente skipear migraciones en
    produccion (el bug que tomo 4 horas destrabar).
    """
    d = _migrations_dir()
    if not d.exists():
        return []
    found: list[tuple[str, Path]] = []
    seen_versions: dict[str, str] = {}  # version -> first filename
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        m = _VERSION_RE.match(f.name)
        if m:
            version = m.group(1).upper()
            if version in seen_versions:
                msg = (
                    f"[migrator] COLISION DE VERSION: '{version}' aparece en dos archivos: "
                    f"'{seen_versions[version]}' y '{f.name}'. Renombra uno con sub-version "
                    f"(ej: {version}_2_descripcion.sql) para evitar que se silencie en deploy."
                )
                logger.error(msg)
                raise RuntimeError(msg)
            seen_versions[version] = f.name
            found.append((version, f))
    # Orden semantico por version numerica: V104 -> (104,) antes que V104_2 -> (104, 2)
    found.sort(key=lambda item: tuple(int(p) for p in item[0][1:].split("_")))
    return found


def _ensure_tracker(cur) -> None:
    """Crea crm.schema_migrations si no existe. Idempotente."""
    cur.execute(
        """
        CREATE SCHEMA IF NOT EXISTS crm;
        CREATE TABLE IF NOT EXISTS crm.schema_migrations (
            version    TEXT PRIMARY KEY,
            filename   TEXT        NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _reconcile_palma_legacy_migrations(conn) -> None:
    """Archiva y limpia entradas divergentes de la rama Palma anterior en crm.schema_migrations.

    Permite desplegar 1-click sobre una BD existente de Palma sin que
    V097..V111 queden bloqueadas por coincidencia de numero de version.
    Idempotente: si no hay filas con esos filenames, no modifica nada.
    """
    filenames = list(_PALMA_LEGACY_DIVERGENT_FILENAMES)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM crm.schema_migrations WHERE filename = ANY(%s) LIMIT 1",
                (filenames,),
            )
            if cur.fetchone() is None:
                return

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS crm.schema_migrations_palma_legacy (
                    version    TEXT PRIMARY KEY,
                    filename   TEXT        NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO crm.schema_migrations_palma_legacy (version, filename, applied_at)
                SELECT version, filename, applied_at
                FROM crm.schema_migrations
                WHERE filename = ANY(%s)
                ON CONFLICT (version) DO NOTHING
                """,
                (filenames,),
            )
            cur.execute(
                "DELETE FROM crm.schema_migrations WHERE filename = ANY(%s)",
                (filenames,),
            )
            deleted = cur.rowcount
        conn.commit()
        logger.info(
            "[migrator] reconciliadas %d entrada(s) legacy de Palma en crm.schema_migrations",
            deleted,
        )
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        logger.error("[migrator] fallo reconciliacion legacy de Palma: %s", exc)


def run_pending_migrations() -> None:
    """Aplica las migraciones nuevas. Llamado desde bootstrap al startup."""
    migrations = _list_migrations()
    if not migrations:
        logger.info("[migrator] no migrations folder or empty — nothing to do")
        return

    with get_db() as conn:
        # Tracker primero (su propia tx)
        try:
            with conn.cursor() as cur:
                _ensure_tracker(cur)
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.error("[migrator] could not create tracker table: %s", exc)
            return

        _reconcile_palma_legacy_migrations(conn)

        # Estado actual del tracker
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version FROM crm.schema_migrations")
                applied: set[str] = {row[0].upper() for row in cur.fetchall()}
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.error("[migrator] could not read tracker: %s", exc)
            return

        for version, path in migrations:
            if version in applied:
                logger.info("[migrator] skip %s — already applied", version)
                continue

            try:
                sql = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.error("[migrator] cannot read %s: %s", path.name, exc)
                break

            sql = _strip_tx_markers(sql)

            logger.info("[migrator] applying %s (%s)…", version, path.name)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO crm.schema_migrations (version, filename) "
                        "VALUES (%s, %s) "
                        "ON CONFLICT (version) DO NOTHING",
                        (version, path.name),
                    )
                conn.commit()
                logger.info("[migrator] OK %s", version)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                logger.error(
                    "[migrator] FAILED %s — %s. Stopping migration chain.",
                    version, exc,
                )
                # No raise: dejamos que el resto del backend arranque.
                # El error queda visible en logs y el admin puede aplicar
                # la migracion manualmente. Las posteriores quedan
                # pendientes hasta que esta resuelva.
                break

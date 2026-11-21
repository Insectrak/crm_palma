"""
schema_bootstrap.py - Auto-bootstrap del schema base para fresh installs.

PROBLEMA QUE RESUELVE
=====================
El auto-migrator (app/db_migrator.py) solo aplica las migraciones que
viven en web/backend/migrations/V040+. Las migraciones legacy V001-V039
viven en database/migrations/ y se aplicaban a mano en cada install
historico (2024-2025).

Para un FRESH install (servidor nuevo, DB vacia), las V040+ fallan
porque las tablas base (auth.users, crm.leads, etc.) no existen
todavia. Este modulo detecta esa situacion al startup y aplica el
schema base automaticamente antes que el auto-migrator se ejecute.

DISEÑO
======
- Llamada UNA sola vez, antes del migrator, desde run_startup_bootstrap().
- Idempotente: si auth.users existe (DB ya bootstrapped), no hace nada.
- Graceful degradation: si los SQL legacy no estan en el contenedor
  (build viejo sin database/), log warning + return — el migrator
  podria fallar pero la app sigue arrancando.
- Per-statement transaction: si una migracion falla, rollback + stop.
  Las posteriores no se aplican hasta arreglar la fallada.
- Marca cada migracion aplicada en crm.schema_migrations para que el
  auto-migrator no las re-corra.

WORKFLOW DEL CONTENEDOR
=======================
El Dockerfile (raiz del repo) copia:
  database/ddl/*.sql        -> /app/legacy_ddl/
  database/migrations/*.sql -> /app/legacy_migrations/

Si esos directorios no existen (ej. dev local con docker-compose viejo),
este modulo loguea warning y retorna sin error.

ARCHIVOS EXCLUIDOS
==================
V005_migrate_existing_data.sql -> es el import de pdr_marketing, NO
forma parte del schema base. Se corre manualmente cuando el cliente
quiere migrar datos historicos (ver docs/MIGRATION_RUNBOOK.md).

export_*.sql, crm_verificacion_*.sql -> son scripts de exportacion
o queries de verificacion ad-hoc, no DDL.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.database import get_db

logger = logging.getLogger(__name__)


# ── Paths dentro del contenedor ──────────────────────────────────────
# El Dockerfile copia database/ddl/ -> /app/legacy_ddl/
# y database/migrations/ -> /app/legacy_migrations/
LEGACY_DDL_DIR = Path("/app/legacy_ddl")
LEGACY_MIGRATIONS_DIR = Path("/app/legacy_migrations")

# ID del advisory lock para el bootstrap. Arbitrario pero unico —
# bloquea entre workers del mismo deploy para evitar race conditions
# (uvicorn con --workers 2 hace que 2 procesos corran ensure_base_schema
# al mismo tiempo, ambos intentan crear las mismas tablas y chocan).
BOOTSTRAP_ADVISORY_LOCK_ID = 9_876_543_210


# Orden estricto de DDL: schema auth -> schema public.
#
# IMPORTANTE: DDL_FUNCIONES_UUID.sql NO se incluye en este orden a
# proposito. Define funciones uuid_generate_v1, _v4, etc. apuntando a
# $libdir/uuid-ossp como CREATE OR REPLACE — pero choca con las que
# provee la propia extension uuid-ossp cuando esta esta cargada.
# Resultado anterior en produccion: "function uuid_generate_v1 already
# exists with same argument types" al re-deploy.
#
# Fix: en _ensure_prerequisites() ejecutamos CREATE EXTENSION "uuid-ossp"
# que provee TODAS las funciones nativamente. El DDL legacy es
# redundante y conflictivo — lo dejamos en el repo por trazabilidad
# historica pero NO lo aplicamos.
DDL_ORDER = [
    "DDL_AUTH_V0.sql",
    "DDL_PUBLIC.sql",
]

# Archivos en database/migrations que NO son schema base
SKIP_FILES = {
    "crm_verificacion_migracion.sql",        # query ad-hoc
    "export_pdr_leads.sql",                  # script de export
    "export_pdr_genera_contactos_sql.sql",   # generador inserts
    "export_pdr_genera_estados_sql.sql",
    "export_pdr_genera_update_sql.sql",
    "V005_migrate_existing_data.sql",        # IMPORT de pdr_marketing (Fase 2)
    # V017 siembra data ESPECIFICA del cliente Palma del Rio (4 asesores con
    # nombres reales + schema crm_legacy + estado 'Historico'). Si se aplica
    # en otro tenant, el cliente nuevo abre el CRM y ve usuarios "Ana
    # Montes", "Diego", etc. que no son suyos. Regla del producto: cada
    # install arranca con DB 100% virgen, sin data de cliente especifico.
    # Para Palma, los datos reales vienen en Fase 2 desde pdr_marketing
    # via scripts/migrate_pdr_marketing*.py — NO desde esta migracion.
    "V017_migracion_pdr.sql",
}

# Regex para extraer key del tracker (mismo que db_migrator)
_VERSION_RE = re.compile(r"^(V\d+(?:_\d+)*)_", re.IGNORECASE)
_TX_LINE_RE = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;\s*$", re.IGNORECASE)


def _version_key(filename: str) -> str:
    """Clave para tracker. V001_foo.sql -> V001 ; 06_bar.sql -> 06_BAR."""
    name = filename.replace(".sql", "")
    m = _VERSION_RE.match(name)
    if m:
        return m.group(1).upper()
    return name.upper()


def _strip_tx_markers(sql: str) -> str:
    """Quita BEGIN/COMMIT/ROLLBACK aislados (psycopg2 maneja la tx)."""
    return "\n".join(
        line for line in sql.splitlines()
        if not _TX_LINE_RE.match(line)
    )


def _has_auth_users(cur) -> bool:
    """True si la tabla auth.users existe."""
    cur.execute("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'auth' AND table_name = 'users'
        LIMIT 1
    """)
    return cur.fetchone() is not None


def _has_crm_leads(cur) -> bool:
    """True si la tabla crm.leads existe (la crea V001)."""
    cur.execute("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'crm' AND table_name = 'leads'
        LIMIT 1
    """)
    return cur.fetchone() is not None


def _ensure_legacy_history_schema(conn) -> None:
    """
    Crea crm_legacy.leads_historico VACIA en todo install nuevo.

    La pantalla "Leads Historicos" del CRM (sidebar Historicos) consulta
    esta tabla. Si no existe -> el endpoint falla y la UI muestra
    "Error al cargar historicos" en rojo.

    En el modelo del producto, esta tabla es para datos historicos del
    sistema anterior del cliente (si lo tuviera). En un install limpio
    queda vacia y la pantalla muestra "no hay leads historicos" — UX
    natural. Si despues hay una migracion Fase 2 desde un sistema previo
    (ej. Palma del Rio: pdr_marketing), un script externo la rellena.

    Antes este DDL vivia en V017_migracion_pdr.sql junto con los INSERTs
    de los 4 asesores reales de Palma. Excluimos V017 del bootstrap
    (regla install limpio) pero perdimos el DDL del schema. Esto lo
    restaura SIN los inserts: solo schema + tabla + indices vacios.
    """
    with conn.cursor() as cur:
        cur.execute("""
            CREATE SCHEMA IF NOT EXISTS crm_legacy;

            CREATE TABLE IF NOT EXISTS crm_legacy.leads_historico (
                id             BIGSERIAL PRIMARY KEY,
                telefono       TEXT,
                telefono_norm  TEXT,
                nombre         TEXT,
                email          TEXT,
                dni            TEXT,
                proyecto       TEXT,
                canal          TEXT,
                asesor_id      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                asesor_nombre  TEXT,
                estado         TEXT,
                seguimiento    TEXT,
                observaciones  TEXT,
                ciudad         TEXT,
                fecha_ingreso  DATE,
                origen_tabla   TEXT NOT NULL DEFAULT 'sistema_anterior',
                migrado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS asesor_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS asesor_nombre TEXT;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS ciudad TEXT;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS seguimiento TEXT;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS fecha_ingreso DATE;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS fecha_creacion DATE;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS fecha_asignacion DATE;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS fecha_ultimo_contacto DATE;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS lead_crm_id INT REFERENCES crm.leads(id) ON DELETE SET NULL;

            ALTER TABLE crm_legacy.leads_historico
                ADD COLUMN IF NOT EXISTS origen_tabla TEXT DEFAULT 'sistema_anterior';

            CREATE INDEX IF NOT EXISTS idx_leads_historico_tel_norm
                ON crm_legacy.leads_historico (telefono_norm);
            CREATE INDEX IF NOT EXISTS idx_leads_historico_dni
                ON crm_legacy.leads_historico (dni);
            CREATE INDEX IF NOT EXISTS idx_leads_historico_fecha_ingreso
                ON crm_legacy.leads_historico (fecha_ingreso DESC);
            CREATE INDEX IF NOT EXISTS idx_leads_historico_fecha_creacion
                ON crm_legacy.leads_historico (fecha_creacion DESC);
            CREATE INDEX IF NOT EXISTS idx_leads_historico_asesor_id
                ON crm_legacy.leads_historico (asesor_id);
        """)
    conn.commit()


def _ensure_prerequisites(conn) -> None:
    """
    Crea extensiones y schemas que los DDLs asumen pre-existentes pero
    NO crean ellos mismos. Sin esto, fresh installs revientan en
    silencio.

    Idempotente. Limpia funciones huerfanas uuid_generate_* en public
    que pudieron haber quedado de installs previos manuales (DDL legacy
    que las creaba apuntando a $libdir/uuid-ossp). Esas funciones
    huerfanas chocan con CREATE EXTENSION "uuid-ossp" porque postgres
    detecta el nombre+args duplicado, error:
        "function uuid_generate_v1 already exists with same argument types"

    Solucion: si existen las funciones uuid_* en public PERO la extension
    uuid-ossp NO esta instalada (= son huerfanas de un install legacy),
    las dropeamos antes de crear la extension limpia.
    """
    with conn.cursor() as cur:
        # 1. Detectar y limpiar funciones uuid_* huerfanas (no parte de
        #    una extension). Si existen pero la extension no esta
        #    registrada, las dropeamos para que CREATE EXTENSION funcione.
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'uuid-ossp'
                ) AND EXISTS (
                    SELECT 1 FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE p.proname = 'uuid_generate_v1'
                      AND n.nspname = 'public'
                ) THEN
                    DROP FUNCTION IF EXISTS public.uuid_generate_v1()                 CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_generate_v1mc()               CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_generate_v3(uuid, text)       CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_generate_v4()                 CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_generate_v5(uuid, text)       CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_nil()                         CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_ns_dns()                      CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_ns_url()                      CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_ns_oid()                      CASCADE;
                    DROP FUNCTION IF EXISTS public.uuid_ns_x500()                     CASCADE;
                END IF;
            END $$;
        """)

        # 2. Extension uuid-ossp: provee uuid_generate_v1/v4/etc nativamente.
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

        # 3. Schemas base (los DDLs los asumen pre-existentes).
        cur.execute("CREATE SCHEMA IF NOT EXISTS auth")
        cur.execute("CREATE SCHEMA IF NOT EXISTS crm")
    conn.commit()


def _ensure_tracker(cur) -> None:
    """Crea crm.schema_migrations si no existe. Mismo formato que db_migrator."""
    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS crm;
        CREATE TABLE IF NOT EXISTS crm.schema_migrations (
            version    TEXT PRIMARY KEY,
            filename   TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def _apply_sql_file(conn, path: Path) -> tuple[bool, str | None]:
    """Aplica un SQL en su propia transaccion. Devuelve (ok, error_msg)."""
    try:
        sql = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"no se puede leer: {e}"

    sql_clean = _strip_tx_markers(sql)
    try:
        with conn.cursor() as cur:
            cur.execute(sql_clean)
        conn.commit()
        return True, None
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        return False, str(e).strip()


def _record_applied(conn, version: str, filename: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO crm.schema_migrations (version, filename) "
            "VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
            (version, filename),
        )
    conn.commit()


def _list_legacy_migrations() -> list[Path]:
    """database/migrations/*.sql, ordenadas, excluyendo aux."""
    if not LEGACY_MIGRATIONS_DIR.exists():
        return []
    files = sorted(LEGACY_MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in files if f.name not in SKIP_FILES]


# ── API publica ──────────────────────────────────────────────────────

def ensure_base_schema() -> None:
    """
    Auto-bootstrap del schema base. Llamado desde run_startup_bootstrap()
    ANTES del auto-migrator y de las defense-in-depth ensure_*_schema().

    Comportamiento:
    - Si auth.users existe → DB ya bootstrapped, log info + return.
    - Si los directorios legacy_* no estan en el contenedor → log warning,
      return (probablemente build viejo, el admin tiene que aplicar
      database/migrations a mano).
    - Si DB vacia y legacy disponibles → aplica DDL + legacy migrations
      en orden, registra en tracker, log [bootstrap] por cada paso.
    - Si una migracion falla → rollback de esa, log error, STOP la
      cadena. El backend igual arranca (fail-soft).
    """
    if not LEGACY_DDL_DIR.exists() or not LEGACY_MIGRATIONS_DIR.exists():
        logger.warning(
            "[schema_bootstrap] directorios legacy no encontrados "
            "(%s, %s) — saltando auto-bootstrap. Si la DB es fresh, "
            "aplicar manualmente database/migrations/ con psql.",
            LEGACY_DDL_DIR, LEGACY_MIGRATIONS_DIR,
        )
        return

    try:
        with get_db() as conn:
            # Advisory lock global: solo UN worker corre el bootstrap a la vez.
            # uvicorn con --workers 2 dispara N procesos que arrancan lifespan
            # en paralelo; sin el lock, los 2 corren ensure_base_schema()
            # simultaneamente y chocan al crear las mismas tablas/indices.
            # pg_advisory_lock BLOQUEA hasta obtener el lock (no try).
            #
            # Si otro worker ya esta haciendo el bootstrap, este worker espera
            # aqui. Cuando el otro termina y libera el lock, este lo obtiene y
            # re-verifica el estado: si ya esta todo bootstrapped, skip.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_lock(%s)",
                    (BOOTSTRAP_ADVISORY_LOCK_ID,),
                )
                cur.fetchone()  # bloquea hasta obtener el lock
            conn.commit()

            # Check 1 (DESPUES del lock): DB ya completamente bootstrapped?
            # Validamos 2 condiciones (auth.users Y crm.leads) en lugar de solo
            # auth.users, porque si un install previo crasheo a mitad de camino
            # dejando auth.users creado pero crm.leads no, mi check anterior
            # asumia "ya bootstrapped" e ignoraba el resto. Ahora detectamos
            # el estado intermedio y completamos el bootstrap.
            with conn.cursor() as cur:
                has_users = _has_auth_users(cur)
                has_leads = _has_crm_leads(cur)
                if has_users and has_leads:
                    logger.info(
                        "[schema_bootstrap] auth.users + crm.leads existen — "
                        "DB ya bootstrapped (otro worker ya lo hizo), skip."
                    )
                    # Liberar lock antes de salir
                    cur.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (BOOTSTRAP_ADVISORY_LOCK_ID,),
                    )
                    cur.fetchone()
                    conn.commit()
                    return
                conn.rollback()  # cerrar tx abierta del SELECT

            if has_users or has_leads:
                logger.warning(
                    "[schema_bootstrap] estado intermedio detectado "
                    "(auth.users=%s, crm.leads=%s) — completando bootstrap, "
                    "los CREATE TABLE IF NOT EXISTS de las migraciones son "
                    "idempotentes asi que es seguro re-correr.",
                    has_users, has_leads,
                )
            else:
                logger.info(
                    "[schema_bootstrap] FRESH DB detected — aplicando "
                    "schema base (DDL + V001-V039)..."
                )

            # 0. Pre-requisitos: extension uuid-ossp + schemas auth/crm.
            # Los DDLs los asumen pre-existentes pero no los crean.
            _ensure_prerequisites(conn)
            logger.info(
                "[schema_bootstrap] prerequisitos OK "
                "(uuid-ossp + schemas auth/crm)"
            )

            # 1. Aplicar DDL en orden
            for name in DDL_ORDER:
                path = LEGACY_DDL_DIR / name
                if not path.exists():
                    logger.error(
                        "[schema_bootstrap] DDL faltante: %s — stop", path
                    )
                    return

                ok, err = _apply_sql_file(conn, path)
                if not ok:
                    logger.error(
                        "[schema_bootstrap] FALLO DDL %s: %s — stop",
                        name, err
                    )
                    return
                logger.info("[schema_bootstrap] OK DDL %s", name)

            # 2. Tracker
            with conn.cursor() as cur:
                _ensure_tracker(cur)
            conn.commit()

            # 2.b. Schema crm_legacy con tabla vacia.
            # La pantalla "Historicos" consulta esta tabla; sin ella la UI
            # tira error rojo. Creamos el DDL puro (sin los inserts de
            # V017 que sembraban data especifica de Palma).
            try:
                _ensure_legacy_history_schema(conn)
                logger.info(
                    "[schema_bootstrap] crm_legacy.leads_historico "
                    "asegurada (vacia, lista para import Fase 2)"
                )
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                logger.warning(
                    "[schema_bootstrap] no se pudo crear crm_legacy: %s",
                    exc
                )

            # 3. Aplicar legacy migrations en orden
            migrations = _list_legacy_migrations()
            applied = 0
            for path in migrations:
                version = _version_key(path.name)
                ok, err = _apply_sql_file(conn, path)
                if not ok:
                    logger.error(
                        "[schema_bootstrap] FALLO %s (%s): %s — stop",
                        version, path.name, err
                    )
                    return
                _record_applied(conn, version, path.name)
                applied += 1
                logger.info(
                    "[schema_bootstrap] OK %s (%s)", version, path.name
                )

            logger.info(
                "[schema_bootstrap] BASE SCHEMA APLICADO: %d DDL + %d "
                "legacy migrations. El auto-migrator puede correr V040+ ahora.",
                len(DDL_ORDER), applied,
            )

            # Liberar advisory lock al terminar OK.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (BOOTSTRAP_ADVISORY_LOCK_ID,),
                )
                cur.fetchone()
            conn.commit()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[schema_bootstrap] error inesperado: %s — saltando "
            "auto-bootstrap, el backend sigue arrancando.", exc
        )
        # Best-effort: liberar el lock si lo teniamos. Si la conexion
        # se rompe el lock se libera solo al cerrar la sesion postgres,
        # pero llamamos a unlock explicito por las dudas.
        try:
            with get_db() as conn2:
                with conn2.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (BOOTSTRAP_ADVISORY_LOCK_ID,),
                    )
                conn2.commit()
        except Exception:  # noqa: BLE001
            pass

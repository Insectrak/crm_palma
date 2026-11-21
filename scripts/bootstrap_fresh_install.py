#!/usr/bin/env python3
"""
bootstrap_fresh_install.py - Aplica el schema base del CRM a una DB vacia.

CONTEXTO
========
El CRM tiene dos capas de migraciones:

  1. SCHEMA BASE (database/ddl/ + database/migrations/V001-V039)
     - Aplicado manualmente a mano en 2024-2025 cuando aun no existia
       el auto-migrator.
     - Crea schemas auth, crm, public + ~30 tablas + funciones UUID.
     - Quien ya tiene una instalacion antigua, NO necesita correr este
       script (ya esta aplicado).

  2. MIGRACIONES INCREMENTALES (web/backend/migrations/V040+)
     - Aplicadas AUTOMATICAMENTE por app/db_migrator.py al primer
       arranque del backend.
     - Asumen que el schema base YA existe.

Para un FRESH install en un servidor nuevo (Doctor Muelita, segundo
deploy de Palma, etc.) este script aplica la capa 1, despues el deploy
del CRM aplica la capa 2 sola.

USO
===
Interactivo (recomendado):
    python scripts/bootstrap_fresh_install.py

Con argumento:
    python scripts/bootstrap_fresh_install.py \
        --database-url "postgresql://postgres:<password>@<host>:5432/crm_db"

Con env var:
    set DATABASE_URL=postgresql://postgres:<password>@<host>:5432/crm_db
    python scripts/bootstrap_fresh_install.py

Override safety check (cuando se SABE que la DB no esta vacia y se
quiere correr de todos modos para arreglar un install corrupto):
    python scripts/bootstrap_fresh_install.py --force

QUE HACE
========
1. Conecta a la DB.
2. Safety check: si auth.users tiene datos, aborta (salvo --force).
3. Aplica DDL en orden: FUNCIONES_UUID -> AUTH_V0 -> PUBLIC.
4. Aplica database/migrations/*.sql en orden alfabetico (V001-V039 +
   las legacy sin prefijo V).
5. Registra cada migracion aplicada en crm.schema_migrations.
6. Imprime resumen + proximos pasos.

DESPUES DE ESTE SCRIPT
======================
1. Deployar el CRM en EasyPanel (o levantar el contenedor).
2. El auto-migrator detecta el tracker existente y solo aplica V040+
   que no esten registradas. No reaplica V001-V039.
3. POST /api/setup/create-admin para crear el primer usuario.
4. Login + configurar catalogos + invitar al equipo.

DEPENDENCIAS
============
- Python 3.10+
- psycopg2-binary  (instalar con: pip install psycopg2-binary)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from textwrap import dedent

# Forzar UTF-8 en stdout (Windows cp1252 fix)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, Exception):
    pass

try:
    import psycopg2
    from psycopg2 import sql as pg_sql  # noqa: F401  (reservado para escapes futuros)
except ImportError:
    print("ERROR: este script necesita psycopg2-binary.")
    print("Instalalo con:  pip install psycopg2-binary")
    sys.exit(2)


# ─── Paths del repo ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
DDL_DIR = REPO_ROOT / "database" / "ddl"
MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations"

# ─── Orden de DDL: auth -> public ──────────────────────────────────
# DDL_FUNCIONES_UUID.sql NO se incluye: define uuid_generate_v1/v4/etc
# como CREATE OR REPLACE FUNCTION apuntando a $libdir/uuid-ossp, lo que
# choca con la extension uuid-ossp ("already exists with same argument
# types"). En su lugar, ensure_prerequisites() ejecuta CREATE EXTENSION
# uuid-ossp que provee las funciones nativamente.
DDL_ORDER = [
    "DDL_AUTH_V0.sql",          # schema auth (users, sessions, resets)
    "DDL_PUBLIC.sql",           # schema public (app_settings, etc.)
]

# ─── Archivos auxiliares en database/migrations que NO son migraciones ──
# El bootstrap solo aplica DDL puro. Excluimos:
#   - Scripts de verificacion (no modifican schema).
#   - Scripts de export (corren contra OTRA DB, no contra crm_db).
#   - Scripts de IMPORT DE DATOS productivos (Fase 2 — ver MIGRATION_RUNBOOK.md).
#     Esos se corren manualmente cuando el cliente decide migrar leads
#     historicos del sistema previo (pdr_marketing). NO en fresh install.
SKIP_FILES = {
    "crm_verificacion_migracion.sql",       # query de verificacion ad-hoc
    "export_pdr_leads.sql",                  # export desde pdr_marketing
    "export_pdr_genera_contactos_sql.sql",   # generador de inserts (no DDL)
    "export_pdr_genera_estados_sql.sql",
    "export_pdr_genera_update_sql.sql",
    "V005_migrate_existing_data.sql",        # IMPORT de pdr_marketing -> Fase 2
    # V017: data ESPECIFICA del cliente Palma (4 asesores con nombres reales).
    # Regla del producto: cada install arranca con DB 100% virgen.
    "V017_migracion_pdr.sql",
}

# ─── Strip de BEGIN/COMMIT (psycopg2 maneja la tx, no necesita en SQL) ──
_TX_LINE_RE = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;\s*$", re.IGNORECASE)


# ────────────────────────────────────────────────────────────────────
# Utilidades
# ────────────────────────────────────────────────────────────────────

def die(msg: str, code: int = 1) -> None:
    print(f"\n[X] ERROR: {msg}\n", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(f"   {msg}")


def ok(msg: str) -> None:
    print(f"   [OK] {msg}")


def warn(msg: str) -> None:
    print(f"   [!] {msg}")


def step(msg: str) -> None:
    print(f"\n>>> {msg}")


def strip_tx_markers(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines()
        if not _TX_LINE_RE.match(line)
    )


def version_key(filename: str) -> str:
    """Clave para tracker: si tiene Vnnn, lo extrae; sino usa el nombre."""
    name = filename.replace(".sql", "")
    m = re.match(r"^(V\d+(?:_\d+)*)_", name, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return name.upper()


# ────────────────────────────────────────────────────────────────────
# DB helpers
# ────────────────────────────────────────────────────────────────────

def connect(database_url: str):
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = False
        return conn
    except psycopg2.Error as e:
        die(f"no pude conectar a la DB: {e}")


def check_fresh(conn, force: bool) -> None:
    """Aborta si la DB ya tiene datos productivos, salvo --force."""
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT count(*) FROM auth.users")
            count = cur.fetchone()[0]
            if count > 0 and not force:
                die(dedent(f"""
                    la DB ya tiene {count} usuario(s) en auth.users.
                    Este script es solo para FRESH installs (DB vacia).

                    Si sabes lo que haces y quieres re-aplicar el bootstrap
                    contra una DB existente (idempotente, no rompe nada
                    pero re-corre todos los CREATE TABLE IF NOT EXISTS),
                    usa: --force
                """).strip())
        except psycopg2.Error:
            # auth.users no existe -> esta mas vacia todavia, ok.
            conn.rollback()


def ensure_tracker(conn) -> None:
    """Crea crm.schema_migrations si no existe. Mismo formato que db_migrator."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE SCHEMA IF NOT EXISTS crm;
            CREATE TABLE IF NOT EXISTS crm.schema_migrations (
                version    TEXT PRIMARY KEY,
                filename   TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()


def ensure_prerequisites(conn) -> None:
    """
    Crea extension uuid-ossp y schemas auth + crm. Idempotente.

    Limpia funciones uuid_* huerfanas en public (si las hubiera de un
    install legacy que las haya creado a mano apuntando a uuid-ossp).
    Sin esto, CREATE EXTENSION falla con "already exists with same
    argument types".
    """
    with conn.cursor() as cur:
        # 1. Limpiar funciones uuid huerfanas si existen sin la extension
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
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        cur.execute("CREATE SCHEMA IF NOT EXISTS auth")
        cur.execute("CREATE SCHEMA IF NOT EXISTS crm")
    conn.commit()


def already_applied(conn, version: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM crm.schema_migrations WHERE version = %s",
            (version,)
        )
        return cur.fetchone() is not None


def record_applied(conn, version: str, filename: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO crm.schema_migrations (version, filename) "
            "VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
            (version, filename)
        )
    conn.commit()


def apply_sql(conn, path: Path) -> tuple[bool, str | None]:
    """Aplica un archivo SQL en su propia transaccion."""
    try:
        sql = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"no puedo leer el archivo: {e}"

    sql_clean = strip_tx_markers(sql)
    try:
        with conn.cursor() as cur:
            cur.execute(sql_clean)
        conn.commit()
        return True, None
    except psycopg2.Error as e:
        conn.rollback()
        return False, str(e).strip()


# ────────────────────────────────────────────────────────────────────
# Orquestacion
# ────────────────────────────────────────────────────────────────────

def list_ddls() -> list[Path]:
    found = []
    for name in DDL_ORDER:
        p = DDL_DIR / name
        if not p.exists():
            die(f"falta archivo DDL: {p}")
        found.append(p)
    return found


def list_legacy_migrations() -> list[Path]:
    """database/migrations/*.sql ordenadas, excluyendo auxiliares."""
    if not MIGRATIONS_DIR.exists():
        die(f"directorio no encontrado: {MIGRATIONS_DIR}")
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in files if f.name not in SKIP_FILES]


def apply_batch(conn, files: list[Path], label: str) -> tuple[int, int, int]:
    """Devuelve (applied, skipped, failed)."""
    applied = skipped = failed = 0
    for path in files:
        version = version_key(path.name)

        if already_applied(conn, version):
            info(f"SKIP {version}  ({path.name})  ya estaba en el tracker")
            skipped += 1
            continue

        success, err = apply_sql(conn, path)
        if not success:
            warn(f"FAIL {version}  ({path.name})")
            warn(f"     {err}")
            failed += 1
            print()
            print("La cadena se detiene aqui para no encadenar errores.")
            print("Arregla el problema en el SQL y volve a correr el script.")
            print("(las migraciones aplicadas ya estan en el tracker, no se reintentan)")
            break

        record_applied(conn, version, path.name)
        ok(f"{version}  ({path.name})")
        applied += 1

    return applied, skipped, failed


def count_tables_per_schema(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_schema, count(*)
            FROM information_schema.tables
            WHERE table_schema IN ('auth', 'crm', 'public')
              AND table_type = 'BASE TABLE'
            GROUP BY table_schema
            ORDER BY table_schema
        """)
        return {row[0]: row[1] for row in cur.fetchall()}


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bootstrap del schema base del CRM en una DB vacia.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--database-url", "-d",
        default=os.environ.get("DATABASE_URL", ""),
        help="postgresql://user:<password>@<host>:port/dbname (o env DATABASE_URL)",
    )
    p.add_argument(
        "--force", "-f",
        action="store_true",
        help="Aplicar aunque la DB no este vacia (idempotente — todas las "
             "migraciones tienen IF NOT EXISTS — pero confirma que sabes lo "
             "que haces).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo lista lo que aplicaria, sin tocar la DB.",
    )
    return p.parse_args()


def prompt_database_url() -> str:
    print("\nNecesito el DATABASE_URL para conectarme. Formato:")
    print("  postgresql://postgres:<password>@<host>:5432/<dbname>")
    print()
    return input("DATABASE_URL: ").strip()


def main() -> int:
    args = parse_args()

    db_url = args.database_url
    if not db_url and not args.dry_run:
        db_url = prompt_database_url()
    if not db_url and not args.dry_run:
        die("DATABASE_URL es obligatorio (via --database-url o env DATABASE_URL)")

    # ── Banner ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  BOOTSTRAP FRESH INSTALL del CRM")
    print("=" * 60)

    # ── Listar archivos ──────────────────────────────────────────
    ddls = list_ddls()
    migs = list_legacy_migrations()

    step("Archivos a aplicar:")
    info(f"DDL base ({len(ddls)} archivos):")
    for p in ddls:
        info(f"  - {p.name}")
    info(f"Migraciones legacy ({len(migs)} archivos):")
    for p in migs[:5]:
        info(f"  - {p.name}")
    if len(migs) > 5:
        info(f"  ... y {len(migs) - 5} mas")

    if args.dry_run:
        print()
        print(">>> DRY RUN — no se conecta a la DB ni se aplica nada.")
        print(f"Total a aplicar: {len(ddls) + len(migs)} archivos")
        return 0

    # ── Conectar y aplicar ──────────────────────────────────────
    step("Conectando a la DB...")
    conn = connect(db_url)
    ok("conectado")

    step("Safety check: la DB esta vacia?")
    check_fresh(conn, args.force)
    if args.force:
        warn("--force activo: saltando safety check")
    else:
        ok("DB vacia, podemos proceder")

    step("Asegurando prerequisitos: uuid-ossp + schemas auth/crm...")
    ensure_prerequisites(conn)
    ok("extension uuid-ossp + schemas auth/crm listos")

    step("Asegurando que crm.schema_migrations existe...")
    ensure_tracker(conn)
    ok("tracker listo")

    step(f"Aplicando {len(ddls)} archivos DDL base...")
    d_ok, d_skip, d_fail = apply_batch(conn, ddls, "DDL")
    if d_fail:
        return 1

    step(f"Aplicando {len(migs)} migraciones legacy...")
    m_ok, m_skip, m_fail = apply_batch(conn, migs, "legacy migrations")
    if m_fail:
        return 1

    # ── Resumen ─────────────────────────────────────────────────
    step("RESUMEN")
    print(f"   DDL aplicadas:           {d_ok}")
    print(f"   DDL skipped (ya en tracker): {d_skip}")
    print(f"   Legacy aplicadas:        {m_ok}")
    print(f"   Legacy skipped:          {m_skip}")
    print(f"   Total fallidas:          {d_fail + m_fail}")

    tables = count_tables_per_schema(conn)
    print()
    info("Tablas creadas por schema:")
    for schema, count in tables.items():
        info(f"  - {schema}:  {count} tablas")

    conn.close()

    # ── Proximos pasos ──────────────────────────────────────────
    step("PROXIMOS PASOS")
    print("""
   1. Deploy del CRM en EasyPanel (o levantar el contenedor).
      El auto-migrator aplica las V040+ que faltan al primer arranque.

   2. Crear el admin inicial:
        curl -X POST https://<dominio>/api/setup/create-admin \\
          -H "Content-Type: application/json" \\
          -d '{"username":"admin","password":"<pass-fuerte>","nombre_completo":"Admin"}'

   3. Verificar:
        curl https://<dominio>/api/health
        curl https://<dominio>/api/setup/status

   4. Login en la UI web, configurar catalogos (estados, fuentes,
      equipos) e invitar al equipo.

   5. Si vas a importar leads de un sistema previo, ver:
        docs/MIGRATION_RUNBOOK.md
""")

    print("=" * 60)
    print("  BOOTSTRAP COMPLETO")
    print("=" * 60)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

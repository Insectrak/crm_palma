"""
Migracion pdr_marketing -> brighton_crm (v2).

Basado en: docs/migracion_pdr_a_brighton.md

Orden:
    1. Limpiar brighton_crm (contactos, leads, usuarios excepto admin)
    2. Crear 12 asesores + 2 supervisores
    3. Leer datos de pdr_marketing (me_asesor, md_leadasignacion, asesorN.md_contactolead)
    4. Insertar leads (5,034) con normalizacion
    5. Determinar estado de cada lead por ultimo contacto
    6. Insertar contactos (1,055)
    7. Verificar resultado

Uso:
    python migrate_pdr_marketing_v2.py --dry-run
    python migrate_pdr_marketing_v2.py
"""
import argparse
import hashlib
import logging
import re
import sys
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("migrate_v2")

# ── Conexiones ───────────────────────────────────────────────────────────────
SRC = {
    "host": "157.90.158.150", "port": 5432, "dbname": "pdr_marketing",
    "user": "postgres", "password": "Pdr_1234",
}
TARGET = {
    "host": "46.224.250.197", "port": 5433, "dbname": "brighton_crm",
    "user": "postgres", "password": "brighton_1234",
}

# ── Mapeo me_asesor.id -> (email, nombre, apellido, rol) ────────────────────
# NOTA: me_asesor.id != me_asesor.asesor_id (tienen gaps)
# me_asesor_id=16 (Diego ex-sup) se EXCLUYE, sus leads se redistribuyen
USERS_TO_CREATE = [
    # (email, first_name, last_name, role, me_asesor_id)
    ("asesor1@palmadelrio.com",  "Paola",    "Cuadros",  "supervisor", 1),
    ("asesor2@palmadelrio.com",  "Rosmary",  "Vilca",    "asesor",     2),
    ("asesor3@palmadelrio.com",  "Solanch",  None,       "asesor",     3),
    ("asesor4@palmadelrio.com",  "Ana",      "Montes",   "asesor",     4),
    ("asesor5@palmadelrio.com",  "Fernando", "Arenas",   "asesor",     5),
    ("asesor6@palmadelrio.com",  "Cinthia",  None,       "asesor",     10),
    ("asesor7@palmadelrio.com",  "Solanch 2", None,      "asesor",     11),
    ("asesor8@palmadelrio.com",  "Noelia",   None,       "asesor",     12),
    ("asesor9@palmadelrio.com",  "Jorge",    None,       "asesor",     13),
    ("asesor10@palmadelrio.com", "Winny",    "Oviedo",   "asesor",     19),
    ("asesor12@palmadelrio.com", "Fabiola",  "Gamero",   "asesor",     24),
    ("asesor13@palmadelrio.com", "Renato",   "Barrios",  "asesor",     25),
    # Supervisor adicional (no existe en viejo sistema)
    ("soporte@brightoninglesnativo.com",   "Diego",    None,       "supervisor", None),
]

# me_asesor.id -> email CRM (para resolver FK en leads)
ME_ASESOR_ID_TO_EMAIL = {
    1:  "asesor1@palmadelrio.com",
    2:  "asesor2@palmadelrio.com",
    3:  "asesor3@palmadelrio.com",
    4:  "asesor4@palmadelrio.com",
    5:  "asesor5@palmadelrio.com",
    10: "asesor6@palmadelrio.com",
    11: "asesor7@palmadelrio.com",
    12: "asesor8@palmadelrio.com",
    13: "asesor9@palmadelrio.com",
    19: "asesor10@palmadelrio.com",
    24: "asesor12@palmadelrio.com",
    25: "asesor13@palmadelrio.com",
}

# Diego ex-sup (me_asesor_id=16): redistribuir 50/50
DIEGO_ME_ASESOR_ID = 16
DIEGO_SPLIT_EMAILS = ["asesor4@palmadelrio.com", "asesor8@palmadelrio.com"]

PASSWORD_GENERIC = "Palma.2026"


# ── Normalizacion ────────────────────────────────────────────────────────────

def clean_phone(raw):
    """Normaliza telefono a +51XXXXXXXXX o None si invalido."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits or set(digits) == {"0"} or len(digits) < 7:
        return None
    if len(digits) == 9:
        return "+51" + digits
    if len(digits) == 11 and digits.startswith("51"):
        return "+" + digits
    if len(digits) == 12 and digits.startswith("51"):
        return "+" + digits
    # Otros formatos raros: devolver con + si tiene >7 digitos
    if 7 <= len(digits) <= 15:
        return "+" + digits if not digits.startswith("+") else digits
    return None


def norm_fuente(raw):
    """Normaliza 95+ valores sucios de plataforma a fuentes CRM."""
    if not raw:
        return "marketing"
    s = str(raw).strip().lower()

    if any(k in s for k in ("face", "fb")):
        return "fb"
    if any(k in s for k in ("insta", "ig")):
        return "ig"
    if any(k in s for k in ("tik", "tt")):
        return "tt mensaje"
    if any(k in s for k in ("whats", "wa")):
        return "wa mensaje"
    if "web" in s:
        return "web"
    if "feria" in s:
        return "feria"
    if any(k in s for k in ("activ", "hospit", "rally", "fullday", "full day",
                             "playa", "conrede", "acomare")):
        return "activacion"
    if s in ("hd", "hm") or s == "h":
        return "activacion"
    if "referido" in s:
        return "referido"
    if "oficina" in s:
        return "marketing"
    return "marketing"


def norm_estado_contacto(raw):
    """Mapea estado_contacto_lead (del viejo) a estado CRM."""
    if not raw:
        return "Contactado"
    s = str(raw).strip().lower()

    if "venta" in s:
        return "Ganado"
    if any(k in s for k in ("reserva", "cita")):
        return "En negociación"
    if any(k in s for k in ("interesado", "cliente potencial")):
        return "Calificado"
    if any(k in s for k in ("desist", "desestim", "no interesado")):
        return "No interesado"
    if "no contactado" in s:
        return "Nuevo"
    # seguimiento, no responde, corta llamada, sin_estado, null, etc.
    return "Contactado"


def norm_tipo_contacto(raw):
    """Limpia tipo_contacto_lead a tipos CRM."""
    if not raw:
        return "llamada"
    s = str(raw).strip().lower()
    if "llamada" in s:
        return "llamada"
    if "mensaje" in s:
        return "mensaje"
    if "cita" in s:
        return "cita"
    return "llamada"


def split_nombre(full):
    """Divide nombre_lead en (nombres, apellidos)."""
    if not full:
        return ("Sin nombre", None)
    parts = str(full).strip().split()
    if not parts:
        return ("Sin nombre", None)
    if len(parts) == 1:
        return (parts[0], None)
    mid = len(parts) // 2 or 1
    return (" ".join(parts[:mid]), " ".join(parts[mid:]))


def make_hash_dedup(telefono, fuente_externa_id=None):
    """SHA256(telefono + fuente_externa_id) para deduplicacion."""
    raw = (telefono or "") + (fuente_externa_id or "")
    return hashlib.sha256(raw.encode()).hexdigest() if raw else None


@contextmanager
def pg(cfg):
    conn = psycopg2.connect(**cfg)
    try:
        yield conn
    finally:
        conn.close()


# ── FASE 1: Leer source ─────────────────────────────────────────────────────

def read_source():
    """Lee todo de pdr_marketing y cierra la conexion."""
    log.info("=== FASE 1: Leyendo source (pdr_marketing) ===")
    data = {}

    with pg(SRC) as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # me_asesor: mapeo id -> asesor_id
        cur.execute("SELECT id, asesor_id, nbrasesor FROM public.me_asesor")
        rows = cur.fetchall()
        data["me_asesor"] = {r["id"]: r for r in rows}
        log.info("  me_asesor: %d registros", len(data["me_asesor"]))

        # md_leadasignacion: fuente principal de leads
        cur.execute("""
            SELECT lead_id, nombre_lead, celular_lead, correo_lead,
                   plataforma, proyecto_campania, city_lead, job_lead,
                   estado_lead, me_asesor_id, observaciones,
                   fecha_ingreso_lead, intentos_contacto_lead
            FROM public.md_leadasignacion
        """)
        data["leads"] = cur.fetchall()
        log.info("  md_leadasignacion: %d leads", len(data["leads"]))

        # asesorN.md_contactolead (schemas 1..13)
        data["contactos"] = []
        for n in range(1, 14):
            schema = f"asesor{n}"
            try:
                cur.execute(f"""
                    SELECT codigo_lead, tipo_contacto_lead,
                           estado_contacto_lead, seguimiento_lead,
                           observaciones, fecha_contacto_lead,
                           fecha_cita_lead, tipo_cita_lead
                    FROM {schema}.md_contactolead
                """)
                rows = cur.fetchall()
                for r in rows:
                    r["_schema"] = schema
                data["contactos"].extend(rows)
                log.info("    %s: %d contactos", schema, len(rows))
            except psycopg2.Error:
                conn.rollback()
                log.info("    %s: no existe o vacia", schema)

        log.info("  Total contactos: %d", len(data["contactos"]))

    log.info("=== Source cerrado. Datos en memoria. ===")
    return data


# ── FASE 2: Limpiar + escribir target ────────────────────────────────────────

def write_target(data, dry_run=False):
    log.info("=== FASE 2: Escribiendo en target (brighton_crm) ===")

    with pg(TARGET) as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # ── Paso 1: Limpiar ──
        log.info("[1/6] Limpiando target...")
        cur.execute("DELETE FROM crm.contactos")
        log.info("    contactos eliminados: %d", cur.rowcount)
        cur.execute("DELETE FROM crm.llamadas")
        log.info("    llamadas eliminadas: %d", cur.rowcount)
        cur.execute("DELETE FROM crm.asignaciones_log")
        log.info("    asignaciones_log eliminados: %d", cur.rowcount)
        cur.execute("DELETE FROM crm.leads")
        log.info("    leads eliminados: %d", cur.rowcount)
        cur.execute("DELETE FROM crm.round_robin_estado")
        log.info("    round_robin_estado eliminados: %d", cur.rowcount)
        cur.execute("DELETE FROM crm.equipos")
        log.info("    equipos eliminados: %d", cur.rowcount)
        cur.execute("DELETE FROM auth.user_sessions")
        log.info("    user_sessions eliminados: %d", cur.rowcount)
        cur.execute("DELETE FROM auth.users WHERE role != 'admin'")
        log.info("    users eliminados (no-admin): %d", cur.rowcount)

        # ── Paso 2: Crear usuarios ──
        log.info("[2/6] Creando usuarios...")
        users_created = 0
        for email, fname, lname, role, _ in USERS_TO_CREATE:
            cur.execute("""
                INSERT INTO auth.users (email, password_hash, first_name, last_name,
                                        role, is_active, is_verified)
                VALUES (%s, crypt(%s, gen_salt('bf')), %s, %s, %s, TRUE, TRUE)
                ON CONFLICT (email) DO NOTHING
                RETURNING id
            """, (email, PASSWORD_GENERIC, fname, lname, role))
            if cur.fetchone():
                users_created += 1
        log.info("    usuarios creados: %d", users_created)

        # Cargar mapas del target
        cur.execute("SELECT id::text, email FROM auth.users")
        email_to_uuid = {r["email"]: r["id"] for r in cur.fetchall()}

        cur.execute("SELECT id, LOWER(nombre) AS nombre FROM crm.fuentes WHERE activo = TRUE")
        fuentes_map = {r["nombre"]: r["id"] for r in cur.fetchall()}

        cur.execute("SELECT id, nombre FROM crm.estados_lead")
        estados_map = {r["nombre"]: r["id"] for r in cur.fetchall()}

        log.info("    maps: %d users, %d fuentes, %d estados",
                 len(email_to_uuid), len(fuentes_map), len(estados_map))

        # ── Paso 3: Crear equipos (supervisor -> asesores) ──
        log.info("[3/6] Creando equipos...")
        # Paola supervisa a todos los asesores por defecto
        paola_uuid = email_to_uuid.get("asesor1@palmadelrio.com")
        if paola_uuid:
            for email, _, _, role, _ in USERS_TO_CREATE:
                if role == "asesor":
                    asesor_uuid = email_to_uuid.get(email)
                    if asesor_uuid:
                        cur.execute("""
                            INSERT INTO crm.equipos (supervisor_id, asesor_id, activo)
                            VALUES (%s::uuid, %s::uuid, TRUE)
                            ON CONFLICT (asesor_id) DO NOTHING
                        """, (paola_uuid, asesor_uuid))
            log.info("    equipos creados bajo Paola")

        # ── Paso 4: Insertar leads ──
        log.info("[4/6] Insertando %d leads...", len(data["leads"]))

        # Construir indice de ultimo contacto por lead_id
        # para determinar estado CRM
        ultimo_contacto = {}  # lead_id -> {estado_contacto_lead, fecha}
        for c in data["contactos"]:
            lid = str(c["codigo_lead"])
            fecha = c["fecha_contacto_lead"]
            if lid not in ultimo_contacto or (fecha and (
                    not ultimo_contacto[lid]["fecha"] or
                    fecha > ultimo_contacto[lid]["fecha"])):
                ultimo_contacto[lid] = {
                    "estado": c["estado_contacto_lead"],
                    "fecha": fecha,
                }

        diego_counter = [0]

        def resolve_asesor(me_asesor_id):
            """Resuelve me_asesor_id a UUID del usuario CRM."""
            if me_asesor_id == DIEGO_ME_ASESOR_ID:
                email = DIEGO_SPLIT_EMAILS[diego_counter[0] % 2]
                diego_counter[0] += 1
                return email_to_uuid.get(email)
            email = ME_ASESOR_ID_TO_EMAIL.get(me_asesor_id)
            return email_to_uuid.get(email) if email else None

        old_to_new = {}  # lead_id original -> crm.leads.id
        inserted = 0
        skipped_tel = 0
        skipped_asesor = 0

        for r in data["leads"]:
            tel = clean_phone(r["celular_lead"])
            if not tel:
                skipped_tel += 1
                continue

            nombres, apellidos = split_nombre(r["nombre_lead"])
            fuente_nombre = norm_fuente(r["plataforma"])
            fuente_id = fuentes_map.get(fuente_nombre)

            # Estado: determinado por ultimo contacto, no por estado_lead
            lid_str = str(r["lead_id"])
            if lid_str in ultimo_contacto:
                estado_nombre = norm_estado_contacto(
                    ultimo_contacto[lid_str]["estado"])
            else:
                estado_nombre = "Nuevo"
            estado_id = estados_map.get(estado_nombre, estados_map.get("Nuevo"))

            asesor_uuid = resolve_asesor(r["me_asesor_id"])
            if not asesor_uuid:
                skipped_asesor += 1
                continue

            hash_dedup = make_hash_dedup(tel, str(r["lead_id"]))

            # Observaciones: combinar city, job, obs original
            obs_parts = []
            if r.get("city_lead"):
                obs_parts.append(f"Ciudad: {r['city_lead'].strip()}")
            if r.get("job_lead"):
                obs_parts.append(f"Trabajo: {r['job_lead'].strip()}")
            if r.get("observaciones"):
                obs_parts.append(r["observaciones"].strip())
            observaciones = " | ".join(obs_parts) if obs_parts else None

            email_raw = (r.get("correo_lead") or "").strip().lower() or None
            # Solo guardar como email si contiene @, sino mover a observaciones
            if email_raw and "@" in email_raw:
                email_lead = email_raw
            else:
                email_lead = None
                if email_raw:
                    obs_parts.append(f"Email orig: {email_raw}")
            campana = (r.get("proyecto_campania") or "").strip() or None

            cur.execute("""
                INSERT INTO crm.leads
                    (nombres, apellidos, telefono, email, campana,
                     fuente_id, estado_id, asesor_id,
                     observaciones, intentos_contacto,
                     created_at, activo, hash_dedup)
                VALUES (%s, %s, %s, %s, %s,
                        %s, %s, %s::uuid,
                        %s, %s,
                        %s, TRUE, %s)
                ON CONFLICT (hash_dedup) DO NOTHING
                RETURNING id
            """, (nombres, apellidos, tel, email_lead, campana,
                  fuente_id, estado_id, asesor_uuid,
                  observaciones, r.get("intentos_contacto_lead") or 0,
                  r["fecha_ingreso_lead"], hash_dedup))

            row = cur.fetchone()
            if row:
                old_to_new[lid_str] = row["id"]
                inserted += 1

        log.info("    insertados=%d, skip_tel=%d, skip_asesor=%d, total_mapeados=%d",
                 inserted, skipped_tel, skipped_asesor, len(old_to_new))

        # ── Paso 5: Insertar contactos ──
        log.info("[5/6] Insertando %d contactos...", len(data["contactos"]))
        c_ok = 0
        c_skip = 0

        for c in data["contactos"]:
            new_lead_id = old_to_new.get(str(c["codigo_lead"]))
            if not new_lead_id:
                c_skip += 1
                continue

            tipo = norm_tipo_contacto(c["tipo_contacto_lead"])
            resultado = norm_estado_contacto(c["estado_contacto_lead"])

            notas_parts = []
            if c.get("seguimiento_lead"):
                notas_parts.append(c["seguimiento_lead"].strip())
            if c.get("observaciones"):
                notas_parts.append(c["observaciones"].strip())
            notas = " | ".join(notas_parts) if notas_parts else None

            cur.execute("""
                INSERT INTO crm.contactos
                    (lead_id, tipo_contacto, resultado, notas,
                     fecha_cita, tipo_cita, created_at, origen)
                VALUES (%s, %s, %s, %s,
                        %s, %s, %s, 'pdr_migration')
            """, (new_lead_id, tipo, resultado, notas,
                  c.get("fecha_cita_lead"),
                  c.get("tipo_cita_lead"),
                  c["fecha_contacto_lead"]))
            c_ok += 1

        log.info("    contactos insertados=%d, sin_match=%d", c_ok, c_skip)

        # ── Paso 6: Verificar ──
        log.info("[6/6] Verificando...")
        cur.execute("""
            SELECT e.nombre, COUNT(l.id) AS total
            FROM crm.estados_lead e
            LEFT JOIN crm.leads l ON l.estado_id = e.id AND l.activo = TRUE
            GROUP BY e.nombre, e.orden
            ORDER BY e.orden
        """)
        for r in cur.fetchall():
            log.info("    %-20s %d", r["nombre"], r["total"])

        cur.execute("SELECT COUNT(*) AS total FROM crm.leads WHERE activo = TRUE")
        total_leads = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(*) AS total FROM crm.contactos")
        total_contactos = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(*) AS total FROM auth.users WHERE role != 'admin'")
        total_users = cur.fetchone()["total"]

        log.info("=== RESUMEN FINAL ===")
        log.info("  Usuarios creados: %d", total_users)
        log.info("  Leads migrados:   %d", total_leads)
        log.info("  Contactos:        %d", total_contactos)

        if dry_run:
            conn.rollback()
            log.warning("DRY-RUN: rollback. Nada escrito en la base.")
        else:
            conn.commit()
            log.info("COMMIT OK. Migracion completada.")


def main():
    ap = argparse.ArgumentParser(description="Migracion pdr_marketing -> brighton_crm v2")
    ap.add_argument("--dry-run", action="store_true",
                    help="Ejecuta todo pero hace rollback al final")
    args = ap.parse_args()

    log.info("=== Migracion v2 — dry_run=%s ===", args.dry_run)

    data = read_source()
    write_target(data, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

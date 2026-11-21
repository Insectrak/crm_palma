"""
Migracion pdr_marketing -> brighton_crm (dev/prod).

Uso:
    python migrate_pdr_marketing.py --target dev --dry-run
    python migrate_pdr_marketing.py --target dev
    python migrate_pdr_marketing.py --target prod

Orden:
    1. Leads        (md_leadconsolidado + md_leadasignacion  -> crm.leads)
    2. Contactos    (asesorN.md_contactolead                 -> crm.contactos)
    3. Citas        (public.todas_las_citas_asesores         -> crm.contactos tipo=cita)
    4. Historico    (leadhistorico.mh_leadconsolidadohistorico -> crm_legacy.leads_historico)

Estrategia: lee TODO del source primero (en memoria), cierra source,
luego escribe al target. Evita timeout del source por inactividad.
"""
import argparse
import logging
import re
import sys
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("migrate_pdr")

SRC = {"host": "157.90.158.150", "port": 5432, "dbname": "pdr_marketing",
       "user": "postgres", "password": "Pdr_1234"}
TARGETS = {
    "dev":  {"host": "brighton.com", "port": 5435, "dbname": "brighton_crm_dev",
             "user": "postgresdev", "password": "brightondev_1234"},
    "prod": {"host": "46.224.250.197", "port": 5433, "dbname": "brighton_crm",
             "user": "postgres", "password": "brighton_1234"},
}

ASESOR_EMAIL = {
    "1": "asesor1@palmadelrio.com",
    "2": "asesor2@palmadelrio.com",
    "3": "asesor3@palmadelrio.com",
    "4": "asesor4@palmadelrio.com",
    "5": "asesor5@palmadelrio.com",
    "6": "asesor6@palmadelrio.com",
    "7": "asesor3@palmadelrio.com",   # Solanch 2 -> fusion
    "8": "asesor8@palmadelrio.com",
    "9": "asesor9@palmadelrio.com",
    "10":"asesor10@palmadelrio.com",
    "12":"asesor12@palmadelrio.com",
    "13":"asesor13@palmadelrio.com",
}
DIEGO_SPLIT = ["asesor4@palmadelrio.com", "asesor8@palmadelrio.com"]


def clean_phone(raw):
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits or set(digits) == {"0"}:
        return None
    if len(digits) == 9:
        return "+51" + digits
    if len(digits) == 11 and digits.startswith("51"):
        return "+" + digits
    if 7 <= len(digits) <= 15:
        return digits
    return None


def norm_fuente(raw):
    if not raw:
        return "marketing"
    s = str(raw).strip().lower()
    if "face" in s or s in ("fb", "fb ads", "facebook ads"): return "fb"
    if "insta" in s or s == "ig":                             return "ig"
    if "tik"  in s or s.startswith("tt"):                     return "tt mensaje"
    if "whats" in s or s.startswith("wa"):                    return "wa mensaje"
    if "feria" in s:                                          return "feria"
    if "activ" in s:                                          return "activacion"
    return "marketing"


def norm_estado(raw):
    if not raw:
        return "Nuevo"
    s = str(raw).strip().lower()
    if "nuevo" in s:    return "Nuevo"
    if "contact" in s:  return "Contactado"
    if "calif" in s:    return "Calificado"
    if "cita" in s:     return "Cita"
    if "venta" in s or "cerrado" in s or "gan" in s: return "Ganado"
    if "perd" in s or "descart" in s:                return "Perdido"
    return "Nuevo"


def split_nombre(full):
    if not full:
        return ("Sin nombre", None)
    parts = str(full).strip().split()
    if not parts:
        return ("Sin nombre", None)
    if len(parts) == 1:
        return (parts[0], None)
    mid = len(parts) // 2 or 1
    return (" ".join(parts[:mid]), " ".join(parts[mid:]))


@contextmanager
def pg(cfg):
    conn = psycopg2.connect(**cfg)
    try:
        yield conn
    finally:
        conn.close()


# ── FASE 1: Leer todo del source ─────────────────────────────────────────────

def read_all_source(cfg):
    log.info("=== Leyendo todo del source ===")
    data = {}

    with pg(cfg) as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # me_asesor map: id(int) -> asesor_id(text)
        cur.execute("SELECT id, asesor_id FROM public.me_asesor")
        data["asesor_map"] = {r["id"]: str(r["asesor_id"]) for r in cur.fetchall() if r["asesor_id"]}
        log.info("  me_asesor: %d", len(data["asesor_map"]))

        # leads consolidado + asignacion
        cur.execute("""
            SELECT c.lead_id, c.nombre_lead, c.celular_lead, c.correo_lead,
                   c.plataforma, c.proyecto_campania, c.city_lead, c.job_lead,
                   c.observaciones, c.fecha_ingreso_lead, c.me_asesor_id AS cons_asesor,
                   a.estado_lead, a.me_asesor_id AS asig_asesor
            FROM public.md_leadconsolidado c
            LEFT JOIN public.md_leadasignacion a USING (lead_id)
        """)
        data["leads"] = cur.fetchall()
        log.info("  leads: %d", len(data["leads"]))

        # contactos de cada schema asesorN
        data["contactos"] = []
        for n in range(1, 14):
            try:
                cur.execute(f"""
                    SELECT codigo_lead, tipo_contacto_lead, seguimiento_lead,
                           fecha_contacto_lead, observaciones, fecha_cita_lead, tipo_cita_lead
                    FROM asesor{n}.md_contactolead
                """)
                rows = cur.fetchall()
                data["contactos"].extend(rows)
            except psycopg2.Error:
                conn.rollback()
        log.info("  contactos: %d", len(data["contactos"]))

        # citas
        cur.execute("""
            SELECT codigo_lead, tipo_contacto_lead, seguimiento_lead,
                   fecha_contacto_lead, observaciones, fecha_cita_lead, tipo_cita_lead
            FROM public.todas_las_citas_asesores
        """)
        data["citas"] = cur.fetchall()
        log.info("  citas: %d", len(data["citas"]))

        # historico
        cur.execute("""
            SELECT numcelularlead, nbrlead, descorreolectroniconico, numdni,
                   desproyecto, descanallead, nbrasesor, estadolead,
                   desseguimiento, descobservacionnlead, desubicacionlead,
                   fechingresolead
            FROM leadhistorico.mh_leadconsolidadohistorico
        """)
        data["historico"] = cur.fetchall()
        log.info("  historico: %d", len(data["historico"]))

    log.info("=== Source cerrado. Datos en memoria. ===")
    return data


# ── FASE 2: Escribir en target ───────────────────────────────────────────────

def write_all_target(cfg, data, dry_run):
    log.info("=== Escribiendo en target ===")

    with pg(cfg) as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Mapas del target
        cur.execute("SELECT id, LOWER(nombre) AS nombre FROM crm.fuentes WHERE activo = TRUE")
        fuentes = {r["nombre"]: r["id"] for r in cur.fetchall()}
        cur.execute("SELECT id, nombre FROM crm.estados_lead")
        estados = {r["nombre"]: r["id"] for r in cur.fetchall()}
        cur.execute("SELECT id::text AS id, email FROM auth.users")
        users = {r["email"]: r["id"] for r in cur.fetchall()}
        log.info("  maps: %d fuentes, %d estados, %d users",
                 len(fuentes), len(estados), len(users))

        asesor_map = data["asesor_map"]
        diego_counter = [0]

        def resolve_asesor(me_asesor_id):
            txt = asesor_map.get(me_asesor_id)
            if not txt:
                return None
            if txt == "11":
                email = DIEGO_SPLIT[diego_counter[0] % 2]
                diego_counter[0] += 1
            else:
                email = ASESOR_EMAIL.get(txt)
            return users.get(email) if email else None

        # ── 1. Leads ──
        log.info("[1/4] Insertando %d leads...", len(data["leads"]))
        old_to_new = {}
        inserted = 0
        skipped_tel = 0

        for r in data["leads"]:
            tel = clean_phone(r["celular_lead"])
            if not tel:
                skipped_tel += 1
                continue

            nombres, apellidos = split_nombre(r["nombre_lead"])
            fuente_id = fuentes.get(norm_fuente(r["plataforma"]))
            estado_id = estados.get(norm_estado(r["estado_lead"]))
            asesor_uuid = resolve_asesor(r["asig_asesor"] or r["cons_asesor"])

            cur.execute("""
                INSERT INTO crm.leads
                    (nombres, apellidos, telefono, email, campana, ciudad, trabajo,
                     fuente_id, estado_id, asesor_id, observaciones, created_at, activo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                ON CONFLICT (hash_dedup) DO NOTHING
                RETURNING id
            """, (nombres, apellidos, tel,
                  (r["correo_lead"] or "").strip().lower() or None,
                  (r["proyecto_campania"] or "").strip() or None,
                  (r["city_lead"] or "").strip() or None,
                  (r["job_lead"] or "").strip() or None,
                  fuente_id, estado_id, asesor_uuid,
                  (r["observaciones"] or "").strip() or None,
                  r["fecha_ingreso_lead"]))
            row = cur.fetchone()
            if row:
                old_to_new[str(r["lead_id"])] = row["id"]
                inserted += 1
            else:
                cur.execute("SELECT id FROM crm.leads WHERE telefono = %s LIMIT 1", (tel,))
                ex = cur.fetchone()
                if ex:
                    old_to_new[str(r["lead_id"])] = ex["id"]

        log.info("    insertados=%d, skip_tel=%d, mapeados=%d",
                 inserted, skipped_tel, len(old_to_new))

        # ── 2. Contactos ──
        log.info("[2/4] Insertando %d contactos...", len(data["contactos"]))
        c_ok = 0
        c_skip = 0
        for c in data["contactos"]:
            new_id = old_to_new.get(str(c["codigo_lead"]))
            if not new_id:
                c_skip += 1
                continue
            notas = " | ".join(filter(None, [
                (c["seguimiento_lead"] or "").strip() or None,
                (c["observaciones"] or "").strip() or None,
            ])) or None
            cur.execute("""
                INSERT INTO crm.contactos
                    (lead_id, tipo_contacto, notas, fecha_cita, tipo_cita, created_at, origen)
                VALUES (%s, %s, %s, %s, %s, %s, 'pdr_migration')
            """, (new_id,
                  (c["tipo_contacto_lead"] or "llamada")[:50],
                  notas, c["fecha_cita_lead"],
                  (c["tipo_cita_lead"] or None),
                  c["fecha_contacto_lead"]))
            c_ok += 1
        log.info("    insertados=%d, sin_match=%d", c_ok, c_skip)

        # ── 3. Citas ──
        log.info("[3/4] Insertando %d citas...", len(data["citas"]))
        ci_ok = 0
        ci_skip = 0
        for c in data["citas"]:
            new_id = old_to_new.get(str(c["codigo_lead"]))
            if not new_id:
                ci_skip += 1
                continue
            notas = " | ".join(filter(None, [
                (c["seguimiento_lead"] or "").strip() or None,
                (c["observaciones"] or "").strip() or None,
            ])) or None
            cur.execute("""
                INSERT INTO crm.contactos
                    (lead_id, tipo_contacto, notas, fecha_cita, tipo_cita, created_at, origen)
                VALUES (%s, 'cita', %s, %s, %s, %s, 'pdr_migration')
            """, (new_id, notas, c["fecha_cita_lead"],
                  (c["tipo_cita_lead"] or None), c["fecha_contacto_lead"]))
            ci_ok += 1
        log.info("    insertados=%d, sin_match=%d", ci_ok, ci_skip)

        # ── 4. Historico ──
        log.info("[4/4] Insertando %d historicos...", len(data["historico"]))
        for r in data["historico"]:
            tel = str(r["numcelularlead"] or "")
            tel_norm = re.sub(r"\D", "", tel) or None
            fecha = r["fechingresolead"]
            if isinstance(fecha, str):
                try:
                    from datetime import date
                    y, m, d = fecha[:10].split("-")
                    fecha = date(int(y), int(m), int(d))
                except Exception:
                    fecha = None
            cur.execute("""
                INSERT INTO crm_legacy.leads_historico
                    (telefono, telefono_norm, nombre, email, dni, proyecto, canal,
                     asesor_nombre, estado, seguimiento, observaciones, ciudad, fecha_ingreso)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (tel or None, tel_norm,
                  (r["nbrlead"] or "").strip() or None,
                  r["descorreolectroniconico"], r["numdni"],
                  r["desproyecto"], r["descanallead"],
                  r["nbrasesor"], r["estadolead"], r["desseguimiento"],
                  r["descobservacionnlead"], r["desubicacionlead"], fecha))
        log.info("    done")

        # ── Resultado ──
        if dry_run:
            conn.rollback()
            log.warning("DRY-RUN: rollback. Nada escrito.")
        else:
            conn.commit()
            log.info("COMMIT OK.")

        log.info("=== RESUMEN: leads=%d, contactos=%d, citas=%d, historico=%d ===",
                 inserted, c_ok, ci_ok, len(data["historico"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=("dev", "prod"), default="dev")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    log.info("Target=%s  dry-run=%s", args.target, args.dry_run)

    data = read_all_source(SRC)
    write_all_target(TARGETS[args.target], data, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Repositorio de formularios públicos — capa de acceso a datos.

SRP: esta capa SOLO habla SQL. No hay reglas de negocio, validación de
permisos, ni generación de slugs — todo eso vive en el service.
DIP:   los consumidores (services, routers) dependen de estas funciones,
       no de los detalles del SQL.

Tablas gestionadas:
  - crm.public_forms            (definición del form)
  - crm.public_form_submissions (log de submissions para audit/rate limit)
  - crm.leads (para inserción de leads desde submits públicos)
"""
from __future__ import annotations

import json
from typing import Optional, Any
from psycopg2.extras import RealDictCursor
from app.database import get_db


# ── Forms CRUD ────────────────────────────────────────────────────────────────

def create_form(
    *,
    slug: str,
    titulo: str,
    descripcion: Optional[str],
    nombre_evento: Optional[str],
    empresa: Optional[str],
    fuente_id: Optional[int],
    campana: Optional[str],
    asignado_a: str,
    created_by: str,
    config: dict,
    expires_at: Optional[str],
    max_submissions: Optional[int],
    sede_id_default: Optional[str] = None,  # V065
) -> dict:
    """Inserta un nuevo form y devuelve el registro completo."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO crm.public_forms (
                    slug, titulo, descripcion, nombre_evento, empresa,
                    fuente_id, campana, asignado_a, created_by, config,
                    expires_at, max_submissions, sede_id_default
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb,
                    %s, %s,
                    CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END
                )
                RETURNING *
                """,
                (
                    slug, titulo, descripcion, nombre_evento, empresa,
                    fuente_id, campana, asignado_a, created_by, json.dumps(config),
                    expires_at, max_submissions,
                    sede_id_default, sede_id_default,
                ),
            )
            conn.commit()
            return cur.fetchone()


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Obtiene datos básicos de un usuario por su UUID."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text AS id, email, first_name, last_name, role, is_active
                FROM auth.users
                WHERE id = %s::uuid
                """,
                (user_id,),
            )
            return cur.fetchone()


def list_eligible_assignees(current_user: Any) -> list[dict]:
    """Lista usuarios activos elegibles para ser asignatarios de un formulario público."""
    from app.constants import Role
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if current_user.role == Role.ADMIN.value:
                cur.execute(
                    """
                    SELECT u.id::text AS id,
                           COALESCE(NULLIF(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')), ''), u.email) AS nombre,
                           u.email,
                           u.role
                    FROM auth.users u
                    WHERE u.is_active = TRUE
                      AND u.role IN ('asesor', 'supervisor', 'admin')
                    ORDER BY
                      CASE WHEN u.role = 'supervisor' THEN 1 WHEN u.role = 'asesor' THEN 2 ELSE 3 END,
                      u.first_name, u.last_name, u.email
                    """
                )
                return cur.fetchall()

            if current_user.role == Role.SUPERVISOR.value:
                cur.execute(
                    """
                    SELECT DISTINCT u.id::text AS id,
                           COALESCE(NULLIF(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')), ''), u.email) AS nombre,
                           u.email,
                           u.role
                    FROM auth.users u
                    WHERE u.is_active = TRUE
                      AND (
                        u.id = %s::uuid
                        OR u.id IN (
                            SELECT eq.asesor_id FROM crm.equipos eq
                            WHERE (
                                eq.supervisor_id = %s::uuid
                                OR eq.supervisor_id IN (
                                    SELECT s.id FROM auth.users s
                                    WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'
                                )
                            ) AND eq.activo = TRUE
                        )
                        OR u.id IN (
                            SELECT s.id FROM auth.users s
                            WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'
                        )
                      )
                    ORDER BY
                      CASE WHEN u.id = %s::uuid THEN 1 WHEN u.role = 'supervisor' THEN 2 ELSE 3 END,
                      u.first_name, u.last_name, u.email
                    """,
                    (
                        current_user.user_id,
                        current_user.user_id,
                        current_user.user_id,
                        current_user.user_id,
                        current_user.user_id,
                    ),
                )
                return cur.fetchall()

            # Asesor con permiso formularios.manage
            cur.execute(
                """
                SELECT DISTINCT u.id::text AS id,
                       COALESCE(NULLIF(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')), ''), u.email) AS nombre,
                       u.email,
                       u.role
                FROM auth.users u
                WHERE u.is_active = TRUE
                  AND (
                    u.id = %s::uuid
                    OR u.id IN (
                        SELECT eq.supervisor_id FROM crm.equipos eq
                        WHERE eq.asesor_id = %s::uuid AND eq.activo = TRUE
                    )
                  )
                ORDER BY CASE WHEN u.id = %s::uuid THEN 1 ELSE 2 END, u.first_name, u.last_name, u.email
                """,
                (current_user.user_id, current_user.user_id, current_user.user_id),
            )
            return cur.fetchall()


def get_form_by_id(form_id: str) -> Optional[dict]:
    """Devuelve el form por id o None si no existe."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT pf.*,
                       TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS creador_nombre,
                       TRIM(COALESCE(ua.first_name,'') || ' ' || COALESCE(ua.last_name,'')) AS asignado_nombre,
                       ua.role AS asignado_rol,
                       ua.email AS asignado_email
                FROM crm.public_forms pf
                LEFT JOIN auth.users u  ON u.id = pf.created_by
                LEFT JOIN auth.users ua ON ua.id = pf.asignado_a
                WHERE pf.id = %s
                """,
                (form_id,),
            )
            return cur.fetchone()


def get_form_by_slug(slug: str) -> Optional[dict]:
    """Devuelve el form por slug — usado por el endpoint público."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM crm.public_forms WHERE slug = %s",
                (slug,),
            )
            return cur.fetchone()


def slug_exists(slug: str) -> bool:
    """True si ya existe un form con ese slug."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM crm.public_forms WHERE slug = %s LIMIT 1",
                (slug,),
            )
            return cur.fetchone() is not None


def list_forms_by_creator(created_by: str, include_archived: bool = False) -> list[dict]:
    """Lista los forms visibles para un creador o asignatario, ordenados por fecha desc."""
    where = "(pf.created_by = %s OR pf.asignado_a = %s)"
    if not include_archived:
        where += " AND pf.activo = TRUE"
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT pf.*,
                       f.nombre AS fuente_nombre,
                       TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS creador_nombre,
                       TRIM(COALESCE(ua.first_name,'') || ' ' || COALESCE(ua.last_name,'')) AS asignado_nombre,
                       ua.role AS asignado_rol,
                       ua.email AS asignado_email,
                       (
                         SELECT COUNT(*)::int
                         FROM crm.leads l
                         WHERE l.origen_form_id = pf.id AND l.activo = TRUE
                       ) AS leads_count
                FROM crm.public_forms pf
                LEFT JOIN crm.fuentes f ON f.id = pf.fuente_id
                LEFT JOIN auth.users u  ON u.id = pf.created_by
                LEFT JOIN auth.users ua ON ua.id = pf.asignado_a
                WHERE {where}
                ORDER BY pf.created_at DESC
                """,
                (created_by, created_by),
            )
            return cur.fetchall()


def list_all_forms(include_archived: bool = False) -> list[dict]:
    """Lista todos los forms (solo admin puede ver esto)."""
    where = "1=1" if include_archived else "pf.activo = TRUE"
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT pf.*,
                       f.nombre AS fuente_nombre,
                       TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS creador_nombre,
                       TRIM(COALESCE(ua.first_name,'') || ' ' || COALESCE(ua.last_name,'')) AS asignado_nombre,
                       ua.role AS asignado_rol,
                       ua.email AS asignado_email,
                       (
                         SELECT COUNT(*)::int
                         FROM crm.leads l
                         WHERE l.origen_form_id = pf.id AND l.activo = TRUE
                       ) AS leads_count
                FROM crm.public_forms pf
                LEFT JOIN crm.fuentes f ON f.id = pf.fuente_id
                LEFT JOIN auth.users u  ON u.id = pf.created_by
                LEFT JOIN auth.users ua ON ua.id = pf.asignado_a
                WHERE {where}
                ORDER BY pf.created_at DESC
                """,
            )
            return cur.fetchall()


def update_form(form_id: str, fields: dict) -> Optional[dict]:
    """Actualiza campos permitidos del form. Devuelve el form actualizado.

    fields puede contener cualquier subconjunto de: titulo, descripcion,
    nombre_evento, empresa, fuente_id, campana, config, activo, expires_at,
    max_submissions, sede_id_default, asignado_a. Los keys no reconocidos se ignoran silenciosamente.
    """
    # Whitelist defensiva — nunca confiar en dict entrante
    allowed = {
        "titulo", "descripcion", "nombre_evento", "empresa",
        "fuente_id", "campana", "config",
        "activo", "expires_at", "max_submissions",
        "sede_id_default", "asignado_a",
    }
    updates: dict[str, Any] = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_form_by_id(form_id)

    set_parts: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        if key == "config":
            set_parts.append("config = %s::jsonb")
            values.append(json.dumps(value))
        elif key == "sede_id_default":
            # V065: cast a uuid; acepta NULL para limpiar.
            set_parts.append("sede_id_default = CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END")
            values.append(value)
            values.append(value)
            continue
        elif key == "asignado_a":
            set_parts.append("asignado_a = %s::uuid")
            values.append(value)
        else:
            set_parts.append(f"{key} = %s")
            values.append(value)
    values.append(form_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.public_forms SET {', '.join(set_parts)} WHERE id = %s RETURNING id",
                values,
            )
            conn.commit()
            return get_form_by_id(form_id)


def archive_form(form_id: str) -> bool:
    """Marca el form como inactivo (soft delete). Devuelve True si hubo match."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crm.public_forms SET activo = FALSE WHERE id = %s",
                (form_id,),
            )
            conn.commit()
            return cur.rowcount > 0


def delete_form_permanent(form_id: str) -> bool:
    """Borrado físico del form.

    Cascadas (declaradas en la FK de la V021):
      - crm.public_form_submissions  → ON DELETE CASCADE (se borran)
      - crm.leads.origen_form_id     → ON DELETE SET NULL (se preserva el lead)

    Devuelve True si se borró algo. Idempotente (no falla si no existe).
    Esta operación NO es reversible — la capa service debe validar que el
    usuario sea admin y que el form ya esté archivado antes de llamar aquí.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM crm.public_forms WHERE id = %s",
                (form_id,),
            )
            conn.commit()
            return cur.rowcount > 0


# ── Submissions ──────────────────────────────────────────────────────────────

def count_recent_submissions_by_ip(ip_address: str, minutes: int) -> int:
    """Cuenta submissions desde una IP en los últimos N minutos. Usado para
    rate limit defensivo (además del slowapi nativo a nivel de endpoint)."""
    if not ip_address:
        return 0
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::int
                FROM crm.public_form_submissions
                WHERE ip_address = %s
                  AND created_at >= NOW() - (%s || ' minutes')::interval
                """,
                (ip_address, str(minutes)),
            )
            return cur.fetchone()[0]


def record_submission_and_create_lead(
    *,
    form: dict,
    lead_data: dict,
    ip_address: Optional[str],
    user_agent: Optional[str],
    payload: dict,
) -> dict:
    """Transaccional: ingresa el lead (o re-engagement si ya existe) + submission.

    V067 — dedupe + recapture:
      Antes de crear, busca lead activo no mergeado con el MISMO telefono.
      Si existe → llama a lead_recapture.handle_recontacto (push al asesor
      original, audit en lead_recontactos, fill de campos vacios, etc) y
      reutiliza ese lead. Patron patrón estándar "Lead Recapture": un
      mismo cliente que vuelve via otro form NO se vuelve a crear como un
      lead nuevo — se re-engancha al asesor original.

    Devuelve `{"lead_id": int, "recaptured": bool, "estrategia": str|None}`.

    Incrementa atomicamente submission_count en el form (enforce de
    max_submissions sin race conditions).
    """
    from psycopg2.extras import RealDictCursor as _RDC
    with get_db() as conn:
        with conn.cursor(cursor_factory=_RDC) as cur:
            try:
                telefono = (lead_data.get("telefono") or "").strip() or None
                email    = (lead_data.get("email") or "").strip().lower() or None

                # ── V067: dedupe check por telefono (luego email) ────────
                existing = None
                if telefono:
                    cur.execute(
                        """
                        SELECT l.id, l.asesor_id::text AS asesor_id,
                               l.supervisor_id::text AS supervisor_id,
                               l.fuente_id, l.email, l.nombres, l.apellidos,
                               e.nombre AS estado_nombre
                        FROM crm.leads l
                        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                        WHERE l.telefono = %s
                          AND l.activo = TRUE
                          AND l.merged_into IS NULL
                        LIMIT 1
                        """,
                        (telefono,),
                    )
                    existing = cur.fetchone()
                if not existing and email:
                    cur.execute(
                        """
                        SELECT l.id, l.asesor_id::text AS asesor_id,
                               l.supervisor_id::text AS supervisor_id,
                               l.fuente_id, l.email, l.nombres, l.apellidos,
                               e.nombre AS estado_nombre
                        FROM crm.leads l
                        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                        WHERE LOWER(l.email) = LOWER(%s)
                          AND l.activo = TRUE
                          AND l.merged_into IS NULL
                        LIMIT 1
                        """,
                        (email,),
                    )
                    existing = cur.fetchone()

                if existing:
                    # ── Recapture path ──────────────────────────────────
                    lead_id = existing["id"]
                    estrategia = None
                    try:
                        from types import SimpleNamespace
                        from app.services import lead_recapture
                        # Construimos un payload-like con los atributos que
                        # handle_recontacto consume. Public forms NO declaran
                        # fuente / api_client_id como tal — el form propaga
                        # su propia fuente_id por catalogo. Pasamos la
                        # etiqueta del form para que el push contextualice
                        # la razon del re-engagement.
                        fuente_label = (
                            form.get("nombre_evento")
                            or form.get("titulo")
                            or "formulario público"
                        )
                        synth_payload = SimpleNamespace(
                            fuente=fuente_label,
                            api_client_id=None,
                        )
                        recap = lead_recapture.handle_recontacto(
                            cur,
                            existing=dict(existing),
                            payload=synth_payload,
                            telefono=telefono or "",
                            email=email,
                            nombres=lead_data.get("nombres") or "",
                            apellidos=lead_data.get("apellidos"),
                            campana=form.get("campana"),
                            fext=None,  # forms publicos no tienen external_id
                        )
                        estrategia = recap.get("estrategia")
                    except Exception:  # noqa: BLE001
                        # Recapture es best-effort. Si V048 no esta aplicada
                        # o algo falla, igual registramos la submission para
                        # no perder el touch del cliente.
                        pass

                    # Submission linked al lead existente
                    cur.execute(
                        """
                        INSERT INTO crm.public_form_submissions (
                            form_id, lead_id, ip_address, user_agent, payload
                        ) VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (form["id"], lead_id, ip_address, user_agent, json.dumps(payload)),
                    )
                    cur.execute(
                        "UPDATE crm.public_forms SET submission_count = submission_count + 1 "
                        "WHERE id = %s",
                        (form["id"],),
                    )
                    conn.commit()
                    return {"lead_id": lead_id, "recaptured": True, "estrategia": estrategia}

                # ── Creacion normal (sin duplicado) ──────────────────────
                asignado_a = form["asignado_a"]
                cur.execute(
                    """
                    INSERT INTO crm.leads (
                        nombres, apellidos, telefono, email, dni,
                        fuente_id, campana, observaciones,
                        supervisor_id, asesor_id, fecha_entrada_cola,
                        origen_form_id, created_by, sede_id,
                        estado_id
                    ) VALUES (
                        %(nombres)s, %(apellidos)s, %(telefono)s, %(email)s, %(dni)s,
                        %(fuente_id)s, %(campana)s, %(observaciones)s,
                        CASE
                            WHEN %(asignado_a)s IS NULL THEN NULL
                            WHEN (SELECT role FROM auth.users WHERE id = %(asignado_a)s::uuid) = 'supervisor'
                                THEN %(asignado_a)s::uuid
                            ELSE (
                                SELECT eq.supervisor_id FROM crm.equipos eq
                                WHERE eq.asesor_id = %(asignado_a)s::uuid AND eq.activo = TRUE
                                LIMIT 1
                            )
                        END,
                        CASE
                            WHEN %(asignado_a)s IS NULL THEN NULL
                            WHEN (SELECT role FROM auth.users WHERE id = %(asignado_a)s::uuid) = 'supervisor'
                                THEN NULL
                            ELSE %(asignado_a)s::uuid
                        END,
                        CASE
                            WHEN %(asignado_a)s IS NULL THEN NULL
                            WHEN (SELECT role FROM auth.users WHERE id = %(asignado_a)s::uuid) = 'supervisor'
                                THEN NOW()
                            ELSE NULL
                        END,
                        %(origen_form_id)s, %(created_by)s,
                        %(sede_id)s,
                        COALESCE(
                            (SELECT id FROM crm.estados_lead WHERE nombre = 'Nuevo' LIMIT 1),
                            (SELECT id FROM crm.estados_lead ORDER BY orden LIMIT 1)
                        )
                    )
                    RETURNING id
                    """,
                    {
                        "nombres":        lead_data.get("nombres"),
                        "apellidos":      lead_data.get("apellidos"),
                        "telefono":       lead_data.get("telefono"),
                        "email":          lead_data.get("email"),
                        "dni":            lead_data.get("dni"),
                        "fuente_id":      form.get("fuente_id"),
                        "campana":        form.get("campana"),
                        "observaciones":  lead_data.get("observaciones"),
                        "asignado_a":     asignado_a,
                        "origen_form_id": form["id"],
                        "created_by":     form["created_by"],
                        "sede_id":        form.get("sede_id_default"),
                    },
                )
                lead_id = cur.fetchone()["id"]

                cur.execute(
                    """
                    INSERT INTO crm.public_form_submissions (
                        form_id, lead_id, ip_address, user_agent, payload
                    ) VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (form["id"], lead_id, ip_address, user_agent, json.dumps(payload)),
                )
                cur.execute(
                    "UPDATE crm.public_forms SET submission_count = submission_count + 1 "
                    "WHERE id = %s",
                    (form["id"],),
                )

                conn.commit()
                return {"lead_id": lead_id, "recaptured": False, "estrategia": None}
            except Exception:
                conn.rollback()
                raise


def count_leads_by_form(form_id: str) -> int:
    """Total de leads vivos capturados por un form. Usado en la vista de detalle.

    NOTA: solo cuenta leads cuyo origen_form_id apunta a este form. Los
    recontactos (lead ya existia, el form solo registro un nuevo submission)
    NO se cuentan aqui. Para el desglose completo usar
    count_breakdown_by_form (V093).
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::int FROM crm.leads "
                "WHERE origen_form_id = %s AND activo = TRUE",
                (form_id,),
            )
            return cur.fetchone()[0]


def count_breakdown_by_form(form_id: str) -> dict:
    """Desglose de captacion del form (V093 — fix bug "3 vs 0").

    Devuelve:
      {
        "total_submissions": int,  # cuantas veces se envio el form
        "leads_nuevos":      int,  # leads creados SOLO por este form
        "recontactos":       int,  # submissions que cayeron sobre lead existente
      }

    Por construccion: total_submissions = leads_nuevos + recontactos.

    Antes de V093 la UI solo mostraba `count_leads_by_form` (= leads_nuevos)
    bajo la etiqueta "LEADS CAPTURADOS", pero el card de la lista mostraba
    `submission_count` (= total_submissions) bajo la misma etiqueta. Eran
    dos numeros distintos con el mismo label → confusion del manager.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(submission_count, 0)::int AS total "
                "FROM crm.public_forms WHERE id = %s",
                (form_id,),
            )
            row = cur.fetchone()
            total_submissions = row[0] if row else 0

            cur.execute(
                "SELECT COUNT(*)::int FROM crm.leads "
                "WHERE origen_form_id = %s AND activo = TRUE",
                (form_id,),
            )
            leads_nuevos = cur.fetchone()[0]

    # Recontactos no tienen su propio contador (el submission se registro
    # contra un lead existente, no se creo lead nuevo). Lo derivamos.
    # Clamp a 0 para defendernos de inconsistencia historica (submission_count
    # podria estar atrasado vs leads.origen_form_id en datos pre-V048).
    recontactos = max(0, total_submissions - leads_nuevos)
    return {
        "total_submissions": total_submissions,
        "leads_nuevos":      leads_nuevos,
        "recontactos":       recontactos,
    }

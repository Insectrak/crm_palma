"""
Metas mensuales — Sprint 3.

CRUD del catalogo crm.metas_mensuales + endpoint de cumplimiento que
compara metas vs realidad real-time. Patron patrón estándar Quotas / patrón estándar
Goals: admin/supervisor define meta numerica por (asesor, mes), sistema
mide automaticamente cuanto le falta a cada uno para cumplir.

Endpoints:
  GET    /api/metas?mes=YYYY-MM             — listado del mes
  POST   /api/metas                          — crear / upsert meta
  PATCH  /api/metas/{id}                     — actualizar meta
  DELETE /api/metas/{id}                     — eliminar meta
  GET    /api/metas/cumplimiento?mes=YYYY-MM — meta vs realidad por asesor
"""
from datetime import date, timedelta
from typing import Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from app.auth.jwt import get_current_user, require_admin, require_supervisor_or_admin
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/metas", tags=["Metas"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_mes(mes: Optional[str]) -> date:
    """Acepta 'YYYY-MM' y devuelve date(YYYY, MM, 1). Default mes actual."""
    if not mes:
        today = date.today()
        return date(today.year, today.month, 1)
    try:
        y, m = int(mes[:4]), int(mes[5:7])
        return date(y, m, 1)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Formato de mes invalido. Usar YYYY-MM (ej: 2026-05).",
        ) from exc


def _siguiente_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class MetaCreate(BaseModel):
    asesor_id:     str        # uuid asesor o supervisor (segun tipo)
    mes:           str        # 'YYYY-MM'
    tipo:          str = "asesor"   # 'asesor' | 'equipo'
    meta_ventas:   int = 0
    meta_citas:    int = 0
    meta_llamadas: int = 0
    notas:         Optional[str] = None


class MetaUpdate(BaseModel):
    meta_ventas:   Optional[int] = None
    meta_citas:    Optional[int] = None
    meta_llamadas: Optional[int] = None
    notas:         Optional[str] = None


def _has_tipo_column(cur) -> bool:
    """Self-healing: detecta si la columna 'tipo' existe (V044 aplicada).
    Sin cache — el migrator de startup puede aplicar V044 despues del
    primer request y queremos pickearlo enseguida."""
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='crm' AND table_name='metas_mensuales' AND column_name='tipo'"
    )
    return cur.fetchone() is not None


# ─── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("")
def list_metas(
    mes: Optional[str] = Query(None, description="YYYY-MM. Default: mes actual."),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Lista metas del mes con datos del asesor/supervisor."""
    primer_dia = _parse_mes(mes)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            tipo_col = "m.tipo" if _has_tipo_column(cur) else "'asesor' AS tipo"
            # Filtro de rol: supervisor solo ve metas de su equipo + las suyas
            if current_user.role == Role.SUPERVISOR:
                cur.execute(
                    f"""
                    SELECT m.id, m.asesor_id, m.mes, m.meta_ventas, m.meta_citas,
                        m.meta_llamadas, m.notas, m.created_at, m.updated_at,
                        {tipo_col},
                        TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
                        u.email AS asesor_email,
                        u.role  AS asesor_role
                    FROM crm.metas_mensuales m
                    JOIN auth.users u ON u.id = m.asesor_id
                    WHERE m.mes = %s
                      AND (
                          m.asesor_id = %s::uuid
                          OR m.asesor_id IN (
                              SELECT asesor_id FROM crm.equipos
                              WHERE supervisor_id = %s::uuid AND activo = TRUE
                          )
                      )
                    ORDER BY u.first_name
                    """,
                    (primer_dia, current_user.user_id, current_user.user_id),
                )
            else:
                cur.execute(
                    f"""
                    SELECT m.id, m.asesor_id, m.mes, m.meta_ventas, m.meta_citas,
                        m.meta_llamadas, m.notas, m.created_at, m.updated_at,
                        {tipo_col},
                        TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
                        u.email AS asesor_email,
                        u.role  AS asesor_role
                    FROM crm.metas_mensuales m
                    JOIN auth.users u ON u.id = m.asesor_id
                    WHERE m.mes = %s
                    ORDER BY u.first_name
                    """,
                    (primer_dia,),
                )
            rows = cur.fetchall()
    return {
        "metas":  [dict(r) for r in rows],
        "mes":    primer_dia.isoformat(),
    }


@router.post("", status_code=201)
def upsert_meta(data: MetaCreate, admin: TokenData = Depends(require_supervisor_or_admin)):
    """Crea o actualiza la meta del (asesor_id, mes, tipo). Si ya existe, sobreescribe.

    tipo='asesor': asesor_id es el UUID del asesor.
    tipo='equipo': asesor_id es el UUID del supervisor cuyo equipo representa.
    """
    if data.tipo not in ("asesor", "equipo"):
        raise HTTPException(400, "tipo invalido (asesor | equipo)")
    primer_dia = _parse_mes(data.mes)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            has_tipo = _has_tipo_column(cur)

            # Validacion: tipo='equipo' requiere que asesor_id sea un supervisor.
            if data.tipo == "equipo":
                cur.execute(
                    "SELECT role FROM auth.users WHERE id = %s::uuid",
                    (data.asesor_id,),
                )
                row = cur.fetchone()
                if not row or row["role"] not in ("supervisor", "admin"):
                    raise HTTPException(400, "Las metas de tipo 'equipo' requieren un supervisor.")

            # Supervisor solo puede definir metas para su equipo + el mismo
            if admin.role == Role.SUPERVISOR:
                if data.tipo == "equipo" and str(data.asesor_id) != str(admin.user_id):
                    raise HTTPException(403, "Solo puedes definir la meta de tu propio equipo.")
                if data.tipo == "asesor":
                    cur.execute(
                        "SELECT 1 FROM auth.users u "
                        "WHERE u.id = %s::uuid "
                        "AND (u.id = %s::uuid OR EXISTS ("
                        "    SELECT 1 FROM crm.equipos "
                        "    WHERE supervisor_id = %s::uuid AND asesor_id = u.id AND activo = TRUE"
                        "))",
                        (data.asesor_id, admin.user_id, admin.user_id),
                    )
                    if not cur.fetchone():
                        raise HTTPException(403, "Solo puedes definir metas para tu equipo.")

            if has_tipo:
                cur.execute(
                    """
                    INSERT INTO crm.metas_mensuales
                        (asesor_id, mes, tipo, meta_ventas, meta_citas, meta_llamadas, notas, created_by)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::uuid)
                    ON CONFLICT (asesor_id, mes, tipo) DO UPDATE SET
                        meta_ventas   = EXCLUDED.meta_ventas,
                        meta_citas    = EXCLUDED.meta_citas,
                        meta_llamadas = EXCLUDED.meta_llamadas,
                        notas         = EXCLUDED.notas,
                        updated_at    = NOW()
                    RETURNING *
                    """,
                    (
                        data.asesor_id, primer_dia, data.tipo,
                        data.meta_ventas, data.meta_citas, data.meta_llamadas,
                        data.notas, admin.user_id,
                    ),
                )
            else:
                # V044 aun no aplicada — fallback al esquema viejo.
                if data.tipo == "equipo":
                    raise HTTPException(503, "Migracion V044 aun no aplicada. Reintenta en unos segundos.")
                cur.execute(
                    """
                    INSERT INTO crm.metas_mensuales
                        (asesor_id, mes, meta_ventas, meta_citas, meta_llamadas, notas, created_by)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid)
                    ON CONFLICT (asesor_id, mes) DO UPDATE SET
                        meta_ventas   = EXCLUDED.meta_ventas,
                        meta_citas    = EXCLUDED.meta_citas,
                        meta_llamadas = EXCLUDED.meta_llamadas,
                        notas         = EXCLUDED.notas,
                        updated_at    = NOW()
                    RETURNING *
                    """,
                    (
                        data.asesor_id, primer_dia,
                        data.meta_ventas, data.meta_citas, data.meta_llamadas,
                        data.notas, admin.user_id,
                    ),
                )
            row = cur.fetchone()
        conn.commit()
    return dict(row)


@router.patch("/{meta_id}")
def update_meta(meta_id: int, data: MetaUpdate, admin: TokenData = Depends(require_supervisor_or_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar")
    set_parts = [f"{k} = %s" for k in fields]
    params = list(fields.values()) + [meta_id]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.metas_mensuales SET {', '.join(set_parts)}, updated_at = NOW() "
                "WHERE id = %s RETURNING *",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Meta no encontrada")
        conn.commit()
    return dict(row)


@router.delete("/{meta_id}")
def delete_meta(meta_id: int, admin: TokenData = Depends(require_supervisor_or_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm.metas_mensuales WHERE id = %s RETURNING id", (meta_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Meta no encontrada")
        conn.commit()
    return {"ok": True}


# ─── Detalle de equipo (drill-down) ──────────────────────────────────────────

@router.get("/equipo/{supervisor_id}/detalle")
def detalle_equipo(
    supervisor_id: str,
    mes: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """Drill-down de un equipo: supervisor + cada asesor activo con sus
    ventas/citas/llamadas individuales del mes. Patron patrón estándar Goals
    detail panel.

    Permisos:
      - admin: cualquier equipo.
      - supervisor: solo su propio equipo.
      - asesor: 403.
    """
    if current_user.role == Role.ASESOR:
        raise HTTPException(403, "Sin permiso")
    if current_user.role == Role.SUPERVISOR and str(supervisor_id) != str(current_user.user_id):
        raise HTTPException(403, "Solo puedes ver tu propio equipo")

    primer_dia = _parse_mes(mes)
    siguiente  = _siguiente_mes(primer_dia)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Confirma que el supervisor existe
            cur.execute(
                "SELECT id::text, first_name, last_name, email, role "
                "FROM auth.users WHERE id = %s::uuid",
                (supervisor_id,),
            )
            sup = cur.fetchone()
            if not sup:
                raise HTTPException(404, "Supervisor no encontrado")
            if sup["role"] not in ("supervisor", "admin"):
                raise HTTPException(400, "El usuario indicado no es supervisor")

            # Lista de miembros: supervisor + asesores activos del equipo.
            cur.execute(
                """
                SELECT
                    u.id::text,
                    u.first_name, u.last_name, u.email, u.role,
                    -- ventas: leads ganados via cambio_estado en el mes
                    -- V070.50 — Atribucion por el ASESOR QUE CERRO (c.asesor_id)
                    -- en lugar del owner actual (l.asesor_id). Patron patrón estándar/
                    -- closed-won (patrón estándar) attribution. Mas filtros: activo + no
                    -- mergeado (paridad con /api/leads).
                    (SELECT COUNT(DISTINCT c.lead_id)
                     FROM crm.contactos c
                     JOIN crm.leads l ON l.id = c.lead_id
                     WHERE c.asesor_id = u.id
                       AND l.activo = TRUE
                       AND l.merged_into IS NULL
                       AND c.tipo_contacto = 'cambio_estado'
                       AND (c.notas ILIKE '%%matr%%' OR c.notas ILIKE '%%ganad%%' OR c.notas ILIKE '%%cierr%%' OR c.notas ILIKE '%%verificad%%')
                       AND c.created_at >= %s::timestamptz
                       AND c.created_at <  %s::timestamptz
                    )::int AS ventas_actuales,
                    -- citas en el mes (paridad: solo leads activos + no merged)
                    (SELECT COUNT(*)
                     FROM crm.contactos c
                     JOIN crm.leads l ON l.id = c.lead_id
                     WHERE c.asesor_id = u.id
                       AND l.activo = TRUE
                       AND l.merged_into IS NULL
                       AND c.fecha_cita >= %s::timestamptz
                       AND c.fecha_cita <  %s::timestamptz
                    )::int AS citas_actuales,
                    -- llamadas en el mes
                    (SELECT COUNT(*)
                     FROM crm.llamadas ll
                     WHERE ll.asesor_id = u.id
                       AND ll.fecha_llamada >= %s::timestamptz
                       AND ll.fecha_llamada <  %s::timestamptz
                    )::int AS llamadas_actuales,
                    -- meta individual (si existe) — solo tipo='asesor'
                    COALESCE(mi.meta_ventas,   0)::int AS meta_ventas,
                    COALESCE(mi.meta_citas,    0)::int AS meta_citas,
                    COALESCE(mi.meta_llamadas, 0)::int AS meta_llamadas
                FROM auth.users u
                LEFT JOIN crm.metas_mensuales mi
                    ON mi.asesor_id = u.id
                    AND mi.mes = %s
                    AND COALESCE(mi.tipo, 'asesor') = 'asesor'
                WHERE u.id = %s::uuid
                   OR u.id IN (
                       SELECT asesor_id FROM crm.equipos
                       WHERE supervisor_id = %s::uuid AND activo = TRUE
                   )
                ORDER BY (u.id = %s::uuid) DESC, u.first_name
                """,
                (
                    primer_dia, siguiente,
                    primer_dia, siguiente,
                    primer_dia, siguiente,
                    primer_dia, supervisor_id, supervisor_id, supervisor_id,
                ),
            )
            miembros = [dict(r) for r in cur.fetchall()]

    # Totales del equipo (suma de miembros)
    tot_v = sum(m["ventas_actuales"] for m in miembros)
    tot_c = sum(m["citas_actuales"] for m in miembros)
    tot_l = sum(m["llamadas_actuales"] for m in miembros)

    # Contribuciones porcentuales (cuánto aportó cada miembro al total del equipo)
    for m in miembros:
        m["nombre"] = " ".join(filter(None, [m.pop("first_name", ""), m.pop("last_name", "")])).strip() or m.get("email", "")
        m["pct_ventas_total"]   = round(m["ventas_actuales"]   * 100 / tot_v, 1) if tot_v else None
        m["pct_citas_total"]    = round(m["citas_actuales"]    * 100 / tot_c, 1) if tot_c else None
        m["pct_llamadas_total"] = round(m["llamadas_actuales"] * 100 / tot_l, 1) if tot_l else None
        m["es_supervisor"]      = m["role"] in ("supervisor", "admin")

    return {
        "supervisor_id": supervisor_id,
        "supervisor_nombre": " ".join(filter(None, [sup["first_name"], sup["last_name"]])).strip() or sup["email"],
        "mes": primer_dia.isoformat(),
        "miembros": miembros,
        "totales": {
            "ventas_actuales":   tot_v,
            "citas_actuales":    tot_c,
            "llamadas_actuales": tot_l,
        },
    }


# ─── Cumplimiento real-time ──────────────────────────────────────────────────

@router.get("/cumplimiento")
def cumplimiento(
    mes: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
):
    """Cumplimiento de metas vs realidad — patron estandar Goals dashboard.

    Devuelve, por cada meta del mes, los actuales reales:
      - ventas_actuales:   leads ganados en el mes con asesor_id = X
      - citas_actuales:    contactos con fecha_cita en el mes
      - llamadas_actuales: llamadas registradas en el mes

    Mas porcentajes de cumplimiento. Sirve para mostrar barras de
    progreso 'Pedro va al 65% de su meta de ventas'.
    """
    primer_dia = _parse_mes(mes)
    siguiente  = _siguiente_mes(primer_dia)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            has_tipo = _has_tipo_column(cur)
            tipo_col = "m.tipo" if has_tipo else "'asesor' AS tipo"

            # Filtro de rol: asesor solo ve su propio cumplimiento.
            if current_user.role == Role.ASESOR and getattr(current_user, "role_id", None) is None:
                where_role = "AND m.asesor_id = %s::uuid"
                role_params = [current_user.user_id]
            elif current_user.role == Role.SUPERVISOR:
                where_role = (
                    "AND (m.asesor_id = %s::uuid "
                    "OR m.asesor_id IN ("
                    "    SELECT asesor_id FROM crm.equipos "
                    "    WHERE supervisor_id = %s::uuid AND activo = TRUE"
                    "))"
                )
                role_params = [current_user.user_id, current_user.user_id]
            else:
                where_role = ""
                role_params = []

            # tipo='asesor': los actuales se calculan contra el asesor_id directamente.
            # tipo='equipo': los actuales se calculan contra el set { supervisor + sus asesores activos }.
            #   Usamos un sub-SELECT que arma el array de UUIDs del equipo y luego
            #   '= ANY(...)' para contar a todos los miembros.
            #
            # NOTA ventas: NO usamos l.updated_at (cambia con cualquier edicion).
            # crm.contactos registra cada cambio de estado con tipo_contacto =
            # 'cambio_estado' y notas = 'Estado → Ganado'. Ese created_at es el
            # timestamp real de cuando el lead fue ganado. Si el lead fue
            # ganado y luego re-abierto, igual cuenta como 'cerrado en el mes'
            # (semantica patrón estándar closed-won-this-period).
            ganado_pattern = "%→ Ganado"
            if has_tipo:
                team_uuid_array = (
                    "ARRAY(SELECT m.asesor_id "
                    "      UNION SELECT eq.asesor_id FROM crm.equipos eq "
                    "                  WHERE eq.supervisor_id = m.asesor_id AND eq.activo = TRUE)"
                )
                # V070.50 — Paridad EXACTA con la lista de Leads + atribucion
                # por el asesor que CERRO (c.asesor_id), no por el dueno actual
                # (l.asesor_id). Patron CRMs profesionales "closed-won
                # attribution": la venta se le atribuye al closer, no al
                # owner del momento del reporte. Asi:
                # - Lead activo + ganado por Ana → cuenta para Ana ✓
                # - Lead borrado activo=FALSE → NO cuenta para nadie ✓
                # - Lead mergeado → NO cuenta ✓
                # - Lead ganado por Ana, reasignado a Juan → sigue siendo de Ana ✓
                ventas_clause = (
                    "CASE WHEN m.tipo = 'equipo' THEN "
                    "  (SELECT COUNT(DISTINCT c.lead_id) FROM crm.contactos c "
                    "    JOIN crm.leads l ON l.id = c.lead_id "
                    f"   WHERE c.asesor_id = ANY({team_uuid_array}) "
                    "      AND l.activo = TRUE "
                    "      AND l.merged_into IS NULL "
                    "      AND c.tipo_contacto = 'cambio_estado' "
                    "      AND (c.notas ILIKE '%%matr%%' OR c.notas ILIKE '%%ganad%%' OR c.notas ILIKE '%%cierr%%' OR c.notas ILIKE '%%verificad%%') "
                    "      AND c.created_at >= %s::timestamptz AND c.created_at < %s::timestamptz) "
                    "ELSE "
                    "  (SELECT COUNT(DISTINCT c.lead_id) FROM crm.contactos c "
                    "    JOIN crm.leads l ON l.id = c.lead_id "
                    "   WHERE c.asesor_id = m.asesor_id "
                    "      AND l.activo = TRUE "
                    "      AND l.merged_into IS NULL "
                    "      AND c.tipo_contacto = 'cambio_estado' "
                    "      AND (c.notas ILIKE '%%matr%%' OR c.notas ILIKE '%%ganad%%' OR c.notas ILIKE '%%cierr%%' OR c.notas ILIKE '%%verificad%%') "
                    "      AND c.created_at >= %s::timestamptz AND c.created_at < %s::timestamptz) "
                    "END::int AS ventas_actuales"
                )
                citas_clause = (
                    "CASE WHEN m.tipo = 'equipo' THEN "
                    "  (SELECT COUNT(*) FROM crm.contactos c "
                    "    JOIN crm.leads l ON l.id = c.lead_id "
                    f"   WHERE c.asesor_id = ANY({team_uuid_array}) "
                    "      AND l.activo = TRUE "
                    "      AND l.merged_into IS NULL "
                    "      AND c.fecha_cita >= %s::timestamptz AND c.fecha_cita < %s::timestamptz) "
                    "ELSE "
                    "  (SELECT COUNT(*) FROM crm.contactos c "
                    "    JOIN crm.leads l ON l.id = c.lead_id "
                    "   WHERE c.asesor_id = m.asesor_id "
                    "      AND l.activo = TRUE "
                    "      AND l.merged_into IS NULL "
                    "      AND c.fecha_cita >= %s::timestamptz AND c.fecha_cita < %s::timestamptz) "
                    "END::int AS citas_actuales"
                )
                llamadas_clause = (
                    "CASE WHEN m.tipo = 'equipo' THEN "
                    "  (SELECT COUNT(*) FROM crm.llamadas ll "
                    f"   WHERE ll.asesor_id = ANY({team_uuid_array}) "
                    "      AND ll.fecha_llamada >= %s::timestamptz AND ll.fecha_llamada < %s::timestamptz) "
                    "ELSE "
                    "  (SELECT COUNT(*) FROM crm.llamadas ll "
                    "   WHERE ll.asesor_id = m.asesor_id "
                    "      AND ll.fecha_llamada >= %s::timestamptz AND ll.fecha_llamada < %s::timestamptz) "
                    "END::int AS llamadas_actuales"
                )
                # Ventas/Citas/Llamadas: 2 ramas CASE × 2 fechas = 4 params c/u (total 6 pares)
                base_params = [primer_dia, siguiente] * 6
            else:
                # V070.50 — Closed-won attribution: c.asesor_id (closer).
                ventas_clause = (
                    "(SELECT COUNT(DISTINCT c.lead_id) FROM crm.contactos c "
                    " JOIN crm.leads l ON l.id = c.lead_id "
                    " WHERE c.asesor_id = m.asesor_id "
                    "   AND l.activo = TRUE "
                    "   AND l.merged_into IS NULL "
                    "   AND c.tipo_contacto = 'cambio_estado' "
                    "   AND (c.notas ILIKE '%%matr%%' OR c.notas ILIKE '%%ganad%%' OR c.notas ILIKE '%%cierr%%' OR c.notas ILIKE '%%verificad%%') "
                    "   AND c.created_at >= %s::timestamptz AND c.created_at < %s::timestamptz "
                    ")::int AS ventas_actuales"
                )
                citas_clause = (
                    "(SELECT COUNT(*) FROM crm.contactos c "
                    " JOIN crm.leads l ON l.id = c.lead_id "
                    " WHERE c.asesor_id = m.asesor_id "
                    "   AND l.activo = TRUE "
                    "   AND l.merged_into IS NULL "
                    "   AND c.fecha_cita >= %s::timestamptz AND c.fecha_cita < %s::timestamptz "
                    ")::int AS citas_actuales"
                )
                llamadas_clause = (
                    "(SELECT COUNT(*) FROM crm.llamadas ll "
                    " WHERE ll.asesor_id = m.asesor_id "
                    "   AND ll.fecha_llamada >= %s::timestamptz AND ll.fecha_llamada < %s::timestamptz "
                    ")::int AS llamadas_actuales"
                )
                base_params = [primer_dia, siguiente] * 3

            # Para metas de equipo, traemos tambien la suma de metas individuales
            # de cada miembro (supervisor + asesores) — sirve para detectar
            # incoherencia "meta_equipo != suma_individuales" y mostrar warning.
            if has_tipo:
                team_uuid_array_member = (
                    "ARRAY(SELECT m.asesor_id "
                    "      UNION SELECT eq.asesor_id FROM crm.equipos eq "
                    "                  WHERE eq.supervisor_id = m.asesor_id AND eq.activo = TRUE)"
                )
                suma_indiv_clauses = (
                    f", CASE WHEN m.tipo = 'equipo' THEN "
                    f"   (SELECT COALESCE(SUM(mi.meta_ventas), 0) FROM crm.metas_mensuales mi "
                    f"     WHERE mi.mes = m.mes AND mi.tipo = 'asesor' "
                    f"       AND mi.asesor_id = ANY({team_uuid_array_member})) "
                    f"  ELSE NULL END::int AS suma_indiv_ventas"
                    f", CASE WHEN m.tipo = 'equipo' THEN "
                    f"   (SELECT COALESCE(SUM(mi.meta_citas), 0) FROM crm.metas_mensuales mi "
                    f"     WHERE mi.mes = m.mes AND mi.tipo = 'asesor' "
                    f"       AND mi.asesor_id = ANY({team_uuid_array_member})) "
                    f"  ELSE NULL END::int AS suma_indiv_citas"
                    f", CASE WHEN m.tipo = 'equipo' THEN "
                    f"   (SELECT COALESCE(SUM(mi.meta_llamadas), 0) FROM crm.metas_mensuales mi "
                    f"     WHERE mi.mes = m.mes AND mi.tipo = 'asesor' "
                    f"       AND mi.asesor_id = ANY({team_uuid_array_member})) "
                    f"  ELSE NULL END::int AS suma_indiv_llamadas"
                )
            else:
                suma_indiv_clauses = (
                    ", NULL::int AS suma_indiv_ventas"
                    ", NULL::int AS suma_indiv_citas"
                    ", NULL::int AS suma_indiv_llamadas"
                )

            cur.execute(
                f"""
                SELECT
                    m.id, m.asesor_id::text, m.mes::text,
                    m.meta_ventas, m.meta_citas, m.meta_llamadas, m.notas,
                    {tipo_col},
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
                    u.email AS asesor_email,
                    u.role  AS asesor_role,
                    {ventas_clause},
                    {citas_clause},
                    {llamadas_clause}
                    {suma_indiv_clauses}
                FROM crm.metas_mensuales m
                JOIN auth.users u ON u.id = m.asesor_id
                WHERE m.mes = %s
                {where_role}
                ORDER BY {('m.tipo DESC, ' if has_tipo else '')}u.first_name
                """,
                base_params + [primer_dia] + role_params,
            )
            rows = cur.fetchall()

    out = []
    # Totales solo de tipo='asesor' para evitar doble conteo con metas
    # de equipo (donde el equipo ya incluye a sus asesores).
    tot_meta_v = tot_act_v = 0
    tot_meta_c = tot_act_c = 0
    tot_meta_l = tot_act_l = 0
    # Totales de equipo (separados para mostrar "metas de equipo" en otra seccion)
    eq_meta_v = eq_act_v = 0
    eq_meta_c = eq_act_c = 0
    eq_meta_l = eq_act_l = 0
    for r in rows:
        d = dict(r)
        # Porcentajes (cap 999% para evitar barras infinitas)
        d["pct_ventas"]   = min(round(d["ventas_actuales"]   * 100 / d["meta_ventas"],   1), 999) if d["meta_ventas"]   else None
        d["pct_citas"]    = min(round(d["citas_actuales"]    * 100 / d["meta_citas"],    1), 999) if d["meta_citas"]    else None
        d["pct_llamadas"] = min(round(d["llamadas_actuales"] * 100 / d["meta_llamadas"], 1), 999) if d["meta_llamadas"] else None
        if d.get("tipo") == "equipo":
            eq_meta_v += d["meta_ventas"];   eq_act_v += d["ventas_actuales"]
            eq_meta_c += d["meta_citas"];    eq_act_c += d["citas_actuales"]
            eq_meta_l += d["meta_llamadas"]; eq_act_l += d["llamadas_actuales"]
        else:
            tot_meta_v += d["meta_ventas"];   tot_act_v += d["ventas_actuales"]
            tot_meta_c += d["meta_citas"];    tot_act_c += d["citas_actuales"]
            tot_meta_l += d["meta_llamadas"]; tot_act_l += d["llamadas_actuales"]
        out.append(d)

    # Dia del mes / dias del mes (para "expected progress")
    today = date.today()
    if today >= primer_dia and today < siguiente:
        dias_del_mes = (siguiente - primer_dia).days
        dias_transcurridos = (today - primer_dia).days + 1
        pct_esperado = round(dias_transcurridos * 100 / dias_del_mes, 1)
    else:
        pct_esperado = 100.0 if today >= siguiente else 0.0

    return {
        "metas":  out,
        "mes":    primer_dia.isoformat(),
        "totales": {
            "meta_ventas":      tot_meta_v,
            "ventas_actuales":  tot_act_v,
            "meta_citas":       tot_meta_c,
            "citas_actuales":   tot_act_c,
            "meta_llamadas":    tot_meta_l,
            "llamadas_actuales": tot_act_l,
            "pct_ventas":      round(tot_act_v * 100 / tot_meta_v, 1) if tot_meta_v else None,
            "pct_citas":       round(tot_act_c * 100 / tot_meta_c, 1) if tot_meta_c else None,
            "pct_llamadas":    round(tot_act_l * 100 / tot_meta_l, 1) if tot_meta_l else None,
        },
        "totales_equipo": {
            "meta_ventas":      eq_meta_v,
            "ventas_actuales":  eq_act_v,
            "meta_citas":       eq_meta_c,
            "citas_actuales":   eq_act_c,
            "meta_llamadas":    eq_meta_l,
            "llamadas_actuales": eq_act_l,
            "pct_ventas":      round(eq_act_v * 100 / eq_meta_v, 1) if eq_meta_v else None,
            "pct_citas":       round(eq_act_c * 100 / eq_meta_c, 1) if eq_meta_c else None,
            "pct_llamadas":    round(eq_act_l * 100 / eq_meta_l, 1) if eq_meta_l else None,
        },
        "pct_esperado": pct_esperado,  # progreso esperado segun dia del mes
    }

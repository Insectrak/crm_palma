"""
Llamadas router — registro y consulta de llamadas telefónicas sincronizadas desde Android.

Endpoints:
- POST /api/llamadas/sync     — sincroniza lote de llamadas desde dispositivo
- GET  /api/llamadas          — lista llamadas con filtros y paginación
- GET  /api/llamadas/stats    — estadísticas de llamadas (solo supervisor/admin)
"""
import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional, List
from app.auth.jwt import get_current_user, require_supervisor_or_admin, require_admin
from app.auth.permissions import can_view_all_data
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/llamadas", tags=["Llamadas"])


# ---------------------------------------------------------------------------
# Schemas Pydantic
# ---------------------------------------------------------------------------

class LlamadaSync(BaseModel):
    """Datos de una llamada enviada desde la app Android."""
    call_log_id: str               # ID único del registro en el dispositivo
    telefono: str
    duracion_segundos: int = 0
    tipo: str                      # saliente | entrante | perdida
    fecha_llamada: str             # ISO 8601: "2024-01-15T10:30:00"
    dispositivo_id: Optional[str] = None
    nombre_contacto: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper: filtro de visibilidad por rol
# ---------------------------------------------------------------------------

def _build_role_filter(user: TokenData) -> tuple[str, list]:
    """
    Construye la cláusula WHERE de visibilidad según el rol del usuario.
    - admin o permiso agenda.view_all/data.view_all: ve todas las llamadas
    - supervisor: ve las llamadas de sus asesores (crm.equipos)
    - asesor/custom sin permiso: ve solo sus propias llamadas
    Retorna (sql_fragment, params_list).
    """
    if can_view_all_data(user, "agenda"):
        return "1=1", []
    elif user.role == "supervisor":
        return (
            "("
            "ll.asesor_id = %s::uuid "
            "OR ll.asesor_id IN ("
                "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
            ") "
            "OR ll.asesor_id IN ("
                "SELECT eq.asesor_id FROM crm.equipos eq "
                "WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN ("
                    "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
                ")) AND eq.activo = TRUE"
            ")"
            ")",
            [user.user_id, user.user_id, user.user_id, user.user_id],
        )
    else:
        return "ll.asesor_id = %s::uuid", [user.user_id]


# ---------------------------------------------------------------------------
# POST /api/llamadas/sync
# ---------------------------------------------------------------------------

@router.post("/sync")
def sync_llamadas(
    items: List[LlamadaSync],
    current_user: TokenData = Depends(get_current_user),
):
    """
    Sincroniza un lote de llamadas desde la app Android.
    Ignora duplicados por (asesor_id, call_log_id).
    """
    synced = 0
    skipped = 0
    touched_lead_ids: set[int] = set()

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Backfill: llamadas previas del asesor con lead_id NULL cuyo teléfono
            # (normalizado a últimos 9 dígitos) coincida con algún lead existente.
            # Así, si el lead se crea después de la llamada, aparece en su historial.
            cur.execute(
                """
                UPDATE crm.llamadas ll
                SET    lead_id = sub.id
                FROM (
                    SELECT DISTINCT ON (RIGHT(REGEXP_REPLACE(telefono, '[^0-9]', '', 'g'), 9))
                           id,
                           RIGHT(REGEXP_REPLACE(telefono, '[^0-9]', '', 'g'), 9) AS tel9
                    FROM   crm.leads
                    WHERE  activo = TRUE
                      AND  telefono IS NOT NULL
                    ORDER  BY RIGHT(REGEXP_REPLACE(telefono, '[^0-9]', '', 'g'), 9),
                              (asesor_id = %s::uuid) DESC,
                              created_at DESC
                ) sub
                WHERE ll.asesor_id = %s::uuid
                  AND ll.lead_id IS NULL
                  AND RIGHT(REGEXP_REPLACE(ll.telefono, '[^0-9]', '', 'g'), 9) = sub.tel9
                """,
                (current_user.user_id, current_user.user_id),
            )

            for item in items:
                # Busca lead por últimos 9 dígitos del teléfono (tolera formatos +51, 051, 0, etc.)
                cur.execute(
                    """
                    SELECT id FROM crm.leads
                    WHERE RIGHT(REGEXP_REPLACE(telefono, '[^0-9]', '', 'g'), 9)
                          = RIGHT(REGEXP_REPLACE(%s,       '[^0-9]', '', 'g'), 9)
                      AND activo = TRUE
                    ORDER BY (asesor_id = %s::uuid) DESC, created_at DESC
                    LIMIT 1
                    """,
                    (item.telefono, current_user.user_id),
                )
                lead_row = cur.fetchone()
                lead_id = lead_row["id"] if lead_row else None

                # Inserta ignorando duplicados por (asesor_id, call_log_id)
                cur.execute(
                    """
                    INSERT INTO crm.llamadas
                        (asesor_id, lead_id, call_log_id, telefono, duracion_segundos,
                         tipo, fecha_llamada, dispositivo_id, nombre_contacto, synced_at)
                    VALUES
                        (%s::uuid, %s, %s, %s, %s,
                         %s, %s::timestamptz, %s, %s, NOW())
                    ON CONFLICT (asesor_id, call_log_id) DO NOTHING
                    """,
                    (
                        current_user.user_id,
                        lead_id,
                        item.call_log_id,
                        item.telefono,
                        item.duracion_segundos,
                        item.tipo,
                        item.fecha_llamada,
                        item.dispositivo_id,
                        item.nombre_contacto,
                    ),
                )
                # rowcount 1 = insertado, 0 = ignorado por conflicto
                if cur.rowcount == 1:
                    synced += 1
                    if lead_id:
                        touched_lead_ids.add(lead_id)
                        try:
                            from app.services import sla_service
                            sla_service.registrar_primer_contacto_sla(lead_id)
                        except Exception:
                            pass
                else:
                    skipped += 1

        conn.commit()

    for lid in touched_lead_ids:
        try:
            from app.services import lead_automation_service
            lead_automation_service.evaluar_lead_individual_no_contesta(lid)
        except Exception:
            pass

    logger.info(
        "Sync llamadas — asesor=%s synced=%d skipped=%d",
        current_user.user_id, synced, skipped,
    )
    return {"synced": synced, "skipped": skipped}


# ---------------------------------------------------------------------------
# GET /api/llamadas
# ---------------------------------------------------------------------------

@router.get("")
def list_llamadas(
    asesor_id: Optional[str] = Query(None),
    lead_id: Optional[int] = Query(None),
    tipo: Optional[str] = Query(None),
    telefono: Optional[str] = Query(None),
    fecha_desde: Optional[str] = Query(None),
    fecha_hasta: Optional[str] = Query(None),
    solo_con_lead: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Lista de llamadas con filtros opcionales.
    La visibilidad se restringe según el rol del usuario autenticado.
    """
    role_clause, role_params = _build_role_filter(current_user)

    # Condiciones adicionales de filtro
    extra_clauses = []
    extra_params = []

    if asesor_id:
        extra_clauses.append("ll.asesor_id = %s::uuid")
        extra_params.append(asesor_id)

    if lead_id:
        extra_clauses.append("ll.lead_id = %s")
        extra_params.append(lead_id)

    if telefono:
        extra_clauses.append("ll.telefono = %s")
        extra_params.append(telefono)

    if tipo:
        extra_clauses.append("ll.tipo = %s")
        extra_params.append(tipo)

    if fecha_desde:
        extra_clauses.append("ll.fecha_llamada >= %s::timestamptz")
        extra_params.append(fecha_desde)

    if fecha_hasta:
        # Incluir hasta el final del día indicado
        extra_clauses.append("ll.fecha_llamada < (%s::date + INTERVAL '1 day')::timestamptz")
        extra_params.append(fecha_hasta)

    if solo_con_lead:
        extra_clauses.append("ll.lead_id IS NOT NULL")

    # Combinar todas las cláusulas WHERE
    all_clauses = [role_clause] + extra_clauses
    where_sql = " AND ".join(all_clauses)

    # Parámetros en orden: primero los del rol, luego los extras, luego limit/offset
    all_params = role_params + extra_params

    query_total = f"""
        SELECT COUNT(*) AS total
        FROM crm.llamadas ll
        WHERE {where_sql}
    """

    query_items = f"""
        SELECT
            ll.id,
            ll.lead_id,
            COALESCE(
                TRIM(COALESCE(lm.nombres, '') || ' ' || COALESCE(lm.apellidos, '')),
                NULL
            ) AS lead_nombre,
            ll.asesor_id::text,
            TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
            ll.telefono,
            ll.duracion_segundos,
            ll.tipo,
            ll.fecha_llamada::text,
            ll.nombre_contacto,
            ll.synced_at::text,
            ll.notas,
            ll.resultado,
            ll.edited_at::text   AS edited_at
        FROM crm.llamadas ll
        LEFT JOIN auth.users u  ON u.id  = ll.asesor_id
        LEFT JOIN crm.leads lm  ON lm.id = ll.lead_id
        WHERE {where_sql}
        -- V070.7 — Tie-breaker estable: paridad con /api/leads y /api/historicos.
        -- Sin ll.id DESC el orden entre llamadas con el mismo fecha_llamada
        -- era no-deterministico (sync masivo desde mobile carga muchas calls
        -- con el mismo timestamp de batch) y la paginacion saltaba filas.
        ORDER BY ll.fecha_llamada DESC NULLS LAST, ll.id DESC
        LIMIT %s OFFSET %s
    """

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Total
            cur.execute(query_total, all_params)
            total = cur.fetchone()["total"]

            # Items paginados
            cur.execute(query_items, all_params + [limit, offset])
            items = cur.fetchall()

    return {"total": total, "items": items}


# ---------------------------------------------------------------------------
# GET /api/llamadas/stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_llamadas_stats(
    periodo: Optional[str] = Query("semana", description="hoy|semana|mes|todo"),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """
    Estadísticas de llamadas para el dashboard de supervisor/admin.
    - Totales hoy y últimos 7 días
    - Distribución por tipo (semana)
    - Duración promedio de llamadas completadas (semana)
    - Top asesores por volumen **dentro del periodo solicitado**
    El param `periodo` controla el filtro de fecha para `por_asesor`,
    `por_tipo` y `duracion_promedio`. Default `semana` mantiene el
    comportamiento previo (retrocompatible con la web).
    """
    # Traducción periodo -> cláusula SQL de fecha.
    # Centralizado aquí (SRP): el resto del endpoint solo interpola la expresión.
    periodo_norm = (periodo or "semana").lower()
    if periodo_norm == "hoy":
        periodo_clause = "ll.fecha_llamada::date = CURRENT_DATE"
    elif periodo_norm == "mes":
        periodo_clause = "ll.fecha_llamada >= date_trunc('month', CURRENT_DATE)"
    elif periodo_norm == "todo":
        periodo_clause = "TRUE"
    else:  # semana (default)
        periodo_clause = "ll.fecha_llamada >= CURRENT_DATE - INTERVAL '6 days'"

    role_clause, role_params = _build_role_filter(current_user)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # Total llamadas hoy
            cur.execute(
                f"""
                SELECT COUNT(*) AS total_hoy
                FROM crm.llamadas ll
                WHERE {role_clause}
                  AND ll.fecha_llamada::date = CURRENT_DATE
                """,
                role_params,
            )
            total_hoy = cur.fetchone()["total_hoy"]

            # Total llamadas últimos 7 días
            cur.execute(
                f"""
                SELECT COUNT(*) AS total_semana
                FROM crm.llamadas ll
                WHERE {role_clause}
                  AND {periodo_clause}
                """,
                role_params,
            )
            total_semana = cur.fetchone()["total_semana"]

            # Distribución por tipo en la semana
            cur.execute(
                f"""
                SELECT tipo, COUNT(*) AS cantidad
                FROM crm.llamadas ll
                WHERE {role_clause}
                  AND {periodo_clause}
                GROUP BY tipo
                """,
                role_params,
            )
            tipo_rows = cur.fetchall()
            por_tipo = {"saliente": 0, "entrante": 0, "perdida": 0}
            for row in tipo_rows:
                if row["tipo"] in por_tipo:
                    por_tipo[row["tipo"]] = row["cantidad"]

            # Duración promedio de llamadas completadas (saliente + entrante, semana)
            cur.execute(
                f"""
                SELECT COALESCE(AVG(ll.duracion_segundos), 0)::int AS duracion_promedio
                FROM crm.llamadas ll
                WHERE {role_clause}
                  AND ll.tipo IN ('saliente', 'entrante')
                  AND ll.duracion_segundos > 0
                  AND {periodo_clause}
                """,
                role_params,
            )
            duracion_promedio = cur.fetchone()["duracion_promedio"]

            # Top 10 asesores por volumen en la semana
            cur.execute(
                f"""
                SELECT
                    ll.asesor_id::text AS asesor_id,
                    TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
                    COUNT(*) AS total,
                    COALESCE(SUM(ll.duracion_segundos), 0)::int AS duracion_total
                FROM crm.llamadas ll
                LEFT JOIN auth.users u ON u.id = ll.asesor_id
                WHERE {role_clause}
                  AND {periodo_clause}
                GROUP BY ll.asesor_id, u.first_name, u.last_name
                ORDER BY total DESC
                LIMIT 50
                """,
                role_params,
            )
            por_asesor = cur.fetchall()

    return {
        "total_hoy": total_hoy,
        "total_semana": total_semana,
        "por_tipo": por_tipo,
        "duracion_promedio_segundos": duracion_promedio,
        "por_asesor": por_asesor,
    }


class BulkDeleteRequest(BaseModel):
    ids: List[int]


@router.delete("/bulk", status_code=200)
def delete_llamadas_bulk(data: BulkDeleteRequest, admin: TokenData = Depends(require_supervisor_or_admin)):
    """Elimina múltiples llamadas en una sola operación. Solo supervisor y admin."""
    if not data.ids:
        raise HTTPException(status_code=400, detail="Sin IDs para eliminar")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm.llamadas WHERE id = ANY(%s) RETURNING id", (data.ids,))
            deleted = cur.rowcount
        conn.commit()
    return {"deleted": deleted}


@router.delete("/{llamada_id}", status_code=200)
def delete_llamada(llamada_id: int, admin: TokenData = Depends(require_supervisor_or_admin)):
    """Elimina una llamada sincronizada. Solo supervisor y admin."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm.llamadas WHERE id = %s RETURNING id", (llamada_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Llamada no encontrada")
        conn.commit()
    return {"message": "Llamada eliminada"}


# ─── V051: Edicion de notas/resultado en llamadas del celular ─────────────

class LlamadaUpdate(BaseModel):
    notas: Optional[str] = None
    resultado: Optional[str] = None


@router.patch("/{llamada_id}", status_code=200)
def update_llamada(
    llamada_id: int,
    data: LlamadaUpdate,
    current_user: TokenData = Depends(get_current_user),
):
    """Edita notas y/o resultado de una llamada (V051).

    Permite que el asesor agregue contexto a las llamadas que vienen del
    sync de la APK (que solo traen telefono + duracion + fecha).

    Permisos:
      - asesor: solo puede editar sus propias llamadas
      - supervisor: puede editar las del equipo
      - admin: cualquiera

    NO se permite editar duracion/fecha — esos son datos objetivos del OS.
    Solo el contexto que el humano agrega.
    """
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "Sin campos a actualizar")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verificar acceso
            cur.execute(
                "SELECT asesor_id::text FROM crm.llamadas WHERE id = %s",
                (llamada_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Llamada no encontrada")
            owner_id = row["asesor_id"]
            if current_user.role == Role.ASESOR and getattr(current_user, "role_id", None) is None and owner_id != str(current_user.user_id):
                raise HTTPException(403, "Solo puedes editar tus propias llamadas")
            elif current_user.role == Role.SUPERVISOR:
                # Verificar que el asesor sea de su equipo
                cur.execute(
                    """
                    SELECT 1 FROM crm.equipos
                    WHERE supervisor_id = %s::uuid AND asesor_id = %s::uuid AND activo = TRUE
                    """,
                    (current_user.user_id, owner_id),
                )
                if not cur.fetchone() and owner_id != str(current_user.user_id):
                    raise HTTPException(403, "Solo puedes editar llamadas de tu equipo")

            # UPDATE solo de los fields enviados
            set_parts = []
            params: list = []
            for k, v in fields.items():
                set_parts.append(f"{k} = %s")
                params.append(v if v != "" else None)
            set_parts.append("edited_at = NOW()")
            set_parts.append("edited_by = %s::uuid")
            params.append(current_user.user_id)
            params.append(llamada_id)

            cur.execute(
                f"UPDATE crm.llamadas SET {', '.join(set_parts)} WHERE id = %s RETURNING id",
                params,
            )
            if not cur.fetchone():
                raise HTTPException(404, "Llamada no encontrada")
        conn.commit()
    return {"ok": True, "id": llamada_id}

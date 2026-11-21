"""
reciclaje_tmk.py — Módulo de Bolsa de Reciclaje para campañas de Telemarketing (TMK).

Permite a administradores y supervisores concentrar y reciclar leads según:
  - No contesta (>= 3 intentos fallidos de llamadas o contactos)
  - Inactivos por > 30 días sin avance
  - Cartera de ex-asesores (asesores dados de baja / inactivos)
  - Base histórica / descartados recuperables
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from app.auth.jwt import require_supervisor_or_admin
from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tmk", tags=["Bolsa Reciclaje TMK"])


class ReasignarLoteRequest(BaseModel):
    nombre_lote: str = Field(..., min_length=3, max_length=150)
    criterio: str = Field(..., pattern="^(no_contesta|inactivos_30d|ex_asesores|base_historica|todos)$")
    limite_leads: int = Field(50, ge=1, le=2000)
    asesores_ids: list[str] = Field(..., min_items=1)
    sede_id: Optional[str] = None
    descripcion: Optional[str] = None


def _ensure_lotes_schema(cur):
    """Garantiza que crm.lotes_reciclaje y crm.leads tengan las columnas requeridas para TMK."""
    cur.execute(
        """
        ALTER TABLE crm.lotes_reciclaje
            ADD COLUMN IF NOT EXISTS sede_id UUID REFERENCES crm.sedes(id) ON DELETE SET NULL;
        ALTER TABLE crm.leads
            ADD COLUMN IF NOT EXISTS fuente_pre_reciclaje_id INTEGER REFERENCES crm.fuentes(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS estado_pre_reciclaje_id INTEGER REFERENCES crm.estados_lead(id) ON DELETE SET NULL;
        """
    )


def _get_or_create_fuente_tmk(cur) -> int | None:
    """Obtiene o crea la fuente 'Bolsa TMK' en crm.fuentes para leads reciclados."""
    cur.execute("SELECT id FROM crm.fuentes WHERE LOWER(nombre) IN ('bolsa tmk', 'bolsa de reciclaje tmk', 'reciclaje tmk', 'tmk') LIMIT 1")
    frow = cur.fetchone()
    if frow:
        return frow["id"]
    try:
        cur.execute(
            "INSERT INTO crm.fuentes (nombre, activo) VALUES ('Bolsa TMK', TRUE) "
            "ON CONFLICT (nombre) DO UPDATE SET activo = TRUE RETURNING id"
        )
        frow = cur.fetchone()
        return frow["id"] if frow else None
    except Exception as exc:
        logger.warning("[reciclaje_tmk] Error asegurando fuente 'Bolsa TMK': %s", exc)
        cur.execute("SELECT id FROM crm.fuentes WHERE activo = TRUE ORDER BY id ASC LIMIT 1")
        frow = cur.fetchone()
        return frow["id"] if frow else None


def _build_criterio_where(criterio: str) -> str:
    """Retorna la cláusula SQL WHERE correspondiente al criterio de reciclaje TMK."""
    if criterio == "no_contesta":
        return """(
            TRIM(e.nombre) ILIKE 'No contesta / Bolsa TMK'
            OR TRIM(e.nombre) ILIKE 'No contesta / Bolsa de reciclaje'
            OR e.nombre ILIKE '%%Bolsa TMK%%'
            OR e.nombre ILIKE '%%Bolsa de reciclaje%%'
        )"""
    elif criterio == "inactivos_30d":
        return """(
            COALESCE(
                (SELECT MAX(created_at) FROM (
                    SELECT created_at FROM crm.contactos WHERE lead_id = l.id
                    UNION ALL
                    SELECT fecha_llamada AS created_at FROM crm.llamadas WHERE lead_id = l.id
                ) _uc),
                l.created_at
            ) < NOW() - INTERVAL '30 days'
        )"""
    elif criterio == "ex_asesores":
        return """(
            l.asesor_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM auth.users u
                WHERE u.id = l.asesor_id AND (u.is_active = FALSE OR COALESCE(u.login_blocked, FALSE) = TRUE)
            )
        )"""
    elif criterio == "base_historica":
        return """(
            (e.nombre ILIKE '%%perdid%%' OR e.nombre ILIKE '%%no inter%%' OR e.nombre ILIKE '%%descart%%')
            AND l.created_at <= NOW() - INTERVAL '15 days'
        )"""
    elif criterio == "todos":
        return f"""(
            {_build_criterio_where('no_contesta')}
            OR {_build_criterio_where('inactivos_30d')}
            OR {_build_criterio_where('ex_asesores')}
            OR {_build_criterio_where('base_historica')}
        )"""
    return "TRUE"


@router.get("/resumen")
def get_resumen_bolsa(
    sede_id: Optional[str] = None,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Retorna el conteo consolidado de leads disponibles por segmento en la Bolsa TMK."""
    where_sede = "AND l.sede_id = %s::uuid" if sede_id else ""
    params = [sede_id] if sede_id else []

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. No contesta
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND e.nombre NOT ILIKE '%%Matr%%' AND e.nombre NOT ILIKE '%%Ganad%%'
                  AND {_build_criterio_where('no_contesta')}
                  {where_sede}
                """,
                params,
            )
            no_contesta = (cur.fetchone() or {}).get("total") or 0

            # 2. Inactivos > 30 días
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND e.nombre NOT ILIKE '%%Matr%%' AND e.nombre NOT ILIKE '%%Ganad%%'
                  AND {_build_criterio_where('inactivos_30d')}
                  {where_sede}
                """,
                params,
            )
            inactivos_30d = (cur.fetchone() or {}).get("total") or 0

            # 3. Cartera de ex-asesores
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND e.nombre NOT ILIKE '%%Matr%%' AND e.nombre NOT ILIKE '%%Ganad%%'
                  AND {_build_criterio_where('ex_asesores')}
                  {where_sede}
                """,
                params,
            )
            ex_asesores = (cur.fetchone() or {}).get("total") or 0

            # 4. Base histórica / Perdidos recuperables
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.activo = TRUE
                  AND {_build_criterio_where('base_historica')}
                  {where_sede}
                """,
                params,
            )
            base_historica = (cur.fetchone() or {}).get("total") or 0

            total_disponible = no_contesta + inactivos_30d + ex_asesores + base_historica

            return {
                "no_contesta": no_contesta,
                "inactivos_30d": inactivos_30d,
                "ex_asesores": ex_asesores,
                "base_historica": base_historica,
                "total_disponible": total_disponible,
            }


class ReasignarIndividualRequest(BaseModel):
    lead_id: int
    asesor_id: str
    estado_id: Optional[int] = None
    criterio: Optional[str] = "manual"


@router.get("/leads")
def list_leads_reciclables(
    criterio: str = Query("todos", pattern="^(no_contesta|inactivos_30d|ex_asesores|base_historica|todos)$"),
    sede_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    page: Optional[int] = Query(None, ge=1),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Retorna listado paginado de leads de la bolsa según el criterio seleccionado, con búsqueda e historial de asignaciones."""
    if page and page >= 1:
        offset = (page - 1) * limit

    join_sql = """
        JOIN crm.estados_lead e ON e.id = l.estado_id
        LEFT JOIN auth.users u ON u.id = l.asesor_id
        LEFT JOIN auth.users u_prev ON u_prev.id = COALESCE(
            l.previous_asesor_id,
            (
                SELECT al.asesor_anterior
                FROM crm.asignaciones_log al
                WHERE al.lead_id = l.id
                  AND al.asesor_anterior IS NOT NULL
                ORDER BY al.created_at DESC
                LIMIT 1
            ),
            (
                SELECT al.asesor_nuevo
                FROM crm.asignaciones_log al
                WHERE al.lead_id = l.id
                  AND al.asesor_nuevo IS NOT NULL
                  AND (l.asesor_id IS NULL OR al.asesor_nuevo != l.asesor_id)
                ORDER BY al.created_at DESC
                LIMIT 1
            )
        )
    """

    where_parts = [
        "l.activo = TRUE",
        "e.nombre NOT ILIKE '%%Matr%%'",
        "e.nombre NOT ILIKE '%%Ganad%%'",
        _build_criterio_where(criterio),
    ]
    params = []

    if sede_id:
        where_parts.append("l.sede_id = %s::uuid")
        params.append(sede_id)

    if search and search.strip():
        term = f"%{search.strip()}%"
        where_parts.append("""(
            TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) ILIKE %s
            OR l.telefono ILIKE %s
            OR l.email ILIKE %s
            OR CAST(l.id AS TEXT) ILIKE %s
            OR TRIM(COALESCE(u_prev.first_name,'') || ' ' || COALESCE(u_prev.last_name,'')) ILIKE %s
            OR u_prev.email ILIKE %s
            OR TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) ILIKE %s
            OR u.email ILIKE %s
        )""")
        params.extend([term, term, term, term, term, term, term, term])

    where_sql = " AND ".join(where_parts)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_lotes_schema(cur)
            # Count total
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm.leads l
                {join_sql}
                WHERE {where_sql}
                """,
                params,
            )
            total_count = (cur.fetchone() or {}).get("total") or 0

            # List con historial de asignaciones
            cur.execute(
                f"""
                SELECT
                    l.id,
                    TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) AS nombre_completo,
                    l.telefono,
                    l.email,
                    l.campana,
                    e.id AS estado_id,
                    e.nombre AS estado_nombre,
                    e.color_hex AS estado_color,
                    f.nombre AS fuente_nombre,
                    l.asesor_id::text AS asesor_actual_id,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_actual,
                    u.email AS asesor_actual_email,
                    u_prev.id::text AS previous_asesor_id,
                    TRIM(COALESCE(u_prev.first_name,'') || ' ' || COALESCE(u_prev.last_name,'')) AS previous_asesor_nombre,
                    u_prev.email AS previous_asesor_email,
                    TRIM(COALESCE(u_prev.first_name,'') || ' ' || COALESCE(u_prev.last_name,'')) AS ultimo_asesor_nombre,
                    u_prev.email AS ultimo_asesor_email,
                    l.sede_id::text AS sede_id,
                    s.nombre AS sede_nombre,
                    l.created_at AS fecha_ingreso,
                    l.es_reciclado,
                    l.fecha_reciclaje,
                    l.origen_reciclaje,
                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'id', al.id,
                                    'asesor_anterior_id', al.asesor_anterior::text,
                                    'asesor_anterior_nombre', TRIM(COALESCE(u_ant.first_name, '') || ' ' || COALESCE(u_ant.last_name, '')),
                                    'asesor_nuevo_id', al.asesor_nuevo::text,
                                    'asesor_nuevo_nombre', TRIM(COALESCE(u_new.first_name, '') || ' ' || COALESCE(u_new.last_name, '')),
                                    'asignado_por_id', al.asignado_por::text,
                                    'asignado_por_nombre', TRIM(COALESCE(u_by.first_name, '') || ' ' || COALESCE(u_by.last_name, '')),
                                    'motivo', al.motivo,
                                    'created_at', al.created_at::text
                                ) ORDER BY al.created_at DESC
                            )
                            FROM crm.asignaciones_log al
                            LEFT JOIN auth.users u_ant ON u_ant.id = al.asesor_anterior
                            LEFT JOIN auth.users u_new ON u_new.id = al.asesor_nuevo
                            LEFT JOIN auth.users u_by ON u_by.id = al.asignado_por
                            WHERE al.lead_id = l.id
                        ),
                        '[]'::json
                    ) AS historial_asignaciones
                FROM crm.leads l
                {join_sql}
                LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                LEFT JOIN crm.sedes s ON s.id = l.sede_id
                WHERE {where_sql}
                ORDER BY l.created_at ASC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = [dict(r) for r in cur.fetchall()]

            current_page = (offset // limit) + 1
            total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

            return {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "page": current_page,
                "total_pages": total_pages,
                "leads": rows,
            }


@router.get("/exportar")
def exportar_leads_bolsa(
    request: Request,
    criterio: str = Query("todos", pattern="^(no_contesta|inactivos_30d|ex_asesores|base_historica|todos)$"),
    sede_id: Optional[str] = None,
    search: Optional[str] = None,
    ids: Optional[str] = None,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """
    Exporta a un libro Excel (.xlsx) todos los contactos de la Bolsa TMK o del segmento filtrado,
    con formato corporativo listo para gestión (estilos, autofiltros, anchos de columna, formato fecha/teléfono).
    """
    join_sql = """
        JOIN crm.estados_lead e ON e.id = l.estado_id
        LEFT JOIN auth.users u ON u.id = l.asesor_id
        LEFT JOIN auth.users u_prev ON u_prev.id = COALESCE(
            l.previous_asesor_id,
            (
                SELECT al.asesor_anterior
                FROM crm.asignaciones_log al
                WHERE al.lead_id = l.id
                  AND al.asesor_anterior IS NOT NULL
                ORDER BY al.created_at DESC
                LIMIT 1
            ),
            (
                SELECT al.asesor_nuevo
                FROM crm.asignaciones_log al
                WHERE al.lead_id = l.id
                  AND al.asesor_nuevo IS NOT NULL
                  AND (l.asesor_id IS NULL OR al.asesor_nuevo != l.asesor_id)
                ORDER BY al.created_at DESC
                LIMIT 1
            )
        )
        LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
        LEFT JOIN crm.sedes s ON s.id = l.sede_id
        LEFT JOIN crm.lotes_reciclaje lr ON lr.id = l.lote_reciclaje_id
    """

    where_parts = [
        "l.activo = TRUE",
        "e.nombre NOT ILIKE '%%Matr%%'",
        "e.nombre NOT ILIKE '%%Ganad%%'",
    ]
    params = []

    target_ids = []
    if ids and ids.strip():
        for x in ids.split(","):
            x = x.strip()
            if x.isdigit():
                target_ids.append(int(x))

    if target_ids:
        where_parts.append("l.id = ANY(%s)")
        params.append(target_ids)
    else:
        where_parts.append(_build_criterio_where(criterio))

        if sede_id:
            where_parts.append("l.sede_id = %s::uuid")
            params.append(sede_id)

        if search and search.strip():
            term = f"%{search.strip()}%"
            where_parts.append("""(
                TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) ILIKE %s
                OR l.telefono ILIKE %s
                OR l.email ILIKE %s
                OR CAST(l.id AS TEXT) ILIKE %s
                OR TRIM(COALESCE(u_prev.first_name,'') || ' ' || COALESCE(u_prev.last_name,'')) ILIKE %s
                OR u_prev.email ILIKE %s
                OR TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) ILIKE %s
                OR u.email ILIKE %s
            )""")
            params.extend([term, term, term, term, term, term, term, term])

    where_sql = " AND ".join(where_parts)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_lotes_schema(cur)
            cur.execute(
                f"""
                SELECT
                    l.id,
                    TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) AS nombre_completo,
                    l.telefono,
                    l.dni,
                    l.email,
                    l.ciudad,
                    CASE
                        WHEN (TRIM(e.nombre) ILIKE 'No contesta / Bolsa TMK' OR TRIM(e.nombre) ILIKE 'No contesta / Bolsa de reciclaje' OR e.nombre ILIKE '%%Bolsa TMK%%' OR e.nombre ILIKE '%%Bolsa de reciclaje%%')
                            THEN 'No Contesta'
                        WHEN (l.asesor_id IS NOT NULL AND EXISTS (SELECT 1 FROM auth.users u2 WHERE u2.id = l.asesor_id AND (u2.is_active = FALSE OR COALESCE(u2.login_blocked, FALSE) = TRUE)))
                            THEN 'Cartera Ex-asesor'
                        WHEN ((e.nombre ILIKE '%%perdid%%' OR e.nombre ILIKE '%%no inter%%' OR e.nombre ILIKE '%%descart%%') AND l.created_at <= NOW() - INTERVAL '15 days')
                            THEN 'Base Histórica'
                        WHEN (COALESCE((SELECT MAX(created_at) FROM (SELECT created_at FROM crm.contactos WHERE lead_id = l.id UNION ALL SELECT fecha_llamada AS created_at FROM crm.llamadas WHERE lead_id = l.id) _uc), l.created_at) < NOW() - INTERVAL '30 days')
                            THEN 'Inactivo > 30 días'
                        ELSE 'Bolsa TMK'
                    END AS segmento_bolsa,
                    e.nombre AS estado_nombre,
                    COALESCE(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')), 'Sin asesor') AS asesor_actual,
                    COALESCE(u.email, '') AS asesor_actual_email,
                    COALESCE(TRIM(COALESCE(u_prev.first_name,'') || ' ' || COALESCE(u_prev.last_name,'')), '—') AS ultimo_asesor_previo,
                    COALESCE(u_prev.email, '') AS ultimo_asesor_email,
                    COALESCE(s.nombre, 'Sin sede') AS sede_nombre,
                    COALESCE(f.nombre, '—') AS fuente_nombre,
                    COALESCE(l.campana, '—') AS campana,
                    COALESCE(l.anuncio, '—') AS anuncio,
                    l.created_at AS fecha_ingreso,
                    l.reassigned_at AS fecha_reasignacion,
                    CASE WHEN l.es_reciclado = TRUE THEN 'Sí' ELSE 'No' END AS es_reciclado,
                    l.fecha_reciclaje,
                    COALESCE(l.origen_reciclaje, '—') AS origen_reciclaje,
                    COALESCE(lr.nombre, '—') AS lote_reciclaje_nombre,
                    (
                        (SELECT COUNT(*) FROM crm.contactos c2 WHERE c2.lead_id = l.id AND c2.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion'))
                      + (SELECT COUNT(*) FROM crm.llamadas ll WHERE ll.lead_id = l.id)
                    ) AS intentos_contacto,
                    COALESCE(
                        (SELECT MAX(created_at) FROM (
                            SELECT created_at FROM crm.contactos WHERE lead_id = l.id
                            UNION ALL
                            SELECT fecha_llamada AS created_at FROM crm.llamadas WHERE lead_id = l.id
                        ) _uc),
                        l.created_at
                    ) AS ultima_actividad,
                    (SELECT tipo_contacto FROM crm.contactos WHERE lead_id = l.id ORDER BY created_at DESC LIMIT 1) AS ultimo_tipo_contacto,
                    (SELECT resultado FROM crm.contactos WHERE lead_id = l.id ORDER BY created_at DESC LIMIT 1) AS ultimo_resultado,
                    COALESCE(l.observaciones, (SELECT notas FROM crm.contactos WHERE lead_id = l.id AND notas IS NOT NULL AND TRIM(notas) != '' ORDER BY created_at DESC LIMIT 1)) AS observaciones
                FROM crm.leads l
                {join_sql}
                WHERE {where_sql}
                ORDER BY l.created_at ASC
                LIMIT 10000
                """,
                params,
            )
            rows = cur.fetchall()

    logger.info(
        "[reciclaje_tmk] Exportando %d leads de la bolsa (criterio=%s, sede=%s, user=%s)",
        len(rows),
        criterio if not target_ids else "seleccionados",
        sede_id,
        current_user.user_id,
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bolsa TMK"

    COLUMNS = [
        {"header": "ID Lead", "key": "id", "width": 10, "align": "center"},
        {"header": "Nombre Completo", "key": "nombre_completo", "width": 28},
        {"header": "Teléfono", "key": "telefono", "width": 16, "align": "left"},
        {"header": "DNI", "key": "dni", "width": 14, "align": "center"},
        {"header": "Email", "key": "email", "width": 28},
        {"header": "Ciudad", "key": "ciudad", "width": 16},
        {"header": "Segmento Bolsa", "key": "segmento_bolsa", "width": 20, "align": "center"},
        {"header": "Estado Actual", "key": "estado_nombre", "width": 18},
        {"header": "Asesor Actual", "key": "asesor_actual", "width": 22},
        {"header": "Email Asesor Actual", "key": "asesor_actual_email", "width": 26},
        {"header": "Último Asesor Previo", "key": "ultimo_asesor_previo", "width": 22},
        {"header": "Email Asesor Previo", "key": "ultimo_asesor_email", "width": 26},
        {"header": "Sede", "key": "sede_nombre", "width": 16},
        {"header": "Fuente", "key": "fuente_nombre", "width": 16},
        {"header": "Campaña", "key": "campana", "width": 24},
        {"header": "Anuncio", "key": "anuncio", "width": 20},
        {"header": "Fecha Ingreso", "key": "fecha_ingreso", "width": 18, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Fecha Reasignación", "key": "fecha_reasignacion", "width": 18, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Es Reciclado", "key": "es_reciclado", "width": 14, "align": "center"},
        {"header": "Fecha Reciclaje", "key": "fecha_reciclaje", "width": 18, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Origen Reciclaje", "key": "origen_reciclaje", "width": 22},
        {"header": "Lote Reciclaje", "key": "lote_reciclaje_nombre", "width": 26},
        {"header": "Intentos Contacto", "key": "intentos_contacto", "width": 16, "align": "center", "fmt": "0"},
        {"header": "Última Actividad", "key": "ultima_actividad", "width": 18, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Último Tipo Contacto", "key": "ultimo_tipo_contacto", "width": 18, "align": "center"},
        {"header": "Último Resultado", "key": "ultimo_resultado", "width": 20},
        {"header": "Observaciones / Notas", "key": "observaciones", "width": 45, "wrap": True},
    ]

    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(border_style="thin", color="D1D5DB")
    cell_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    zebra_fill = PatternFill("solid", fgColor="F8FAFC")

    for c_idx, col in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=c_idx, value=col["header"])
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = cell_border
        ws.column_dimensions[get_column_letter(c_idx)].width = col["width"]

    ws.row_dimensions[1].height = 28

    for r_idx, row in enumerate(rows, 2):
        is_zebra = (r_idx % 2 == 0)
        for c_idx, col in enumerate(COLUMNS, 1):
            val = row.get(col["key"])
            if col["key"] in ("telefono", "dni") and val is not None:
                val = str(val)
            if isinstance(val, datetime) and val.tzinfo is not None:
                val = val.replace(tzinfo=None)

            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            if "fmt" in col:
                cell.number_format = col["fmt"]
            cell.alignment = Alignment(
                horizontal=col.get("align", "left"),
                vertical="center",
                wrap_text=col.get("wrap", False),
            )
            cell.border = cell_border
            if is_zebra:
                cell.fill = zebra_fill

    ws.freeze_panes = "A2"
    last_col_letter = get_column_letter(len(COLUMNS))
    ws.auto_filter.ref = f"A1:{last_col_letter}{max(len(rows) + 1, 2)}"
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0

    output = io.BytesIO()
    wb.save(output)
    content = output.getvalue()

    today = date.today().strftime("%Y-%m-%d")
    suffix = "seleccionados" if target_ids else criterio
    filename = f"contactos_bolsa_tmk_{suffix}_{today}.xlsx"

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/reasignar-lead-individual")
def reasignar_lead_individual(
    body: ReasignarIndividualRequest,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Reasigna un lead específico de la Bolsa TMK a un asesor o supervisor de forma directa."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_lotes_schema(cur)
            fuente_tmk_id = _get_or_create_fuente_tmk(cur)

            cur.execute(
                """
                SELECT id, asesor_id, fuente_id, estado_id
                FROM crm.leads
                WHERE id = %s AND activo = TRUE
                FOR UPDATE
                """,
                (body.lead_id,),
            )
            lead = cur.fetchone()
            if not lead:
                raise HTTPException(status_code=404, detail="Lead no encontrado.")

            asesor_ant = lead["asesor_id"]
            fuente_ant = lead["fuente_id"]
            estado_ant = lead["estado_id"]

            nuevo_estado_id = body.estado_id
            if not nuevo_estado_id:
                cur.execute("SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%Nuevo%%' ORDER BY orden ASC LIMIT 1")
                ne_row = cur.fetchone()
                nuevo_estado_id = ne_row["id"] if ne_row else estado_ant

            cur.execute(
                """
                UPDATE crm.leads
                SET
                    previous_asesor_id = COALESCE(%s::uuid, previous_asesor_id),
                    reassigned_at = NOW(),
                    fuente_pre_reciclaje_id = COALESCE(fuente_pre_reciclaje_id, %s),
                    estado_pre_reciclaje_id = COALESCE(estado_pre_reciclaje_id, %s),
                    asesor_id = %s::uuid,
                    estado_id = COALESCE(%s, estado_id),
                    fuente_id = COALESCE(%s, fuente_id),
                    es_reciclado = TRUE,
                    fecha_reciclaje = NOW(),
                    origen_reciclaje = %s,
                    sla_15m_cumplido = NULL,
                    sla_15m_notificado_at = NULL,
                    sla_24h_notificado_at = NULL,
                    atencion_prioritaria = TRUE,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    asesor_ant,
                    fuente_ant,
                    estado_ant,
                    body.asesor_id,
                    nuevo_estado_id,
                    fuente_tmk_id,
                    f"Bolsa TMK ({body.criterio})",
                    body.lead_id,
                ),
            )

            # Auditoría en asignaciones_log
            cur.execute(
                """
                INSERT INTO crm.asignaciones_log (
                    lead_id,
                    asesor_anterior,
                    asesor_nuevo,
                    asignado_por,
                    motivo
                ) VALUES (
                    %s,
                    %s,
                    %s::uuid,
                    %s::uuid,
                    %s
                )
                """,
                (
                    body.lead_id,
                    asesor_ant,
                    body.asesor_id,
                    current_user.user_id,
                    f"reciclaje_tmk:individual:{body.criterio}",
                ),
            )

            # Auditoría en contactos
            cur.execute(
                """
                INSERT INTO crm.contactos (
                    lead_id,
                    asesor_id,
                    tipo_contacto,
                    resultado,
                    notas
                ) VALUES (
                    %s,
                    %s::uuid,
                    'reasignacion',
                    'Reasignación TMK Directa',
                    'Reasignado individualmente desde Bolsa TMK a asesor/supervisor'
                )
                """,
                (
                    body.lead_id,
                    current_user.user_id,
                ),
            )

            # Sincronizar WhatsApp
            cur.execute(
                """
                UPDATE crm.wa_conversations
                   SET asesor_id = %s::uuid
                 WHERE lead_id = %s
                """,
                (body.asesor_id, body.lead_id),
            )

            conn.commit()

            return {
                "ok": True,
                "lead_id": body.lead_id,
                "message": f"Lead #{body.lead_id} reasignado exitosamente.",
            }


@router.post("/reasignar-lote")
def reasignar_lote_tmk(
    body: ReasignarLoteRequest,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Crea un lote y reasigna los leads seleccionados equitativamente entre los asesores de TMK."""
    where_parts = [
        "l.activo = TRUE",
        "e.nombre NOT ILIKE '%%Matr%%'",
        "e.nombre NOT ILIKE '%%Ganad%%'",
        _build_criterio_where(body.criterio),
    ]
    params = []

    if body.sede_id:
        where_parts.append("l.sede_id = %s::uuid")
        params.append(body.sede_id)

    where_sql = " AND ".join(where_parts)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_lotes_schema(cur)
            # 1. Obtener o asegurar la fuente "Bolsa TMK"
            fuente_tmk_id = _get_or_create_fuente_tmk(cur)

            # 2. Obtener estado "Nuevo" o primer estado según orden para los leads reasignados
            cur.execute("SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%Nuevo%%' ORDER BY orden ASC LIMIT 1")
            nuevo_estado_row = cur.fetchone()
            if not nuevo_estado_row:
                cur.execute("SELECT id FROM crm.estados_lead ORDER BY orden ASC LIMIT 1")
                nuevo_estado_row = cur.fetchone()
            nuevo_estado_id = nuevo_estado_row["id"] if nuevo_estado_row else None

            # 3. Seleccionar los leads candidatos respetando el límite
            cur.execute(
                f"""
                SELECT
                    l.id,
                    l.asesor_id AS asesor_anterior_id,
                    l.fuente_id AS fuente_anterior_id,
                    l.estado_id AS estado_anterior_id
                FROM crm.leads l
                JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE {where_sql}
                ORDER BY l.created_at ASC
                LIMIT %s
                FOR UPDATE OF l SKIP LOCKED
                """,
                params + [body.limite_leads],
            )
            candidatos = cur.fetchall()

            if not candidatos:
                raise HTTPException(status_code=400, detail="No se encontraron leads disponibles para el criterio y sede seleccionados.")

            # 4. Crear el lote en crm.lotes_reciclaje
            cur.execute(
                """
                INSERT INTO crm.lotes_reciclaje (
                    nombre,
                    criterio,
                    descripcion,
                    total_leads,
                    asesores_asignados,
                    sede_id,
                    creado_por
                ) VALUES (
                    %s, %s, %s, %s, %s::jsonb, %s::uuid, %s::uuid
                ) RETURNING id
                """,
                (
                    body.nombre_lote,
                    body.criterio,
                    body.descripcion or "",
                    len(candidatos),
                    json.dumps(body.asesores_ids),
                    body.sede_id if body.sede_id else None,
                    current_user.user_id,
                ),
            )
            lote_id = cur.fetchone()["id"]

            # 5. Asignación round-robin equitativa entre los asesores/supervisores destino
            num_asesores = len(body.asesores_ids)
            for idx, cand in enumerate(candidatos):
                nuevo_asesor_id = body.asesores_ids[idx % num_asesores]
                lead_id = cand["id"]
                asesor_ant = cand["asesor_anterior_id"]
                fuente_ant = cand["fuente_anterior_id"]
                estado_ant = cand["estado_anterior_id"]

                # Actualizar lead
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET
                        previous_asesor_id = COALESCE(%s::uuid, previous_asesor_id),
                        reassigned_at = NOW(),
                        fuente_pre_reciclaje_id = COALESCE(fuente_pre_reciclaje_id, %s),
                        estado_pre_reciclaje_id = COALESCE(estado_pre_reciclaje_id, %s),
                        asesor_id = %s::uuid,
                        estado_id = COALESCE(%s, estado_id),
                        fuente_id = COALESCE(%s, fuente_id),
                        es_reciclado = TRUE,
                        fecha_reciclaje = NOW(),
                        origen_reciclaje = %s,
                        lote_reciclaje_id = %s::uuid,
                        sla_15m_cumplido = NULL,
                        sla_15m_notificado_at = NULL,
                        sla_24h_notificado_at = NULL,
                        atencion_prioritaria = TRUE,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        asesor_ant,
                        fuente_ant,
                        estado_ant,
                        nuevo_asesor_id,
                        nuevo_estado_id,
                        fuente_tmk_id,
                        "Bolsa TMK",
                        lote_id,
                        lead_id,
                    ),
                )

                # Registrar en crm.asignaciones_log para auditoría de reasignación
                cur.execute(
                    """
                    INSERT INTO crm.asignaciones_log (
                        lead_id,
                        asesor_anterior,
                        asesor_nuevo,
                        asignado_por,
                        motivo
                    ) VALUES (
                        %s,
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s
                    )
                    """,
                    (
                        lead_id,
                        asesor_ant,
                        nuevo_asesor_id,
                        current_user.user_id,
                        f"reciclaje_tmk:{body.criterio}",
                    ),
                )

                # Propagar cambio al chat WhatsApp asociado (si existe)
                cur.execute(
                    """
                    UPDATE crm.wa_conversations
                       SET asesor_id = %s::uuid
                     WHERE lead_id = %s
                    """,
                    (nuevo_asesor_id, lead_id),
                )

                # Registrar contacto de auditoría / trazabilidad
                cur.execute(
                    """
                    INSERT INTO crm.contactos (
                        lead_id,
                        asesor_id,
                        tipo_contacto,
                        resultado,
                        notas
                    ) VALUES (
                        %s,
                        %s::uuid,
                        'reasignacion',
                        'Reciclado TMK',
                        %s
                    )
                    """,
                    (
                        lead_id,
                        current_user.user_id,
                        f"Reasignado a TMK vía lote '{body.nombre_lote}' (Criterio: {body.criterio})",
                    ),
                )

            conn.commit()
            logger.info(
                "[TMK] Lote '%s' (%s) creado: %d leads reasignados entre %d asesores.",
                body.nombre_lote,
                lote_id,
                len(candidatos),
                num_asesores,
            )

            return {
                "ok": True,
                "lote_id": str(lote_id),
                "leads_reasignados": len(candidatos),
                "asesores_involucrados": num_asesores,
                "message": f"Se reasignaron exitosamente {len(candidatos)} leads entre {num_asesores} asesores.",
            }


@router.get("/lotes")
def list_lotes_reciclaje(
    limit: int = Query(20, ge=1, le=100),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Retorna historial de lotes de telemarketing ejecutados."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_lotes_schema(cur)
            cur.execute(
                """
                SELECT
                    lr.id,
                    lr.nombre,
                    lr.criterio,
                    lr.descripcion,
                    lr.total_leads,
                    lr.asesores_asignados,
                    lr.created_at,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS creado_por_nombre,
                    s.nombre AS sede_nombre
                FROM crm.lotes_reciclaje lr
                LEFT JOIN auth.users u ON u.id = lr.creado_por
                LEFT JOIN crm.sedes s ON s.id = lr.sede_id
                ORDER BY lr.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return {"lotes": [dict(r) for r in cur.fetchall()]}


class RevertirTmkRequest(BaseModel):
    ids: Optional[list[int]] = Field(None, description="Lista de IDs de leads a revertir")
    lead_ids: Optional[list[int]] = Field(None, description="Alias de ids")

    def get_target_ids(self) -> list[int]:
        raw = self.ids or self.lead_ids or []
        res = []
        for x in raw:
            try:
                val = int(x)
                if val > 0:
                    res.append(val)
            except (TypeError, ValueError):
                pass
        return res


@router.post("/revertir")
def revertir_leads_tmk(
    body: RevertirTmkRequest,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """
    Revierte la asignación de leads movidos por la Bolsa de Reciclaje TMK:
    1. Devuelve el lead a su asesor anterior (o NULL si no tenía asesor).
    2. Restaura la fuente anterior (o desvincula 'Bolsa TMK').
    3. Restaura el estado anterior (o estado previo a la asignación de TMK).
    4. Limpia los flags es_reciclado, fecha_reciclaje, origen_reciclaje, lote_reciclaje_id.
    5. Registra el evento en crm.asignaciones_log y crm.contactos.
    6. Sincroniza la conversación de WhatsApp con el asesor restaurado.
    """
    target_ids = body.get_target_ids()
    if not target_ids:
        raise HTTPException(status_code=400, detail="No se enviaron IDs de leads válidos para revertir.")

    revertidos = 0
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_lotes_schema(cur)

            # Buscar leads candidatos
            cur.execute(
                """
                SELECT
                    l.id,
                    l.asesor_id AS asesor_actual_id,
                    l.previous_asesor_id,
                    l.fuente_id,
                    l.fuente_pre_reciclaje_id,
                    l.estado_id,
                    l.estado_pre_reciclaje_id,
                    l.lote_reciclaje_id,
                    l.origen_reciclaje
                FROM crm.leads l
                WHERE l.id = ANY(%s)
                FOR UPDATE OF l
                """,
                (target_ids,),
            )
            leads_rows = cur.fetchall()

            if not leads_rows:
                raise HTTPException(status_code=404, detail="No se encontraron los leads especificados.")

            for lead in leads_rows:
                lead_id = lead["id"]
                asesor_actual = lead["asesor_actual_id"]

                # 1. Determinar asesor anterior
                asesor_anterior = lead["previous_asesor_id"]
                if not asesor_anterior:
                    # Buscar en asignaciones_log
                    cur.execute(
                        """
                        SELECT asesor_anterior
                        FROM crm.asignaciones_log
                        WHERE lead_id = %s
                          AND (motivo ILIKE '%%reciclaje_tmk%%' OR motivo ILIKE '%%Bolsa TMK%%')
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (lead_id,),
                    )
                    log_row = cur.fetchone()
                    if log_row:
                        asesor_anterior = log_row["asesor_anterior"]

                # 2. Determinar fuente anterior
                fuente_restaurada = lead.get("fuente_pre_reciclaje_id")
                if not fuente_restaurada:
                    # Si no hay fuente_pre_reciclaje_id, buscar la primera fuente general que no sea TMK
                    cur.execute(
                        """
                        SELECT id FROM crm.fuentes
                        WHERE LOWER(nombre) NOT IN ('bolsa tmk', 'bolsa de reciclaje tmk', 'reciclaje tmk', 'tmk')
                          AND activo = TRUE
                        ORDER BY id ASC LIMIT 1
                        """
                    )
                    f_default = cur.fetchone()
                    fuente_restaurada = f_default["id"] if f_default else lead["fuente_id"]

                # 3. Determinar estado anterior
                estado_restaurado = lead.get("estado_pre_reciclaje_id")
                if not estado_restaurado:
                    cur.execute(
                        """
                        SELECT id FROM crm.estados_lead
                        WHERE nombre ILIKE '%%No contesta / Bolsa TMK%%'
                           OR nombre ILIKE '%%Bolsa TMK%%'
                           OR nombre ILIKE '%%No contesta%%'
                           OR nombre ILIKE '%%Sin respuesta%%'
                        ORDER BY orden ASC LIMIT 1
                        """
                    )
                    e_row = cur.fetchone()
                    if not e_row:
                        cur.execute("SELECT id FROM crm.estados_lead ORDER BY orden ASC LIMIT 1")
                        e_row = cur.fetchone()
                    estado_restaurado = e_row["id"] if e_row else lead["estado_id"]

                # 4. Actualizar lead
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET
                        asesor_id = %s::uuid,
                        previous_asesor_id = %s::uuid,
                        reassigned_at = NOW(),
                        fuente_id = %s,
                        estado_id = %s,
                        es_reciclado = FALSE,
                        fecha_reciclaje = NULL,
                        origen_reciclaje = NULL,
                        lote_reciclaje_id = NULL,
                        fuente_pre_reciclaje_id = NULL,
                        estado_pre_reciclaje_id = NULL,
                        atencion_prioritaria = FALSE,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        asesor_anterior,
                        asesor_actual,
                        fuente_restaurada,
                        estado_restaurado,
                        lead_id,
                    ),
                )

                # 5. Registrar en asignaciones_log
                cur.execute(
                    """
                    INSERT INTO crm.asignaciones_log (
                        lead_id,
                        asesor_anterior,
                        asesor_nuevo,
                        asignado_por,
                        motivo
                    ) VALUES (
                        %s,
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        'reversion_reciclaje_tmk'
                    )
                    """,
                    (
                        lead_id,
                        asesor_actual,
                        asesor_anterior,
                        current_user.user_id,
                    ),
                )

                # 6. Registrar en contactos para trazabilidad
                cur.execute(
                    """
                    INSERT INTO crm.contactos (
                        lead_id,
                        asesor_id,
                        tipo_contacto,
                        resultado,
                        notas
                    ) VALUES (
                        %s,
                        %s::uuid,
                        'reasignacion',
                        'Reversión TMK',
                        'Lead devuelto de Bolsa TMK a su asignación y estado original'
                    )
                    """,
                    (
                        lead_id,
                        current_user.user_id,
                    ),
                )

                # 7. Sincronizar conversación WhatsApp
                cur.execute(
                    """
                    UPDATE crm.wa_conversations
                       SET asesor_id = %s::uuid
                     WHERE lead_id = %s
                    """,
                    (asesor_anterior, lead_id),
                )

                revertidos += 1

            conn.commit()
            logger.info(
                "[TMK] %d leads revertidos de Bolsa TMK por usuario %s",
                revertidos,
                current_user.user_id,
            )

            return {
                "ok": True,
                "revertidos": revertidos,
                "message": f"Se revirtieron exitosamente {revertidos} lead(s) de la Bolsa TMK.",
            }


class DesasignarTmkRequest(BaseModel):
    ids: Optional[list[int]] = Field(None, description="Lista de IDs de leads a desasignar")
    lead_ids: Optional[list[int]] = Field(None, description="Alias de ids")
    criterio: Optional[str] = Field(None, description="Criterio si es desasignación masiva por segmento")
    sede_id: Optional[str] = Field(None, description="Sede para filtrado si aplica")
    desasignar_todos_en_filtro: Optional[bool] = Field(False, description="Desasignar todos los leads del filtro actual")

    def get_target_ids(self) -> list[int]:
        raw = self.ids or self.lead_ids or []
        return [int(x) for x in raw if x is not None]


@router.post("/desasignar-leads")
def desasignar_leads_tmk(
    body: DesasignarTmkRequest,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """
    Quita el asesor asignado a los leads especificados o del segmento filtrado en Bolsa TMK,
    dejándolos como 'Sin asesor' y registrando la auditoría en crm.asignaciones_log y crm.contactos.
    """
    target_ids = body.get_target_ids()

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if body.desasignar_todos_en_filtro and body.criterio:
                where_parts = [
                    "l.activo = TRUE",
                    "l.asesor_id IS NOT NULL",
                    "e.nombre NOT ILIKE '%%Matr%%'",
                    "e.nombre NOT ILIKE '%%Ganad%%'",
                    _build_criterio_where(body.criterio),
                ]
                params = []
                if body.sede_id:
                    where_parts.append("l.sede_id = %s::uuid")
                    params.append(body.sede_id)
                where_sql = " AND ".join(where_parts)
                cur.execute(
                    f"""
                    SELECT l.id, l.asesor_id::text AS asesor_actual
                    FROM crm.leads l
                    JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE {where_sql}
                    FOR UPDATE OF l SKIP LOCKED
                    """,
                    params,
                )
                leads_to_unassign = cur.fetchall()
            elif target_ids:
                cur.execute(
                    """
                    SELECT l.id, l.asesor_id::text AS asesor_actual
                    FROM crm.leads l
                    WHERE l.id = ANY(%s) AND l.activo = TRUE
                    FOR UPDATE OF l SKIP LOCKED
                    """,
                    (target_ids,),
                )
                leads_to_unassign = cur.fetchall()
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Debe especificar una lista de leads o activar desasignar_todos_en_filtro.",
                )

            if not leads_to_unassign:
                return {
                    "ok": True,
                    "desasignados": 0,
                    "message": "No se encontraron leads con asesor para desasignar.",
                }

            desasignados = 0
            for row in leads_to_unassign:
                lid = row["id"]
                asesor_ant = row["asesor_actual"]

                cur.execute(
                    """
                    UPDATE crm.leads
                    SET previous_asesor_id = COALESCE(%s::uuid, previous_asesor_id),
                        asesor_id = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (asesor_ant, lid),
                )

                if asesor_ant:
                    cur.execute(
                        """
                        INSERT INTO crm.asignaciones_log (
                            lead_id,
                            asesor_anterior,
                            asesor_nuevo,
                            asignado_por,
                            motivo
                        ) VALUES (%s, %s::uuid, NULL, %s::uuid, 'desasignacion_bolsa_tmk')
                        """,
                        (lid, asesor_ant, current_user.user_id),
                    )
                    cur.execute(
                        """
                        UPDATE crm.wa_conversations
                           SET asesor_id = NULL
                         WHERE lead_id = %s
                        """,
                        (lid,),
                    )

                cur.execute(
                    """
                    INSERT INTO crm.contactos (
                        lead_id,
                        asesor_id,
                        tipo_contacto,
                        resultado,
                        notas
                    ) VALUES (
                        %s,
                        %s::uuid,
                        'cambio_estado',
                        'Desasignado',
                        'Asesor desasignado desde la Bolsa de Reciclaje TMK'
                    )
                    """,
                    (lid, current_user.user_id),
                )
                desasignados += 1

            conn.commit()
            logger.info("[TMK] %d leads desasignados por usuario %s", desasignados, current_user.user_id)
            return {
                "ok": True,
                "desasignados": desasignados,
                "message": f"Se quitó el asesor a {desasignados} lead(s) exitosamente.",
            }


@router.post("/automatizacion-no-contesta")
def ejecutar_automatizacion_no_contesta(
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """
    Ejecuta manualmente la automatización completa de estados de No contesta
    (Día 1, Día 2, Día 3) y hacia 'No contesta / Bolsa de reciclaje' tras 12 horas.
    """
    from app.services.lead_automation_service import procesar_automatizaciones_estados_no_contesta
    resultado = procesar_automatizaciones_estados_no_contesta()
    return resultado

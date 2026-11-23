"""
Leads router — CRUD con filtrado por rol.
- admin:      ve todos los leads
- supervisor: ve leads de sus asesores (crm.equipos)
- asesor:     ve solo sus propios leads
"""
import io
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from fastapi import APIRouter, HTTPException, Depends, Query, Request, Body
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, field_validator, Field
from typing import Optional, List


# V041 — comprobacion defensiva: si la migracion V041 no se ha aplicado
# todavia en el ambiente, la columna `tipo_documento` no existe y los
# INSERT/UPDATE que la referencian fallarian con error generico. Cacheamos
# la respuesta porque el schema no cambia en runtime; el restart de deploy
# refresca el cache automaticamente.
@lru_cache(maxsize=1)
def _has_tipo_documento_column() -> bool:
    try:
        from app.database import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'leads'
                      AND column_name  = 'tipo_documento'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        # Si la consulta de schema falla, asumimos que NO existe para
        # no romper el flujo principal con queries que la referencian.
        return False


# V117: tolerancia a drift de esquema para proxima_gestion_notificada_at.
@lru_cache(maxsize=1)
def _has_proxima_gestion_notificada_column() -> bool:
    try:
        from app.database import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'leads'
                      AND column_name  = 'proxima_gestion_notificada_at'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


# V119: tolerancia a drift de esquema para gestion_especial_admin.
@lru_cache(maxsize=1)
def _has_gestion_especial_admin_column() -> bool:
    try:
        from app.database import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'leads'
                      AND column_name  = 'gestion_especial_admin'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


# V124: tolerancia a drift de esquema para ficha_tecnica.
_has_ft_cached = None

def _has_ficha_tecnica_column() -> bool:
    global _has_ft_cached
    if _has_ft_cached is True:
        return True
    try:
        from app.database import get_db
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'leads'
                      AND column_name  = 'ficha_tecnica'
                    LIMIT 1
                    """
                )
                exists = cur.fetchone() is not None
                if exists:
                    _has_ft_cached = True
                return exists
    except Exception:  # noqa: BLE001
        return False



EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# V040: documento de identidad acepta DNI / CE / Pasaporte. La columna
# `dni` es TEXT y guarda el codigo crudo; el tipo se infiere por longitud
# y composicion. Patron unificado:
#   - 8 digitos numericos        → DNI peruano nacional
#   - 9 digitos numericos        → Carnet de Extranjeria moderno
#   - 6 a 12 caracteres alfanum  → Pasaporte (incluye los dos casos numericos)
# El frontend ya valida por tipo seleccionado; este regex es la salvaguarda
# de "defense in depth" — solo rechaza valores claramente malformados.
DNI_RE = re.compile(r"^[A-Z0-9]{6,12}$")


# V028: la calidad es configurable desde `crm.catalogo_calidad`. Se consulta
# bajo demanda y se cachea por request (no en memoria proceso) para que los
# cambios del admin se reflejen sin reiniciar el servidor. Un set vacío nunca
# debería ocurrir porque los seeds crean FRIO/TIBIO/CALIENTE, pero si ocurre
# aceptamos cualquier valor para no bloquear el sistema.
def _load_calidad_codigos() -> set[str]:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT codigo FROM crm.catalogo_calidad WHERE activo = TRUE"
                )
                return {r[0] for r in cur.fetchall()}
    except Exception:
        return set()
from app.auth.jwt import get_current_user, require_admin, require_supervisor_or_admin
from app.auth.permissions import check_permission, has_permission
from app.auth.rate_limit import limiter
from app.auth.schemas import TokenData
from app.constants import Role
from app.database import get_db
from app.filters.lead_filters import LeadFilters, lead_filters_query, role_filter
from app.repositories import leads_repository
from app.services import assignments_service, audit_service, field_security_service
from app.sql_utils import safe_set_clause

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/leads", tags=["Leads"])


# ---------------------------------------------------------------------------
# Listar leads (paginado)
# ---------------------------------------------------------------------------

@router.get("")
@limiter.limit("120/minute")  # V070.66 — anti-scraping de PII (Ley 29733 PE)
def list_leads(
    request: Request,
    filters: LeadFilters = Depends(lead_filters_query),
    limit: int = Query(50, le=1000),
    offset: int = Query(0, ge=0),
    sort: Optional[str] = Query(None, description="Ej: 'fecha_ingreso:desc' o 'nombre_completo:asc,fecha_ingreso:desc'"),
    current_user: TokenData = Depends(get_current_user),
):
    rows, total = leads_repository.find_paginated(
        filters, current_user, limit=limit, offset=offset, sort=sort,
    )

    # Audit log: registra que el usuario listo leads, cuantos vio y con que
    # filtros. Fail-safe: si el insert falla no afecta la respuesta.
    audit_service.record_list(
        user=current_user,
        lead_count=len(rows),
        filters=filters.model_dump(exclude_none=True) if hasattr(filters, "model_dump") else None,
        request=request,
    )

    # Field-Level Security (ADR-0011 Sprint 5): enmascarar campos sensibles
    # de cada lead antes de devolver. Admin/_all pasan derecho.
    rows = field_security_service.mask_records(current_user, "leads", rows)

    return {"total": total, "items": rows}


@router.get("/campanas")
def list_campanas(
    current_user: TokenData = Depends(get_current_user),
):
    """Lista los valores distintos de campana presentes en crm.leads,
    ordenados A→Z. Alimenta el dropdown de filtro en el frontend."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT campana FROM crm.leads "
                "WHERE campana IS NOT NULL AND campana != '' "
                "ORDER BY campana"
            )
            return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Mantenimiento: Regularización de leads de Históricos sin fuente
# ---------------------------------------------------------------------------

class CorregirFuenteHistoricosRequest(BaseModel):
    lead_ids: Optional[List[int]] = None


@router.get("/mantenimiento/historicos-sin-fuente")
def detectar_historicos_sin_fuente(
    current_user: TokenData = Depends(require_admin),
):
    """Detecta leads que fueron asignados desde Históricos pero no tienen
    asociada la fuente 'Historico', teniendo como condición que su última
    asignación provino de históricos."""
    query = """
        SELECT
            l.id,
            TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
            l.telefono,
            l.email,
            COALESCE(f.nombre, 'Sin fuente') AS fuente_actual,
            e.nombre AS estado_nombre,
            TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
            l.created_at::text AS fecha_ingreso
        FROM crm.leads l
        LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
        LEFT JOIN auth.users u ON u.id = l.asesor_id
        WHERE l.activo = TRUE
          AND (
              l.fuente_id IS NULL
              OR LOWER(f.nombre) NOT IN ('historico', 'histórico', 'historicos', 'históricos')
          )
          AND (
              EXISTS (
                  SELECT 1 FROM crm_legacy.leads_historico h
                  WHERE h.lead_crm_id = l.id
                    AND NOT EXISTS (
                        SELECT 1 FROM crm.asignaciones_log al
                        WHERE al.lead_id = l.id
                          AND al.created_at > COALESCE(h.fecha_asignacion::timestamptz, h.migrado_en, '2000-01-01'::timestamptz)
                          AND al.motivo NOT ILIKE '%%historico%%'
                          AND al.motivo NOT ILIKE '%%histórico%%'
                    )
              )
              OR (
                  (
                      SELECT al.motivo
                      FROM crm.asignaciones_log al
                      WHERE al.lead_id = l.id
                      ORDER BY al.created_at DESC, al.id DESC
                      LIMIT 1
                  ) ILIKE '%%historico%%'
                  OR
                  (
                      SELECT al.motivo
                      FROM crm.asignaciones_log al
                      WHERE al.lead_id = l.id
                      ORDER BY al.created_at DESC, al.id DESC
                      LIMIT 1
                  ) ILIKE '%%histórico%%'
              )
          )
        ORDER BY l.created_at DESC
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            rows = cur.fetchall()
            return {
                "count": len(rows),
                "leads": [dict(r) for r in rows],
            }


@router.post("/mantenimiento/corregir-fuente-historicos")
def corregir_fuente_historicos(
    body: Optional[CorregirFuenteHistoricosRequest] = None,
    current_user: TokenData = Depends(require_admin),
):
    """Actualiza la fuente a 'Historico' en los leads cuya última asignación
    fue desde históricos y aún no tienen dicha fuente asignada."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Obtener o asegurar la fuente 'Historico'
            cur.execute("SELECT id FROM crm.fuentes WHERE LOWER(nombre) IN ('historico', 'histórico', 'historicos', 'históricos') LIMIT 1")
            frow = cur.fetchone()
            if not frow:
                cur.execute(
                    "INSERT INTO crm.fuentes (nombre, activo) VALUES ('Historico', TRUE) "
                    "ON CONFLICT (nombre) DO UPDATE SET activo = TRUE RETURNING id"
                )
                frow = cur.fetchone()
            fuente_id = frow["id"] if frow else None

            if not fuente_id:
                raise HTTPException(500, "No se pudo asegurar la fuente 'Historico' en crm.fuentes.")

            # 2. Filtrar por IDs específicos si se enviaron o por todos los detectados
            if body and body.lead_ids:
                extra_where = "AND l.id = ANY(%s)"
                params = [body.lead_ids, fuente_id]
            else:
                extra_where = ""
                params = [fuente_id]

            cur.execute(
                f"""
                WITH target_leads AS (
                    SELECT l.id
                    FROM crm.leads l
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    WHERE l.activo = TRUE
                      AND (
                          l.fuente_id IS NULL
                          OR LOWER(f.nombre) NOT IN ('historico', 'histórico', 'historicos', 'históricos')
                      )
                      AND (
                          EXISTS (
                              SELECT 1 FROM crm_legacy.leads_historico h
                              WHERE h.lead_crm_id = l.id
                                AND NOT EXISTS (
                                    SELECT 1 FROM crm.asignaciones_log al
                                    WHERE al.lead_id = l.id
                                      AND al.created_at > COALESCE(h.fecha_asignacion::timestamptz, h.migrado_en, '2000-01-01'::timestamptz)
                                      AND al.motivo NOT ILIKE '%%historico%%'
                                      AND al.motivo NOT ILIKE '%%histórico%%'
                                )
                          )
                          OR (
                              (
                                  SELECT al.motivo
                                  FROM crm.asignaciones_log al
                                  WHERE al.lead_id = l.id
                                  ORDER BY al.created_at DESC, al.id DESC
                                  LIMIT 1
                              ) ILIKE '%%historico%%'
                              OR
                              (
                                  SELECT al.motivo
                                  FROM crm.asignaciones_log al
                                  WHERE al.lead_id = l.id
                                  ORDER BY al.created_at DESC, al.id DESC
                                  LIMIT 1
                              ) ILIKE '%%histórico%%'
                          )
                      )
                      {extra_where}
                )
                UPDATE crm.leads
                SET fuente_id = %s,
                    updated_at = NOW()
                WHERE id IN (SELECT id FROM target_leads)
                RETURNING id
                """,
                params,
            )
            updated_rows = cur.fetchall()
            updated_count = len(updated_rows)
            conn.commit()

            return {
                "ok": True,
                "updated_count": updated_count,
                "fuente_id": fuente_id,
                "message": f"Se actualizó la fuente a 'Historico' en {updated_count} lead(s) asignados desde Históricos.",
            }



# ---------------------------------------------------------------------------
# Exportar leads a Excel (solo admin)
# ---------------------------------------------------------------------------

@router.get("/exportar")
# Rate limit: max 60 descargas por IP por minuto. Permite trabajar cómodamente
# a administradores y supervisores sin bloqueos repentinos.
@limiter.limit("60/minute")
def exportar_leads(
    request: Request,
    filters: LeadFilters = Depends(lead_filters_query),
    limit: int = Query(5000, le=10000),
    offset: int = Query(0, ge=0),
    # V094 — Export abierto a admin + supervisor (legacy) + cualquier rol
    # custom con el permiso `reportes.export`. Esto permite habilitar el
    # export a roles como `marketing_proveedor` (Wedo) SIN romper la
    # politica original de los 13 asesores (rol legacy asesor sigue
    # rechazado salvo que el admin marque explicitamente el permiso).
    current_user: TokenData = Depends(check_permission("reportes.export", "supervisor")),
):
    """Export Excel pulido (formato profesional, listo para entregar al cliente).

    Decisiones:
      - Las fechas viajan como datetime nativo desde el repo y se escriben con
        `number_format` propio — Excel las trata como fechas reales (filtros,
        ordenamiento por tiempo, no como strings).
      - Formato de fecha `yyyy-mm-dd hh:mm` (ISO-like): ordena visualmente igual
        que cronológicamente, no es ambigüo (US vs EU), y se copia limpio a
        Python/Pandas/BI sin reparseo. Más amigable para analistas que el
        formato local `dd/mm/yyyy`.
      - Anchos de columna fijos por tipo de dato (no auto-fit ciego), porque el
        auto-fit con observaciones largas hace columnas inservibles.
      - Freeze pane + auto-filter sobre la fila 1: navegación cómoda en datasets
        de miles de filas.
      - Zebra striping ligero para legibilidad.
      - Estado/Plataforma capitalizados (la BD los guarda en minúsculas).
      - Teléfono forzado a texto para preservar el `+` y los ceros iniciales.
    """
    from datetime import datetime, date
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    rows = leads_repository.find_for_export(
        filters, current_user, limit=limit, offset=offset
    )

    # Audit log: registra la descarga ANTES de construir el workbook. Si el
    # cliente abandona la descarga o el build falla, igual sabemos que hubo
    # intento de export con estos filtros. Fail-safe.
    audit_service.record_export(
        user=current_user,
        lead_count=len(rows),
        filters=filters.model_dump(exclude_none=True),
        request=request,
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"

    # ── Definición declarativa de columnas (un solo lugar para tocar) ────────
    # `width`        : ancho fijo en caracteres Excel
    # `key`          : campo del row dict
    # `align`        : horizontal alignment (default: left)
    # `fmt`          : number_format (para fechas o números)
    # `wrap`         : wrap_text (para textos largos)
    # `transform`    : función opcional para limpiar el valor
    def _title(v):
        return v.title() if isinstance(v, str) and v else v

    COLUMNS = [
        {"header": "Nombre",          "key": "nombre_completo",       "width": 28},
        {"header": "Teléfono",        "key": "telefono",              "width": 16, "align": "left"},
        {"header": "DNI",             "key": "dni",                   "width": 12, "align": "center"},
        {"header": "Email",           "key": "email",                 "width": 28},
        {"header": "Estado",          "key": "estado_nombre",         "width": 14, "transform": _title},
        # V094 — Distinción "Nuevo" vs "Recontacto" para análisis de campañas
        # del proveedor. Ubicada después del Estado para que el filtro pivot
        # quede visualmente junto al estado funcional del lead.
        {"header": "Tipo",            "key": "tipo_lead",             "width": 12, "align": "center"},
        {"header": "Origen",          "key": "origen",                "width": 14, "align": "center"},
        {"header": "Fuente",          "key": "fuente_nombre",         "width": 14, "transform": _title},
        {"header": "Campaña",         "key": "campana",               "width": 28},
        {"header": "Campaña ID",      "key": "campana_id",            "width": 20, "align": "left"},
        {"header": "Formulario",      "key": "form_nombre",           "width": 24},
        {"header": "Formulario ID",   "key": "form_id",               "width": 20, "align": "left"},
        {"header": "Intentos",        "key": "intentos_contacto",     "width": 10, "align": "center", "fmt": "0"},
        # V094 — Total de recontactos y fecha del último.
        {"header": "Recontactos",     "key": "total_recontactos",     "width": 12, "align": "center", "fmt": "0"},
        {"header": "Último recontacto","key": "ultimo_recontacto_at", "width": 17, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        # V096.6 — Atribucion del ULTIMO recontacto. Las columnas Campaña /
        # Formulario / Fuente de arriba reflejan la atribucion ORIGINAL del
        # lead; estas 4 muestran desde donde vino el ultimo touch del
        # cliente. Util para reportes "cliente original de TikTok reactivado
        # via WhatsApp/Camp Premium". Vacias si el lead nunca fue recontactado.
        {"header": "Últ. recontacto - Fuente",     "key": "ult_recontacto_fuente",  "width": 18, "transform": _title},
        {"header": "Últ. recontacto - Campaña",    "key": "ult_recontacto_campana", "width": 28},
        {"header": "Últ. recontacto - Formulario", "key": "ult_recontacto_form",    "width": 24},
        {"header": "Últ. recontacto - Anuncio",    "key": "ult_recontacto_anuncio", "width": 24},
        {"header": "Supervisor",      "key": "supervisor_nombre",     "width": 22},
        {"header": "Asesor",          "key": "asesor_nombre",         "width": 20},
        {"header": "Fecha ingreso",   "key": "fecha_ingreso",         "width": 17, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Fecha asignación","key": "fecha_asignacion",      "width": 17, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "1er contacto",    "key": "fecha_primer_contacto", "width": 17, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Último contacto", "key": "fecha_ultimo_contacto", "width": 17, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Última actividad","key": "ultima_actividad",      "width": 17, "fmt": "yyyy-mm-dd hh:mm", "align": "center"},
        {"header": "Tipo contacto",   "key": "ultimo_tipo_contacto",  "width": 14, "transform": _title, "align": "center"},
        {"header": "Resultado",       "key": "ultimo_resultado",      "width": 16, "transform": _title},
        {"header": "Ciudad",          "key": "ciudad",                "width": 16, "transform": _title},
        {"header": "Trabajo",         "key": "trabajo",               "width": 18},
        {"header": "Referido por",    "key": "referido_por",          "width": 22},
        {"header": "Código Convenio", "key": "codigo_convenio",       "width": 18},
        {"header": "Observaciones",   "key": "observaciones",         "width": 50, "wrap": True},
    ]

    # ── Estilos reutilizables ────────────────────────────────────────────────
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(border_style="thin", color="D1D5DB")
    cell_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    zebra_fill = PatternFill("solid", fgColor="F8FAFC")

    # ── Encabezado ───────────────────────────────────────────────────────────
    for c_idx, col in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=c_idx, value=col["header"])
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = cell_border
        ws.column_dimensions[get_column_letter(c_idx)].width = col["width"]

    ws.row_dimensions[1].height = 28

    # ── Filas de datos ───────────────────────────────────────────────────────
    for r_idx, row in enumerate(rows, 2):
        is_zebra = (r_idx % 2 == 0)
        for c_idx, col in enumerate(COLUMNS, 1):
            value = row.get(col["key"])

            # Limpieza opcional (capitalización, etc.)
            if value is not None and "transform" in col:
                value = col["transform"](value)

            # Teléfono y DNI: forzar a texto para preservar el "+" y los
            # ceros iniciales (Excel auto-coerce a número y los come).
            if col["key"] in ("telefono", "dni") and value is not None:
                value = str(value)

            # openpyxl no acepta datetimes timezone-aware. El SQL ya los
            # convierte a hora Lima naive, pero por si acaso despojamos
            # cualquier tzinfo residual.
            if isinstance(value, datetime) and value.tzinfo is not None:
                value = value.replace(tzinfo=None)

            cell = ws.cell(row=r_idx, column=c_idx, value=value)

            # Formato de fecha / número
            if "fmt" in col:
                cell.number_format = col["fmt"]

            # Alineación
            cell.alignment = Alignment(
                horizontal=col.get("align", "left"),
                vertical="center",
                wrap_text=col.get("wrap", False),
            )

            cell.border = cell_border
            if is_zebra:
                cell.fill = zebra_fill

    # ── Freeze pane + autofiltro + altura mínima ─────────────────────────────
    ws.freeze_panes = "A2"
    last_col_letter = get_column_letter(len(COLUMNS))
    ws.auto_filter.ref = f"A1:{last_col_letter}{max(len(rows) + 1, 2)}"

    # Page setup: orientación horizontal y ajuste a una página de ancho al
    # imprimir — útil si el cliente quiere PDF.
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_options.horizontalCentered = True
    ws.print_title_rows = "1:1"

    # ── Streaming response ───────────────────────────────────────────────────
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    # V070.68 (Bundle B): nombre del archivo derivado del slug del tenant.
    # Antes era "leads_palma_rio_*.xlsx" hardcoded — Doctor Muelita habria
    # descargado archivos diciendo "Palma Rio". Slug se calcula de company_name
    # (ej: 'Doctor Muelita' -> 'doctor_muelita').
    from app.services.brand_service import get_filename_slug
    today = date.today().strftime("%Y-%m-%d")
    filename = f"leads_{get_filename_slug()}_{today}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Detalle de un lead
# ---------------------------------------------------------------------------

@router.get("/{lead_id}")
def get_lead(
    lead_id: int,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
):
    role_clause, params = role_filter(current_user)
    params.append(lead_id)

    # V041.3: vw_leads_dashboard pre-V041 NO expone l.dni ni l.tipo_documento
    # (la view solo proyecta nombres/telefono/email/etc). Antes el endpoint
    # devolvia dni=NULL al frontend aunque la columna en crm.leads tuviera
    # valor — UI mostraba "—" en CE/Pasaporte y rompia la edicion. Ahora
    # SELECT explicito sobre l.* garantiza que el dato viaja al cliente
    # independientemente de si la migracion V041 (que recrea la view) corrio.
    tipo_doc_select = "l.tipo_documento" if _has_tipo_documento_column() else "NULL AS tipo_documento"
    ga_select = "COALESCE(l.gestion_especial_admin, FALSE) AS gestion_especial_admin, l.gestion_admin_at::text AS gestion_admin_at, l.gestion_admin_user_id::text AS gestion_admin_user_id" if _has_gestion_especial_admin_column() else "FALSE AS gestion_especial_admin, NULL AS gestion_admin_at, NULL AS gestion_admin_user_id"
    ft_select = "l.ficha_tecnica AS ficha_tecnica, COALESCE(l.ficha_tecnica_completada, FALSE) AS ficha_tecnica_completada" if _has_ficha_tecnica_column() else "'{}'::jsonb AS ficha_tecnica, FALSE AS ficha_tecnica_completada"
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    v.*,
                    l.dni AS dni,
                    l.anuncio AS anuncio,
                    l.conjunto AS conjunto,
                    l.resumen_ia AS resumen_ia,
                    l.datos_extra AS datos_extra,
                    l.api_client_id::text AS api_client_id,
                    ac.nombre AS proveedor_nombre,
                    l.api_client_legacy_slug   AS api_client_legacy_slug,
                    l.api_client_legacy_nombre AS api_client_legacy_nombre,
                    -- V091 — tracking de herencia (badge "Heredado de X · hace N días").
                    l.previous_asesor_id::text AS previous_asesor_id,
                    l.reassigned_at::text      AS reassigned_at,
                    (
                        SELECT TRIM(COALESCE(pa.first_name,'') || ' ' || COALESCE(pa.last_name,''))
                        FROM auth.users pa
                        WHERE pa.id = l.previous_asesor_id
                    ) AS previous_asesor_nombre,
                    -- V069.3: resolver nombre legible de campaña (campaign_id)
                    -- y formulario (form_id) desde meta_catalog_cache. Antes el
                    -- detalle del lead solo devolvia el ID raw (ej. "1858117249047009")
                    -- mientras que la lista (leads_repository) ya hacia el JOIN —
                    -- inconsistencia visible para el usuario.
                    mc_c.name AS campana_nombre,
                    mc_f.name AS form_nombre,
                    -- V069.4: form_id del lead (ej. "7610832729906807056"). Necesario
                    -- para mostrar el ID raw bajo el nombre resuelto en el detalle
                    -- (paridad con la columna Formulario de la lista de Leads).
                    l.fuente_form_id AS fuente_form_id,
                    -- V065: sede de destino del lead
                    l.sede_id::text            AS sede_id,
                    sed.codigo                 AS sede_codigo,
                    sed.nombre                 AS sede_nombre,
                    sed.color_hex              AS sede_color,
                    l.merged_into              AS merged_into,
                    {tipo_doc_select},
                    {ga_select},
                    {ft_select},
                    v.asesor_id::text AS asesor_id,
                    v.supervisor_id::text AS supervisor_id,
                    (
                        CASE
                            WHEN l.supervisor_id IS NOT NULL
                                 AND (
                                     l.estado_id IN (SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%matr%%' OR nombre ILIKE '%%ganad%%' OR nombre ILIKE '%%cierr%%')
                                     OR l.tipo_cierre IS NOT NULL
                                 )
                                 AND NOT EXISTS (
                                     SELECT 1 FROM crm.equipos eq
                                     WHERE eq.asesor_id = v.asesor_id
                                       AND eq.supervisor_id = l.supervisor_id
                                       AND eq.activo = TRUE
                                 )
                            THEN TRUE
                            ELSE FALSE
                        END
                    ) AS is_respaldo_supervision,
                    v.fecha_ingreso::text,
                    v.updated_at::text,
                    v.fecha_proxima_accion::text,
                    (
                        SELECT c.fecha_cita::text
                        FROM crm.contactos c
                        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
                        ORDER BY c.created_at DESC, c.id DESC
                        LIMIT 1
                    ) AS fecha_cita,
                    (
                        SELECT c.tipo_cita
                        FROM crm.contactos c
                        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
                        ORDER BY c.created_at DESC, c.id DESC
                        LIMIT 1
                    ) AS tipo_cita,
                    (
                        SELECT c.cita_estado_id
                        FROM crm.contactos c
                        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
                        ORDER BY c.created_at DESC, c.id DESC
                        LIMIT 1
                    ) AS cita_estado_id,
                    (
                        SELECT ce.codigo
                        FROM crm.contactos c
                        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
                        ORDER BY c.created_at DESC, c.id DESC
                        LIMIT 1
                    ) AS cita_estado_codigo,
                    (
                        SELECT ce.nombre
                        FROM crm.contactos c
                        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
                        ORDER BY c.created_at DESC, c.id DESC
                        LIMIT 1
                    ) AS cita_estado_nombre,
                    (
                        SELECT ce.color_hex
                        FROM crm.contactos c
                        LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                        WHERE c.lead_id = v.id AND c.fecha_cita IS NOT NULL
                        ORDER BY c.created_at DESC, c.id DESC
                        LIMIT 1
                    ) AS cita_estado_color,
                    (
                        SELECT MIN(ts) FROM (
                            SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            UNION ALL
                            SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = v.id
                        ) _all
                    )::text AS fecha_primer_contacto,
                    (
                        SELECT MAX(ts) FROM (
                            SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            UNION ALL
                            SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = v.id
                        ) _all
                    )::text AS fecha_ultimo_contacto,
                    (
                        SELECT MAX(ts) FROM (
                            SELECT created_at AS ts FROM crm.contactos WHERE lead_id = v.id
                            UNION ALL
                            SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = v.id
                            UNION ALL
                            SELECT created_at FROM crm.asignaciones_log WHERE lead_id = v.id
                            UNION ALL
                            SELECT created_at FROM crm.lead_recontactos WHERE lead_id = v.id
                            UNION ALL
                            SELECT COALESCE(l.updated_at, l.created_at) AS ts
                        ) _all_act
                    )::text AS ultima_actividad
                FROM crm.vw_leads_dashboard v
                JOIN crm.leads l ON l.id = v.id
                LEFT JOIN crm.api_clients ac ON ac.id = l.api_client_id
                LEFT JOIN crm.sedes sed ON sed.id = l.sede_id
                -- V069.3: catalogo Meta/TikTok (campaign + form). fetch_status='ok'
                -- evita devolver nombres cacheados con error.
                LEFT JOIN crm.meta_catalog_cache mc_c
                       ON mc_c.entity_type = 'campaign'
                      AND mc_c.entity_id   = v.campana
                      AND mc_c.fetch_status = 'ok'
                LEFT JOIN crm.meta_catalog_cache mc_f
                       ON mc_f.entity_type = 'form'
                      AND mc_f.entity_id   = l.fuente_form_id
                      AND mc_f.fetch_status = 'ok'
                WHERE ({role_clause}) AND v.id = %s
                """,
                params,
            )
            lead = cur.fetchone()

    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    lead = dict(lead)

    # referido_por & codigo_convenio: columnas opcionales
    try:
        with get_db() as conn2:
            with conn2.cursor(cursor_factory=RealDictCursor) as cur2:
                cur2.execute("SELECT referido_por, codigo_convenio FROM crm.leads WHERE id = %s", (lead_id,))
                row = cur2.fetchone()
                lead["referido_por"] = row["referido_por"] if row else None
                lead["codigo_convenio"] = row["codigo_convenio"] if row else None
    except Exception:
        lead["referido_por"] = None
        lead["codigo_convenio"] = None

    # V127: Historial de fusiones (si este lead absorbió a otros o fue fusionado)
    try:
        with get_db() as conn_m:
            with conn_m.cursor(cursor_factory=RealDictCursor) as cur_m:
                from app.services import lead_merge_service
                merges = lead_merge_service.get_lead_merges(cur_m, lead_id)
                lead["merges"] = merges
                lead["is_merged"] = len(merges) > 0
    except Exception:
        lead["merges"] = []
        lead["is_merged"] = False

    # Audit log: vista de ficha individual. Fail-safe.
    audit_service.record_detail(
        user=current_user,
        lead_id=lead_id,
        request=request,
    )

    # Field-Level Security (ADR-0011 Sprint 5): enmascarar campos sensibles
    # antes de devolver al cliente, segun el rol del usuario.
    lead = field_security_service.mask_record(current_user, "leads", lead)

    return lead


# ---------------------------------------------------------------------------
# Crear lead
# ---------------------------------------------------------------------------

class LeadCreate(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    dni: Optional[str] = None
    tipo_documento: Optional[str] = None  # V041: 'DNI' | 'CE' | 'Pasaporte'
    ciudad: Optional[str] = None
    trabajo: Optional[str] = None
    fuente_id: Optional[int] = None
    estado_id: Optional[int] = None
    asesor_id: Optional[str] = None
    supervisor_id: Optional[str] = None  # V035: admin puede forzar cola de un supervisor
    campana: Optional[str] = None
    fuente_externa_id: Optional[str] = None
    observaciones: Optional[str] = None
    es_recontacto: bool = False
    referido_por: Optional[str] = None
    codigo_convenio: Optional[str] = None
    # V027: campos de carga masiva (gerencia)
    proyecto: Optional[str] = None
    estrategia: Optional[str] = None
    calidad: Optional[str] = None  # FRIO | TIBIO | CALIENTE | None
    sede_id: Optional[str] = None  # V065: sede de destino del lead
    # V102 / V111: campos específicos por estado
    fecha_proxima_gestion: Optional[str] = None
    accion_proxima_gestion: Optional[str] = None
    motivo_perdida: Optional[str] = None
    motivo_perdida_otro: Optional[str] = None
    tipo_cierre: Optional[str] = None
    segunda_voz: Optional[str] = None

    @field_validator("calidad", mode="before")
    @classmethod
    def _normalize_calidad(cls, v):
        if v is None or v == "":
            return None
        s = str(v).strip().upper()
        # V028: catálogo configurable — validamos contra DB. Si la tabla no
        # responde (caso extremo), aceptamos el valor ya normalizado para no
        # bloquear el API. La UI solo ofrece opciones válidas.
        codigos = _load_calidad_codigos()
        if codigos and s not in codigos:
            opciones = ", ".join(sorted(codigos)) or "FRIO, TIBIO, CALIENTE"
            raise ValueError(f"calidad debe ser uno de: {opciones}")
        return s


def _validate_lead_payload(data, fuente_nombre: Optional[str]):
    """Validaciones de negocio comunes a create/update.
    Lanza HTTPException 422 con `detail` que el frontend muestra en el banner.
    """
    if hasattr(data, "fuente_id") and data.fuente_id is None and isinstance(data, LeadCreate):
        raise HTTPException(status_code=422, detail="Es obligatorio seleccionar una fuente para el lead.")
    if data.email and not EMAIL_RE.match(data.email.strip()):
        raise HTTPException(status_code=422, detail="Formato de email inválido (ej: nombre@dominio.com).")
    if data.dni and not DNI_RE.match(data.dni.strip()):
        raise HTTPException(status_code=422, detail="El DNI debe tener exactamente 8 dígitos.")
    # Si la fuente es "referido", referido_por es obligatorio
    if fuente_nombre and "referid" in fuente_nombre.lower():
        if not (data.referido_por and data.referido_por.strip()):
            raise HTTPException(status_code=422, detail="Es obligatorio indicar quién refirió al lead.")
    # Si la fuente es "convenio" o "convenios", codigo_convenio es obligatorio
    if fuente_nombre and "convenio" in fuente_nombre.lower():
        if not (hasattr(data, "codigo_convenio") and data.codigo_convenio and data.codigo_convenio.strip()):
            raise HTTPException(status_code=422, detail="Es obligatorio indicar el código de convenio.")


@router.get("/check-duplicate")
def check_duplicate(
    telefono: Optional[str] = None,
    email: Optional[str] = None,
    dni: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
):
    """V067: chequea si ya existe un lead con estos datos.

    Devuelve `{ match: lead | null, match_field: "telefono"|"email"|"dni"|null }`.
    El frontend lo invoca onBlur del campo telefono/email/dni para mostrar
    warning ANTES de submit (patron estandar).

    Acepta los 3 campos opcionalmente — basta con uno para chequear.
    Search order: telefono > email > dni (telefono es el match mas fuerte).
    El match ignora leads merged_into.
    """
    if not (telefono or email or dni):
        return {"match": None, "match_field": None}

    role_clause, role_params = role_filter(current_user)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Telefono — match por ULTIMOS 9 DIGITOS (longitud celular Peru).
            # Antes era match EXACTO (l.telefono = %s) — fallaba con cualquier
            # diferencia de formato. Caso real (Oscar Apestegui +51924223814):
            # el frontend probaba 4 formatos pero el lead en DB estaba con
            # un 5to formato distinto → ningun match → InfoTab vacio.
            #
            # Mismo patron RIGHT(_, 9) que usan llamadas.py y el phone_match
            # de whatsapp.py — consistencia en toda la app.
            if telefono:
                tel = telefono.strip()
                cur.execute(
                    f"""
                    SELECT
                        l.id, l.nombres, l.apellidos, l.telefono, l.email,
                        l.asesor_id::text AS asesor_id,
                        (SELECT TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                         FROM auth.users u WHERE u.id = l.asesor_id) AS asesor_nombre,
                        e.nombre AS estado_nombre,
                        l.created_at::text AS created_at
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE RIGHT(REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g'), 9)
                        = RIGHT(REGEXP_REPLACE(%s, '\\D', '', 'g'), 9)
                      AND LENGTH(REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g')) >= 9
                      AND LENGTH(REGEXP_REPLACE(%s, '\\D', '', 'g')) >= 9
                      AND l.activo = TRUE
                      AND l.merged_into IS NULL
                      AND ({role_clause})
                    ORDER BY (l.asesor_id IS NOT NULL) DESC, l.created_at DESC
                    LIMIT 1
                    """,
                    [tel, tel] + role_params,
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "telefono"}

            # Email — match case-insensitive
            if email:
                em = email.strip().lower()
                cur.execute(
                    f"""
                    SELECT
                        l.id, l.nombres, l.apellidos, l.telefono, l.email,
                        l.asesor_id::text AS asesor_id,
                        (SELECT TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                         FROM auth.users u WHERE u.id = l.asesor_id) AS asesor_nombre,
                        e.nombre AS estado_nombre,
                        l.created_at::text AS created_at
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE LOWER(l.email) = %s
                      AND l.activo = TRUE
                      AND l.merged_into IS NULL
                      AND ({role_clause})
                    LIMIT 1
                    """,
                    [em] + role_params,
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "email"}

            # DNI — match exacto sin formato
            if dni:
                d = dni.strip()
                cur.execute(
                    f"""
                    SELECT
                        l.id, l.nombres, l.apellidos, l.telefono, l.email,
                        l.asesor_id::text AS asesor_id,
                        (SELECT TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                         FROM auth.users u WHERE u.id = l.asesor_id) AS asesor_nombre,
                        e.nombre AS estado_nombre,
                        l.created_at::text AS created_at
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.dni = %s
                      AND l.activo = TRUE
                      AND l.merged_into IS NULL
                      AND ({role_clause})
                    LIMIT 1
                    """,
                    [d] + role_params,
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "dni"}

    return {"match": None, "match_field": None}


@router.post("", status_code=201)
def create_lead(
    data: LeadCreate,
    allow_duplicate: bool = False,
    duplicate_reason: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
):
    if getattr(current_user, "role_id", None) is not None and not has_permission(current_user, "leads.create"):
        raise HTTPException(status_code=403, detail="No tienes permiso para crear leads.")

    # V067: dedupe — antes de insertar, chequear si ya existe lead con el
    # mismo telefono (match mas fuerte). Si match y NO viene allow_duplicate,
    # devolver 409 con info del existente para que el frontend muestre el
    # modal "¿usar este o crear de todos modos?". Patron patrón estándar.
    if data.telefono and not allow_duplicate:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        l.id, l.nombres, l.apellidos, l.telefono, l.email,
                        l.asesor_id::text AS asesor_id,
                        (SELECT TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,''))
                         FROM auth.users u WHERE u.id = l.asesor_id) AS asesor_nombre,
                        e.nombre AS estado_nombre
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.telefono = %s AND l.activo = TRUE AND l.merged_into IS NULL
                    LIMIT 1
                    """,
                    (data.telefono.strip(),),
                )
                existing = cur.fetchone()
                if existing:
                    # 409 Conflict con info estructurada — el frontend lee
                    # err.response.data.detail.existing_lead para mostrar
                    # el banner.
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code":          "duplicate_telefono",
                            "message":       "Ya existe un lead con este teléfono.",
                            "existing_lead": dict(existing),
                            "can_override":  True,
                            "hint":          "Para crear de todos modos, agregar ?allow_duplicate=true",
                        },
                    )

    # V035: resolver rol del UUID asignado para decidir si va a cola o directo.
    #   - admin/supervisor sin asesor_id explícito → queda en su cola
    #     (asesor_id=NULL, supervisor_id=self, fecha_entrada_cola=NOW()).
    #   - asesor sin asesor_id → auto-asignado a sí mismo.
    #   - asesor_id explícito apuntando a un asesor real → directo.
    #   - asesor_id explícito apuntando a un supervisor → supervisor_id + cola.
    payload_asesor_id = data.asesor_id

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Estado por defecto: Nuevo
            if not data.estado_id:
                cur.execute("SELECT id FROM crm.estados_lead WHERE nombre = 'Nuevo' LIMIT 1")
                row = cur.fetchone()
                estado_id = row["id"] if row else None
            else:
                estado_id = data.estado_id

            # Buscar nombre de fuente (obligatoria)
            if not data.fuente_id:
                raise HTTPException(status_code=422, detail="Es obligatorio seleccionar una fuente para el lead.")
            cur.execute("SELECT nombre FROM crm.fuentes WHERE id = %s", (data.fuente_id,))
            row = cur.fetchone()
            fuente_nombre = row["nombre"] if row else None
            if not fuente_nombre:
                raise HTTPException(status_code=422, detail="La fuente seleccionada no es válida o está inactiva.")

            _validate_lead_payload(data, fuente_nombre)

            # Validar campos específicos por estado
            cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (estado_id,))
            est_row = cur.fetchone()
            if est_row:
                est_norm = (est_row["nombre"] or "").lower()
                for _s, _d in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
                    est_norm = est_norm.replace(_s, _d)
                if any(w in est_norm for w in ["matr", "ganad", "cierr", "venta concretad"]):
                    if not data.tipo_cierre or not data.tipo_cierre.strip():
                        raise HTTPException(
                            status_code=400,
                            detail="Debe ingresar el tipo de cierre de forma obligatoria para este estado.",
                        )
                    if data.tipo_cierre.strip() == "Con segunda voz" and (not data.segunda_voz or not data.segunda_voz.strip()):
                        raise HTTPException(
                            status_code=400,
                            detail="Debe indicar la persona que realizó la segunda voz.",
                        )
                elif any(w in est_norm for w in ["perdid", "no interesad", "desist", "descart"]):
                    if not data.motivo_perdida or not data.motivo_perdida.strip():
                        raise HTTPException(
                            status_code=400,
                            detail="Debe seleccionar el motivo de pérdida.",
                        )
                    if data.motivo_perdida.strip() == "Otro" and (not data.motivo_perdida_otro or not data.motivo_perdida_otro.strip()):
                        raise HTTPException(
                            status_code=400,
                            detail="Debe especificar el motivo de pérdida.",
                        )
                elif any(w in est_norm for w in ["seguimiento", "negociacion", "visita"]):
                    if not data.fecha_proxima_gestion or not data.fecha_proxima_gestion.strip():
                        from datetime import datetime, timedelta, timezone
                        data.fecha_proxima_gestion = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

            # Resolver target (supervisor_id, asesor_id, fecha_entrada_cola, bump_rotation)
            target_supervisor, target_asesor, fecha_cola, bump_rotation = _resolve_lead_owner(
                cur, payload_asesor_id, data.supervisor_id, current_user
            )

            # V041: tipo_documento — el frontend envia 'DNI' | 'CE' | 'Pasaporte'.
            # Si viene None/vacio o un valor invalido, dejamos que el DEFAULT
            # 'DNI' del schema actue (CHECK constraint rechaza valores raros).
            # Si la migracion V041 todavia no corrio, omitimos la columna del
            # INSERT para no romper el endpoint (defensa en profundidad).
            tipo_doc = data.tipo_documento if data.tipo_documento in ('DNI', 'CE', 'Pasaporte') else 'DNI'
            include_tipo_doc = _has_tipo_documento_column()

            # V065: sede_id es opcional — el INSERT lo recibe via CASE
            # para manejar el NULL (Postgres no acepta NULL::uuid implicito).
            # V067: si se llego aca con allow_duplicate=true, registramos
            # el override + razon para audit.
            override_flag = bool(allow_duplicate)
            override_reason = (duplicate_reason or "").strip()[:255] or None

            fpg_val = data.fecha_proxima_gestion.strip() if (data.fecha_proxima_gestion and data.fecha_proxima_gestion.strip()) else None
            mp_val = data.motivo_perdida.strip() if (data.motivo_perdida and data.motivo_perdida.strip()) else None
            mpo_val = data.motivo_perdida_otro.strip() if (data.motivo_perdida_otro and data.motivo_perdida_otro.strip()) else None
            tc_val = data.tipo_cierre.strip() if (data.tipo_cierre and data.tipo_cierre.strip()) else None
            sv_val = data.segunda_voz.strip() if (data.segunda_voz and data.segunda_voz.strip()) else None

            if include_tipo_doc:
                cur.execute(
                    """
                    INSERT INTO crm.leads
                        (fuente_id, estado_id, supervisor_id, asesor_id,
                         fecha_entrada_cola, nombres, apellidos,
                         telefono, email, dni, tipo_documento, ciudad, trabajo, es_recontacto,
                         campana, fuente_externa_id, observaciones, referido_por, codigo_convenio,
                         proyecto, estrategia, calidad, sede_id,
                         fecha_proxima_gestion, motivo_perdida, motivo_perdida_otro,
                         tipo_cierre, segunda_voz,
                         created_with_duplicate_override, duplicate_override_reason,
                         activo)
                    VALUES (%s, %s,
                            CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                            CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                            %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                            %s::timestamptz, %s, %s,
                            %s, %s,
                            %s, %s,
                            TRUE)
                    RETURNING id
                    """,
                    (
                        data.fuente_id, estado_id,
                        target_supervisor, target_supervisor,
                        target_asesor, target_asesor,
                        fecha_cola,
                        data.nombres, data.apellidos, data.telefono,
                        data.email, data.dni, tipo_doc, data.ciudad, data.trabajo,
                        data.es_recontacto, data.campana,
                        data.fuente_externa_id, data.observaciones,
                        data.referido_por, data.codigo_convenio,
                        data.proyecto, data.estrategia, data.calidad,
                        data.sede_id, data.sede_id,
                        fpg_val, mp_val, mpo_val,
                        tc_val, sv_val,
                        override_flag, override_reason,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO crm.leads
                        (fuente_id, estado_id, supervisor_id, asesor_id,
                         fecha_entrada_cola, nombres, apellidos,
                         telefono, email, dni, ciudad, trabajo, es_recontacto,
                         campana, fuente_externa_id, observaciones, referido_por, codigo_convenio,
                         proyecto, estrategia, calidad, sede_id,
                         fecha_proxima_gestion, motivo_perdida, motivo_perdida_otro,
                         tipo_cierre, segunda_voz,
                         created_with_duplicate_override, duplicate_override_reason,
                         activo)
                    VALUES (%s, %s,
                            CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                            CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                            %s,
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                            %s::timestamptz, %s, %s,
                            %s, %s,
                            %s, %s,
                            TRUE)
                    RETURNING id
                    """,
                    (
                        data.fuente_id, estado_id,
                        target_supervisor, target_supervisor,
                        target_asesor, target_asesor,
                        fecha_cola,
                        data.nombres, data.apellidos, data.telefono,
                        data.email, data.dni, data.ciudad, data.trabajo,
                        data.es_recontacto, data.campana,
                        data.fuente_externa_id, data.observaciones,
                        data.referido_por, data.codigo_convenio,
                        data.proyecto, data.estrategia, data.calidad,
                        data.sede_id, data.sede_id,
                        fpg_val, mp_val, mpo_val,
                        tc_val, sv_val,
                        override_flag, override_reason,
                    ),
                )
            new_id = cur.fetchone()["id"]

            # Issue #43 — si el supervisor se eligio via _next_supervisor (admin
            # sin hints), actualizar el contador diario para que el proximo
            # lead rote al siguiente supervisor. Sin este bump, todos los leads
            # admin van siempre al mismo supervisor (regresion del fix #42).
            if bump_rotation and target_supervisor:
                from app.services.integrations.ingest_core import _bump_rotacion
                _bump_rotacion(cur, target_supervisor, new_id)
        # V070.64 — sin conn.commit() explicito: get_db() ya hace commit
        # automatico al salir del with. El doble commit era no-op pero
        # creaba ambiguedad si ocurria excepcion entre los dos.

    # Push notification al dueño operativo del lead.
    # V070.51 — performed_by para skip self-action (creador no recibe push
    # de un lead que el mismo cargo).
    # V070.85 — Si el lead queda en cola del supervisor (sin asesor real),
    # tambien notificamos al supervisor para que se entere y lo asigne o
    # atienda. Antes solo se notificaba si habia asesor → supervisores no
    # se enteraban hasta entrar manualmente al CRM.
    recipient = target_asesor or target_supervisor
    if recipient:
        from app.services.notification_service import notify_new_lead
        lead_name = f"{data.nombres or ''} {data.apellidos or ''}".strip() or "Nuevo lead"
        # V070.91 — lead_id para deep-link en mobile al tap.
        notify_new_lead(
            recipient, lead_name,
            performed_by=current_user.user_id,
            lead_id=new_id,
        )

    return {"id": new_id, "message": "Lead creado"}


def _resolve_lead_owner(cur, payload_asesor_id, payload_supervisor_id, current_user):
    """Devuelve (supervisor_id, asesor_id, fecha_entrada_cola, bump_rotation).

    V035: separa dueño funcional (supervisor) de dueño operativo (asesor).
    Un lead en cola tiene supervisor_id poblado y asesor_id NULL.

    Prioridad:
      1. asesor_id explícito (apunta a asesor o supervisor — se deduce su rol).
      2. supervisor_id explícito (admin eligiendo cola destino).
      3. inferencia por rol del creador.

    `bump_rotation` es True solo cuando se eligió un supervisor via el motor
    de round-robin (`_next_supervisor`). El caller debe llamar
    `_bump_rotacion(cur, supervisor_id, lead_id)` después del INSERT para
    que el contador diario suba y el próximo lead rote al otro supervisor.
    En todos los demás casos (asesor/supervisor explícito, asesor crea, etc)
    es False — no se altera el contador de rotación.
    """
    if payload_asesor_id:
        cur.execute(
            "SELECT role FROM auth.users WHERE id = %s::uuid",
            (payload_asesor_id,),
        )
        row = cur.fetchone()
        role = row["role"] if row else None
        if role == "supervisor":
            return payload_asesor_id, None, datetime.now(timezone.utc), False
        # asesor real → busco su supervisor en equipos
        cur.execute(
            "SELECT supervisor_id FROM crm.equipos "
            "WHERE asesor_id = %s::uuid AND activo = TRUE LIMIT 1",
            (payload_asesor_id,),
        )
        row = cur.fetchone()
        sup = row["supervisor_id"] if row else None
        return sup, payload_asesor_id, None, False

    if payload_supervisor_id and current_user.role in (Role.ADMIN, Role.SUPERVISOR):
        return payload_supervisor_id, None, datetime.now(timezone.utc), False

    # Sin hints: inferir según rol del creador
    if current_user.role == Role.ASESOR:
        cur.execute(
            "SELECT supervisor_id FROM crm.equipos "
            "WHERE asesor_id = %s::uuid AND activo = TRUE LIMIT 1",
            (current_user.user_id,),
        )
        row = cur.fetchone()
        sup = row["supervisor_id"] if row else None
        return sup, current_user.user_id, None, False
    if current_user.role == Role.SUPERVISOR:
        return current_user.user_id, None, datetime.now(timezone.utc), False
    # admin sin hints: usa el MISMO round-robin que las integraciones
    # (Meta, TikTok, WhatsApp directo, ingest multi-tenant). Garantiza:
    #   - Rotacion real entre supervisores (no siempre el mismo).
    #   - Circuit breaker V070.78: skipea equipos bloqueados (>=80% pausa).
    #   - Tie-breaker deterministico ante empates de contador.
    # Issue #43 — la version anterior usaba ORDER BY created_at ASC LIMIT 1
    # y todos los leads admin caian siempre en el supervisor mas antiguo.
    # Edge: si no hay ningun supervisor activo, preservamos limbo (None).
    from app.services.integrations.ingest_core import _next_supervisor
    sup_id = _next_supervisor(cur)
    if sup_id:
        return sup_id, None, datetime.now(timezone.utc), True
    return None, None, None, False


# ---------------------------------------------------------------------------
# Actualizar lead
# ---------------------------------------------------------------------------

class LeadUpdate(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    ciudad: Optional[str] = None
    trabajo: Optional[str] = None
    observaciones: Optional[str] = None
    estado_id: Optional[int] = None
    fuente_id: Optional[int] = None
    campana: Optional[str] = None
    es_recontacto: Optional[bool] = None
    referido_por: Optional[str] = None
    codigo_convenio: Optional[str] = None
    asesor_id: Optional[str] = None
    dni: Optional[str] = None
    tipo_documento: Optional[str] = None  # V041: 'DNI' | 'CE' | 'Pasaporte'
    # V027: campos de carga masiva (gerencia)
    proyecto: Optional[str] = None
    estrategia: Optional[str] = None
    calidad: Optional[str] = None  # FRIO | TIBIO | CALIENTE | None
    sede_id: Optional[str] = None  # V065: sede de destino del lead
    # V102 / V111: campos específicos por estado
    fecha_proxima_gestion: Optional[str] = None
    accion_proxima_gestion: Optional[str] = None
    motivo_perdida: Optional[str] = None
    motivo_perdida_otro: Optional[str] = None
    tipo_cierre: Optional[str] = None
    segunda_voz: Optional[str] = None
    # V119: gestión especial por administración
    gestion_especial_admin: Optional[bool] = None
    # V124: Ficha técnica / Cuestionario de descubrimiento comercial
    ficha_tecnica: Optional[dict] = None

    @field_validator("calidad", mode="before")
    @classmethod
    def _normalize_calidad(cls, v):
        if v is None or v == "":
            return None
        s = str(v).strip().upper()
        # V028: catálogo configurable — validamos contra DB. Si la tabla no
        # responde (caso extremo), aceptamos el valor ya normalizado para no
        # bloquear el API. La UI solo ofrece opciones válidas.
        codigos = _load_calidad_codigos()
        if codigos and s not in codigos:
            opciones = ", ".join(sorted(codigos)) or "FRIO, TIBIO, CALIENTE"
            raise ValueError(f"calidad debe ser uno de: {opciones}")
        return s


@router.patch("/{lead_id}")
def update_lead(lead_id: int, data: LeadUpdate, current_user: TokenData = Depends(get_current_user)):
    if getattr(current_user, "role_id", None) is not None and not has_permission(current_user, "leads.edit"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar leads.")

    # Distinguimos "no enviado" de "enviado como null" para que `asesor_id`
    # pueda explícitamente liberarse (None) sin que se confunda con omisión.
    sent = data.model_dump(exclude_unset=True)

    # Field-Level Security (ADR-0011 Sprint 5): rechazar si el usuario intenta
    # tocar campos que su rol no puede editar. Devolvemos 403 con la lista
    # explicita de fields bloqueados (frontend deberia haber deshabilitado
    # los inputs, pero defensa en profundidad obliga al chequeo en backend).
    blocked_fields = field_security_service.validate_update_allowed(
        current_user, "leads", sent,
    )
    if blocked_fields:
        raise HTTPException(
            status_code=403,
            detail=f"Tu rol no puede editar: {', '.join(sorted(blocked_fields))}",
        )

    # `asesor_id` se enruta por el servicio de asignaciones para auditar.
    asesor_id_in_payload = "asesor_id" in sent
    new_asesor_id = sent.pop("asesor_id", None) if asesor_id_in_payload else None

    # V065: sede_id se trata aparte porque debe poder enviarse como NULL
    # explicito (limpiar sede de un lead).
    sede_id_in_payload = "sede_id" in sent
    sede_id_value = sent.pop("sede_id", None) if sede_id_in_payload else None

    # V072: calidad tambien debe poder enviarse como NULL explicito para
    # limpiar la clasificacion del lead (volver a "Sin clasificar").
    calidad_in_payload = "calidad" in sent
    calidad_value = sent.pop("calidad", None) if calidad_in_payload else None

    # V124: Ficha técnica de descubrimiento comercial
    ficha_tecnica_in_payload = "ficha_tecnica" in sent
    ficha_tecnica_value = sent.pop("ficha_tecnica", None) if ficha_tecnica_in_payload else None

    # Columnas que pueden explícitamente ser limpiadas con None / NULL si vienen en sent
    NULLABLE_COLUMNS = {
        "tipo_cierre", "segunda_voz", "motivo_perdida", "motivo_perdida_otro",
        "fecha_proxima_gestion", "accion_proxima_gestion", "codigo_convenio", "referido_por", "observaciones",
        "email", "ciudad", "trabajo", "dni", "tipo_documento", "campana",
    }

    fields = {}
    for k, v in sent.items():
        if k in NULLABLE_COLUMNS:
            if isinstance(v, str):
                fields[k] = v.strip() if v.strip() else None
            else:
                fields[k] = v
        elif v is not None:
            fields[k] = v

    if not fields and not asesor_id_in_payload and not sede_id_in_payload and not calidad_in_payload and not ficha_tecnica_in_payload:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    # Validación de obligatoriedad de campos según el estado (Matrícula, Perdido, Seguimiento)
    target_estado_id = fields.get("estado_id")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if target_estado_id:
                cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (target_estado_id,))
                est_row = cur.fetchone()
            else:
                cur.execute(
                    "SELECT e.nombre FROM crm.leads l JOIN crm.estados_lead e ON l.estado_id = e.id WHERE l.id = %s",
                    (lead_id,),
                )
                est_row = cur.fetchone()

            if est_row:
                est_norm = (est_row["nombre"] or "").lower()
                for _s, _d in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
                    est_norm = est_norm.replace(_s, _d)
                is_matr = any(w in est_norm for w in ["matr", "ganad", "cierr", "venta concretad"])
                is_perd = any(w in est_norm for w in ["perdid", "no interesad", "desist", "descart"])
                is_seg = any(w in est_norm for w in ["seguimiento", "negociacion", "visita"])
                is_opor = "oportunidad" in est_norm or "futur" in est_norm

                if is_matr:
                    # Si se cambia al estado cierre/ganado o si se está enviando/editando tipo_cierre
                    if target_estado_id or "tipo_cierre" in fields:
                        tc = fields.get("tipo_cierre")
                        if not tc or not str(tc).strip():
                            raise HTTPException(
                                status_code=400,
                                detail="Debe ingresar el tipo de cierre de forma obligatoria para este estado.",
                            )
                        if str(tc).strip() == "Con segunda voz" and (not fields.get("segunda_voz") or not str(fields.get("segunda_voz")).strip()):
                            raise HTTPException(
                                status_code=400,
                                detail="Debe indicar la persona que realizó la segunda voz.",
                            )
                elif target_estado_id:
                    # Si cambia a otro estado que no es matrícula y no se envió tipo_cierre, limpiar los campos de cierre
                    if "tipo_cierre" not in fields:
                        fields["tipo_cierre"] = None
                    if "segunda_voz" not in fields:
                        fields["segunda_voz"] = None

                if target_estado_id:
                    if is_perd:
                        mp = fields.get("motivo_perdida")
                        if not mp or not str(mp).strip():
                            raise HTTPException(
                                status_code=400,
                                detail="Debe seleccionar el motivo de pérdida.",
                            )
                        if str(mp).strip() == "Otro" and (not fields.get("motivo_perdida_otro") or not str(fields.get("motivo_perdida_otro")).strip()):
                            raise HTTPException(
                                status_code=400,
                                detail="Debe especificar el motivo de pérdida.",
                            )
                    else:
                        if "motivo_perdida" not in fields:
                            fields["motivo_perdida"] = None
                        if "motivo_perdida_otro" not in fields:
                            fields["motivo_perdida_otro"] = None

                    if is_seg or is_opor:
                        fpg = fields.get("fecha_proxima_gestion")
                        if not fpg or not str(fpg).strip():
                            from datetime import datetime, timedelta, timezone
                            fields["fecha_proxima_gestion"] = (datetime.now(timezone.utc) + timedelta(days=1 if is_seg else 7)).isoformat()
                    else:
                        if "fecha_proxima_gestion" not in fields:
                            fields["fecha_proxima_gestion"] = None

                    if is_opor:
                        apg = fields.get("accion_proxima_gestion")
                        if not apg or not str(apg).strip():
                            fields["accion_proxima_gestion"] = "Volver a contactar"
                    else:
                        if "accion_proxima_gestion" not in fields:
                            fields["accion_proxima_gestion"] = None

    if fields or sede_id_in_payload or calidad_in_payload or ficha_tecnica_in_payload:
        _LEAD_COLUMNS = {
            "nombres", "apellidos", "telefono", "email", "ciudad",
            "trabajo", "observaciones", "estado_id", "fuente_id",
            "campana", "es_recontacto", "referido_por", "codigo_convenio", "dni",
            "calidad",
            # V060: 'proyecto' y 'estrategia' siguen aceptandose para no
            # romper integraciones externas que aun manden esos campos,
            # pero la UI nueva (V060+) NO los envia. Los datos legacy
            # quedan congelados (read-only desde el detalle del lead).
            "proyecto", "estrategia",
            # V102 / V111: campos específicos por estado
            "fecha_proxima_gestion", "accion_proxima_gestion", "motivo_perdida", "motivo_perdida_otro",
            "tipo_cierre", "segunda_voz",
        }
        # V041: solo permitimos tipo_documento si la columna existe en DB.
        # Sin esta guarda, un PATCH con tipo_documento contra un schema sin
        # la migracion aplicada crashearia con "column does not exist".
        if _has_tipo_documento_column():
            _LEAD_COLUMNS.add("tipo_documento")
        else:
            fields.pop("tipo_documento", None)

        # V119: gestión especial por administración
        if _has_gestion_especial_admin_column():
            _LEAD_COLUMNS.add("gestion_especial_admin")
        else:
            fields.pop("gestion_especial_admin", None)

        role_clause, role_params = role_filter(current_user)
        set_clause, set_params = safe_set_clause(fields, _LEAD_COLUMNS) if fields else ("", [])
        # V065: construimos manualmente el SET final inyectando sede_id si
        # vino en el payload (acepta NULL explicito para limpiar la sede).
        set_parts = []
        if set_clause:
            set_parts.append(set_clause)
        if sede_id_in_payload:
            set_parts.append("sede_id = CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END")
            set_params.extend([sede_id_value, sede_id_value])
        # V072: idem para calidad (NULL explicito = limpiar clasificacion).
        if calidad_in_payload:
            set_parts.append("calidad = %s")
            set_params.append(calidad_value)
        # V124: ficha_tecnica JSONB
        if ficha_tecnica_in_payload and _has_ficha_tecnica_column():
            import json
            ft_dict = ficha_tecnica_value if isinstance(ficha_tecnica_value, dict) else {}
            clean_ft = {}
            for k, v in ft_dict.items():
                if isinstance(v, str):
                    clean_ft[k] = v.strip()
                elif v is not None:
                    clean_ft[k] = str(v)
            is_comp = all(
                bool(clean_ft.get(k) and str(clean_ft.get(k)).strip())
                for k in ["motivacion", "beneficiario", "ubicacion", "experiencia_previa", "necesidad_actual", "inicio"]
            )
            set_parts.append("ficha_tecnica = %s::jsonb")
            set_params.append(json.dumps(clean_ft))
            set_parts.append("ficha_tecnica_completada = %s")
            set_params.append(is_comp)
        if "fecha_proxima_gestion" in fields and _has_proxima_gestion_notificada_column():
            set_parts.append("proxima_gestion_notificada_at = NULL")
        set_expr = (", ".join(set_parts) + ", ") if set_parts else ""
        sql_params = set_params + role_params + [lead_id]

        webhook_delivery_id = None
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Obtener estado previo, api_client_id y gestion_especial_admin
                has_ga = _has_gestion_especial_admin_column()
                ga_sel = "COALESCE(l.gestion_especial_admin, FALSE) AS gestion_especial_admin," if has_ga else "FALSE AS gestion_especial_admin,"
                cur.execute(
                    f"""
                    SELECT
                        l.*,
                        e.nombre AS previous_estado_nombre,
                        {ga_sel}
                        l.api_client_id::text AS api_client_id
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.id = %s
                    """,
                    (lead_id,),
                )
                prev_row = cur.fetchone()
                previous_estado_id = prev_row["estado_id"] if prev_row else None
                previous_estado_nombre = prev_row.get("previous_estado_nombre") if prev_row else None
                api_client_id = prev_row.get("api_client_id") if prev_row else None

                cur.execute(
                    f"""
                    UPDATE crm.leads l
                    SET {set_expr}updated_at = NOW()
                    WHERE ({role_clause}) AND id = %s
                    RETURNING id
                    """,
                    sql_params,
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

                # V126: Registrar cambios de campos en crm.lead_historial_cambios
                try:
                    from app.services import lead_history_service
                    all_new_fields = dict(fields)
                    if sede_id_in_payload:
                        all_new_fields["sede_id"] = sede_id_value
                    if calidad_in_payload:
                        all_new_fields["calidad"] = calidad_value
                    if ficha_tecnica_in_payload:
                        all_new_fields["ficha_tecnica"] = clean_ft if 'clean_ft' in locals() else ficha_tecnica_value
                    if is_admin and has_ga and "gestion_especial_admin" in sent:
                        all_new_fields["gestion_especial_admin"] = bool(sent["gestion_especial_admin"])

                    lead_history_service.record_lead_updates(
                        cur,
                        lead_id=lead_id,
                        user=current_user,
                        old_lead=prev_row,
                        new_fields=all_new_fields,
                        origin="edicion_ficha",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[leads.update] error registrando historial lead=%s: %s", lead_id, exc)

                is_admin = getattr(current_user, "role", None) in ("admin", Role.ADMIN.value)

                # V119: Toggle explícito de gestión especial por administración desde el payload
                if is_admin and has_ga and "gestion_especial_admin" in sent:
                    explicit_ga = bool(sent["gestion_especial_admin"])
                    if explicit_ga and not prev_row.get("gestion_especial_admin"):
                        cur.execute(
                            """
                            UPDATE crm.leads
                            SET gestion_especial_admin = TRUE,
                                gestion_admin_at = NOW(),
                                gestion_admin_user_id = %s::uuid
                            WHERE id = %s
                            """,
                            (current_user.user_id, lead_id),
                        )
                        cur.execute(
                            """
                            INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas)
                            VALUES (%s, %s::uuid, 'cambio_estado', '🛡️ Caso especial: Gestión por Administración activada (cambio automático de estados desactivado para este lead)')
                            """,
                            (lead_id, current_user.user_id),
                        )
                    elif not explicit_ga and prev_row.get("gestion_especial_admin"):
                        cur.execute(
                            """
                            UPDATE crm.leads
                            SET gestion_especial_admin = FALSE,
                                gestion_admin_at = NULL,
                                gestion_admin_user_id = NULL
                            WHERE id = %s
                            """,
                            (lead_id,),
                        )
                        cur.execute(
                            """
                            INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas)
                            VALUES (%s, %s::uuid, 'cambio_estado', '🛡️ Gestión por Administración: Automatización de estados reactivada para este lead')
                            """,
                            (lead_id, current_user.user_id),
                        )

                # Si se envió estado_id y cambió respecto al anterior, registrar en crm.contactos
                new_estado_id = fields.get("estado_id")
                if new_estado_id is not None and new_estado_id != previous_estado_id:
                    cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (new_estado_id,))
                    new_est_row = cur.fetchone()
                    new_est_nombre = new_est_row["nombre"] if new_est_row else str(new_estado_id)

                    notas_log = f"Estado → {new_est_nombre}"
                    if fields.get("motivo_perdida"):
                        mp = fields["motivo_perdida"]
                        mpo = fields.get("motivo_perdida_otro")
                        motivo_detalle = f"{mp} ({mpo})" if (mp == "Otro" and mpo) else mp
                        notas_log += f" · Motivo: {motivo_detalle}"
                    elif fields.get("tipo_cierre"):
                        tc = fields["tipo_cierre"]
                        sv = fields.get("segunda_voz")
                        cierre_detalle = f"{tc} (2da voz: {sv})" if (tc == "Con segunda voz" and sv) else tc
                        notas_log += f" · Cierre: {cierre_detalle}"
                    elif fields.get("fecha_proxima_gestion"):
                        notas_log += f" · Próx. gestión: {fields['fecha_proxima_gestion']}"

                    # V119: Si el admin cambia el estado de un lead que cumple reglas automatizadas,
                    # se apaga el cambio automático y se deja evidencia explícita en el historial.
                    if is_admin and has_ga:
                        from app.services.lead_automation_service import lead_cumple_reglas_no_contesta
                        if lead_cumple_reglas_no_contesta(cur, lead_id, previous_estado_nombre) or bool(prev_row.get("gestion_especial_admin")):
                            cur.execute(
                                """
                                UPDATE crm.leads
                                SET gestion_especial_admin = TRUE,
                                    gestion_admin_at = NOW(),
                                    gestion_admin_user_id = %s::uuid
                                WHERE id = %s
                                """,
                                (current_user.user_id, lead_id),
                            )
                            notas_log += " · 🛡️ Caso especial: Gestión por Administración (se ha apagado el cambio automático para este lead)"

                    prox_gestion_val = str(fields["fecha_proxima_gestion"]).strip() if fields.get("fecha_proxima_gestion") else None
                    cur.execute(
                        """
                        INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas, fecha_proxima_accion)
                        VALUES (%s, %s::uuid, 'cambio_estado', %s, %s::timestamptz)
                        """,
                        (lead_id, current_user.user_id, notas_log, prox_gestion_val),
                    )

                    if api_client_id:
                        try:
                            from app.services import webhook_service
                            payload_evt = webhook_service.build_lead_payload(
                                cur, lead_id=lead_id,
                                event_type=webhook_service.EVENT_LEAD_STATUS_CHANGED,
                                previous_estado_id=previous_estado_id,
                                client_id=api_client_id,
                            )
                            if payload_evt:
                                webhook_delivery_id = webhook_service.enqueue_event(
                                    cur, client_id=api_client_id, lead_id=lead_id,
                                    event_type=webhook_service.EVENT_LEAD_STATUS_CHANGED,
                                    payload=payload_evt,
                                )
                        except Exception:  # noqa: BLE001
                            logger.exception("[leads.update] webhook enqueue fallo lead=%s", lead_id)

        if webhook_delivery_id:
            from app.services import webhook_service
            webhook_service.dispatch_async(webhook_delivery_id)

    if asesor_id_in_payload:
        # El servicio decide: si el asesor_id no cambia (no-op) pasa sin
        # ruido; si cambia, valida rol/equipo y escribe el log de auditoría.
        assignments_service.reassign_one(
            lead_id=lead_id,
            new_asesor_id=new_asesor_id,
            current_user=current_user,
        )

    return {"message": "Lead actualizado"}


# ---------------------------------------------------------------------------
# Cambiar estado de un lead
# ---------------------------------------------------------------------------

class EstadoUpdate(BaseModel):
    estado_id: int
    fecha_proxima_gestion: Optional[str] = None
    accion_proxima_gestion: Optional[str] = None
    motivo_perdida: Optional[str] = None
    motivo_perdida_otro: Optional[str] = None
    tipo_cierre: Optional[str] = None
    segunda_voz: Optional[str] = None
    # V119: gestión especial por administración
    gestion_especial_admin: Optional[bool] = None


# IMPORTANTE: /bulk/estado DEBE declararse antes que /{lead_id}/estado
# para que FastAPI no intente parsear "bulk" como lead_id: int → 422.

def _coerce_int_list(v):
    """Acepta lista de ints o strings numericos. Ignora valores invalidos."""
    if v is None:
        return []
    result = []
    for x in v:
        try:
            n = int(x)
            if n > 0:
                result.append(n)
        except (TypeError, ValueError):
            continue
    return result


def _coerce_int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


@router.patch("/bulk/estado")
def bulk_update_estado(
    payload: dict = Body(...),
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    if getattr(current_user, "role_id", None) is not None and not has_permission(current_user, "leads.edit"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar leads.")

    """Cambia el estado de multiples leads en una sola transaccion."""
    ids = _coerce_int_list(payload.get("ids") or [])
    estado_id = _coerce_int(payload.get("estado_id"))
    logger.info(f"bulk/estado payload={payload} parsed ids={ids} estado_id={estado_id}")

    if not ids:
        raise HTTPException(status_code=400, detail="Sin IDs válidos para actualizar")
    if estado_id is None or estado_id <= 0:
        raise HTTPException(status_code=400, detail="estado_id inválido")

    role_clause, role_params = role_filter(current_user)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (estado_id,))
            estado_row = cur.fetchone()
            if not estado_row:
                raise HTTPException(status_code=404, detail="Estado no encontrado")
            estado_nombre = estado_row["nombre"]

            cur.execute(
                f"UPDATE crm.leads SET estado_id = %s, updated_at = NOW() "
                f"WHERE id IN ("
                f"  SELECT l.id FROM crm.leads l "
                f"  WHERE l.id = ANY(%s) AND ({role_clause}) AND l.activo = TRUE"
                f") "
                f"RETURNING id",
                [estado_id, ids] + role_params,
            )
            updated_rows = cur.fetchall()
            updated = len(updated_rows)

            # V119: si quien actualiza en bulk es admin, detectar leads que cumplen reglas y apagarles automatización
            is_admin = getattr(current_user, "role", None) in ("admin", Role.ADMIN.value)
            ids_gestion_admin = set()
            if is_admin and updated > 0 and _has_gestion_especial_admin_column():
                from app.services.lead_automation_service import lead_cumple_reglas_no_contesta
                updated_ids = [r["id"] for r in updated_rows]
                for lid in updated_ids:
                    if lead_cumple_reglas_no_contesta(cur, lid):
                        ids_gestion_admin.add(lid)
                if ids_gestion_admin:
                    cur.execute(
                        """
                        UPDATE crm.leads
                        SET gestion_especial_admin = TRUE,
                            gestion_admin_at = NOW(),
                            gestion_admin_user_id = %s::uuid
                        WHERE id = ANY(%s)
                        """,
                        (current_user.user_id, list(ids_gestion_admin)),
                    )

            if updated > 0:
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    """
                    INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas)
                    VALUES %s
                    """,
                    [
                        (
                            row["id"],
                            current_user.user_id,
                            "cambio_estado",
                            (
                                f"Estado → {estado_nombre} · 🛡️ Caso especial: Gestión por Administración (se ha apagado el cambio automático para este lead)"
                                if row["id"] in ids_gestion_admin
                                else f"Estado → {estado_nombre}"
                            ),
                        )
                        for row in updated_rows
                    ],
                )
        # V070.64 — sin conn.commit() (get_db() lo hace automatico).

                # V126: Registrar en historial de cambios
            try:
                from app.services import lead_history_service
                for row in updated_rows:
                    lead_history_service.record_status_change(
                        cur,
                        lead_id=row["id"],
                        user=current_user,
                        old_estado_id=None,
                        new_estado_id=estado_id,
                        extra_details=f"Cambio masivo a {estado_nombre}",
                        origen="cambio_estado_masivo",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[leads.bulk_update_estado] error registrando historial: %s", exc)

    return {"updated": updated, "estado": estado_nombre}


@router.patch("/bulk/fuente")
def bulk_update_fuente(
    payload: dict = Body(...),
    current_user: TokenData = Depends(require_admin),
):
    """Cambia la fuente de múltiples leads en una sola transacción (Solo Admin)."""
    ids = _coerce_int_list(payload.get("ids") or [])
    fuente_id = _coerce_int(payload.get("fuente_id"))
    logger.info(f"bulk/fuente payload={payload} parsed ids={ids} fuente_id={fuente_id}")

    if not ids:
        raise HTTPException(status_code=400, detail="Sin IDs válidos para actualizar")
    if fuente_id is None or fuente_id <= 0:
        raise HTTPException(status_code=400, detail="fuente_id inválido")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT nombre FROM crm.fuentes WHERE id = %s", (fuente_id,))
            fuente_row = cur.fetchone()
            if not fuente_row:
                raise HTTPException(status_code=404, detail="Fuente no encontrada")
            fuente_nombre = fuente_row["nombre"]

            cur.execute(
                """
                UPDATE crm.leads
                SET fuente_id = %s, updated_at = NOW()
                WHERE id = ANY(%s) AND activo = TRUE
                RETURNING id
                """,
                (fuente_id, ids),
            )
            updated_rows = cur.fetchall()
            updated = len(updated_rows)

            if updated > 0:
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    """
                    INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas)
                    VALUES %s
                    """,
                    [
                        (row["id"], current_user.user_id, "cambio_fuente", f"Fuente → {fuente_nombre}")
                        for row in updated_rows
                    ],
                )

                # V126: Registrar en historial de cambios
            try:
                from app.services import lead_history_service
                for row in updated_rows:
                    lead_history_service.record_field_change(
                        cur,
                        lead_id=row["id"],
                        user=current_user,
                        campo="fuente_id",
                        campo_label="Fuente",
                        valor_anterior=None,
                        valor_nuevo=fuente_nombre,
                        origen="cambio_fuente_masivo",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[leads.bulk_update_fuente] error registrando historial: %s", exc)

    return {"updated": updated, "fuente": fuente_nombre}


@router.patch("/{lead_id}/estado")
def update_estado(lead_id: int, data: EstadoUpdate, current_user: TokenData = Depends(get_current_user)):
    if getattr(current_user, "role_id", None) is not None and not has_permission(current_user, "leads.edit"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar el estado del lead.")

    # Validar obligatoriedad de campos según el estado destino
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (data.estado_id,))
            estado_row = cur.fetchone()
            if not estado_row:
                raise HTTPException(status_code=404, detail="Estado no encontrado")
            estado_nombre = estado_row["nombre"] or ""
            est_norm = estado_nombre.lower()
            for _s, _d in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
                est_norm = est_norm.replace(_s, _d)

            is_matricula = any(w in est_norm for w in ["matr", "ganad", "cierr", "venta concretad"])
            is_perdido = any(w in est_norm for w in ["perdid", "no interesad", "desist", "descart"])
            is_seguimiento = any(w in est_norm for w in ["seguimiento", "negociacion", "visita"])
            is_oportunidad = "oportunidad" in est_norm or "futur" in est_norm

            if is_matricula:
                if not data.tipo_cierre or not data.tipo_cierre.strip():
                    data.tipo_cierre = "Cierre autónomo"
                elif data.tipo_cierre.strip() == "Con segunda voz" and (not data.segunda_voz or not data.segunda_voz.strip()):
                    data.tipo_cierre = "Cierre autónomo"

            if is_perdido:
                if not data.motivo_perdida or not data.motivo_perdida.strip():
                    data.motivo_perdida = "Otro"
                    data.motivo_perdida_otro = "No especificado"
                elif data.motivo_perdida.strip() == "Otro" and (not data.motivo_perdida_otro or not data.motivo_perdida_otro.strip()):
                    data.motivo_perdida_otro = "No especificado"

            if is_seguimiento:
                if not data.fecha_proxima_gestion or not data.fecha_proxima_gestion.strip():
                    from datetime import datetime, timedelta, timezone
                    data.fecha_proxima_gestion = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

            if is_oportunidad:
                if not data.fecha_proxima_gestion or not data.fecha_proxima_gestion.strip():
                    from datetime import datetime, timedelta, timezone
                    data.fecha_proxima_gestion = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                if not data.accion_proxima_gestion or not data.accion_proxima_gestion.strip():
                    data.accion_proxima_gestion = "Volver a contactar"

    # Construir cláusula de permiso sin alias 'l' (UPDATE no usa alias).
    # V035: supervisor también ve leads con supervisor_id = él (en cola).
    if current_user.role == "admin":
        role_clause, role_params = "TRUE", []
    elif current_user.role == "supervisor":
        role_clause = (
            "(asesor_id IN ("
            "    SELECT asesor_id FROM crm.equipos WHERE supervisor_id IN ("
            "        SELECT %s::uuid UNION SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
            "    ) AND activo = TRUE"
            ") "
            "OR asesor_id = %s::uuid "
            "OR (asesor_id IS NULL AND (supervisor_id = %s::uuid OR supervisor_id IN (SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'))))"
        )
        role_params = [current_user.user_id, current_user.user_id, current_user.user_id, current_user.user_id, current_user.user_id]
    else:
        role_clause, role_params = "asesor_id = %s::uuid", [current_user.user_id]

    set_clauses = ["estado_id = %s", "updated_at = NOW()"]
    set_params = [data.estado_id]

    has_pgn_col = _has_proxima_gestion_notificada_column()
    if data.fecha_proxima_gestion is not None:
        set_clauses.append("fecha_proxima_gestion = %s::timestamptz")
        set_params.append(data.fecha_proxima_gestion.strip() if data.fecha_proxima_gestion.strip() else None)
        if has_pgn_col:
            set_clauses.append("proxima_gestion_notificada_at = NULL")
    elif is_seguimiento or is_oportunidad:
        pass
    else:
        set_clauses.append("fecha_proxima_gestion = NULL")
        if has_pgn_col:
            set_clauses.append("proxima_gestion_notificada_at = NULL")

    if data.accion_proxima_gestion is not None:
        set_clauses.append("accion_proxima_gestion = %s")
        set_params.append(data.accion_proxima_gestion.strip() if data.accion_proxima_gestion.strip() else None)
    elif not is_oportunidad:
        set_clauses.append("accion_proxima_gestion = NULL")

    if data.motivo_perdida is not None:
        set_clauses.append("motivo_perdida = %s")
        set_params.append(data.motivo_perdida.strip() if data.motivo_perdida.strip() else None)
    elif not is_perdido:
        set_clauses.append("motivo_perdida = NULL")

    if data.motivo_perdida_otro is not None:
        set_clauses.append("motivo_perdida_otro = %s")
        set_params.append(data.motivo_perdida_otro.strip() if data.motivo_perdida_otro.strip() else None)
    elif not is_perdido:
        set_clauses.append("motivo_perdida_otro = NULL")

    if data.tipo_cierre is not None:
        set_clauses.append("tipo_cierre = %s")
        set_params.append(data.tipo_cierre.strip() if data.tipo_cierre.strip() else None)
    elif not is_matricula:
        set_clauses.append("tipo_cierre = NULL")

    if data.segunda_voz is not None:
        set_clauses.append("segunda_voz = %s")
        set_params.append(data.segunda_voz.strip() if data.segunda_voz.strip() else None)
    elif not is_matricula:
        set_clauses.append("segunda_voz = NULL")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # V058: capturamos estado_id previo + api_client_id para webhook
            # V119: y gestion_especial_admin + previous_estado_nombre
            has_ga = _has_gestion_especial_admin_column()
            ga_sel = "COALESCE(l.gestion_especial_admin, FALSE) AS gestion_especial_admin," if has_ga else "FALSE AS gestion_especial_admin,"
            cur.execute(
                f"""
                SELECT
                    l.*,
                    e.nombre AS previous_estado_nombre,
                    {ga_sel}
                    l.api_client_id::text AS api_client_id
                FROM crm.leads l
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                WHERE l.id = %s
                """,
                (lead_id,),
            )
            prev_row = cur.fetchone()
            previous_estado_id = prev_row["estado_id"] if prev_row else None
            previous_estado_nombre = prev_row.get("previous_estado_nombre") if prev_row else None
            api_client_id = prev_row.get("api_client_id") if prev_row else None

            # V119: Bypass de automatización para gestión especial por administración
            is_admin = getattr(current_user, "role", None) in ("admin", Role.ADMIN.value)
            activar_gestion_admin = False
            reactivar_auto = False
            if is_admin and has_ga:
                from app.services.lead_automation_service import lead_cumple_reglas_no_contesta
                if data.gestion_especial_admin is False:
                    reactivar_auto = True
                elif data.gestion_especial_admin is True:
                    activar_gestion_admin = True
                else:
                    activar_gestion_admin = lead_cumple_reglas_no_contesta(cur, lead_id, previous_estado_nombre) or bool(prev_row.get("gestion_especial_admin"))

            if activar_gestion_admin:
                set_clauses.append("gestion_especial_admin = TRUE")
                set_clauses.append("gestion_admin_at = NOW()")
                set_clauses.append("gestion_admin_user_id = %s::uuid")
                set_params.append(current_user.user_id)
            elif reactivar_auto:
                set_clauses.append("gestion_especial_admin = FALSE")
                set_clauses.append("gestion_admin_at = NULL")
                set_clauses.append("gestion_admin_user_id = NULL")

            full_update_set = ", ".join(set_clauses)
            params = set_params + role_params + [lead_id]

            cur.execute(
                f"""
                UPDATE crm.leads
                SET {full_update_set}
                WHERE ({role_clause}) AND id = %s
                RETURNING id
                """,
                params,
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            # Obtener nombre del estado para el log automático
            cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (data.estado_id,))
            estado_row = cur.fetchone()
            estado_nombre = estado_row["nombre"] if estado_row else str(data.estado_id)

            # Construir notas detalladas para el historial de contactos
            notas_log = f"Estado → {estado_nombre}"
            if data.motivo_perdida:
                motivo_detalle = f"{data.motivo_perdida} ({data.motivo_perdida_otro})" if (data.motivo_perdida == "Otro" and data.motivo_perdida_otro) else data.motivo_perdida
                notas_log += f" · Motivo: {motivo_detalle}"
            elif data.tipo_cierre:
                cierre_detalle = f"{data.tipo_cierre} (2da voz: {data.segunda_voz})" if (data.tipo_cierre == "Con segunda voz" and data.segunda_voz) else data.tipo_cierre
                notas_log += f" · Cierre: {cierre_detalle}"
            elif data.fecha_proxima_gestion:
                notas_log += f" · Próx. gestión: {data.fecha_proxima_gestion}"

            if activar_gestion_admin:
                notas_log += " · 🛡️ Caso especial: Gestión por Administración (se ha apagado el cambio automático para este lead)"
            elif reactivar_auto:
                notas_log += " · 🛡️ Gestión por Administración: Automatización de estados reactivada para este lead"

            # Registrar cambio de estado en historial (sin incrementar intentos_contacto)
            prox_gestion_val = data.fecha_proxima_gestion.strip() if (data.fecha_proxima_gestion and data.fecha_proxima_gestion.strip()) else None
            cur.execute(
                """
                INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas, fecha_proxima_accion)
                VALUES (%s, %s::uuid, 'cambio_estado', %s, %s::timestamptz)
                """,
                (lead_id, current_user.user_id, notas_log, prox_gestion_val),
            )

            # V126: Registrar en historial de cambios
            try:
                from app.services import lead_history_service
                lead_history_service.record_status_change(
                    cur,
                    lead_id=lead_id,
                    user=current_user,
                    old_estado_id=previous_estado_id,
                    new_estado_id=data.estado_id,
                    extra_details=data.motivo_perdida or data.tipo_cierre or None,
                    origen="cambio_estado",
                )
                extra_status_fields = {}
                if data.fecha_proxima_gestion is not None:
                    extra_status_fields["fecha_proxima_gestion"] = data.fecha_proxima_gestion
                if data.accion_proxima_gestion is not None:
                    extra_status_fields["accion_proxima_gestion"] = data.accion_proxima_gestion
                if data.motivo_perdida is not None:
                    extra_status_fields["motivo_perdida"] = data.motivo_perdida
                if data.motivo_perdida_otro is not None:
                    extra_status_fields["motivo_perdida_otro"] = data.motivo_perdida_otro
                if data.tipo_cierre is not None:
                    extra_status_fields["tipo_cierre"] = data.tipo_cierre
                if data.segunda_voz is not None:
                    extra_status_fields["segunda_voz"] = data.segunda_voz
                if extra_status_fields and prev_row:
                    lead_history_service.record_lead_updates(
                        cur,
                        lead_id=lead_id,
                        user=current_user,
                        old_lead=prev_row,
                        new_fields=extra_status_fields,
                        origin="cambio_estado",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[leads.update_estado] error registrando historial lead=%s: %s", lead_id, exc)

            # V058: encolar webhook lead.status_changed si el lead viene
            # de un proveedor con webhook configurado. Solo si realmente
            # cambio el estado (no si seleccionaron el mismo).
            webhook_delivery_id = None
            if api_client_id and previous_estado_id != data.estado_id:
                try:
                    from app.services import webhook_service
                    payload_evt = webhook_service.build_lead_payload(
                        cur, lead_id=lead_id,
                        event_type=webhook_service.EVENT_LEAD_STATUS_CHANGED,
                        previous_estado_id=previous_estado_id,
                        client_id=api_client_id,
                    )
                    if payload_evt:
                        webhook_delivery_id = webhook_service.enqueue_event(
                            cur, client_id=api_client_id, lead_id=lead_id,
                            event_type=webhook_service.EVENT_LEAD_STATUS_CHANGED,
                            payload=payload_evt,
                        )
                except Exception:  # noqa: BLE001
                    logger.exception("[leads.estado] webhook enqueue fallo lead=%s", lead_id)
        # V070.64 — sin conn.commit() (get_db() lo hace automatico).

    # V060.2: dispatch INMEDIATO post-commit
    if webhook_delivery_id:
        from app.services import webhook_service
        webhook_service.dispatch_async(webhook_delivery_id)

    return {"message": "Estado actualizado"}


# ---------------------------------------------------------------------------
# Reasignar asesor (solo supervisor/admin)
# ---------------------------------------------------------------------------

class AsesorUpdate(BaseModel):
    asesor_id: Optional[str] = None  # None = desasignar


class BulkAsesorUpdate(BaseModel):
    ids: List[int]
    asesor_id: Optional[str] = None  # None = liberar

    @field_validator("ids", mode="before")
    @classmethod
    def _v_ids(cls, v):
        return _coerce_int_list(v)


@router.patch("/bulk/asesor")
def bulk_reassign_asesor(
    data: BulkAsesorUpdate,
    current_user: TokenData = Depends(check_permission("asignacion.manage", "supervisor", "admin")),
):
    """Reasignación masiva en una sola transacción.

    - admin o global: cualquier lead → cualquier asesor/supervisor.
    - equipo: solo leads de su equipo → miembros de su equipo (supervisores y asesores).
    - personalizado: solo hacia los usuarios autorizados en el rol.
    - El filtro de rol se aplica también dentro del repositorio como
      defensa en profundidad (los IDs ajenos al user se descartan).
    - Cada cambio queda registrado en `crm.asignaciones_log`.
    """
    result = assignments_service.reassign_bulk(
        lead_ids=data.ids,
        new_asesor_id=data.asesor_id,
        current_user=current_user,
    )
    return {"message": "Asesores reasignados", **result}


@router.patch("/{lead_id}/asesor")
def reassign_asesor(
    lead_id: int,
    data: AsesorUpdate,
    current_user: TokenData = Depends(check_permission("asignacion.manage", "supervisor", "admin")),
):
    """Reasigna (o libera con null) un único lead.

    - admin o global: cualquier lead → cualquier asesor/supervisor.
    - equipo: solo leads de su equipo y solo hacia miembros de su equipo.
    - personalizado: solo hacia usuarios autorizados.
    - Toda transición se registra en `crm.asignaciones_log` (auditoría).
    """
    result = assignments_service.reassign_one(
        lead_id=lead_id,
        new_asesor_id=data.asesor_id,
        current_user=current_user,
    )
    return {"message": "Asesor reasignado", **result}


# ---------------------------------------------------------------------------
# Derivación al asesor que trabajó originalmente al cliente (Antecedentes)
# ---------------------------------------------------------------------------

class DeriveAntecedentePayload(BaseModel):
    asesor_id: str


@router.post("/{lead_id}/derivar-antecedente")
def derive_antecedente(
    lead_id: int,
    data: DeriveAntecedentePayload,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Devuelve el lead al asesor (de cualquier equipo) que ya lo trabajó
    según los antecedentes registrados.

    El servicio valida que `asesor_id` realmente aparezca en los antecedentes
    del lead — sin esa salvaguarda, este endpoint sería un bypass total
    de los permisos por equipo.
    """
    result = assignments_service.derive_to_original_asesor(
        lead_id=lead_id,
        target_asesor_id=data.asesor_id,
        current_user=current_user,
    )
    return {"message": "Lead derivado al asesor original", **result}


# ---------------------------------------------------------------------------
# Asignación automática round-robin (solo supervisor/admin)
# Distribuye leads sin asesor entre los asesores del equipo del supervisor
# ---------------------------------------------------------------------------

@router.post("/asignacion-automatica")
def asignacion_automatica(current_user: TokenData = Depends(require_supervisor_or_admin)):
    """Round-robin de leads sin asesor entre el equipo del usuario actual.

    Cada asignación queda registrada en `crm.asignaciones_log` con
    motivo='round_robin' para auditoría y reporting.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Obtener asesores disponibles según rol.
            # V094.6 — patrón estándar "Freeze": auto-routing (round-robin masivo)
            # salta usuarios con login_blocked=TRUE. La asignacion manual
            # uno-a-uno desde el dropdown SI los muestra (el admin elige).
            if current_user.role == "admin":
                cur.execute(
                    """
                    SELECT id::text AS id FROM auth.users
                    WHERE role = 'asesor'
                      AND is_active = TRUE
                      AND COALESCE(login_blocked, FALSE) = FALSE
                    ORDER BY id
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT u.id::text AS id FROM auth.users u
                    JOIN crm.equipos eq ON eq.asesor_id = u.id
                    WHERE eq.supervisor_id = %s::uuid
                      AND eq.activo = TRUE
                      AND u.is_active = TRUE
                      AND COALESCE(u.login_blocked, FALSE) = FALSE
                    ORDER BY u.id
                    """,
                    (current_user.user_id,),
                )
            asesores = [r["id"] for r in cur.fetchall()]

            if not asesores:
                raise HTTPException(status_code=400, detail="No hay asesores disponibles")

            # Obtener leads sin asesor
            cur.execute(
                "SELECT id FROM crm.leads WHERE asesor_id IS NULL AND activo = TRUE ORDER BY id FOR UPDATE"
            )
            leads = [r["id"] for r in cur.fetchall()]

            if not leads:
                return {"assigned": 0, "message": "No hay leads sin asignar"}

            # Asignar en round-robin: lo construimos como pares y aplicamos
            # UPDATE + INSERT log en lotes para mantener atomicidad sin
            # explotar el connection time.
            pairs = [(leads[i], asesores[i % len(asesores)]) for i in range(len(leads))]

            cur.executemany(
                """
                UPDATE crm.leads
                   SET asesor_id  = %s::uuid,
                       updated_at = NOW()
                 WHERE id = %s
                """,
                [(asesor_id, lead_id) for lead_id, asesor_id in pairs],
            )
            cur.executemany(
                """
                INSERT INTO crm.asignaciones_log
                    (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                VALUES (%s, NULL, %s::uuid, %s::uuid, 'round_robin')
                """,
                [(lead_id, asesor_id, current_user.user_id) for lead_id, asesor_id in pairs],
            )
            assigned = len(pairs)
        # V070.64 — sin conn.commit() (get_db() lo hace automatico).

    return {"assigned": assigned, "message": f"{assigned} leads asignados automáticamente"}


# ---------------------------------------------------------------------------
# Eliminación masiva de leads (soft delete) — solo supervisor/admin
# ---------------------------------------------------------------------------

class BulkDeleteLeadsRequest(BaseModel):
    ids: List[int]

    @field_validator("ids", mode="before")
    @classmethod
    def _v_ids(cls, v):
        return _coerce_int_list(v)


@router.delete("/bulk", status_code=200)
def delete_leads_bulk(
    data: BulkDeleteLeadsRequest,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    if getattr(current_user, "role_id", None) is not None and not has_permission(current_user, "leads.delete"):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar leads.")

    """
    Soft-delete masivo de leads (activo = FALSE).
    El supervisor solo puede eliminar leads de sus propios asesores.
    El admin puede eliminar cualquier lead.
    """
    if not data.ids:
        raise HTTPException(status_code=400, detail="Sin IDs para eliminar")

    role_clause, role_params = role_filter(current_user)

    # role_clause usa alias `l.asesor_id` — lo envolvemos en subquery
    # para soportar supervisor/asesor (el UPDATE no puede tener alias propio).
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE crm.leads SET activo = FALSE, updated_at = NOW() "
                f"WHERE id IN ("
                f"  SELECT l.id FROM crm.leads l "
                f"  WHERE l.id = ANY(%s) AND ({role_clause})"
                f") "
                f"RETURNING id",
                [data.ids] + role_params,
            )
            deleted = cur.rowcount
        # V070.64 — sin conn.commit() (get_db() lo hace automatico).

    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Historial de asignaciones de un lead (auditoría)
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/properties")
def list_lead_properties(
    lead_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Propiedades custom del lead (valores EAV + metadata de property_definitions).

    Respeta el filtro por rol — si el usuario no puede ver el lead, no
    puede leer sus propiedades.
    """
    role_clause, params = role_filter(current_user)
    params.append(lead_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id FROM crm.leads l WHERE ({role_clause}) AND id = %s AND activo = TRUE",
                params,
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")
    from app.services.integrations import field_mappings_repo as _fm
    return {"items": _fm.get_properties_for_lead(lead_id)}


@router.get("/{lead_id}/asignaciones")
def list_assignments_history(
    lead_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Devuelve el historial de reasignaciones para un lead.

    El acceso al historial respeta el filtro de rol: si el usuario no
    puede ver el lead, tampoco puede ver su historial.
    """
    role_clause, params = role_filter(current_user)
    params.append(lead_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id FROM crm.leads l WHERE ({role_clause}) AND id = %s AND activo = TRUE",
                params,
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

    return leads_repository.find_assignments_history(lead_id)


# ---------------------------------------------------------------------------
# V126: Historial de cambios de un lead (auditor?a completa de campos)
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/historial-cambios")
def get_lead_historial_cambios(
    lead_id: int,
    limit: int = Query(150, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: TokenData = Depends(get_current_user),
):
    """Devuelve el historial detallado de cambios de un lead (auditor?a)."""
    role_clause, params = role_filter(current_user)
    params.append(lead_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id FROM crm.leads l WHERE ({role_clause}) AND id = %s AND activo = TRUE",
                params,
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            from app.services import lead_history_service
            return lead_history_service.get_lead_history(cur, lead_id=lead_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# V127: Fusión de leads con el mismo teléfono desde la ficha del lead
# ---------------------------------------------------------------------------

class LeadMergeInLeadRequest(BaseModel):
    secondary_id: int = Field(..., description="ID del lead duplicado que se absorberá en este lead")
    chosen_owner_id: Optional[str] = Field(default=None, description="UUID del asesor que tendrá la autoridad del lead fusionado")
    field_decisions: Optional[dict[str, str]] = Field(default=None, description="Decisiones campo por campo ('master' | 'secondary')")
    notes: Optional[str] = Field(default=None, max_length=2000, description="Notas explicativas de la fusión")


@router.get("/{lead_id}/duplicate-candidate")
def check_lead_duplicate_candidate(
    lead_id: int,
    current_user: TokenData = Depends(require_admin),
):
    """V127: busca otros leads activos que compartan el mismo teléfono para ofrecer la opción de fusión (solo admin)."""
    role_clause, params = role_filter(current_user)
    params.append(lead_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id FROM crm.leads l WHERE ({role_clause}) AND id = %s",
                params,
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            from app.services import lead_merge_service
            return lead_merge_service.get_candidate_duplicates(cur, lead_id)


@router.get("/{lead_id}/merge-preview")
def get_lead_merge_preview(
    lead_id: int,
    secondary_id: int = Query(..., ge=1),
    current_user: TokenData = Depends(require_admin),
):
    """V127: vista previa de fusión comparando el lead actual con el candidato secundario (solo admin)."""
    from app.services import lead_merge_service
    return lead_merge_service.preview_merge(lead_id, secondary_id)


@router.post("/{lead_id}/merge")
def execute_lead_merge(
    lead_id: int,
    req: LeadMergeInLeadRequest,
    current_user: TokenData = Depends(require_admin),
):
    """V127: ejecuta la fusión de dos leads que comparten el mismo teléfono (solo admin)."""
    user_name = " ".join(filter(None, [
        getattr(current_user, "first_name", None),
        getattr(current_user, "last_name", None),
    ])).strip() or getattr(current_user, "email", None) or "Usuario"

    from app.services import lead_merge_service
    return lead_merge_service.merge_leads(
        master_id=lead_id,
        secondary_id=req.secondary_id,
        chosen_owner_id=req.chosen_owner_id,
        field_decisions=req.field_decisions,
        notes=req.notes,
        admin_user_id=str(current_user.user_id),
        admin_user_name=user_name,
        admin_user_role=getattr(current_user, "role", "admin"),
    )


# ---------------------------------------------------------------------------
# V048: Historial de re-engagement (recontactos) de un lead
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/recontactos")
def list_recontactos(
    lead_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Lista los re-engagements de un lead (V048): cada vez que el mismo
    cliente volvio a interesarse via otra campaña/fuente."""
    role_clause, params = role_filter(current_user)
    params.append(lead_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id FROM crm.leads l WHERE ({role_clause}) AND id = %s AND activo = TRUE",
                params,
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            try:
                # V084 — incluimos anuncio/conjunto/fuente_form_id para que el
                # asesor vea QUE campaña/ad/adset trajo el nuevo interes del
                # cliente. Si la DB no tiene V084 aplicada, las columnas no
                # existen y caemos al fallback sin esos campos.
                cur.execute(
                    """
                    SELECT
                        r.id, r.lead_id,
                        r.fuente_id, f.nombre AS fuente_nombre,
                        r.api_client_id::text AS api_client_id,
                        ac.nombre AS api_client_nombre,
                        r.campana, r.fuente_externa_id,
                        r.anuncio, r.conjunto, r.fuente_form_id,
                        -- V096.4 — nombres legibles via meta_catalog_cache.
                        -- Antes el panel Re-engagement solo mostraba IDs
                        -- ("Campaña: 120211999888777" en lugar del nombre).
                        mc_c.name AS campaign_name,
                        mc_f.name AS form_name,
                        r.asesor_mantenido::text AS asesor_mantenido,
                        TRIM(COALESCE(am.first_name,'') || ' ' || COALESCE(am.last_name,'')) AS asesor_mantenido_nombre,
                        r.asesor_anterior::text AS asesor_anterior,
                        TRIM(COALESCE(aa.first_name,'') || ' ' || COALESCE(aa.last_name,'')) AS asesor_anterior_nombre,
                        r.estrategia, r.estado_lead_anterior, r.estado_lead_nuevo,
                        r.notificado, r.razon,
                        r.created_at::text AS created_at
                    FROM crm.lead_recontactos r
                    LEFT JOIN crm.fuentes f ON f.id = r.fuente_id
                    LEFT JOIN crm.api_clients ac ON ac.id = r.api_client_id
                    LEFT JOIN auth.users am ON am.id = r.asesor_mantenido
                    LEFT JOIN auth.users aa ON aa.id = r.asesor_anterior
                    LEFT JOIN crm.meta_catalog_cache mc_c
                      ON mc_c.entity_type = 'campaign' AND mc_c.entity_id = r.campana
                    LEFT JOIN crm.meta_catalog_cache mc_f
                      ON mc_f.entity_type = 'form'     AND mc_f.entity_id = r.fuente_form_id
                    WHERE r.lead_id = %s
                    ORDER BY r.created_at DESC
                    """,
                    (lead_id,),
                )
                rows = [dict(r) for r in cur.fetchall()]
            except Exception:
                # V048 / V084 aún no aplicada — fallback al schema viejo.
                try:
                    cur.execute(
                        """
                        SELECT
                            r.id, r.lead_id,
                            r.fuente_id, f.nombre AS fuente_nombre,
                            r.api_client_id::text AS api_client_id,
                            ac.nombre AS api_client_nombre,
                            r.campana, r.fuente_externa_id,
                            r.asesor_mantenido::text AS asesor_mantenido,
                            TRIM(COALESCE(am.first_name,'') || ' ' || COALESCE(am.last_name,'')) AS asesor_mantenido_nombre,
                            r.asesor_anterior::text AS asesor_anterior,
                            TRIM(COALESCE(aa.first_name,'') || ' ' || COALESCE(aa.last_name,'')) AS asesor_anterior_nombre,
                            r.estrategia, r.estado_lead_anterior, r.estado_lead_nuevo,
                            r.notificado, r.razon,
                            r.created_at::text AS created_at
                        FROM crm.lead_recontactos r
                        LEFT JOIN crm.fuentes f ON f.id = r.fuente_id
                        LEFT JOIN crm.api_clients ac ON ac.id = r.api_client_id
                        LEFT JOIN auth.users am ON am.id = r.asesor_mantenido
                        LEFT JOIN auth.users aa ON aa.id = r.asesor_anterior
                        WHERE r.lead_id = %s
                        ORDER BY r.created_at DESC
                        """,
                        (lead_id,),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                except Exception:
                    rows = []
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Historial de contactos de un lead
# ---------------------------------------------------------------------------

@router.get("/{lead_id}/contactos")
def list_contactos(lead_id: int, current_user: TokenData = Depends(get_current_user)):
    role_clause, params = role_filter(current_user)
    params.append(lead_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verificar acceso al lead
            cur.execute(
                f"SELECT id FROM crm.leads l WHERE ({role_clause}) AND id = %s AND activo = TRUE",
                params,
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            # V070.30 — Devolver tambien cita_estado_* para que el frontend
            # muestre el badge correcto despues de un PATCH. Antes este
            # endpoint omitia esos campos → al editar el estado a "Completada",
            # el PATCH actualizaba DB pero el GET no traia el dato → la UI
            # mostraba siempre "Pendiente" en las refrescos. Reportado en UAT.
            #
            # LEFT JOIN tolerante: cita_estados existe desde V042. Si la
            # tabla aun no existe en algun deploy lageado, la query falla
            # — pero V042 ya esta aplicada hace tiempo. Sin fallback aqui
            # — el contactos.py tiene una version con self-heal si hace falta.
            cur.execute(
                """
                SELECT
                    c.id, c.tipo_contacto, c.resultado, c.notas,
                    c.proxima_accion, c.fecha_proxima_accion::text,
                    c.fecha_cita::text, c.tipo_cita, c.url_reunion, c.duracion_minutos,
                    c.created_at::text,
                    c.cita_estado_id,
                    ce.codigo    AS cita_estado_codigo,
                    ce.nombre    AS cita_estado_nombre,
                    ce.color_hex AS cita_estado_color,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre
                FROM crm.contactos c
                LEFT JOIN auth.users u            ON u.id  = c.asesor_id
                LEFT JOIN crm.cita_estados ce     ON ce.id = c.cita_estado_id
                WHERE c.lead_id = %s
                ORDER BY c.created_at DESC
                """,
                (lead_id,),
            )
            return cur.fetchall()


# ---------------------------------------------------------------------------
# Antecedentes — matches del lead en historico legacy + leads inactivos
# ---------------------------------------------------------------------------

def _is_test_or_invalid_dni(dni: Optional[str]) -> bool:
    """Detecta DNIs basura/de prueba que generarian falsos positivos
    masivos en el matching de antecedentes.

    Casos cubiertos:
      - Menos de 7 digitos
      - Todos los digitos iguales (11111111, 99999999)
      - Secuenciales ascendentes (01234567, 12345678)
      - Secuenciales descendentes (87654321, 98765432)
      - DNIs conocidos de pruebas/seeds
    """
    if not dni:
        return True
    s = re.sub(r"\D", "", dni.strip())
    if len(s) < 7:
        return True
    # Todos los digitos iguales
    if len(set(s)) == 1:
        return True
    # Secuenciales (asc/desc) — comparamos diferencias entre digitos consecutivos
    diffs = {int(s[i + 1]) - int(s[i]) for i in range(len(s) - 1)}
    if diffs == {1} or diffs == {-1}:
        return True
    # DNIs hardcoded de pruebas
    if s in {"12345678", "87654321", "00000000"}:
        return True
    return False


@router.get("/{lead_id}/origen-meta")
def get_lead_origen_meta(
    lead_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Devuelve la data de Meta (Facebook/Instagram) asociada al lead:
    leadgen_id (Facebook Lead ID), ad_id, adset_id, campaign_id +
    nombres legibles desde meta_catalog_cache.

    Devuelve 200 con `interactions: []` si el lead no es de Meta — la
    UI decide ocultar la seccion en ese caso.
    """
    role_clause, params = role_filter(current_user)
    params.append(lead_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT 1 FROM crm.leads l
                WHERE ({role_clause}) AND l.id = %s
                """,
                params,
            )
            if not cur.fetchone():
                raise HTTPException(404, "Lead no encontrado o sin permiso")

            cur.execute(
                """
                SELECT
                    im.leadgen_id,
                    im.page_id,
                    im.form_id,
                    im.ad_id,
                    im.adset_id,
                    im.campaign_id,
                    im.es_duplicado,
                    im.fecha_interaccion,
                    cf.name  AS form_name,
                    ca.name  AS ad_name,
                    cs.name  AS adset_name,
                    cc.name  AS campaign_name
                FROM crm.lead_interacciones_meta im
                LEFT JOIN crm.meta_catalog_cache cf
                       ON cf.entity_type = 'form'     AND cf.entity_id = im.form_id
                LEFT JOIN crm.meta_catalog_cache ca
                       ON ca.entity_type = 'ad'       AND ca.entity_id = im.ad_id
                LEFT JOIN crm.meta_catalog_cache cs
                       ON cs.entity_type = 'adset'    AND cs.entity_id = im.adset_id
                LEFT JOIN crm.meta_catalog_cache cc
                       ON cc.entity_type = 'campaign' AND cc.entity_id = im.campaign_id
                WHERE im.lead_id = %s
                ORDER BY im.fecha_interaccion DESC
                LIMIT 20
                """,
                (lead_id,),
            )
            interactions = [dict(r) for r in cur.fetchall()]
            for r in interactions:
                if r.get("fecha_interaccion") is not None:
                    r["fecha_interaccion"] = r["fecha_interaccion"].isoformat()

    return {"interactions": interactions, "total": len(interactions)}


@router.get("/{lead_id}/antecedentes")
def list_lead_antecedentes(
    lead_id: int,
    current_user: TokenData = Depends(get_current_user),
):
    """Devuelve todos los antecedentes del lead: cruza por telefono
    normalizado (ultimos 9 digitos) o DNI contra:

      1. crm_legacy.leads_historico (sistema anterior)
      2. crm.leads inactivos (duplicados/reactivaciones del propio CRM)

    Debe ser coherente con el flag `es_recontacto` (bootstrap.py
    `ensure_recontacto_backfill`): si el flag esta TRUE, este endpoint
    debe devolver al menos un item; si no, la UI mostraria una pildora
    sin drill-down.

    DNIs claramente de prueba (12345678, 11111111, secuenciales) se
    excluyen del matching para evitar falsos positivos masivos cuando
    se usan datos de seed.

    Scopeado via role_filter: asesores solo ven antecedentes de sus
    propios leads.
    """
    role_clause, params = role_filter(current_user)
    params.append(lead_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT l.telefono, l.dni
                FROM crm.leads l
                WHERE ({role_clause}) AND l.id = %s AND l.activo = TRUE
                """,
                params,
            )
            lead = cur.fetchone()
            if not lead:
                raise HTTPException(404, "Lead no encontrado o sin permiso")

            telefono_raw = (lead["telefono"] or "").strip()
            digits = re.sub(r"\D", "", telefono_raw)
            last9 = digits[-9:] if len(digits) >= 9 else None
            dni_raw = (lead["dni"] or "").strip() or None
            # Excluir DNIs de prueba para evitar matches masivos. Si el lead
            # llega con DNI 12345678 (seed), seguimos buscando por telefono.
            dni = None if _is_test_or_invalid_dni(dni_raw) else dni_raw
            if dni_raw and not dni:
                logger.info(
                    "[antecedentes] lead=%s dni '%s' descartado por basura/test",
                    lead_id, dni_raw,
                )

            if not last9 and not dni:
                return {
                    "total": 0,
                    "items": [],
                    "summary": {"by_telefono": 0, "by_dni": 0, "by_ambos": 0,
                                "con_asesor": 0, "sin_asesor": 0},
                }

            items: list[dict] = []

            # 1) Historico legacy ------------------------------------------------
            # V070.82: incluimos match_telefono / match_dni en cada fila para
            # mostrar en UI el chip de razon del match. Los CASE usan los
            # mismos parametros del WHERE (duplicados al inicio del array
            # de params para el SELECT).
            select_match_legacy = []
            select_params_legacy: list = []
            if last9:
                select_match_legacy.append(
                    "CASE WHEN h.telefono_norm LIKE %s THEN TRUE ELSE FALSE END AS match_telefono"
                )
                select_params_legacy.append(f"%{last9}%")
            else:
                select_match_legacy.append("FALSE AS match_telefono")
            if dni:
                select_match_legacy.append(
                    "CASE WHEN h.dni = %s THEN TRUE ELSE FALSE END AS match_dni"
                )
                select_params_legacy.append(dni)
            else:
                select_match_legacy.append("FALSE AS match_dni")

            where_parts = []
            q_params: list = []
            if last9:
                where_parts.append("h.telefono_norm LIKE %s")
                q_params.append(f"%{last9}%")
            if dni:
                where_parts.append("h.dni = %s")
                q_params.append(dni)
            where_sql = " OR ".join(where_parts)

            try:
                cur.execute(
                    f"""
                    SELECT
                        h.id, h.nombre, h.telefono, h.email, h.dni,
                        h.proyecto, h.canal, h.asesor_nombre,
                        h.estado, h.seguimiento, h.observaciones,
                        h.ciudad, h.fecha_ingreso::text, h.origen_tabla,
                        {', '.join(select_match_legacy)}
                    FROM crm_legacy.leads_historico h
                    WHERE {where_sql}
                    ORDER BY h.fecha_ingreso DESC NULLS LAST, h.id DESC
                    LIMIT 100
                    """,
                    select_params_legacy + q_params,
                )
                for row in cur.fetchall():
                    row["source"] = "legacy"
                    items.append(row)
            except Exception as exc:
                # Si la tabla legacy no existe (entorno limpio/testing), no
                # reventamos — seguimos con los inactivos del CRM.
                logger.info("antecedentes: legacy lookup omitido — %s", exc)
                conn.rollback()

            # 2) Leads previos del propio CRM (duplicados activos o inactivos) ---
            # Matching por ultimos 9 digitos normalizados: es tolerante a
            # diferencias de formato (+51, espacios, guiones, etc.) que no
            # captaria un l.telefono = %s exacto. Incluimos activos porque un
            # duplicado activo tambien es "antecedente" (mismo cliente, otro
            # registro). Excluimos el propio lead por id.
            if last9 or dni:
                select_match_crm = []
                select_params_crm: list = []
                if last9:
                    select_match_crm.append(
                        "CASE WHEN RIGHT(REGEXP_REPLACE(l.telefono, '\\D', '', 'g'), 9) = %s "
                        "THEN TRUE ELSE FALSE END AS match_telefono"
                    )
                    select_params_crm.append(last9)
                else:
                    select_match_crm.append("FALSE AS match_telefono")
                if dni:
                    select_match_crm.append(
                        "CASE WHEN l.dni = %s THEN TRUE ELSE FALSE END AS match_dni"
                    )
                    select_params_crm.append(dni)
                else:
                    select_match_crm.append("FALSE AS match_dni")

                where_parts_crm = []
                q_params_crm: list = []
                if last9:
                    where_parts_crm.append(
                        "RIGHT(REGEXP_REPLACE(l.telefono, '\\D', '', 'g'), 9) = %s"
                    )
                    q_params_crm.append(last9)
                if dni:
                    where_parts_crm.append("l.dni = %s")
                    q_params_crm.append(dni)
                where_crm = " OR ".join(where_parts_crm)
                q_params_crm.append(lead_id)

                try:
                    cur.execute(
                        f"""
                        SELECT
                            l.id,
                            TRIM(CONCAT_WS(' ', l.nombres, l.apellidos)) AS nombre,
                            l.telefono,
                            l.email,
                            l.dni,
                            NULL::text AS proyecto,
                            f.nombre AS canal,
                            l.asesor_id::text AS asesor_id,
                            TRIM(CONCAT_WS(' ', u.first_name, u.last_name)) AS asesor_nombre,
                            u.role AS asesor_role,
                            e.nombre AS estado,
                            NULL::text AS seguimiento,
                            l.observaciones,
                            NULL::text AS ciudad,
                            l.created_at::text AS fecha_ingreso,
                            CASE WHEN l.activo THEN 'crm_activo' ELSE 'crm_inactivo' END AS origen_tabla,
                            l.activo,
                            {', '.join(select_match_crm)}
                        FROM crm.leads l
                        LEFT JOIN crm.fuentes f       ON f.id = l.fuente_id
                        LEFT JOIN crm.estados_lead e  ON e.id = l.estado_id
                        LEFT JOIN auth.users u        ON u.id = l.asesor_id
                        WHERE ({where_crm})
                          AND l.id <> %s
                        ORDER BY l.created_at DESC
                        LIMIT 50
                        """,
                        select_params_crm + q_params_crm,
                    )
                    for row in cur.fetchall():
                        row["source"] = (
                            "crm_activo" if row.pop("activo", False) else "crm_inactivo"
                        )
                        items.append(row)
                except Exception as exc:
                    logger.info("antecedentes: lookup duplicados crm omitido — %s", exc)
                    conn.rollback()

    # Ordenamos todos los antecedentes por fecha_ingreso desc (None al final)
    items.sort(
        key=lambda r: (r.get("fecha_ingreso") or ""),
        reverse=True,
    )

    # V070.82: summary del card — totales por razon del match y por
    # disponibilidad de asesor. Permite al operador leer el contexto del
    # cliente en 2 segundos antes de revisar item por item.
    summary = {
        "by_telefono": sum(1 for it in items if it.get("match_telefono") and not it.get("match_dni")),
        "by_dni":      sum(1 for it in items if it.get("match_dni") and not it.get("match_telefono")),
        "by_ambos":    sum(1 for it in items if it.get("match_telefono") and it.get("match_dni")),
        "con_asesor":  sum(1 for it in items if it.get("asesor_id")),
        "sin_asesor":  sum(1 for it in items if not it.get("asesor_id")),
    }
    return {"total": len(items), "items": items, "summary": summary}

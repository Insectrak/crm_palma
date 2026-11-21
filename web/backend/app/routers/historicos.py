"""
Consulta y gestión de leads históricos (crm_legacy.leads_historico).

Módulo exclusivo para Administradores:
- Capacidad de carga masiva de hasta 5,000 registros.
- Soporte para columnas extendidas: Estado del lead, Creación, Asignación, Último contacto.
- Flexibilidad total en el campo Asesor (acepta texto libre y alerta si no existe en el CRM).
- Consulta y filtrado desglosado por meses con paginación máxima de 50.
- Check de duplicados dual (CRM e Histórico) y promoción automática al asignar asesor.
- Eliminación individual y masiva de leads históricos.
"""
from __future__ import annotations

import io
import json
import logging
import re
from datetime import date, datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from app.auth.jwt import require_admin, require_supervisor_or_admin
from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/historicos", tags=["Historicos"])

MAX_ROWS = 5000
MAX_MB = 15
MAX_PAGE_SIZE = 50

MONTH_NAMES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

_schema_ensured = False


def _ensure_schema_if_needed(conn):
    global _schema_ensured
    if _schema_ensured:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE SCHEMA IF NOT EXISTS crm_legacy;

                CREATE TABLE IF NOT EXISTS crm_legacy.leads_historico (
                    id                     BIGSERIAL PRIMARY KEY,
                    telefono               TEXT,
                    telefono_norm          TEXT,
                    nombre                 TEXT,
                    email                  TEXT,
                    dni                    TEXT,
                    proyecto               TEXT,
                    canal                  TEXT,
                    asesor_id              UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                    asesor_nombre          TEXT,
                    estado                 TEXT,
                    seguimiento            TEXT,
                    observaciones          TEXT,
                    ciudad                 TEXT,
                    fecha_ingreso          DATE,
                    fecha_creacion         DATE,
                    fecha_asignacion       DATE,
                    fecha_ultimo_contacto  DATE,
                    lead_crm_id            INT REFERENCES crm.leads(id) ON DELETE SET NULL,
                    origen_tabla           TEXT NOT NULL DEFAULT 'sistema_anterior',
                    migrado_en             TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

                CREATE TABLE IF NOT EXISTS crm_legacy.cargas_historico_historial (
                    id                  BIGSERIAL PRIMARY KEY,
                    uploaded_by         UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                    uploaded_by_nombre  TEXT,
                    filename            TEXT,
                    total_rows          INT NOT NULL DEFAULT 0,
                    inserted            INT NOT NULL DEFAULT 0,
                    duplicates          INT NOT NULL DEFAULT 0,
                    promoted_to_crm     INT NOT NULL DEFAULT 0,
                    errors              INT NOT NULL DEFAULT 0,
                    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                ALTER TABLE crm_legacy.cargas_historico_historial
                    ADD COLUMN IF NOT EXISTS duplicates_details JSONB DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS error_details JSONB DEFAULT '[]'::jsonb;

                ALTER TABLE crm_legacy.leads_historico
                    ADD COLUMN IF NOT EXISTS es_duplicado BOOLEAN NOT NULL DEFAULT FALSE;

                ALTER TABLE crm_legacy.leads_historico
                    ADD COLUMN IF NOT EXISTS duplicado_con_lead_id INT REFERENCES crm.leads(id) ON DELETE SET NULL;

                ALTER TABLE crm_legacy.leads_historico
                    ADD COLUMN IF NOT EXISTS duplicado_motivo TEXT;

                CREATE INDEX IF NOT EXISTS idx_leads_historico_es_duplicado
                    ON crm_legacy.leads_historico (es_duplicado);

                CREATE INDEX IF NOT EXISTS idx_leads_historico_lead_crm_id
                    ON crm_legacy.leads_historico (lead_crm_id);

                INSERT INTO crm.fuentes (nombre, activo)
                VALUES ('Historico', TRUE)
                ON CONFLICT (nombre) DO UPDATE SET activo = TRUE;
            """)
        conn.commit()
        _schema_ensured = True
    except Exception as exc:
        conn.rollback()
        logger.warning("Historicos schema auto-ensure: %s", exc)


# ── Limpieza y validaciones ───────────────────────────────────────────────────

def _get_or_create_fuente_historico(cur) -> int | None:
    """Obtiene o crea la fuente 'Historico' en crm.fuentes para leads promovidos."""
    cur.execute("SELECT id FROM crm.fuentes WHERE LOWER(nombre) IN ('historico', 'histórico') LIMIT 1")
    frow = cur.fetchone()
    if frow:
        return frow["id"]
    try:
        cur.execute(
            "INSERT INTO crm.fuentes (nombre, activo) VALUES ('Historico', TRUE) "
            "ON CONFLICT (nombre) DO UPDATE SET activo = TRUE RETURNING id"
        )
        frow = cur.fetchone()
        return frow["id"] if frow else None
    except Exception as exc:
        logger.warning("[historicos] Error asegurando fuente 'Historico': %s", exc)
        cur.execute("SELECT id FROM crm.fuentes WHERE activo = TRUE ORDER BY id ASC LIMIT 1")
        frow = cur.fetchone()
        return frow["id"] if frow else None

def _clean_phone(raw) -> str | None:
    if raw is None:
        return None
    s = re.sub(r'[\s\-\(\)\.]+', '', str(raw).strip())
    digits = re.sub(r'\D', '', s)
    if not digits or set(digits) == {'0'}:
        return None
    if len(digits) == 9:
        return '+51' + digits
    if len(digits) == 11 and digits.startswith('51'):
        return '+' + digits
    if 7 <= len(digits) <= 15:
        return digits
    return None


def _clean_email(raw) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lower()
    if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', s):
        return s
    return None


def _clean_text(raw, max_len: int = 250) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()[:max_len]
    return s or None


_FECHA_FORMATS: tuple[str, ...] = (
    '%Y-%m-%d',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S',
    '%d/%m/%Y',
    '%d/%m/%Y %H:%M:%S',
    '%d-%m-%Y',
    '%Y/%m/%d',
)


def _clean_fecha(raw) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _FECHA_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_match_str(s: str | None) -> str:
    if not s:
        return ""
    import unicodedata
    nfkd = unicodedata.normalize('NFKD', str(s))
    no_accents = ''.join([c for c in nfkd if not unicodedata.combining(c)])
    return re.sub(r'[\s\.\-_]+', ' ', no_accents.lower().strip())


def _split_names(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if not parts:
        return ('Sin nombre', '')
    if len(parts) == 1:
        return (parts[0], '')
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (' '.join(parts[:-2]), ' '.join(parts[-2:]))


def _apply_map(raw_row: dict, col_map: dict) -> dict:
    return {
        key: raw_row.get(file_col)
        for key, file_col in col_map.items()
        if file_col
    }


def _parse_file(content: bytes, filename: str) -> tuple[list[str], list[dict]]:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('xlsx', 'xls'):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(400, "No se pudo abrir el archivo Excel.")
        ws = wb.active
        rows_gen = ws.iter_rows(values_only=True)
        raw_headers = next(rows_gen, None)
        if not raw_headers:
            return [], []
        columns = [str(c).strip() for c in raw_headers if c is not None]
        rows = []
        for r in rows_gen:
            if not any(r):
                continue
            row_dict = {}
            for col_idx, h in enumerate(columns):
                row_dict[h] = r[col_idx] if col_idx < len(r) else None
            rows.append(row_dict)
        return columns, rows
    elif ext == 'csv':
        import csv
        text = content.decode('utf-8', errors='replace')
        dialect = csv.Sniffer().sniff(text[:2048]) if len(text) > 10 else csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        columns = reader.fieldnames or []
        rows = list(reader)
        return columns, rows
    raise HTTPException(400, "Formato no soportado. Usa .xlsx, .xls o .csv")


# ── Promoción de Lead a crm.leads al Asignarse ───────────────────────────────

def _promote_historico_to_crm(
    cur,
    lead_hist_id: int,
    target_asesor_id: str,
    target_asesor_nombre: str,
    nombres_hint: str | None = None,
    apellidos_hint: str | None = None,
    fuente_id_hint: int | None = None,
    estado_id_hint: int | None = None,
    trabajo_hint: str | None = None,
    referido_por_hint: str | None = None,
    codigo_convenio_hint: str | None = None,
) -> int | None:
    """Crea o actualiza el registro en crm.leads para que aparezca en el pipeline /leads."""
    cur.execute(
        """
        SELECT id, nombre, telefono, telefono_norm, email, dni,
               proyecto, canal, asesor_id, asesor_nombre, estado,
               observaciones, ciudad, fecha_ingreso, fecha_creacion,
               fecha_asignacion, fecha_ultimo_contacto, lead_crm_id
        FROM crm_legacy.leads_historico
        WHERE id = %s
        FOR UPDATE
        """,
        (lead_hist_id,),
    )
    hist = cur.fetchone()
    if not hist:
        return None

    fuente_id = fuente_id_hint or _get_or_create_fuente_historico(cur)

    if hist.get("lead_crm_id"):
        cur.execute(
            """
            UPDATE crm.leads
            SET asesor_id = %s::uuid,
                fuente_id = COALESCE(%s, fuente_id),
                activo = TRUE,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (target_asesor_id, fuente_id, hist["lead_crm_id"]),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE crm_legacy.leads_historico
                SET asesor_id = %s::uuid,
                    asesor_nombre = %s
                WHERE id = %s
                """,
                (target_asesor_id, target_asesor_nombre, lead_hist_id),
            )
            return row["id"]

    if nombres_hint or apellidos_hint:
        nombres = (nombres_hint or "").strip() or "Sin nombre"
        apellidos = (apellidos_hint or "").strip()
    else:
        nombres, apellidos = _split_names(hist.get("nombre") or "Sin nombre")

    estado_id = estado_id_hint
    if not estado_id:
        if hist.get("estado"):
            cur.execute("SELECT id FROM crm.estados_lead WHERE nombre ILIKE %s LIMIT 1", (f"%{hist['estado'].strip()}%",))
            erow = cur.fetchone()
            if erow:
                estado_id = erow["id"]
        if not estado_id:
            cur.execute("SELECT id FROM crm.estados_lead WHERE nombre ILIKE 'Nuevo' LIMIT 1")
            erow = cur.fetchone()
            if not erow:
                cur.execute("SELECT id FROM crm.estados_lead ORDER BY orden ASC, id ASC LIMIT 1")
                erow = cur.fetchone()
            estado_id = erow["id"] if erow else None

    created_at_val = hist.get("fecha_creacion") or hist.get("fecha_ingreso") or date.today()

    cur.execute(
        """
        INSERT INTO crm.leads (
            fuente_id, estado_id, asesor_id,
            nombres, apellidos, telefono, email, dni,
            ciudad, trabajo, campana, proyecto,
            referido_por, codigo_convenio, observaciones,
            created_at, activo
        )
        VALUES (
            %s, %s, %s::uuid,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, TRUE
        )
        RETURNING id
        """,
        (
            fuente_id,
            estado_id,
            target_asesor_id,
            nombres,
            apellidos,
            hist.get("telefono") or hist.get("telefono_norm"),
            hist.get("email"),
            hist.get("dni"),
            hist.get("ciudad"),
            trabajo_hint,
            hist.get("proyecto"),
            hist.get("proyecto"),
            referido_por_hint,
            codigo_convenio_hint,
            hist.get("observaciones"),
            created_at_val,
        ),
    )
    crm_lead = cur.fetchone()
    crm_id = crm_lead["id"] if crm_lead else None

    cur.execute(
        """
        UPDATE crm_legacy.leads_historico
        SET asesor_id = %s::uuid,
            asesor_nombre = %s,
            lead_crm_id = %s
        WHERE id = %s
        """,
        (target_asesor_id, target_asesor_nombre, crm_id, lead_hist_id),
    )
    return crm_id


# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class CreateLeadHistoricoRequest(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: str
    email: Optional[str] = None
    tipo_documento: Optional[str] = "DNI"
    dni: Optional[str] = None
    campana: Optional[str] = None
    proyecto: Optional[str] = None
    canal: Optional[str] = None
    observaciones: Optional[str] = None
    ciudad: Optional[str] = None
    trabajo: Optional[str] = None
    fuente_id: Optional[int] = None
    fuente: Optional[str] = None
    estado_id: Optional[int] = None
    estado: Optional[str] = None
    estado_lead: Optional[str] = None
    asesor_id: Optional[str] = None
    referido_por: Optional[str] = None
    codigo_convenio: Optional[str] = None
    fecha_ingreso: Optional[str] = None
    fecha_creacion: Optional[str] = None
    fecha_asignacion: Optional[str] = None
    fecha_ultimo_contacto: Optional[str] = None
    allow_duplicate: Optional[bool] = False
    duplicate_reason: Optional[str] = None


class ReasignarHistoricosRequest(BaseModel):
    lead_ids: list[int] = Field(..., min_items=1)
    asesor_id: Optional[str] = None


class DeleteHistoricosRequest(BaseModel):
    lead_ids: list[int] = Field(..., min_items=1)


class DevolverHistoricosRequest(BaseModel):
    lead_ids: list[int] = Field(..., min_items=1)


# ── Check de Duplicados (CRM + Histórico) ───────────────────────────────────

@router.get("/check-duplicate")
def check_duplicate_historicos(
    telefono: Optional[str] = None,
    email: Optional[str] = None,
    dni: Optional[str] = None,
    current_user: TokenData = Depends(require_admin),
):
    if not (telefono or email or dni):
        return {"match": None, "match_field": None, "match_source": None}

    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Chequear en crm.leads (CRM Activo)
            if telefono:
                tel = telefono.strip()
                cur.execute(
                    """
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
                    ORDER BY (l.asesor_id IS NOT NULL) DESC, l.created_at DESC
                    LIMIT 1
                    """,
                    [tel, tel],
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "telefono", "match_source": "crm"}

            if email:
                em = email.strip().lower()
                cur.execute(
                    """
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
                    LIMIT 1
                    """,
                    [em],
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "email", "match_source": "crm"}

            if dni:
                d = dni.strip()
                cur.execute(
                    """
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
                    LIMIT 1
                    """,
                    [d],
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "dni", "match_source": "crm"}

            # 2. Chequear en crm_legacy.leads_historico (Histórico)
            if telefono:
                tel = telefono.strip()
                cur.execute(
                    """
                    SELECT
                        h.id, h.nombre AS nombres, '' AS apellidos, h.telefono, h.email,
                        h.asesor_id::text AS asesor_id,
                        COALESCE(
                            NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''),
                            NULLIF(TRIM(h.asesor_nombre), ''),
                            '—'
                        ) AS asesor_nombre,
                        h.estado AS estado_nombre,
                        COALESCE(h.fecha_creacion, h.fecha_ingreso)::text AS created_at
                    FROM crm_legacy.leads_historico h
                    LEFT JOIN auth.users u ON u.id = h.asesor_id
                    WHERE RIGHT(REGEXP_REPLACE(COALESCE(h.telefono, ''), '\\D', '', 'g'), 9)
                        = RIGHT(REGEXP_REPLACE(%s, '\\D', '', 'g'), 9)
                      AND LENGTH(REGEXP_REPLACE(COALESCE(h.telefono, ''), '\\D', '', 'g')) >= 9
                      AND LENGTH(REGEXP_REPLACE(%s, '\\D', '', 'g')) >= 9
                    ORDER BY h.fecha_ingreso DESC NULLS LAST, h.id DESC
                    LIMIT 1
                    """,
                    [tel, tel],
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "telefono", "match_source": "historico"}

            if email:
                em = email.strip().lower()
                cur.execute(
                    """
                    SELECT
                        h.id, h.nombre AS nombres, '' AS apellidos, h.telefono, h.email,
                        h.asesor_id::text AS asesor_id,
                        COALESCE(
                            NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''),
                            NULLIF(TRIM(h.asesor_nombre), ''),
                            '—'
                        ) AS asesor_nombre,
                        h.estado AS estado_nombre,
                        COALESCE(h.fecha_creacion, h.fecha_ingreso)::text AS created_at
                    FROM crm_legacy.leads_historico h
                    LEFT JOIN auth.users u ON u.id = h.asesor_id
                    WHERE LOWER(h.email) = %s
                    LIMIT 1
                    """,
                    [em],
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "email", "match_source": "historico"}

            if dni:
                d = dni.strip()
                cur.execute(
                    """
                    SELECT
                        h.id, h.nombre AS nombres, '' AS apellidos, h.telefono, h.email,
                        h.asesor_id::text AS asesor_id,
                        COALESCE(
                            NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''),
                            NULLIF(TRIM(h.asesor_nombre), ''),
                            '—'
                        ) AS asesor_nombre,
                        h.estado AS estado_nombre,
                        COALESCE(h.fecha_creacion, h.fecha_ingreso)::text AS created_at
                    FROM crm_legacy.leads_historico h
                    LEFT JOIN auth.users u ON u.id = h.asesor_id
                    WHERE h.dni = %s
                    LIMIT 1
                    """,
                    [d],
                )
                row = cur.fetchone()
                if row:
                    return {"match": dict(row), "match_field": "dni", "match_source": "historico"}

    return {"match": None, "match_field": None, "match_source": None}


# ── Endpoints de Listado y Métricas ──────────────────────────────────────────

@router.get("")
def list_historicos(
    tab: Optional[str] = "sin_asignar",
    search: Optional[str] = None,
    mes: Optional[str] = None,
    proyecto: Optional[str] = None,
    canal: Optional[str] = None,
    estado: Optional[str] = None,
    asesor_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: TokenData = Depends(require_admin),
):
    """Lista leads históricos con desglose mensual, filtros, 3 pestañas y paginación fija de 50."""
    where_parts = []
    params = []

    # Filtrado por pestaña principal (V105)
    tab_norm = (tab or "sin_asignar").strip().lower()
    if tab_norm == "sin_asignar":
        where_parts.append("(h.es_duplicado IS NOT TRUE) AND (h.lead_crm_id IS NULL OR cl.id IS NULL OR cl.activo = FALSE OR h.asesor_id IS NULL)")
    elif tab_norm == "asignados":
        where_parts.append("(h.lead_crm_id IS NOT NULL AND cl.id IS NOT NULL AND cl.activo = TRUE AND cl.merged_into IS NULL AND h.asesor_id IS NOT NULL)")
    elif tab_norm == "duplicados":
        where_parts.append("(h.es_duplicado IS TRUE)")
    # 'todos' no aplica filtro de tab

    if mes and mes.strip() and mes.strip().lower() != "todos":
        where_parts.append("TO_CHAR(COALESCE(h.fecha_creacion, h.fecha_ingreso), 'YYYY-MM') = %s")
        params.append(mes.strip())

    if search:
        search_clean = search.strip()
        digits = re.sub(r'\D', '', search_clean)
        if digits and len(digits) >= 4:
            where_parts.append("h.telefono_norm LIKE %s")
            params.append(f"%{digits[-9:]}%")
        else:
            tokens = [t for t in search_clean.split() if t]
            if len(tokens) <= 1:
                where_parts.append("(h.nombre ILIKE %s OR h.email ILIKE %s OR h.dni ILIKE %s OR h.asesor_nombre ILIKE %s)")
                term = f"%{search_clean}%"
                params.extend([term, term, term, term])
            else:
                token_clauses = []
                for tok in tokens:
                    token_clauses.append("(h.nombre ILIKE %s OR h.email ILIKE %s OR h.dni ILIKE %s OR h.asesor_nombre ILIKE %s)")
                    tterm = f"%{tok}%"
                    params.extend([tterm, tterm, tterm, tterm])
                where_parts.append("(" + " AND ".join(token_clauses) + ")")

    if proyecto:
        where_parts.append("h.proyecto ILIKE %s")
        params.append(f"%{proyecto.strip()}%")

    if canal:
        where_parts.append("h.canal ILIKE %s")
        params.append(f"%{canal.strip()}%")

    if estado:
        where_parts.append("h.estado ILIKE %s")
        params.append(f"%{estado.strip()}%")

    if asesor_id:
        if asesor_id == "sin_asesor":
            where_parts.append("h.asesor_id IS NULL AND (h.asesor_nombre IS NULL OR h.asesor_nombre = '')")
        elif asesor_id == "asesor_no_registrado":
            where_parts.append("h.asesor_id IS NULL AND h.asesor_nombre IS NOT NULL AND h.asesor_nombre != ''")
        else:
            where_parts.append("h.asesor_id = %s::uuid")
            params.append(asesor_id)

    where_sql = " AND ".join(where_parts) if where_parts else "TRUE"

    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM crm_legacy.leads_historico h
                LEFT JOIN crm.leads cl ON cl.id = h.lead_crm_id
                WHERE {where_sql}
                """,
                params,
            )
            total = (cur.fetchone() or {}).get("total", 0)

            cur.execute(
                f"""
                SELECT
                    h.id, h.nombre, h.telefono, h.email, h.dni,
                    h.proyecto, h.canal,
                    h.asesor_id::text AS asesor_id,
                    COALESCE(
                        NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''),
                        NULLIF(TRIM(h.asesor_nombre), ''),
                        '—'
                    ) AS asesor_nombre,
                    (u.id IS NOT NULL) AS asesor_is_registered,
                    h.estado, h.seguimiento, h.observaciones,
                    h.ciudad,
                    COALESCE(h.fecha_creacion, h.fecha_ingreso)::text AS fecha_creacion,
                    h.fecha_asignacion::text AS fecha_asignacion,
                    h.fecha_ultimo_contacto::text AS fecha_ultimo_contacto,
                    h.fecha_ingreso::text AS fecha_ingreso,
                    h.lead_crm_id,
                    COALESCE(cl.activo, FALSE) AS lead_crm_activo,
                    h.origen_tabla,
                    COALESCE(h.es_duplicado, FALSE) AS es_duplicado,
                    h.duplicado_con_lead_id,
                    h.duplicado_motivo
                FROM crm_legacy.leads_historico h
                LEFT JOIN auth.users u ON u.id = h.asesor_id
                LEFT JOIN crm.leads cl ON cl.id = h.lead_crm_id
                WHERE {where_sql}
                ORDER BY COALESCE(h.fecha_creacion, h.fecha_ingreso) DESC NULLS LAST, h.id DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            items = cur.fetchall()

    return {
        "total": total,
        "items": items,
        "page_size": limit,
        "offset": offset,
        "tab": tab_norm,
    }


@router.get("/meses")
def list_meses(
    current_user: TokenData = Depends(require_admin),
):
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    TO_CHAR(COALESCE(fecha_creacion, fecha_ingreso), 'YYYY-MM') AS mes,
                    COUNT(*) AS count
                FROM crm_legacy.leads_historico
                WHERE COALESCE(fecha_creacion, fecha_ingreso) IS NOT NULL
                GROUP BY TO_CHAR(COALESCE(fecha_creacion, fecha_ingreso), 'YYYY-MM')
                ORDER BY mes DESC
                """
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*) AS total_sin_fecha
                FROM crm_legacy.leads_historico
                WHERE COALESCE(fecha_creacion, fecha_ingreso) IS NULL
                """
            )
            sin_fecha_count = (cur.fetchone() or {}).get("total_sin_fecha", 0)

    meses = []
    for r in rows:
        m = r["mes"]
        try:
            year, month = int(m[:4]), int(m[5:7])
            label = f"{MONTH_NAMES_ES.get(month, '')} {year}"
        except Exception:
            label = m
        meses.append({
            "mes": m,
            "label": label,
            "count": r["count"],
        })

    if sin_fecha_count > 0:
        meses.append({
            "mes": "sin_fecha",
            "label": "Sin fecha definida",
            "count": sin_fecha_count,
        })

    return {"meses": meses}


@router.get("/filtros")
def historicos_filtros(
    current_user: TokenData = Depends(require_admin),
):
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT proyecto FROM crm_legacy.leads_historico
                WHERE proyecto IS NOT NULL AND proyecto != ''
                ORDER BY proyecto
            """)
            proyectos = [r["proyecto"] for r in cur.fetchall()]

            cur.execute("""
                SELECT DISTINCT canal FROM crm_legacy.leads_historico
                WHERE canal IS NOT NULL AND canal != ''
                ORDER BY canal
            """)
            canales = [r["canal"] for r in cur.fetchall()]

            cur.execute("""
                SELECT DISTINCT estado FROM crm_legacy.leads_historico
                WHERE estado IS NOT NULL AND estado != ''
                ORDER BY estado
            """)
            estados = [r["estado"] for r in cur.fetchall()]

    return {"proyectos": proyectos, "canales": canales, "estados": estados}


@router.get("/stats")
def historicos_stats(
    current_user: TokenData = Depends(require_admin),
):
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(DISTINCT h.id) AS total,
                    COUNT(DISTINCT h.id) FILTER (
                        WHERE (h.es_duplicado IS NOT TRUE)
                          AND (h.lead_crm_id IS NULL OR cl.id IS NULL OR cl.activo = FALSE OR h.asesor_id IS NULL)
                    ) AS sin_asignar,
                    COUNT(DISTINCT h.id) FILTER (
                        WHERE h.lead_crm_id IS NOT NULL
                          AND cl.id IS NOT NULL
                          AND cl.activo = TRUE
                          AND cl.merged_into IS NULL
                          AND h.asesor_id IS NOT NULL
                    ) AS asignados,
                    COUNT(DISTINCT h.id) FILTER (
                        WHERE h.es_duplicado IS TRUE
                    ) AS duplicados,
                    COUNT(DISTINCT h.telefono_norm) AS telefonos_unicos,
                    COUNT(DISTINCT h.proyecto) FILTER (WHERE h.proyecto IS NOT NULL AND h.proyecto != '') AS proyectos,
                    COUNT(DISTINCT h.id) FILTER (
                        WHERE cl.id IS NOT NULL
                          AND cl.activo = TRUE
                          AND cl.merged_into IS NULL
                          AND cl.asesor_id IS NOT NULL
                    ) AS asignados_crm,
                    COUNT(DISTINCT h.id) FILTER (
                        WHERE h.asesor_id IS NULL AND h.asesor_nombre IS NOT NULL AND h.asesor_nombre != ''
                    ) AS no_registrados
                FROM crm_legacy.leads_historico h
                LEFT JOIN crm.leads cl ON cl.id = h.lead_crm_id
            """)
            return cur.fetchone() or {}


@router.get("/asesores")
def list_asesores_para_historicos(
    current_user: TokenData = Depends(require_admin),
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    id::text AS id,
                    TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre,
                    email,
                    role
                FROM auth.users
                WHERE is_active = TRUE AND role IN ('asesor', 'supervisor', 'admin')
                ORDER BY role, first_name, last_name
                """
            )
            return {"asesores": cur.fetchall()}


# ── Creación Individual ───────────────────────────────────────────────────────

@router.post("")
def create_lead_historico(
    body: CreateLeadHistoricoRequest,
    current_user: TokenData = Depends(require_admin),
):
    """Crea un lead individual en crm_legacy.leads_historico y, si se asigna asesor, en crm.leads."""
    nombres_part = (body.nombres or "").strip()
    apellidos_part = (body.apellidos or "").strip()
    if not nombres_part and not apellidos_part:
        raise HTTPException(400, "Se requiere al menos nombre o apellido.")

    full_name = f"{nombres_part} {apellidos_part}".strip()

    tel_clean = _clean_phone(body.telefono)
    if not tel_clean:
        raise HTTPException(400, "Teléfono inválido. Ingrese un número válido de al menos 7 dígitos.")

    email_clean = _clean_email(body.email)
    dni_clean = _clean_text(body.dni, 20)

    # Fechas
    fecha_creacion_dt = _clean_fecha(body.fecha_creacion) or _clean_fecha(body.fecha_ingreso) or date.today()
    fecha_asignacion_dt = _clean_fecha(body.fecha_asignacion)
    fecha_ultimo_contacto_dt = _clean_fecha(body.fecha_ultimo_contacto)

    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── Check de duplicados ──
            if not body.allow_duplicate:
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
                    WHERE RIGHT(REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g'), 9)
                        = RIGHT(REGEXP_REPLACE(%s, '\\D', '', 'g'), 9)
                      AND l.activo = TRUE AND l.merged_into IS NULL
                    LIMIT 1
                    """,
                    (tel_clean,),
                )
                existing_crm = cur.fetchone()
                if existing_crm:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "duplicate_lead",
                            "message": "Ya existe un lead activo en el CRM con este teléfono.",
                            "existing_lead": dict(existing_crm),
                            "match_source": "crm",
                            "can_override": True,
                        },
                    )

                cur.execute(
                    """
                    SELECT
                        h.id, h.nombre AS nombres, '' AS apellidos, h.telefono, h.email,
                        h.asesor_id::text AS asesor_id,
                        h.asesor_nombre,
                        h.estado AS estado_nombre
                    FROM crm_legacy.leads_historico h
                    WHERE RIGHT(REGEXP_REPLACE(COALESCE(h.telefono, ''), '\\D', '', 'g'), 9)
                        = RIGHT(REGEXP_REPLACE(%s, '\\D', '', 'g'), 9)
                    LIMIT 1
                    """,
                    (tel_clean,),
                )
                existing_hist = cur.fetchone()
                if existing_hist:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "duplicate_lead",
                            "message": "Ya existe un lead en Históricos con este teléfono.",
                            "existing_lead": dict(existing_hist),
                            "match_source": "historico",
                            "can_override": True,
                        },
                    )

            # Resolver nombre de canal/fuente y estado
            canal_nombre = body.canal or body.fuente
            estado_nombre = body.estado_lead or body.estado or "Historico"
            proyecto_nombre = body.campana or body.proyecto

            if body.fuente_id:
                cur.execute("SELECT nombre FROM crm.fuentes WHERE id = %s", (body.fuente_id,))
                f_row = cur.fetchone()
                if f_row:
                    canal_nombre = f_row["nombre"]

            if body.estado_id:
                cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (body.estado_id,))
                e_row = cur.fetchone()
                if e_row:
                    estado_nombre = e_row["nombre"]

            asesor_id_val = None
            asesor_nombre = None
            if body.asesor_id and body.asesor_id not in ("unassign", "pool"):
                cur.execute(
                    """
                    SELECT id::text, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre
                    FROM auth.users WHERE id = %s::uuid AND is_active = TRUE
                    """,
                    (body.asesor_id,),
                )
                u_row = cur.fetchone()
                if u_row:
                    asesor_id_val = u_row["id"]
                    asesor_nombre = u_row["nombre"]

            extras = []
            if body.trabajo:
                extras.append(f"Trabajo: {body.trabajo.strip()}")
            if body.referido_por:
                extras.append(f"Referido por: {body.referido_por.strip()}")
            if body.codigo_convenio:
                extras.append(f"Convenio: {body.codigo_convenio.strip()}")
            if body.observaciones:
                extras.append(body.observaciones.strip())
            obs_final = " | ".join(extras) if extras else None

            cur.execute(
                """
                INSERT INTO crm_legacy.leads_historico (
                    nombre, telefono, telefono_norm, email, dni,
                    proyecto, canal, asesor_id, asesor_nombre,
                    estado, observaciones, ciudad,
                    fecha_ingreso, fecha_creacion, fecha_asignacion, fecha_ultimo_contacto,
                    origen_tabla
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s::uuid, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    'individual'
                )
                RETURNING id, nombre, telefono, email, dni, proyecto, canal,
                          asesor_id::text AS asesor_id, asesor_nombre, estado,
                          ciudad, fecha_creacion::text, fecha_asignacion::text,
                          fecha_ultimo_contacto::text, origen_tabla
                """,
                (
                    full_name,
                    tel_clean,
                    tel_clean,
                    email_clean,
                    dni_clean,
                    _clean_text(proyecto_nombre, 150),
                    _clean_text(canal_nombre, 100),
                    asesor_id_val,
                    asesor_nombre,
                    _clean_text(estado_nombre, 100),
                    _clean_text(obs_final, 1000),
                    _clean_text(body.ciudad, 100),
                    fecha_creacion_dt,
                    fecha_creacion_dt,
                    fecha_asignacion_dt,
                    fecha_ultimo_contacto_dt,
                ),
            )
            created = cur.fetchone()
            crm_id = None

        conn.commit()

    return {
        "message": "Lead histórico creado exitosamente",
        "lead": created,
        "promoted_to_crm_id": None,
    }


# ── Reasignación y Promoción a /leads con Control de Duplicados ────────────

@router.post("/reasignar")
def reasignar_historicos(
    body: ReasignarHistoricosRequest,
    current_user: TokenData = Depends(require_admin),
):
    if not body.lead_ids:
        raise HTTPException(400, "Debe seleccionar al menos un lead histórico para reasignar.")

    asesor_id_val = None
    asesor_nombre = None

    if body.asesor_id and body.asesor_id not in ("unassign", "pool"):
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id::text, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre
                    FROM auth.users WHERE id = %s::uuid AND is_active = TRUE
                    """,
                    (body.asesor_id,),
                )
                user_row = cur.fetchone()
                if not user_row:
                    raise HTTPException(404, "El asesor seleccionado no existe o está inactivo.")
                asesor_id_val = user_row["id"]
                asesor_nombre = user_row["nombre"]

    promoted_count = 0
    duplicates_list = []

    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if asesor_id_val:
                for lid in body.lead_ids:
                    # 1. Obtener datos del lead histórico
                    cur.execute(
                        """
                        SELECT id, nombre, telefono, telefono_norm, email, dni, lead_crm_id
                        FROM crm_legacy.leads_historico
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (lid,),
                    )
                    hist = cur.fetchone()
                    if not hist:
                        continue

                    # 2. Check si existe duplicidad con un lead activo existente en crm.leads
                    # (excluyendo el propio lead_crm_id si ya fue promovido previamente a ese mismo)
                    duplicate_match = None
                    match_reason = None
                    match_field = None

                    tel = hist.get("telefono") or hist.get("telefono_norm")
                    if tel:
                        tel_clean = re.sub(r'\D', '', str(tel))
                        if len(tel_clean) >= 7:
                            cur.execute(
                                """
                                SELECT 
                                    l.id, l.nombres, l.apellidos, l.telefono, l.email, l.dni,
                                    l.asesor_id::text AS asesor_id,
                                    (SELECT TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
                                     FROM auth.users u WHERE u.id = l.asesor_id) AS asesor_nombre,
                                    e.nombre AS estado_nombre,
                                    l.created_at::text AS created_at
                                FROM crm.leads l
                                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                                WHERE RIGHT(REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g'), 9) = RIGHT(%s, 9)
                                  AND LENGTH(REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g')) >= 7
                                  AND l.activo = TRUE
                                  AND l.merged_into IS NULL
                                  AND (%s IS NULL OR l.id != %s)
                                LIMIT 1
                                """,
                                (tel_clean, hist.get("lead_crm_id"), hist.get("lead_crm_id")),
                            )
                            match = cur.fetchone()
                            if match:
                                duplicate_match = match
                                match_field = "teléfono"
                                match_reason = f"Teléfono ({tel}) coincide con Lead activo #{match['id']}"

                    if not duplicate_match and hist.get("email") and hist.get("email").strip():
                        em_clean = hist["email"].strip().lower()
                        cur.execute(
                            """
                            SELECT 
                                l.id, l.nombres, l.apellidos, l.telefono, l.email, l.dni,
                                l.asesor_id::text AS asesor_id,
                                (SELECT TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
                                 FROM auth.users u WHERE u.id = l.asesor_id) AS asesor_nombre,
                                e.nombre AS estado_nombre,
                                l.created_at::text AS created_at
                            FROM crm.leads l
                            LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                            WHERE LOWER(l.email) = %s
                              AND l.activo = TRUE
                              AND l.merged_into IS NULL
                              AND (%s IS NULL OR l.id != %s)
                            LIMIT 1
                            """,
                            (em_clean, hist.get("lead_crm_id"), hist.get("lead_crm_id")),
                        )
                        match = cur.fetchone()
                        if match:
                            duplicate_match = match
                            match_field = "email"
                            match_reason = f"Email ({em_clean}) coincide con Lead activo #{match['id']}"

                    if not duplicate_match and hist.get("dni") and hist.get("dni").strip():
                        dni_clean = hist["dni"].strip()
                        cur.execute(
                            """
                            SELECT 
                                l.id, l.nombres, l.apellidos, l.telefono, l.email, l.dni,
                                l.asesor_id::text AS asesor_id,
                                (SELECT TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
                                 FROM auth.users u WHERE u.id = l.asesor_id) AS asesor_nombre,
                                e.nombre AS estado_nombre,
                                l.created_at::text AS created_at
                            FROM crm.leads l
                            LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                            WHERE l.dni = %s
                              AND l.activo = TRUE
                              AND l.merged_into IS NULL
                              AND (%s IS NULL OR l.id != %s)
                            LIMIT 1
                            """,
                            (dni_clean, hist.get("lead_crm_id"), hist.get("lead_crm_id")),
                        )
                        match = cur.fetchone()
                        if match:
                            duplicate_match = match
                            match_field = "DNI"
                            match_reason = f"DNI ({dni_clean}) coincide con Lead activo #{match['id']}"

                    if duplicate_match:
                        # Marcar histórico como duplicado y OMITIR la asignación/promoción
                        cur.execute(
                            """
                            UPDATE crm_legacy.leads_historico
                            SET es_duplicado = TRUE,
                                duplicado_con_lead_id = %s,
                                duplicado_motivo = %s
                            WHERE id = %s
                            """,
                            (duplicate_match["id"], match_reason, lid),
                        )
                        dup_nombre = f"{duplicate_match['nombres'] or ''} {duplicate_match['apellidos'] or ''}".strip() or "Lead sin nombre"
                        duplicates_list.append({
                            "historico_id": lid,
                            "nombre": hist.get("nombre") or "Sin nombre",
                            "telefono": hist.get("telefono") or "—",
                            "email": hist.get("email") or "—",
                            "crm_lead_id": duplicate_match["id"],
                            "crm_lead_nombre": dup_nombre,
                            "crm_asesor_nombre": duplicate_match["asesor_nombre"] or "Sin asesor",
                            "crm_estado_nombre": duplicate_match["estado_nombre"] or "—",
                            "match_field": match_field,
                            "motivo": match_reason,
                        })
                    else:
                        # Limpiar flag de duplicado si existía y promover/asignar normalmente
                        cur.execute(
                            """
                            UPDATE crm_legacy.leads_historico
                            SET es_duplicado = FALSE,
                                duplicado_con_lead_id = NULL,
                                duplicado_motivo = NULL
                            WHERE id = %s
                            """,
                            (lid,),
                        )
                        crm_id = _promote_historico_to_crm(cur, lid, asesor_id_val, asesor_nombre)
                        if crm_id:
                            promoted_count += 1
            else:
                # Obtener leads_crm_id y asesores anteriores para auditoría antes de desasignar
                cur.execute(
                    """
                    SELECT h.id AS hist_id, h.lead_crm_id, l.asesor_id AS crm_asesor_id
                    FROM crm_legacy.leads_historico h
                    LEFT JOIN crm.leads l ON l.id = h.lead_crm_id
                    WHERE h.id = ANY(%s)
                    """,
                    (body.lead_ids,),
                )
                rows = cur.fetchall()

                cur.execute(
                    """
                    UPDATE crm_legacy.leads_historico
                    SET asesor_id = NULL,
                        asesor_nombre = NULL
                    WHERE id = ANY(%s)
                    """,
                    (body.lead_ids,),
                )
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET asesor_id = NULL,
                        activo = FALSE,
                        updated_at = NOW()
                    WHERE id IN (
                        SELECT lead_crm_id FROM crm_legacy.leads_historico
                        WHERE id = ANY(%s) AND lead_crm_id IS NOT NULL
                    )
                    """,
                    (body.lead_ids,),
                )
                cur.execute(
                    """
                    UPDATE crm.wa_conversations
                    SET asesor_id = NULL
                    WHERE lead_id IN (
                        SELECT lead_crm_id FROM crm_legacy.leads_historico
                        WHERE id = ANY(%s) AND lead_crm_id IS NOT NULL
                    )
                    """,
                    (body.lead_ids,),
                )

                for r in rows:
                    if r.get("lead_crm_id") and r.get("crm_asesor_id"):
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
                                NULL,
                                %s::uuid,
                                'historicos:quitar_asignacion'
                            )
                            """,
                            (r["lead_crm_id"], r["crm_asesor_id"], current_user.user_id),
                        )
        conn.commit()

    if asesor_id_val:
        if duplicates_list and promoted_count > 0:
            msg = f"Se asignaron {promoted_count} lead(s) a {asesor_nombre}. Se omitieron {len(duplicates_list)} lead(s) por duplicidad con leads ya existentes en el CRM."
        elif duplicates_list and promoted_count == 0:
            msg = f"No se asignaron leads: los {len(duplicates_list)} lead(s) seleccionados ya existen como leads activos en el CRM."
        else:
            msg = f"Se asignaron {promoted_count} lead(s) a {asesor_nombre} exitosamente. Ahora están visibles en la página de Leads."
    else:
        msg = f"Se quitó la asignación de {len(body.lead_ids)} lead(s) histórico(s). Quedan nuevamente en espera de reasignación."

    return {
        "success": True,
        "total_solicitados": len(body.lead_ids),
        "updated": promoted_count if asesor_id_val else len(body.lead_ids),
        "promoted": promoted_count,
        "duplicates_count": len(duplicates_list),
        "duplicates": duplicates_list,
        "asesor_nombre": asesor_nombre or "Sin asesor",
        "message": msg,
    }


@router.post("/devolver-leads")
def devolver_leads_a_historicos(
    body: DevolverHistoricosRequest,
    current_user: TokenData = Depends(require_supervisor_or_admin),
):
    """Devuelve leads desde crm.leads hacia crm_legacy.leads_historico:
    - Quita asesor y supervisor en crm.leads (asesor_id=NULL, supervisor_id=NULL)
    - Quita el lead de la lista activa de Leads (activo=FALSE)
    - En crm_legacy.leads_historico pone asesor_id=NULL, asesor_nombre=NULL
    - Quita asesor de crm.wa_conversations
    - Registra en crm.asignaciones_log
    """
    if not body.lead_ids:
        return {
            "success": True,
            "count": 0,
            "message": "No se enviaron leads para devolver.",
        }

    from app.filters.lead_filters import role_filter
    role_clause, role_params = role_filter(current_user)

    try:
        with get_db() as conn:
            _ensure_schema_if_needed(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Obtener los leads activos autorizados para el usuario
                cur.execute(
                    f"""
                    SELECT l.id, l.nombres, l.apellidos,
                           TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
                           l.telefono, l.email, l.dni, l.ciudad, l.trabajo, l.campana, l.proyecto,
                           l.observaciones, l.asesor_id::text AS asesor_id, l.supervisor_id::text AS supervisor_id,
                           l.created_at, e.nombre AS estado_nombre, f.nombre AS fuente_nombre
                    FROM crm.leads l
                    LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                    LEFT JOIN crm.fuentes f ON f.id = l.fuente_id
                    WHERE l.id = ANY(%s)
                      AND l.activo = TRUE
                      AND ({role_clause})
                    FOR UPDATE OF l
                    """,
                    [body.lead_ids] + role_params,
                )
                leads_to_revert = cur.fetchall()
                if not leads_to_revert:
                    return {
                        "success": True,
                        "count": 0,
                        "message": "No se encontraron leads válidos o con permisos para devolver a Históricos.",
                    }

                valid_ids = [r["id"] for r in leads_to_revert]

                # 2. Actualizar o insertar en crm_legacy.leads_historico
                for lead in leads_to_revert:
                    lid = lead["id"]
                    tel = lead["telefono"]
                    tel_clean = re.sub(r'\D', '', str(tel)) if tel else None
                    created_date = (
                        lead["created_at"].date()
                        if hasattr(lead.get("created_at"), "date")
                        else lead.get("created_at")
                    )

                    # ¿Existe ya vinculado por lead_crm_id?
                    cur.execute(
                        "SELECT id FROM crm_legacy.leads_historico WHERE lead_crm_id = %s LIMIT 1 FOR UPDATE",
                        (lid,),
                    )
                    h_row = cur.fetchone()
                    if h_row:
                        cur.execute(
                            """
                            UPDATE crm_legacy.leads_historico
                            SET asesor_id = NULL,
                                asesor_nombre = NULL
                            WHERE lead_crm_id = %s
                            """,
                            (lid,),
                        )
                    elif tel_clean and len(tel_clean) >= 7:
                        # Buscar por teléfono aprovechando telefono_norm indexado
                        cur.execute(
                            """
                            SELECT id FROM crm_legacy.leads_historico
                            WHERE telefono_norm = %s
                               OR RIGHT(COALESCE(telefono_norm, ''), 9) = RIGHT(%s, 9)
                               OR RIGHT(COALESCE(telefono, ''), 9) = RIGHT(%s, 9)
                            LIMIT 1 FOR UPDATE
                            """,
                            (tel_clean, tel_clean, tel_clean),
                        )
                        h_tel_row = cur.fetchone()
                        if h_tel_row:
                            cur.execute(
                                """
                                UPDATE crm_legacy.leads_historico
                                SET asesor_id = NULL,
                                    asesor_nombre = NULL,
                                    lead_crm_id = %s
                                WHERE id = %s
                                """,
                                (lid, h_tel_row["id"]),
                            )
                        else:
                            # Insertar nuevo histórico
                            cur.execute(
                                """
                                INSERT INTO crm_legacy.leads_historico (
                                    nombre, telefono, telefono_norm, email, dni,
                                    proyecto, canal, asesor_id, asesor_nombre,
                                    estado, observaciones, ciudad,
                                    fecha_ingreso, fecha_creacion,
                                    lead_crm_id, origen_tabla
                                ) VALUES (
                                    %s, %s, %s, %s, %s,
                                    %s, %s, NULL, NULL,
                                    %s, %s, %s,
                                    %s::date, %s::date,
                                    %s, 'devolucion_crm'
                                )
                                """,
                                (
                                    lead["nombre_completo"] or "Sin nombre",
                                    tel,
                                    tel_clean,
                                    lead["email"],
                                    lead["dni"],
                                    _clean_text(lead["proyecto"] or lead["campana"], 150),
                                    _clean_text(lead["fuente_nombre"] or "Historico", 100),
                                    _clean_text(lead["estado_nombre"] or "Historico", 100),
                                    _clean_text(lead["observaciones"], 1000),
                                    _clean_text(lead["ciudad"], 100),
                                    created_date,
                                    created_date,
                                    lid,
                                ),
                            )
                    else:
                        # Sin teléfono: insertar nuevo histórico
                        cur.execute(
                            """
                            INSERT INTO crm_legacy.leads_historico (
                                nombre, telefono, telefono_norm, email, dni,
                                proyecto, canal, asesor_id, asesor_nombre,
                                estado, observaciones, ciudad,
                                fecha_ingreso, fecha_creacion,
                                lead_crm_id, origen_tabla
                            ) VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, NULL, NULL,
                                %s, %s, %s,
                                %s::date, %s::date,
                                %s, 'devolucion_crm'
                            )
                            """,
                            (
                                lead["nombre_completo"] or "Sin nombre",
                                tel,
                                tel_clean,
                                lead["email"],
                                lead["dni"],
                                _clean_text(lead["proyecto"] or lead["campana"], 150),
                                _clean_text(lead["fuente_nombre"] or "Historico", 100),
                                _clean_text(lead["estado_nombre"] or "Historico", 100),
                                _clean_text(lead["observaciones"], 1000),
                                _clean_text(lead["ciudad"], 100),
                                created_date,
                                created_date,
                                lid,
                            ),
                        )

                # 3. Desactivar y quitar asesor/supervisor en crm.leads
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET asesor_id = NULL,
                        supervisor_id = NULL,
                        activo = FALSE,
                        updated_at = NOW()
                    WHERE id = ANY(%s)
                    """,
                    (valid_ids,),
                )

                # 4. Quitar asesor en wa_conversations
                cur.execute(
                    """
                    UPDATE crm.wa_conversations
                    SET asesor_id = NULL
                    WHERE lead_id = ANY(%s)
                    """,
                    (valid_ids,),
                )

                # 5. Auditoría
                for lead in leads_to_revert:
                    if lead.get("asesor_id"):
                        cur.execute(
                            """
                            INSERT INTO crm.asignaciones_log (
                                lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo
                            ) VALUES (%s, %s::uuid, NULL, %s::uuid, 'historicos:devolucion')
                            """,
                            (lead["id"], lead["asesor_id"], current_user.user_id),
                        )

            conn.commit()

        return {
            "success": True,
            "count": len(valid_ids),
            "message": f"Se devolvieron {len(valid_ids)} lead(s) a Históricos correctamente.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error al devolver leads a Históricos: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al devolver leads a Históricos: {str(exc)}",
        )


# ── Eliminación de Leads Históricos ──────────────────────────────────────────

@router.delete("/{lead_id}")
def delete_lead_historico_single(
    lead_id: int,
    current_user: TokenData = Depends(require_admin),
):
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm_legacy.leads_historico WHERE id = %s", (lead_id,))
            deleted = cur.rowcount
        conn.commit()

    if not deleted:
        raise HTTPException(404, "Lead histórico no encontrado.")

    return {"success": True, "message": "Lead histórico eliminado exitosamente."}


@router.delete("")
def delete_leads_historico_bulk(
    body: DeleteHistoricosRequest,
    current_user: TokenData = Depends(require_admin),
):
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm_legacy.leads_historico WHERE id = ANY(%s)", (body.lead_ids,))
            deleted = cur.rowcount
        conn.commit()

    return {
        "success": True,
        "deleted": deleted,
        "message": f"Se eliminaron {deleted} leads históricos.",
    }


# ── Plantilla y Carga Masiva (hasta 5,000 registros con columnas ampliadas) ───

@router.get("/plantilla")
def download_plantilla(current_user: TokenData = Depends(require_admin)):
    """Devuelve la plantilla oficial Excel de históricos ampliada a todas las columnas requeridas."""
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        'nombres',
        'apellidos',
        'telefono',
        'ciudad',
        'estado_lead',
        'asesor',
        'fuente',
        'Creación',
        'fecha_asign',
        'fecha_ultimo',
        'email',
        'dni',
        'campana',
        'codigo_convenio',
        'observaciones',
    ]
    example = [
        'Carlos',
        'García López',
        '987654321',
        'Arequipa',
        'Nuevo',
        'Asesor Ejemplo',
        'Convenios',
        '2026-01-15',
        '2026-01-16',
        '2026-02-10',
        'carlos@email.com',
        '12345678',
        'Campaña Q2 2026',
        'CONV-2026',
        'Interesado en nuestros servicios',
    ]

    header_font = Font(name='Arial', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[cell.column_letter].width = max(len(h) + 6, 18)

    example_font = Font(name='Arial', size=10, italic=True, color='64748B')
    for col_idx, val in enumerate(example, 1):
        cell = ws.cell(row=2, column=col_idx, value=val)
        cell.font = example_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 20

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_leads_historico.xlsx"'},
    )


@router.post("/preview")
async def preview_file(
    file: UploadFile = File(...),
    current_user: TokenData = Depends(require_admin),
):
    content = await file.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el límite de {MAX_MB} MB.")

    columns, rows = _parse_file(content, file.filename or "file")
    return {
        "columns": columns,
        "preview": rows[:10],
        "total_rows": len(rows),
    }


def _run_dry_run_historicos(content: bytes, filename: str, col_map: dict) -> dict:
    _, all_rows = _parse_file(content, filename or "file")
    if len(all_rows) > MAX_ROWS:
        raise HTTPException(400, f"El archivo tiene {len(all_rows)} filas. El límite máximo para históricos es de {MAX_ROWS} filas.")

    result_rows = []
    seen_in_file = set()
    valid_phones_for_db_check = []

    for idx, raw_row in enumerate(all_rows, start=2):
        mapped = _apply_map(raw_row, col_map)
        errors = []

        tel = _clean_phone(mapped.get('telefono'))
        if not tel:
            errors.append('Teléfono inválido o vacío (mínimo 7 dígitos)')

        nombres = _clean_text(mapped.get('nombres'))
        apellidos = _clean_text(mapped.get('apellidos'))
        if not nombres and not apellidos:
            errors.append('Debe tener al menos nombres o apellidos')

        fuente_raw = _clean_text(mapped.get('fuente')) or _clean_text(mapped.get('estrategia'))
        if not fuente_raw:
            errors.append('La fuente es obligatoria')

        # Manejo de fechas opcionales
        fecha_creacion_raw = mapped.get('fecha_creacion') or mapped.get('fecha')
        fecha_asignacion_raw = mapped.get('fecha_asignacion')
        fecha_ultimo_contacto_raw = mapped.get('fecha_ultimo_contacto')
        estado_lead_raw = _clean_text(mapped.get('estado_lead')) or _clean_text(mapped.get('estado')) or _clean_text(mapped.get('calidad'))

        base_payload = {
            "row": idx,
            "nombres": nombres or 'Sin nombre',
            "apellidos": apellidos,
            "telefono": tel or str(mapped.get('telefono') or '').strip() or None,
            "email": _clean_email(mapped.get('email')),
            "dni": _clean_text(mapped.get('dni'), 20),
            "fuente": fuente_raw,
            "campana": _clean_text(mapped.get('campana'), 150) or _clean_text(mapped.get('proyecto'), 150),
            "estado_lead": estado_lead_raw or 'Nuevo',
            "ciudad": _clean_text(mapped.get('ciudad'), 100),
            "observaciones": _clean_text(mapped.get('observaciones'), 1000),
            "fecha_creacion": str(fecha_creacion_raw) if fecha_creacion_raw is not None else None,
            "fecha_asignacion": str(fecha_asignacion_raw) if fecha_asignacion_raw is not None else None,
            "fecha_ultimo_contacto": str(fecha_ultimo_contacto_raw) if fecha_ultimo_contacto_raw is not None else None,
            "asesor": _clean_text(mapped.get('asesor'), 100),
        }

        if errors:
            result_rows.append({**base_payload, "status": "error", "errors": errors})
            continue

        if tel in seen_in_file:
            result_rows.append({**base_payload, "status": "duplicate_file", "errors": ["Teléfono duplicado en el archivo"]})
            continue
        seen_in_file.add(tel)
        valid_phones_for_db_check.append(tel)
        result_rows.append({**base_payload, "status": "valid", "errors": []})

    existing_crm_phones = set()
    existing_hist_phones = set()

    if valid_phones_for_db_check:
        with get_db() as conn:
            _ensure_schema_if_needed(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT l.telefono FROM crm.leads l
                    WHERE l.telefono = ANY(%s) AND l.activo = TRUE AND l.merged_into IS NULL
                    """,
                    (valid_phones_for_db_check,),
                )
                existing_crm_phones = {r[0] for r in cur.fetchall()}

                cur.execute(
                    "SELECT DISTINCT telefono_norm FROM crm_legacy.leads_historico WHERE telefono_norm = ANY(%s)",
                    (valid_phones_for_db_check,),
                )
                existing_hist_phones = {r[0] for r in cur.fetchall()}

    for r in result_rows:
        if r["status"] == "valid":
            phone = r.get("telefono")
            if phone in existing_crm_phones:
                r["status"] = "duplicate_crm"
                r["errors"] = ["Ya existe como lead activo en el CRM"]
            elif phone in existing_hist_phones:
                r["status"] = "duplicate_historico"
                r["errors"] = ["Ya existe en la base histórica"]

    summary = {
        "valid": sum(1 for r in result_rows if r["status"] == "valid"),
        "duplicates_file": sum(1 for r in result_rows if r["status"] == "duplicate_file"),
        "duplicates_crm": sum(1 for r in result_rows if r["status"] == "duplicate_crm"),
        "duplicates_historico": sum(1 for r in result_rows if r["status"] == "duplicate_historico"),
        "errors": sum(1 for r in result_rows if r["status"] == "error"),
    }

    return {
        "total_rows": len(all_rows),
        "summary": summary,
        "rows": result_rows,
    }


@router.post("/preview-validated")
async def preview_validated(
    file: UploadFile = File(...),
    column_map: str = Form(...),
    current_user: TokenData = Depends(require_admin),
):
    content = await file.read()
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el límite de {MAX_MB} MB.")
    try:
        col_map = json.loads(column_map)
    except Exception:
        raise HTTPException(400, "column_map inválido.")

    return _run_dry_run_historicos(content, file.filename or "file", col_map)


@router.post("/download-errors")
async def download_errors(
    file: UploadFile = File(...),
    column_map: str = Form(...),
    current_user: TokenData = Depends(require_admin),
):
    content = await file.read()
    col_map = json.loads(column_map)
    result = _run_dry_run_historicos(content, file.filename or "file", col_map)

    rows_by_status = {
        "error": [r for r in result["rows"] if r["status"] == "error"],
        "duplicate_file": [r for r in result["rows"] if r["status"] == "duplicate_file"],
        "duplicate_crm": [r for r in result["rows"] if r["status"] == "duplicate_crm"],
        "duplicate_historico": [r for r in result["rows"] if r["status"] == "duplicate_historico"],
    }
    sheet_titles = {
        "error": "Errores",
        "duplicate_file": "Duplicados en archivo",
        "duplicate_crm": "Duplicados en CRM",
        "duplicate_historico": "Duplicados en Histórico",
    }

    if sum(len(v) for v in rows_by_status.values()) == 0:
        raise HTTPException(400, "No hay filas problemáticas para exportar.")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    from openpyxl.styles import Alignment, Font, PatternFill
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="334155")
    header_align = Alignment(horizontal="left", vertical="center")

    cols = [
        ("Fila", "row", 8),
        ("Nombres", "nombres", 20),
        ("Apellidos", "apellidos", 20),
        ("Teléfono", "telefono", 16),
        ("Ciudad", "ciudad", 16),
        ("Estado Lead", "estado_lead", 16),
        ("Asesor", "asesor", 18),
        ("Fuente", "fuente", 20),
        ("Creación", "fecha_creacion", 16),
        ("Asignación", "fecha_asignacion", 16),
        ("Último Contacto", "fecha_ultimo_contacto", 16),
        ("Email", "email", 26),
        ("DNI", "dni", 14),
        ("Campaña", "campana", 18),
        ("Observaciones", "observaciones", 30),
        ("Motivo", "_motivo", 60),
    ]

    for status_key, sheet_name in sheet_titles.items():
        rows = rows_by_status[status_key]
        if not rows:
            continue
        ws = wb.create_sheet(title=sheet_name)
        for col_idx, (label, _, width) in enumerate(cols, 1):
            cell = ws.cell(row=1, column=col_idx, value=label)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            ws.column_dimensions[cell.column_letter].width = width

        for row_idx, r in enumerate(rows, 2):
            values = {
                "row": r.get("row"),
                "nombres": r.get("nombres") or "",
                "apellidos": r.get("apellidos") or "",
                "telefono": r.get("telefono") or "",
                "ciudad": r.get("ciudad") or "",
                "estado_lead": r.get("estado_lead") or "",
                "asesor": r.get("asesor") or "",
                "fuente": r.get("fuente") or "",
                "fecha_creacion": r.get("fecha_creacion") or "",
                "fecha_asignacion": r.get("fecha_asignacion") or "",
                "fecha_ultimo_contacto": r.get("fecha_ultimo_contacto") or "",
                "email": r.get("email") or "",
                "dni": r.get("dni") or "",
                "campana": r.get("campana") or "",
                "observaciones": r.get("observaciones") or "",
                "_motivo": "; ".join(r.get("errors") or []),
            }
            for col_idx, (_, key, _) in enumerate(cols, 1):
                ws.cell(row=row_idx, column=col_idx, value=values[key])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="problemas_historicos_{ts}.xlsx"'},
    )


@router.post("/carga-masiva")
async def ejecutar_carga_masiva(
    file: UploadFile = File(...),
    column_map: str = Form(...),
    target_asesor_id: Optional[str] = Form(None),
    current_user: TokenData = Depends(require_admin),
):
    """Importa hasta 5,000 leads a crm_legacy.leads_historico omitiendo duplicados."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "El archivo está vacío.")
    if len(content) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo supera el límite de {MAX_MB} MB.")

    try:
        col_map = json.loads(column_map)
    except Exception:
        raise HTTPException(400, "El mapeo de columnas es inválido.")

    _, all_rows = _parse_file(content, file.filename or "file")
    if len(all_rows) > MAX_ROWS:
        raise HTTPException(400, f"El archivo supera el máximo de {MAX_ROWS} filas para históricos.")

    users_db: dict[str, tuple[str, str]] = {}
    users_first_name_db: dict[str, tuple[str, str]] = {}
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text, TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                       first_name, last_name, email
                FROM auth.users WHERE is_active = TRUE
                """
            )
            for r in cur.fetchall():
                full_name = (r["nombre"] or "").strip()
                first_name = (r["first_name"] or "").strip()
                email = (r["email"] or "").strip()
                if full_name:
                    users_db[full_name.lower()] = (r["id"], full_name)
                    users_db[_normalize_match_str(full_name)] = (r["id"], full_name)
                if first_name:
                    users_first_name_db[first_name.lower()] = (r["id"], full_name)
                    users_first_name_db[_normalize_match_str(first_name)] = (r["id"], full_name)
                if email:
                    users_db[email.lower()] = (r["id"], full_name)
                    users_db[_normalize_match_str(email)] = (r["id"], full_name)

    default_asesor_id = None
    default_asesor_nombre = None
    if target_asesor_id and target_asesor_id not in ("unassign", "pool"):
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id::text, TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre FROM auth.users WHERE id = %s::uuid AND is_active = TRUE",
                    (target_asesor_id,),
                )
                u = cur.fetchone()
                if u:
                    default_asesor_id = u["id"]
                    default_asesor_nombre = u["nombre"]

    valid_records = []
    error_rows = []
    duplicates_details = []
    seen_in_file = set()

    for idx, raw_row in enumerate(all_rows, start=2):
        mapped = _apply_map(raw_row, col_map)
        tel = _clean_phone(mapped.get("telefono"))
        if not tel:
            error_rows.append({
                "row": idx,
                "nombres": _clean_text(mapped.get("nombres")) or "",
                "apellidos": _clean_text(mapped.get("apellidos")) or "",
                "telefono": str(mapped.get("telefono") or ""),
                "email": _clean_email(mapped.get("email")) or "",
                "dni": _clean_text(mapped.get("dni"), 20) or "",
                "error": "Teléfono inválido o vacío",
                "motivo": "Teléfono inválido o vacío",
            })
            continue

        if tel in seen_in_file:
            duplicates_details.append({
                "row": idx,
                "nombres": _clean_text(mapped.get("nombres")) or "",
                "apellidos": _clean_text(mapped.get("apellidos")) or "",
                "telefono": tel,
                "email": _clean_email(mapped.get("email")) or "",
                "dni": _clean_text(mapped.get("dni"), 20) or "",
                "proyecto": _clean_text(mapped.get("campana"), 150) or _clean_text(mapped.get("proyecto"), 150) or "",
                "canal": _clean_text(mapped.get("fuente"), 100) or _clean_text(mapped.get("estrategia"), 100) or "",
                "error": f"Teléfono duplicado en archivo: {tel}",
                "motivo": f"Teléfono duplicado en el mismo archivo ({tel})",
                "tipo": "archivo",
            })
            continue
        seen_in_file.add(tel)

        nombres = _clean_text(mapped.get("nombres"))
        apellidos = _clean_text(mapped.get("apellidos"))
        if not nombres and not apellidos:
            error_rows.append({
                "row": idx,
                "nombres": "",
                "apellidos": "",
                "telefono": tel,
                "email": _clean_email(mapped.get("email")) or "",
                "dni": _clean_text(mapped.get("dni"), 20) or "",
                "error": "Debe incluir nombres o apellidos",
                "motivo": "Debe incluir nombres o apellidos",
            })
            continue
        nombre_completo = f"{nombres or ''} {apellidos or ''}".strip() or "Sin nombre"

        email = _clean_email(mapped.get("email"))
        dni = _clean_text(mapped.get("dni"), 20)
        ciudad = _clean_text(mapped.get("ciudad"), 100)
        proyecto = _clean_text(mapped.get("campana"), 150) or _clean_text(mapped.get("proyecto"), 150)
        canal = _clean_text(mapped.get("fuente"), 100) or _clean_text(mapped.get("estrategia"), 100)
        estado = _clean_text(mapped.get("estado_lead"), 100) or _clean_text(mapped.get("estado"), 100) or _clean_text(mapped.get("calidad"), 100) or "Historico"
        observaciones = _clean_text(mapped.get("observaciones"), 1000)

        # Fechas
        fecha_creacion_dt = _clean_fecha(mapped.get("fecha_creacion")) or _clean_fecha(mapped.get("fecha")) or date.today()
        fecha_asignacion_dt = _clean_fecha(mapped.get("fecha_asignacion"))
        fecha_ultimo_contacto_dt = _clean_fecha(mapped.get("fecha_ultimo_contacto"))

        # El campo asesor acepta cualquier texto libre
        asesor_raw = _clean_text(mapped.get("asesor"))
        asesor_id_row = default_asesor_id
        asesor_nombre_row = default_asesor_nombre

        if asesor_raw:
            raw_clean = asesor_raw.strip()
            norm_clean = _normalize_match_str(raw_clean)
            found = (
                users_db.get(raw_clean.lower())
                or users_db.get(norm_clean)
                or users_first_name_db.get(raw_clean.lower())
                or users_first_name_db.get(norm_clean)
            )
            if found:
                asesor_id_row, asesor_nombre_row = found
            else:
                # Asesor no registrado en el CRM: conservamos el texto libre tal cual
                asesor_id_row = None
                asesor_nombre_row = raw_clean

        valid_records.append((
            nombre_completo, tel, tel, email, dni,
            proyecto, canal, asesor_id_row, asesor_nombre_row,
            estado, observaciones, ciudad,
            fecha_creacion_dt, fecha_creacion_dt, fecha_asignacion_dt, fecha_ultimo_contacto_dt,
            nombres, apellidos, idx,
        ))

    if not valid_records:
        try:
            with get_db() as conn:
                _ensure_schema_if_needed(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO crm_legacy.cargas_historico_historial
                            (uploaded_by, uploaded_by_nombre, filename,
                             total_rows, inserted, duplicates, promoted_to_crm, errors,
                             duplicates_details, error_details)
                        VALUES (%s::uuid, (
                            SELECT TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,''))
                            FROM auth.users WHERE id = %s::uuid
                        ), %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        """,
                        (
                            current_user.user_id, current_user.user_id,
                            file.filename or "archivo",
                            len(all_rows), 0, len(duplicates_details), 0,
                            len(error_rows),
                            json.dumps(duplicates_details),
                            json.dumps(error_rows),
                        ),
                    )
                conn.commit()
        except Exception as e:
            logger.error("Error registrando historial de carga masiva de históricos (sin filas válidas): %s", e)

        return {
            "inserted": 0,
            "duplicates": len(duplicates_details),
            "promoted_to_crm": 0,
            "errors": len(error_rows),
            "error_rows": error_rows,
        }

    phones = [r[1] for r in valid_records]
    existing_crm_phones = set()
    existing_hist_phones = set()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT telefono FROM crm.leads WHERE telefono = ANY(%s) AND activo = TRUE AND merged_into IS NULL", (phones,))
            existing_crm_phones = {r[0] for r in cur.fetchall()}

            cur.execute("SELECT DISTINCT telefono_norm FROM crm_legacy.leads_historico WHERE telefono_norm = ANY(%s)", (phones,))
            existing_hist_phones = {r[0] for r in cur.fetchall()}

    all_existing = existing_crm_phones.union(existing_hist_phones)

    to_insert = []
    for r in valid_records:
        if r[1] in all_existing:
            dup_type = "CRM" if r[1] in existing_crm_phones else "Histórico"
            duplicates_details.append({
                "row": r[18] if len(r) > 18 else "—",
                "nombres": r[16] or "",
                "apellidos": r[17] or "",
                "telefono": r[1],
                "email": r[3] or "",
                "dni": r[4] or "",
                "proyecto": r[5] or "",
                "canal": r[6] or "",
                "motivo": f"Teléfono ya registrado en {dup_type} ({r[1]})",
                "tipo": dup_type.lower(),
            })
        else:
            to_insert.append(r)

    dup_count = len(duplicates_details)

    inserted = 0
    promoted = 0
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for rec in to_insert:
                try:
                    cur.execute(
                        """
                        INSERT INTO crm_legacy.leads_historico (
                            nombre, telefono, telefono_norm, email, dni,
                            proyecto, canal, asesor_id, asesor_nombre,
                            estado, observaciones, ciudad,
                            fecha_ingreso, fecha_creacion, fecha_asignacion, fecha_ultimo_contacto,
                            origen_tabla
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s::uuid, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s,
                            'carga_masiva'
                        )
                        RETURNING id
                        """,
                        rec[:16],
                    )
                    inserted += 1
                except Exception as exc:
                    logger.error("Error insertando histórico: %s", exc)
                    error_rows.append({
                        "row": rec[18] if len(rec) > 18 else "—",
                        "nombres": rec[16] or "",
                        "apellidos": rec[17] or "",
                        "telefono": rec[1],
                        "email": rec[3] or "",
                        "dni": rec[4] or "",
                        "error": f"Error DB: {rec[1]}",
                        "motivo": f"Error DB: {str(exc)}",
                    })
        conn.commit()

    # Registrar en historial de cargas masivas de históricos
    try:
        with get_db() as conn:
            _ensure_schema_if_needed(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm_legacy.cargas_historico_historial
                        (uploaded_by, uploaded_by_nombre, filename,
                         total_rows, inserted, duplicates, promoted_to_crm, errors,
                         duplicates_details, error_details)
                    VALUES (%s::uuid, (
                        SELECT TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,''))
                        FROM auth.users WHERE id = %s::uuid
                    ), %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        current_user.user_id, current_user.user_id,
                        file.filename or "archivo",
                        len(all_rows), inserted, dup_count, 0,
                        len(error_rows),
                        json.dumps(duplicates_details),
                        json.dumps(error_rows),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.error("Error registrando historial de carga masiva de históricos: %s", e)

    msg = f"Se importaron {inserted} leads históricos exitosamente."

    return {
        "inserted": inserted,
        "duplicates": dup_count,
        "promoted_to_crm": 0,
        "errors": len(error_rows),
        "error_rows": error_rows,
        "message": msg,
    }


# ── Historial de Cargas Masivas de Históricos ────────────────────────────────

@router.get("/cargas-historial")
def list_cargas_historial(
    limit: int = 50,
    current_user: TokenData = Depends(require_admin),
):
    """Lista las últimas cargas masivas realizadas en históricos."""
    limit = max(1, min(limit, 200))
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, uploaded_by_nombre, filename,
                       total_rows, inserted, duplicates, promoted_to_crm, errors, uploaded_at
                FROM crm_legacy.cargas_historico_historial
                ORDER BY uploaded_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    for r in rows:
        if r.get("uploaded_at"):
            r["uploaded_at"] = r["uploaded_at"].isoformat()
    return {"items": rows}


@router.get("/cargas-historial/{historial_id}/detalles")
def get_carga_historial_detalles(
    historial_id: int,
    current_user: TokenData = Depends(require_admin),
):
    """Retorna los detalles estructurados de duplicados y errores de una carga masiva de históricos."""
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, uploaded_by_nombre, filename,
                       total_rows, inserted, duplicates, promoted_to_crm, errors, uploaded_at,
                       COALESCE(duplicates_details, '[]'::jsonb) AS duplicates_details,
                       COALESCE(error_details, '[]'::jsonb) AS error_details
                FROM crm_legacy.cargas_historico_historial
                WHERE id = %s
                """,
                (historial_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Registro de historial no encontrado.")
            if row.get("uploaded_at"):
                row["uploaded_at"] = row["uploaded_at"].isoformat()
            return row


@router.delete("/cargas-historial/{historial_id}")
def delete_carga_historial(
    historial_id: int,
    current_user: TokenData = Depends(require_admin),
):
    """Elimina un registro del historial de cargas masivas de históricos."""
    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crm_legacy.cargas_historico_historial WHERE id = %s", (historial_id,))
            deleted = cur.rowcount
        conn.commit()
    if deleted == 0:
        raise HTTPException(404, "Registro de historial no encontrado.")
    return {"deleted": True, "id": historial_id}


# ── Exportar a Excel ─────────────────────────────────────────────────────────

@router.get("/exportar")
def historicos_exportar(
    search: Optional[str] = Query(None),
    mes: Optional[str] = Query(None),
    proyecto: Optional[str] = Query(None),
    canal: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    asesor_id: Optional[str] = Query(None),
    current_user: TokenData = Depends(require_admin),
):
    where_parts = []
    params = []

    if mes and mes.strip() and mes.strip().lower() != "todos":
        where_parts.append("TO_CHAR(COALESCE(h.fecha_creacion, h.fecha_ingreso), 'YYYY-MM') = %s")
        params.append(mes.strip())

    if search:
        search_clean = search.strip()
        digits = re.sub(r'\D', '', search_clean)
        if digits and len(digits) >= 4:
            where_parts.append("h.telefono_norm LIKE %s")
            params.append(f"%{digits[-9:]}%")
        else:
            tokens = [t for t in search_clean.split() if t]
            if len(tokens) <= 1:
                where_parts.append("(h.nombre ILIKE %s OR h.email ILIKE %s OR h.dni ILIKE %s OR h.asesor_nombre ILIKE %s)")
                term = f"%{search_clean}%"
                params.extend([term, term, term, term])
            else:
                token_clauses = []
                for tok in tokens:
                    token_clauses.append("(h.nombre ILIKE %s OR h.email ILIKE %s OR h.dni ILIKE %s OR h.asesor_nombre ILIKE %s)")
                    tterm = f"%{tok}%"
                    params.extend([tterm, tterm, tterm, tterm])
                where_parts.append("(" + " AND ".join(token_clauses) + ")")

    if proyecto:
        where_parts.append("h.proyecto ILIKE %s")
        params.append(f"%{proyecto.strip()}%")

    if canal:
        where_parts.append("h.canal ILIKE %s")
        params.append(f"%{canal.strip()}%")

    if estado:
        where_parts.append("h.estado ILIKE %s")
        params.append(f"%{estado.strip()}%")

    if asesor_id:
        if asesor_id == "sin_asesor":
            where_parts.append("h.asesor_id IS NULL AND (h.asesor_nombre IS NULL OR h.asesor_nombre = '')")
        elif asesor_id == "asesor_no_registrado":
            where_parts.append("h.asesor_id IS NULL AND h.asesor_nombre IS NOT NULL AND h.asesor_nombre != ''")
        else:
            where_parts.append("h.asesor_id = %s::uuid")
            params.append(asesor_id)

    where_sql = " AND ".join(where_parts) if where_parts else "TRUE"

    with get_db() as conn:
        _ensure_schema_if_needed(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    h.nombre, h.telefono, h.email, h.dni,
                    h.proyecto, h.canal,
                    COALESCE(
                        NULLIF(TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')), ''),
                        NULLIF(TRIM(h.asesor_nombre), ''),
                        '—'
                    ) AS asesor_nombre,
                    h.estado, h.seguimiento, h.observaciones,
                    h.ciudad,
                    COALESCE(h.fecha_creacion, h.fecha_ingreso)::text AS fecha_creacion,
                    h.fecha_asignacion::text AS fecha_asignacion,
                    h.fecha_ultimo_contacto::text AS fecha_ultimo_contacto,
                    h.origen_tabla
                FROM crm_legacy.leads_historico h
                LEFT JOIN auth.users u ON u.id = h.asesor_id
                WHERE {where_sql}
                ORDER BY COALESCE(h.fecha_creacion, h.fecha_ingreso) DESC NULLS LAST, h.id DESC
                LIMIT 50000
                """,
                params,
            )
            rows = cur.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Históricos"
    headers = [
        "Nombre", "Teléfono", "Email", "DNI", "Proyecto", "Canal",
        "Asesor", "Estado", "Seguimiento", "Observaciones", "Ciudad",
        "Creación", "Asignación", "Último Contacto", "Origen",
    ]
    ws.append(headers)
    for row in rows:
        ws.append([
            row.get("nombre"), row.get("telefono"), row.get("email"),
            row.get("dni"), row.get("proyecto"), row.get("canal"),
            row.get("asesor_nombre"), row.get("estado"), row.get("seguimiento"),
            row.get("observaciones"), row.get("ciudad"),
            row.get("fecha_creacion"), row.get("fecha_asignacion"),
            row.get("fecha_ultimo_contacto"), row.get("origen_tabla"),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"historicos_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

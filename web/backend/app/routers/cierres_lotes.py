"""
cierres_lotes.py — Módulo exclusivo Admin para control de Cierres de Ventas (PDR-FO-GC-17):
- Respaldo y fuente de verdad en PostgreSQL (editable desde el CRM).
- Comparación / Diff estilo Git desde subida de Excel (.xlsx / .csv) o Drive.
- Historial de versiones (commits/revisiones) y auditoría de campos.
- Exportación a Excel (.xlsx).
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.routers.separaciones import (
    MONTH_NAMES,
    DriveConfigIn,
    RevisionApproveIn,
    RevisionRejectIn,
    _next_revision_number,
    _resolve_actor,
    upsert_pending_module_revision,
)
from app.services import separaciones_drive_service as sds

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cierres-lotes", tags=["Gestión de Lotes - Cierres"])

MODULO = "cierres"


class CierreCreateIn(BaseModel):
    anio: int = 2026
    mes: int
    asesor: Optional[str] = None
    proyecto: str
    lote: str
    cliente_nombre: str
    distrito: Optional[str] = None
    fecha_ingreso_inicial: Optional[str] = None
    monto_total: Optional[float] = None
    moneda: str = "SOLES"
    pct_inicial_raw: Optional[str] = None
    estrategia: Optional[str] = None
    area: Optional[str] = None
    edad: Optional[int] = None
    cantidad_inicial: Optional[float] = None
    tipo_cambio: Optional[float] = None
    observaciones: Optional[str] = None
    lead_id: Optional[int] = None


class CierreUpdateIn(BaseModel):
    anio: Optional[int] = None
    mes: Optional[int] = None
    asesor: Optional[str] = None
    proyecto: Optional[str] = None
    lote: Optional[str] = None
    cliente_nombre: Optional[str] = None
    distrito: Optional[str] = None
    fecha_ingreso_inicial: Optional[str] = None
    monto_total: Optional[float] = None
    moneda: Optional[str] = None
    pct_inicial_raw: Optional[str] = None
    estrategia: Optional[str] = None
    area: Optional[str] = None
    edad: Optional[int] = None
    cantidad_inicial: Optional[float] = None
    tipo_cambio: Optional[float] = None
    observaciones: Optional[str] = None
    lead_id: Optional[int] = None


def _normalize_moneda(raw: Optional[str]) -> str:
    up = (raw or "").strip().upper()
    if "DOLAR" in up or "USD" in up or "$" in up:
        return "DOLARES"
    return "SOLES"


def _serialize_cierre_out(r: dict[str, Any]) -> dict[str, Any]:
    out = dict(r)
    for num_k in ("monto_total", "pct_inicial", "cantidad_inicial", "tipo_cambio"):
        if out.get(num_k) is not None:
            out[num_k] = float(out[num_k])
    for dt_k in ("fecha_ingreso_date", "created_at", "updated_at"):
        if hasattr(out.get(dt_k), "isoformat"):
            out[dt_k] = out[dt_k].isoformat()
    return out


def _fetch_filtered_cierres(
    cur,
    *,
    anio: Optional[int] = None,
    mes: Optional[int] = None,
    proyecto: Optional[str] = None,
    asesor: Optional[str] = None,
    moneda: Optional[str] = None,
    estrategia: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    filters = ["activo = TRUE"]
    params: list[Any] = []

    if anio is not None:
        filters.append("anio = %s")
        params.append(anio)
    if mes is not None:
        filters.append("mes = %s")
        params.append(mes)
    if proyecto:
        filters.append("LOWER(TRIM(COALESCE(proyecto, ''))) = LOWER(TRIM(%s))")
        params.append(proyecto)
    if asesor:
        filters.append("LOWER(TRIM(COALESCE(asesor, ''))) = LOWER(TRIM(%s))")
        params.append(asesor)
    if moneda:
        filters.append("UPPER(TRIM(COALESCE(moneda, ''))) = UPPER(TRIM(%s))")
        params.append(_normalize_moneda(moneda))
    if estrategia:
        filters.append("LOWER(TRIM(COALESCE(estrategia, ''))) = LOWER(TRIM(%s))")
        params.append(estrategia)
    if search:
        q = f"%{search.strip()}%"
        filters.append(
            "(COALESCE(asesor, '') ILIKE %s OR COALESCE(proyecto, '') ILIKE %s OR "
            "COALESCE(lote, '') ILIKE %s OR COALESCE(cliente_nombre, '') ILIKE %s OR "
            "COALESCE(distrito, '') ILIKE %s OR COALESCE(estrategia, '') ILIKE %s OR "
            "COALESCE(observaciones, '') ILIKE %s)"
        )
        params.extend([q, q, q, q, q, q, q])

    cur.execute(
        f"""
        SELECT *
        FROM crm.cierres_lotes_registros
        WHERE {' AND '.join(filters)}
        ORDER BY anio DESC, mes DESC, orden_fila ASC, id ASC
        """,
        params,
    )
    return [_serialize_cierre_out(r) for r in cur.fetchall()]


def _compute_cierres_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    monto_soles = sum((r.get("monto_total") or 0) for r in rows if (r.get("moneda") or "SOLES") == "SOLES")
    monto_dolares = sum((r.get("monto_total") or 0) for r in rows if r.get("moneda") == "DOLARES")
    inicial_soles = sum((r.get("cantidad_inicial") or 0) for r in rows if (r.get("moneda") or "SOLES") == "SOLES")
    inicial_dolares = sum((r.get("cantidad_inicial") or 0) for r in rows if r.get("moneda") == "DOLARES")
    pct_vals = [r["pct_inicial"] for r in rows if r.get("pct_inicial") is not None]
    prom_pct = round((sum(pct_vals) / len(pct_vals)) * 100, 1) if pct_vals else 0.0

    estrategias: dict[str, int] = {}
    asesores_map: dict[str, dict[str, Any]] = {}
    proyectos_map: dict[str, dict[str, Any]] = {}

    for r in rows:
        est = (r.get("estrategia") or "SIN ESTRATEGIA").strip()
        estrategias[est] = estrategias.get(est, 0) + 1

        mon = r.get("moneda") or "SOLES"
        m_tot = r.get("monto_total") or 0
        c_ini = r.get("cantidad_inicial") or 0

        ase = (r.get("asesor") or "SIN ASESOR").strip()
        if ase not in asesores_map:
            asesores_map[ase] = {
                "asesor": ase,
                "total": 0,
                "monto_soles": 0.0,
                "monto_dolares": 0.0,
                "inicial_soles": 0.0,
                "inicial_dolares": 0.0,
            }
        asesores_map[ase]["total"] += 1
        if mon == "DOLARES":
            asesores_map[ase]["monto_dolares"] = round(asesores_map[ase]["monto_dolares"] + m_tot, 2)
            asesores_map[ase]["inicial_dolares"] = round(asesores_map[ase]["inicial_dolares"] + c_ini, 2)
        else:
            asesores_map[ase]["monto_soles"] = round(asesores_map[ase]["monto_soles"] + m_tot, 2)
            asesores_map[ase]["inicial_soles"] = round(asesores_map[ase]["inicial_soles"] + c_ini, 2)

        proy = (r.get("proyecto") or "SIN PROYECTO").strip()
        if proy not in proyectos_map:
            proyectos_map[proy] = {"proyecto": proy, "total": 0, "monto_soles": 0.0, "monto_dolares": 0.0}
        proyectos_map[proy]["total"] += 1
        if mon == "DOLARES":
            proyectos_map[proy]["monto_dolares"] = round(proyectos_map[proy]["monto_dolares"] + m_tot, 2)
        else:
            proyectos_map[proy]["monto_soles"] = round(proyectos_map[proy]["monto_soles"] + m_tot, 2)

    return {
        "total_cierres": len(rows),
        "monto_total_soles": round(monto_soles, 2),
        "monto_total_dolares": round(monto_dolares, 2),
        "inicial_total_soles": round(inicial_soles, 2),
        "inicial_total_dolares": round(inicial_dolares, 2),
        "promedio_pct_inicial": prom_pct,
        "resumen_estrategias": [
            {"estrategia": k, "total": v}
            for k, v in sorted(estrategias.items(), key=lambda x: (-x[1], x[0]))
        ],
        "resumen_asesores": sorted(asesores_map.values(), key=lambda x: (-x["total"], x["asesor"])),
        "resumen_proyectos": sorted(proyectos_map.values(), key=lambda x: (-x["total"], x["proyecto"])),
    }


@router.get("/meta")
def get_cierres_meta(admin: TokenData = Depends(require_admin)):
    """Catálogos, períodos disponibles, config Drive y revisión pendiente de Cierres."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT anio, mes, mes_nombre
                FROM crm.cierres_lotes_registros
                WHERE activo = TRUE
                ORDER BY anio DESC, mes DESC
                """
            )
            periodos = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    ARRAY_AGG(DISTINCT TRIM(proyecto)) FILTER (WHERE TRIM(COALESCE(proyecto, '')) <> '') AS proyectos,
                    ARRAY_AGG(DISTINCT TRIM(asesor)) FILTER (WHERE TRIM(COALESCE(asesor, '')) <> '') AS asesores,
                    ARRAY_AGG(DISTINCT TRIM(estrategia)) FILTER (WHERE TRIM(COALESCE(estrategia, '')) <> '') AS estrategias,
                    ARRAY_AGG(DISTINCT UPPER(TRIM(moneda))) FILTER (WHERE TRIM(COALESCE(moneda, '')) <> '') AS monedas,
                    COUNT(*)::int AS total_registros
                FROM crm.cierres_lotes_registros
                WHERE activo = TRUE
                """
            )
            cats = cur.fetchone() or {}

            cur.execute("SELECT * FROM crm.separaciones_drive_config WHERE modulo = %s LIMIT 1", (MODULO,))
            drive_cfg = cur.fetchone()
            drive_cfg_out = dict(drive_cfg) if drive_cfg else None
            if drive_cfg_out:
                for k in ("last_checked_at", "updated_at"):
                    if hasattr(drive_cfg_out.get(k), "isoformat"):
                        drive_cfg_out[k] = drive_cfg_out[k].isoformat()

            cur.execute(
                """
                SELECT *
                FROM crm.separaciones_revisions
                WHERE modulo = %s AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (MODULO,),
            )
            pending = cur.fetchone()
            pending_out = dict(pending) if pending else None
            if pending_out and hasattr(pending_out.get("created_at"), "isoformat"):
                pending_out["created_at"] = pending_out["created_at"].isoformat()

            cur.execute(
                "SELECT COUNT(*)::int AS total_revs FROM crm.separaciones_revisions WHERE modulo = %s AND status IN ('approved', 'applied')",
                (MODULO,),
            )
            rev_count = (cur.fetchone() or {}).get("total_revs", 0)

    return {
        "periodos": periodos,
        "catalogos": {
            "proyectos": sorted(cats.get("proyectos") or []),
            "asesores": sorted(cats.get("asesores") or []),
            "estrategias": sorted(cats.get("estrategias") or []),
            "monedas": sorted(cats.get("monedas") or ["SOLES", "DOLARES"]),
        },
        "total_registros": cats.get("total_registros") or 0,
        "drive_config": drive_cfg_out,
        "pending_revision": pending_out,
        "total_revisions": rev_count,
    }


@router.get("")
def list_cierres_lotes(
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    proyecto: Optional[str] = Query(None),
    asesor: Optional[str] = Query(None),
    moneda: Optional[str] = Query(None),
    estrategia: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: TokenData = Depends(require_admin),
):
    """Lista los cierres de ventas respaldados en el servidor con KPIs calculados."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            rows = _fetch_filtered_cierres(
                cur,
                anio=anio,
                mes=mes,
                proyecto=proyecto,
                asesor=asesor,
                moneda=moneda,
                estrategia=estrategia,
                search=search,
            )

    return {
        "resumen": _compute_cierres_stats(rows),
        "total": len(rows),
        "items": rows,
    }


@router.post("", status_code=201)
def create_cierre_registro(
    data: CierreCreateIn,
    admin: TokenData = Depends(require_admin),
):
    """Crea un nuevo cierre de venta en PostgreSQL y registra versión + auditoría."""
    if data.mes < 1 or data.mes > 12:
        raise HTTPException(status_code=400, detail="mes inválido (1-12)")

    mes_nombre = MONTH_NAMES[data.mes]
    fi_str, fi_date = sds.parse_date_flexible(data.fecha_ingreso_inicial)
    pct_num, pct_raw = sds._parse_pct_inicial(data.pct_inicial_raw)
    moneda_norm = _normalize_moneda(data.moneda)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute(
                """
                SELECT COALESCE(MAX(orden_fila), 0) + 1 AS next_orden
                FROM crm.cierres_lotes_registros
                WHERE anio = %s AND mes = %s AND activo = TRUE
                """,
                (data.anio, data.mes),
            )
            next_orden = int((cur.fetchone() or {}).get("next_orden", 1))

            cur.execute(
                """
                INSERT INTO crm.cierres_lotes_registros (
                    anio, mes, mes_nombre, orden_fila,
                    asesor, proyecto, lote, cliente_nombre, distrito,
                    fecha_ingreso_inicial, fecha_ingreso_date,
                    monto_total, moneda, pct_inicial, pct_inicial_raw,
                    estrategia, area, edad, cantidad_inicial, tipo_cambio,
                    observaciones, origen, lead_id, created_by, updated_by
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, 'crm', %s, %s::uuid, %s::uuid
                )
                RETURNING *
                """,
                (
                    data.anio, data.mes, mes_nombre, next_orden,
                    sds._clean_str(data.asesor), sds._clean_str(data.proyecto),
                    sds._clean_str(data.lote), sds._clean_str(data.cliente_nombre),
                    sds._clean_str(data.distrito),
                    fi_str, fi_date,
                    data.monto_total, moneda_norm, pct_num, pct_raw,
                    sds._clean_str(data.estrategia), sds._clean_str(data.area),
                    data.edad, data.cantidad_inicial, data.tipo_cambio,
                    sds._clean_str(data.observaciones),
                    data.lead_id, actor_id, actor_id,
                ),
            )
            created = dict(cur.fetchone())

            rev_num = _next_revision_number(cur)
            snap = sds._serialize_cierre_snapshot(created)
            diff_entry = [{
                "change_type": "added",
                "sync_key": f"crm-cie-{created['id']}",
                "registro_id": created["id"],
                "label": sds._cierre_row_label(snap),
                "before": None,
                "after": snap,
                "changed_fields": [],
            }]
            cur.execute(
                """
                INSERT INTO crm.separaciones_revisions (
                    modulo, revision_number, source, status, summary_json, diff_json,
                    message, created_by, created_by_name, reviewed_by, reviewed_by_name, reviewed_at
                )
                VALUES (%s, %s, 'crm_manual', 'applied', %s::jsonb, %s::jsonb, %s, %s::uuid, %s, %s::uuid, %s, NOW())
                RETURNING id
                """,
                (
                    MODULO,
                    rev_num,
                    json.dumps({"added": 1, "modified": 0, "removed": 0}),
                    json.dumps(diff_entry),
                    f"Alta cierre en CRM: {sds._cierre_row_label(snap)}",
                    actor_id, user_name, actor_id, user_name,
                ),
            )
            rev_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO crm.separaciones_audit_log (
                    modulo, cierre_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                )
                VALUES (%s, %s, %s, 'create', 'registro', NULL, %s, %s::uuid, %s)
                """,
                (MODULO, created["id"], rev_id, sds._cierre_row_label(snap), actor_id, user_name),
            )
        conn.commit()

    return _serialize_cierre_out(created)


@router.put("/drive/config")
def update_cierres_drive_config(
    data: DriveConfigIn,
    admin: TokenData = Depends(require_admin),
):
    """Permite actualizar el enlace del Google Sheet monitoreado para Cierres."""
    sheet_id, gid = sds.extract_spreadsheet_id_and_gid(data.sheet_url)
    if not sheet_id:
        raise HTTPException(status_code=400, detail="URL de Google Sheets inválida")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE crm.separaciones_drive_config
                SET spreadsheet_id = %s, gid = %s, sheet_url = %s, updated_at = NOW()
                WHERE modulo = %s
                RETURNING *
                """,
                (sheet_id, gid, data.sheet_url.strip(), MODULO),
            )
            cfg = dict(cur.fetchone())
        conn.commit()
    return cfg


@router.post("/drive/check")
def check_cierres_drive_changes(admin: TokenData = Depends(require_admin)):
    """Consulta el Google Sheet de Cierres en Drive y crea/actualiza revisión pendiente estilo Git."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute("SELECT * FROM crm.separaciones_drive_config WHERE modulo = %s LIMIT 1", (MODULO,))
            cfg = cur.fetchone()
            spreadsheet_id = (cfg or {}).get("spreadsheet_id") or sds.DEFAULT_CIERRES_SPREADSHEET_ID
            gid = (cfg or {}).get("gid") or sds.DEFAULT_GID

            try:
                csv_text, drive_hash = sds.fetch_drive_csv(spreadsheet_id, gid)
                drive_rows = sds.parse_cierres_csv(csv_text, origen="drive")
            except Exception as exc:
                logger.warning("[cierres_drive] error consultando Drive: %s", exc)
                cur.execute(
                    """
                    UPDATE crm.separaciones_drive_config
                    SET last_checked_at = NOW(), last_check_status = 'error',
                        last_check_error = %s, updated_at = NOW()
                    WHERE modulo = %s
                    """,
                    (str(exc)[:500], MODULO),
                )
                conn.commit()
                raise HTTPException(
                    status_code=502,
                    detail=f"No se pudo leer el Drive de Cierres (verifica permisos o usa Subir Excel): {exc}",
                )

            cur.execute("SELECT * FROM crm.cierres_lotes_registros WHERE activo = TRUE")
            crm_rows = [dict(r) for r in cur.fetchall()]

            diff_res = sds.compute_cierres_diff(crm_rows, drive_rows)
            summary = diff_res["summary"]
            has_changes = (summary["added"] + summary["modified"] + summary["removed"]) > 0
            source = "drive_initial" if len(crm_rows) == 0 else "drive_sync"
            msg = (
                f"Importación inicial Cierres desde Drive ({summary['added']} registros)"
                if source == "drive_initial"
                else f"Cambios Cierres en Drive: +{summary['added']} nuevos, ~{summary['modified']} modificados, -{summary['removed']} quitados"
            )
            pending_rev = upsert_pending_module_revision(
                cur,
                modulo=MODULO,
                source=source,
                content_hash=drive_hash,
                diff_res=diff_res,
                message=msg,
                actor_id=actor_id,
                user_name=user_name,
                update_drive_status=True,
            )
        conn.commit()

    return {
        "has_changes": has_changes,
        "drive_hash": drive_hash,
        "summary": summary,
        "pending_revision": pending_rev,
    }


@router.post("/upload")
async def upload_cierres_excel(
    file: UploadFile = File(...),
    admin: TokenData = Depends(require_admin),
):
    """Sube Excel (.xlsx/.xlsm) o CSV de Cierres, compara contra PostgreSQL y crea Diff estilo Git."""
    filename = (file.filename or "cierres.xlsx").strip()
    if not filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(status_code=400, detail="Solo se admiten archivos .xlsx, .xlsm o .csv")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    try:
        sheets, file_hash = sds.read_tabular_sheets(content, filename)
        incoming_rows = sds.parse_cierres_workbook(sheets, origen="excel")
    except Exception as exc:
        logger.warning("[cierres_upload] error leyendo %s: %s", filename, exc)
        raise HTTPException(status_code=400, detail=f"No se pudo interpretar el archivo de Cierres: {exc}")

    if not incoming_rows:
        raise HTTPException(
            status_code=400,
            detail="No se detectaron registros del Cuadro de Cierre de Ventas en el archivo subido",
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute("SELECT * FROM crm.cierres_lotes_registros WHERE activo = TRUE")
            crm_rows = [dict(r) for r in cur.fetchall()]

            diff_res = sds.compute_cierres_diff(crm_rows, incoming_rows)
            summary = diff_res["summary"]
            has_changes = (summary["added"] + summary["modified"] + summary["removed"]) > 0
            msg = (
                f"Carga Cierres desde Excel ({filename}): +{summary['added']} nuevos, "
                f"~{summary['modified']} modificados, -{summary['removed']} quitados"
            )
            pending_rev = upsert_pending_module_revision(
                cur,
                modulo=MODULO,
                source="excel_upload",
                content_hash=file_hash,
                diff_res=diff_res,
                message=msg,
                actor_id=actor_id,
                user_name=user_name,
                update_drive_status=False,
            )
        conn.commit()

    return {
        "has_changes": has_changes,
        "parsed_rows": len(incoming_rows),
        "filename": filename,
        "file_hash": file_hash,
        "summary": summary,
        "pending_revision": pending_rev,
    }


@router.get("/revisions")
def list_cierres_revisions(
    limit: int = Query(50, ge=1, le=200),
    admin: TokenData = Depends(require_admin),
):
    """Lista historial de revisiones / commits estilo Git de Cierres."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM crm.separaciones_revisions
                WHERE modulo = %s
                ORDER BY revision_number DESC, id DESC
                LIMIT %s
                """,
                (MODULO, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k in ("created_at", "reviewed_at"):
            if hasattr(r.get(k), "isoformat"):
                r[k] = r[k].isoformat()
    return {"items": rows}


@router.post("/revisions/{revision_id}/approve")
def approve_cierres_revision(
    revision_id: int,
    data: RevisionApproveIn,
    admin: TokenData = Depends(require_admin),
):
    """Aprueba e incorpora en PostgreSQL los cierres seleccionados desde Excel o Drive."""
    selected_set = set(data.selected_keys) if data.selected_keys is not None else None

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute(
                "SELECT * FROM crm.separaciones_revisions WHERE id = %s AND modulo = %s",
                (revision_id, MODULO),
            )
            rev = cur.fetchone()
            if not rev:
                raise HTTPException(status_code=404, detail="Revisión no encontrada")
            if rev["status"] != "pending":
                raise HTTPException(status_code=400, detail=f"La revisión ya está en estado '{rev['status']}'")

            row_origen = "excel" if rev.get("source") == "excel_upload" else "drive"
            diff_items = rev.get("diff_json") or []
            applied_items = []
            applied_counts = {"added": 0, "modified": 0, "removed": 0}

            for item in diff_items:
                sk = item.get("sync_key")
                if selected_set is not None and sk not in selected_set:
                    continue

                ctype = item.get("change_type")
                after = item.get("after") or {}
                before = item.get("before") or {}

                if ctype == "added":
                    cur.execute(
                        """
                        INSERT INTO crm.cierres_lotes_registros (
                            anio, mes, mes_nombre, orden_fila, sync_key,
                            asesor, proyecto, lote, cliente_nombre, distrito,
                            fecha_ingreso_inicial, fecha_ingreso_date,
                            monto_total, moneda, pct_inicial, pct_inicial_raw,
                            estrategia, area, edad, cantidad_inicial, tipo_cambio,
                            observaciones, origen, created_by, updated_by
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s::date,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s::uuid, %s::uuid
                        )
                        RETURNING id
                        """,
                        (
                            after.get("anio"), after.get("mes"), after.get("mes_nombre"),
                            after.get("orden_fila") or 0, sk,
                            after.get("asesor"), after.get("proyecto"), after.get("lote"),
                            after.get("cliente_nombre"), after.get("distrito"),
                            after.get("fecha_ingreso_inicial"), after.get("fecha_ingreso_date"),
                            after.get("monto_total"), after.get("moneda") or "SOLES",
                            after.get("pct_inicial"), after.get("pct_inicial_raw"),
                            after.get("estrategia"), after.get("area"), after.get("edad"),
                            after.get("cantidad_inicial"), after.get("tipo_cambio"),
                            after.get("observaciones"), row_origen, actor_id, actor_id,
                        ),
                    )
                    new_id = cur.fetchone()["id"]
                    cur.execute(
                        """
                        INSERT INTO crm.separaciones_audit_log (
                            modulo, cierre_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                        )
                        VALUES (%s, %s, %s, 'approve_add', 'registro', NULL, %s, %s::uuid, %s)
                        """,
                        (MODULO, new_id, revision_id, item.get("label"), actor_id, user_name),
                    )
                    applied_counts["added"] += 1
                    applied_items.append(item)

                elif ctype == "modified":
                    reg_id = item.get("registro_id")
                    if not reg_id:
                        cur.execute(
                            "SELECT id FROM crm.cierres_lotes_registros WHERE sync_key = %s AND activo = TRUE LIMIT 1",
                            (sk,),
                        )
                        found = cur.fetchone()
                        reg_id = found["id"] if found else None
                    if reg_id:
                        cur.execute(
                            """
                            UPDATE crm.cierres_lotes_registros
                            SET asesor = %s, proyecto = %s, lote = %s,
                                cliente_nombre = %s, distrito = %s,
                                fecha_ingreso_inicial = %s, fecha_ingreso_date = %s::date,
                                monto_total = %s, moneda = %s,
                                pct_inicial = %s, pct_inicial_raw = %s,
                                estrategia = %s, area = %s, edad = %s,
                                cantidad_inicial = %s, tipo_cambio = %s,
                                observaciones = %s, orden_fila = %s,
                                updated_by = %s::uuid, updated_at = NOW()
                            WHERE id = %s
                            """,
                            (
                                after.get("asesor"), after.get("proyecto"), after.get("lote"),
                                after.get("cliente_nombre"), after.get("distrito"),
                                after.get("fecha_ingreso_inicial"), after.get("fecha_ingreso_date"),
                                after.get("monto_total"), after.get("moneda") or "SOLES",
                                after.get("pct_inicial"), after.get("pct_inicial_raw"),
                                after.get("estrategia"), after.get("area"), after.get("edad"),
                                after.get("cantidad_inicial"), after.get("tipo_cambio"),
                                after.get("observaciones"), after.get("orden_fila") or 0,
                                actor_id, reg_id,
                            ),
                        )
                        for cf in item.get("changed_fields") or []:
                            cur.execute(
                                """
                                INSERT INTO crm.separaciones_audit_log (
                                    modulo, cierre_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                                )
                                VALUES (%s, %s, %s, 'approve_update', %s, %s, %s, %s::uuid, %s)
                                """,
                                (MODULO, reg_id, revision_id, cf.get("field"), cf.get("before"), cf.get("after"), actor_id, user_name),
                            )
                        applied_counts["modified"] += 1
                        applied_items.append(item)

                elif ctype == "removed":
                    reg_id = item.get("registro_id")
                    if reg_id:
                        cur.execute(
                            """
                            UPDATE crm.cierres_lotes_registros
                            SET activo = FALSE, updated_by = %s::uuid, updated_at = NOW()
                            WHERE id = %s AND activo = TRUE
                            """,
                            (actor_id, reg_id),
                        )
                        cur.execute(
                            """
                            INSERT INTO crm.separaciones_audit_log (
                                modulo, cierre_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                            )
                            VALUES (%s, %s, %s, 'approve_remove', 'registro', %s, NULL, %s::uuid, %s)
                            """,
                            (MODULO, reg_id, revision_id, item.get("label") or before.get("cliente_nombre"), actor_id, user_name),
                        )
                        applied_counts["removed"] += 1
                        applied_items.append(item)

            final_msg = (data.message or "").strip() or rev.get("message")
            cur.execute(
                """
                UPDATE crm.separaciones_revisions
                SET status = 'approved',
                    summary_json = %s::jsonb,
                    diff_json = %s::jsonb,
                    message = %s,
                    reviewed_by = %s::uuid,
                    reviewed_by_name = %s,
                    reviewed_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (
                    json.dumps(applied_counts),
                    json.dumps(applied_items),
                    final_msg,
                    actor_id,
                    user_name,
                    revision_id,
                ),
            )
            approved_rev = dict(cur.fetchone())

            if rev.get("source") != "excel_upload":
                cur.execute(
                    """
                    UPDATE crm.separaciones_drive_config
                    SET last_approved_hash = COALESCE(%s, last_approved_hash),
                        last_check_status = 'up_to_date',
                        updated_at = NOW()
                    WHERE modulo = %s
                    """,
                    (rev.get("drive_hash"), MODULO),
                )
        conn.commit()

    for k in ("created_at", "reviewed_at"):
        if hasattr(approved_rev.get(k), "isoformat"):
            approved_rev[k] = approved_rev[k].isoformat()

    return {
        "message": "Cierres aprobados y respaldados en el servidor",
        "applied_counts": applied_counts,
        "revision": approved_rev,
    }


@router.post("/revisions/{revision_id}/reject")
def reject_cierres_revision(
    revision_id: int,
    data: Optional[RevisionRejectIn] = None,
    admin: TokenData = Depends(require_admin),
):
    """Descarta cambios entrantes en Cierres manteniendo el respaldo del servidor."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute(
                "SELECT * FROM crm.separaciones_revisions WHERE id = %s AND modulo = %s",
                (revision_id, MODULO),
            )
            rev = cur.fetchone()
            if not rev:
                raise HTTPException(status_code=404, detail="Revisión no encontrada")
            if rev["status"] != "pending":
                raise HTTPException(status_code=400, detail=f"La revisión ya está en estado '{rev['status']}'")

            new_msg = rev.get("message") or "Revisión descartada"
            if data and data.reason and data.reason.strip():
                new_msg = f"{new_msg} · Rechazada: {data.reason.strip()}"

            cur.execute(
                """
                UPDATE crm.separaciones_revisions
                SET status = 'rejected', message = %s,
                    reviewed_by = %s::uuid, reviewed_by_name = %s, reviewed_at = NOW()
                WHERE id = %s
                """,
                (new_msg, actor_id, user_name, revision_id),
            )
            if rev.get("source") != "excel_upload":
                cur.execute(
                    "UPDATE crm.separaciones_drive_config SET last_check_status = 'rejected_keep_crm', updated_at = NOW() WHERE modulo = %s",
                    (MODULO,),
                )
        conn.commit()
    return {"message": "Revisión descartada; prevalecen los datos del CRM"}


@router.get("/export")
def export_cierres_excel(
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    admin: TokenData = Depends(require_admin),
):
    """Exporta Cierres de Ventas desde PostgreSQL a Excel (.xlsx)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            rows = _fetch_filtered_cierres(cur, anio=anio, mes=mes)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cierres de Ventas"

    hdr_fill = PatternFill(start_color="1F1D5C", end_color="1F1D5C", fill_type="solid")
    hdr_font = Font(color="FFFFFF", bold=True)

    headers = [
        "Año", "Mes", "Asesor", "Proyecto", "Lote", "Nombre del Cliente",
        "Distrito Origen", "Fecha Ingreso Inicial", "Monto Total de Venta", "Moneda",
        "% de Inicial", "Cantidad de Inicial", "Tipo de Cambio",
        "Estrategia", "Área", "Edad", "Observaciones", "Origen",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = hdr_fill
        cell.font = hdr_font

    for r in rows:
        ws.append([
            r["anio"], r["mes_nombre"], r.get("asesor") or "", r.get("proyecto") or "",
            r.get("lote") or "", r.get("cliente_nombre") or "", r.get("distrito") or "",
            r.get("fecha_ingreso_inicial") or "", r.get("monto_total") if r.get("monto_total") is not None else "",
            r.get("moneda") or "SOLES", r.get("pct_inicial_raw") or "",
            r.get("cantidad_inicial") if r.get("cantidad_inicial") is not None else "",
            r.get("tipo_cambio") if r.get("tipo_cambio") is not None else "",
            r.get("estrategia") or "", r.get("area") or "",
            r.get("edad") if r.get("edad") is not None else "",
            r.get("observaciones") or "", r.get("origen") or "crm",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"cierres_lotes_{anio or 'todos'}_{mes or 'todos'}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/{registro_id}")
def update_cierre_registro(
    registro_id: int,
    data: CierreUpdateIn,
    admin: TokenData = Depends(require_admin),
):
    """Edita un cierre en PostgreSQL registrando diff de campos en historial."""
    sent = data.model_dump(exclude_unset=True)
    if not sent:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute("SELECT * FROM crm.cierres_lotes_registros WHERE id = %s AND activo = TRUE", (registro_id,))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Registro de cierre no encontrado")
            existing = dict(existing)

            updates: dict[str, Any] = {}
            if "anio" in sent and sent["anio"]:
                updates["anio"] = int(sent["anio"])
            if "mes" in sent and sent["mes"] and 1 <= int(sent["mes"]) <= 12:
                updates["mes"] = int(sent["mes"])
                updates["mes_nombre"] = MONTH_NAMES[int(sent["mes"])]
            for text_col in ("asesor", "proyecto", "lote", "cliente_nombre", "distrito", "estrategia", "area", "observaciones"):
                if text_col in sent:
                    updates[text_col] = sds._clean_str(sent[text_col])
            if "fecha_ingreso_inicial" in sent:
                fi_str, fi_date = sds.parse_date_flexible(sent["fecha_ingreso_inicial"])
                updates["fecha_ingreso_inicial"] = fi_str
                updates["fecha_ingreso_date"] = fi_date
            if "moneda" in sent:
                updates["moneda"] = _normalize_moneda(sent["moneda"])
            if "pct_inicial_raw" in sent:
                pct_num, pct_raw = sds._parse_pct_inicial(sent["pct_inicial_raw"])
                updates["pct_inicial"] = pct_num
                updates["pct_inicial_raw"] = pct_raw
            for num_col in ("monto_total", "edad", "cantidad_inicial", "tipo_cambio", "lead_id"):
                if num_col in sent:
                    updates[num_col] = sent[num_col]

            if not updates:
                raise HTTPException(status_code=400, detail="Sin cambios válidos")

            set_parts = [f"{col} = %s" for col in updates]
            params = list(updates.values()) + [actor_id, registro_id]
            set_parts.append("updated_by = %s::uuid")
            set_parts.append("updated_at = NOW()")

            cur.execute(
                f"UPDATE crm.cierres_lotes_registros SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                params,
            )
            updated = dict(cur.fetchone())

            before_snap = sds._serialize_cierre_snapshot(existing)
            after_snap = sds._serialize_cierre_snapshot(updated)
            changed_fields = []
            for field_key, field_label in sds.CIERRES_COMPARE_FIELDS:
                if (before_snap.get(field_key) or "") != (after_snap.get(field_key) or ""):
                    changed_fields.append({
                        "field": field_key,
                        "label": field_label,
                        "before": before_snap.get(field_key),
                        "after": after_snap.get(field_key),
                    })

            if changed_fields:
                rev_num = _next_revision_number(cur)
                diff_entry = [{
                    "change_type": "modified",
                    "sync_key": updated.get("sync_key") or f"crm-cie-{registro_id}",
                    "registro_id": registro_id,
                    "label": sds._cierre_row_label(after_snap),
                    "before": before_snap,
                    "after": after_snap,
                    "changed_fields": changed_fields,
                }]
                cur.execute(
                    """
                    INSERT INTO crm.separaciones_revisions (
                        modulo, revision_number, source, status, summary_json, diff_json,
                        message, created_by, created_by_name, reviewed_by, reviewed_by_name, reviewed_at
                    )
                    VALUES (%s, %s, 'crm_manual', 'applied', %s::jsonb, %s::jsonb, %s, %s::uuid, %s, %s::uuid, %s, NOW())
                    RETURNING id
                    """,
                    (
                        MODULO,
                        rev_num,
                        json.dumps({"added": 0, "modified": 1, "removed": 0}),
                        json.dumps(diff_entry),
                        f"Edición cierre en CRM: {sds._cierre_row_label(after_snap)}",
                        actor_id, user_name, actor_id, user_name,
                    ),
                )
                rev_id = cur.fetchone()["id"]
                for cf in changed_fields:
                    cur.execute(
                        """
                        INSERT INTO crm.separaciones_audit_log (
                            modulo, cierre_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                        )
                        VALUES (%s, %s, %s, 'update', %s, %s, %s, %s::uuid, %s)
                        """,
                        (MODULO, registro_id, rev_id, cf["field"], cf["before"], cf["after"], actor_id, user_name),
                    )
        conn.commit()

    return _serialize_cierre_out(updated)


@router.delete("/{registro_id}")
def delete_cierre_registro(
    registro_id: int,
    admin: TokenData = Depends(require_admin),
):
    """Elimina lógicamente un cierre dejando constancia en revisiones y auditoría."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute(
                """
                UPDATE crm.cierres_lotes_registros
                SET activo = FALSE, updated_by = %s::uuid, updated_at = NOW()
                WHERE id = %s AND activo = TRUE
                RETURNING *
                """,
                (actor_id, registro_id),
            )
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(status_code=404, detail="Registro de cierre no encontrado")
            deleted = dict(deleted)
            snap = sds._serialize_cierre_snapshot(deleted)
            rev_num = _next_revision_number(cur)
            diff_entry = [{
                "change_type": "removed",
                "sync_key": deleted.get("sync_key") or f"crm-cie-{registro_id}",
                "registro_id": registro_id,
                "label": sds._cierre_row_label(snap),
                "before": snap,
                "after": None,
                "changed_fields": [],
            }]
            cur.execute(
                """
                INSERT INTO crm.separaciones_revisions (
                    modulo, revision_number, source, status, summary_json, diff_json,
                    message, created_by, created_by_name, reviewed_by, reviewed_by_name, reviewed_at
                )
                VALUES (%s, %s, 'crm_manual', 'applied', %s::jsonb, %s::jsonb, %s, %s::uuid, %s, %s::uuid, %s, NOW())
                RETURNING id
                """,
                (
                    MODULO,
                    rev_num,
                    json.dumps({"added": 0, "modified": 0, "removed": 1}),
                    json.dumps(diff_entry),
                    f"Cierre eliminado en CRM: {sds._cierre_row_label(snap)}",
                    actor_id, user_name, actor_id, user_name,
                ),
            )
            rev_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO crm.separaciones_audit_log (
                    modulo, cierre_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                )
                VALUES (%s, %s, %s, 'delete', 'registro', %s, NULL, %s::uuid, %s)
                """,
                (MODULO, registro_id, rev_id, sds._cierre_row_label(snap), actor_id, user_name),
            )
        conn.commit()
    return {"message": "Registro de cierre eliminado", "id": registro_id}

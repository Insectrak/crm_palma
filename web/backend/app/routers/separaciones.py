"""
separaciones.py — Módulo exclusivo Admin para control de Separaciones y Cierres:
- Respaldo y fuente de verdad en PostgreSQL (editable desde el CRM).
- Detección de cambios desde el Google Sheet en Drive y flujo de revisión/aprobación estilo Git.
- Historial de versiones (commits/revisiones) y auditoría de campos.
- Exportación a Excel (.xlsx).
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.services import separaciones_drive_service as sds

logger = logging.getLogger(__name__)
LIMA_TZ = ZoneInfo("America/Lima")

router = APIRouter(prefix="/api/separaciones", tags=["Separaciones y Cierres"])

MONTH_NAMES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL",
    5: "MAYO", 6: "JUNIO", 7: "JULIO", 8: "AGOSTO",
    9: "SETIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE",
}


class RegistroCreateIn(BaseModel):
    tipo: str = "separacion"  # 'separacion' | 'cierre'
    anio: int = 2026
    mes: int
    asesor: Optional[str] = None
    proyecto: str
    lote: str
    fecha_ingreso: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    monto_raw: Optional[str] = None
    estrategia: Optional[str] = None
    estado: Optional[str] = None
    observaciones: Optional[str] = None
    lead_id: Optional[int] = None


class RegistroUpdateIn(BaseModel):
    tipo: Optional[str] = None
    anio: Optional[int] = None
    mes: Optional[int] = None
    asesor: Optional[str] = None
    proyecto: Optional[str] = None
    lote: Optional[str] = None
    fecha_ingreso: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    monto_raw: Optional[str] = None
    estrategia: Optional[str] = None
    estado: Optional[str] = None
    observaciones: Optional[str] = None
    lead_id: Optional[int] = None


class DriveConfigIn(BaseModel):
    sheet_url: str


class RevisionApproveIn(BaseModel):
    selected_keys: Optional[list[str]] = None
    message: Optional[str] = None


class RevisionRejectIn(BaseModel):
    reason: Optional[str] = None


def _resolve_actor(cur, user: TokenData) -> tuple[Optional[str], str]:
    """Resuelve (user_id_existente_en_db, nombre_legible) evitando fallos FK con tokens sintéticos."""
    fallback = (
        (getattr(user, "nombre_completo", None) or "").strip()
        or getattr(user, "email", None)
        or "Admin"
    )
    uid = getattr(user, "user_id", None)
    if not uid:
        return None, fallback
    try:
        cur.execute(
            """
            SELECT id::text AS id,
                   TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre,
                   email
            FROM auth.users
            WHERE id = %s::uuid
            """,
            (str(uid),),
        )
        row = cur.fetchone()
        if row:
            nombre = (row.get("nombre") or "").strip() or row.get("email") or fallback
            return row["id"], nombre
    except Exception:
        pass
    return None, fallback


def _next_revision_number(cur) -> int:
    cur.execute("SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_rev FROM crm.separaciones_revisions")
    row = cur.fetchone()
    return int(row["next_rev"]) if row else 1


def _enrich_registro_out(r: dict[str, Any], today_lima: date) -> dict[str, Any]:
    out = dict(r)
    for dt_k in ("fecha_ingreso_date", "fecha_vencimiento_date", "created_at", "updated_at"):
        val = out.get(dt_k)
        if hasattr(val, "isoformat"):
            out[dt_k] = val.isoformat()
    if out.get("monto_numerico") is not None:
        out["monto_numerico"] = float(out["monto_numerico"])

    est = (out.get("estado") or "").strip().upper()
    fv = r.get("fecha_vencimiento_date")
    if isinstance(fv, str):
        try:
            fv = date.fromisoformat(fv)
        except ValueError:
            fv = None

    vigencia_status = None
    dias_restantes = None
    if out.get("tipo") == "separacion":
        if est in ("VENDIDO", "VENTA", "VENTAS"):
            vigencia_status = "vendida"
        elif est in ("LIBERADO", "NO VA", "SOLICITUD DE DEVOLUCIÓN", "ANULADO"):
            vigencia_status = "liberada"
        elif est == "SEPARADO" or not est:
            if fv is not None:
                dias_restantes = (fv - today_lima).days
                vigencia_status = "vigente" if dias_restantes >= 0 else "vencida"
            else:
                vigencia_status = "vigente"
        else:
            vigencia_status = "otra"

    out["vigencia_status"] = vigencia_status
    out["dias_para_vencer"] = dias_restantes
    return out


def _compute_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sep_rows = [r for r in rows if r.get("tipo") == "separacion"]
    cie_rows = [r for r in rows if r.get("tipo") == "cierre"]

    vigentes = sum(1 for r in sep_rows if r.get("vigencia_status") == "vigente")
    vencidas = sum(1 for r in sep_rows if r.get("vigencia_status") == "vencida")
    convertidas = sum(1 for r in sep_rows if r.get("vigencia_status") == "vendida")
    liberadas = sum(1 for r in sep_rows if r.get("vigencia_status") == "liberada")

    monto_pen = sum(
        (r.get("monto_numerico") or 0)
        for r in sep_rows
        if (r.get("moneda") or "PEN") == "PEN"
    )
    monto_usd = sum(
        (r.get("monto_numerico") or 0)
        for r in sep_rows
        if r.get("moneda") == "USD"
    )

    estrategias_sep: dict[str, int] = {}
    for r in sep_rows:
        est = (r.get("estrategia") or "SIN ESTRATEGIA").strip()
        estrategias_sep[est] = estrategias_sep.get(est, 0) + 1

    estrategias_cie: dict[str, int] = {}
    for r in cie_rows:
        est = (r.get("estrategia") or "SIN ESTRATEGIA").strip()
        estrategias_cie[est] = estrategias_cie.get(est, 0) + 1

    asesores_sep: dict[str, dict[str, Any]] = {}
    for r in sep_rows:
        ase = (r.get("asesor") or "SIN ASESOR").strip()
        if ase not in asesores_sep:
            asesores_sep[ase] = {"asesor": ase, "total": 0, "vendidas": 0, "vigentes": 0, "vencidas": 0, "liberadas": 0}
        asesores_sep[ase]["total"] += 1
        vs = r.get("vigencia_status")
        if vs == "vendida":
            asesores_sep[ase]["vendidas"] += 1
        elif vs == "vigente":
            asesores_sep[ase]["vigentes"] += 1
        elif vs == "vencida":
            asesores_sep[ase]["vencidas"] += 1
        elif vs == "liberada":
            asesores_sep[ase]["liberadas"] += 1

    return {
        "total_separaciones": len(sep_rows),
        "separaciones_vigentes": vigentes,
        "separaciones_vencidas": vencidas,
        "separaciones_vendidas": convertidas,
        "separaciones_liberadas": liberadas,
        "total_cierres": len(cie_rows),
        "monto_total_pen": round(monto_pen, 2),
        "monto_total_usd": round(monto_usd, 2),
        "resumen_estrategia_separaciones": [
            {"estrategia": k, "total": v}
            for k, v in sorted(estrategias_sep.items(), key=lambda x: (-x[1], x[0]))
        ],
        "resumen_estrategia_cierres": [
            {"estrategia": k, "total": v}
            for k, v in sorted(estrategias_cie.items(), key=lambda x: (-x[1], x[0]))
        ],
        "resumen_asesores": sorted(asesores_sep.values(), key=lambda x: (-x["total"], x["asesor"])),
    }


def _fetch_filtered_rows(
    cur,
    *,
    anio: Optional[int] = None,
    mes: Optional[int] = None,
    tipo: Optional[str] = None,
    proyecto: Optional[str] = None,
    asesor: Optional[str] = None,
    estrategia: Optional[str] = None,
    estado: Optional[str] = None,
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
    if tipo in ("separacion", "cierre"):
        filters.append("tipo = %s")
        params.append(tipo)
    if proyecto:
        filters.append("LOWER(TRIM(COALESCE(proyecto, ''))) = LOWER(TRIM(%s))")
        params.append(proyecto)
    if asesor:
        filters.append("LOWER(TRIM(COALESCE(asesor, ''))) = LOWER(TRIM(%s))")
        params.append(asesor)
    if estrategia:
        filters.append("LOWER(TRIM(COALESCE(estrategia, ''))) = LOWER(TRIM(%s))")
        params.append(estrategia)
    if estado:
        filters.append("UPPER(TRIM(COALESCE(estado, ''))) = UPPER(TRIM(%s))")
        params.append(estado)
    if search and search.strip():
        pat = f"%{search.strip()}%"
        filters.append(
            "(COALESCE(asesor, '') ILIKE %s OR COALESCE(proyecto, '') ILIKE %s "
            "OR COALESCE(lote, '') ILIKE %s OR COALESCE(estrategia, '') ILIKE %s "
            "OR COALESCE(observaciones, '') ILIKE %s)"
        )
        params.extend([pat, pat, pat, pat, pat])

    where_sql = " AND ".join(filters)
    cur.execute(
        f"""
        SELECT *
        FROM crm.separaciones_registros
        WHERE {where_sql}
        ORDER BY anio DESC, mes DESC, tipo DESC, orden_fila ASC, id ASC
        """,
        params,
    )
    today_lima = datetime.now(LIMA_TZ).date()
    return [_enrich_registro_out(dict(r), today_lima) for r in cur.fetchall()]


@router.get("/meta")
def get_separaciones_meta(admin: TokenData = Depends(require_admin)):
    """Devuelve períodos disponibles, catálogos dinámicos, estado de Drive y revisiones pendientes."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT anio, mes, mes_nombre
                FROM crm.separaciones_registros
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
                    ARRAY_AGG(DISTINCT UPPER(TRIM(estado))) FILTER (WHERE TRIM(COALESCE(estado, '')) <> '') AS estados,
                    COUNT(*)::int AS total_registros
                FROM crm.separaciones_registros
                WHERE activo = TRUE
                """
            )
            cats = cur.fetchone() or {}

            cur.execute("SELECT * FROM crm.separaciones_drive_config WHERE id = 1")
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
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            pending = cur.fetchone()
            pending_out = dict(pending) if pending else None
            if pending_out and hasattr(pending_out.get("created_at"), "isoformat"):
                pending_out["created_at"] = pending_out["created_at"].isoformat()

            cur.execute("SELECT COUNT(*)::int AS total_revs FROM crm.separaciones_revisions WHERE status IN ('approved', 'applied')")
            rev_count = (cur.fetchone() or {}).get("total_revs", 0)

    return {
        "periodos": periodos,
        "catalogos": {
            "proyectos": sorted(cats.get("proyectos") or []),
            "asesores": sorted(cats.get("asesores") or []),
            "estrategias": sorted(cats.get("estrategias") or []),
            "estados": sorted(cats.get("estados") or []),
        },
        "total_registros": cats.get("total_registros") or 0,
        "drive_config": drive_cfg_out,
        "pending_revision": pending_out,
        "total_revisions": rev_count,
    }


@router.get("")
def list_separaciones(
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    tipo: Optional[str] = Query(None),
    proyecto: Optional[str] = Query(None),
    asesor: Optional[str] = Query(None),
    estrategia: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    vigencia: Optional[str] = Query(None, description="vigente | vencida | vendida | liberada"),
    search: Optional[str] = Query(None),
    admin: TokenData = Depends(require_admin),
):
    """Lista separaciones y cierres respaldados en el servidor con resumen calculado."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            rows = _fetch_filtered_rows(
                cur,
                anio=anio,
                mes=mes,
                tipo=tipo,
                proyecto=proyecto,
                asesor=asesor,
                estrategia=estrategia,
                estado=estado,
                search=search,
            )

    if vigencia:
        vig_norm = vigencia.strip().lower()
        rows_filtered = [r for r in rows if r.get("vigencia_status") == vig_norm]
    else:
        rows_filtered = rows

    stats = _compute_stats(rows_filtered)
    return {
        "resumen": stats,
        "total": len(rows_filtered),
        "items": rows_filtered,
    }


@router.post("", status_code=201)
def create_separacion_registro(
    data: RegistroCreateIn,
    admin: TokenData = Depends(require_admin),
):
    """Crea una nueva separación o cierre en PostgreSQL y registra versión + auditoría."""
    if data.tipo not in ("separacion", "cierre"):
        raise HTTPException(status_code=400, detail="tipo debe ser 'separacion' o 'cierre'")
    if data.mes < 1 or data.mes > 12:
        raise HTTPException(status_code=400, detail="mes inválido (1-12)")

    mes_nombre = MONTH_NAMES[data.mes]
    fi_str, fi_date = sds.parse_date_flexible(data.fecha_ingreso)
    fv_str, fv_date = sds.parse_date_flexible(data.fecha_vencimiento)
    monto_str, monto_num, moneda = sds.parse_money(data.monto_raw)
    estado_val = (data.estado or ("SEPARADO" if data.tipo == "separacion" else "VENDIDO")).strip().upper()

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute(
                """
                SELECT COALESCE(MAX(orden_fila), 0) + 1 AS next_orden
                FROM crm.separaciones_registros
                WHERE anio = %s AND mes = %s AND activo = TRUE
                """,
                (data.anio, data.mes),
            )
            next_orden = int((cur.fetchone() or {}).get("next_orden", 1))

            cur.execute(
                """
                INSERT INTO crm.separaciones_registros (
                    tipo, anio, mes, mes_nombre, orden_fila,
                    asesor, proyecto, lote,
                    fecha_ingreso, fecha_ingreso_date,
                    fecha_vencimiento, fecha_vencimiento_date,
                    monto_raw, monto_numerico, moneda,
                    estrategia, estado, observaciones,
                    origen, lead_id, created_by, updated_by
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    'crm', %s, %s::uuid, %s::uuid
                )
                RETURNING *
                """,
                (
                    data.tipo, data.anio, data.mes, mes_nombre, next_orden,
                    sds._clean_str(data.asesor), sds._clean_str(data.proyecto), sds._clean_str(data.lote),
                    fi_str, fi_date,
                    fv_str, fv_date,
                    monto_str, monto_num, moneda,
                    sds._clean_str(data.estrategia), estado_val, sds._clean_str(data.observaciones),
                    data.lead_id, actor_id, actor_id,
                ),
            )
            created = dict(cur.fetchone())

            rev_num = _next_revision_number(cur)
            snap = sds._serialize_row_snapshot(created)
            diff_entry = [{
                "change_type": "added",
                "sync_key": f"crm-{created['id']}",
                "registro_id": created["id"],
                "label": sds._row_label(snap),
                "before": None,
                "after": snap,
                "changed_fields": [],
            }]
            cur.execute(
                """
                INSERT INTO crm.separaciones_revisions (
                    revision_number, source, status, summary_json, diff_json,
                    message, created_by, created_by_name, reviewed_by, reviewed_by_name, reviewed_at
                )
                VALUES (%s, 'crm_manual', 'applied', %s::jsonb, %s::jsonb, %s, %s::uuid, %s, %s::uuid, %s, NOW())
                RETURNING id
                """,
                (
                    rev_num,
                    json.dumps({"added": 1, "modified": 0, "removed": 0}),
                    json.dumps(diff_entry),
                    f"Alta manual en CRM: {sds._row_label(snap)}",
                    actor_id, user_name, actor_id, user_name,
                ),
            )
            rev_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO crm.separaciones_audit_log (
                    registro_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                )
                VALUES (%s, %s, 'create', 'registro', NULL, %s, %s::uuid, %s)
                """,
                (created["id"], rev_id, sds._row_label(snap), actor_id, user_name),
            )
        conn.commit()

    return _enrich_registro_out(created, datetime.now(LIMA_TZ).date())


@router.patch("/{registro_id}")
def update_separacion_registro(
    registro_id: int,
    data: RegistroUpdateIn,
    admin: TokenData = Depends(require_admin),
):
    """Edita un registro en PostgreSQL registrando diff de campos en versión e historial."""
    sent = data.model_dump(exclude_unset=True)
    if not sent:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute("SELECT * FROM crm.separaciones_registros WHERE id = %s AND activo = TRUE", (registro_id,))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
            existing = dict(existing)

            updates: dict[str, Any] = {}
            if "tipo" in sent and sent["tipo"] in ("separacion", "cierre"):
                updates["tipo"] = sent["tipo"]
            if "anio" in sent and sent["anio"]:
                updates["anio"] = int(sent["anio"])
            if "mes" in sent and sent["mes"] and 1 <= int(sent["mes"]) <= 12:
                updates["mes"] = int(sent["mes"])
                updates["mes_nombre"] = MONTH_NAMES[int(sent["mes"])]
            for text_col in ("asesor", "proyecto", "lote", "estrategia", "observaciones"):
                if text_col in sent:
                    updates[text_col] = sds._clean_str(sent[text_col])
            if "estado" in sent:
                est_clean = sds._clean_str(sent["estado"])
                updates["estado"] = est_clean.upper() if est_clean else None
            if "fecha_ingreso" in sent:
                fi_str, fi_date = sds.parse_date_flexible(sent["fecha_ingreso"])
                updates["fecha_ingreso"] = fi_str
                updates["fecha_ingreso_date"] = fi_date
            if "fecha_vencimiento" in sent:
                fv_str, fv_date = sds.parse_date_flexible(sent["fecha_vencimiento"])
                updates["fecha_vencimiento"] = fv_str
                updates["fecha_vencimiento_date"] = fv_date
            if "monto_raw" in sent:
                m_str, m_num, moneda = sds.parse_money(sent["monto_raw"])
                updates["monto_raw"] = m_str
                updates["monto_numerico"] = m_num
                updates["moneda"] = moneda
            if "lead_id" in sent:
                updates["lead_id"] = sent["lead_id"]

            if not updates:
                raise HTTPException(status_code=400, detail="Sin cambios válidos")

            set_parts = [f"{col} = %s" for col in updates]
            params = list(updates.values()) + [actor_id, registro_id]
            set_parts.append("updated_by = %s::uuid")
            set_parts.append("updated_at = NOW()")

            cur.execute(
                f"UPDATE crm.separaciones_registros SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                params,
            )
            updated = dict(cur.fetchone())

            before_snap = sds._serialize_row_snapshot(existing)
            after_snap = sds._serialize_row_snapshot(updated)
            changed_fields = []
            for field_key, field_label in sds.COMPARE_FIELDS:
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
                    "sync_key": updated.get("sync_key") or f"crm-{registro_id}",
                    "registro_id": registro_id,
                    "label": sds._row_label(after_snap),
                    "before": before_snap,
                    "after": after_snap,
                    "changed_fields": changed_fields,
                }]
                cur.execute(
                    """
                    INSERT INTO crm.separaciones_revisions (
                        revision_number, source, status, summary_json, diff_json,
                        message, created_by, created_by_name, reviewed_by, reviewed_by_name, reviewed_at
                    )
                    VALUES (%s, 'crm_manual', 'applied', %s::jsonb, %s::jsonb, %s, %s::uuid, %s, %s::uuid, %s, NOW())
                    RETURNING id
                    """,
                    (
                        rev_num,
                        json.dumps({"added": 0, "modified": 1, "removed": 0}),
                        json.dumps(diff_entry),
                        f"Edición en CRM: {sds._row_label(after_snap)}",
                        actor_id, user_name, actor_id, user_name,
                    ),
                )
                rev_id = cur.fetchone()["id"]
                for cf in changed_fields:
                    cur.execute(
                        """
                        INSERT INTO crm.separaciones_audit_log (
                            registro_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                        )
                        VALUES (%s, %s, 'update', %s, %s, %s, %s::uuid, %s)
                        """,
                        (registro_id, rev_id, cf["field"], cf["before"], cf["after"], actor_id, user_name),
                    )
        conn.commit()

    return _enrich_registro_out(updated, datetime.now(LIMA_TZ).date())


@router.delete("/{registro_id}")
def delete_separacion_registro(
    registro_id: int,
    admin: TokenData = Depends(require_admin),
):
    """Elimina lógicamente un registro dejando constancia en revisiones y auditoría."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute(
                """
                UPDATE crm.separaciones_registros
                SET activo = FALSE, updated_by = %s::uuid, updated_at = NOW()
                WHERE id = %s AND activo = TRUE
                RETURNING *
                """,
                (actor_id, registro_id),
            )
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
            deleted = dict(deleted)
            snap = sds._serialize_row_snapshot(deleted)
            rev_num = _next_revision_number(cur)
            diff_entry = [{
                "change_type": "removed",
                "sync_key": deleted.get("sync_key") or f"crm-{registro_id}",
                "registro_id": registro_id,
                "label": sds._row_label(snap),
                "before": snap,
                "after": None,
                "changed_fields": [],
            }]
            cur.execute(
                """
                INSERT INTO crm.separaciones_revisions (
                    revision_number, source, status, summary_json, diff_json,
                    message, created_by, created_by_name, reviewed_by, reviewed_by_name, reviewed_at
                )
                VALUES (%s, 'crm_manual', 'applied', %s::jsonb, %s::jsonb, %s, %s::uuid, %s, %s::uuid, %s, NOW())
                RETURNING id
                """,
                (
                    rev_num,
                    json.dumps({"added": 0, "modified": 0, "removed": 1}),
                    json.dumps(diff_entry),
                    f"Eliminado en CRM: {sds._row_label(snap)}",
                    actor_id, user_name, actor_id, user_name,
                ),
            )
            rev_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO crm.separaciones_audit_log (
                    registro_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                )
                VALUES (%s, %s, 'delete', 'registro', %s, NULL, %s::uuid, %s)
                """,
                (registro_id, rev_id, sds._row_label(snap), actor_id, user_name),
            )
        conn.commit()
    return {"message": "Registro eliminado", "id": registro_id}


@router.put("/drive/config")
def update_drive_config(
    data: DriveConfigIn,
    admin: TokenData = Depends(require_admin),
):
    """Permite actualizar el enlace del Google Sheet monitoreado."""
    sheet_id, gid = sds.extract_spreadsheet_id_and_gid(data.sheet_url)
    if not sheet_id:
        raise HTTPException(status_code=400, detail="URL de Google Sheets inválida")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE crm.separaciones_drive_config
                SET spreadsheet_id = %s, gid = %s, sheet_url = %s, updated_at = NOW()
                WHERE id = 1
                RETURNING *
                """,
                (sheet_id, gid, data.sheet_url.strip()),
            )
            cfg = dict(cur.fetchone())
        conn.commit()
    return cfg


@router.post("/drive/check")
def check_drive_changes(admin: TokenData = Depends(require_admin)):
    """
    Consulta el Google Sheet en Drive, detecta cambios respecto al estado actual en el CRM
    y crea/actualiza una revisión pendiente estilo Git (sin sobreescribir automáticamente).
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute("SELECT * FROM crm.separaciones_drive_config WHERE id = 1")
            cfg = cur.fetchone()
            spreadsheet_id = (cfg or {}).get("spreadsheet_id") or sds.DEFAULT_SPREADSHEET_ID
            gid = (cfg or {}).get("gid") or sds.DEFAULT_GID

            try:
                csv_text, drive_hash = sds.fetch_drive_csv(spreadsheet_id, gid)
                drive_rows = sds.parse_drive_csv(csv_text)
            except Exception as exc:
                logger.warning("[separaciones_drive] error consultando Drive: %s", exc)
                cur.execute(
                    """
                    UPDATE crm.separaciones_drive_config
                    SET last_checked_at = NOW(), last_check_status = 'error',
                        last_check_error = %s, updated_at = NOW()
                    WHERE id = 1
                    """,
                    (str(exc)[:500],),
                )
                conn.commit()
                raise HTTPException(status_code=502, detail=f"No se pudo leer el Excel de Drive: {exc}")

            cur.execute("SELECT * FROM crm.separaciones_registros WHERE activo = TRUE")
            crm_rows = [dict(r) for r in cur.fetchall()]

            diff_res = sds.compute_drive_diff(crm_rows, drive_rows)
            summary = diff_res["summary"]
            has_changes = (summary["added"] + summary["modified"] + summary["removed"]) > 0
            source = "drive_initial" if len(crm_rows) == 0 else "drive_sync"

            pending_rev = None
            if has_changes:
                cur.execute(
                    "SELECT * FROM crm.separaciones_revisions WHERE status = 'pending' ORDER BY created_at DESC LIMIT 1"
                )
                existing_pending = cur.fetchone()
                msg = (
                    f"Importación inicial desde Drive ({summary['added']} registros)"
                    if source == "drive_initial"
                    else f"Cambios detectados en Drive: +{summary['added']} nuevos, ~{summary['modified']} modificados, -{summary['removed']} quitados"
                )
                if existing_pending:
                    cur.execute(
                        """
                        UPDATE crm.separaciones_revisions
                        SET source = %s, drive_hash = %s, summary_json = %s::jsonb,
                            diff_json = %s::jsonb, message = %s, created_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (source, drive_hash, json.dumps(summary), json.dumps(diff_res["changes"]), msg, existing_pending["id"]),
                    )
                    pending_rev = dict(cur.fetchone())
                else:
                    rev_num = _next_revision_number(cur)
                    cur.execute(
                        """
                        INSERT INTO crm.separaciones_revisions (
                            revision_number, source, status, drive_hash, summary_json, diff_json,
                            message, created_by, created_by_name
                        )
                        VALUES (%s, %s, 'pending', %s, %s::jsonb, %s::jsonb, %s, %s::uuid, %s)
                        RETURNING *
                        """,
                        (rev_num, source, drive_hash, json.dumps(summary), json.dumps(diff_res["changes"]), msg, actor_id, user_name),
                    )
                    pending_rev = dict(cur.fetchone())
            else:
                # Si ya no hay diferencias, limpiar cualquier revisión pendiente obsoleta
                cur.execute(
                    """
                    UPDATE crm.separaciones_revisions
                    SET status = 'rejected', reviewed_by = %s::uuid, reviewed_by_name = %s, reviewed_at = NOW()
                    WHERE status = 'pending'
                    """,
                    (actor_id, user_name),
                )

            cur.execute(
                """
                UPDATE crm.separaciones_drive_config
                SET last_checked_at = NOW(), last_seen_hash = %s,
                    last_check_status = %s, last_check_error = NULL, updated_at = NOW()
                WHERE id = 1
                """,
                (drive_hash, "changes_pending" if has_changes else "up_to_date"),
            )
        conn.commit()

    if pending_rev and hasattr(pending_rev.get("created_at"), "isoformat"):
        pending_rev["created_at"] = pending_rev["created_at"].isoformat()

    return {
        "has_changes": has_changes,
        "drive_hash": drive_hash,
        "summary": summary,
        "pending_revision": pending_rev,
    }


@router.get("/revisions")
def list_separaciones_revisions(
    limit: int = Query(50, ge=1, le=200),
    admin: TokenData = Depends(require_admin),
):
    """Lista el historial de versiones / commits estilo Git."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM crm.separaciones_revisions
                ORDER BY revision_number DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k in ("created_at", "reviewed_at"):
            if hasattr(r.get(k), "isoformat"):
                r[k] = r[k].isoformat()
    return {"items": rows}


@router.post("/revisions/{revision_id}/approve")
def approve_drive_revision(
    revision_id: int,
    data: RevisionApproveIn,
    admin: TokenData = Depends(require_admin),
):
    """Aprueba e incorpora en PostgreSQL los cambios seleccionados desde Drive (merge estilo Git)."""
    selected_set = set(data.selected_keys) if data.selected_keys is not None else None

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute("SELECT * FROM crm.separaciones_revisions WHERE id = %s", (revision_id,))
            rev = cur.fetchone()
            if not rev:
                raise HTTPException(status_code=404, detail="Revisión no encontrada")
            if rev["status"] != "pending":
                raise HTTPException(status_code=400, detail=f"La revisión ya está en estado '{rev['status']}'")

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
                        INSERT INTO crm.separaciones_registros (
                            tipo, anio, mes, mes_nombre, orden_fila, sync_key,
                            asesor, proyecto, lote,
                            fecha_ingreso, fecha_ingreso_date,
                            fecha_vencimiento, fecha_vencimiento_date,
                            monto_raw, monto_numerico, moneda,
                            estrategia, estado, observaciones,
                            origen, created_by, updated_by
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s::date,
                            %s, %s::date,
                            %s, %s, %s,
                            %s, %s, %s,
                            'drive', %s::uuid, %s::uuid
                        )
                        RETURNING id
                        """,
                        (
                            after.get("tipo"), after.get("anio"), after.get("mes"), after.get("mes_nombre"),
                            after.get("orden_fila") or 0, sk,
                            after.get("asesor"), after.get("proyecto"), after.get("lote"),
                            after.get("fecha_ingreso"), after.get("fecha_ingreso_date"),
                            after.get("fecha_vencimiento"), after.get("fecha_vencimiento_date"),
                            after.get("monto_raw"), after.get("monto_numerico"), after.get("moneda") or "PEN",
                            after.get("estrategia"), after.get("estado"), after.get("observaciones"),
                            actor_id, actor_id,
                        ),
                    )
                    new_id = cur.fetchone()["id"]
                    cur.execute(
                        """
                        INSERT INTO crm.separaciones_audit_log (
                            registro_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                        )
                        VALUES (%s, %s, 'drive_approve_add', 'registro', NULL, %s, %s::uuid, %s)
                        """,
                        (new_id, revision_id, item.get("label"), actor_id, user_name),
                    )
                    applied_counts["added"] += 1
                    applied_items.append(item)

                elif ctype == "modified":
                    reg_id = item.get("registro_id")
                    if not reg_id:
                        cur.execute(
                            "SELECT id FROM crm.separaciones_registros WHERE sync_key = %s AND activo = TRUE LIMIT 1",
                            (sk,),
                        )
                        found = cur.fetchone()
                        reg_id = found["id"] if found else None
                    if reg_id:
                        cur.execute(
                            """
                            UPDATE crm.separaciones_registros
                            SET asesor = %s, proyecto = %s, lote = %s,
                                fecha_ingreso = %s, fecha_ingreso_date = %s::date,
                                fecha_vencimiento = %s, fecha_vencimiento_date = %s::date,
                                monto_raw = %s, monto_numerico = %s, moneda = %s,
                                estrategia = %s, estado = %s, observaciones = %s,
                                orden_fila = %s, updated_by = %s::uuid, updated_at = NOW()
                            WHERE id = %s
                            """,
                            (
                                after.get("asesor"), after.get("proyecto"), after.get("lote"),
                                after.get("fecha_ingreso"), after.get("fecha_ingreso_date"),
                                after.get("fecha_vencimiento"), after.get("fecha_vencimiento_date"),
                                after.get("monto_raw"), after.get("monto_numerico"), after.get("moneda") or "PEN",
                                after.get("estrategia"), after.get("estado"), after.get("observaciones"),
                                after.get("orden_fila") or 0, actor_id, reg_id,
                            ),
                        )
                        for cf in item.get("changed_fields") or []:
                            cur.execute(
                                """
                                INSERT INTO crm.separaciones_audit_log (
                                    registro_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                                )
                                VALUES (%s, %s, 'drive_approve_update', %s, %s, %s, %s::uuid, %s)
                                """,
                                (reg_id, revision_id, cf.get("field"), cf.get("before"), cf.get("after"), actor_id, user_name),
                            )
                        applied_counts["modified"] += 1
                        applied_items.append(item)

                elif ctype == "removed":
                    reg_id = item.get("registro_id")
                    if reg_id:
                        cur.execute(
                            """
                            UPDATE crm.separaciones_registros
                            SET activo = FALSE, updated_by = %s::uuid, updated_at = NOW()
                            WHERE id = %s AND activo = TRUE
                            """,
                            (actor_id, reg_id),
                        )
                        cur.execute(
                            """
                            INSERT INTO crm.separaciones_audit_log (
                                registro_id, revision_id, action, campo, valor_anterior, valor_nuevo, usuario_id, usuario_nombre
                            )
                            VALUES (%s, %s, 'drive_approve_remove', 'registro', %s, NULL, %s::uuid, %s)
                            """,
                            (reg_id, revision_id, item.get("label") or before.get("proyecto"), actor_id, user_name),
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

            cur.execute(
                """
                UPDATE crm.separaciones_drive_config
                SET last_approved_hash = COALESCE(%s, last_approved_hash),
                    last_check_status = 'up_to_date',
                    updated_at = NOW()
                WHERE id = 1
                """,
                (rev.get("drive_hash"),),
            )
        conn.commit()

    for k in ("created_at", "reviewed_at"):
        if hasattr(approved_rev.get(k), "isoformat"):
            approved_rev[k] = approved_rev[k].isoformat()

    return {
        "message": "Cambios aprobados y respaldados en el servidor",
        "applied_counts": applied_counts,
        "revision": approved_rev,
    }


@router.post("/revisions/{revision_id}/reject")
def reject_drive_revision(
    revision_id: int,
    data: Optional[RevisionRejectIn] = None,
    admin: TokenData = Depends(require_admin),
):
    """Descarta los cambios entrantes de Drive manteniendo intacta la información del servidor."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            actor_id, user_name = _resolve_actor(cur, admin)
            cur.execute("SELECT * FROM crm.separaciones_revisions WHERE id = %s", (revision_id,))
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
            cur.execute(
                "UPDATE crm.separaciones_drive_config SET last_check_status = 'rejected_keep_crm', updated_at = NOW() WHERE id = 1"
            )
        conn.commit()
    return {"message": "Revisión descartada; prevalecen los datos del CRM"}


@router.get("/export")
def export_separaciones_excel(
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    admin: TokenData = Depends(require_admin),
):
    """Exporta Separaciones y Cierres desde la base del servidor a Excel (.xlsx)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            rows = _fetch_filtered_rows(cur, anio=anio, mes=mes)

    wb = openpyxl.Workbook()
    ws_sep = wb.active
    ws_sep.title = "Separaciones"

    hdr_fill = PatternFill(start_color="1F1D5C", end_color="1F1D5C", fill_type="solid")
    hdr_font = Font(color="FFFFFF", bold=True)

    sep_headers = [
        "Año", "Mes", "Asesor", "Proyecto", "Lote",
        "Fecha Ingreso", "Fecha Vencimiento", "Vigencia",
        "Monto", "Moneda", "Estrategia", "Estado", "Observaciones", "Origen",
    ]
    ws_sep.append(sep_headers)
    for cell in ws_sep[1]:
        cell.fill = hdr_fill
        cell.font = hdr_font

    for r in rows:
        if r["tipo"] != "separacion":
            continue
        ws_sep.append([
            r["anio"], r["mes_nombre"], r["asesor"] or "", r["proyecto"] or "", r["lote"] or "",
            r["fecha_ingreso"] or "", r["fecha_vencimiento"] or "", (r["vigencia_status"] or "").upper(),
            r["monto_numerico"] if r["monto_numerico"] is not None else (r["monto_raw"] or ""),
            r["moneda"] or "PEN", r["estrategia"] or "", r["estado"] or "", r["observaciones"] or "", r["origen"],
        ])

    ws_cie = wb.create_sheet("Cierres y Ventas")
    cie_headers = ["Año", "Mes", "Proyecto", "Lote", "Estrategia", "Asesor", "Estado", "Observaciones", "Origen"]
    ws_cie.append(cie_headers)
    for cell in ws_cie[1]:
        cell.fill = hdr_fill
        cell.font = hdr_font

    for r in rows:
        if r["tipo"] != "cierre":
            continue
        ws_cie.append([
            r["anio"], r["mes_nombre"], r["proyecto"] or "", r["lote"] or "",
            r["estrategia"] or "", r["asesor"] or "", r["estado"] or "VENDIDO", r["observaciones"] or "", r["origen"],
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"separaciones_cierres_{anio or 'todos'}_{mes or 'todos'}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

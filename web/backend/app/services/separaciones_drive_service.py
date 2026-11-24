"""
separaciones_drive_service.py — Parser de Google Sheets (CIERRES y SEPARACIONES PALMA)
y motor de comparación / versionado estilo Git contra los registros en PostgreSQL.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import httpx

DEFAULT_SPREADSHEET_ID = "15ZbIPoJEWAajSUzjajE4350nT6XhjMSW1FqCBk_2Zew"
DEFAULT_GID = "0"

MONTH_MAP: dict[str, tuple[int, str]] = {
    "ENERO": (1, "ENERO"),
    "BNERO": (1, "ENERO"),  # Typo presente en la hoja original (R208)
    "FEBRERO": (2, "FEBRERO"),
    "MARZO": (3, "MARZO"),
    "ABRIL": (4, "ABRIL"),
    "MAYO": (5, "MAYO"),
    "JUNIO": (6, "JUNIO"),
    "JULIO": (7, "JULIO"),
    "AGOSTO": (8, "AGOSTO"),
    "SETIEMBRE": (9, "SETIEMBRE"),
    "SEPTIEMBRE": (9, "SETIEMBRE"),
    "OCTUBRE": (10, "OCTUBRE"),
    "NOVIEMBRE": (11, "NOVIEMBRE"),
    "DICIEMBRE": (12, "DICIEMBRE"),
}

COMPARE_FIELDS: tuple[tuple[str, str], ...] = (
    ("asesor", "Asesor"),
    ("proyecto", "Proyecto"),
    ("lote", "Lote"),
    ("fecha_ingreso", "Fecha Ingreso"),
    ("fecha_vencimiento", "Fecha Vencimiento"),
    ("monto_raw", "Monto"),
    ("estrategia", "Estrategia"),
    ("estado", "Estado"),
    ("observaciones", "Observaciones"),
)


def extract_spreadsheet_id_and_gid(url: str) -> tuple[str, str]:
    """Extrae spreadsheet_id y gid desde un enlace estándar de Google Sheets."""
    s = (url or "").strip()
    m_id = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", s)
    sheet_id = m_id.group(1) if m_id else s
    m_gid = re.search(r"[#?&]gid=(\d+)", s)
    gid = m_gid.group(1) if m_gid else "0"
    return sheet_id, gid


def build_csv_export_url(spreadsheet_id: str, gid: str = "0") -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid or '0'}"


def fetch_drive_csv(spreadsheet_id: str, gid: str = "0", timeout: float = 20.0) -> tuple[str, str]:
    """Descarga el CSV de Google Drive y retorna (texto_csv, sha256_hex)."""
    url = build_csv_export_url(spreadsheet_id, gid)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": "PalmaCRM-Sync/1.0"})
        resp.raise_for_status()
        content_bytes = resp.content
        csv_text = content_bytes.decode("utf-8", errors="replace")
        # Verificar que no devolvio una pagina HTML de login (hoja privada)
        ct = (resp.headers.get("content-type") or "").lower()
        if "text/html" in ct and csv_text.lstrip().startswith("<"):
            raise ValueError("El documento de Google Drive no es público o requiere iniciar sesión.")
        digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        return csv_text, digest


def _clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = re.sub(r"\s+", " ", str(val)).strip()
    return s if s else None


def _norm_key_part(val: Any) -> str:
    s = (_clean_str(val) or "").upper()
    for src, dst in (("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("Ü", "U"), ("Ñ", "N")):
        s = s.replace(src, dst)
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s


def parse_date_flexible(raw: Optional[str]) -> tuple[Optional[str], Optional[date]]:
    """Convierte DD/MM/YYYY o D/M/YY a ('DD/MM/YYYY', date)."""
    s = _clean_str(raw)
    if not s:
        return None, None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.strftime("%d/%m/%Y"), d
        except ValueError:
            continue
    return s, None


def parse_money(raw: Optional[str]) -> tuple[Optional[str], Optional[float], str]:
    """Parsea montos como 'S/200.00', 'S/.500.00', '$19,000.00', '500'."""
    s = _clean_str(raw)
    if not s:
        return None, None, "PEN"
    moneda = "USD" if "$" in s else "PEN"
    cleaned = re.sub(r"[^\d.,-]", "", s).replace(",", "")
    if not cleaned:
        return s, None, moneda
    try:
        dec = Decimal(cleaned).quantize(Decimal("0.01"))
        return s, float(dec), moneda
    except (InvalidOperation, ValueError):
        return s, None, moneda


def _detect_month(cell_text: Optional[str]) -> Optional[tuple[int, str]]:
    s = (_clean_str(cell_text) or "").upper()
    return MONTH_MAP.get(s)


def parse_drive_csv(csv_text: str) -> list[dict[str, Any]]:
    """
    Parsea la hoja estructurada de CIERRES PALMA y SEPARACIONES PALMA en registros normalizados.
    Devuelve una lista ordenada de dicts listos para comparar o guardar en PostgreSQL.
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    current_year = 2026
    current_month: Optional[tuple[int, str]] = None

    # Índices por defecto según estructura estándar de la hoja
    c_proy_idx, c_lote_idx, c_est_idx = 3, 4, 5
    s_ase_idx, s_proy_idx, s_lote_idx = 14, 15, 16
    s_fing_idx, s_fvenc_idx, s_monto_idx = 17, 18, 19
    s_est_idx, s_estado_idx, s_obs_idx = 20, 21, 26

    parsed: list[dict[str, Any]] = []
    seen_counts: dict[str, int] = {}

    def _cell(row: list[str], idx: int) -> Optional[str]:
        if idx < 0 or idx >= len(row):
            return None
        return _clean_str(row[idx])

    def _next_sync_key(base_key: str) -> str:
        cnt = seen_counts.get(base_key, 0) + 1
        seen_counts[base_key] = cnt
        return f"{base_key}#{cnt}"

    for r_idx, row in enumerate(rows):
        c0 = _cell(row, 0)
        c1 = _cell(row, 1)

        # Detectar banner de año (ej. "CIERRES PALMA 2026", "CIERRES PALMA 2025")
        if c0 and ("CIERRES" in c0.upper() or "SEPARACIONES" in c0.upper()):
            m_year = re.search(r"\b(20\d{2})\b", c0)
            if m_year:
                current_year = int(m_year.group(1))
                current_month = None
            continue

        # Detectar encabezado de columna (ASESOR / PROYECTO / LOTE)
        row_upper = [(_clean_str(x) or "").upper() for x in row]
        if "ASESOR" in row_upper and "PROYECTO" in row_upper and "LOTE" in row_upper:
            s_ase_idx = row_upper.index("ASESOR")
            s_proy_idx = row_upper.index("PROYECTO", s_ase_idx)
            s_lote_idx = row_upper.index("LOTE", s_proy_idx)
            for idx_col, hdr in enumerate(row_upper):
                if idx_col > s_lote_idx:
                    if "INGRESO" in hdr:
                        s_fing_idx = idx_col
                    elif "VENCIMIENTO" in hdr:
                        s_fvenc_idx = idx_col
                    elif "MONTO" in hdr:
                        s_monto_idx = idx_col
                    elif hdr == "ESTRATEGIA":
                        s_est_idx = idx_col
                    elif hdr == "ESTADO":
                        s_estado_idx = idx_col
            continue

        # Detectar título de mes en C0 o C1
        m_c0 = _detect_month(c0)
        m_c1 = _detect_month(c1)
        if m_c0:
            current_month = m_c0
        elif m_c1:
            current_month = m_c1

        if current_month is None:
            continue

        mes_num, mes_nombre = current_month

        # ── Bloque izquierdo: CIERRES ────────────────────────────────────────
        c_proy = _cell(row, c_proy_idx)
        c_lote = _cell(row, c_lote_idx)
        c_est = _cell(row, c_est_idx)
        if (c_proy or c_lote) and not ((c_proy or "").upper().startswith("TOTAL")):
            base_c = (
                f"cie|{current_year}|{mes_num:02d}|"
                f"{_norm_key_part(c_proy)}|{_norm_key_part(c_lote)}|{_norm_key_part(c_est)}"
            )
            parsed.append({
                "tipo": "cierre",
                "anio": current_year,
                "mes": mes_num,
                "mes_nombre": mes_nombre,
                "orden_fila": r_idx + 1,
                "sync_key": _next_sync_key(base_c),
                "asesor": None,
                "proyecto": c_proy,
                "lote": c_lote,
                "fecha_ingreso": None,
                "fecha_ingreso_date": None,
                "fecha_vencimiento": None,
                "fecha_vencimiento_date": None,
                "monto_raw": None,
                "monto_numerico": None,
                "moneda": "PEN",
                "estrategia": c_est,
                "estado": "VENDIDO",
                "observaciones": None,
                "origen": "drive",
            })

        # ── Bloque derecho: SEPARACIONES ─────────────────────────────────────
        s_ase = _cell(row, s_ase_idx)
        s_proy = _cell(row, s_proy_idx)
        s_lote = _cell(row, s_lote_idx)
        s_fing_raw = _cell(row, s_fing_idx)
        s_fvenc_raw = _cell(row, s_fvenc_idx)
        s_monto_raw = _cell(row, s_monto_idx)
        s_est = _cell(row, s_est_idx)
        s_estado = _cell(row, s_estado_idx)
        s_obs = _cell(row, s_obs_idx)

        if s_ase and s_ase.lower().startswith("total"):
            continue

        if (s_ase and (s_proy or s_lote)) or (s_proy and s_lote):
            fing_str, fing_date = parse_date_flexible(s_fing_raw)
            fvenc_str, fvenc_date = parse_date_flexible(s_fvenc_raw)
            monto_str, monto_num, moneda = parse_money(s_monto_raw)
            estado_norm = s_estado.upper() if s_estado else None

            base_s = (
                f"sep|{current_year}|{mes_num:02d}|"
                f"{_norm_key_part(s_proy)}|{_norm_key_part(s_lote)}|{_norm_key_part(s_ase)}"
            )
            parsed.append({
                "tipo": "separacion",
                "anio": current_year,
                "mes": mes_num,
                "mes_nombre": mes_nombre,
                "orden_fila": r_idx + 1,
                "sync_key": _next_sync_key(base_s),
                "asesor": s_ase,
                "proyecto": s_proy,
                "lote": s_lote,
                "fecha_ingreso": fing_str,
                "fecha_ingreso_date": fing_date.isoformat() if fing_date else None,
                "fecha_vencimiento": fvenc_str,
                "fecha_vencimiento_date": fvenc_date.isoformat() if fvenc_date else None,
                "monto_raw": monto_str,
                "monto_numerico": monto_num,
                "moneda": moneda,
                "estrategia": s_est,
                "estado": estado_norm,
                "observaciones": s_obs,
                "origen": "drive",
            })

    return parsed


def _serialize_row_snapshot(r: dict[str, Any]) -> dict[str, Any]:
    """Snapshot serializable comparable en JSON para revisiones estilo Git."""
    fi = r.get("fecha_ingreso_date")
    fv = r.get("fecha_vencimiento_date")
    if hasattr(fi, "isoformat"):
        fi = fi.isoformat()
    if hasattr(fv, "isoformat"):
        fv = fv.isoformat()
    mn = r.get("monto_numerico")
    return {
        "tipo": r.get("tipo"),
        "anio": r.get("anio"),
        "mes": r.get("mes"),
        "mes_nombre": r.get("mes_nombre"),
        "orden_fila": r.get("orden_fila") or 0,
        "sync_key": r.get("sync_key"),
        "asesor": _clean_str(r.get("asesor")),
        "proyecto": _clean_str(r.get("proyecto")),
        "lote": _clean_str(r.get("lote")),
        "fecha_ingreso": _clean_str(r.get("fecha_ingreso")),
        "fecha_ingreso_date": fi,
        "fecha_vencimiento": _clean_str(r.get("fecha_vencimiento")),
        "fecha_vencimiento_date": fv,
        "monto_raw": _clean_str(r.get("monto_raw")),
        "monto_numerico": float(mn) if mn is not None else None,
        "moneda": r.get("moneda") or "PEN",
        "estrategia": _clean_str(r.get("estrategia")),
        "estado": _clean_str(r.get("estado")),
        "observaciones": _clean_str(r.get("observaciones")),
    }


def _row_label(r: dict[str, Any]) -> str:
    tipo_lbl = "Cierre" if r.get("tipo") == "cierre" else "Separación"
    parts = [
        f"{tipo_lbl}",
        f"{r.get('mes_nombre') or ''} {r.get('anio') or ''}".strip(),
        r.get("proyecto") or "Sin proyecto",
        f"Lote {r.get('lote')}" if r.get("lote") else None,
        r.get("asesor"),
    ]
    return " · ".join([p for p in parts if p])


def compute_drive_diff(crm_rows: list[dict[str, Any]], drive_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compara registros entrantes de Google Drive contra el estado actual en PostgreSQL.
    Registros creados manualmente en el CRM (origen='crm' sin sync_key en Drive) se preservan
    y NO se marcan como eliminados.
    """
    crm_by_key: dict[str, dict[str, Any]] = {}
    for row in crm_rows:
        sk = row.get("sync_key")
        if sk:
            crm_by_key[sk] = row

    drive_by_key: dict[str, dict[str, Any]] = {}
    for row in drive_rows:
        sk = row.get("sync_key")
        if sk:
            drive_by_key[sk] = row

    changes: list[dict[str, Any]] = []
    unchanged = 0
    added = 0
    modified = 0
    removed = 0

    for d_row in drive_rows:
        sk = d_row["sync_key"]
        after_snap = _serialize_row_snapshot(d_row)
        existing = crm_by_key.get(sk)

        if not existing:
            added += 1
            changes.append({
                "change_type": "added",
                "sync_key": sk,
                "registro_id": None,
                "label": _row_label(after_snap),
                "before": None,
                "after": after_snap,
                "changed_fields": [],
            })
            continue

        before_snap = _serialize_row_snapshot(existing)
        changed_fields = []
        for field_key, field_label in COMPARE_FIELDS:
            v_before = before_snap.get(field_key)
            v_after = after_snap.get(field_key)
            if (v_before or "") != (v_after or ""):
                changed_fields.append({
                    "field": field_key,
                    "label": field_label,
                    "before": v_before,
                    "after": v_after,
                })

        if changed_fields:
            modified += 1
            changes.append({
                "change_type": "modified",
                "sync_key": sk,
                "registro_id": existing.get("id"),
                "label": _row_label(after_snap),
                "before": before_snap,
                "after": after_snap,
                "changed_fields": changed_fields,
            })
        else:
            unchanged += 1

    # Solo detectar eliminaciones en filas cuyo origen fue Drive
    for c_row in crm_rows:
        sk = c_row.get("sync_key")
        if sk and c_row.get("origen") == "drive" and sk not in drive_by_key:
            removed += 1
            before_snap = _serialize_row_snapshot(c_row)
            changes.append({
                "change_type": "removed",
                "sync_key": sk,
                "registro_id": c_row.get("id"),
                "label": _row_label(before_snap),
                "before": before_snap,
                "after": None,
                "changed_fields": [],
            })

    return {
        "summary": {
            "added": added,
            "modified": modified,
            "removed": removed,
            "unchanged": unchanged,
            "drive_total": len(drive_rows),
            "crm_total": len(crm_rows),
        },
        "changes": changes,
    }

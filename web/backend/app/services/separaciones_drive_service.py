"""
separaciones_drive_service.py — Parsers de Google Sheets / Excel (.xlsx y .csv) para
Separaciones Palma y Cuadro de Cierre de Ventas (PDR-FO-GC-17), y motor de
comparación / versionado estilo Git contra los registros en PostgreSQL.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import httpx

DEFAULT_SPREADSHEET_ID = "15ZbIPoJEWAajSUzjajE4350nT6XhjMSW1FqCBk_2Zew"
DEFAULT_CIERRES_SPREADSHEET_ID = "1nuHne0EdIiSawpLCJQV3eOpRQ9PVsmnVSuT7EUJfCPg"
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

CIERRES_COMPARE_FIELDS: tuple[tuple[str, str], ...] = (
    ("asesor", "Asesor"),
    ("proyecto", "Proyecto"),
    ("lote", "Lote"),
    ("cliente_nombre", "Cliente"),
    ("distrito", "Distrito"),
    ("fecha_ingreso_inicial", "Fecha Ingreso Inicial"),
    ("monto_total", "Monto Total"),
    ("moneda", "Moneda"),
    ("pct_inicial_raw", "% Inicial"),
    ("estrategia", "Estrategia"),
    ("area", "Área"),
    ("edad", "Edad"),
    ("cantidad_inicial", "Cantidad Inicial"),
    ("tipo_cambio", "Tipo de Cambio"),
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
        ct = (resp.headers.get("content-type") or "").lower()
        if "text/html" in ct and csv_text.lstrip().startswith("<"):
            raise ValueError("El documento de Google Drive no es público o requiere iniciar sesión.")
        digest = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        return csv_text, digest


def _coerce_cell_str(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        return cell.date().isoformat()
    if isinstance(cell, date):
        return cell.isoformat()
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    return str(cell)


def read_tabular_sheets(file_bytes: bytes, filename: str = "") -> tuple[list[tuple[str, list[list[str]]]], str]:
    """Lee un archivo (.xlsx/.xlsm o .csv) y retorna ([(nombre_hoja, matriz_strings), ...], sha256_hex)."""
    digest = hashlib.sha256(file_bytes).hexdigest()
    fname = (filename or "").lower().strip()
    is_xlsx = fname.endswith((".xlsx", ".xlsm")) or file_bytes[:2] == b"PK"

    if is_xlsx:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        sheets: list[tuple[str, list[list[str]]]] = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = [[_coerce_cell_str(c) for c in row] for row in ws.iter_rows(values_only=True)]
            sheets.append((sheet_name, rows))
        wb.close()
        return sheets, digest

    # CSV fallback UTF-8 -> Latin-1
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1", errors="replace")
    return [("", list(csv.reader(io.StringIO(text))))], digest


def read_tabular_file_as_rows(file_bytes: bytes, filename: str = "") -> tuple[list[list[str]], str]:
    """Compatibilidad: retorna la primera hoja como matriz_de_strings y su sha256_hex."""
    sheets, digest = read_tabular_sheets(file_bytes, filename)
    return (sheets[0][1] if sheets else []), digest


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
    """Convierte DD/MM/YYYY, YYYY-MM-DD, D/M/YY o serial de Excel a ('DD/MM/YYYY', date)."""
    s = _clean_str(raw)
    if not s:
        return None, None
    # Serial numérico de Excel (ej. 46319 o 46319.0)
    if re.match(r"^\d{5}(?:\.0+)?$", s):
        serial = int(float(s))
        if 35000 <= serial <= 60000:
            d = date(1899, 12, 30) + timedelta(days=serial)
            return d.strftime("%d/%m/%Y"), d
    # Recortar hora si viene 'YYYY-MM-DD HH:MM:SS'
    s_date = s.split(" ")[0].strip() if re.match(r"^\d{4}-\d{2}-\d{2}\s", s) else s
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            d = datetime.strptime(s_date, fmt).date()
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


def _parse_decimal_num(raw: Optional[str], places: int = 2) -> Optional[float]:
    s = _clean_str(raw)
    if not s or s.startswith("#"):
        return None
    cleaned = re.sub(r"[^\d.,-]", "", s).replace(",", "")
    if not cleaned:
        return None
    try:
        q = Decimal("1") if places == 0 else Decimal("1." + ("0" * places))
        return float(Decimal(cleaned).quantize(q))
    except (InvalidOperation, ValueError):
        return None


def _parse_pct_inicial(raw: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    s = _clean_str(raw)
    if not s or s.startswith("#"):
        return None, None
    up = s.upper()
    if up == "CONTADO":
        return 1.0, "CONTADO"
    if "%" in s:
        num = _parse_decimal_num(s.replace("%", ""), places=4)
        if num is None:
            return None, s
        ratio = round(num / 100.0, 4)
        return ratio, f"{round(ratio * 100, 2):g}%"
    num = _parse_decimal_num(s, places=4)
    if num is None:
        return None, s
    # Si viene como 0.1 / 0.2 -> 10% / 20%
    if 0 < num <= 1.0:
        return num, f"{round(num * 100, 2):g}%"
    return round(num / 100.0, 4), f"{round(num, 2):g}%"


def _detect_month(cell_text: Optional[str]) -> Optional[tuple[int, str]]:
    s = (_clean_str(cell_text) or "").upper()
    return MONTH_MAP.get(s)


# =============================================================================
# PARSER 1: SEPARACIONES PALMA (Hoja original)
# =============================================================================

def parse_separaciones_rows(rows: list[list[str]]) -> list[dict[str, Any]]:
    """Parsea matriz tabular de SEPARACIONES PALMA (y su bloque resumen izquierdo)."""
    current_year = 2026
    current_month: Optional[tuple[int, str]] = None

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

        if c0 and ("CIERRES" in c0.upper() or "SEPARACIONES" in c0.upper()):
            m_year = re.search(r"\b(20\d{2})\b", c0)
            if m_year:
                current_year = int(m_year.group(1))
                current_month = None
            continue

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

        m_c0 = _detect_month(c0)
        m_c1 = _detect_month(c1)
        if m_c0:
            current_month = m_c0
        elif m_c1:
            current_month = m_c1

        if current_month is None:
            continue

        mes_num, mes_nombre = current_month

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


def parse_drive_csv(csv_text: str) -> list[dict[str, Any]]:
    """Compatibilidad: parsea CSV de SEPARACIONES PALMA."""
    return parse_separaciones_rows(list(csv.reader(io.StringIO(csv_text))))


# =============================================================================
# PARSER 2: CUADRO DE CIERRE DE VENTAS (PDR-FO-GC-17)
# =============================================================================

_SUMMARY_SHEET_KEYWORDS = (
    "BASE HIST",
    "PRODUCC",
    "RANKING",
    "RESUMEN ANUAL",
    "DINAMICA",
    "TABLA",
)


def _infer_period_from_title(title: str) -> tuple[int, Optional[tuple[int, str]]]:
    up = (_clean_str(title) or "").upper()
    yr_m = re.search(r"\b(20\d{2})\b", up)
    yr = int(yr_m.group(1)) if yr_m else 2026
    for m_key, m_val in MONTH_MAP.items():
        if re.search(rf"\b{m_key}\b", up):
            return yr, m_val
    return yr, None


def parse_separaciones_workbook(sheets: list[tuple[str, list[list[str]]]]) -> list[dict[str, Any]]:
    """Parsea una o más hojas de un Excel/CSV de Separaciones preservando sync_key únicos."""
    all_rows: list[dict[str, Any]] = []
    seen_sync: dict[str, int] = {}
    for sheet_name, rows in sheets:
        up = (_clean_str(sheet_name) or "").upper()
        if up and any(k in up for k in _SUMMARY_SHEET_KEYWORDS):
            continue
        parsed_sheet = parse_separaciones_rows(rows)
        for item in parsed_sheet:
            base = item["sync_key"].rsplit("#", 1)[0]
            cnt = seen_sync.get(base, 0) + 1
            seen_sync[base] = cnt
            item["sync_key"] = f"{base}#{cnt}"
            all_rows.append(item)
    return all_rows


def parse_cierres_rows(
    rows: list[list[str]],
    origen: str = "drive",
    default_year: int = 2026,
    default_month: Optional[tuple[int, str]] = None,
) -> list[dict[str, Any]]:
    """
    Parsea bloques mensuales del formato 'CUADRO DE CIERRE DE VENTAS - <MES> - <ANIO>'
    (incluyendo bloques inferiores de Febrero/Enero sin mes en el banner y deteniéndose
    antes de la tabla consolidada 'Nro | MES | ORDEN DE MES | TRIMESTRE').
    """
    current_year = default_year
    current_month: Optional[tuple[int, str]] = default_month
    last_resolved_month: Optional[tuple[int, int]] = None  # (year, month_num)
    col_map: dict[str, int] = {}

    parsed: list[dict[str, Any]] = []
    seen_counts: dict[str, int] = {}

    def _cell(row: list[str], idx: Optional[int]) -> Optional[str]:
        if idx is None or idx < 0 or idx >= len(row):
            return None
        return _clean_str(row[idx])

    def _next_sync_key(base_key: str) -> str:
        cnt = seen_counts.get(base_key, 0) + 1
        seen_counts[base_key] = cnt
        return f"{base_key}#{cnt}"

    for r_idx, row in enumerate(rows):
        row_upper = [(_clean_str(x) or "").upper() for x in row]
        joined_upper = " ".join([x for x in row_upper if x])

        # Detener antes de tablas consolidadas o resúmenes anuales para no duplicar Enero..Junio
        if (
            ("ORDEN DE MES" in row_upper and "TRIMESTRE" in row_upper)
            or joined_upper.startswith("RESUMEN ANUAL")
        ):
            break

        # Detectar banner de cuadro: "CUADRO DE CIERRE DE VENTAS - OCTUBRE - 2026"
        banner_match = None
        for cell_u in row_upper:
            if "CUADRO DE CIERRE DE VENTAS" in cell_u:
                banner_match = cell_u
                break

        if banner_match:
            m_year = re.search(r"\b(20\d{2})\b", banner_match)
            if m_year:
                current_year = int(m_year.group(1))
            found_m = None
            for m_key, m_val in MONTH_MAP.items():
                if re.search(rf"\b{m_key}\b", banner_match):
                    found_m = m_val
                    break
            if found_m is not None:
                current_month = found_m
            elif default_month is not None:
                current_month = default_month
            else:
                current_month = None
            col_map = {}
            continue

        # Detectar fila de cabecera de tabla de cierres
        if (
            "ASESOR" in row_upper
            and "PROYECTO" in row_upper
            and ("NOMENCLATURA DE LOTE" in row_upper or "LOTE" in row_upper)
            and "NOMBRE DEL CLIENTE" in row_upper
        ):
            col_map = {}
            for idx_col, hdr in enumerate(row_upper):
                if hdr == "ASESOR":
                    col_map["asesor"] = idx_col
                elif hdr == "PROYECTO":
                    col_map["proyecto"] = idx_col
                elif hdr in ("NOMENCLATURA DE LOTE", "LOTE"):
                    col_map["lote"] = idx_col
                elif hdr == "NOMBRE DEL CLIENTE":
                    col_map["cliente_nombre"] = idx_col
                elif "DISTRITO" in hdr:
                    col_map["distrito"] = idx_col
                elif "INGRESO DE INICIAL" in hdr or "NGRESO DE INICIAL" in hdr:
                    col_map["fecha_ingreso_inicial"] = idx_col
                elif "MONTO TOTAL DE VENTA" in hdr:
                    col_map["monto_total"] = idx_col
                elif hdr == "MONEDA":
                    col_map["moneda"] = idx_col
                elif "% DE INICIAL" in hdr:
                    col_map["pct_inicial"] = idx_col
                elif hdr == "ESTRATEGIA":
                    col_map["estrategia"] = idx_col
                elif hdr == "AREA":
                    col_map["area"] = idx_col
                elif hdr == "EDAD":
                    col_map["edad"] = idx_col
                elif "CANTIDAD DE INICIAL" in hdr:
                    col_map["cantidad_inicial"] = idx_col
                elif "TIPO DE CAMBIO" in hdr:
                    col_map["tipo_cambio"] = idx_col
                elif hdr.startswith("OBSERVACIONES"):
                    col_map["observaciones"] = idx_col
            continue

        if not col_map:
            continue

        asesor = _cell(row, col_map.get("asesor"))
        proyecto = _cell(row, col_map.get("proyecto"))
        lote = _cell(row, col_map.get("lote"))
        cliente = _cell(row, col_map.get("cliente_nombre"))

        if not (asesor and proyecto and lote and cliente):
            continue
        if "NO SE TIENE VENTAS" in cliente.upper():
            continue

        fing_raw = _cell(row, col_map.get("fecha_ingreso_inicial"))
        fing_str, fing_date = parse_date_flexible(fing_raw)

        # Resolver mes cuando el banner no lo indica (ej. Febrero y Enero al final)
        if current_month is None:
            if fing_date is not None:
                m_num = fing_date.month
                m_name = {v[0]: v[1] for v in MONTH_MAP.values()}[m_num]
                current_year = fing_date.year
                current_month = (m_num, m_name)
            elif last_resolved_month is not None and last_resolved_month[1] > 1:
                m_num = last_resolved_month[1] - 1
                m_name = {v[0]: v[1] for v in MONTH_MAP.values()}[m_num]
                current_year = last_resolved_month[0]
                current_month = (m_num, m_name)
            else:
                continue

        mes_num, mes_nombre = current_month
        last_resolved_month = (current_year, mes_num)

        distrito = _cell(row, col_map.get("distrito"))
        monto_total = _parse_decimal_num(_cell(row, col_map.get("monto_total")), places=2)
        moneda_raw = (_cell(row, col_map.get("moneda")) or "").upper()
        moneda = "DOLARES" if ("DOLAR" in moneda_raw or "USD" in moneda_raw) else ("SOLES" if "SOL" in moneda_raw else (moneda_raw or "SOLES"))
        pct_num, pct_raw = _parse_pct_inicial(_cell(row, col_map.get("pct_inicial")))
        estrategia = _cell(row, col_map.get("estrategia"))
        area = _cell(row, col_map.get("area"))
        edad_f = _parse_decimal_num(_cell(row, col_map.get("edad")), places=0)
        edad = int(edad_f) if edad_f is not None else None
        cantidad_inicial = _parse_decimal_num(_cell(row, col_map.get("cantidad_inicial")), places=2)
        tipo_cambio = _parse_decimal_num(_cell(row, col_map.get("tipo_cambio")), places=4)
        observaciones = _cell(row, col_map.get("observaciones"))

        base_key = (
            f"cie_v2|{current_year}|{mes_num:02d}|"
            f"{_norm_key_part(proyecto)}|{_norm_key_part(lote)}|{_norm_key_part(cliente)}"
        )
        parsed.append({
            "anio": current_year,
            "mes": mes_num,
            "mes_nombre": mes_nombre,
            "orden_fila": r_idx + 1,
            "sync_key": _next_sync_key(base_key),
            "asesor": asesor,
            "proyecto": proyecto,
            "lote": lote,
            "cliente_nombre": cliente,
            "distrito": distrito,
            "fecha_ingreso_inicial": fing_str,
            "fecha_ingreso_date": fing_date.isoformat() if fing_date else None,
            "monto_total": monto_total,
            "moneda": moneda,
            "pct_inicial": pct_num,
            "pct_inicial_raw": pct_raw,
            "estrategia": estrategia,
            "area": area,
            "edad": edad,
            "cantidad_inicial": cantidad_inicial,
            "tipo_cambio": tipo_cambio,
            "observaciones": observaciones,
            "origen": origen,
        })

    return parsed


def parse_cierres_workbook(
    sheets: list[tuple[str, list[list[str]]]],
    origen: str = "excel",
) -> list[dict[str, Any]]:
    """Parsea un Excel multi-hoja o CSV de Cuadro de Cierre de Ventas (PDR-FO-GC-17)."""
    all_rows: list[dict[str, Any]] = []
    seen_sync: dict[str, int] = {}
    for sheet_name, rows in sheets:
        up = (_clean_str(sheet_name) or "").upper()
        if up and any(k in up for k in _SUMMARY_SHEET_KEYWORDS):
            continue
        def_yr, def_mo = _infer_period_from_title(sheet_name)
        parsed_sheet = parse_cierres_rows(
            rows,
            origen=origen,
            default_year=def_yr,
            default_month=def_mo,
        )
        for item in parsed_sheet:
            base = item["sync_key"].rsplit("#", 1)[0]
            cnt = seen_sync.get(base, 0) + 1
            seen_sync[base] = cnt
            item["sync_key"] = f"{base}#{cnt}"
            all_rows.append(item)
    return all_rows


def parse_cierres_csv(csv_text: str, origen: str = "drive") -> list[dict[str, Any]]:
    return parse_cierres_rows(list(csv.reader(io.StringIO(csv_text))), origen=origen)


# =============================================================================
# DIFF MOTOR (SEPARACIONES & CIERRES)
# =============================================================================

def _serialize_row_snapshot(r: dict[str, Any]) -> dict[str, Any]:
    """Snapshot serializable comparable en JSON para revisiones estilo Git (Separaciones)."""
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


def _serialize_cierre_snapshot(r: dict[str, Any]) -> dict[str, Any]:
    """Snapshot serializable comparable en JSON para revisiones estilo Git (Cierres)."""
    fi = r.get("fecha_ingreso_date")
    if hasattr(fi, "isoformat"):
        fi = fi.isoformat()
    return {
        "anio": r.get("anio"),
        "mes": r.get("mes"),
        "mes_nombre": r.get("mes_nombre"),
        "orden_fila": r.get("orden_fila") or 0,
        "sync_key": r.get("sync_key"),
        "asesor": _clean_str(r.get("asesor")),
        "proyecto": _clean_str(r.get("proyecto")),
        "lote": _clean_str(r.get("lote")),
        "cliente_nombre": _clean_str(r.get("cliente_nombre")),
        "distrito": _clean_str(r.get("distrito")),
        "fecha_ingreso_inicial": _clean_str(r.get("fecha_ingreso_inicial")),
        "fecha_ingreso_date": fi,
        "monto_total": float(r["monto_total"]) if r.get("monto_total") is not None else None,
        "moneda": _clean_str(r.get("moneda")) or "SOLES",
        "pct_inicial": float(r["pct_inicial"]) if r.get("pct_inicial") is not None else None,
        "pct_inicial_raw": _clean_str(r.get("pct_inicial_raw")),
        "estrategia": _clean_str(r.get("estrategia")),
        "area": _clean_str(r.get("area")),
        "edad": int(r["edad"]) if r.get("edad") is not None else None,
        "cantidad_inicial": float(r["cantidad_inicial"]) if r.get("cantidad_inicial") is not None else None,
        "tipo_cambio": float(r["tipo_cambio"]) if r.get("tipo_cambio") is not None else None,
        "observaciones": _clean_str(r.get("observaciones")),
    }


def _row_label(r: dict[str, Any]) -> str:
    tipo_lbl = "Cierre" if r.get("tipo") == "cierre" else "Separación"
    parts = [
        tipo_lbl,
        f"{r.get('mes_nombre') or ''} {r.get('anio') or ''}".strip(),
        r.get("proyecto") or "Sin proyecto",
        f"Lote {r.get('lote')}" if r.get("lote") else None,
        r.get("asesor"),
    ]
    return " · ".join([p for p in parts if p])


def _cierre_row_label(r: dict[str, Any]) -> str:
    parts = [
        "Cierre",
        f"{r.get('mes_nombre') or ''} {r.get('anio') or ''}".strip(),
        r.get("proyecto") or "Sin proyecto",
        f"Lote {r.get('lote')}" if r.get("lote") else None,
        r.get("cliente_nombre"),
    ]
    return " · ".join([p for p in parts if p])


def _diff_generic(
    crm_rows: list[dict[str, Any]],
    incoming_rows: list[dict[str, Any]],
    *,
    serializer,
    label_fn,
    compare_fields: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    crm_by_key: dict[str, dict[str, Any]] = {}
    for row in crm_rows:
        sk = row.get("sync_key")
        if sk:
            crm_by_key[sk] = row

    incoming_by_key: dict[str, dict[str, Any]] = {}
    for row in incoming_rows:
        sk = row.get("sync_key")
        if sk:
            incoming_by_key[sk] = row

    changes: list[dict[str, Any]] = []
    unchanged = 0
    added = 0
    modified = 0
    removed = 0

    for d_row in incoming_rows:
        sk = d_row["sync_key"]
        after_snap = serializer(d_row)
        existing = crm_by_key.get(sk)

        if not existing:
            added += 1
            changes.append({
                "change_type": "added",
                "sync_key": sk,
                "registro_id": None,
                "label": label_fn(after_snap),
                "before": None,
                "after": after_snap,
                "changed_fields": [],
            })
            continue

        before_snap = serializer(existing)
        changed_fields = []
        for field_key, field_label in compare_fields:
            v_before = before_snap.get(field_key)
            v_after = after_snap.get(field_key)
            norm_b = "" if v_before is None else str(v_before)
            norm_a = "" if v_after is None else str(v_after)
            if norm_b != norm_a:
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
                "label": label_fn(after_snap),
                "before": before_snap,
                "after": after_snap,
                "changed_fields": changed_fields,
            })
        else:
            unchanged += 1

    # Detectar eliminaciones solo sobre filas provenientes de Drive o Excel subido
    for c_row in crm_rows:
        sk = c_row.get("sync_key")
        if sk and c_row.get("origen") in ("drive", "excel") and sk not in incoming_by_key:
            removed += 1
            before_snap = serializer(c_row)
            changes.append({
                "change_type": "removed",
                "sync_key": sk,
                "registro_id": c_row.get("id"),
                "label": label_fn(before_snap),
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
            "drive_total": len(incoming_rows),
            "crm_total": len(crm_rows),
        },
        "changes": changes,
    }


def compute_drive_diff(crm_rows: list[dict[str, Any]], drive_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compara registros de Separaciones (Drive o Excel) contra PostgreSQL."""
    return _diff_generic(
        crm_rows,
        drive_rows,
        serializer=_serialize_row_snapshot,
        label_fn=_row_label,
        compare_fields=COMPARE_FIELDS,
    )


def compute_cierres_diff(crm_rows: list[dict[str, Any]], incoming_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compara registros de Cierres (Drive o Excel) contra PostgreSQL."""
    return _diff_generic(
        crm_rows,
        incoming_rows,
        serializer=_serialize_cierre_snapshot,
        label_fn=_cierre_row_label,
        compare_fields=CIERRES_COMPARE_FIELDS,
    )

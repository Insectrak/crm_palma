"""Tests unitarios para Gestión de Lotes (Separaciones + Cierres), Excel/Drive parsers y diff Git."""
import io
import pytest
from fastapi import HTTPException

from app.auth.jwt import require_admin
from app.auth.schemas import TokenData
from app.services.separaciones_drive_service import (
    compute_cierres_diff,
    compute_drive_diff,
    extract_spreadsheet_id_and_gid,
    parse_cierres_csv,
    parse_cierres_workbook,
    parse_date_flexible,
    parse_drive_csv,
    parse_money,
    read_tabular_sheets,
)


SAMPLE_CSV = """\
,,,,,,,,,,,,,,,,,,,,,,,,,,,
CIERRES PALMA 2026,,,,,,,,,,,,,,,SEPARACIONES PALMA 2026,,,,,,,,,,,,
OCTUBRE,,,,,,,,,,,,,,,,,,,,,,,,,,,
,RESUMEN ,,,,,,RESUMEN GENERAL DEL MES,,,,,,,ASESOR,PROYECTO,LOTE,FECHA DE INGRESO,FECHA DE VENCIMIENTO,MONTO DE LA SEPARACIÓN,ESTRATEGIA,ESTADO,,,,,
,OCTUBRE,,PUERTO PALMERAS,A1,WEDO,,WEDO,2,,,,,,JORGE,SUMMER PARK,H10,02/10/2026,31/10/2026,S/200.00,LEAD WEDO,VENDIDO,,,,,
,,,PUERTO PALMERAS,F36,REFERIDOS,,,,,,,,ANA,PUERTO PALMERAS,F38,07/03/2026,15/11/2026,,OFICINA,LIBERADO,,,,,
,,,,,,,,,,,,,,ROSSMARY,PUERTO MADERO: CITYBEACH,B47,27/10/2026,7/11/2026,S/500.00,REFERIDOS,SEPARADO,,,,,Observacion prueba
,,,,,,,,,,,,,,Total de separaciones 3,,,,,,,,,,,,,
ENERO,,,,,,,,,,,,,,,,,,,,,,,,,,,
,RESUMEN ,,,,,,RESUMEN GENERAL DEL MES,,,,,,,ASESOR,PROYECTO,LOTE,FECHA DE INGRESO,FECHA DE VENCIMIENTO,MONTO DE LA SEPARACIÓN,ESTRATEGIA,ESTADO,,,,,
,BNERO,,SIERRA DORADA,A21,RASTRILLO DATA,,,,,,,,,ANA,SIERRA DORADA,A21,,,"$19,000.00",RASTRILLO,VENTA,,,,,
"""


@pytest.mark.unit
def test_extract_spreadsheet_id_and_gid():
    sid, gid = extract_spreadsheet_id_and_gid(
        "https://docs.google.com/spreadsheets/d/15ZbIPoJEWAajSUzjajE4350nT6XhjMSW1FqCBk_2Zew/edit?gid=12#gid=12"
    )
    assert sid == "15ZbIPoJEWAajSUzjajE4350nT6XhjMSW1FqCBk_2Zew"
    assert gid == "12"


@pytest.mark.unit
def test_parse_money_pen_and_usd():
    assert parse_money("S/200.00") == ("S/200.00", 200.0, "PEN")
    assert parse_money("$19,000.00") == ("$19,000.00", 19000.0, "USD")
    assert parse_money("500") == ("500", 500.0, "PEN")


@pytest.mark.unit
def test_parse_drive_csv_extrae_cierres_y_separaciones():
    rows = parse_drive_csv(SAMPLE_CSV)
    cierres = [r for r in rows if r["tipo"] == "cierre"]
    seps = [r for r in rows if r["tipo"] == "separacion"]

    assert len(cierres) == 3
    assert cierres[0]["mes"] == 10
    assert cierres[0]["proyecto"] == "PUERTO PALMERAS"
    assert cierres[2]["mes"] == 1  # BNERO -> ENERO

    assert len(seps) == 4
    assert seps[0]["asesor"] == "JORGE"
    assert seps[0]["monto_numerico"] == 200.0
    assert seps[0]["fecha_ingreso"] == "02/10/2026"
    assert seps[2]["observaciones"] == "Observacion prueba"
    assert seps[3]["moneda"] == "USD"
    assert seps[3]["monto_numerico"] == 19000.0


@pytest.mark.unit
def test_compute_drive_diff_detecta_agregados_modificados_eliminados_y_preserva_crm():
    drive_rows = parse_drive_csv(SAMPLE_CSV)
    # Simular base CRM:
    # - seps[0] modificado en CRM/Drive (estado cambiado en Drive)
    # - una fila extra origen='drive' que ya no está en Drive -> removed
    # - una fila extra origen='crm' creada manualmente -> NO debe marcarse removed
    crm_rows = [
        dict(drive_rows[0], id=1, origen="drive"),  # cierre unchanged
        dict(drive_rows[1], id=2, origen="drive", estado="SEPARADO"),  # separacion Jorge: Drive tiene VENDIDO
        {
            "id": 99,
            "tipo": "separacion",
            "anio": 2026,
            "mes": 10,
            "mes_nombre": "OCTUBRE",
            "sync_key": "sep|2026|10|OTRO|X1|PEDRO#1",
            "asesor": "PEDRO",
            "proyecto": "OTRO",
            "lote": "X1",
            "origen": "drive",
        },
        {
            "id": 100,
            "tipo": "separacion",
            "anio": 2026,
            "mes": 10,
            "mes_nombre": "OCTUBRE",
            "sync_key": None,
            "asesor": "LUCIA",
            "proyecto": "PUERTO PALMERAS",
            "lote": "Z9",
            "origen": "crm",
        },
    ]

    diff = compute_drive_diff(crm_rows, drive_rows)
    s = diff["summary"]
    assert s["unchanged"] == 1
    assert s["modified"] == 1
    assert s["added"] == len(drive_rows) - 2
    assert s["removed"] == 1  # solo la fila origen='drive', nunca la origen='crm'

    mod = next(c for c in diff["changes"] if c["change_type"] == "modified")
    assert mod["changed_fields"][0]["field"] == "estado"
    assert mod["changed_fields"][0]["before"] == "SEPARADO"
    assert mod["changed_fields"][0]["after"] == "VENDIDO"


@pytest.mark.unit
def test_separaciones_y_cierres_rechazan_no_admin():
    sup = TokenData(user_id="2", email="sup@test.com", role="supervisor")
    ase = TokenData(user_id="3", email="ase@test.com", role="asesor")

    for non_admin in (sup, ase):
        with pytest.raises(HTTPException) as exc:
            require_admin(non_admin)
        assert exc.value.status_code == 403


@pytest.mark.unit
def test_parse_date_flexible_serial_excel():
    s, d = parse_date_flexible("46319.0")
    assert s is not None
    assert d is not None
    assert d.year == 2026 and d.month == 10


@pytest.mark.unit
def test_parse_cierres_csv_y_diff():
    csv_sample = """\
,FORMATO,PDR-FO-GC-17,,,,,,,,,,,,,
,CUADRO DE CIERRE DE VENTAS - OCTUBRE - 2026,,,,,,,,,,,,,,,
,ASESOR,PROYECTO,NOMENCLATURA DE LOTE,NOMBRE DEL CLIENTE,DISTRITO DE ORIGEN DEL CLIENTE,FECHA DE INGRESO DE INICIAL,MONTO TOTAL DE VENTA,MONEDA,% DE INICIAL,ESTRATEGIA,AREA,EDAD,CANTIDAD DE INICIAL,TIPO DE CAMBIO,OBSERVACIONES
,FABIOLA,PUERTO PALMERAS,A1,GLADYS CABRERA,paucarpata,24/10/2026,73187.10,SOLES,10%,WEDO,COMERCIAL,37,7320.00,3.50,
,PAOLA,CITY BEACH,B2,MARIO PEREZ,JLBYR,15/10/2026,84000,DOLARES,20%,WEDO,COMERCIAL,41,16800,3.50,Observacion A
Nro,MES,ORDEN DE MES,TRIMESTRE,ASESOR,PROYECTO,NOMENCLATURA DE LOTE,NOMBRE DEL CLIENTE
1,46023,1,T1,ANA,SIERRA DORADA,A21,DUPLICADO A IGNORAR
"""
    rows = parse_cierres_csv(csv_sample, origen="excel")
    assert len(rows) == 2
    assert rows[0]["mes"] == 10
    assert rows[0]["moneda"] == "SOLES"
    assert rows[0]["pct_inicial"] == 0.1
    assert rows[1]["moneda"] == "DOLARES"

    crm_rows = [
        dict(rows[0], id=10, origen="excel", estrategia="OTRA"),
        {
            "id": 11,
            "anio": 2026,
            "mes": 10,
            "mes_nombre": "OCTUBRE",
            "sync_key": "cie_v2|2026|10|X|L9|BORRAR#1",
            "proyecto": "X",
            "lote": "L9",
            "cliente_nombre": "BORRAR",
            "origen": "excel",
        },
        {
            "id": 12,
            "anio": 2026,
            "mes": 10,
            "mes_nombre": "OCTUBRE",
            "sync_key": None,
            "proyecto": "X",
            "lote": "M1",
            "cliente_nombre": "MANUAL CRM",
            "origen": "crm",
        },
    ]
    diff = compute_cierres_diff(crm_rows, rows)
    assert diff["summary"]["modified"] == 1
    assert diff["summary"]["added"] == 1
    assert diff["summary"]["removed"] == 1  # Nunca borra origen='crm'


@pytest.mark.unit
def test_read_tabular_sheets_xlsx_multi_hoja_cierres():
    import openpyxl

    wb = openpyxl.Workbook()
    ws_oct = wb.active
    ws_oct.title = "OCTUBRE 2026"
    ws_oct.append(["CUADRO DE CIERRE DE VENTAS - OCTUBRE - 2026"])
    ws_oct.append(["ASESOR", "PROYECTO", "NOMENCLATURA DE LOTE", "NOMBRE DEL CLIENTE", "FECHA DE INGRESO DE INICIAL", "MONTO TOTAL DE VENTA", "MONEDA", "% DE INICIAL", "ESTRATEGIA", "AREA", "EDAD", "CANTIDAD DE INICIAL", "TIPO DE CAMBIO"])
    ws_oct.append(["FABIOLA", "PUERTO PALMERAS", "A1", "CLIENTE UNO", "46319.0", 73187.1, "SOLES", 0.1, "WEDO", "COMERCIAL", 37, 7320.0, 3.5])

    ws_feb = wb.create_sheet("FEBRERO 2026")
    ws_feb.append(["CUADRO DE CIERRE DE VENTAS"])
    ws_feb.append(["ASESOR", "PROYECTO", "NOMENCLATURA DE LOTE", "NOMBRE DEL CLIENTE", "FECHA DE INGRESO DE INICIAL", "MONTO TOTAL DE VENTA", "MONEDA", "% DE INICIAL", "ESTRATEGIA", "AREA", "EDAD", "CANTIDAD DE INICIAL"])
    ws_feb.append(["SOL", "PUERTO PALMERAS", "H13", "LUIS ROJAS", "11/02/2026", 61506.9, "DOLARES", 0.1, "WEDO", "COMERCIAL", 35, 6150.69])

    ws_base = wb.create_sheet("BASE HISTÓRICA 2026 ")
    ws_base.append(["Nro", "MES", "ORDEN DE MES", "TRIMESTRE", "ASESOR", "PROYECTO", "NOMENCLATURA DE LOTE", "NOMBRE DEL CLIENTE"])
    ws_base.append([1, 46023, 1, "T1", "SOL", "PUERTO PALMERAS", "H13", "LUIS ROJAS"])

    buf = io.BytesIO()
    wb.save(buf)
    sheets, _ = read_tabular_sheets(buf.getvalue(), "CIERRES_PALMA_2026.xlsx")
    parsed = parse_cierres_workbook(sheets, origen="excel")

    assert len(parsed) == 2
    assert {(r["mes"], r["cliente_nombre"]) for r in parsed} == {
        (10, "CLIENTE UNO"),
        (2, "LUIS ROJAS"),
    }

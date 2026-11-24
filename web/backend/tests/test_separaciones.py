"""Tests unitarios para el módulo de Separaciones, parser de Drive y diff estilo Git."""
import pytest
from fastapi import HTTPException

from app.auth.schemas import TokenData
from app.routers.separaciones import (
    approve_drive_revision,
    check_drive_changes,
    create_separacion_registro,
    list_separaciones,
    RegistroCreateIn,
    RevisionApproveIn,
)
from app.services.separaciones_drive_service import (
    compute_drive_diff,
    extract_spreadsheet_id_and_gid,
    parse_drive_csv,
    parse_money,
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
def test_separaciones_endpoints_rechazan_no_admin():
    sup = TokenData(user_id="2", email="sup@test.com", role="supervisor")
    ase = TokenData(user_id="3", email="ase@test.com", role="asesor")

    with pytest.raises(HTTPException) as e1:
        list_separaciones(admin=sup)
    assert e1.value.status_code == 403

    with pytest.raises(HTTPException) as e2:
        check_drive_changes(admin=ase)
    assert e2.value.status_code == 403

    with pytest.raises(HTTPException) as e3:
        approve_drive_revision(1, RevisionApproveIn(), admin=sup)
    assert e3.value.status_code == 403

    with pytest.raises(HTTPException) as e4:
        create_separacion_registro(
            RegistroCreateIn(tipo="separacion", anio=2026, mes=10, proyecto="X", lote="A1"),
            admin=ase,
        )
    assert e4.value.status_code == 403

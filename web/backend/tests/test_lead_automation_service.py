"""
test_lead_automation_service.py — Tests unitarios para la automatización dinámica de estados.
"""
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.services.lead_automation_service import (
    _calcular_meta_estado,
    _nivel_jerarquia_no_contesta,
    evaluar_lead_individual_no_contesta,
    procesar_automatizaciones_estados_no_contesta,
    procesar_automatizacion_no_contesta_dia_3,
    lead_cumple_reglas_no_contesta,
)

SAMPLE_ACTIVE_CONFIG = {
    "enabled": True,
    "reglas_intentos": [
        {"id": "r1", "nombre": "No contesta Día 1", "estado_destino_id": 10, "min_llamadas": 3, "min_whatsapp": 1, "orden": 1, "activo": True},
        {"id": "r2", "nombre": "No contesta Día 2", "estado_destino_id": 11, "min_llamadas": 5, "min_whatsapp": 2, "orden": 2, "activo": True},
        {"id": "r3", "nombre": "No contesta Día 3", "estado_destino_id": 12, "min_llamadas": 6, "min_whatsapp": 3, "orden": 3, "activo": True},
    ],
    "reglas_tiempo": [
        {"id": "rt1", "nombre": "Pase a Bolsa de reciclaje", "estado_origen_id": 12, "horas_espera": 12, "estado_destino_id": 20, "desasignar_asesor": True, "activo": True},
    ],
    "excluir_contacto_efectivo": True,
    "respetar_gestion_admin": True,
}

SAMPLE_DISABLED_CONFIG = {
    "enabled": False,
    "reglas_intentos": [],
    "reglas_tiempo": [],
    "excluir_contacto_efectivo": True,
    "respetar_gestion_admin": True,
}


def test_calcular_meta_estado():
    estados_map = {
        "dia_1": {"id": 10, "nombre": "No contesta Día 1"},
        "dia_2": {"id": 11, "nombre": "No contesta Día 2"},
        "dia_3": {"id": 12, "nombre": "No contesta Día 3"},
        "bolsa": {"id": 20, "nombre": "No contesta / Bolsa de reciclaje"},
    }

    # Insuficiente
    assert _calcular_meta_estado(2, 0, estados_map) is None
    assert _calcular_meta_estado(3, 0, estados_map) is None
    assert _calcular_meta_estado(0, 1, estados_map) is None

    # Día 1: >= 3 llamadas Y >= 1 WA
    res_d1 = _calcular_meta_estado(3, 1, estados_map)
    assert res_d1 == estados_map["dia_1"]
    assert _calcular_meta_estado(4, 1, estados_map) == estados_map["dia_1"]

    # Día 2: >= 5 llamadas Y >= 2 WA
    assert _calcular_meta_estado(5, 1, estados_map) == estados_map["dia_1"]  # falta 1 WA para Día 2
    res_d2 = _calcular_meta_estado(5, 2, estados_map)
    assert res_d2 == estados_map["dia_2"]
    assert _calcular_meta_estado(6, 2, estados_map) == estados_map["dia_2"]  # falta 1 WA para Día 3

    # Día 3: >= 6 llamadas Y >= 3 WA
    res_d3 = _calcular_meta_estado(6, 3, estados_map)
    assert res_d3 == estados_map["dia_3"]
    assert _calcular_meta_estado(12, 5, estados_map) == estados_map["dia_3"]


def test_nivel_jerarquia_no_contesta():
    estados_map = {
        "dia_1": {"id": 10, "nombre": "No contesta Día 1"},
        "dia_2": {"id": 11, "nombre": "No contesta Día 2"},
        "dia_3": {"id": 12, "nombre": "No contesta Día 3"},
        "bolsa": {"id": 20, "nombre": "No contesta / Bolsa de reciclaje"},
    }
    assert _nivel_jerarquia_no_contesta(1, estados_map) == 0       # Estado cualquiera (Nuevo)
    assert _nivel_jerarquia_no_contesta(10, estados_map) == 1      # Día 1
    assert _nivel_jerarquia_no_contesta(11, estados_map) == 2      # Día 2
    assert _nivel_jerarquia_no_contesta(12, estados_map) == 3      # Día 3
    assert _nivel_jerarquia_no_contesta(20, estados_map) == 4      # Bolsa


def test_evaluar_lead_individual_disabled_by_default():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.lead_automation_service.get_db", return_value=db_cm), \
         patch("app.services.lead_automation_service.get_lead_automation_config", return_value=SAMPLE_DISABLED_CONFIG):
        res = evaluar_lead_individual_no_contesta(100)

    assert res["ok"] is True
    assert res["actualizado"] is False
    assert "deshabilitada" in res["motivo"]
    calls = [str(c[0][0]) for c in cur.execute.call_args_list]
    assert not any("UPDATE crm.leads" in c for c in calls)


def test_evaluar_lead_individual_promotes_lead():
    cur = MagicMock()
    # Lead datos: tiene 3 llamadas y 1 WA, sin contacto efectivo
    cur.fetchone.side_effect = [
        {
            "id": 100,
            "asesor_id": "11111111-1111-1111-1111-111111111111",
            "estado_id": 1,
            "estado_nombre": "Nuevo",
            "es_final": False,
            "total_llamadas": 3,
            "total_wa": 1,
            "tiene_contacto_efectivo": False,
            "gestion_especial_admin": False,
        },
        {"nombre": "No contesta Día 1"},  # Target state name
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.lead_automation_service.get_db", return_value=db_cm), \
         patch("app.services.lead_automation_service.get_lead_automation_config", return_value=SAMPLE_ACTIVE_CONFIG):
        res = evaluar_lead_individual_no_contesta(100)

    assert res["ok"] is True
    assert res["actualizado"] is True
    assert res["nuevo_estado"] == "No contesta Día 1"

    calls = [str(c[0][0]) for c in cur.execute.call_args_list]
    assert any("UPDATE crm.leads" in c for c in calls)
    assert any("INSERT INTO crm.contactos" in c for c in calls)


def test_evaluar_lead_individual_skips_effective_contact():
    cur = MagicMock()
    cur.fetchone.return_value = {
        "id": 101,
        "asesor_id": "11111111-1111-1111-1111-111111111111",
        "estado_id": 1,
        "estado_nombre": "Nuevo",
        "es_final": False,
        "total_llamadas": 5,
        "total_wa": 2,
        "tiene_contacto_efectivo": True,  # Lead contestó
        "gestion_especial_admin": False,
    }

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.lead_automation_service.get_db", return_value=db_cm), \
         patch("app.services.lead_automation_service.get_lead_automation_config", return_value=SAMPLE_ACTIVE_CONFIG):
        res = evaluar_lead_individual_no_contesta(101)

    assert res["ok"] is True
    assert res["actualizado"] is False
    assert "contacto efectivo" in res["motivo"]


def test_procesar_automatizaciones_estados_disabled():
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.lead_automation_service.get_db", return_value=db_cm), \
         patch("app.services.lead_automation_service.get_lead_automation_config", return_value=SAMPLE_DISABLED_CONFIG):
        res = procesar_automatizaciones_estados_no_contesta()

    assert res["ok"] is True
    assert res["total_movidos"] == 0
    assert "deshabilitada" in res["motivo"]


def test_procesar_automatizaciones_estados_no_contesta_batch():
    cur = MagicMock()
    cur.fetchall.side_effect = [
        # SELECT id, nombre FROM crm.estados_lead
        [
            {"id": 1, "nombre": "Nuevo"},
            {"id": 10, "nombre": "No contesta Día 1"},
            {"id": 11, "nombre": "No contesta Día 2"},
            {"id": 12, "nombre": "No contesta Día 3"},
            {"id": 20, "nombre": "No contesta / Bolsa de reciclaje"},
        ],
        # Candidatos para reglas de intentos
        [
            {"id": 201, "asesor_id": "aaa", "estado_id": 1, "total_llamadas": 3, "total_wa": 1},   # -> Día 1
            {"id": 202, "asesor_id": "bbb", "estado_id": 10, "total_llamadas": 5, "total_wa": 2},  # -> Día 2
            {"id": 203, "asesor_id": "ccc", "estado_id": 11, "total_llamadas": 6, "total_wa": 3},  # -> Día 3
        ],
        # Candidatos para regla de tiempo (Bolsa tras 12h)
        [
            {"id": 204, "asesor_id": "ddd", "source_estado_nombre": "No contesta Día 3"},
        ],
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.lead_automation_service.get_db", return_value=db_cm), \
         patch("app.services.lead_automation_service.get_lead_automation_config", return_value=SAMPLE_ACTIVE_CONFIG):
        res = procesar_automatizaciones_estados_no_contesta()

    assert res["ok"] is True
    assert res["total_movidos"] == 4

    calls = [str(c[0][0]) for c in cur.execute.call_args_list]
    assert any("UPDATE crm.leads" in c and "asesor_id = NULL" in c for c in calls)
    assert any("INSERT INTO crm.asignaciones_log" in c for c in calls)
    assert any("UPDATE crm.wa_conversations" in c and "asesor_id = NULL" in c for c in calls)


def test_evaluar_lead_individual_skips_gestion_especial_admin():
    cur = MagicMock()
    cur.fetchone.return_value = {
        "id": 102,
        "asesor_id": "11111111-1111-1111-1111-111111111111",
        "estado_id": 1,
        "estado_nombre": "Nuevo",
        "es_final": False,
        "total_llamadas": 6,
        "total_wa": 3,
        "tiene_contacto_efectivo": False,
        "gestion_especial_admin": True,
    }

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.services.lead_automation_service.get_db", return_value=db_cm), \
         patch("app.services.lead_automation_service._has_gestion_especial_admin_column", return_value=True), \
         patch("app.services.lead_automation_service.get_lead_automation_config", return_value=SAMPLE_ACTIVE_CONFIG):
        res = evaluar_lead_individual_no_contesta(102)

    assert res["ok"] is True
    assert res["actualizado"] is False
    assert "gestión especial por Administración" in res["motivo"]

    calls = [str(c[0][0]) for c in cur.execute.call_args_list]
    assert not any("UPDATE crm.leads" in c for c in calls)

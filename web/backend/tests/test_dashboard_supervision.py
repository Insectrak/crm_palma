"""Tests unitarios para el router dashboard_supervision (Supervisión y Control)."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.routers.dashboard_supervision import (
    ESTADOS_EXCLUIDOS_KEYS,
    ESTADOS_GESTION_KEYS,
    _build_advisor_scope_filters,
    _build_contactos_scope_filters,
    _build_llamadas_scope_filters,
    _build_supervision_scope_filters,
    _cambio_estado_cita_sql,
    _citas_ordenadas_cte_sql,
    _clasificacion_operativa_case_sql,
    _classify_advisor_activity,
    _strict_contacto_call_wa_sql,
    get_resumen_supervision_control,
    get_seguimiento_citas,
    get_evolucion_citas,
)
from app.auth.schemas import TokenData


class MockCursor:
    """Cursor simulado que registra queries/params ejecutados y retorna respuestas en orden."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self._current = None

    def execute(self, sql, params=None):
        # Validar que el SQL no tenga '%' sueltos cuando hay parámetros (evita crashes psycopg2)
        if params:
            cleaned = sql.replace("%s", "").replace("%%", "")
            assert "%" not in cleaned, f"Literal '%' sin escapar detectado en SQL: {sql[:120]}"
        self.executed.append((sql, params))
        if self.responses:
            self._current = self.responses.pop(0)
        else:
            self._current = None

    def fetchall(self):
        return self._current if isinstance(self._current, list) else []

    def fetchone(self):
        return self._current if isinstance(self._current, dict) else {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class MockConn:
    """Conexión simulada para pruebas unitarias sin PostgreSQL real."""

    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, cursor_factory=None):
        return self._cursor


@pytest.mark.unit
def test_supervision_control_rechaza_roles_no_admin():
    """Solo usuarios con rol admin pueden acceder al endpoint de supervisión y control."""
    asesor_user = TokenData(user_id="1", email="a@test.com", role="asesor")
    supervisor_user = TokenData(user_id="2", email="s@test.com", role="supervisor")

    with pytest.raises(HTTPException) as exc_asesor:
        get_resumen_supervision_control(current_user=asesor_user)
    with pytest.raises(HTTPException) as exc_sup:
        get_resumen_supervision_control(current_user=supervisor_user)

    assert exc_asesor.value.status_code == 403
    assert exc_sup.value.status_code == 403


@pytest.mark.unit
def test_classify_advisor_activity_detecta_sin_gestion_en_el_dia():
    """Un asesor sin llamadas ni contactos en el día se clasifica sin_actividad aun con actividad previa reciente."""
    estado_sin_hoy, alerta_reciente = _classify_advisor_activity(0, 0, minutos_inactivo=45)
    estado_sin_largo, alerta_larga = _classify_advisor_activity(0, 0, minutos_inactivo=185)
    estado_con_llamada, alerta_ok = _classify_advisor_activity(1, 0, minutos_inactivo=200)
    estado_con_contacto, alerta_c_ok = _classify_advisor_activity(0, 2, minutos_inactivo=30)

    assert estado_sin_hoy == "sin_actividad"
    assert alerta_reciente is False
    assert estado_sin_largo == "sin_actividad"
    assert alerta_larga is True
    assert estado_con_llamada == "activo"
    assert alerta_ok is False
    assert estado_con_contacto == "activo"
    assert alerta_c_ok is False


@pytest.mark.unit
def test_scope_filters_incluyen_sede_supervisor_y_asesor():
    """Los filtros de sede, supervisor y asesor se propagan en leads, asesores, llamadas y contactos."""
    sede = "11111111-1111-1111-1111-111111111111"
    sup = "22222222-2222-2222-2222-222222222222"
    asesor = "33333333-3333-3333-3333-333333333333"
    start_dt = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 11, 13, 23, 59, tzinfo=timezone.utc)

    lead_sql, lead_params = _build_supervision_scope_filters(sede, sup, asesor)
    adv_sql, adv_params = _build_advisor_scope_filters(sede, sup, asesor)
    llam_sql, llam_params = _build_llamadas_scope_filters(start_dt, end_dt, sede, sup, asesor)
    cont_sql, cont_params = _build_contactos_scope_filters(start_dt, end_dt, sede, sup, asesor)

    assert sede in lead_params and sup in lead_params and asesor in lead_params
    assert "l.asesor_id = %s::uuid" in lead_sql
    assert sede in adv_params and sup in adv_params and asesor in adv_params
    assert "u.role IN ('asesor', 'supervisor')" in adv_sql
    assert "u.id = %s::uuid" in adv_sql
    assert adv_params.count(sup) == 2
    assert sede in llam_params and sup in llam_params and asesor in llam_params
    assert "ll.asesor_id = %s::uuid" in llam_sql
    assert llam_params.count(sup) == 2
    assert sede in cont_params and sup in cont_params and asesor in cont_params
    assert "COALESCE(c.asesor_id, lc_s.asesor_id) = %s::uuid" in cont_sql
    strict_sql = _strict_contacto_call_wa_sql("c")
    assert "'llamada'" in strict_sql and "'whatsapp'" in strict_sql
    assert "c.fecha_cita IS NULL" in strict_sql
    assert "STRPOS(LOWER(COALESCE(c.resultado, '')), 'cita') = 0" in strict_sql


@pytest.mark.unit
def test_sql_citas_y_clasificacion_operativa_cubren_reglas():
    """El SQL generado incluye partición por primera cita y todas las categorías de inclusión/exclusión."""
    citas_sql = _citas_ordenadas_cte_sql()
    case_sql = _clasificacion_operativa_case_sql()

    assert "ROW_NUMBER() OVER (" in citas_sql
    assert "PARTITION BY c.lead_id" in citas_sql
    assert "tuvo_estado_cita_dia_previo" in citas_sql
    assert "c_prev.notas" in citas_sql
    assert "estado_nuevo_id" not in citas_sql

    for key in ESTADOS_GESTION_KEYS:
        assert f"'{key}'" in case_sql
    for key in ESTADOS_EXCLUIDOS_KEYS:
        assert f"'{key}'" in case_sql


@pytest.mark.unit
def test_resumen_supervision_control_retorna_nuevos_indicadores_y_filtra_por_asesor():
    """El endpoint retorna primeras citas, leads únicos contactados, leads en gestión y respeta filtros."""
    admin_user = TokenData(user_id="admin-1", email="admin@test.com", role="admin")
    asesor_id = "33333333-3333-3333-3333-333333333333"
    sup_id = "22222222-2222-2222-2222-222222222222"

    responses = [
        # 1. asesores_rows
        [
            {"asesor_id": asesor_id, "nombre": "Janet Perez", "email": "janet@test.com"},
            {"asesor_id": "44444444-4444-4444-4444-444444444444", "nombre": "Renato Diaz", "email": "renato@test.com"},
        ],
        # 2. kpis_leads + control_operativo
        {
            "pendientes_sin_contacto": 5,
            "criticos_gt_15m": 2,
            "criticos_gt_2h": 1,
            "sin_asesor_huerfanos": 0,
            "no_gestionados_gt_24h": 3,
            "leads_nuevos_periodo": 12,
            "leads_con_primer_contacto_periodo": 10,
            "primer_contacto_promedio_min": 14.5,
            "primer_contacto_mediana_min": 6.0,
            "total_leads_activos": 100,
            "gestion_no_contesta_123": 20,
            "gestion_bolsa_reciclaje": 10,
            "gestion_contactado": 15,
            "gestion_oportunidad_futura": 8,
            "gestion_en_seguimiento": 12,
            "gestion_nuevas_citas": 5,
            "excluido_nuevos": 10,
            "excluido_equivocados_inexistentes": 4,
            "excluido_matriculas": 6,
            "excluido_perdidos": 7,
            "excluido_citas_ya_existentes": 3,
            "excluido_otros": 0,
        },
        # 2b. citas_stats
        {
            "agendados_primeras_citas": 5,
            "citas_reprogramadas_previas": 3,
            "leads_con_reprogramacion_previa": 2,
            "citas_canceladas": 1,
        },
        # 3. cruzados_stats
        {"total_leads_cruzados": 2, "telefonos_cruzados": 1},
        # 4. kpis_llamadas
        {
            "total_llamadas": 113,
            "leads_unicos_llamados": 46,
            "salientes": 110,
            "entrantes": 3,
            "perdidas": 0,
            "contestadas": 38,
            "duracion_total_segundos": 3600,
            "duracion_promedio_segundos": 95,
            "asesores_con_llamadas": 1,
        },
        # 4b. leads_unicos_contactados
        {"leads_unicos_contactados": 46},
        # 4c. contactos_call_wa_row
        {"llamadas_manuales_periodo": 4, "whatsapp_periodo": 8},
        # 5. distribucion_horaria
        [{"hora": 10, "total": 25, "contestadas": 10}],
        # 6. asesores_detalle
        [
            {
                "asesor_id": asesor_id,
                "asesor_nombre": "Janet Perez",
                "asesor_email": "janet@test.com",
                "rol": "asesor",
                "sede_nombre": "Lima Centro",
                "supervisor_id": sup_id,
                "supervisor_nombre": "Carlos Sup",
                "leads_asignados_periodo": 40,
                "leads_pendientes": 1,
                "no_gestionados_24h": 0,
                "leads_en_gestion": 70,
                "llamadas_periodo": 113,
                "leads_unicos_llamados": 46,
                "llamadas_manuales_periodo": 4,
                "whatsapp_periodo": 8,
                "contactos_periodo": 12,
                "gestiones_periodo": 125,
                "leads_unicos_contactados": 46,
                "llamadas_salientes": 110,
                "llamadas_contestadas": 38,
                "duracion_total_seg": 3600,
                "duracion_promedio_segundos": 95,
                "minutos_llamadas": 60.0,
                "agendados_primeras_citas": 5,
                "citas_reprogramadas_previas": 2,
                "matriculas_periodo": 2,
                "ultima_actividad_ts": datetime.now(timezone.utc),
            },
            {
                "asesor_id": "44444444-4444-4444-4444-444444444444",
                "asesor_nombre": "Renato Diaz",
                "asesor_email": "renato@test.com",
                "rol": "asesor",
                "sede_nombre": "Lima Centro",
                "supervisor_id": sup_id,
                "supervisor_nombre": "Carlos Sup",
                "leads_asignados_periodo": 5,
                "leads_pendientes": 4,
                "no_gestionados_24h": 2,
                "leads_en_gestion": 12,
                "llamadas_periodo": 0,
                "leads_unicos_llamados": 0,
                "llamadas_manuales_periodo": 0,
                "whatsapp_periodo": 0,
                "contactos_periodo": 0,
                "gestiones_periodo": 0,
                "leads_unicos_contactados": 0,
                "llamadas_salientes": 0,
                "llamadas_contestadas": 0,
                "duracion_total_seg": 0,
                "duracion_promedio_segundos": 0,
                "minutos_llamadas": 0.0,
                "agendados_primeras_citas": 0,
                "citas_reprogramadas_previas": 0,
                "matriculas_periodo": 0,
                "ultima_actividad_ts": None,
            },
            {
                "asesor_id": sup_id,
                "asesor_nombre": "Carlos Sup",
                "asesor_email": "carlos@test.com",
                "rol": "supervisor",
                "sede_nombre": "Lima Centro",
                "supervisor_id": None,
                "supervisor_nombre": "",
                "leads_asignados_periodo": 8,
                "leads_pendientes": 0,
                "no_gestionados_24h": 0,
                "leads_en_gestion": 10,
                "llamadas_periodo": 10,
                "leads_unicos_llamados": 6,
                "llamadas_manuales_periodo": 1,
                "whatsapp_periodo": 2,
                "contactos_periodo": 3,
                "gestiones_periodo": 13,
                "leads_unicos_contactados": 7,
                "llamadas_salientes": 10,
                "llamadas_contestadas": 5,
                "duracion_total_seg": 300,
                "duracion_promedio_segundos": 60,
                "minutos_llamadas": 5.0,
                "agendados_primeras_citas": 1,
                "citas_reprogramadas_previas": 0,
                "matriculas_periodo": 1,
                "ultima_actividad_ts": datetime.now(timezone.utc),
            },
        ],
        # 7. equipos_rows
        [{"supervisor_id": sup_id, "supervisor_nombre": "Carlos Sup", "total_asesores": 2}],
        # 8. leads_urgentes
        [],
        # 9. fuentes_desempeno
        [
            {
                "fuente_id": 161,
                "fuente_nombre": "TikTok",
                "leads_periodo": 10,
                "con_primer_contacto": 8,
                "tiempo_promedio_min": 12.4,
                "tiempo_mediana_min": 5.5,
                "llamadas_app": 25,
                "llamadas_manuales": 5,
            }
        ],
        # 10. traslados_row
        {
            "total_traslados": 7,
            "leads_unicos_trasladados": 6,
            "entre_equipos": 3,
            "mismo_equipo": 4,
        },
    ]

    mock_cur = MockCursor(responses)
    mock_conn = MockConn(mock_cur)

    @contextmanager
    def _fake_get_db():
        yield mock_conn

    with patch("app.routers.dashboard_supervision.get_db", _fake_get_db):
        result = get_resumen_supervision_control(
            periodo="hoy",
            supervisor_id=sup_id,
            asesor_id=asesor_id,
            current_user=admin_user,
        )

    assert result["kpis_operativos"]["avance_llamadas"]["total_llamadas"] == 113
    assert result["kpis_operativos"]["avance_llamadas"]["llamadas_manuales_periodo"] == 4
    assert result["kpis_operativos"]["avance_llamadas"]["whatsapp_periodo"] == 8
    assert result["kpis_operativos"]["avance_llamadas"]["total_llamadas_y_wa"] == 125
    assert result["kpis_operativos"]["avance_llamadas"]["leads_unicos_contactados"] == 46
    assert result["kpis_operativos"]["citas_resumen"]["agendados_primeras_citas"] == 5
    assert result["kpis_operativos"]["citas_resumen"]["citas_reprogramadas_previas"] == 3
    assert result["kpis_operativos"]["control_operativo"]["leads_en_gestion"] == 70
    assert result["kpis_operativos"]["control_operativo"]["leads_excluidos"] == 30
    assert result["kpis_operativos"]["asesores_actividad"]["activos_hoy"] == 2
    assert result["kpis_operativos"]["asesores_actividad"]["sin_actividad_hoy"] == 1
    assert any(a.get("rol") == "supervisor" and a.get("asesor_id") == sup_id for a in result["asesores_detalle"])
    assert result["equipos_desempeno"][0]["llamadas_total"] == 123
    assert result["foco_critico"]["asesores_sin_actividad"][0]["asesor_nombre"] == "Renato Diaz"
    assert result["kpis_operativos"]["avance_llamadas"]["total_llamadas_incl_manuales"] == 117
    assert result["kpis_operativos"]["avance_llamadas"]["llamadas_promedio_por_lead"] == 9.75
    assert result["kpis_operativos"]["tiempo_primer_contacto"] == {
        "leads_periodo": 12,
        "con_primer_contacto": 10,
        "tiempo_promedio_min": 14.5,
        "tiempo_mediana_min": 6.0,
    }
    assert result["kpis_operativos"]["traslados_bolsas"] == {
        "total_traslados": 7,
        "leads_unicos_trasladados": 6,
        "entre_equipos": 3,
        "mismo_equipo": 4,
    }
    assert result["fuentes_desempeno"][0]["llamadas_totales"] == 30
    assert result["fuentes_desempeno"][0]["llamadas_promedio_por_lead"] == 3.0
    janet = next(a for a in result["asesores_detalle"] if a["asesor_id"] == asesor_id)
    assert janet["llamadas_totales_periodo"] == 117
    assert janet["llamadas_promedio_por_lead"] == 2.92
    assert janet["duracion_promedio_segundos"] == 95
    assert any(params and asesor_id in params for _, params in mock_cur.executed)


@pytest.mark.unit
def test_seguimiento_citas_rechaza_no_admin():
    """Solo admin puede acceder al endpoint de seguimiento a citas."""
    sup_user = TokenData(user_id="2", email="s@test.com", role="supervisor")
    with pytest.raises(HTTPException) as exc:
        get_seguimiento_citas(current_user=sup_user)
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_seguimiento_citas_cuenta_actuales_e_historicos_y_solo_periodo():
    """Cuenta leads con estado actual de cita y leads que tuvieron estado cita en historial."""
    admin_user = TokenData(user_id="admin-1", email="admin@test.com", role="admin")
    now_utc = datetime.now(timezone.utc)

    rows = [
        {
            "id": 101,
            "nombre": "Lead Con Cita Actual",
            "telefono": "999111222",
            "created_at": now_utc,
            "updated_at": now_utc,
            "estado_id": 4,
            "estado_nombre": "Cita agendada",
            "estado_color": "#6366F1",
            "estado_es_final": False,
            "fuente_nombre": "Facebook",
            "sede_nombre": "Lima",
            "asesor_id": "a1",
            "asesor_nombre": "Asesor 1",
            "supervisor_id": "s1",
            "supervisor_nombre": "Sup 1",
            "estado_actual_es_cita": True,
            "tuvo_estado_cita_historial": True,
            "total_citas_registradas": 1,
            "primera_vez_cita_at": now_utc,
            "en_periodo": True,
            "ultima_fecha_cita": now_utc,
            "tipo_cita": "Cita Virtual",
            "cita_estado_codigo": "pendiente",
            "cita_estado_nombre": "Pendiente",
            "cita_estado_color": "#3B82F6",
            "notas_cita": "Confirmada",
        },
        {
            "id": 102,
            "nombre": "Lead Tuvo Cita Antes",
            "telefono": "999333444",
            "created_at": now_utc,
            "updated_at": now_utc,
            "estado_id": 7,
            "estado_nombre": "Matrícula",
            "estado_color": "#10B981",
            "estado_es_final": True,
            "fuente_nombre": "Instagram",
            "sede_nombre": "Lima",
            "asesor_id": "a1",
            "asesor_nombre": "Asesor 1",
            "supervisor_id": "s1",
            "supervisor_nombre": "Sup 1",
            "estado_actual_es_cita": False,
            "tuvo_estado_cita_historial": True,
            "total_citas_registradas": 2,
            "primera_vez_cita_at": now_utc,
            "en_periodo": False,
            "ultima_fecha_cita": now_utc,
            "tipo_cita": "Presencial",
            "cita_estado_codigo": "completada",
            "cita_estado_nombre": "Completada",
            "cita_estado_color": "#10B981",
            "notas_cita": "Asistió",
        },
    ]

    mock_cur = MockCursor([
        {"has_hist": True, "has_cita_estados": True},
        rows,
    ])
    mock_conn = MockConn(mock_cur)

    @contextmanager
    def _fake_get_db():
        yield mock_conn

    with patch("app.routers.dashboard_supervision.get_db", _fake_get_db):
        res_all = get_seguimiento_citas(periodo="hoy", solo_periodo=False, current_user=admin_user)

    assert res_all["resumen"]["total_leads_citas"] == 2
    assert res_all["resumen"]["con_estado_cita_actual"] == 1
    assert res_all["resumen"]["tuvieron_estado_cita_antes"] == 1
    assert res_all["resumen"]["matriculas_desde_cita"] == 1
    assert res_all["resumen"]["perdidos_desde_cita"] == 0
    assert res_all["resumen"]["pct_cita_a_matricula"] == 50.0
    assert res_all["resumen"]["pct_cita_a_perdido"] == 0.0
    assert res_all["resumen"]["en_periodo"] == 1
    assert len(res_all["leads"]) == 2
    assert res_all["por_asesor"][0]["total"] == 2
    assert res_all["por_asesor"][0]["matriculas"] == 1
    assert res_all["por_asesor"][0]["pct_matricula"] == 50.0
    por_fuente = {f["fuente_nombre"]: f for f in res_all["por_fuente"]}
    assert por_fuente["Facebook"] == {
        "fuente_nombre": "Facebook",
        "con_estado_actual": 1,
        "tuvieron_antes": 0,
        "matriculas": 0,
        "perdidos": 0,
        "pct_matricula": 0.0,
        "pct_perdido": 0.0,
        "total": 1,
    }
    assert por_fuente["Instagram"] == {
        "fuente_nombre": "Instagram",
        "con_estado_actual": 0,
        "tuvieron_antes": 1,
        "matriculas": 1,
        "perdidos": 0,
        "pct_matricula": 100.0,
        "pct_perdido": 0.0,
        "total": 1,
    }

    mock_cur_p = MockCursor([
        {"has_hist": False, "has_cita_estados": True},
        rows,
    ])
    mock_conn_p = MockConn(mock_cur_p)

    @contextmanager
    def _fake_get_db_p():
        yield mock_conn_p

    with patch("app.routers.dashboard_supervision.get_db", _fake_get_db_p):
        res_per = get_seguimiento_citas(periodo="hoy", solo_periodo=True, current_user=admin_user)

    assert res_per["resumen"]["total_leads_citas"] == 1
    assert res_per["leads"][0]["id"] == 101
    assert any("tuvo_cita_contacto_en_periodo" in sql and "AS en_periodo" in sql for sql, _ in mock_cur_p.executed)
    assert any("\\(por [^)]*\\)" in sql for sql, _ in mock_cur_p.executed)
    assert any("tuvo_hist_cita_en_periodo" in sql and len(params) == 6 for sql, params in mock_cur.executed if params)
    assert any(len(params) == 4 for _, params in mock_cur_p.executed if params)


@pytest.mark.unit
def test_cambio_estado_cita_sql_ignora_sufijos_y_motivos():
    """Verifica que el helper excluye '(por Cita)' y '· Motivo: ...' sin usar '%' sin escapar."""
    expr = _cambio_estado_cita_sql("ch")
    assert "ch.notas" in expr
    assert "%" not in expr
    assert "\\(por [^)]*\\)" in expr
    assert "(cita|agendad)" in expr


@pytest.mark.unit
def test_evolucion_citas_rechaza_no_admin():
    """Solo admin puede acceder al endpoint de evolución de citas y cohortes."""
    sup_user = TokenData(user_id="2", email="s@test.com", role="supervisor")
    asesor_user = TokenData(user_id="3", email="a@test.com", role="asesor")

    with pytest.raises(HTTPException) as exc_sup:
        get_evolucion_citas(current_user=sup_user)
    with pytest.raises(HTTPException) as exc_ase:
        get_evolucion_citas(current_user=asesor_user)

    assert exc_sup.value.status_code == 403
    assert exc_ase.value.status_code == 403


@pytest.mark.unit
def test_evolucion_citas_cuantifica_cohortes_tropiezos_y_cartera_antigua():
    """Mide logros del período por cohorte (Setiembre vs actual), tropiezos recuperados y cartera antigua."""
    admin_user = TokenData(user_id="admin-1", email="admin@test.com", role="admin")
    sep_dt = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    nov_dt = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)

    evol_rows = [
        # Caso Fabiola: lead ingresado en Setiembre que logra Separación en Noviembre tras reprogramación
        {
            "id": 201,
            "nombre": "Cliente Setiembre Separacion",
            "telefono": "999111000",
            "created_at": sep_dt,
            "updated_at": nov_dt,
            "estado_id": 5,
            "estado_nombre": "Reserva",
            "estado_color": "#14B8A6",
            "estado_es_final": False,
            "fuente_nombre": "Meta Ads",
            "sede_nombre": "Palma",
            "asesor_id": "a-fab",
            "asesor_nombre": "Fabiola Asesora",
            "supervisor_id": "sup-1",
            "supervisor_nombre": "Paola Cuadros",
            "total_citas_reg": 2,
            "primera_contacto_cv_at": datetime(2026, 9, 12, 16, 0, tzinfo=timezone.utc),
            "tuvo_contacto_cv_periodo": False,
            "tuvo_contacto_cv": True,
            "tuvo_ce_tropiezo": True,
            "tuvo_ce_completada": True,
            "tuvo_ce_pendiente": False,
            "ultimo_cambio_pos_at": nov_dt,
            "tuvo_cambio_pos_periodo": True,
            "gestiones_contacto_periodo": 2,
            "tuvo_hist_cv_periodo": False,
            "tuvo_hist_cv": True,
            "primera_hist_cv_at": None,
            "ultima_hist_pos_at": nov_dt,
            "tuvo_hist_pos_periodo": True,
            "tuvo_hist_tropiezo": True,
            "tuvo_hist_completada": True,
            "cambios_cita_hist": 2,
            "ultima_fecha_cita": datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc),
            "tipo_cita": "Visita a Proyecto",
            "ultima_cita_estado_codigo": "completada",
            "ultima_cita_estado_nombre": "Completada",
            "ultima_cita_estado_color": "#10B981",
            "cita_visita_en_periodo": True,
            "cierre_en_periodo": True,
        },
        # Lead ingresado en Noviembre con Venta Concretada sin tropiezos
        {
            "id": 202,
            "nombre": "Cliente Noviembre Venta",
            "telefono": "999222000",
            "created_at": datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc),
            "updated_at": nov_dt,
            "estado_id": 6,
            "estado_nombre": "Ganado",
            "estado_color": "#10B981",
            "estado_es_final": True,
            "fuente_nombre": "WhatsApp",
            "sede_nombre": "Palma",
            "asesor_id": "a-fab",
            "asesor_nombre": "Fabiola Asesora",
            "supervisor_id": "sup-1",
            "supervisor_nombre": "Paola Cuadros",
            "total_citas_reg": 1,
            "primera_contacto_cv_at": datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc),
            "tuvo_contacto_cv_periodo": True,
            "tuvo_contacto_cv": True,
            "tuvo_ce_tropiezo": False,
            "tuvo_ce_completada": True,
            "tuvo_ce_pendiente": False,
            "ultimo_cambio_pos_at": nov_dt,
            "tuvo_cambio_pos_periodo": True,
            "gestiones_contacto_periodo": 1,
            "tuvo_hist_cv_periodo": False,
            "tuvo_hist_cv": True,
            "primera_hist_cv_at": None,
            "ultima_hist_pos_at": nov_dt,
            "tuvo_hist_pos_periodo": True,
            "tuvo_hist_tropiezo": False,
            "tuvo_hist_completada": False,
            "cambios_cita_hist": 0,
            "ultima_fecha_cita": datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc),
            "tipo_cita": "Cita",
            "ultima_cita_estado_codigo": "completada",
            "ultima_cita_estado_nombre": "Completada",
            "ultima_cita_estado_color": "#10B981",
            "cita_visita_en_periodo": True,
            "cierre_en_periodo": True,
        },
    ]

    cartera_rows = [
        {
            "id": 301,
            "nombre": "Lead Octubre Seguimiento",
            "telefono": "999333000",
            "created_at": datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc),
            "fecha_proxima_gestion": nov_dt,
            "accion_proxima_gestion": "Confirmar visita sábado",
            "estado_nombre": "En negociacion",
            "estado_color": "#F59E0B",
            "fuente_nombre": "TikTok",
            "asesor_id": "a-fab",
            "asesor_nombre": "Fabiola Asesora",
            "supervisor_nombre": "Paola Cuadros",
            "contactos_periodo": 2,
            "llamadas_periodo": 3,
            "ultimo_contacto_at": nov_dt,
            "tuvo_intento_cita": True,
        }
    ]

    mock_cur = MockCursor([
        {"has_hist": True, "has_cita_estados": True, "has_llamadas": True},
        evol_rows,
        cartera_rows,
    ])
    mock_conn = MockConn(mock_cur)

    @contextmanager
    def _fake_get_db():
        yield mock_conn

    with patch("app.routers.dashboard_supervision.get_db", _fake_get_db):
        res = get_evolucion_citas(
            periodo="custom",
            fecha_inicio="2026-11-01",
            fecha_fin="2026-11-30",
            sede_id=None,
            supervisor_id=None,
            asesor_id=None,
            current_user=admin_user,
        )

    assert res["cohorte_corte_mes"] == "2026-11"
    r = res["resumen"]
    assert r["total_citas_visitas_periodo"] == 2
    assert r["citas_visitas_mismo_mes"] == 1
    assert r["citas_visitas_mes_anterior"] == 1
    assert r["separaciones_mismo_mes"] == 0
    assert r["separaciones_mes_anterior"] == 1
    assert r["ventas_mismo_mes"] == 1
    assert r["ventas_mes_anterior"] == 0
    assert r["cierres_mes_anterior"] == 1
    assert r["pct_cierres_mes_anterior"] == 50.0
    assert r["pct_recuperacion_tropiezo"] == 100.0
    assert r["cartera_antigua_total"] == 1
    assert r["cartera_antigua_con_gestion_reciente"] == 1
    assert r["cartera_antigua_con_intento_cita"] == 1

    assert len(res["leads_recuperados"]) == 1
    assert res["leads_recuperados"][0]["cohorte_mes"] == "2026-09"
    assert res["leads_recuperados"][0]["recuperada_tropiezo"] is True
    assert res["por_asesor"][0]["separaciones_meses_anteriores"] == 1
    assert res["por_asesor"][0]["cartera_antigua_gestionada"] == 1


@pytest.mark.unit
def test_record_cita_event_registra_creacion_y_reprogramacion():
    """Verifica que record_cita_event guarda trazabilidad de cita en lead_historial_cambios."""
    from unittest.mock import MagicMock
    from app.services import lead_history_service

    cur = MagicMock()
    # resolve_user_info, resolve_cita_estado(new), has_datos_extra
    cur.fetchone.side_effect = [
        {"nombre": "Paola", "email": "p@test.com", "role": "supervisor"},
        {"codigo": "pendiente", "nombre": "Pendiente"},
        (1,),
        # update: resolve_cita_estado(old), resolve_cita_estado(new), resolve_user_info, has_datos_extra
        {"codigo": "pendiente", "nombre": "Pendiente"},
        {"codigo": "reprogramada", "nombre": "Reprogramada"},
        {"nombre": "Paola", "email": "p@test.com", "role": "supervisor"},
        (1,),
    ]
    user = TokenData(user_id="00000000-0000-0000-0000-000000000001", email="p@test.com", role="supervisor")

    lead_history_service.record_cita_event(
        cur,
        lead_id=55,
        user=user,
        action="create",
        contacto_id=10,
        new_fecha_cita="2026-11-25T10:00:00-05:00",
        new_cita_estado_id=1,
        new_tipo_cita="Visita a Proyecto",
    )
    lead_history_service.record_cita_event(
        cur,
        lead_id=55,
        user=user,
        action="update",
        contacto_id=10,
        old_cita_estado_id=1,
        new_cita_estado_id=3,
    )

    inserts = [
        call for call in cur.execute.call_args_list
        if "INSERT INTO crm.lead_historial_cambios" in str(call[0][0])
    ]
    assert len(inserts) == 2

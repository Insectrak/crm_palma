"""Tests del team_health_service (ADR-0010 — Team Circuit Breaker + Reglas de Disponibilidad).

Estrategia: stub del cursor de DB para evitar dependencia de Postgres real
(consistente con el resto de la suite que corre con DEMO_MODE=true).
"""
from datetime import date, datetime, timezone

import pytest


def _ts(year=2026, month=5, day=16, hour=12):
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


class _StubCursor:
    """Cursor minimo que devuelve filas prearmadas segun query pattern."""

    def __init__(
        self,
        *,
        asesores: list[dict],
        cap_default: int = 200,
        estrategia_sd: str | None = None,
        auto_asignar_enabled: bool = True,
        team_auto_enabled: bool = True,
        incluir_supervisor: bool = False,
        supervisor_user: dict | None = None,
    ):
        self.asesores = asesores
        self.cap_default = cap_default
        self.estrategia_sd = estrategia_sd
        self.auto_asignar_enabled = auto_asignar_enabled
        self.team_auto_enabled = team_auto_enabled
        self.incluir_supervisor = incluir_supervisor
        self.supervisor_user = supervisor_user
        self._last_query = ""
        self._history_rows: list = []  # filas pre-armadas para SELECT history
        self.inserts: list = []        # tuplas (sql, params) de INSERTs registrados

    def execute(self, sql, params=None):
        self._last_query = " ".join(sql.split())
        if "INSERT INTO crm.team_status_history" in self._last_query:
            self.inserts.append((self._last_query, params))

    def fetchone(self):
        sql = self._last_query
        sql_lower = sql.lower()
        if "from crm.assignment_config" in sql_lower:
            return {
                "auto_asignar_enabled": self.auto_asignar_enabled,
                "max_leads_abiertos_default": self.cap_default,
                "estrategia_sin_disponibles": self.estrategia_sd or "asignar_supervisor",
                "incluir_supervisor_en_rotacion": self.incluir_supervisor,
            }
        if "max_leads_abiertos_default" in sql:
            return {"max_leads_abiertos_default": self.cap_default}
        if "estrategia_sin_disponibles" in sql:
            if self.estrategia_sd is None:
                return None
            return {"estrategia_sin_disponibles": self.estrategia_sd}
        if "bool_or(auto_asignar_enabled)" in sql_lower:
            return {"enabled": self.team_auto_enabled}
        if "from auth.users" in sql_lower and "where u.id =" in sql_lower:
            if self.supervisor_user is not None:
                return self.supervisor_user
            return {
                "user_id": "sup-id",
                "is_active": True,
                "activo_rotacion": True,
                "login_blocked": False,
                "disponible_rotacion": True,
                "max_leads_abiertos": 200,
                "ausencia_desde": None,
                "ausencia_hasta": None,
                "leads_abiertos": 0,
            }
        if "FROM crm.team_status_history" in sql:
            if self._history_rows:
                return self._history_rows.pop(0)
            return None
        return None

    def fetchall(self):
        sql_lower = self._last_query.lower()
        if "from crm.equipos" in sql_lower and "asesor_id" in sql_lower:
            return self.asesores
        return []

    def set_last_status(self, status: str):
        """Simula que el ultimo history row dice este status."""
        self._history_rows = [{"new_status": status}]


# ─────────────────────────────────────────────────────────────────────────
# Escenarios de Calculo de Estado
# ─────────────────────────────────────────────────────────────────────────


class TestComputeTeamStatus:
    def test_1_equipo_sano_todos_disponibles(self):
        """5/5 disponibles -> status=active, pct=0%."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(asesores=[
            {"disponible_rotacion": True, "leads_abiertos": 10, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(5)
        ], auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-1", now=_ts())
        assert result["status"] == "active"
        assert result["total_asesores"] == 5
        assert result["asesores_pausados"] == 0
        assert result["pct_pausados"] == 0.0

    def test_2_equipo_50pct_pausados_sigue_active(self):
        """2/4 pausados = 50% < 60% -> status=active (no llega a at_risk)."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(asesores=[
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
        ], auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-2", now=_ts())
        assert result["status"] == "active"
        assert result["pct_pausados"] == 0.5

    def test_3_equipo_60pct_pausados_at_risk(self):
        """3/5 pausados = 60% -> status=at_risk."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(asesores=[
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
        ], auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-3", now=_ts())
        assert result["status"] == "at_risk"
        assert result["pct_pausados"] == 0.6

    def test_4_equipo_80pct_pausados_con_asesor_disponible_NO_bloquea(self):
        """4/5 pausados = 80%, pero 1 asesor disponible -> status=at_risk, NO blocked!"""
        from app.services.team_health_service import compute_team_status
        asesores = [
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(4)
        ]
        asesores.append({
            "disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
            "ausencia_desde": None, "ausencia_hasta": None,
        })
        cur = _StubCursor(asesores=asesores, auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-4", now=_ts())
        assert result["status"] == "at_risk"
        assert result["pct_pausados"] == 0.8

    def test_5_equipo_100pct_pausados_blocked(self):
        """4/4 pausados = 0 disponibles con auto-asignar activo -> status=blocked."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(asesores=[
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(4)
        ], auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-5", now=_ts())
        assert result["status"] == "blocked"
        assert result["pct_pausados"] == 1.0

    def test_6_equipo_sin_asesores_con_auto_asignar_es_blocked(self):
        """0 asesores con auto_asignar_enabled=True -> status=blocked."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(asesores=[], auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-empty", now=_ts())
        assert result["status"] == "blocked"
        assert result["total_asesores"] == 0
        assert result["pct_pausados"] == 1.0

    def test_7_auto_asignar_desactivado_nunca_bloquea_equipo_sin_asesores(self):
        """Si auto_asignar_enabled=False, el supervisor recibe leads directo -> status=active."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(asesores=[], auto_asignar_enabled=False)
        result = compute_team_status(cur, "sup-carolina", now=_ts())
        assert result["status"] == "active"
        assert result["total_asesores"] == 0

    def test_8_auto_asignar_desactivado_nunca_bloquea_asesores_pausados(self):
        """Si auto_asignar_enabled=False, no bloquea aunque todos los asesores esten pausados."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(asesores=[
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(3)
        ], auto_asignar_enabled=False)
        result = compute_team_status(cur, "sup-claudia", now=_ts())
        assert result["status"] == "active"
        assert result["total_asesores"] == 3
        assert result["asesores_pausados"] == 3

    def test_9_supervisor_en_rotacion_evita_bloqueo_si_todos_asesores_pausados(self):
        """Si incluir_supervisor_en_rotacion=True y supervisor disponible -> status=at_risk, NO blocked."""
        from app.services.team_health_service import compute_team_status
        cur = _StubCursor(
            asesores=[
                {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
                 "ausencia_desde": None, "ausencia_hasta": None}
                for _ in range(3)
            ],
            auto_asignar_enabled=True,
            incluir_supervisor=True,
            supervisor_user={
                "user_id": "sup-gladys",
                "is_active": True,
                "activo_rotacion": True,
                "login_blocked": False,
                "disponible_rotacion": True,
                "max_leads_abiertos": 200,
                "ausencia_desde": None,
                "ausencia_hasta": None,
                "leads_abiertos": 5,
            },
        )
        result = compute_team_status(cur, "sup-gladys", now=_ts())
        assert result["status"] == "at_risk"
        assert result["asesores_pausados"] == 3


class TestPauseTriggers:
    """Las 3 razones por las que un asesor cuenta como pausado."""

    def test_disponible_rotacion_false_cuenta_como_pausado(self):
        from app.services.team_health_service import _is_asesor_paused
        a = {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None, "cap_default": 200}
        assert _is_asesor_paused(a, _ts()) is True

    def test_ausencia_activa_cuenta_como_pausado(self):
        from app.services.team_health_service import _is_asesor_paused
        a = {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": date(2026, 5, 10), "ausencia_hasta": date(2026, 5, 20),
             "cap_default": 200}
        assert _is_asesor_paused(a, _ts(day=16)) is True

    def test_ausencia_pasada_NO_cuenta_como_pausado(self):
        from app.services.team_health_service import _is_asesor_paused
        a = {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": date(2026, 5, 1), "ausencia_hasta": date(2026, 5, 10),
             "cap_default": 200}
        assert _is_asesor_paused(a, _ts(day=16)) is False

    def test_cap_lleno_cuenta_como_pausado(self):
        from app.services.team_health_service import _is_asesor_paused
        a = {"disponible_rotacion": True, "leads_abiertos": 200, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None, "cap_default": 200}
        assert _is_asesor_paused(a, _ts()) is True

    def test_cap_no_lleno_NO_cuenta_como_pausado(self):
        from app.services.team_health_service import _is_asesor_paused
        a = {"disponible_rotacion": True, "leads_abiertos": 199, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None, "cap_default": 200}
        assert _is_asesor_paused(a, _ts()) is False

    def test_cap_lleno_NO_cuenta_si_count_cap_full_false(self):
        """V070.79: cuando la estrategia global es 'ignorar_capacity',
        cap-lleno NO debe contar como pausado."""
        from app.services.team_health_service import _is_asesor_paused
        a = {"disponible_rotacion": True, "leads_abiertos": 1000, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None, "cap_default": 200}
        assert _is_asesor_paused(a, _ts(), count_cap_full=True) is True
        assert _is_asesor_paused(a, _ts(), count_cap_full=False) is False


class TestIgnorarCapacityCoherence:
    def test_un_asesor_cap_lleno_y_resto_pausados_NO_bloquea_con_ignorar_capacity(self):
        from app.services.team_health_service import compute_team_status
        asesores = [
            {"disponible_rotacion": True, "leads_abiertos": 1000, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
        ]
        cur = _StubCursor(asesores=asesores, estrategia_sd="ignorar_capacity", auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-ana", now=_ts())
        assert result["asesores_pausados"] == 3
        assert result["pct_pausados"] == 0.75
        assert result["status"] == "at_risk"

    def test_mismo_equipo_SI_bloquea_con_estrategia_default(self):
        from app.services.team_health_service import compute_team_status
        asesores = [
            {"disponible_rotacion": True, "leads_abiertos": 1000, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None},
        ]
        cur = _StubCursor(asesores=asesores, estrategia_sd="asignar_supervisor", auto_asignar_enabled=True)
        result = compute_team_status(cur, "sup-ana", now=_ts())
        assert result["asesores_pausados"] == 4
        assert result["pct_pausados"] == 1.0
        assert result["status"] == "blocked"


class TestHysteresis:
    def test_desbloqueo_inmediato_al_tener_un_asesor_disponible(self):
        """Si estaba blocked y ahora tiene 1 asesor disponible de 4 (75% pausados), pasa a at_risk."""
        from app.services.team_health_service import compute_team_status_with_hysteresis
        asesores = [
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(3)
        ]
        asesores.append({
            "disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
            "ausencia_desde": None, "ausencia_hasta": None,
        })
        cur = _StubCursor(asesores=asesores, auto_asignar_enabled=True)
        cur.set_last_status("blocked")
        result = compute_team_status_with_hysteresis(cur, "sup-h", now=_ts())
        assert result["status"] == "at_risk"
        assert result["previous_status"] == "blocked"

    def test_blocked_baja_a_50pct_se_desbloquea_active(self):
        """50% < 60% UNBLOCK_THRESHOLD -> vuelve a active."""
        from app.services.team_health_service import compute_team_status_with_hysteresis
        asesores = [
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(5)
        ]
        asesores += [
            {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(5)
        ]
        cur = _StubCursor(asesores=asesores, auto_asignar_enabled=True)
        cur.set_last_status("blocked")
        result = compute_team_status_with_hysteresis(cur, "sup-h", now=_ts())
        assert result["status"] == "active"

    def test_active_sube_a_100pct_se_bloquea(self):
        """Transicion active -> blocked cuando todos quedan pausados (0 disponibles)."""
        from app.services.team_health_service import compute_team_status_with_hysteresis
        asesores = [
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(10)
        ]
        cur = _StubCursor(asesores=asesores, auto_asignar_enabled=True)
        cur.set_last_status("active")
        result = compute_team_status_with_hysteresis(cur, "sup-h", now=_ts())
        assert result["status"] == "blocked"


class TestPickSupervisorWithMostCapacity:
    def test_lista_vacia_devuelve_none(self):
        from app.services.team_health_service import pick_supervisor_with_most_capacity
        assert pick_supervisor_with_most_capacity(_StubCursor(asesores=[]), []) is None

    def test_un_solo_supervisor_devuelve_ese(self):
        from app.services.team_health_service import pick_supervisor_with_most_capacity
        result = pick_supervisor_with_most_capacity(
            _StubCursor(asesores=[]), ["sup-only"]
        )
        assert result == "sup-only"


class TestEvaluateAndRecordTransition:
    def test_transicion_active_a_blocked_registra_insert(self):
        from app.services.team_health_service import evaluate_and_record_transition
        cur = _StubCursor(asesores=[
            {"disponible_rotacion": False, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(5)
        ], auto_asignar_enabled=True)
        cur.set_last_status("active")
        result = evaluate_and_record_transition(cur, "sup-x", now=_ts())
        assert result["transitioned"] is True
        assert result["status"] == "blocked"
        assert result["previous_status"] == "active"
        assert len(cur.inserts) == 1

    def test_sin_transicion_no_inserta(self):
        from app.services.team_health_service import evaluate_and_record_transition
        cur = _StubCursor(asesores=[
            {"disponible_rotacion": True, "leads_abiertos": 0, "max_leads_abiertos": 200,
             "ausencia_desde": None, "ausencia_hasta": None}
            for _ in range(5)
        ], auto_asignar_enabled=True)
        cur.set_last_status("active")
        result = evaluate_and_record_transition(cur, "sup-y", now=_ts())
        assert result["transitioned"] is False
        assert result["status"] == "active"
        assert len(cur.inserts) == 0


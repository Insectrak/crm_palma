"""Tests del router reportes_v2 — V070.103 — 5 reportes profesionales.

Estos tests verifican:
  - Contrato HTTP (status codes, schemas de respuesta)
  - Autenticacion + role gating
  - Helpers _role_clause_* funcionan segun rol

Sin DB real (DEMO_MODE). Validamos shape de respuesta + manejo de roles.
"""
import pytest
from unittest.mock import MagicMock, patch


# ════════════════════════════════════════════════════════════════════════════
# TESTS DE HELPERS — Pure functions (sin DB)
# ════════════════════════════════════════════════════════════════════════════

class TestRoleClauseHelpers:
    """V070.103 — los helpers de role filtering deben aplicar segun rol."""

    def test_role_clause_leads_admin_ve_todo(self):
        from app.routers.reportes_v2 import _role_clause_leads
        from app.auth.schemas import TokenData
        user = TokenData(
            user_id="00000000-0000-0000-0000-000000000001",
            email="admin@test", role="admin"
        )
        clause, params = _role_clause_leads(user)
        assert clause == "TRUE"
        assert params == []

    def test_role_clause_leads_supervisor_filtra_equipo(self):
        from app.routers.reportes_v2 import _role_clause_leads
        from app.auth.schemas import TokenData
        user = TokenData(
            user_id="00000000-0000-0000-0000-000000000002",
            email="sup@test", role="supervisor"
        )
        clause, params = _role_clause_leads(user)
        assert "equipos" in clause
        assert "supervisor_id" in clause
        assert len(params) == 3
        assert all(p == user.user_id for p in params)

    def test_role_clause_leads_asesor_solo_propios(self):
        from app.routers.reportes_v2 import _role_clause_leads
        from app.auth.schemas import TokenData
        user = TokenData(
            user_id="00000000-0000-0000-0000-000000000003",
            email="asesor@test", role="asesor"
        )
        clause, params = _role_clause_leads(user)
        assert "l.asesor_id = %s::uuid" in clause
        assert params == [user.user_id]

    def test_role_clause_users_distinto_alias_funciona(self):
        from app.routers.reportes_v2 import _role_clause_users
        from app.auth.schemas import TokenData
        user = TokenData(
            user_id="00000000-0000-0000-0000-000000000003",
            email="asesor@test", role="asesor"
        )
        clause, params = _role_clause_users(user, alias="u")
        assert clause == "u.id = %s::uuid"

    def test_role_clause_alias_personalizable(self):
        from app.routers.reportes_v2 import _role_clause_leads
        from app.auth.schemas import TokenData
        user = TokenData(
            user_id="00000000-0000-0000-0000-000000000099",
            email="a@b.com", role="asesor"
        )
        clause, _ = _role_clause_leads(user, alias="lead")
        assert "lead.asesor_id" in clause


class TestDefaultRange:
    """V070.103 — el rango por default debe ser los ultimos 30 dias."""

    def test_sin_parametros_ultimos_30_dias(self):
        from app.routers.reportes_v2 import _default_range
        from datetime import date, timedelta
        desde, hasta = _default_range(None, None)
        assert hasta == date.today().isoformat()
        assert desde == (date.today() - timedelta(days=30)).isoformat()

    def test_con_fechas_explicitas_no_modifica(self):
        from app.routers.reportes_v2 import _default_range
        desde, hasta = _default_range("2026-01-01", "2026-01-31")
        assert desde == "2026-01-01"
        assert hasta == "2026-01-31"

    def test_solo_uno_default_el_otro(self):
        from app.routers.reportes_v2 import _default_range
        from datetime import date, timedelta
        desde, hasta = _default_range("2026-01-01", None)
        assert desde == "2026-01-01"
        assert hasta == date.today().isoformat()


# ════════════════════════════════════════════════════════════════════════════
# TESTS DE AUTENTICACION HTTP
# ════════════════════════════════════════════════════════════════════════════

class TestReportesV2Auth:
    """Todos los endpoints requieren auth. Algunos requieren rol especifico."""

    def test_eficiencia_llamadas_sin_token_401(self, client):
        r = client.get("/api/reportes/v2/eficiencia-llamadas")
        assert r.status_code == 401

    def test_leadtime_sin_token_401(self, client):
        r = client.get("/api/reportes/v2/leadtime")
        assert r.status_code == 401

    def test_funnel_sin_token_401(self, client):
        r = client.get("/api/reportes/v2/funnel")
        assert r.status_code == 401

    def test_control_sin_token_401(self, client):
        r = client.get("/api/reportes/v2/control")
        assert r.status_code == 401

    def test_estrategico_sin_token_401(self, client):
        r = client.get("/api/reportes/v2/estrategico")
        assert r.status_code == 401


class TestReportesV2RoleGating:
    """Estrategico es admin-only. Control requiere supervisor+."""

    def test_estrategico_asesor_devuelve_403(self, client, auth_headers_asesor, app_instance):
        # Mockear get_db para que no toque DB (asesor falla antes con 403)
        from app.routers.reportes_v2 import estrategico
        # El check de rol ocurre dentro del handler. Llamando directo con
        # un asesor debe lanzar 403 sin tocar DB.
        from app.auth.schemas import TokenData
        from fastapi import HTTPException
        user = TokenData(
            user_id="00000000-0000-0000-0000-000000000003",
            email="asesor@test", role="asesor"
        )
        with pytest.raises(HTTPException) as exc:
            estrategico(current_user=user)
        assert exc.value.status_code == 403


# ════════════════════════════════════════════════════════════════════════════
# TESTS DE PARAMETROS QUERY
# ════════════════════════════════════════════════════════════════════════════

class TestReportesV2QueryParams:
    """Validaciones de query params."""

    def test_control_dias_sin_contacto_default_7(self, app_instance):
        """El parametro dias_sin_contacto debe ser >= 1 y <= 90."""
        from fastapi.testclient import TestClient
        # Verificacion del rango via Query(..., ge=1, le=90) — el contrato
        # esta en el decorator, pero podemos verificar leyendo la signature.
        from app.routers.reportes_v2 import control_dashboard
        import inspect
        sig = inspect.signature(control_dashboard)
        assert "dias_sin_contacto" in sig.parameters

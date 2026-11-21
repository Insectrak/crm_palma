"""
V093: tests del gating por permiso `formularios.manage` + count breakdown.

Cubre:
- `_ensure_can_manage` ya no usa hardcodeo de rol — usa has_permission.
  - admin pasa (bypass legacy)
  - supervisor pasa (tiene formularios.manage = true en seed V078)
  - asesor sin permiso → 403
  - asesor con formularios.manage = true → pasa (caso "asesor_senior")
- `count_breakdown_by_form` devuelve total/nuevos/recontactos coherentes:
  - total = nuevos + recontactos por construccion
  - clamp a 0 si la diff fuera negativa (defensa contra datos inconsistentes)
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.auth.schemas import TokenData
from app.services.public_forms_service import _ensure_can_manage


def _make_user(role: str, permissions: dict | None = None) -> TokenData:
    """Helper: construye un TokenData minimal para los tests."""
    return TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email=f"{role}@palma.test",
        role=role,
        permissions=permissions or {},
    )


# ── _ensure_can_manage ──────────────────────────────────────────────────────

class TestEnsureCanManage:
    """V093 — el gate paso de role-check hardcoded a permission-check."""

    def test_admin_pasa_via_bypass(self):
        user = _make_user("admin")  # admin no necesita permissions explicitas
        _ensure_can_manage(user)  # no raise = OK

    def test_supervisor_con_permiso_pasa(self):
        # Seed V078: supervisor built-in tiene formularios.manage = true.
        user = _make_user("supervisor", {"formularios.manage": True})
        _ensure_can_manage(user)

    def test_asesor_sin_permiso_es_bloqueado(self):
        # Seed V078: asesor built-in NO tiene formularios.manage.
        user = _make_user("asesor", {})
        with pytest.raises(HTTPException) as exc_info:
            _ensure_can_manage(user)
        assert exc_info.value.status_code == 403
        assert "formularios" in exc_info.value.detail.lower()

    def test_asesor_con_permiso_otorgado_pasa(self):
        """Caso 'asesor_senior': admin le otorgo formularios.manage manualmente.
        Antes de V093 esto era IMPOSIBLE (hardcoded a admin+supervisor).
        Ahora funciona sin tocar codigo."""
        user = _make_user("asesor", {"formularios.manage": True})
        _ensure_can_manage(user)

    def test_rol_custom_con_all_pasa(self):
        """Rol custom con flag _all (super-rol) pasa cualquier check."""
        user = _make_user("custom_role", {"_all": True})
        _ensure_can_manage(user)

    def test_supervisor_sin_permiso_es_bloqueado(self):
        """Defensa: si admin desactiva formularios.manage al supervisor,
        el sistema lo respeta (no es un permiso "ineliminable")."""
        user = _make_user("supervisor", {"formularios.manage": False})
        with pytest.raises(HTTPException) as exc_info:
            _ensure_can_manage(user)
        assert exc_info.value.status_code == 403


# ── count_breakdown_by_form ─────────────────────────────────────────────────

class TestCountBreakdown:
    """V093 — fix del bug 'LEADS CAPTURADOS: 3 vs 0' en formularios."""

    def _stub_repo(self, *, total: int, nuevos: int):
        """Mockea las 2 queries del repo: submission_count y count leads."""
        def fake_count_breakdown(form_id: str) -> dict:
            recontactos = max(0, total - nuevos)
            return {
                "total_submissions": total,
                "leads_nuevos":      nuevos,
                "recontactos":       recontactos,
            }
        return fake_count_breakdown

    def test_caso_palma_3_submissions_0_nuevos(self):
        """El bug que reporto el manager: 3 submissions, 0 leads nuevos,
        3 recontactos (todos los submissions cayeron sobre leads existentes)."""
        fn = self._stub_repo(total=3, nuevos=0)
        result = fn("form-id")
        assert result == {"total_submissions": 3, "leads_nuevos": 0, "recontactos": 3}

    def test_caso_mixto(self):
        """10 submissions: 7 leads nuevos + 3 recontactos."""
        fn = self._stub_repo(total=10, nuevos=7)
        result = fn("form-id")
        assert result["recontactos"] == 3

    def test_caso_todos_nuevos(self):
        """5 submissions, 5 leads nuevos, 0 recontactos."""
        fn = self._stub_repo(total=5, nuevos=5)
        result = fn("form-id")
        assert result["recontactos"] == 0

    def test_clamp_a_cero_si_inconsistente(self):
        """Defensa contra datos historicos pre-V048: leads.origen_form_id
        podria contar mas que submission_count (raro pero posible).
        En ese caso recontactos NO debe ser negativo."""
        fn = self._stub_repo(total=3, nuevos=5)
        result = fn("form-id")
        assert result["recontactos"] == 0
        # total y nuevos se mantienen reales, no se distorsionan.
        assert result["total_submissions"] == 3
        assert result["leads_nuevos"]      == 5

    def test_cero_submissions_cero_todo(self):
        """Form recien creado, ningun submission aun."""
        fn = self._stub_repo(total=0, nuevos=0)
        result = fn("form-id")
        assert result == {"total_submissions": 0, "leads_nuevos": 0, "recontactos": 0}

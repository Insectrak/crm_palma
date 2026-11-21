"""
Tests unitarios de los 3 modos de alcance para asignación de leads (ADR-0011):
  1. Global: asigna a cualquier usuario activo de la empresa (como admin).
  2. Equipo: encapsulado estrictamente a su equipo actual (supervisores y asesores, sea supervisor o no).
  3. Personalizado: restringido a una lista seleccionada de supervisores y asesores (allowed_users).
"""
import unittest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

from app.auth.schemas import TokenData
from app.constants import Role
from app.services.assignments_service import (
    can_assign_leads,
    get_assignment_scope,
    _authorize_target,
    _authorize_source,
    _is_in_user_team,
)


USER_ASESOR_1 = "00000000-0000-0000-0000-000000000010"
USER_ASESOR_2 = "00000000-0000-0000-0000-000000000020"
USER_OTHER_ASESOR = "00000000-0000-0000-0000-000000000099"
USER_SUPERVISOR = "00000000-0000-0000-0000-000000000001"
USER_OTHER_SUPERVISOR = "00000000-0000-0000-0000-000000000002"
USER_ADMIN = "00000000-0000-0000-0000-000000000000"


def _make_user(role=Role.ASESOR, user_id=USER_ASESOR_1, permissions=None) -> TokenData:
    return TokenData(
        user_id=user_id,
        email="test@crm.com",
        role=role,
        permissions=permissions or {},
    )


class TestAssignmentScopes(unittest.TestCase):
    def test_can_assign_leads_evaluates_permissions_correctly(self):
        # Admin siempre puede
        self.assertTrue(can_assign_leads(_make_user(Role.ADMIN, USER_ADMIN)))

        # Supervisor legacy siempre puede
        self.assertTrue(can_assign_leads(_make_user(Role.SUPERVISOR, USER_SUPERVISOR)))

        # Asesor normal sin permiso no puede
        self.assertFalse(can_assign_leads(_make_user(Role.ASESOR, USER_ASESOR_1)))

        # Asesor con asignacion.manage puede
        self.assertTrue(can_assign_leads(_make_user(Role.ASESOR, USER_ASESOR_1, {"asignacion.manage": True})))

        # Rol custom con _all puede
        self.assertTrue(can_assign_leads(_make_user(Role.ASESOR, USER_ASESOR_1, {"_all": True})))

    def test_get_assignment_scope_resolves_modes(self):
        # Admin siempre es global
        scope, users = get_assignment_scope(_make_user(Role.ADMIN))
        self.assertEqual(scope, "global")
        self.assertEqual(users, [])

        # Supervisor sin scope explícito -> default 'equipo'
        scope, users = get_assignment_scope(_make_user(Role.SUPERVISOR))
        self.assertEqual(scope, "equipo")
        self.assertEqual(users, [])

        # Asesor con asignacion.manage sin scope explícito -> default 'equipo'
        scope, users = get_assignment_scope(_make_user(Role.ASESOR, permissions={"asignacion.manage": True}))
        self.assertEqual(scope, "equipo")
        self.assertEqual(users, [])

        # Asesor con scope global explícito
        scope, users = get_assignment_scope(_make_user(
            Role.ASESOR,
            permissions={"asignacion.manage": True, "asignacion.scope": "global"}
        ))
        self.assertEqual(scope, "global")

        # Asesor con scope personalizado y usuarios autorizados
        allowed = [USER_ASESOR_2, USER_SUPERVISOR]
        scope, users = get_assignment_scope(_make_user(
            Role.ASESOR,
            permissions={
                "asignacion.manage": True,
                "asignacion.scope": "personalizado",
                "asignacion.allowed_users": allowed,
            }
        ))
        self.assertEqual(scope, "personalizado")
        self.assertEqual(users, allowed)

    @patch("app.services.assignments_service._is_active_assignable_user", return_value=True)
    def test_authorize_target_global_scope(self, mock_active):
        """En modo global, puede asignar a cualquier usuario activo de la empresa."""
        user = _make_user(Role.ASESOR, USER_ASESOR_1, {"asignacion.manage": True, "asignacion.scope": "global"})

        # Puede asignar a cualquier asesor u otro supervisor
        _authorize_target(user, USER_OTHER_ASESOR)
        _authorize_target(user, USER_OTHER_SUPERVISOR)
        # Puede liberar (None)
        _authorize_target(user, None)

    @patch("app.services.assignments_service._is_in_user_team")
    def test_authorize_target_equipo_scope_allows_supervisor_and_teammates(self, mock_in_team):
        """En modo equipo, un asesor puede asignar a su supervisor ('sea supervisor o no') y a sus compañeros."""
        user = _make_user(Role.ASESOR, USER_ASESOR_1, {"asignacion.manage": True, "asignacion.scope": "equipo"})

        def mock_is_in_team(uid, role, target):
            return target in (USER_ASESOR_1, USER_ASESOR_2, USER_SUPERVISOR)

        mock_in_team.side_effect = mock_is_in_team

        # 1. Asignar a su supervisor es válido ("sea supervisor o no")
        _authorize_target(user, USER_SUPERVISOR)

        # 2. Asignar a su compañero asesor es válido
        _authorize_target(user, USER_ASESOR_2)

        # 3. Asignarse a sí mismo es válido
        _authorize_target(user, USER_ASESOR_1)

        # 4. Asignar a alguien fuera de su equipo levanta 403
        with self.assertRaises(HTTPException) as ctx:
            _authorize_target(user, USER_OTHER_ASESOR)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertTrue("no pertenece a tu equipo" in ctx.exception.detail or "solo puedes asignar" in ctx.exception.detail)

    @patch("app.services.assignments_service._is_active_assignable_user", return_value=True)
    def test_authorize_target_personalizado_scope(self, mock_active):
        """En modo personalizado, solo puede asignar a los usuarios en allowed_users."""
        user = _make_user(Role.ASESOR, USER_ASESOR_1, {
            "asignacion.manage": True,
            "asignacion.scope": "personalizado",
            "asignacion.allowed_users": [USER_ASESOR_2, USER_SUPERVISOR],
        })

        # Usuarios en la lista son autorizados
        _authorize_target(user, USER_ASESOR_2)
        _authorize_target(user, USER_SUPERVISOR)

        # Usuario no listado levanta 403
        with self.assertRaises(HTTPException) as ctx:
            _authorize_target(user, USER_OTHER_ASESOR)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("no está en la lista de usuarios autorizados", ctx.exception.detail)

    def test_authorize_target_raises_403_when_no_permission(self):
        """Un usuario sin permiso de asignación recibe 403 inmediato."""
        user = _make_user(Role.ASESOR, USER_ASESOR_1, permissions={})
        with self.assertRaises(HTTPException) as ctx:
            _authorize_target(user, USER_ASESOR_2)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("No tienes permiso", ctx.exception.detail)

    @patch("app.services.assignments_service._is_in_user_team")
    def test_authorize_source_equipo_scope(self, mock_in_team):
        """En modo equipo, solo puede reasignar leads de su propio equipo."""
        user = _make_user(Role.ASESOR, USER_ASESOR_1, {"asignacion.manage": True, "asignacion.scope": "equipo"})

        def mock_is_in_team(uid, role, target):
            return target in (USER_ASESOR_1, USER_ASESOR_2, USER_SUPERVISOR)

        mock_in_team.side_effect = mock_is_in_team

        # Lead asignado a sí mismo -> OK
        _authorize_source(user, current_asesor_id=USER_ASESOR_1)

        # Lead asignado a compañero de equipo -> OK
        _authorize_source(user, current_asesor_id=USER_ASESOR_2)

        # Lead asignado a otro asesor fuera del equipo -> 403
        with self.assertRaises(HTTPException) as ctx:
            _authorize_source(user, current_asesor_id=USER_OTHER_ASESOR)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("no pertenece a tu equipo", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()

"""
Tests V089 — control del permiso `notificaciones.manage_own`.

El admin puede revocar este permiso a un rol para que sus usuarios no
puedan apagar su kill switch personal ni cambiar el horario silencioso.

Caso de uso: la manager de Palma quiere que los 13 asesores SIEMPRE
reciban push de leads, sin que ellos puedan desactivarlos por error o
intencionalmente.
"""
import pytest

from tests.fixtures import fake_db_returning


# ── PUT /api/settings/me/notification-prefs ──────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_save_notif_prefs_as_admin_always_passes(client, auth_headers_admin, monkeypatch):
    """Admin legacy bypasea siempre — su rol no requiere el permiso."""
    monkeypatch.setattr(
        "app.services.notification_service.save_user_prefs",
        lambda uid, data: {**data, "user_id": uid},
    )

    response = client.put(
        "/api/settings/me/notification-prefs",
        headers=auth_headers_admin,
        json={"push_enabled": False, "events_disabled": [], "urgent_events_disabled": []},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.auth
@pytest.mark.unit
def test_save_notif_prefs_as_asesor_with_permission_succeeds(
    client, monkeypatch, auth_token_asesor,
):
    """Asesor con permiso `notificaciones.manage_own` puede modificar sus
    preferencias (comportamiento default tras V089 — sin cambios para los
    asesores históricos que ya tenían el flag TRUE en built-in)."""
    # Generamos un token con el permiso TRUE explícito.
    from app.auth.jwt import create_access_token
    token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000003",
        "email": "asesor@test.local",
        "role": "asesor",
        "permissions": {"notificaciones.manage_own": True},
    })
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(
        "app.services.notification_service.save_user_prefs",
        lambda uid, data: {**data, "user_id": uid},
    )

    response = client.put(
        "/api/settings/me/notification-prefs",
        headers=headers,
        json={"push_enabled": False, "events_disabled": [], "urgent_events_disabled": []},
    )

    assert response.status_code == 200
    # Token sin usar para asesor con permiso revocado:
    assert auth_token_asesor is not None


@pytest.mark.auth
@pytest.mark.unit
def test_save_notif_prefs_without_permission_returns_403(client):
    """Asesor con el permiso `notificaciones.manage_own` REVOCADO no puede
    persistir preferencias. El backend valida defense-in-depth aunque el
    frontend ya esconda el tab.

    Bug ID: V089 manager_wants_to_force_push_for_all_advisors
    """
    from app.auth.jwt import create_access_token
    token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000003",
        "email": "asesor@test.local",
        "role": "asesor",
        # Sin notificaciones.manage_own — el admin lo revocó.
        "permissions": {"leads.view": True},
    })
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put(
        "/api/settings/me/notification-prefs",
        headers=headers,
        json={"push_enabled": False, "events_disabled": [], "urgent_events_disabled": []},
    )

    assert response.status_code == 403
    detail = response.json()["detail"].lower()
    assert "administrador" in detail or "supervisor" in detail


@pytest.mark.auth
@pytest.mark.unit
def test_save_notif_prefs_with_all_bypass_passes(client, monkeypatch):
    """Si el rol custom tiene `_all`: true, el chequeo del permiso individual
    se saltea (bypass clásico)."""
    from app.auth.jwt import create_access_token
    token = create_access_token({
        "sub": "00000000-0000-0000-0000-000000000003",
        "email": "asesor@test.local",
        "role": "asesor",
        "permissions": {"_all": True},
    })
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(
        "app.services.notification_service.save_user_prefs",
        lambda uid, data: {**data, "user_id": uid},
    )

    response = client.put(
        "/api/settings/me/notification-prefs",
        headers=headers,
        json={"push_enabled": True, "events_disabled": [], "urgent_events_disabled": []},
    )

    assert response.status_code == 200


# Suprimir warning unused import (fake_db_returning expuesto por consistencia
# con los otros tests del módulo; este archivo no lo usa porque el backend
# del endpoint no toca DB cuando save_user_prefs está mockeado).
_ = fake_db_returning

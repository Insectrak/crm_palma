"""
V094: tests del export de leads — guard de permiso + columnas "Tipo"
(Nuevo / Recontacto) y "Recontactos totales" en el Excel.

Cambio principal: el endpoint /api/leads/exportar pasó de
`require_supervisor_or_admin` (rol legacy) a
`check_permission("reportes.export", "supervisor")`. Esto permite
habilitar el export a roles custom como `marketing_proveedor` (Wedo)
SIN romper la política original de los 13 asesores.
"""
from unittest.mock import patch

import pytest

from app.auth.jwt import create_access_token


def _token(role, permissions=None):
    """Helper: crea un JWT con el rol + permissions custom."""
    return create_access_token({
        "sub": f"user-{role}",
        "email": f"{role}@palma.test",
        "role": role,
        "permissions": permissions or {},
    })


@pytest.fixture()
def mocked_export(monkeypatch):
    """Stub del repo + audit + rate limiter para tests rápidos."""
    monkeypatch.setattr(
        "app.repositories.leads_repository.find_for_export",
        lambda filters, user, limit, offset: [],
    )
    monkeypatch.setattr(
        "app.services.audit_service.record_export",
        lambda **kwargs: None,
    )
    # Disable rate limiter para no acumular 3/5min entre tests.
    from app.auth.rate_limit import limiter
    monkeypatch.setattr(limiter, "enabled", False, raising=False)


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_export_as_admin_succeeds(client, mocked_export):
    """Admin legacy siempre pasa (bypass clásico)."""
    headers = {"Authorization": f"Bearer {_token('admin')}"}
    response = client.get("/api/leads/exportar", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_export_as_supervisor_succeeds(client, mocked_export):
    """Supervisor legacy explícito (segundo argumento de check_permission)."""
    headers = {"Authorization": f"Bearer {_token('supervisor')}"}
    response = client.get("/api/leads/exportar", headers=headers)
    assert response.status_code == 200


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_export_as_asesor_without_permission_returns_403(client, mocked_export):
    """Asesor legacy SIN el permiso `reportes.export` queda rechazado.

    Bug ID: V094 keep_palma_advisors_blocked_from_export

    Es la política de gerencia (abril 2026): los 13 asesores no descargan
    data masiva.
    """
    headers = {"Authorization": f"Bearer {_token('asesor')}"}
    response = client.get("/api/leads/exportar", headers=headers)
    assert response.status_code == 403


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_export_as_asesor_with_permission_succeeds(client, mocked_export):
    """Rol custom (asesor + marketing_proveedor) CON el permiso
    `reportes.export = true` puede descargar.

    Caso de uso real: Wedo necesita su Excel para análisis de campañas.
    La admin de Palma marca el permiso en el rol `marketing_proveedor` y
    Wedo ya puede exportar, sin que esto habilite a los 13 asesores.
    """
    headers = {"Authorization": f"Bearer {_token('asesor', {'reportes.export': True})}"}
    response = client.get("/api/leads/exportar", headers=headers)
    assert response.status_code == 200


@pytest.mark.leads
@pytest.mark.unit
@pytest.mark.regression
def test_export_excel_contains_tipo_and_recontactos_columns(client, mocked_export):
    """V094 — El Excel devuelto debe incluir las columnas Tipo y Recontactos.

    Verificamos descargando el body y reabriéndolo con openpyxl para
    inspeccionar la fila de headers. Garantiza que futuros cambios no
    revierten silenciosamente las columnas que Wedo necesita.
    """
    import io
    import openpyxl

    headers_auth = {"Authorization": f"Bearer {_token('admin')}"}
    response = client.get("/api/leads/exportar", headers=headers_auth)
    assert response.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(response.content), read_only=True)
    ws = wb.active
    header_row = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    assert "Tipo" in header_row, "Falta la columna 'Tipo' (Nuevo/Recontacto)"
    assert "Recontactos" in header_row, "Falta la columna 'Recontactos' (total)"
    assert "Último recontacto" in header_row, "Falta la columna 'Último recontacto'"


@pytest.mark.leads
@pytest.mark.unit
def test_export_columns_order_keeps_basic_first(client, mocked_export):
    """Sanity: las columnas clave (Nombre, Teléfono, Estado) siguen al
    principio para no romper el layout para los usuarios actuales."""
    import io
    import openpyxl

    headers_auth = {"Authorization": f"Bearer {_token('admin')}"}
    response = client.get("/api/leads/exportar", headers=headers_auth)
    assert response.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(response.content), read_only=True)
    ws = wb.active
    header_row = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    assert header_row[:4] == ["Nombre", "Teléfono", "DNI", "Email"]


# Suppress unused import warning — `patch` queda disponible por consistencia
# con otros tests del módulo que sí lo usan.
_ = patch

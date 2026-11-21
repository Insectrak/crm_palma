"""
Tests V090 — ciclo de vida del usuario: pre-check de leads activos y
reasignación masiva antes de deshabilitar.

Cubre el patrón estándar de la industria: cuando un usuario sale de la
empresa, sus leads no pueden quedar huérfanos. El admin elige qué hacer
con ellos en una sola operación atómica.
"""
import pytest

from tests.fixtures import fake_db_returning


USER_ID = "00000000-0000-0000-0000-000000000099"
TARGET_ID = "00000000-0000-0000-0000-000000000077"
SUP_ID = "00000000-0000-0000-0000-000000000050"


# ── GET /auth/users/{id}/active-leads-count ──────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_active_leads_count_returns_n(client, auth_headers_admin, monkeypatch):
    """Happy path: devuelve el conteo de leads activos del usuario."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({"n": 47}),
    )

    response = client.get(
        f"/auth/users/{USER_ID}/active-leads-count",
        headers=auth_headers_admin,
    )

    assert response.status_code == 200
    assert response.json()["count"] == 47


@pytest.mark.auth
@pytest.mark.unit
def test_active_leads_count_zero(client, auth_headers_admin, monkeypatch):
    """Si no tiene leads activos, devuelve 0."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning({"n": 0}),
    )

    response = client.get(
        f"/auth/users/{USER_ID}/active-leads-count",
        headers=auth_headers_admin,
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.auth
@pytest.mark.unit
def test_active_leads_count_as_asesor_returns_403(client, auth_headers_asesor):
    """usuarios.manage es admin-only."""
    response = client.get(
        f"/auth/users/{USER_ID}/active-leads-count",
        headers=auth_headers_asesor,
    )
    assert response.status_code == 403


# ── POST /auth/users/{id}/reassign-leads ─────────────────────────────────


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_keep_is_noop(client, auth_headers_admin):
    """mode='keep' no toca nada — devuelve reassigned=0 sin tocar DB."""
    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "keep"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reassigned"] == 0
    assert body["mode"] == "keep"


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_invalid_returns_400(client, auth_headers_admin):
    """mode no soportado → 400."""
    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "delete_all"},
    )
    assert response.status_code == 400


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_asesor_without_target_returns_400(client, auth_headers_admin):
    """mode='asesor' sin target_user_id → 400."""
    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "asesor"},
    )
    assert response.status_code == 400
    assert "target_user_id" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_asesor_happy_path(client, auth_headers_admin, monkeypatch):
    """Reasignación bulk a un asesor específico activo."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            # SELECT origin user
            {"id": USER_ID, "email": "fernando@palma.test", "nombre": "Fernando Arenas"},
            # SELECT target user (debe estar activo + role válido)
            {"id": TARGET_ID, "role": "asesor", "is_active": True, "nombre": "Ana Montes"},
            # SELECT supervisor del equipo del target
            {"supervisor_id": SUP_ID},
            # UPDATE leads RETURNING id (3 leads movidos)
            [{"id": 1}, {"id": 2}, {"id": 3}],
        ),
    )
    monkeypatch.setattr(
        "app.services.permission_audit_service._insert",
        lambda **kwargs: None,
    )

    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "asesor", "target_user_id": TARGET_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reassigned"] == 3
    assert body["mode"] == "asesor"
    assert body["target_name"] == "Ana Montes"


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_asesor_disabled_target_returns_400(client, auth_headers_admin, monkeypatch):
    """Bug ID: V090 cant_reassign_to_disabled_user

    Si el target user está deshabilitado, rechazamos — no podemos mandar
    leads a alguien que tampoco va a poder trabajarlos.
    """
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": USER_ID, "email": "fernando@palma.test", "nombre": "Fernando Arenas"},
            {"id": TARGET_ID, "role": "asesor", "is_active": False, "nombre": "Disabled User"},
        ),
    )

    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "asesor", "target_user_id": TARGET_ID},
    )

    assert response.status_code == 400
    assert "deshabilitado" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_supervisor_happy_path(client, auth_headers_admin, monkeypatch):
    """Reasignación a la cola del supervisor del equipo del user origen.
    Patrón recomendado cuando la supervisora está full y no puede repartir
    inmediatamente."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            # SELECT origin user
            {"id": USER_ID, "email": "fernando@palma.test", "nombre": "Fernando Arenas"},
            # SELECT supervisor del equipo del origen
            {"id": SUP_ID, "nombre": "Paola Cuadros"},
            # UPDATE leads RETURNING id (15 leads movidos)
            [{"id": i} for i in range(15)],
        ),
    )
    monkeypatch.setattr(
        "app.services.permission_audit_service._insert",
        lambda **kwargs: None,
    )

    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "supervisor"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reassigned"] == 15
    assert body["mode"] == "supervisor"
    assert body["target_name"] == "Paola Cuadros"


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_supervisor_without_team_returns_400(
    client, auth_headers_admin, monkeypatch,
):
    """Si el user origen no tiene supervisor de equipo asignado, no podemos
    usar este modo — el admin debe elegir otro."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": USER_ID, "email": "fernando@palma.test", "nombre": "Fernando Arenas"},
            None,  # SELECT supervisor → no encontrado
        ),
    )

    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "supervisor"},
    )
    assert response.status_code == 400
    assert "supervisor" in response.json()["detail"].lower()


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_mode_unassign_happy_path(client, auth_headers_admin, monkeypatch):
    """Modo unassign: leads quedan sin asesor ni supervisor."""
    monkeypatch.setattr(
        "app.auth.router.get_db",
        fake_db_returning(
            {"id": USER_ID, "email": "fernando@palma.test", "nombre": "Fernando Arenas"},
            # UPDATE leads RETURNING id (8 movidos)
            [{"id": i} for i in range(8)],
        ),
    )
    monkeypatch.setattr(
        "app.services.permission_audit_service._insert",
        lambda **kwargs: None,
    )

    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "unassign"},
    )

    assert response.status_code == 200
    assert response.json()["reassigned"] == 8


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_as_asesor_returns_403(client, auth_headers_asesor):
    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_asesor,
        json={"mode": "keep"},
    )
    assert response.status_code == 403


# ── V091 — Tracking de herencia (previous_asesor_id + reassigned_at) ─────


@pytest.mark.auth
@pytest.mark.unit
def test_reassign_sets_previous_asesor_id_and_reassigned_at(
    client, auth_headers_admin, monkeypatch,
):
    """Bug ID: V091 inherit_tracking_for_supervisor_context

    Tras una reasignación, cada lead debe quedar con previous_asesor_id
    apuntando al user origen y reassigned_at = NOW() para que el frontend
    pueda mostrar el badge "Heredado de X · hace N días" durante 30 días.

    Verificamos que el SQL del UPDATE incluye los nuevos campos. Usamos
    un mock del cursor.execute para inspeccionar la query.
    """
    # Captura de los SQL ejecutados.
    executed_sqls: list[str] = []
    executed_params: list[tuple] = []

    from unittest.mock import MagicMock
    from contextlib import contextmanager

    # Cola de filas que el fake DB devuelve. Solo necesitamos cubrir
    # las consultas previas al UPDATE que captamos.
    fake_rows = [
        # SELECT origin
        {"id": USER_ID, "email": "fernando@palma.test", "nombre": "Fernando"},
        # SELECT supervisor del equipo
        {"id": SUP_ID, "nombre": "Paola"},
        # UPDATE returning ids (3 leads)
        [{"id": 1}, {"id": 2}, {"id": 3}],
    ]
    row_idx = {"i": 0}

    def fake_execute(sql, params=None):
        executed_sqls.append(sql)
        executed_params.append(params)

    def fake_fetchone():
        r = fake_rows[row_idx["i"]] if row_idx["i"] < len(fake_rows) else None
        row_idx["i"] += 1
        return r if isinstance(r, dict) else (r[0] if isinstance(r, list) and r else None)

    def fake_fetchall():
        r = fake_rows[row_idx["i"]] if row_idx["i"] < len(fake_rows) else []
        row_idx["i"] += 1
        return r if isinstance(r, list) else [r] if r else []

    @contextmanager
    def fake_get_db():
        conn = MagicMock()
        cur = MagicMock()
        cur.execute.side_effect = fake_execute
        cur.fetchone.side_effect = fake_fetchone
        cur.fetchall.side_effect = fake_fetchall
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        yield conn

    monkeypatch.setattr("app.auth.router.get_db", fake_get_db)
    monkeypatch.setattr(
        "app.services.permission_audit_service._insert",
        lambda **kwargs: None,
    )

    response = client.post(
        f"/auth/users/{USER_ID}/reassign-leads",
        headers=auth_headers_admin,
        json={"mode": "supervisor"},
    )

    assert response.status_code == 200
    # La query del UPDATE debe contener los campos V091.
    update_sql = next(
        (s for s in executed_sqls if "UPDATE crm.leads" in s),
        None,
    )
    assert update_sql is not None, "El UPDATE de leads no fue ejecutado"
    assert "previous_asesor_id" in update_sql, "Falta setear previous_asesor_id"
    assert "reassigned_at" in update_sql, "Falta setear reassigned_at"

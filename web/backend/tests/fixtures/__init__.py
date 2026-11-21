"""
Factory helpers para crear test data de forma consistente y DRY.

Patron tomado de factory_boy + faker, pero implementado inline para
mantener cero dependencias nuevas.

Reglas:
  - Cada factory devuelve un dict listo para usar (no instancia un objeto
    de SQLAlchemy ni nada concreto — los tests trabajan con dicts).
  - Defaults razonables para que el caller solo pase lo que importa.
  - **overrides para customizar cualquier campo.
  - UUIDs determinísticos por test (no random) para que los failures
    sean reproducibles.

Uso:
    from tests.fixtures import make_user, make_lead

    admin = make_user(role="admin")
    lead = make_lead(asesor_id=admin["id"], calidad="CALIENTE")
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


# UUIDs fijos para tests deterministas. Si necesitas mas, agregar aqui
# en vez de generar uuid4 random (rompe reproducibilidad de failures).
TEST_UUID_ADMIN      = "00000000-0000-0000-0000-000000000001"
TEST_UUID_SUPERVISOR = "00000000-0000-0000-0000-000000000002"
TEST_UUID_ASESOR     = "00000000-0000-0000-0000-000000000003"
TEST_UUID_LEAD       = "00000000-0000-0000-0000-000000000100"
TEST_UUID_FUENTE_FB  = "00000000-0000-0000-0000-000000000200"


def _now_iso() -> str:
    """Timestamp ISO 8601 estable para tests."""
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()


# ── User factory ──────────────────────────────────────────────────────────

def make_user(
    *,
    user_id: str | None = None,
    email: str = "user@palma.test",
    role: str = "asesor",
    first_name: str = "Test",
    last_name: str = "User",
    is_active: bool = True,
    password_hash: str = "$2b$12$fakehashfakefakefakefakefakefakefakefakefakefakefakefake",
    telefono: str | None = None,
    default_wa_number_id: int | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Crea un dict con la forma de auth.users compatible con RealDictCursor.

    Defaults: asesor activo, password_hash bcrypt placeholder, sin telefono.

    Pasa **overrides para campos custom (ej: created_at, updated_at).
    """
    if user_id is None:
        # Si role tiene UUID fijo conocido, usalo; sino generar deterministico
        user_id = {
            "admin":      TEST_UUID_ADMIN,
            "supervisor": TEST_UUID_SUPERVISOR,
            "asesor":     TEST_UUID_ASESOR,
        }.get(role, str(uuid.uuid5(uuid.NAMESPACE_DNS, email)))

    base = {
        "id":                   user_id,
        "email":                email.lower().strip(),
        "role":                 role,
        "first_name":           first_name,
        "last_name":            last_name,
        "is_active":            is_active,
        "password_hash":        password_hash,
        "telefono":             telefono,
        "default_wa_number_id": default_wa_number_id,
        "created_at":           _now_iso(),
        "updated_at":           _now_iso(),
    }
    base.update(overrides)
    return base


# ── Lead factory ──────────────────────────────────────────────────────────

def make_lead(
    *,
    lead_id: int = 42,
    nombres: str = "Juan Carlos",
    apellidos: str = "Test Ramirez",
    telefono: str = "+51987654321",
    email: str | None = None,
    asesor_id: str | None = None,
    supervisor_id: str | None = TEST_UUID_SUPERVISOR,
    fuente_id: int = 1,
    estado_id: int = 1,
    calidad: str | None = None,
    campana: str = "Test Campaign",
    fuente_externa_id: str | None = None,
    activo: bool = True,
    **overrides: Any,
) -> dict[str, Any]:
    """Crea un dict con la forma de crm.leads.

    Defaults: lead activo, sin calidad, asignado a supervisor (sin asesor).

    Para tests de routing, pasar asesor_id=None para simular lead sin asignar.
    """
    base = {
        "id":                lead_id,
        "nombres":           nombres,
        "apellidos":         apellidos,
        "telefono":          telefono,
        "email":             email,
        "asesor_id":         asesor_id,
        "supervisor_id":     supervisor_id,
        "fuente_id":         fuente_id,
        "estado_id":         estado_id,
        "calidad":           calidad,
        "campana":           campana,
        "fuente_externa_id": fuente_externa_id,
        "activo":            activo,
        "created_at":        _now_iso(),
        "updated_at":        _now_iso(),
    }
    base.update(overrides)
    return base


# ── DB mock helpers ───────────────────────────────────────────────────────

def fake_db_returning(*rows: dict | list[dict] | None):
    """Context manager generator que simula app.database.get_db.

    Cada llamada al cursor.execute() consume el siguiente "row" de la cola.
    - Si row es dict      → cur.fetchone() devuelve ese dict.
    - Si row es list      → cur.fetchall() devuelve esa lista.
    - Si row es None      → cur.fetchone() devuelve None (no match).

    Usado con monkeypatch:
        monkeypatch.setattr("app.auth.router.get_db", fake_db_returning(user_dict))

    Para queries multiples consecutivas:
        fake_db_returning(user_dict, [lead1, lead2], None)
    """
    from contextlib import contextmanager
    from unittest.mock import MagicMock

    @contextmanager
    def _conn_ctx():
        conn = MagicMock()
        cur = MagicMock()
        # Cola de rows que se van consumiendo en cada fetchone/fetchall
        cur._rows = list(rows)
        cur._row_idx = 0

        def _next_row():
            if cur._row_idx < len(cur._rows):
                r = cur._rows[cur._row_idx]
                cur._row_idx += 1
                return r
            return None

        def _fetchone(*_, **__):
            r = _next_row()
            if isinstance(r, list):
                return r[0] if r else None
            return r

        def _fetchall(*_, **__):
            r = _next_row()
            if isinstance(r, list):
                return r
            if r is None:
                return []
            return [r]

        cur.fetchone.side_effect = _fetchone
        cur.fetchall.side_effect = _fetchall
        cur.rowcount = 1
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__  = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        conn.commit = MagicMock()
        conn.rollback = MagicMock()
        yield conn

    def _get_db_replacement():
        return _conn_ctx()

    return _get_db_replacement

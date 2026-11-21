"""Tests del repositorio de Field Mappings (HubSpot/Salesforce-style).

Cubren la lógica pura que no toca DB real:

  - `slugify_key`: normalización NFKD + snake_case.
  - `_validate_mapping`: rechaza target_type/column fuera de whitelist,
    exige target_key salvo para 'ignore', y valida existencia para property.
  - `apply_mappings`: sobre un cursor falso, aplica reglas a raw_field_data
    y clasifica cada campo (applied/ignored/unmapped/errors).

No tocan PostgreSQL. Corren con DEMO_MODE=true.
"""
from __future__ import annotations

from typing import Optional

import pytest


# ── slugify_key ─────────────────────────────────────────────────────────────

def test_slugify_removes_accents_and_lowercases():
    from app.services.integrations.field_mappings_repo import slugify_key
    assert slugify_key("Proyecto de Interés") == "proyecto_de_interes"


def test_slugify_replaces_non_alphanumeric_with_underscore():
    from app.services.integrations.field_mappings_repo import slugify_key
    # Los símbolos se reemplazan 1:1 por `_`; los saltos de línea también.
    # Se aceptan subrayados consecutivos (no hay colapso) pero nunca hay
    # underscore al inicio o al final porque `strip("_")` lo elimina.
    out = slugify_key("¿Canal preferido?")
    assert out.startswith("canal")
    assert not out.startswith("_") and not out.endswith("_")
    # Sólo contiene [a-z0-9_].
    assert all(c.isalnum() or c == "_" for c in out)


def test_slugify_empty_returns_empty():
    from app.services.integrations.field_mappings_repo import slugify_key
    assert slugify_key("") == ""
    assert slugify_key(None) == ""


# ── _validate_mapping ───────────────────────────────────────────────────────

def test_validate_rejects_unknown_target_type():
    from app.services.integrations.field_mappings_repo import (
        _validate_mapping,
        FieldMappingError,
    )
    with pytest.raises(FieldMappingError) as exc:
        _validate_mapping(target_type="foo", target_key="bar")
    assert exc.value.status_code == 400


def test_validate_ignore_does_not_require_target_key():
    from app.services.integrations.field_mappings_repo import _validate_mapping
    assert _validate_mapping(target_type="ignore", target_key=None) is None


def test_validate_column_requires_whitelisted_key():
    from app.services.integrations.field_mappings_repo import (
        _validate_mapping,
        FieldMappingError,
    )
    # Columna fuera de ALLOWED_COLUMN_TARGETS debe fallar, impidiendo SQL
    # injection vía nombres de columna dinámicos.
    with pytest.raises(FieldMappingError):
        _validate_mapping(target_type="column", target_key="password_hash")
    # Una válida pasa.
    assert _validate_mapping(target_type="column", target_key="email") == "email"


def test_validate_column_requires_non_empty_key():
    from app.services.integrations.field_mappings_repo import (
        _validate_mapping,
        FieldMappingError,
    )
    with pytest.raises(FieldMappingError):
        _validate_mapping(target_type="column", target_key="")
    with pytest.raises(FieldMappingError):
        _validate_mapping(target_type="column", target_key=None)


def test_validate_property_requires_existing_definition(monkeypatch):
    from app.services.integrations import field_mappings_repo as fm
    # Sin definición → debe fallar.
    monkeypatch.setattr(fm, "get_property_definition", lambda _k: None)
    with pytest.raises(fm.FieldMappingError):
        fm._validate_mapping(target_type="property", target_key="proyecto_interes")

    # Con definición inactiva → también falla.
    monkeypatch.setattr(
        fm, "get_property_definition",
        lambda _k: {"property_key": _k, "is_active": False},
    )
    with pytest.raises(fm.FieldMappingError):
        fm._validate_mapping(target_type="property", target_key="proyecto_interes")

    # Con definición activa → pasa.
    monkeypatch.setattr(
        fm, "get_property_definition",
        lambda _k: {"property_key": _k, "is_active": True},
    )
    assert fm._validate_mapping(
        target_type="property",
        target_key="proyecto_interes",
    ) == "proyecto_interes"


# ── apply_mappings con cursor falso ─────────────────────────────────────────

class _FakeCursor:
    """Cursor en memoria suficiente para apply_mappings.

    Responde al SELECT de _load_mappings_for_form devolviendo reglas
    preconfiguradas y acepta INSERT/UPDATE sin hacer nada.
    """

    def __init__(self, rules: Optional[list[dict]] = None):
        self._rules = rules or []
        self.executed: list[tuple] = []
        self._last_query: str = ""

    def execute(self, sql, params=None):
        self._last_query = sql
        self.executed.append((sql, params))

    def fetchall(self):
        # Solo hay un SELECT en apply_mappings (el de form_field_mappings).
        if "form_field_mappings" in self._last_query:
            return list(self._rules)
        return []

    def fetchone(self):
        return None


def test_apply_mappings_counts_unmapped_when_no_rules():
    from app.services.integrations import field_mappings_repo as fm
    cur = _FakeCursor(rules=[])
    stats = fm.apply_mappings(
        cur,
        lead_id=42,
        provider="meta",
        form_id="form-9",
        raw_field_data=[
            {"name": "proyecto_interes", "values": ["Lote A"]},
            {"name": "tipo_pago",         "values": ["Crédito"]},
        ],
    )
    assert stats == {"applied": 0, "ignored": 0, "unmapped": 2, "errors": 0}


def test_apply_mappings_routes_column_property_and_ignore():
    from app.services.integrations import field_mappings_repo as fm
    cur = _FakeCursor(rules=[
        {"form_id": "form-9", "meta_field_name": "campana_nombre",
         "target_type": "column",   "target_key": "campana"},
        {"form_id": "form-9", "meta_field_name": "proyecto_interes",
         "target_type": "property", "target_key": "proyecto_interes"},
        {"form_id": "form-9", "meta_field_name": "debug_field",
         "target_type": "ignore",   "target_key": None},
    ])
    stats = fm.apply_mappings(
        cur,
        lead_id=42,
        provider="meta",
        form_id="form-9",
        raw_field_data=[
            {"name": "Campana_Nombre",   "values": ["Campaña Q2"]},   # case-insensitive
            {"name": "proyecto_interes", "values": ["Lote A"]},
            {"name": "debug_field",      "values": ["verbose"]},
            {"name": "sin_mapear",       "values": ["x"]},
        ],
    )
    assert stats == {"applied": 2, "ignored": 1, "unmapped": 1, "errors": 0}


def test_apply_mappings_skips_empty_values():
    from app.services.integrations import field_mappings_repo as fm
    cur = _FakeCursor(rules=[
        {"form_id": "_any_", "meta_field_name": "email",
         "target_type": "column", "target_key": "email"},
    ])
    stats = fm.apply_mappings(
        cur,
        lead_id=1,
        provider="meta",
        form_id=None,
        raw_field_data=[
            {"name": "email", "values": [""]},        # valor vacío
            {"name": "email", "values": [None]},       # None
            {"name": "email", "values": []},           # lista vacía
            {"values": ["x"]},                         # sin name
        ],
    )
    # Ningún campo aplica; tampoco cuentan como unmapped porque el guard
    # descarta antes de consultar reglas.
    assert stats == {"applied": 0, "ignored": 0, "unmapped": 0, "errors": 0}


def test_apply_mappings_returns_zeros_on_no_lead_or_empty_payload():
    from app.services.integrations import field_mappings_repo as fm
    cur = _FakeCursor(rules=[])
    assert fm.apply_mappings(
        cur, lead_id=0, provider="meta", form_id="f", raw_field_data=[{"name": "x"}],
    ) == {"applied": 0, "ignored": 0, "unmapped": 0, "errors": 0}
    assert fm.apply_mappings(
        cur, lead_id=1, provider="meta", form_id="f", raw_field_data=[],
    ) == {"applied": 0, "ignored": 0, "unmapped": 0, "errors": 0}


def test_apply_mappings_counts_errors_when_writer_raises(monkeypatch):
    from app.services.integrations import field_mappings_repo as fm

    def _boom(*a, **kw):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(fm, "_upsert_lead_property", _boom)

    cur = _FakeCursor(rules=[
        {"form_id": "_any_", "meta_field_name": "proyecto_interes",
         "target_type": "property", "target_key": "proyecto_interes"},
    ])
    stats = fm.apply_mappings(
        cur, lead_id=1, provider="meta", form_id=None,
        raw_field_data=[{"name": "proyecto_interes", "values": ["Lote A"]}],
    )
    assert stats["errors"] == 1
    assert stats["applied"] == 0


def test_apply_mappings_specific_form_wins_over_wildcard():
    from app.services.integrations import field_mappings_repo as fm
    # Mismo meta_field con regla _any_ (property) y regla form-9 (column).
    # El _load_mappings_for_form debe preferir la específica.
    cur = _FakeCursor(rules=[
        {"form_id": "_any_",  "meta_field_name": "edad",
         "target_type": "property", "target_key": "edad"},
        {"form_id": "form-9", "meta_field_name": "edad",
         "target_type": "column",   "target_key": "observaciones"},
    ])
    stats = fm.apply_mappings(
        cur, lead_id=1, provider="meta", form_id="form-9",
        raw_field_data=[{"name": "edad", "values": ["35"]}],
    )
    # Específica gana → column → applied=1, no property calls.
    assert stats == {"applied": 1, "ignored": 0, "unmapped": 0, "errors": 0}
    # Confirmar que se ejecutó un UPDATE a crm.leads, no un INSERT a lead_properties.
    update_executed = any(
        "UPDATE crm.leads" in q for q, _ in cur.executed
    )
    assert update_executed


# ── ALLOWED_COLUMN_TARGETS es inmutable (frozenset) ─────────────────────────

def test_allowed_column_targets_is_frozenset():
    from app.services.integrations.field_mappings_repo import ALLOWED_COLUMN_TARGETS
    assert isinstance(ALLOWED_COLUMN_TARGETS, frozenset)
    # `id` o columnas de auth no deben estar incluidas.
    assert "id" not in ALLOWED_COLUMN_TARGETS
    assert "password_hash" not in ALLOWED_COLUMN_TARGETS
    # Columnas del lead sí.
    assert "email" in ALLOWED_COLUMN_TARGETS
    assert "observaciones" in ALLOWED_COLUMN_TARGETS


# ── acquire_backfill_lock ───────────────────────────────────────────────────

class _LockCursor:
    """Cursor que simula pg_try_advisory_xact_lock devolviendo un valor fijo."""

    def __init__(self, lock_result: bool, as_dict: bool = False):
        self._result = lock_result
        self._as_dict = as_dict
        self.last_sql: str = ""
        self.last_params: tuple | None = None

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params

    def fetchone(self):
        if self._as_dict:
            return {"pg_try_advisory_xact_lock": self._result}
        return (self._result,)


def test_acquire_backfill_lock_returns_true_when_granted():
    from app.services.integrations.field_mappings_repo import acquire_backfill_lock
    cur = _LockCursor(lock_result=True)
    assert acquire_backfill_lock(cur) is True
    assert "pg_try_advisory_xact_lock" in cur.last_sql


def test_acquire_backfill_lock_returns_false_when_busy():
    from app.services.integrations.field_mappings_repo import acquire_backfill_lock
    cur = _LockCursor(lock_result=False)
    assert acquire_backfill_lock(cur) is False


def test_acquire_backfill_lock_handles_realdict_cursor():
    from app.services.integrations.field_mappings_repo import acquire_backfill_lock
    cur = _LockCursor(lock_result=True, as_dict=True)
    assert acquire_backfill_lock(cur) is True


# ── run_backfill_job: orquestación del ciclo de estados ─────────────────────

def test_run_backfill_job_marks_rejected_when_lock_busy(monkeypatch):
    """Si otro worker tiene el lock, el job queda 'rejected' sin correr backfill."""
    from app.services.integrations import field_mappings_repo as fm

    updates: list[dict] = []

    # Simula get_db → context manager con cursor que niega el lock.
    class _Conn:
        def cursor(self, cursor_factory=None):
            return _LockCtx(lock_result=False)
        def commit(self): pass
        def rollback(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class _LockCtx:
        def __init__(self, lock_result):
            self._cur = _LockCursor(lock_result=lock_result)
        def __enter__(self): return self._cur
        def __exit__(self, *a): pass

    class _DBCtx:
        def __enter__(self): return _Conn()
        def __exit__(self, *a): pass

    monkeypatch.setattr(fm, "get_db", lambda: _DBCtx())

    def _fake_update(job_id, **kw):
        updates.append({"job_id": job_id, **kw})

    monkeypatch.setattr(fm, "update_backfill_job", _fake_update)
    # Si el lock falla, backfill_mappings no debe correr.
    monkeypatch.setattr(fm, "backfill_mappings", lambda **kw: pytest.fail(
        "backfill_mappings no debe correr cuando el lock está tomado"
    ))

    fm.run_backfill_job("job-xyz", {"provider": "meta"})

    statuses = [u.get("status") for u in updates if "status" in u]
    assert "running" in statuses     # marca running primero
    assert "rejected" in statuses    # y luego rejected
    # completed=True debe acompañar al rejected para cerrar el job.
    last = updates[-1]
    assert last["status"] == "rejected"
    assert last.get("completed") is True


def test_run_backfill_job_captures_exceptions_as_failed(monkeypatch):
    """Cualquier excepción dentro del job queda como status='failed'."""
    from app.services.integrations import field_mappings_repo as fm

    updates: list[dict] = []

    def _fake_update(job_id, **kw):
        updates.append({"job_id": job_id, **kw})

    # Simulamos que get_db explota — el job debe capturarlo.
    monkeypatch.setattr(fm, "update_backfill_job", _fake_update)
    monkeypatch.setattr(fm, "get_db", lambda: (_ for _ in ()).throw(
        RuntimeError("db unreachable")
    ))

    fm.run_backfill_job("job-boom", {"provider": "meta"})

    last = updates[-1]
    assert last["status"] == "failed"
    assert last.get("completed") is True
    assert "db unreachable" in (last.get("error") or "")


# ── delete_property_values: dry-run y borrado real ──────────────────────────

class _ValuesCursor:
    """Cursor falso para delete_property_values:
       - SELECT COUNT → devuelve `count_value`.
       - DELETE       → registra rowcount = `delete_rowcount`.
    """
    def __init__(self, count_value: int, delete_rowcount: Optional[int] = None):
        self._count = count_value
        self._delete_rowcount = (
            delete_rowcount if delete_rowcount is not None else count_value
        )
        self.executed: list[tuple[str, tuple]] = []
        self.rowcount = 0
        self._last_was_select = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params or ()))
        norm = sql.strip().upper()
        if norm.startswith("SELECT"):
            self._last_was_select = True
        elif norm.startswith("DELETE"):
            self._last_was_select = False
            self.rowcount = self._delete_rowcount

    def fetchone(self):
        if self._last_was_select:
            return (self._count,)
        return None


class _ValuesConn:
    def __init__(self, cur: _ValuesCursor):
        self._cur = cur
        self.commits = 0

    def cursor(self, cursor_factory=None):
        cur = self._cur
        class _Ctx:
            def __enter__(self_inner): return cur
            def __exit__(self_inner, *a): pass
        return _Ctx()

    def commit(self): self.commits += 1
    def rollback(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass


def _patch_get_db(monkeypatch, conn):
    from app.services.integrations import field_mappings_repo as fm
    class _DBCtx:
        def __enter__(self_inner): return conn
        def __exit__(self_inner, *a): pass
    monkeypatch.setattr(fm, "get_db", lambda: _DBCtx())


def test_delete_property_values_dry_run_counts_without_deleting(monkeypatch):
    from app.services.integrations import field_mappings_repo as fm
    cur = _ValuesCursor(count_value=42)
    _patch_get_db(monkeypatch, _ValuesConn(cur))

    result = fm.delete_property_values("dni", dry_run=True, triggered_by="admin@x")

    assert result == {"property_key": "dni", "count": 42, "dry_run": True, "deleted": 0}
    # Debe haber sólo SELECT, jamás DELETE en dry_run.
    sqls = [s for s, _ in cur.executed]
    assert any("SELECT" in s.upper() for s in sqls)
    assert not any("DELETE" in s.upper() for s in sqls)


def test_delete_property_values_real_delete_returns_deleted_count(monkeypatch):
    from app.services.integrations import field_mappings_repo as fm
    cur = _ValuesCursor(count_value=5, delete_rowcount=5)
    _patch_get_db(monkeypatch, _ValuesConn(cur))

    result = fm.delete_property_values("dni", dry_run=False, triggered_by="admin@x")

    assert result["count"] == 5
    assert result["deleted"] == 5
    assert result["dry_run"] is False
    sqls = [s for s, _ in cur.executed]
    assert any("DELETE" in s.upper() for s in sqls)


def test_delete_property_values_zero_count_skips_delete(monkeypatch):
    """Si no hay valores, no debe ejecutar el DELETE (idempotencia barata)."""
    from app.services.integrations import field_mappings_repo as fm
    cur = _ValuesCursor(count_value=0)
    _patch_get_db(monkeypatch, _ValuesConn(cur))

    result = fm.delete_property_values("dni", dry_run=False)

    assert result == {"property_key": "dni", "count": 0, "dry_run": False, "deleted": 0}
    sqls = [s for s, _ in cur.executed]
    assert not any("DELETE" in s.upper() for s in sqls)


def test_delete_property_values_rejects_empty_key():
    from app.services.integrations.field_mappings_repo import (
        delete_property_values,
        FieldMappingError,
    )
    with pytest.raises(FieldMappingError) as exc:
        delete_property_values("   ", dry_run=True)
    assert exc.value.status_code == 400


def test_delete_property_values_strips_property_key(monkeypatch):
    """Whitespace alrededor del key no debe pasar al WHERE — siempre se trim."""
    from app.services.integrations import field_mappings_repo as fm
    cur = _ValuesCursor(count_value=1)
    _patch_get_db(monkeypatch, _ValuesConn(cur))

    result = fm.delete_property_values("  dni  ", dry_run=True)

    assert result["property_key"] == "dni"
    # El parámetro pasado al SELECT también debe ir limpio.
    select_call = next(p for s, p in cur.executed if "SELECT" in s.upper())
    assert select_call == ("dni",)

"""
Tests de db_migrator.py — el auto-aplicador de migraciones al startup.

Estos tests son CRITICOS porque un bug aqui significa:
  - Migraciones se silencian -> features rotas en prod
  - Migraciones se duplican -> errores SQL ruidosos
  - Migraciones aplican en mal orden -> data corrupt

Bug historico V070.60 documentado en el codigo: regex que colapsaba
V068, V068_3, V068_4 en "V068" hizo que migraciones se silenciaran
4 horas hasta destrabar. Esta suite previene regresiones de eso.
"""
from pathlib import Path

import pytest

from app.db_migrator import (
    _VERSION_RE,
    _strip_tx_markers,
    _list_migrations,
)


# ── _VERSION_RE: regex de version ────────────────────────────────────────

@pytest.mark.unit
def test_version_re_matches_simple_VNN_filename():
    """V040_create_users.sql -> version 'V040'."""
    m = _VERSION_RE.match("V040_create_users.sql")
    assert m is not None
    assert m.group(1) == "V040"


@pytest.mark.unit
def test_version_re_matches_VNN_with_subversion():
    """V068_3_clean_same_day.sql -> 'V068_3'.

    Regresion del bug V070.60: antes el regex `(V\\d+)_.+` capturaba
    solo 'V068' y las subversiones colisionaban -> tracker silenciaba."""
    m = _VERSION_RE.match("V068_3_clean_same_day.sql")
    assert m is not None
    assert m.group(1) == "V068_3"


@pytest.mark.unit
def test_version_re_matches_VNN_with_multiple_subversions():
    """V068_4_external_created_at.sql -> 'V068_4'."""
    m = _VERSION_RE.match("V068_4_external_created_at.sql")
    assert m is not None
    assert m.group(1) == "V068_4"


@pytest.mark.unit
def test_version_re_matches_VNN_with_letter_after_underscore():
    """V068_lead_recontactos.sql (sin subnum) -> 'V068'."""
    m = _VERSION_RE.match("V068_lead_recontactos_daily_dedup.sql")
    assert m is not None
    assert m.group(1) == "V068"


@pytest.mark.unit
def test_version_re_ignores_legacy_001_format():
    """Archivos legacy estilo '001_create_users.sql' NO matchean
    (deben quedar como historicos sin tocar)."""
    assert _VERSION_RE.match("001_create_users.sql") is None


@pytest.mark.unit
def test_version_re_ignores_non_sql_files():
    """README.md, MIGRATIONS.md, etc no deben matchear."""
    assert _VERSION_RE.match("README.md") is None
    assert _VERSION_RE.match("MIGRATIONS.md") is None


@pytest.mark.unit
def test_version_re_is_case_insensitive():
    """v040_xxx.sql o V040_xxx.sql ambos matchean."""
    assert _VERSION_RE.match("v040_test.sql") is not None
    assert _VERSION_RE.match("V040_test.sql") is not None


# ── _strip_tx_markers ────────────────────────────────────────────────────

@pytest.mark.unit
def test_strip_tx_markers_removes_begin_commit_lines():
    """BEGIN; / COMMIT; aislados se quitan."""
    sql = """
BEGIN;
CREATE TABLE foo (id INT);
COMMIT;
"""
    result = _strip_tx_markers(sql)
    assert "BEGIN" not in result.upper()
    assert "COMMIT" not in result.upper()
    assert "CREATE TABLE foo" in result


@pytest.mark.unit
def test_strip_tx_markers_keeps_create_statements():
    sql = "CREATE TABLE x (id INT);\nINSERT INTO x VALUES (1);"
    result = _strip_tx_markers(sql)
    assert "CREATE TABLE" in result
    assert "INSERT INTO" in result


@pytest.mark.unit
def test_strip_tx_markers_keeps_inline_BEGIN_in_function_body():
    """BEGIN dentro de una funcion PL/pgSQL (sin ser linea aislada)
    NO debe ser strippeado."""
    sql = """
CREATE OR REPLACE FUNCTION foo() RETURNS void AS $$
BEGIN
    RETURN;
END;
$$ LANGUAGE plpgsql;
"""
    result = _strip_tx_markers(sql)
    # El BEGIN dentro de la funcion es lo que queda. Solo se strippearia
    # si fuera "^\\s*BEGIN;?\\s*$" — el de adentro no termina en ;.
    assert "BEGIN" in result
    assert "CREATE OR REPLACE FUNCTION" in result


@pytest.mark.unit
def test_strip_tx_markers_handles_rollback():
    sql = "ROLLBACK;\nCREATE TABLE x (id INT);"
    result = _strip_tx_markers(sql)
    assert "ROLLBACK" not in result.upper()


@pytest.mark.unit
def test_strip_tx_markers_empty_string_returns_empty():
    assert _strip_tx_markers("") == ""


# ── _list_migrations: deteccion de colisiones (CRITICO) ──────────────────

@pytest.mark.unit
def test_list_migrations_raises_on_version_collision(tmp_path, monkeypatch):
    """Bug V070.64: si dos archivos producen la misma version
    (ej: V071_legacy.sql y V071_new.sql), el segundo se silenciaba en
    deploy. Ahora _list_migrations lanza RuntimeError ANTES de aplicar."""
    # Arrange — crear 2 archivos que colisionan en V071
    (tmp_path / "V071_legacy.sql").write_text("SELECT 1;")
    (tmp_path / "V071_new_feature.sql").write_text("SELECT 2;")
    monkeypatch.setattr("app.db_migrator._migrations_dir", lambda: tmp_path)

    # Act + Assert
    with pytest.raises(RuntimeError) as exc:
        _list_migrations()

    assert "COLISION" in str(exc.value)
    assert "V071" in str(exc.value)


@pytest.mark.unit
def test_list_migrations_accepts_subversions_without_collision(
    tmp_path, monkeypatch,
):
    """V068, V068_3, V068_4 son versiones DISTINTAS (no colisionan)."""
    (tmp_path / "V068_base.sql").write_text("SELECT 1;")
    (tmp_path / "V068_3_subfix.sql").write_text("SELECT 2;")
    (tmp_path / "V068_4_another.sql").write_text("SELECT 3;")
    monkeypatch.setattr("app.db_migrator._migrations_dir", lambda: tmp_path)

    # No debe lanzar
    result = _list_migrations()

    versions = sorted([v for v, _ in result])
    assert versions == ["V068", "V068_3", "V068_4"]


@pytest.mark.unit
def test_list_migrations_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    """Si no existe el directorio migrations/, devuelve lista vacia (no raise)."""
    inexistente = tmp_path / "no-existe"
    monkeypatch.setattr("app.db_migrator._migrations_dir", lambda: inexistente)

    assert _list_migrations() == []


@pytest.mark.unit
def test_list_migrations_orders_alphabetically(tmp_path, monkeypatch):
    """V041 antes que V042 antes que V100 (alfabetico)."""
    (tmp_path / "V042_b.sql").write_text("SELECT 1;")
    (tmp_path / "V100_c.sql").write_text("SELECT 1;")
    (tmp_path / "V041_a.sql").write_text("SELECT 1;")
    monkeypatch.setattr("app.db_migrator._migrations_dir", lambda: tmp_path)

    result = _list_migrations()
    versions = [v for v, _ in result]
    assert versions == ["V041", "V042", "V100"]


@pytest.mark.unit
def test_list_migrations_ignores_non_matching_files(tmp_path, monkeypatch):
    """README.md, .gitkeep, 001_legacy.sql no se cuentan."""
    (tmp_path / "V040_real.sql").write_text("SELECT 1;")
    (tmp_path / "README.md").write_text("docs")
    (tmp_path / "001_legacy.sql").write_text("legacy")
    (tmp_path / ".gitkeep").write_text("")
    monkeypatch.setattr("app.db_migrator._migrations_dir", lambda: tmp_path)

    result = _list_migrations()
    assert len(result) == 1
    assert result[0][0] == "V040"

"""
V094.2 — tests del auto-sync del catalogo crm.campanas en cada arranque.

Cubre:
- ensure_campanas_schema corre el INSERT incluso si la tabla ya existia
  (bug original V028: solo se sembraba al crear la tabla).
- Idempotencia: ON CONFLICT DO NOTHING — multiples ejecuciones consecutivas
  no rompen ni duplican.
- Tolerancia a errores: si la sync falla (DB caida, permisos), no
  bloquea el resto del bootstrap (solo log warning).
"""
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_sync_corre_aunque_tabla_ya_exista():
    """V094.2 — el sync debe correr en cada arranque, no solo al crear
    la tabla. Antes del fix, esto NO pasaba (bug en Palma prod)."""
    with patch("app.bootstrap._campanas_schema_exists", return_value=True), \
         patch("app.bootstrap.get_db") as mock_get_db:
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db.return_value.__enter__.return_value = mock_conn

        from app.bootstrap import ensure_campanas_schema
        ensure_campanas_schema()

        # Verifica que cur.execute fue llamado con un INSERT que tiene
        # ON CONFLICT DO NOTHING (idempotencia)
        assert mock_cursor.execute.called
        sql_called = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO crm.campanas" in sql_called
        assert "ON CONFLICT (nombre) DO NOTHING" in sql_called
        assert "SELECT DISTINCT TRIM(campana)" in sql_called
        # Y commit fue llamado (no quedo en transaccion abierta)
        assert mock_conn.commit.called


@pytest.mark.unit
def test_sync_no_intenta_actualizar_activo():
    """V094.2 — defensa: el INSERT usa ON CONFLICT DO NOTHING (no UPDATE).
    Si el admin desactivo manualmente una campaña (activo=FALSE), el
    sync NO debe reactivarla — respeta la decision humana."""
    with patch("app.bootstrap._campanas_schema_exists", return_value=True), \
         patch("app.bootstrap.get_db") as mock_get_db:
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db.return_value.__enter__.return_value = mock_conn

        from app.bootstrap import ensure_campanas_schema
        ensure_campanas_schema()

        sql_called = mock_cursor.execute.call_args[0][0]
        # NO debe haber "DO UPDATE SET activo" — eso reactivaria campanas
        # desactivadas a mano por el admin.
        assert "DO UPDATE SET activo" not in sql_called
        assert "DO NOTHING" in sql_called


@pytest.mark.unit
def test_sync_tolerante_a_error_de_db():
    """Si la sync explota (DB caida, permission denied), debe loggear
    warning y NO romper el resto del bootstrap. Fail-safe."""
    with patch("app.bootstrap._campanas_schema_exists", return_value=True), \
         patch("app.bootstrap.get_db") as mock_get_db, \
         patch("app.bootstrap.logger") as mock_logger:
        mock_get_db.side_effect = Exception("connection refused")

        from app.bootstrap import ensure_campanas_schema
        # No debe levantar exception
        ensure_campanas_schema()

        # Debe haber logueado un warning sin propagar el error
        assert mock_logger.warning.called


@pytest.mark.unit
def test_ddl_inicial_corre_solo_si_tabla_no_existe():
    """V094.2 backward compat — el DDL completo (CREATE TABLE) solo corre
    si la tabla no existia. El sync corre siempre (cada deploy)."""
    with patch("app.bootstrap._campanas_schema_exists", return_value=False), \
         patch("app.bootstrap.get_db") as mock_get_db:
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 51
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_db.return_value.__enter__.return_value = mock_conn

        from app.bootstrap import ensure_campanas_schema
        ensure_campanas_schema()

        # Debe haber 2 ejecuciones: DDL + sync
        assert mock_cursor.execute.call_count == 2
        calls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        # Primera llamada: DDL (CREATE TABLE)
        assert "CREATE TABLE" in calls[0]
        # Segunda llamada: sync (INSERT … ON CONFLICT DO NOTHING)
        assert "INSERT INTO crm.campanas" in calls[1]
        assert "ON CONFLICT" in calls[1]

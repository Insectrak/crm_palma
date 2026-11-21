"""V096.8 — Tests de regresion para GET /api/agenda/citas-proximas.

Bug ID: visto en vivo en prod 2026-06-24 sobre contacto 2822.

Antes del fix V096.8 el endpoint devolvia citas cuyo asesor no tenia
telefono (NULL o cadena vacia). El workflow n8n las procesaba pero la
rama 'Asesor tiene tel?' las mandaba a 'Marcar sin tel (skip)', que
insertaba un row en crm.recordatorios_enviados con
enviado_a='sin_telefono'.

Resultado: la cita quedaba 'marcada como enviada' sin que se hubiera
notificado a nadie. Si despues se asignaba un asesor con telefono, el
recordatorio nunca salia porque el flag ya existia (filtro
'NOT EXISTS recordatorios_enviados').

Fix V096.8: el SQL filtra en origen — solo devuelve citas cuyo asesor
tiene telefono valido. Si nadie tiene tel, no se devuelve, no se
contamina, el flow natural retoma cuando aparece el tel.
"""
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.regression
def test_citas_proximas_excluye_asesor_sin_telefono():
    """El SQL del endpoint debe excluir citas cuyo asesor tenga
    telefono NULL o cadena vacia."""
    from app.routers.agenda import citas_proximas

    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.agenda.get_db", return_value=db_cm):
        citas_proximas()

    # El query debe haberse ejecutado.
    assert cur.execute.call_count >= 1
    sql = cur.execute.call_args_list[0][0][0]

    # Filtros V096.8 presentes en el SQL.
    assert "u.telefono IS NOT NULL" in sql, (
        "El query no filtra asesores sin telefono — bug del 24/06"
    )
    assert "TRIM(u.telefono) <> ''" in sql, (
        "El query no filtra asesores con telefono vacio (string en blanco)"
    )

    # INNER JOIN a auth.users (no LEFT) — citas sin asesor tampoco salen.
    assert "JOIN auth.users u ON u.id = c.asesor_id" in sql
    assert "LEFT JOIN auth.users" not in sql, (
        "auth.users debe ser INNER JOIN, no LEFT — citas sin asesor no se "
        "pueden notificar"
    )


def test_citas_proximas_devuelve_estructura_json_correcta():
    """Backwards-compat: el endpoint sigue devolviendo {total, citas}."""
    from app.routers.agenda import citas_proximas

    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.agenda.get_db", return_value=db_cm):
        result = citas_proximas()

    assert result == {"total": 0, "citas": []}


def test_citas_proximas_mantiene_filtros_originales():
    """Verifica que los filtros existentes (ventana de 35 min y exclusion
    de citas ya con recordatorio enviado) siguen aplicados."""
    from app.routers.agenda import citas_proximas

    cur = MagicMock()
    cur.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    with patch("app.routers.agenda.get_db", return_value=db_cm):
        citas_proximas()

    sql = cur.execute.call_args_list[0][0][0]
    assert "c.fecha_cita > NOW()" in sql
    assert "INTERVAL '35 minutes'" in sql
    assert "crm.recordatorios_enviados" in sql
    assert "l.activo = TRUE" in sql

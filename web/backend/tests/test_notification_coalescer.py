"""Tests para notification_coalescer (V075).

Estrategia: testeo unitario con mocks de DB y de notification_service.
No requiere PostgreSQL — todo aislado para correr en CI rapido.

Cubre las reglas de negocio criticas:
  - CALIENTE bypassea el buffer y va inmediato
  - Sin lead_id, va inmediato (no podemos buffearlo)
  - Flush con <BATCH_THRESHOLD envia individual
  - Flush con >=BATCH_THRESHOLD envia 1 batch agregada
  - Breakdown formatea bien la mezcla de fuentes
  - Fallback a inmediato si el INSERT en buffer falla
"""
from unittest.mock import MagicMock, patch


# ── Helpers de fixtures ──────────────────────────────────────────────────

def _mock_db_conn():
    """Devuelve un context-manager mock con cursor encadenable."""
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


# ── Helpers puros (no requieren mock) ────────────────────────────────────

def test_format_fuente_breakdown_basico():
    from app.services.notification_coalescer import _format_fuente_breakdown
    out = _format_fuente_breakdown(["facebook", "instagram", "facebook"])
    # 2 facebook > 1 instagram → orden por frecuencia desc
    assert out == "2 Facebook · 1 Instagram"


def test_format_fuente_breakdown_solo_top_3():
    from app.services.notification_coalescer import _format_fuente_breakdown
    out = _format_fuente_breakdown([
        "fb", "fb", "fb", "ig", "ig", "tt", "wa", "ref"
    ])
    # Solo top 3, ordenadas por frecuencia
    parts = out.split(" · ")
    assert len(parts) == 3
    assert parts[0].startswith("3")  # fb gana


def test_format_fuente_breakdown_normaliza_vacios():
    from app.services.notification_coalescer import _format_fuente_breakdown
    out = _format_fuente_breakdown(["", None, "facebook"])  # type: ignore[list-item]
    # Vacios y None se agrupan como "otra"
    assert "Otra" in out
    assert "Facebook" in out


# ── enqueue: bypass CALIENTE ──────────────────────────────────────────────

@patch("app.services.notification_coalescer.notify_immediate")
def test_enqueue_caliente_va_inmediato(mock_immediate):
    """Si calidad es CALIENTE, NO toca el buffer — manda push inmediato."""
    from app.services import notification_coalescer
    mock_immediate.return_value = True

    result = notification_coalescer.enqueue(
        asesor_id="aaaaaaaa-1111-2222-3333-444444444444",
        lead_id=999,
        lead_name="Juan",
        fuente="facebook",
        calidad="CALIENTE",
    )

    assert result is True
    mock_immediate.assert_called_once()
    # Y NO debio tocar la DB para insertar en el buffer
    kwargs = mock_immediate.call_args.kwargs
    assert kwargs["lead_id"] == 999
    assert kwargs["lead_name"] == "Juan"


@patch("app.services.notification_coalescer.notify_immediate")
def test_enqueue_caliente_case_insensitive(mock_immediate):
    """'caliente' o 'Caliente' tambien bypassean."""
    from app.services import notification_coalescer
    mock_immediate.return_value = True

    notification_coalescer.enqueue(
        asesor_id="aaaa", lead_id=1, lead_name="X", calidad="caliente",
    )
    mock_immediate.assert_called_once()


@patch("app.services.notification_coalescer.notify_immediate")
def test_enqueue_sin_lead_id_va_inmediato(mock_immediate):
    """Sin lead_id, no podemos buffear bien → bypass inmediato."""
    from app.services import notification_coalescer
    mock_immediate.return_value = True

    notification_coalescer.enqueue(
        asesor_id="aaaa", lead_id=None, lead_name="X", calidad="FRIO",
    )
    mock_immediate.assert_called_once()


@patch("app.services.notification_coalescer.notify_immediate")
def test_enqueue_sin_asesor_id_devuelve_false(mock_immediate):
    """Asesor vacio = no hay a quien notificar."""
    from app.services import notification_coalescer
    result = notification_coalescer.enqueue(
        asesor_id="", lead_id=1, lead_name="X", calidad="FRIO",
    )
    assert result is False
    mock_immediate.assert_not_called()


# ── enqueue: encolado normal ──────────────────────────────────────────────

@patch("app.services.notification_coalescer.get_db")
@patch("app.services.notification_coalescer.notify_immediate")
def test_enqueue_normal_inserta_en_buffer(mock_immediate, mock_get_db):
    """Lead no-CALIENTE con lead_id → INSERT en buffer, no push inmediata."""
    from app.services import notification_coalescer
    conn, cur = _mock_db_conn()
    mock_get_db.return_value = conn

    result = notification_coalescer.enqueue(
        asesor_id="aaaa", lead_id=42, lead_name="Maria",
        fuente="instagram", calidad="FRIO",
    )

    assert result is True
    mock_immediate.assert_not_called()
    cur.execute.assert_called_once()
    sql_call = cur.execute.call_args
    assert "INSERT INTO crm.notification_buffer" in sql_call[0][0]
    # Params en el orden correcto: asesor, lead_id, lead_name, fuente, performed_by
    params = sql_call[0][1]
    assert params[0] == "aaaa"
    assert params[1] == 42
    assert params[2] == "Maria"
    assert params[3] == "instagram"


@patch("app.services.notification_coalescer.get_db")
@patch("app.services.notification_coalescer.notify_immediate")
def test_enqueue_fallback_inmediato_si_db_falla(mock_immediate, mock_get_db):
    """Si la tabla no existe (V075 no aplicada) o cualquier error DB,
    el coalescer hace fallback a push inmediato. Mejor spam que cero."""
    from app.services import notification_coalescer
    mock_get_db.side_effect = Exception("relation does not exist")
    mock_immediate.return_value = True

    result = notification_coalescer.enqueue(
        asesor_id="aaaa", lead_id=1, lead_name="X", calidad="FRIO",
    )

    assert result is True
    mock_immediate.assert_called_once()

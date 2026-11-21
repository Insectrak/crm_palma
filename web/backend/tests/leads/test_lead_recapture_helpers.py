"""
Tests de las funciones helpers del modulo lead_recapture.py.

Cubre las funciones puras + las que tocan DB con mock:
  - _decidir_estrategia: principio "rapport preservado" (mantener asesor).
  - _resolve_fuente_id: lookup case-insensitive.
  - _safe_uuid: validacion de longitud minima.
  - _is_duplicate_recontacto_event: idempotency dual (fext + dia comercial).
  - _send_push_recontacto: best-effort, no propaga errores.
  - _fill_empty_fields: solo rellena vacios, nunca sobrescribe.

handle_recontacto (la funcion principal) es muy compleja y queda para
integration tests. Estos helpers son la base que la sostiene.
"""
from unittest.mock import MagicMock, patch

import pytest


# ── _safe_uuid ────────────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_safe_uuid_with_none_returns_none():
    from app.services.lead_recapture import _safe_uuid
    assert _safe_uuid(None) is None


@pytest.mark.leads
@pytest.mark.unit
def test_safe_uuid_with_empty_string_returns_none():
    from app.services.lead_recapture import _safe_uuid
    assert _safe_uuid("") is None
    assert _safe_uuid("  ") is None


@pytest.mark.leads
@pytest.mark.unit
def test_safe_uuid_with_short_string_returns_none():
    """Strings <32 chars NO son UUID validos."""
    from app.services.lead_recapture import _safe_uuid
    assert _safe_uuid("abc") is None
    assert _safe_uuid("00000000-0000-0000-0000") is None  # <32


@pytest.mark.leads
@pytest.mark.unit
def test_safe_uuid_with_valid_uuid_returns_it_trimmed():
    """UUID >=32 chars devuelve el string limpio."""
    from app.services.lead_recapture import _safe_uuid
    uuid_str = "00000000-0000-0000-0000-000000000001"
    assert _safe_uuid(uuid_str) == uuid_str
    assert _safe_uuid(f"  {uuid_str}  ") == uuid_str  # trim


# ── _decidir_estrategia ───────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_decidir_estrategia_sin_asesor_devuelve_routing_normal():
    """Lead sin asesor original -> routing normal."""
    from app.services.lead_recapture import _decidir_estrategia
    cur = MagicMock()
    estrategia, asesor, inactivo, razon = _decidir_estrategia(cur, None, "sup-uuid")

    assert estrategia == "sin_asesor_original"
    assert asesor is None
    assert inactivo is False
    cur.execute.assert_not_called()  # no consulta DB si no hay asesor


@pytest.mark.leads
@pytest.mark.unit
def test_decidir_estrategia_asesor_activo_se_mantiene():
    """Asesor activo -> rapport preservado, se mantiene."""
    from app.services.lead_recapture import _decidir_estrategia
    cur = MagicMock()
    cur.fetchone.return_value = {"id": "asesor-uuid", "is_active": True}

    estrategia, asesor, inactivo, razon = _decidir_estrategia(
        cur, "asesor-uuid", "sup-uuid",
    )

    assert estrategia == "mantener_asesor"
    assert asesor == "asesor-uuid"
    assert inactivo is False
    assert "rapport" in razon.lower()


@pytest.mark.leads
@pytest.mark.unit
def test_decidir_estrategia_asesor_inactivo_libera_lead():
    """Asesor con is_active=False -> liberar para re-routing."""
    from app.services.lead_recapture import _decidir_estrategia
    cur = MagicMock()
    cur.fetchone.return_value = {"id": "asesor-uuid", "is_active": False}

    estrategia, asesor, inactivo, razon = _decidir_estrategia(
        cur, "asesor-uuid", "sup-uuid",
    )

    assert estrategia == "liberar_inactivo"
    assert asesor is None
    assert inactivo is True
    assert "inactivo" in razon.lower()


@pytest.mark.leads
@pytest.mark.unit
def test_decidir_estrategia_asesor_no_existe_libera_lead():
    """Asesor borrado de la DB -> liberar."""
    from app.services.lead_recapture import _decidir_estrategia
    cur = MagicMock()
    cur.fetchone.return_value = None  # asesor no encontrado

    estrategia, asesor, inactivo, razon = _decidir_estrategia(
        cur, "asesor-borrado", "sup-uuid",
    )

    assert estrategia == "liberar_inactivo"
    assert asesor is None
    assert inactivo is True


# ── _resolve_fuente_id ────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_resolve_fuente_id_with_empty_returns_none():
    from app.services.lead_recapture import _resolve_fuente_id
    cur = MagicMock()
    assert _resolve_fuente_id(cur, None) is None
    assert _resolve_fuente_id(cur, "") is None


@pytest.mark.leads
@pytest.mark.unit
def test_resolve_fuente_id_with_match_returns_id():
    """SELECT case-insensitive devuelve el id."""
    from app.services.lead_recapture import _resolve_fuente_id
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 42}

    result = _resolve_fuente_id(cur, "Facebook")

    assert result == 42


@pytest.mark.leads
@pytest.mark.unit
def test_resolve_fuente_id_with_no_match_returns_none():
    from app.services.lead_recapture import _resolve_fuente_id
    cur = MagicMock()
    cur.fetchone.return_value = None

    assert _resolve_fuente_id(cur, "inexistente") is None


@pytest.mark.leads
@pytest.mark.unit
def test_resolve_fuente_id_swallows_db_exception_returns_none():
    """Si la DB falla, return None (best-effort, no rompe ingest)."""
    from app.services.lead_recapture import _resolve_fuente_id
    cur = MagicMock()
    cur.execute.side_effect = Exception("table missing")

    assert _resolve_fuente_id(cur, "facebook") is None


# ── _is_duplicate_recontacto_event ────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_is_duplicate_recontacto_with_existing_fext_returns_true():
    """Si la combinacion (lead_id, fuente_externa_id) ya existe -> es duplicado."""
    from app.services.lead_recapture import _is_duplicate_recontacto_event
    cur = MagicMock()
    cur.fetchone.return_value = (1,)  # encontrado

    result = _is_duplicate_recontacto_event(
        cur, lead_id=42, fext="POSTMAN-001", fuente_id=1,
    )

    assert result is True


@pytest.mark.leads
@pytest.mark.unit
def test_is_duplicate_recontacto_swallows_exception_returns_false():
    """Best-effort: si falla el check, devuelve False (deja pasar el insert)."""
    from app.services.lead_recapture import _is_duplicate_recontacto_event
    cur = MagicMock()
    cur.execute.side_effect = Exception("DB down")

    result = _is_duplicate_recontacto_event(
        cur, lead_id=42, fext=None, fuente_id=1,
    )

    assert result is False


# ── _fill_empty_fields ────────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_fill_empty_fields_no_op_when_existing_has_data():
    """Si los campos del lead existente NO estan vacios, no se ejecuta UPDATE."""
    from app.services.lead_recapture import _fill_empty_fields
    cur = MagicMock()
    existing = {
        "email": "ya-tiene@email.com",
        "nombres": "Ya",
        "apellidos": "Tiene",
    }

    _fill_empty_fields(
        cur, 42, existing,
        nombres="Nuevo", apellidos="Nombre", email="nuevo@email.com",
    )

    cur.execute.assert_not_called()


@pytest.mark.leads
@pytest.mark.unit
def test_fill_empty_fields_only_fills_email_when_empty():
    """Email vacio en existing pero rellenado en input -> UPDATE solo email."""
    from app.services.lead_recapture import _fill_empty_fields
    cur = MagicMock()
    existing = {
        "email": "",          # vacio
        "nombres": "Ya tiene",
        "apellidos": "Apellido",
    }

    _fill_empty_fields(
        cur, 42, existing,
        nombres="X", apellidos="Y", email="nuevo@email.com",
    )

    cur.execute.assert_called_once()
    sql = cur.execute.call_args[0][0]
    assert "email = %s" in sql
    assert "nombres" not in sql.split("WHERE")[0]  # no rellena nombres


# ── _send_push_recontacto ─────────────────────────────────────────────────

@pytest.mark.leads
@pytest.mark.unit
def test_send_push_recontacto_returns_true_on_success():
    from app.services.lead_recapture import _send_push_recontacto
    cur = MagicMock()
    with patch("app.services.notification_service.notify_lead_recontacto") as mock_notify:
        mock_notify.return_value = True
        result = _send_push_recontacto(
            cur, lead_id=42, asesor_id="uuid",
            nombres="Ana", apellidos="Test",
            fuente="facebook", campana="Promo X",
        )

    assert result is True
    mock_notify.assert_called_once()


@pytest.mark.leads
@pytest.mark.unit
def test_send_push_recontacto_returns_false_on_exception():
    """Best-effort: si notify_lead_recontacto levanta, devuelve False."""
    from app.services.lead_recapture import _send_push_recontacto
    cur = MagicMock()
    with patch("app.services.notification_service.notify_lead_recontacto") as mock_notify:
        mock_notify.side_effect = Exception("FCM down")
        result = _send_push_recontacto(
            cur, lead_id=42, asesor_id="uuid",
            nombres="Ana", apellidos="Test",
            fuente="facebook", campana="Promo X",
        )

    assert result is False


# ── V084: atribucion Meta-level del recontacto ────────────────────────────

@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_handle_recontacto_persiste_anuncio_conjunto_form_id():
    """Bug ID: V084 — el proveedor reporto que cuando un lead viejo entra por
    una nueva campaña de Meta, los campos anuncio/conjunto/fuente_form_id se
    descartaban silenciosamente. Este test asegura que ahora se pasan al
    INSERT de crm.lead_recontactos."""
    from app.services.lead_recapture import handle_recontacto

    cur = MagicMock()
    # Orden real de fetchone() en handle_recontacto:
    #   1. _decidir_estrategia -> SELECT auth.users
    #   2. _resolve_fuente_id  -> SELECT crm.fuentes
    #   3. _is_duplicate (fext)
    #   4. _is_duplicate (dia comercial)
    #   5. SELECT existing recontacto por (lead_id, fext)
    #   6. INSERT ... RETURNING id
    cur.fetchone.side_effect = [
        {"id": "asesor-uuid", "is_active": True},   # _decidir_estrategia
        {"id": 1},                                    # _resolve_fuente_id
        None,                                         # _is_duplicate (fext)
        None,                                         # _is_duplicate (dia)
        None,                                         # SELECT existing recontacto
        {"id": 99},                                   # INSERT RETURNING
    ]

    payload = MagicMock()
    payload.fuente = "facebook"
    payload.anuncio = "Ad_Retargeting_X"
    payload.conjunto = "AdSet_Lookalike_30d"
    payload.fuente_form_id = "form_12345"
    payload.external_created_at = None
    payload.api_client_id = None

    existing = {
        "id": 42,
        "asesor_id": "asesor-uuid",
        "supervisor_id": "sup-uuid",
        "estado_nombre": "Contactado",
        "created_at": None,
    }

    with patch("app.services.notification_service.notify_lead_recontacto"):
        handle_recontacto(
            cur,
            existing=existing,
            payload=payload,
            telefono="+51987654321",
            email=None,
            nombres="Juan",
            apellidos="Perez",
            campana="Campaign_Meta_2026",
            fext="fb_lead_001",
        )

    # Buscamos el INSERT INTO crm.lead_recontactos entre los execute() calls
    # y verificamos que los 3 valores nuevos esten en el tuple de params.
    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO crm.lead_recontactos" in c[0][0]
    ]
    assert insert_calls, "No se encontro el INSERT a crm.lead_recontactos"

    primary = insert_calls[0]
    sql = primary[0][0]
    params = primary[0][1]

    # Schema V084: columnas en el INSERT.
    assert "anuncio" in sql
    assert "conjunto" in sql
    assert "fuente_form_id" in sql

    # Y los valores del payload tienen que llegar al INSERT.
    assert "Ad_Retargeting_X" in params
    assert "AdSet_Lookalike_30d" in params
    assert "form_12345" in params


@pytest.mark.leads
@pytest.mark.regression
@pytest.mark.unit
def test_handle_recontacto_normaliza_campos_meta_vacios_a_none():
    """Strings vacios/whitespace del proveedor se normalizan a None — no
    queremos columnas TEXT con '   ' que rompan reportes."""
    from app.services.lead_recapture import handle_recontacto

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": "asesor-uuid", "is_active": True},   # _decidir_estrategia
        {"id": 1},                                    # _resolve_fuente_id
        None,                                         # _is_duplicate (fext)
        None,                                         # _is_duplicate (dia)
        None,                                         # SELECT existing recontacto
        {"id": 99},                                   # INSERT RETURNING
    ]

    payload = MagicMock()
    payload.fuente = "facebook"
    payload.anuncio = "   "                # whitespace
    payload.conjunto = ""                   # vacio
    payload.fuente_form_id = None           # explicito
    payload.external_created_at = None
    payload.api_client_id = None

    with patch("app.services.notification_service.notify_lead_recontacto"):
        handle_recontacto(
            cur,
            existing={
                "id": 42, "asesor_id": "asesor-uuid", "supervisor_id": "sup-uuid",
                "estado_nombre": "Contactado", "created_at": None,
            },
            payload=payload,
            telefono="+51987654321", email=None,
            nombres="Juan", apellidos="Perez",
            campana=None, fext="fb_lead_002",
        )

    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO crm.lead_recontactos" in c[0][0]
    ]
    assert insert_calls
    params = insert_calls[0][0][1]

    # No debe llegar '   ' ni '' — todos los meta fields vacios -> None.
    assert "   " not in params
    assert "" not in params

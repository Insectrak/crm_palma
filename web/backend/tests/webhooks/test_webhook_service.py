"""
Tests del modulo app/services/webhook_service.py.

Cubre las dos piezas mas criticas:
  - _sign_payload: HMAC-SHA256 que el proveedor verifica para garantizar
    integridad y autenticidad del webhook.
  - enqueue_event: lo que se llama desde el codigo de negocio para
    encolar un webhook. Debe ser SILENCIOSO ante errores (regla: webhook
    nunca debe romper el flujo de negocio).

Las funciones del worker (process_pending_queue, _process_one_delivery)
quedan para otra sesion (tests de integration con DB real).
"""
from unittest.mock import MagicMock

import pytest


# ── _sign_payload ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_sign_payload_is_deterministic():
    """Mismo secret + mismo payload -> mismo hash, siempre."""
    from app.services.webhook_service import _sign_payload
    sig1 = _sign_payload("secret-x", b'{"foo":"bar"}')
    sig2 = _sign_payload("secret-x", b'{"foo":"bar"}')
    assert sig1 == sig2


@pytest.mark.unit
def test_sign_payload_different_secrets_produce_different_hashes():
    """Cambio chico en el secret cambia totalmente el hash."""
    from app.services.webhook_service import _sign_payload
    sig1 = _sign_payload("secret-a", b'{"foo":"bar"}')
    sig2 = _sign_payload("secret-b", b'{"foo":"bar"}')
    assert sig1 != sig2


@pytest.mark.unit
def test_sign_payload_different_payloads_produce_different_hashes():
    """Mismo secret pero payload distinto -> hash distinto. Integridad."""
    from app.services.webhook_service import _sign_payload
    sig1 = _sign_payload("secret", b'{"a":1}')
    sig2 = _sign_payload("secret", b'{"a":2}')
    assert sig1 != sig2


@pytest.mark.unit
def test_sign_payload_returns_hex_digest_64_chars():
    """SHA256 hex = 64 chars."""
    from app.services.webhook_service import _sign_payload
    sig = _sign_payload("secret", b"any")
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


# ── enqueue_event ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_enqueue_event_with_invalid_event_type_returns_none():
    """event_type no listado en ALL_EVENTS -> return None silencioso (con log)."""
    from app.services.webhook_service import enqueue_event
    cur = MagicMock()

    result = enqueue_event(
        cur,
        client_id="00000000-0000-0000-0000-000000000001",
        lead_id=42,
        event_type="evento.que.no.existe",
        payload={"x": 1},
    )

    assert result is None
    # No ejecuto ninguna query (rejected al inicio)
    cur.execute.assert_not_called()


@pytest.mark.unit
def test_enqueue_event_returns_none_when_client_not_found():
    """Si el cliente no existe (o esta revocado), SELECT devuelve None -> return None."""
    from app.services.webhook_service import enqueue_event
    cur = MagicMock()
    cur.fetchone.return_value = None  # SELECT client devuelve nada

    result = enqueue_event(
        cur,
        client_id="00000000-0000-0000-0000-000000000099",
        lead_id=42,
        event_type="lead.created",
        payload={"x": 1},
    )

    assert result is None


@pytest.mark.unit
def test_enqueue_event_returns_none_when_webhook_disabled():
    """Cliente existe pero webhook_enabled=False -> no encola, return None."""
    from app.services.webhook_service import enqueue_event
    cur = MagicMock()
    cur.fetchone.return_value = {
        "webhook_url": "https://webhook.com/x",
        "webhook_enabled": False,         # <<< deshabilitado
        "webhook_events": ["lead.created"],
    }

    result = enqueue_event(
        cur, client_id="x", lead_id=1, event_type="lead.created", payload={},
    )
    assert result is None


@pytest.mark.unit
def test_enqueue_event_returns_none_when_event_not_subscribed():
    """Cliente tiene webhook activo pero no suscripto a este evento."""
    from app.services.webhook_service import enqueue_event
    cur = MagicMock()
    cur.fetchone.return_value = {
        "webhook_url": "https://webhook.com/x",
        "webhook_enabled": True,
        "webhook_events": ["lead.created"],  # solo lead.created
    }

    result = enqueue_event(
        cur, client_id="x", lead_id=1,
        event_type="lead.reassigned",   # <<< no suscripto
        payload={},
    )
    assert result is None


@pytest.mark.unit
def test_enqueue_event_returns_none_when_url_empty():
    """webhook_enabled=True pero webhook_url vacia -> no encola."""
    from app.services.webhook_service import enqueue_event
    cur = MagicMock()
    cur.fetchone.return_value = {
        "webhook_url": "",                # <<< vacia
        "webhook_enabled": True,
        "webhook_events": ["lead.created"],
    }

    result = enqueue_event(
        cur, client_id="x", lead_id=1, event_type="lead.created", payload={},
    )
    assert result is None


@pytest.mark.unit
def test_enqueue_event_swallows_db_exceptions_returns_none():
    """Webhook NUNCA debe romper el flujo de negocio. Si DB falla en el
    SELECT del cliente, devuelve None silencioso (log es side effect)."""
    from app.services.webhook_service import enqueue_event
    cur = MagicMock()
    cur.execute.side_effect = Exception("DB down")

    # No levanta
    result = enqueue_event(
        cur, client_id="x", lead_id=1, event_type="lead.created", payload={},
    )
    assert result is None


# ── build_lead_payload (V096) ────────────────────────────────────────────

def _mk_lead_row(**overrides):
    """Row base que devolveria el SELECT de build_lead_payload, simulando
    un lead con todos sus JOINs. Tests sobreescriben campos puntuales."""
    base = {
        "id": 7821,
        "external_id": "881958194328318",
        "nombres": "Cesar", "apellidos": "Enriquez",
        "telefono": "+51998069935", "email": "x@y.com", "dni": "29606789",
        "campana": "120211234567890",
        "campaign_name": "Camp. Segunda Vivienda",
        "fuente_form_id": "1234567890123456",
        "form_name": "We do - Segunda Vivienda - V 4",
        "conjunto": "AS1 - Familia",
        "anuncio": "Lead ad",
        "fuente": "Instagram", "estado": "Nuevo",
        "asesor_id": None, "supervisor_id": None,
        "asesor_email": None, "asesor_telefono": None, "asesor_nombre": None,
        "supervisor_email": None, "supervisor_telefono": None, "supervisor_nombre": None,
        "created_at": "2026-06-22T16:18:31",
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_build_lead_payload_includes_form_and_campaign_fields():
    """V096 — Bug ID: pre-PR Wedo. El payload del webhook no devolvia
    fuente_form_id, form_name ni campaign_name. Wedo no podia correlacionar
    el lead con su metadata del form."""
    from app.services.webhook_service import build_lead_payload
    cur = MagicMock()
    # 1er fetchone: privacy config; 2do: el lead row con JOINs.
    cur.fetchone.side_effect = [
        {
            "webhook_include_asesor_contact": True,
            "webhook_include_supervisor": True,
            "webhook_include_supervisor_contact": False,
        },
        _mk_lead_row(),
    ]

    payload = build_lead_payload(
        cur, lead_id=7821, event_type="lead.assigned",
        client_id="00000000-0000-0000-0000-000000000001",
    )

    assert payload is not None
    lead = payload["lead"]
    assert lead["fuente_form_id"] == "1234567890123456"
    assert lead["form_name"]      == "We do - Segunda Vivienda - V 4"
    assert lead["campaign_name"]  == "Camp. Segunda Vivienda"
    assert lead["campana"]        == "120211234567890"
    assert lead["external_id"]    == "881958194328318"
    # Campos preexistentes intactos (no regression)
    assert lead["conjunto"] == "AS1 - Familia"
    assert lead["anuncio"]  == "Lead ad"


@pytest.mark.unit
def test_build_lead_payload_nullable_when_cache_missing():
    """V096 — Si el meta_catalog_cache no tiene fila para esa campana/form
    (lead viejo, polling no hidrato el cache, etc), los nuevos campos
    llegan como None en el JSON. No rompe el consumer."""
    from app.services.webhook_service import build_lead_payload
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {
            "webhook_include_asesor_contact": True,
            "webhook_include_supervisor": True,
            "webhook_include_supervisor_contact": False,
        },
        _mk_lead_row(
            fuente_form_id=None,
            form_name=None,
            campaign_name=None,
            campana=None,
        ),
    ]

    payload = build_lead_payload(
        cur, lead_id=1, event_type="lead.assigned",
        client_id="00000000-0000-0000-0000-000000000001",
    )

    assert payload is not None
    lead = payload["lead"]
    assert lead["fuente_form_id"] is None
    assert lead["form_name"]      is None
    assert lead["campaign_name"]  is None

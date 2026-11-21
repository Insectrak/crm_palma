"""
V084: tests del evento webhook `lead.recontacto`.

Cubre:
  - `lead.recontacto` esta en ALL_EVENTS (suscribible por el proveedor).
  - `enqueue_event` lo acepta como event_type valido.
  - `build_lead_payload` agrega el bloque `recontacto` cuando recibe
    `event_type='lead.recontacto'` y `recontacto_id` no nulo.
  - El bloque NO se agrega cuando falta `recontacto_id` o cuando el
    SELECT no encuentra la fila (defensa contra race conditions).
"""
from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_event_lead_recontacto_esta_en_all_events():
    """Bug ID: V084 — el proveedor debe poder suscribirse a lead.recontacto.
    Si esta constante no esta en ALL_EVENTS, enqueue_event lo rechaza y el
    proveedor nunca recibe el push de re-engagement."""
    from app.services.webhook_service import ALL_EVENTS, EVENT_LEAD_RECONTACTO

    assert EVENT_LEAD_RECONTACTO == "lead.recontacto"
    assert EVENT_LEAD_RECONTACTO in ALL_EVENTS


@pytest.mark.unit
def test_enqueue_event_acepta_lead_recontacto_como_event_type():
    """enqueue_event con event_type='lead.recontacto' no debe rechazar
    por 'event_type no soportado'. Llega al SELECT del client."""
    from app.services.webhook_service import enqueue_event

    cur = MagicMock()
    cur.fetchone.return_value = None  # client no encontrado -> short-circuit

    result = enqueue_event(
        cur,
        client_id="00000000-0000-0000-0000-000000000001",
        lead_id=42,
        event_type="lead.recontacto",
        payload={"event": "lead.recontacto"},
    )

    # None porque el client no existe, NO por event_type invalido.
    assert result is None
    # Pero el SELECT al client se intento (no fue rejected upfront).
    assert cur.execute.called


@pytest.mark.regression
@pytest.mark.unit
def test_build_lead_payload_agrega_bloque_recontacto_cuando_aplica():
    """V084 — el payload de lead.recontacto debe incluir un bloque con la
    atribucion NUEVA (campaña/anuncio/conjunto del recontacto), separado
    del bloque `lead` que mantiene la atribucion ORIGINAL."""
    from app.services.webhook_service import build_lead_payload

    cur = MagicMock()
    # SELECT crm.leads (lead canonico — atribucion ORIGINAL)
    # SELECT crm.lead_recontactos (atribucion NUEVA)
    cur.fetchone.side_effect = [
        {
            "id": 42,
            "external_id": "google_form_old",
            "nombres": "Carlos", "apellidos": "Ramirez",
            "telefono": "+51999111469",
            "email": None, "dni": None,
            "fuente": "Google AdWords",
            "campana": "Búsqueda Marca Q1-2025",
            "conjunto": None, "anuncio": None,
            "estado": "Contactado",
            "asesor_id": None, "supervisor_id": None,
            "asesor_email": None, "asesor_telefono": None, "asesor_nombre": None,
            "supervisor_email": None, "supervisor_telefono": None, "supervisor_nombre": None,
            "created_at": "2025-03-12T09:14:22.000Z",
        },
        {
            "id": 789,
            "campana": "120299988877766",
            "campaign_name": "Meta_Promo_Verano_2026",       # V096.4
            "anuncio": "Ad_Retargeting_X",
            "conjunto": "AdSet_Lookalike_30d",
            "fuente_form_id": "9876543210987654",
            "form_name": "FB Lead Form - Promo Verano",      # V096.4
            "fuente_externa_id": "fb_lead_001",
            "external_created_at": None,
            "estrategia": "mantener_asesor",
            "estado_lead_anterior": "Contactado",
            "razon": "Se mantiene al asesor original — rapport preservado.",
            "created_at": None,
            "fuente": "Facebook",
        },
    ]

    payload = build_lead_payload(
        cur,
        lead_id=42,
        event_type="lead.recontacto",
        recontacto_id=789,
    )

    # El bloque `lead` mantiene la atribucion original (Google).
    assert payload["lead"]["campana"] == "Búsqueda Marca Q1-2025"
    assert payload["lead"]["fuente"] == "Google AdWords"

    # El bloque `recontacto` revela la atribucion NUEVA (Meta).
    assert "recontacto" in payload
    rec = payload["recontacto"]
    assert rec["id"] == 789
    assert rec["campana"] == "120299988877766"
    assert rec["anuncio"] == "Ad_Retargeting_X"
    assert rec["conjunto"] == "AdSet_Lookalike_30d"
    assert rec["fuente"] == "Facebook"
    assert rec["fuente_form_id"] == "9876543210987654"
    assert rec["fuente_externa_id"] == "fb_lead_001"
    assert rec["estrategia"] == "mantener_asesor"
    # V096.4 — nombres legibles resueltos via meta_catalog_cache deben llegar
    # al payload (simetria con el bloque `lead`). Antes solo venian los IDs.
    assert rec["campaign_name"] == "Meta_Promo_Verano_2026"
    assert rec["form_name"] == "FB Lead Form - Promo Verano"


@pytest.mark.regression
@pytest.mark.unit
def test_build_lead_payload_recontacto_sin_cache_devuelve_null():
    """V096.4 — Bug ID: pre-V096.4 webhook recontacto solo devolvia IDs.
    Si meta_catalog_cache no tiene fila para esa campana/form (lead viejo o
    polling sin nombres), los campos campaign_name/form_name llegan como
    None — paridad con el bloque `lead`, degradacion graciosa."""
    from app.services.webhook_service import build_lead_payload

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {
            "id": 42,
            "external_id": None,
            "nombres": "X", "apellidos": None,
            "telefono": "+51999999999",
            "email": None, "dni": None,
            "fuente": None, "campana": None,
            "campaign_name": None, "fuente_form_id": None, "form_name": None,
            "conjunto": None, "anuncio": None,
            "estado": None,
            "asesor_id": None, "supervisor_id": None,
            "asesor_email": None, "asesor_telefono": None, "asesor_nombre": None,
            "supervisor_email": None, "supervisor_telefono": None, "supervisor_nombre": None,
            "created_at": None,
        },
        {
            "id": 999,
            "campana": "120299988877766",
            "campaign_name": None,    # cache miss
            "anuncio": "ad",
            "conjunto": "as",
            "fuente_form_id": "9876543210987654",
            "form_name": None,        # cache miss
            "fuente_externa_id": "fext",
            "external_created_at": None,
            "estrategia": "mantener_asesor",
            "estado_lead_anterior": None,
            "razon": None,
            "created_at": None,
            "fuente": "Facebook",
        },
    ]

    payload = build_lead_payload(
        cur, lead_id=42, event_type="lead.recontacto", recontacto_id=999,
    )

    rec = payload["recontacto"]
    # IDs sí llegaron (datos crudos de la fila).
    assert rec["campana"] == "120299988877766"
    assert rec["fuente_form_id"] == "9876543210987654"
    # Nombres son null porque el cache no los tenía — no rompe el consumer.
    assert rec["campaign_name"] is None
    assert rec["form_name"] is None


@pytest.mark.unit
def test_build_lead_payload_sin_recontacto_id_no_agrega_bloque():
    """Si el caller llama build_lead_payload con event_type='lead.recontacto'
    pero sin recontacto_id, NO agregamos el bloque (fallback seguro — el
    payload queda sin atribucion nueva pero el resto funciona)."""
    from app.services.webhook_service import build_lead_payload

    cur = MagicMock()
    cur.fetchone.return_value = {
        "id": 42,
        "external_id": None,
        "nombres": "X", "apellidos": None,
        "telefono": "+51999999999",
        "email": None, "dni": None,
        "fuente": None, "campana": None,
        "conjunto": None, "anuncio": None,
        "estado": None,
        "asesor_id": None, "supervisor_id": None,
        "asesor_email": None, "asesor_telefono": None, "asesor_nombre": None,
        "supervisor_email": None, "supervisor_telefono": None, "supervisor_nombre": None,
        "created_at": None,
    }

    payload = build_lead_payload(
        cur,
        lead_id=42,
        event_type="lead.recontacto",
        recontacto_id=None,
    )

    assert "recontacto" not in payload


@pytest.mark.unit
def test_build_lead_payload_recontacto_no_encontrado_no_rompe():
    """Si la fila de lead_recontactos no se encuentra (race con DELETE),
    el bloque se omite silenciosamente — el payload base sigue saliendo."""
    from app.services.webhook_service import build_lead_payload

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {
            "id": 42,
            "external_id": None,
            "nombres": "X", "apellidos": None,
            "telefono": "+51999999999",
            "email": None, "dni": None,
            "fuente": None, "campana": None,
            "conjunto": None, "anuncio": None,
            "estado": None,
            "asesor_id": None, "supervisor_id": None,
            "asesor_email": None, "asesor_telefono": None, "asesor_nombre": None,
            "supervisor_email": None, "supervisor_telefono": None, "supervisor_nombre": None,
            "created_at": None,
        },
        None,   # SELECT crm.lead_recontactos NO encuentra el row
    ]

    payload = build_lead_payload(
        cur,
        lead_id=42,
        event_type="lead.recontacto",
        recontacto_id=789,
    )

    # No tira excepcion, pero tampoco agrega el bloque.
    assert payload is not None
    assert "recontacto" not in payload

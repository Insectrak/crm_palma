"""Tests de visibilidad por rol en /api/whatsapp/conversations.

Modelo aplicado (own → team → all, estilo Salesforce/HubSpot):
- admin      → ve todo.
- supervisor → su equipo (crm.equipos) + chats propios + pool compartido
               sin owner en estados de triage.
- asesor     → solo chats asignados a si mismo.
"""
from app.routers.whatsapp import (
    _ARCHIVE_REASONS,
    _SHARED_POOL_STATUSES,
    _conversation_visibility_clause,
)
from app.auth.schemas import TokenData


def _user(role: str, user_id: str = "00000000-0000-0000-0000-000000000099") -> TokenData:
    return TokenData(user_id=user_id, email=f"{role}@t.local", role=role)


def test_admin_sin_restriccion():
    sql, params = _conversation_visibility_clause(_user("admin"))
    assert sql == "TRUE"
    assert params == []


def test_asesor_solo_lo_suyo():
    sql, params = _conversation_visibility_clause(_user("asesor", "uuid-asesor"))
    assert "c.asesor_id = %s::uuid" in sql
    assert params == ["uuid-asesor"]


def test_supervisor_incluye_equipo_propio_y_pool():
    sql, params = _conversation_visibility_clause(_user("supervisor", "uuid-sup"))
    # Incluye chats propios (recien clasificados sin delegar)
    assert "c.asesor_id = %s::uuid" in sql
    # Incluye su equipo via crm.equipos
    assert "FROM crm.equipos" in sql
    assert "supervisor_id = %s::uuid AND activo = TRUE" in sql
    # V035: incluye leads en cola del supervisor (lead.supervisor_id=self)
    assert "FROM crm.leads l" in sql
    assert "l.supervisor_id = %s::uuid" in sql
    # Incluye pool compartido sin owner en estados de triage
    assert "c.asesor_id IS NULL" in sql
    for status in _SHARED_POOL_STATUSES:
        assert status in params
    # user_id aparece cinco veces:
    #   1. c.asesor_id = self
    #   2. NOT EXISTS guardrail (otro supervisor dueno del lead)
    #   3. crm.equipos supervisor_id
    #   4. l.supervisor_id = self
    #   5. l3 → equipos del supervisor (regla 5: heredar visibilidad del lead
    #      cuando la conv no tiene asesor pero el lead si pertenece al equipo)
    assert params.count("uuid-sup") == 5


def test_supervisor_ve_leads_en_cola_post_v035():
    """Post-V035: supervisor debe ver chats de leads con lead.supervisor_id=self
    aunque wa_conversations.asesor_id sea NULL y el status ya no este en el pool.

    Este es el caso Antonella/taty/Guss: lead clasificado y en cola del
    supervisor, pero la conversacion no tiene owner directo.
    """
    sql, _ = _conversation_visibility_clause(_user("supervisor", "uuid-sup"))
    # El clause debe incluir una referencia explicita a lead.supervisor_id
    assert "l.supervisor_id = %s::uuid" in sql
    assert "l.id = c.lead_id" in sql


def test_pool_excluye_leads_con_supervisor_ya_asignado():
    """El pool compartido no debe mostrar chats cuyo lead ya tiene un
    supervisor asignado — ese supervisor es el unico dueno.

    Ejemplo: Virgi (lead.supervisor_id=Diego, conv.asesor_id=NULL,
    status=manual_review). Paola NO debe verla en su Chat.
    """
    sql, _ = _conversation_visibility_clause(_user("supervisor", "uuid-sup"))
    # El pool ahora debe requerir ausencia de supervisor_id en el lead
    assert "l2.supervisor_id IS NOT NULL" in sql
    assert "NOT EXISTS" in sql


def test_supervisor_no_ve_chat_asignado_si_lead_tiene_otro_supervisor():
    """Si conv.asesor_id apunta al supervisor A pero lead.supervisor_id=B,
    A NO debe ver el chat — el owner autoritativo es B (lead).

    Caso real taty: conv.asesor_id=Paola (legacy), lead.supervisor_id=Diego.
    Paola no debe ver el chat; Diego si via clause l.supervisor_id=self.
    """
    sql, _ = _conversation_visibility_clause(_user("supervisor", "uuid-sup"))
    # La clause propia debe incluir el guardrail NOT EXISTS
    assert "l0.supervisor_id <> %s::uuid" in sql
    assert "l0.supervisor_id IS NOT NULL" in sql


def test_supervisor_pool_cubre_pending_queued_manual_failed():
    """El pool compartido debe incluir exactamente los 4 estados de triage.

    pending/queued son transitorios (IA procesando), manual_review/failed
    son estados finales sin decision — todos deben ser visibles a cualquier
    supervisor para permitir triage colaborativo.
    """
    assert set(_SHARED_POOL_STATUSES) == {
        "pending", "queued", "manual_review", "failed",
    }


def test_rol_desconocido_no_ve_nada():
    """Un rol no-admin/supervisor/asesor no debe poder ver nada (deny by default)."""
    sql, params = _conversation_visibility_clause(_user("invitado"))
    assert sql == "FALSE"
    assert params == []


def test_list_conversations_asesor_sin_token_rechazado(client):
    """Sanity check: endpoint requiere auth."""
    r = client.get("/api/whatsapp/conversations")
    assert r.status_code in (401, 403)


def test_archive_reasons_enum():
    """Los motivos de archivo son un enum cerrado estilo Salesforce."""
    assert _ARCHIVE_REASONS == {
        "not_a_lead", "spam", "duplicate", "no_response", "other",
    }


def test_archive_endpoint_sin_token_rechazado(client):
    """Sanity check: endpoint de archivo requiere auth."""
    r = client.post("/api/whatsapp/conversations/1/archive", json={"reason": "spam"})
    assert r.status_code in (401, 403)

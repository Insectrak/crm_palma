"""Tests para `app.services.wa_conversation_service`.

V070.71 (Bundle C.3 — split de whatsapp.py).
"""
import pytest


class _StubCursor:
    """Cursor minimo que registra queries y devuelve fetchone()s prearmados."""
    def __init__(self, fetchone_queue=None):
        self.calls = []
        self._queue = list(fetchone_queue or [])

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        if self._queue:
            return self._queue.pop(0)
        return None


class TestGetOrCreateConversation:
    def test_upsert_devuelve_id(self):
        from app.services.wa_conversation_service import get_or_create_conversation
        cur = _StubCursor(fetchone_queue=[(42,)])
        result = get_or_create_conversation(cur, "+51987654321", "Carlos", wa_number_id=3)
        assert result == 42
        assert len(cur.calls) == 1
        sql, params = cur.calls[0]
        assert "INSERT INTO crm.wa_conversations" in sql
        assert "ON CONFLICT (wa_phone) DO UPDATE" in sql
        assert params == ("+51987654321", "Carlos", 3)

    def test_acepta_wa_number_id_none(self):
        from app.services.wa_conversation_service import get_or_create_conversation
        cur = _StubCursor(fetchone_queue=[(7,)])
        result = get_or_create_conversation(cur, "+51987654321", "Test", wa_number_id=None)
        assert result == 7
        _, params = cur.calls[0]
        assert params[2] is None


class TestReleaseLeadIfTerminal:
    def test_devuelve_false_si_no_hay_lead_terminal(self):
        """Conversacion sin lead enlazado o lead en estado activo → no libera."""
        from app.services.wa_conversation_service import release_lead_if_terminal
        cur = _StubCursor(fetchone_queue=[None])  # SELECT no encuentra fila
        assert release_lead_if_terminal(cur, conversation_id=99) is False
        # Solo ejecuto el SELECT, no UPDATE ni nada
        assert len(cur.calls) == 1

    def test_libera_lead_si_estado_es_terminal(self):
        """Lead en 'Ganado' → cierra wa_conversation_leads + nulea lead_id."""
        from app.services.wa_conversation_service import release_lead_if_terminal
        # SELECT devuelve lead_id=123, UPDATE wa_conversation_leads no devuelve nada,
        # UPDATE wa_conversations tampoco.
        cur = _StubCursor(fetchone_queue=[(123,)])
        result = release_lead_if_terminal(cur, conversation_id=55)
        assert result is True
        # Debe haber ejecutado: 1 SELECT + 1 UPDATE wa_conversation_leads + 1 UPDATE wa_conversations
        assert len(cur.calls) == 3
        sql_select, _ = cur.calls[0]
        assert "FROM crm.wa_conversations" in sql_select
        sql_update_leads, params_leads = cur.calls[1]
        assert "UPDATE crm.wa_conversation_leads" in sql_update_leads
        assert params_leads == (55, 123)
        sql_update_conv, params_conv = cur.calls[2]
        assert "UPDATE crm.wa_conversations" in sql_update_conv
        assert "lead_id" in sql_update_conv
        assert "NULL" in sql_update_conv
        assert params_conv == (55,)


class TestTerminalStatesConstant:
    def test_terminal_states_contiene_los_3_canonicos(self):
        from app.services.wa_conversation_service import TERMINAL_LEAD_STATES
        assert "Ganado" in TERMINAL_LEAD_STATES
        assert "Perdido" in TERMINAL_LEAD_STATES
        assert "No interesado" in TERMINAL_LEAD_STATES
        assert len(TERMINAL_LEAD_STATES) == 3

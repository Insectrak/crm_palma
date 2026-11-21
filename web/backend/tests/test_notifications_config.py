"""Tests para notification_service y endpoints /api/settings/notifications.

Cubre:
- _safe_format: substitucion de variables, keys faltantes no rompen,
  espacios colapsados.
- notify(): respeta enabled=False, render dummy, fcm.send se invoca
  con title+body procesados.
- load_templates(): defaults sin DB, merge sobre defaults, cache TTL.
- Endpoints: GET (admin), PUT con sanitizado/whitelist, POST /test.
"""
from contextlib import contextmanager

from app.config import settings as app_settings


# ── _safe_format ───────────────────────────────────────────────────────────

def test_safe_format_substitutes_known_vars():
    from app.services.notification_service import _safe_format
    assert _safe_format("Hola {name}", {"name": "Juan"}) == "Hola Juan"


def test_safe_format_missing_key_keeps_literal():
    """Var no provista queda como {placeholder} (no levanta KeyError)."""
    from app.services.notification_service import _safe_format
    result = _safe_format("Hola {name} de {fuente}", {"name": "Juan"})
    assert "{fuente}" in result
    assert "Juan" in result


def test_safe_format_collapses_extra_spaces_from_empty_vars():
    from app.services.notification_service import _safe_format
    # Si fuente="" y el template tiene "Hola {name} ({fuente})", queda
    # "Hola Juan ()" que despues se trim/colapsa a "Hola Juan ()"
    result = _safe_format("Hola {name}", {"name": "  Juan  "})
    assert result == "Hola Juan"


def test_safe_format_empty_template_returns_empty():
    from app.services.notification_service import _safe_format
    assert _safe_format("", {"any": "value"}) == ""
    assert _safe_format(None, {}) == ""


def test_safe_format_handles_none_values():
    from app.services.notification_service import _safe_format
    result = _safe_format("Hola {name}", {"name": None})
    # None se convierte a "" → "Hola " que se trim a "Hola"
    assert result == "Hola"


# ── notify() ───────────────────────────────────────────────────────────────

def test_notify_returns_false_when_event_disabled(monkeypatch):
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self):
                        # Devuelve dict con events.lead_created.enabled=False
                        return ({"events": {"lead_created": {"enabled": False}}},)
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.notification_service.get_db", fake_get_db)

    sent_calls = []
    monkeypatch.setattr("app.services.fcm_service.send",
                        lambda *a, **kw: sent_calls.append((a, kw)) or True)

    result = ns.notify("lead_created", "uuid-asesor", {"lead_name": "Test"})
    assert result is False
    assert sent_calls == []  # fcm.send NO debe haberse llamado


def test_notify_calls_fcm_with_rendered_template(monkeypatch):
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()

    @contextmanager
    def fake_get_db():
        class _C:
            # V070.60 — acepta cursor_factory=RealDictCursor (kwarg que ahora
            # usa load_user_prefs y otros consumidores tras la migración a
            # RealDictCursor). Sin **kwargs, los tests rompen con TypeError.
            def cursor(self, *args, **kwargs):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self): return None  # sin row → defaults
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.notification_service.get_db", fake_get_db)

    # V070.51 — el servicio añadió quiet hours (default 21:00-08:00 Lima).
    # Si el test corre dentro de esa ventana, notify() devuelve False y
    # nunca llega a fcm_service.send. Forzamos non-quiet para que el test
    # valide únicamente render+envío (no la lógica de horarios).
    monkeypatch.setattr(
        "app.services.notification_service._is_quiet_hour_now",
        lambda *a, **k: False,
    )

    sent_calls = []
    def fake_send(uid, title, body, data=None):
        sent_calls.append({"uid": uid, "title": title, "body": body, "data": data})
        return True
    monkeypatch.setattr("app.services.fcm_service.send", fake_send)

    result = ns.notify("lead_created", "uuid-x", {"lead_name": "Carlos"})
    assert result is True
    assert len(sent_calls) == 1
    assert sent_calls[0]["uid"] == "uuid-x"
    assert sent_calls[0]["title"] == "Nuevo lead asignado"
    assert sent_calls[0]["body"] == "Carlos"


def test_notify_returns_false_for_empty_recipient(monkeypatch):
    from app.services import notification_service as ns
    sent_calls = []
    monkeypatch.setattr("app.services.fcm_service.send",
                        lambda *a, **kw: sent_calls.append(a) or True)
    assert ns.notify("lead_created", "", {"lead_name": "X"}) is False
    assert sent_calls == []


# ── load_templates ────────────────────────────────────────────────────────

def test_load_templates_returns_defaults_when_no_row(monkeypatch):
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self): return None
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.notification_service.get_db", fake_get_db)

    templates = ns.load_templates()
    assert "lead_created" in templates
    assert "wa_message_inbound" in templates
    assert templates["lead_created"]["enabled"] is True


def test_load_templates_merges_db_over_defaults(monkeypatch):
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self):
                        return ({"events": {
                            "lead_created": {"title": "Custom title!", "enabled": False},
                        }},)
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.notification_service.get_db", fake_get_db)

    templates = ns.load_templates()
    assert templates["lead_created"]["title"] == "Custom title!"
    assert templates["lead_created"]["enabled"] is False
    # Body NO fue customizado → queda en default
    assert templates["lead_created"]["body"] == "{lead_name}"
    # wa_message_inbound NO fue tocado → queda completo en default
    assert templates["wa_message_inbound"]["enabled"] is True


# ── Endpoints ──────────────────────────────────────────────────────────────

def test_get_notifications_requires_admin(client, auth_headers_asesor):
    res = client.get("/api/settings/notifications", headers=auth_headers_asesor)
    assert res.status_code == 403


def test_get_notifications_demo_returns_defaults(client, auth_headers_admin, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.get("/api/settings/notifications", headers=auth_headers_admin)
    assert res.status_code == 200
    body = res.json()
    assert "events" in body
    assert "lead_created" in body["events"]
    assert "available_variables" in body
    assert "lead_name" in body["available_variables"]["lead_created"]


def test_put_notifications_sanitizes_and_whitelists(
    client, auth_headers_admin, monkeypatch,
):
    """Eventos desconocidos del payload se filtran. Campos faltantes vienen
    con defaults. Title/body se truncan a max length."""
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.put(
        "/api/settings/notifications",
        headers=auth_headers_admin,
        json={
            "events": {
                "lead_created":   {"enabled": False, "title": "T", "body": "B"},
                "evento_inventado": {"enabled": True, "title": "X", "body": "Y"},  # debe filtrarse
                # lead_reassigned y wa_message_inbound NO van → quedan en defaults
            },
        },
    )
    assert res.status_code == 200
    body = res.json()
    events = body["events"]
    # Whitelist: solo eventos conocidos
    assert "lead_created" in events
    assert "lead_reassigned" in events
    assert "wa_message_inbound" in events
    assert "evento_inventado" not in events
    # Customizacion respetada
    assert events["lead_created"]["enabled"] is False
    assert events["lead_created"]["title"] == "T"
    # Eventos no provistos quedan en default (enabled=True)
    assert events["lead_reassigned"]["enabled"] is True


def test_test_endpoint_requires_auth(client):
    res = client.post("/api/settings/notifications/test", json={"event_type": "lead_created"})
    assert res.status_code == 401


def test_test_endpoint_demo_returns_rendered_preview(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.post(
        "/api/settings/notifications/test",
        headers=auth_headers_admin,
        json={"event_type": "lead_created"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["demo"] is True
    assert body["title"] == "Nuevo lead asignado"
    # body fue renderizado con dummy context (lead_name)
    assert "Juan" in body["body"]


def test_test_endpoint_rejects_unknown_event(
    client, auth_headers_admin, monkeypatch,
):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    res = client.post(
        "/api/settings/notifications/test",
        headers=auth_headers_admin,
        json={"event_type": "evento_que_no_existe"},
    )
    assert res.status_code == 400


# ── V070.85 — Push al supervisor cuando lead queda en su cola ─────────────
#
# Antes los paths Meta/API ingest y creacion manual de leads solo notificaban
# si habia asesor real. Si el lead quedaba en cola del supervisor (auto-asignacion
# off, equipo sin candidatos, circuit breaker activo, admin creando sin
# asignar), el supervisor NO se enteraba hasta entrar manualmente al CRM.
# Estos tests aseguran que notify_new_lead es agnostic al rol — funciona
# igual para supervisor que para asesor, y que el patron
# 'recipient = asesor or supervisor; notify_new_lead(recipient, ...)' es
# valido y produce un push real.


def _patch_for_notify(monkeypatch):
    """Setup comun: get_db mockeado + quiet hours off + capturador de send."""
    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self, *args, **kwargs):
                class _Cur:
                    def execute(self, *a, **k): pass
                    def fetchone(self): return None
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.notification_service.get_db", fake_get_db)
    monkeypatch.setattr(
        "app.services.notification_service._is_quiet_hour_now",
        lambda *a, **k: False,
    )
    sent_calls = []
    def fake_send(uid, title, body, data=None):
        sent_calls.append({"uid": uid, "title": title, "body": body, "data": data})
        return True
    monkeypatch.setattr("app.services.fcm_service.send", fake_send)
    return sent_calls


def test_notify_new_lead_dispara_push_al_supervisor_cuando_no_hay_asesor(monkeypatch):
    """Contrato V070.85: notify_new_lead(supervisor_id, ...) debe disparar
    fcm.send igual que para un asesor. El servicio es agnostic al rol del
    recipient — la decision de a quien notificar la toma el caller (ingest
    core o routers/leads.py)."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_for_notify(monkeypatch)

    # Simula el patron del caller: target_asesor=None, target_supervisor=ID
    supervisor_id = "supervisor-uuid-x"
    result = ns.notify_new_lead(supervisor_id, "Maria Garcia", fuente="instagram")

    assert result is True
    assert len(sent_calls) == 1
    assert sent_calls[0]["uid"] == supervisor_id
    assert sent_calls[0]["title"] == "Nuevo lead asignado"
    assert "Maria Garcia" in sent_calls[0]["body"]


def test_notify_new_lead_funciona_igual_para_asesor_y_supervisor(monkeypatch):
    """Sanity check: el mismo notify_new_lead llamado con un asesor_id y
    luego con un supervisor_id debe producir 2 pushes equivalentes (mismo
    title, mismo body, diferente uid). Garantiza que no hay rama oculta
    que discrimine por rol."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_for_notify(monkeypatch)

    ns.notify_new_lead("asesor-uuid", "Juan Perez", fuente="facebook")
    ns.notify_new_lead("supervisor-uuid", "Juan Perez", fuente="facebook")

    assert len(sent_calls) == 2
    assert sent_calls[0]["title"] == sent_calls[1]["title"]
    assert sent_calls[0]["body"] == sent_calls[1]["body"]
    assert sent_calls[0]["uid"] != sent_calls[1]["uid"]


def test_notify_new_lead_skip_self_action_para_supervisor(monkeypatch):
    """Anti-noise: si el supervisor crea manualmente un lead y queda en su
    propia cola (target_supervisor == current_user), NO se debe disparar
    push redundante. performed_by=recipient → skip."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_for_notify(monkeypatch)

    supervisor_id = "supervisor-uuid-self"
    result = ns.notify_new_lead(
        supervisor_id, "Lead Manual", fuente="manual",
        performed_by=supervisor_id,
    )

    assert result is False  # skip self-action
    assert sent_calls == []


# ── V070.87 — lead_created es URGENT (paridad Salesforce/HubSpot) ─────────


def test_lead_created_es_urgent_y_bypassea_quiet_hours(monkeypatch):
    """Contrato V070.87: notify_new_lead debe enviar push AUNQUE estemos
    dentro del rango quiet_hours. Un lead nuevo es oportunidad fresca y
    no puede esperar 8h (HBR: la probabilidad de cerrar cae >80% si la
    primera respuesta tarda >1h)."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_for_notify(monkeypatch)

    # Forzamos quiet hours = ACTIVO (como si fueran las 03:00 AM).
    monkeypatch.setattr(
        "app.services.notification_service._is_quiet_hour_now",
        lambda *a, **k: True,
    )

    result = ns.notify_new_lead("asesor-uuid", "Lead madrugada", fuente="instagram")

    # Pese a quiet hours activo, debe enviarse porque lead_created es URGENT.
    assert result is True
    assert len(sent_calls) == 1
    assert sent_calls[0]["uid"] == "asesor-uuid"


def test_lead_reassigned_NO_es_urgent_y_respeta_quiet_hours(monkeypatch):
    """Sanity: solo lead_created y wa_message_inbound son URGENT.
    lead_reassigned NO es urgent — sigue respetando quiet hours."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_for_notify(monkeypatch)

    monkeypatch.setattr(
        "app.services.notification_service._is_quiet_hour_now",
        lambda *a, **k: True,
    )

    result = ns.notify_lead_reassigned("asesor-uuid", "Lead reasignado")

    # Reasignacion puede esperar a la mañana; suprimida por quiet hours.
    assert result is False
    assert sent_calls == []


def test_urgent_events_contiene_lead_created(monkeypatch):
    """Contrato explicito: lead_created esta en URGENT_EVENTS.
    Si alguien lo quita por error, este test salta."""
    from app.services.notification_service import URGENT_EVENTS
    assert "lead_created" in URGENT_EVENTS
    assert "wa_message_inbound" in URGENT_EVENTS


# ── V073 — Override personal del bypass URGENT (Salesforce DND-style) ─────


def _patch_with_user_prefs(monkeypatch, urgent_events_disabled=None,
                           push_enabled=True, events_disabled=None,
                           quiet_hours_active=True):
    """Setup que reemplaza load_user_prefs con valores controlados."""
    sent_calls = _patch_for_notify(monkeypatch)

    # Override _is_quiet_hour_now con valor parametrico
    monkeypatch.setattr(
        "app.services.notification_service._is_quiet_hour_now",
        lambda *a, **k: quiet_hours_active,
    )
    monkeypatch.setattr(
        "app.services.notification_service.load_user_prefs",
        lambda uid: {
            "push_enabled":           push_enabled,
            "quiet_hours_enabled":    None,
            "quiet_hours_start":      None,
            "quiet_hours_end":        None,
            "events_disabled":        events_disabled or [],
            "urgent_events_disabled": urgent_events_disabled or [],
        },
    )
    return sent_calls


def test_v073_user_desactiva_bypass_de_lead_created_respeta_quiet_hours(monkeypatch):
    """Caso central V073: el user agrego 'lead_created' a su
    urgent_events_disabled → el push de un lead NUEVO debe SUPRIMIRSE
    durante quiet hours, igual que un evento no-urgent."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_with_user_prefs(
        monkeypatch,
        urgent_events_disabled=["lead_created"],
        quiet_hours_active=True,
    )

    result = ns.notify_new_lead("asesor-uuid", "Lead 3am")

    # Sin override seria URGENT y pasaria. Con override, respeta quiet hours.
    assert result is False
    assert sent_calls == []


def test_v073_user_NO_desactiva_bypass_de_lead_created_recibe_aunque_quiet(monkeypatch):
    """Sanity check: si el user no toca urgent_events_disabled (default
    vacio), lead_created sigue siendo URGENT y bypassea quiet hours."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_with_user_prefs(
        monkeypatch,
        urgent_events_disabled=[],  # default
        quiet_hours_active=True,
    )

    result = ns.notify_new_lead("asesor-uuid", "Lead 3am")

    # URGENT por default, bypassea quiet hours.
    assert result is True
    assert len(sent_calls) == 1


def test_v073_override_de_lead_created_NO_afecta_wa_message(monkeypatch):
    """Independencia: desactivar el bypass de lead_created NO debe afectar
    el bypass de wa_message_inbound. Cada evento URGENT se overridea por
    separado (Salesforce DND-style allowed types per type)."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_with_user_prefs(
        monkeypatch,
        urgent_events_disabled=["lead_created"],
        quiet_hours_active=True,
    )

    # wa_message_inbound NO esta en urgent_events_disabled → sigue URGENT.
    result = ns.notify_wa_message_inbound(
        "asesor-uuid", "Cliente Juan", "Hola, sigo interesado",
    )

    assert result is True
    assert len(sent_calls) == 1


def test_v073_default_urgent_events_disabled_vacio_en_user_prefs_defaults():
    """Contract test: _user_prefs_defaults() incluye urgent_events_disabled
    como []. Sin esto, load_user_prefs() de usuarios sin fila DB rompe
    el acceso al campo."""
    from app.services.notification_service import _user_prefs_defaults
    defaults = _user_prefs_defaults()
    assert "urgent_events_disabled" in defaults
    assert defaults["urgent_events_disabled"] == []


# ── V070.91 — Deep-link by record id en push payload (Salesforce-style) ──


def _patch_capture_send(monkeypatch):
    """Setup que captura los kwargs de fcm_service.send (incluido data)."""
    sent_calls = _patch_for_notify(monkeypatch)

    monkeypatch.setattr(
        "app.services.notification_service._is_quiet_hour_now",
        lambda *a, **k: False,
    )
    return sent_calls


def test_v070_91_notify_new_lead_incluye_lead_id_en_data(monkeypatch):
    """notify_new_lead(lead_id=42) debe enviar data={'type':'lead_created','lead_id':'42'}.
    Necesario para que el mobile pueda navegar al LeadDetalle especifico al tap."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_capture_send(monkeypatch)

    ns.notify_new_lead("asesor-uuid", "Maria Garcia", fuente="instagram", lead_id=42)

    assert len(sent_calls) == 1
    data = sent_calls[0]["data"]
    assert data is not None
    assert data.get("type") == "lead_created"
    assert data.get("lead_id") == "42"  # str para FCM payload


def test_v070_91_notify_new_lead_sin_lead_id_omite_campo(monkeypatch):
    """Si no se pasa lead_id, NO debe aparecer 'lead_id' en data.
    Mobile cae a fallback (lista de Leads) cuando el campo esta ausente."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_capture_send(monkeypatch)

    ns.notify_new_lead("asesor-uuid", "Maria Garcia", fuente="instagram")

    assert len(sent_calls) == 1
    data = sent_calls[0]["data"]
    assert data.get("type") == "lead_created"
    assert "lead_id" not in data


def test_v070_91_notify_lead_reassigned_incluye_lead_id(monkeypatch):
    """notify_lead_reassigned tambien lleva lead_id para deep-link."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_capture_send(monkeypatch)

    ns.notify_lead_reassigned("asesor-uuid", "Juan Perez", lead_id=100)

    assert len(sent_calls) == 1
    data = sent_calls[0]["data"]
    assert data.get("type") == "lead_reassigned"
    assert data.get("lead_id") == "100"


def test_v070_91_notify_lead_recontacto_incluye_lead_id(monkeypatch):
    """notify_lead_recontacto ya recibia lead_id por signature; ahora
    tambien lo propaga al data payload del push."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_capture_send(monkeypatch)

    ns.notify_lead_recontacto("asesor-uuid", 555, "Ana Lopez", fuente="instagram")

    assert len(sent_calls) == 1
    data = sent_calls[0]["data"]
    assert data.get("type") == "lead_recontacto"
    assert data.get("lead_id") == "555"


def test_v070_91_notify_wa_message_inbound_data_intacto(monkeypatch):
    """Sanity: el deep-link de WhatsApp (conversation_id) NO cambio."""
    from app.services import notification_service as ns
    ns.invalidate_templates_cache()
    sent_calls = _patch_capture_send(monkeypatch)

    ns.notify_wa_message_inbound(
        "asesor-uuid", "Cliente Juan", "Hola sigo interesado",
        wa_phone="+51999111222", conversation_id=789,
    )

    assert len(sent_calls) == 1
    data = sent_calls[0]["data"]
    assert data.get("type") == "wa_message_inbound"
    assert data.get("conversation_id") == "789"


def test_v073_save_user_prefs_whitelist_urgent_events(monkeypatch):
    """save_user_prefs solo acepta en urgent_events_disabled eventos que
    EFECTIVAMENTE esten en URGENT_EVENTS. Otros se descartan silencio.
    Esto previene que el frontend mande basura o eventos no-urgent."""
    from app.services import notification_service as ns

    saved_data = {}

    @contextmanager
    def fake_get_db():
        class _C:
            def cursor(self, *a, **k):
                class _Cur:
                    def execute(self_inner, sql, params=None):
                        if "INSERT INTO" in sql and params:
                            saved_data["urgent_events_disabled"] = params[6]
                    def __enter__(self_inner): return self_inner
                    def __exit__(self_inner, *a): return False
                return _Cur()
            def commit(self): pass
            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
        yield _C()
    monkeypatch.setattr("app.services.notification_service.get_db", fake_get_db)

    # Mezcla: 'lead_created' (urgent OK), 'lead_reassigned' (no-urgent,
    # debe descartarse), 'evento_inexistente' (basura, descartar).
    ns.save_user_prefs("user-uuid", {
        "push_enabled": True,
        "urgent_events_disabled": [
            "lead_created",       # OK
            "lead_reassigned",    # no es urgent → descartar
            "evento_inexistente", # basura → descartar
        ],
    })

    import json
    parsed = json.loads(saved_data["urgent_events_disabled"])
    assert parsed == ["lead_created"]  # solo el valido sobrevive

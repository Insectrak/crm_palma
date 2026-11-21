"""Tests de regresion para PATCH /api/leads/{lead_id}/contactos/{id} (V070.97).

Bug B (reportado en prod 2026-05-17): al editar un contacto desde mobile,
los campos extra (nuevo_estado_id, duracion_minutos, proxima_accion, etc)
se ignoraban silenciosamente porque el schema ContactoUpdate solo aceptaba
5 campos. Mobile bloqueaba el envio condicionalmente con comentario:

    "nuevo_estado_id solo aplica a CREACION (el endpoint POST lo acepta;
     el PATCH lo ignora)."

Fix V070.97 — paridad total con CREATE: ContactoUpdate acepta todos los
campos y el handler aplica nuevo_estado_id al lead en el mismo PATCH
(Salesforce-style: editar cita y cambiar estado del lead en una operacion).

Tests aqui son del SCHEMA Pydantic (sin DB) — verifican que los campos
quedan registrados y no son silenciosamente droppeados.
"""
import pytest


class TestContactoUpdateSchema:
    """V070.97 — ContactoUpdate debe aceptar todos los campos que CREATE."""

    def test_acepta_nuevo_estado_id(self):
        """Bug B raiz: este campo se ignoraba silenciosamente en PATCH."""
        from app.routers.contactos import ContactoUpdate
        upd = ContactoUpdate(nuevo_estado_id=42)
        assert upd.nuevo_estado_id == 42

    def test_acepta_duracion_minutos(self):
        from app.routers.contactos import ContactoUpdate
        upd = ContactoUpdate(duracion_minutos=30)
        assert upd.duracion_minutos == 30

    def test_acepta_proxima_accion(self):
        from app.routers.contactos import ContactoUpdate
        upd = ContactoUpdate(proxima_accion="llamar manana")
        assert upd.proxima_accion == "llamar manana"

    def test_acepta_fecha_proxima_accion(self):
        from app.routers.contactos import ContactoUpdate
        upd = ContactoUpdate(fecha_proxima_accion="2026-05-20T09:00:00")
        assert upd.fecha_proxima_accion == "2026-05-20T09:00:00"

    def test_acepta_tipo_cita(self):
        from app.routers.contactos import ContactoUpdate
        upd = ContactoUpdate(tipo_cita="presencial")
        assert upd.tipo_cita == "presencial"

    def test_acepta_url_reunion(self):
        from app.routers.contactos import ContactoCreate, ContactoUpdate
        from app.routers.agenda import ContactoIn
        upd = ContactoUpdate(url_reunion="https://meet.google.com/abc-defg-hij")
        assert upd.url_reunion == "https://meet.google.com/abc-defg-hij"

        cre = ContactoCreate(url_reunion="https://zoom.us/j/123456789")
        assert cre.url_reunion == "https://zoom.us/j/123456789"

        cin = ContactoIn(url_reunion="https://teams.microsoft.com/l/meetup-join/xyz")
        assert cin.url_reunion == "https://teams.microsoft.com/l/meetup-join/xyz"

    def test_payload_combinado_cita_y_estado(self):
        """Caso real: editar una cita y cambiar el estado del lead a 'Calificado'
        en la misma operacion. Antes el estado se ignoraba silenciosamente."""
        from app.routers.contactos import ContactoUpdate
        upd = ContactoUpdate(
            tipo_contacto="presencial",
            resultado="cita_agendada",
            fecha_cita="2026-05-20T15:00:00",
            cita_estado_id=1,
            nuevo_estado_id=5,
            duracion_minutos=60,
            notas="Cliente acepto la reunion.",
        )
        assert upd.nuevo_estado_id == 5
        assert upd.cita_estado_id == 1
        assert upd.duracion_minutos == 60
        assert upd.fecha_cita == "2026-05-20T15:00:00"

    def test_payload_solo_nuevo_estado_id_es_valido(self):
        """Caso edge: el usuario solo quiere cambiar el estado del lead
        sin modificar el contacto. Debe ser valido."""
        from app.routers.contactos import ContactoUpdate
        upd = ContactoUpdate(nuevo_estado_id=3)
        # Todos los demas campos deben quedar None.
        assert upd.tipo_contacto is None
        assert upd.resultado is None
        assert upd.fecha_cita is None
        assert upd.cita_estado_id is None
        assert upd.nuevo_estado_id == 3


# ── V096.8 — Reset de recordatorios al reprogramar ────────────────────────

@pytest.mark.regression
def test_update_contacto_con_fecha_cita_dispara_delete_recordatorios():
    """V096.8 — Bug ID: visto en vivo en prod 2026-06-24 sobre contacto 2822.

    Cuando un asesor reprograma una cita cuyo recordatorio ya se envio (o
    quedo marcado como 'sin_telefono'), el flag en crm.recordatorios_enviados
    sigue ahi y el query del polling lo filtra → el nuevo recordatorio
    nunca sale.

    Esta regresion verifica que el PATCH ejecuta el DELETE de la tabla de
    recordatorios cuando se pasa fecha_cita.
    """
    from unittest.mock import MagicMock, patch
    from app.routers.contactos import update_contacto, ContactoUpdate
    from app.auth.schemas import TokenData

    cur = MagicMock()
    # 1ra fetchone(): RETURNING del UPDATE — devolvemos id para que no falle 404.
    cur.fetchone.return_value = {"id": 99}
    cur.rowcount = 1

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@test", role="admin", first_name="Admin", last_name=""
    )

    with patch("app.routers.contactos.get_db", return_value=db_cm), \
         patch("app.routers.agenda._has_cita_estado_column", return_value=True):
        update_contacto(
            lead_id=1, contacto_id=99,
            data=ContactoUpdate(fecha_cita="2026-06-25T15:00:00"),
            current_user=user,
        )

    # Buscar entre todas las llamadas a execute() una con DELETE sobre
    # recordatorios_enviados WHERE contacto_id = 99.
    delete_calls = [
        call for call in cur.execute.call_args_list
        if "DELETE FROM crm.recordatorios_enviados" in str(call[0][0])
        and "contacto_id = %s" in str(call[0][0])
    ]
    assert len(delete_calls) == 1, (
        f"PATCH con fecha_cita debe ejecutar UN DELETE en recordatorios_enviados, "
        f"hubo {len(delete_calls)}: {delete_calls}"
    )
    # Verifica que el parametro del DELETE es el contacto_id correcto.
    assert delete_calls[0][0][1] == (99,)


def test_update_contacto_sin_fecha_cita_NO_dispara_delete_recordatorios():
    """V096.8 — backwards-compat: PATCH sin fecha_cita (ej: solo cambia notas
    o estado) NO debe tocar la tabla recordatorios_enviados. Sino borrariamos
    flags validos cada vez que se edita cualquier campo."""
    from unittest.mock import MagicMock, patch
    from app.routers.contactos import update_contacto, ContactoUpdate
    from app.auth.schemas import TokenData

    cur = MagicMock()
    cur.fetchone.return_value = {"id": 99}

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    user = TokenData(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@test", role="admin", first_name="Admin", last_name=""
    )

    with patch("app.routers.contactos.get_db", return_value=db_cm), \
         patch("app.routers.agenda._has_cita_estado_column", return_value=True):
        update_contacto(
            lead_id=1, contacto_id=99,
            data=ContactoUpdate(notas="solo edito notas"),
            current_user=user,
        )

    delete_calls = [
        call for call in cur.execute.call_args_list
        if "DELETE FROM crm.recordatorios_enviados" in str(call[0][0])
    ]
    assert len(delete_calls) == 0, (
        f"PATCH sin fecha_cita NO debe tocar recordatorios_enviados, "
        f"hubo {len(delete_calls)}: {delete_calls}"
    )


def test_payload_vacio_no_se_rechaza_a_nivel_pydantic():
    """Pydantic acepta payload vacio. El rechazo 400 lo hace el handler
    cuando ni hay campos del contacto ni nuevo_estado_id."""
    from app.routers.contactos import ContactoUpdate
    upd = ContactoUpdate()
    assert upd.nuevo_estado_id is None
    assert upd.tipo_contacto is None


# ── Tests de permisos de asesor en citas vs no-citas ───────────────────────

def test_asesor_sin_permiso_general_PUEDE_editar_cita():
    """Un asesor sin el flag 'asesor_can_edit' PUEDE editar una cita
    (para cambiar estado de cita, reprogramar, etc.)."""
    from unittest.mock import MagicMock, patch
    from app.routers.contactos import update_contacto, ContactoUpdate
    from app.auth.schemas import TokenData

    cur = MagicMock()
    # 1. SELECT contacto existente (es cita)
    # 2. SELECT app_settings contact_permissions
    # 3. UPDATE crm.contactos RETURNING id
    cur.fetchone.side_effect = [
        {
            "id": 10,
            "tipo_contacto": "whatsapp",
            "resultado": "cita_agendada",
            "notas": "Cita en oficina",
            "fecha_cita": "2026-08-11 10:00:00+00",
            "tipo_cita": "Cita oficina Bustamante",
            "cita_estado_id": 1,
        },
        {"value": {"asesor_can_edit": False, "asesor_can_delete": False}},
        {"id": 10},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    asesor_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000002",
        email="asesor@test", role="asesor", first_name="Asesor", last_name=""
    )

    with patch("app.routers.contactos.get_db", return_value=db_cm), \
         patch("app.routers.agenda._has_cita_estado_column", return_value=True):
        res = update_contacto(
            lead_id=1,
            contacto_id=10,
            data=ContactoUpdate(cita_estado_id=3, notas="Reprogramada por solicitud"),
            current_user=asesor_user,
        )

    assert res == {"message": "Contacto actualizado"}


def test_asesor_sin_permiso_general_NO_puede_editar_contacto_regular():
    """Un asesor sin el flag 'asesor_can_edit' recibe 403 al intentar
    editar un contacto que NO es cita (ej. llamada o nota regular)."""
    from unittest.mock import MagicMock, patch
    from fastapi import HTTPException
    from app.routers.contactos import update_contacto, ContactoUpdate
    from app.auth.schemas import TokenData

    cur = MagicMock()
    # 1. SELECT contacto existente (es llamada regular)
    # 2. SELECT app_settings contact_permissions
    cur.fetchone.side_effect = [
        {
            "id": 11,
            "tipo_contacto": "llamada",
            "resultado": "no_contesta",
            "notas": "Llamada sin respuesta",
            "fecha_cita": None,
            "tipo_cita": None,
            "cita_estado_id": None,
        },
        {"value": {"asesor_can_edit": False, "asesor_can_delete": False}},
    ]

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    db_cm = MagicMock()
    db_cm.__enter__.return_value = conn

    asesor_user = TokenData(
        user_id="00000000-0000-0000-0000-000000000002",
        email="asesor@test", role="asesor", first_name="Asesor", last_name=""
    )

    with patch("app.routers.contactos.get_db", return_value=db_cm), \
         patch("app.routers.agenda._has_cita_estado_column", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            update_contacto(
                lead_id=1,
                contacto_id=11,
                data=ContactoUpdate(notas="Cambio notas"),
                current_user=asesor_user,
            )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "No tienes permiso para editar contactos"


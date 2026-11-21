"""Servicio de cliente Meta Cloud API para WhatsApp.

V070.71 (Bundle C.2 — split de whatsapp.py).

Centraliza la resolucion de:
  - access_token a usar para enviar (multi-WABA + fallback legacy).
  - headers HTTP para Meta Graph API.
  - URL del endpoint de envio segun phone_number_id.
  - numero desde el que enviar (catalogo wa_numbers + reglas de prioridad).

API publica:
  - META_GRAPH_BASE: constante con la URL base de la Graph API.
  - resolve_access_token(phone_number_id=None) -> str
  - meta_headers(phone_number_id=None) -> dict
  - meta_send_url(phone_number_id=None) -> str
  - resolve_sending_number(wa_number_id, to_phone, advisor_default_wa_number_id)
    -> (wa_number_id_final, phone_number_id_meta)

Diseno:
- Las funciones levantan HTTPException con codigos y mensajes claros
  cuando faltan credenciales o config — el router las propaga al usuario.
- Cero estado mutable — todas son funciones puras (modulo nivel).
- Imports lazy de wa_babas_service / wa_numbers_service para evitar
  circulos durante el boot.

Strangler Pattern: whatsapp.py mantiene wrappers privados
(_resolve_access_token, _meta_headers, _meta_send_url, _resolve_sending_number)
que delegan aqui. Los call sites internos no cambian.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from app.config import settings

# Version de Graph API. Tocar aqui propaga a todos los call sites.
META_GRAPH_BASE = "https://graph.facebook.com/v20.0"


def resolve_access_token(phone_number_id: Optional[str] = None) -> str:
    """Devuelve el access_token a usar para un envio.

    Prioridad:
      1. Access token de la WABA del numero (multi-WABA, V034).
      2. Access token de la WABA default activa.
      3. Access token del env (legacy — primer arranque antes de V034 seed).

    Si no hay ninguno disponible, levanta HTTPException 500.
    """
    from app.services import wa_babas_service

    if phone_number_id:
        baba = wa_babas_service.get_baba_for_phone(phone_number_id)
        if baba:
            token = wa_babas_service.get_access_token(baba)
            if token:
                return token

    default_baba = wa_babas_service.get_default_baba()
    if default_baba:
        token = wa_babas_service.get_access_token(default_baba)
        if token:
            return token

    if settings.meta_wa_access_token:
        return settings.meta_wa_access_token

    raise HTTPException(
        500,
        "Access token de WhatsApp no disponible. Registra una WABA desde "
        "Configuracion > WhatsApp > Cuentas Empresariales.",
    )


def meta_headers(phone_number_id: Optional[str] = None) -> dict:
    """Headers HTTP para llamadas a Meta Graph API."""
    return {
        "Authorization": f"Bearer {resolve_access_token(phone_number_id)}",
        "Content-Type":  "application/json",
    }


def meta_send_url(phone_number_id: Optional[str] = None) -> str:
    """URL para enviar mensajes desde un phone_number_id concreto.

    Si phone_number_id es None, usa settings.meta_wa_phone_number_id
    (legacy/fallback). Si tampoco hay env var → HTTPException 500.
    """
    pid = phone_number_id or settings.meta_wa_phone_number_id
    if not pid:
        raise HTTPException(500, "phone_number_id no disponible (ni parametro ni env)")
    return f"{META_GRAPH_BASE}/{pid}/messages"


def resolve_sending_number(
    wa_number_id: Optional[int],
    to_phone: Optional[str] = None,
    advisor_default_wa_number_id: Optional[int] = None,
) -> tuple[Optional[int], Optional[str]]:
    """Dado un wa_number_id opcional y un telefono destino, resuelve la
    pareja (wa_number_id_final, phone_number_id_meta) para el envio.

    Prioridad:
      1. wa_number_id explicito del payload.
      2. Numero de la conversacion existente con to_phone.
      3. Default del asesor (auth.users.default_wa_number_id — V035).
      4. Default activo del catalogo wa_numbers.
      5. settings.meta_wa_phone_number_id (legacy).

    Si ninguna fuente da un numero valido → HTTPException 409 con codigo
    estable WHATSAPP_NOT_CONFIGURED para que el frontend muestre el
    empty state de onboarding (no un alert generico).
    """
    from app.database import get_db
    from app.services.wa_numbers_service import get_by_id, get_default

    if wa_number_id:
        num = get_by_id(wa_number_id)
        if num and num["activo"]:
            return num["id"], num["phone_number_id"]
        if num and not num["activo"]:
            raise HTTPException(400, f"La linea {num['display_name']} esta inactiva")
        raise HTTPException(404, "wa_number_id no existe")

    if to_phone:
        from psycopg2.extras import RealDictCursor
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT n.id, n.phone_number_id, n.activo
                      FROM crm.wa_conversations c
                      JOIN crm.wa_numbers      n ON n.id = c.wa_number_id
                     WHERE c.wa_phone = %s
                    """,
                    (to_phone,),
                )
                row = cur.fetchone()
                if row and row["activo"]:
                    return row["id"], row["phone_number_id"]

    if advisor_default_wa_number_id:
        num = get_by_id(advisor_default_wa_number_id)
        if num and num["activo"]:
            return num["id"], num["phone_number_id"]

    default_num = get_default()
    if default_num:
        return default_num["id"], default_num["phone_number_id"]

    env_pid = settings.meta_wa_phone_number_id
    if env_pid:
        return None, env_pid

    raise HTTPException(
        status_code=409,
        detail={
            "code":    "WHATSAPP_NOT_CONFIGURED",
            "message": (
                "WhatsApp Business no esta configurado. Pide al admin "
                "que conecte una WABA en Integraciones."
            ),
        },
    )

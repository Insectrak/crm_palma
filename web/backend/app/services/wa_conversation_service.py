"""Servicio de lifecycle de conversaciones WhatsApp.

V070.71 (Bundle C.3 — split de whatsapp.py).

Centraliza:
  - get_or_create_conversation(): upsert idempotente de crm.wa_conversations.
  - release_lead_if_terminal(): cuando llega mensaje a una conv enlazada a
    un lead en estado terminal (Ganado/Perdido/No interesado), libera la
    atadura para que el siguiente mensaje sea tratado como caso nuevo.

API publica:
  - TERMINAL_LEAD_STATES: tupla de estados que disparan la liberacion.
  - get_or_create_conversation(cur, wa_phone, contact_name, wa_number_id) -> int
  - release_lead_if_terminal(cur, conversation_id) -> bool

Diseno:
- Las funciones reciben el cursor del caller (mismo tx con el webhook
  caller — un rollback del webhook tambien borra el upsert).
- Cero side effects fuera del cursor recibido. NO abren conexiones nuevas.
- Logging informativo cuando hay liberacion (decision de negocio relevante).

Strangler Pattern: whatsapp.py mantiene wrappers privados que delegan
aqui — los call sites internos del router no cambian.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Estados terminales — un lead aqui significa que el caso esta cerrado.
# Si llega un mensaje nuevo a una conversacion atada a un lead terminal,
# lo tratamos como un caso nuevo (IA clasifica + rotacion crea lead nuevo).
TERMINAL_LEAD_STATES = ('Ganado', 'Perdido', 'No interesado')


def get_or_create_conversation(
    cur,
    wa_phone: str,
    contact_name: Optional[str],
    wa_number_id: Optional[int] = None,
) -> int:
    """Devuelve conversation_id, creandola si no existe (upsert idempotente).

    `wa_number_id` linkea la conversacion al numero propio (linea) que la
    recibio. En conversaciones existentes sin numero asignado (pre-V033)
    lo setea al primer uso (COALESCE).
    """
    cur.execute(
        """
        INSERT INTO crm.wa_conversations (wa_phone, contact_name, wa_number_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (wa_phone) DO UPDATE SET
            contact_name = COALESCE(EXCLUDED.contact_name, crm.wa_conversations.contact_name),
            wa_number_id = COALESCE(crm.wa_conversations.wa_number_id, EXCLUDED.wa_number_id)
        RETURNING id
        """,
        (wa_phone, contact_name, wa_number_id),
    )
    return cur.fetchone()[0]


def release_lead_if_terminal(cur, conversation_id: int) -> bool:
    """Si la conversacion esta enlazada a un lead en estado terminal, libera
    la atadura — el proximo CAS encolara IA y wa_router_service creara un
    lead nuevo via rotacion.

    Marca el caso anterior como cerrado en `crm.wa_conversation_leads` para
    que el chat muestre 'Caso 1 / 2 / 3'.

    Returns:
        True si hubo liberacion (habia un caso terminal abierto); False
        en caso contrario (no hay lead enlazado o esta en estado activo).
    """
    cur.execute(
        """
        SELECT c.lead_id
          FROM crm.wa_conversations c
          LEFT JOIN crm.leads l         ON l.id = c.lead_id
          LEFT JOIN crm.estados_lead e  ON e.id = l.estado_id
         WHERE c.id = %s
           AND c.lead_id IS NOT NULL
           AND COALESCE(e.nombre, '') = ANY(%s)
        """,
        (conversation_id, list(TERMINAL_LEAD_STATES)),
    )
    row = cur.fetchone()
    if not row:
        return False
    prior_lead_id = row[0]

    # Cierra el caso en el historial (no-op si V025 aun no aplicado).
    try:
        cur.execute(
            """
            UPDATE crm.wa_conversation_leads
               SET closed_at = NOW()
             WHERE conversation_id = %s
               AND lead_id = %s
               AND closed_at IS NULL
            """,
            (conversation_id, prior_lead_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "wa: no se pudo cerrar wa_conversation_leads conv=%s lead=%s: %s",
            conversation_id, prior_lead_id, exc,
        )

    cur.execute(
        """
        UPDATE crm.wa_conversations
           SET lead_id                 = NULL,
               classification_status   = 'pending',
               classification_attempts = 0,
               classified_at           = NULL
         WHERE id = %s
        """,
        (conversation_id,),
    )

    logger.info(
        "wa: conv=%s caso anterior lead=%s terminal — liberado para nueva clasificacion",
        conversation_id, prior_lead_id,
    )
    return True

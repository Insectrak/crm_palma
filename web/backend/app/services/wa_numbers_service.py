"""
wa_numbers_service.py — Gestion de numeros propios de WhatsApp Business.

Responsabilidad:
  - Resolver phone_number_id (Meta) → wa_number_id (nuestro catalogo)
  - Auto-registrar numeros nuevos cuando llega un webhook de un numero
    no conocido (defensivo: no perdemos mensajes)
  - Entregar el numero default para /send sin contexto

Clean Code / SOLID:
  - SRP: solo gestiona el catalogo de numeros. No enruta mensajes ni
    envia.
  - Cache LRU basico en memoria por (phone_number_id) — el catalogo
    cambia raramente (altas manuales del admin), no tiene sentido pegar
    PG en cada webhook.
"""
from __future__ import annotations

import logging
from typing import Optional

from psycopg2.extras import RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)

# Cache in-memory: phone_number_id → dict(id, display_name, ...).
# Se invalida en altas/ediciones desde el CRUD.
_CACHE: dict[str, dict] = {}


def invalidate_cache() -> None:
    """Llamar tras INSERT/UPDATE/DELETE en crm.wa_numbers."""
    _CACHE.clear()


def _row_to_dict(row) -> dict:
    return {
        "id":              row["id"],
        "phone_number_id": row["phone_number_id"],
        "display_phone":   row["display_phone"],
        "display_name":    row["display_name"],
        "waba_id":         row["waba_id"],
        "waba_id_ref":     row.get("waba_id_ref") if hasattr(row, "get") else row["waba_id_ref"],
        "is_default":      row["is_default"],
        "activo":          row["activo"],
    }


def get_by_phone_number_id(phone_number_id: str) -> Optional[dict]:
    """Busca un numero por su ID de Meta. Retorna dict o None."""
    if not phone_number_id:
        return None
    cached = _CACHE.get(phone_number_id)
    if cached is not None:
        return cached

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, phone_number_id, display_phone, display_name,
                       waba_id, is_default, activo, waba_id_ref
                FROM crm.wa_numbers
                WHERE phone_number_id = %s
                """,
                (phone_number_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    data = _row_to_dict(row)
    _CACHE[phone_number_id] = data
    return data


def get_by_id(wa_number_id: int) -> Optional[dict]:
    """Busca un numero por su PK interno."""
    if not wa_number_id:
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, phone_number_id, display_phone, display_name,
                       waba_id, is_default, activo, waba_id_ref
                FROM crm.wa_numbers
                WHERE id = %s
                """,
                (wa_number_id,),
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_default() -> Optional[dict]:
    """Retorna el numero marcado is_default=TRUE. Fallback: primero activo."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, phone_number_id, display_phone, display_name,
                       waba_id, is_default, activo, waba_id_ref
                FROM crm.wa_numbers
                WHERE activo = TRUE
                ORDER BY is_default DESC, id ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    return _row_to_dict(row) if row else None


def has_sending_capability() -> bool:
    """True si existe >=1 numero activo con phone_number_id valido (puede enviar).

    Es la fuente unica de verdad que consume el preflight de los endpoints
    de envio y el /status del frontend — SRP estricto: la pregunta
    'esta el sistema configurado para mandar WhatsApp?' solo se contesta
    aqui. Ningun otro modulo replica esta logica.

    Diseño:
      - Query ligero (EXISTS) — usable en hot path sin penalizar.
      - No retorna detalles del numero (eso es responsabilidad de get_default).
      - Booleano puro → no expone metadata sensible al caller.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM crm.wa_numbers
                    WHERE activo = TRUE
                      AND phone_number_id IS NOT NULL
                      AND phone_number_id <> ''
                )
                """
            )
            return bool(cur.fetchone()[0])


def list_all(only_active: bool = False) -> list[dict]:
    """Lista todos los numeros propios (para UI de admin o selector)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if only_active:
                cur.execute(
                    """
                    SELECT n.id, n.phone_number_id, n.display_phone, n.display_name,
                           n.waba_id, n.is_default, n.activo, n.waba_id_ref,
                           b.display_name AS waba_display_name
                    FROM crm.wa_numbers n
                    LEFT JOIN crm.wa_babas b ON b.id = n.waba_id_ref
                    WHERE n.activo = TRUE
                    ORDER BY n.is_default DESC, n.display_name ASC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT n.id, n.phone_number_id, n.display_phone, n.display_name,
                           n.waba_id, n.is_default, n.activo, n.waba_id_ref,
                           b.display_name AS waba_display_name
                    FROM crm.wa_numbers n
                    LEFT JOIN crm.wa_babas b ON b.id = n.waba_id_ref
                    ORDER BY n.is_default DESC, n.activo DESC, n.display_name ASC
                    """
                )
            results = []
            for r in cur.fetchall():
                d = _row_to_dict(r)
                d["waba_display_name"] = r.get("waba_display_name") if hasattr(r, "get") else r["waba_display_name"]
                results.append(d)
            return results


def get_or_register(
    phone_number_id: str,
    display_phone: Optional[str] = None,
) -> Optional[dict]:
    """Resuelve phone_number_id → wa_number. Si no existe, lo auto-registra
    con un nombre provisional para que el admin lo rename despues.

    Usado desde el webhook: un mensaje de un numero no registrado NO se
    pierde — se crea el numero sobre la marcha y se flaguea como
    activo=FALSE para que el admin lo revise antes de usarlo para envios.
    """
    if not phone_number_id:
        return None
    existing = get_by_phone_number_id(phone_number_id)
    if existing:
        return existing

    # Auto-registro con activo=FALSE para que admin lo revise
    provisional_name = f"Linea {display_phone or phone_number_id[-6:]}"
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm.wa_numbers
                        (phone_number_id, display_phone, display_name,
                         is_default, activo)
                    VALUES (%s, %s, %s, FALSE, FALSE)
                    ON CONFLICT (phone_number_id) DO NOTHING
                    RETURNING id
                    """,
                    (phone_number_id, display_phone, provisional_name),
                )
                cur.fetchone()
            conn.commit()
        invalidate_cache()
        logger.warning(
            "wa_numbers: auto-registrado numero desconocido phone_id=%s "
            "como inactivo — admin debe revisarlo en /configuracion/numeros",
            phone_number_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("wa_numbers: fallo auto-registro de %s: %s", phone_number_id, exc)
        return None

    return get_by_phone_number_id(phone_number_id)


def set_default(wa_number_id: int) -> bool:
    """Marca un numero como default (desmarca los demas). Atomico."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE crm.wa_numbers SET is_default = FALSE "
                    "WHERE is_default = TRUE AND id <> %s",
                    (wa_number_id,),
                )
                cur.execute(
                    "UPDATE crm.wa_numbers SET is_default = TRUE, updated_at = NOW() "
                    "WHERE id = %s",
                    (wa_number_id,),
                )
                updated = cur.rowcount
            conn.commit()
        invalidate_cache()
        return updated > 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("wa_numbers: fallo set_default(%s): %s", wa_number_id, exc)
        return False

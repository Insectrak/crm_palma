"""
field_security_service.py — Field-Level Security (ADR-0011 Sprint 5).

Aproximacion al modelo patrón estándar FLS:
- Cada rol puede tener visibilidad/edicion restringida a campos especificos
  de un objeto.
- El catalogo de fields enmascarables vive en app.auth.field_catalog.
- La key en permissions JSONB: `field.<obj>.<field>.<read|edit>` = bool.
- Si la key NO esta presente -> default TRUE (compat: no rompe roles
  existentes).

Helpers expuestos:
  - is_field_readable(user, obj, field) -> bool
  - is_field_editable(user, obj, field) -> bool
  - mask_record(user, obj, record) -> dict       # remueve fields no readable
  - mask_records(user, obj, records) -> list
  - validate_update_allowed(user, obj, payload) -> list[str]
        # devuelve lista de fields que el usuario intenta tocar sin permiso

NO mockea ni cachea. Cada llamada es O(1) sobre el dict de permissions.
Pensado para usarse en routers despues de fetch (mask) y antes de update
(validate).
"""
from __future__ import annotations

from typing import Any, Optional

from app.auth.field_catalog import FIELD_CATALOG, is_field_in_catalog
from app.auth.schemas import TokenData
from app.constants import Role


# ── Helpers de lectura ──────────────────────────────────────────────────────

def _bypass(user: Optional[TokenData]) -> bool:
    """Admin legacy o flag _all = bypass total de FLS."""
    if user is None:
        return False
    if user.role == Role.ADMIN.value:
        return True
    perms = user.permissions or {}
    return perms.get("_all") is True


def is_field_readable(user: Optional[TokenData], obj: str, field: str) -> bool:
    """True si el usuario puede LEER el field. Default true (compat).

    Si el field no esta en el catalogo, devuelve True (no es enmascarable)."""
    if not is_field_in_catalog(obj, field):
        return True
    if _bypass(user):
        return True
    perms = (user.permissions if user else {}) or {}
    return perms.get(f"field.{obj}.{field}.read", True) is not False


def is_field_editable(user: Optional[TokenData], obj: str, field: str) -> bool:
    """True si el usuario puede MODIFICAR el field. Default true (compat).

    Implica is_field_readable: si no podes leer, no podes editar (defensa).
    Si el field no esta en el catalogo, devuelve True."""
    if not is_field_in_catalog(obj, field):
        return True
    if _bypass(user):
        return True
    if not is_field_readable(user, obj, field):
        return False
    perms = (user.permissions if user else {}) or {}
    return perms.get(f"field.{obj}.{field}.edit", True) is not False


# ── Masking ─────────────────────────────────────────────────────────────────

def mask_record(
    user: Optional[TokenData],
    obj: str,
    record: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Devuelve `record` con los fields no readables removidos.

    None in -> None out (idempotente con respuestas vacias)."""
    if record is None:
        return None
    if _bypass(user):
        return record
    catalog_fields = FIELD_CATALOG.get(obj, [])
    if not catalog_fields:
        return record
    out = dict(record)
    for field in catalog_fields:
        if not is_field_readable(user, obj, field):
            out.pop(field, None)
    return out


def mask_records(
    user: Optional[TokenData],
    obj: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aplica mask_record a cada elemento. Mantiene orden."""
    if not records:
        return records
    if _bypass(user):
        return records
    return [mask_record(user, obj, r) for r in records]


# ── Validacion de updates ───────────────────────────────────────────────────

def validate_update_allowed(
    user: Optional[TokenData],
    obj: str,
    payload: dict[str, Any],
) -> list[str]:
    """Devuelve la lista de fields del payload que el usuario NO puede editar.

    Lista vacia = update permitido. El router debe rechazar con 403 si
    devuelve algun field bloqueado.

    NOTA: si payload trae fields que NO estan en el catalogo (ej. lead.id,
    lead.created_at), NO los reporta — solo evaluamos lo enmascarable."""
    if _bypass(user):
        return []
    catalog_fields = set(FIELD_CATALOG.get(obj, []))
    if not catalog_fields:
        return []
    blocked = []
    for field in payload.keys():
        if field in catalog_fields and not is_field_editable(user, obj, field):
            blocked.append(field)
    return blocked

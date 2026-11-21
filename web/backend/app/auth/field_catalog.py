"""
field_catalog.py — catalogo de fields auditables para Field-Level Security
(ADR-0011 Sprint 5).

Define que campos de cada objeto del CRM son enmascarables/restringibles
a nivel de rol. Por defecto: si un campo NO esta en este catalogo, NO
es enmascarable (acceso libre segun el permission key del objeto).

Patron inspirado en patrón estándar Field-Level Security:
- read=false  → el field no se incluye en respuestas API
- edit=false  → el field se devuelve pero PATCH/PUT lo rechazan

Convencion de keys en permissions JSONB:
    field.<object>.<fieldname>.read = boolean
    field.<object>.<fieldname>.edit = boolean

Si la key NO esta presente, default = TRUE (backward compat).
"""
from __future__ import annotations

# Mapeo: object -> lista de fields enmascarables.
# El catalogo se sincroniza con el del frontend (lib/fieldCatalog.js).
# Para agregar un field: aparecer aqui + en el del frontend + el endpoint
# que devuelve el objeto debe enmascarar via field_security_service.
FIELD_CATALOG: dict[str, list[str]] = {
    "leads": [
        "telefono",
        "email",
        "observaciones",
        "presupuesto",
        "tipo_cierre",
        "segunda_voz",
        "motivo_perdida",
        "motivo_perdida_otro",
        "fecha_proxima_gestion",
    ],
    # Futuras extensiones por objeto:
    # "contactos": ["contenido"],
    # "eventos_calendario": ["notas"],
}


def is_field_in_catalog(obj: str, field: str) -> bool:
    """True si el field es enmascarable. False = acceso siempre libre."""
    return field in FIELD_CATALOG.get(obj, [])

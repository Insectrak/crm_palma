"""PII utils — helpers para enmascarar datos personales antes de loguear.

Ley 29733 PE exige minimizacion del dato. Logs en INFO no deben llevar PII
completa (telefono, email, DNI) — solo lo suficiente para diagnosticar
incidentes. Esta es la unica fuente de verdad para el formato de masking.

Convencion:
    mask_phone('+51987654321')   -> '***4321'
    mask_email('juan@test.com')  -> 'j**n@test.com'
    mask_dni('40123456')         -> '****3456'

Reglas:
- Devolver string en TODOS los casos (None / vacio → 'none').
- Conservar los ultimos 4 chars (suficiente para correlacionar logs).
- NO loguear el valor real, ni siquiera en DEBUG (regla de equipo).
"""
from __future__ import annotations

from typing import Optional


def mask_phone(value: Optional[str]) -> str:
    """Telefono → '***1234' (ultimos 4 digitos visibles).

    Casos:
        None / ''     → 'none'
        '987654321'   → '***4321'
        '+51987654321'-> '***4321'
        '+51 987 654 321' → '***4321' (ignora separadores al contar)
        '99'          → '99' (muy corto: no enmascarar, ya es ambiguo)
    """
    if not value:
        return "none"
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) <= 4:
        return digits or "none"
    return f"***{digits[-4:]}"


def mask_email(value: Optional[str]) -> str:
    """Email → 'j**n@dominio.com' (primer/ultimo char del local, dominio visible)."""
    if not value:
        return "none"
    s = str(value).strip()
    if "@" not in s:
        return "***"
    local, _, domain = s.partition("@")
    if len(local) <= 2:
        masked_local = local[0] + "*" if local else "*"
    else:
        masked_local = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{masked_local}@{domain}"


def mask_dni(value: Optional[str]) -> str:
    """DNI → '****3456' (ultimos 4 visibles). DNI peruano son 8 digitos."""
    if not value:
        return "none"
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) <= 4:
        return digits or "none"
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"

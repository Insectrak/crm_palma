"""
Constantes del dominio CRM.

Centraliza roles de usuario y nombres de estados de lead para evitar
magic strings repartidas por routers, queries y validaciones.
"""
from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    ASESOR = "asesor"

    @classmethod
    def values(cls) -> list[str]:
        return [r.value for r in cls]


class LeadEstado(str, Enum):
    """Nombres canónicos de los estados en `crm.estados_lead`.

    Si el cliente renombra un estado en la UI, cambiar también el valor aquí
    para mantener el dashboard funcionando.
    """
    NUEVO = "Nuevo"
    CONTACTADO = "Contactado"
    CALIFICADO = "Calificado"
    EN_NEGOCIACION = "En negociación"
    GANADO = "Ganado"
    PERDIDO = "Perdido"
    NO_INTERESADO = "No interesado"


# Sentinel para indicar que una reasignación no debe alterar el supervisor_id actual
KEEP_SUPERVISOR = object()

# Tope defensivo para operaciones masivas de reasignación
MAX_BULK_REASSIGN = 500


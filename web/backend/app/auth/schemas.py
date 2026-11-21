"""
Esquemas Pydantic para autenticación CRM.

Roles legacy: admin | supervisor | asesor (campo `role` text).
Roles custom (ADR-0011): configurables vía auth.roles + permisos JSONB.
"""
from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "asesor"
    user_id: str
    email: str
    nombre_completo: Optional[str] = None
    default_wa_number_id: Optional[int] = None
    # ADR-0011 — permisos efectivos del rol del usuario (snapshot al login)
    permissions: dict = Field(default_factory=dict)
    role_id: Optional[int] = None
    role_is_external: bool = False
    api_client_id: Optional[str] = None


class TokenData(BaseModel):
    """Datos decodificados del JWT. Disponible en todos los endpoints protegidos."""
    user_id: str   # UUID como string
    email: str
    role: str = "asesor"
    # ADR-0011 — sistema de permisos granulares
    permissions: dict = Field(default_factory=dict)
    role_id: Optional[int] = None
    role_is_external: bool = False
    api_client_id: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_active: bool
    # V094 — independiente de is_active. Si TRUE, el usuario no puede
    # iniciar sesion pero SIGUE visible en todas las listas operacionales.
    login_blocked: bool = False
    telefono: Optional[str] = None
    created_at: Optional[str] = None
    default_wa_number_id: Optional[int] = None
    default_wa_number_name: Optional[str] = None
    # ADR-0011 — Rol custom asociado (NULL si el usuario es solo legacy).
    # `role_name` es el label que la UI muestra en la badge cuando esta presente
    # (ej. "marketing" en lugar del role text legacy "asesor").
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    supervisor_jefe_id: Optional[str] = None
    supervisor_jefe_nombre: Optional[str] = None


class PermissionsRefreshResponse(BaseModel):
    """Respuesta del endpoint /auth/me/permissions (Live Permission Refresh).

    Devuelve el snapshot ACTUAL del rol del usuario (lectura directa de DB),
    no el del JWT. Permite al frontend rehidratar permisos sin re-login
    cuando un admin cambia el rol del usuario.

    CRITICAL: tambien devuelve un `access_token` nuevo con los permisos
    frescos embebidos. El frontend DEBE reemplazar su token en storage,
    si no las proximas requests al backend usaran el JWT viejo (stale)
    y los chequeos de FLS/check_permission daran resultados incorrectos
    (ej. el backend sigue devolviendo telefono enmascarable porque el
    JWT no tiene la key field.leads.telefono.read=false todavia).
    """
    access_token: str
    permissions: dict = Field(default_factory=dict)
    role: str
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    role_is_external: bool = False
    api_client_id: Optional[str] = None

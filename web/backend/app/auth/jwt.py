"""
JWT utilities para el CRM.
Token payload: sub=user_uuid, email, role
"""
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.auth.schemas import TokenData
from app.constants import Role

bearer_scheme = HTTPBearer()


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.access_token_expire_hours
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_token(token: str) -> TokenData:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str | None = payload.get("sub")
        email: str | None = payload.get("email")
        role: str = payload.get("role", Role.ASESOR.value)
        if not user_id or not email:
            raise exc
        # ADR-0011 — campos opcionales del sistema de roles+permisos.
        # Tokens emitidos antes de V078 no los traen → defaults seguros.
        return TokenData(
            user_id=user_id,
            email=email,
            role=role,
            permissions=payload.get("permissions") or {},
            role_id=payload.get("role_id"),
            role_is_external=bool(payload.get("role_is_external", False)),
            api_client_id=payload.get("api_client_id"),
        )
    except JWTError:
        raise exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenData:
    return verify_token(credentials.credentials)


def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere rol admin")
    return current_user


def require_supervisor_or_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role not in (Role.ADMIN, Role.SUPERVISOR) and getattr(current_user, "role_id", None) is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere rol supervisor o admin")
    return current_user


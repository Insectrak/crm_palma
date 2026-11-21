"""
Tests unitarios del módulo de JWT.
Verifica generación, verificación y dependencias de autorización.
"""
import pytest
from fastapi import HTTPException

from app.auth.jwt import (
    create_access_token,
    verify_token,
    require_admin,
    require_supervisor_or_admin,
)
from app.auth.schemas import TokenData


def _payload(role="asesor"):
    return {
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "user@test.local",
        "role": role,
    }


def test_create_and_verify_token_roundtrip():
    token = create_access_token(_payload(role="admin"))
    data = verify_token(token)
    assert data.user_id == "00000000-0000-0000-0000-000000000001"
    assert data.email == "user@test.local"
    assert data.role == "admin"


def test_verify_token_rejects_garbage():
    with pytest.raises(HTTPException) as exc:
        verify_token("not-a-real-token")
    assert exc.value.status_code == 401


def test_verify_token_rejects_missing_sub():
    from jose import jwt
    from app.config import settings
    token = jwt.encode(
        {"email": "x@y.com", "role": "asesor"},
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        verify_token(token)
    assert exc.value.status_code == 401


def test_require_admin_allows_admin():
    user = TokenData(user_id="u1", email="a@b.c", role="admin")
    assert require_admin(user) is user


def test_require_admin_rejects_asesor():
    user = TokenData(user_id="u1", email="a@b.c", role="asesor")
    with pytest.raises(HTTPException) as exc:
        require_admin(user)
    assert exc.value.status_code == 403


def test_require_admin_rejects_supervisor():
    user = TokenData(user_id="u1", email="a@b.c", role="supervisor")
    with pytest.raises(HTTPException) as exc:
        require_admin(user)
    assert exc.value.status_code == 403


def test_require_supervisor_or_admin_allows_both():
    admin = TokenData(user_id="u1", email="a@b.c", role="admin")
    sup = TokenData(user_id="u2", email="s@b.c", role="supervisor")
    assert require_supervisor_or_admin(admin) is admin
    assert require_supervisor_or_admin(sup) is sup


def test_require_supervisor_or_admin_rejects_asesor():
    user = TokenData(user_id="u1", email="a@b.c", role="asesor")
    with pytest.raises(HTTPException) as exc:
        require_supervisor_or_admin(user)
    assert exc.value.status_code == 403

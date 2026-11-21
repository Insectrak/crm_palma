"""
permission_audit.py — lectura del audit log de cambios de permisos
(ADR-0011 Sprint 4, Ley 29733 PE).

  GET /api/permission-audit
    Lista las entradas del audit log con filtros opcionales.
    Requiere permiso roles.manage (mismo nivel que gestionar los roles
    que el log auditea).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.auth.permissions import check_permission
from app.auth.schemas import TokenData
from app.services import permission_audit_service as audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/permission-audit", tags=["Permission Audit"])


@router.get("")
def list_audit(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    actor_user_id: Optional[str] = None,
    target_kind: Optional[str] = None,
    target_id: Optional[str] = None,
    action: Optional[str] = None,
    _: TokenData = Depends(check_permission("roles.manage")),
):
    """Lista entradas del audit log, mas recientes primero.

    Filtros opcionales:
      - actor_user_id: solo cambios hechos por este admin
      - target_kind: 'role' o 'user'
      - target_id:   role_id o user_id (en combinacion con target_kind)
      - action:      'role.create' | 'role.update_perms' | 'role.update_meta' |
                     'role.delete' | 'user.role_change'

    Respuesta:
      {
        "items": [ {id, actor_email, action, target_label, before_state,
                    after_state, ip_address, created_at, ...} ],
        "total": <int>
      }
    """
    return audit.list_recent(
        limit=limit,
        offset=offset,
        actor_user_id=actor_user_id,
        target_kind=target_kind,
        target_id=target_id,
        action=action,
    )

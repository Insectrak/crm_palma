"""
password_reset_audit_service.py — registra los envíos de correo de
restablecimiento de contraseña iniciados por un admin.

Tabla destino: auth.audit_password_resets (V087).

Cumplimiento Ley 29733 PE: el reseteo de credenciales es una operación
sensible sobre datos personales del usuario. La traza queda durante la
vida del tenant para responder a solicitudes ARCO o investigar abusos
del rol admin.

Fail-safe: si la escritura del audit falla NO propaga la excepción al
caller. El audit es secundario; nunca debe romper el envío del correo
ni la respuesta al admin.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request

from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    try:
        return request.client.host if request.client else None
    except Exception:
        return None


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    ua = request.headers.get("user-agent")
    return ua[:500] if ua else None


def record_send_reset_email(
    *,
    actor: TokenData,
    target_user_id: str,
    target_user_email: Optional[str],
    email_sent: bool,
    smtp_error: Optional[str],
    request: Optional[Request] = None,
) -> None:
    """Inserta una fila en auth.audit_password_resets.

    Args:
        actor: admin que inicio el envio (de get_current_user).
        target_user_id: UUID del user al que se le envio el reset.
        target_user_email: email del target (denormalizado para sobrevivir
            a un DELETE futuro del usuario).
        email_sent: True si el SMTP acepto el envio, False si fallo.
        smtp_error: motivo del fallo (truncado a 500 chars) o None.
        request: para extraer IP + User-Agent.
    """
    try:
        truncated_error = (smtp_error or "")[:500] if smtp_error else None
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.audit_password_resets (
                        target_user_id, target_user_email,
                        actor_user_id, actor_email,
                        email_sent, smtp_error,
                        ip_address, user_agent
                    ) VALUES (
                        %s::uuid, %s,
                        %s::uuid, %s,
                        %s, %s,
                        %s, %s
                    )
                    """,
                    (
                        target_user_id, target_user_email,
                        actor.user_id, actor.email,
                        email_sent, truncated_error,
                        _client_ip(request), _user_agent(request),
                    ),
                )
    except Exception as exc:
        logger.warning(
            "password_reset_audit: insert fallo (silenciado) target=%s sent=%s err=%s",
            target_user_id, email_sent, exc,
        )

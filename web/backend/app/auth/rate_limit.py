"""
Rate limiting para endpoints de autenticación.

Usa slowapi (wrapper de limits sobre Starlette) con un limiter global.
Las claves se calculan por IP del cliente — para evitar que un atacante
desde una sola IP pueda hacer brute force ilimitado contra /auth/login,
/auth/reset-password o la verificación de tokens de invitación.

Límites elegidos conservadores para un CRM interno (no es un sitio público
con miles de usuarios concurrentes):

- login:                10 intentos por minuto por IP
- reset-password:        5 intentos por minuto por IP
- invite verify:        20 intentos por minuto por IP
- accept-invite:         5 intentos por minuto por IP
- change-password:      10 intentos por minuto por usuario autenticado

En tests (DEMO_MODE) el limiter queda como no-op para no interferir con la
suite, ya que pytest puede disparar muchas requests en pocos ms.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


def _key_func(request):
    """Devuelve la IP del cliente; en demo_mode usa una clave constante para
    deshabilitar efectivamente el rate limit (los tests reusan la misma)."""
    if settings.demo_mode:
        return "demo-mode-no-limit"
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    # En demo_mode los límites son tan altos que nunca se alcanzan en tests.
    default_limits=[] if settings.demo_mode else ["200/minute"],
    enabled=not settings.demo_mode,
)

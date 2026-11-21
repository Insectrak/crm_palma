"""
Endpoint de setup inicial — solo funciona si no hay usuarios en la DB.
Similar al flujo de primer acceso de patrón premium / Chatwoot.

El `username` del payload se trata como `email` (es el identificador real
de login en auth.users). El nombre_completo es opcional; si viene, se
intenta partir en first_name + last_name por el primer espacio.
"""
import bcrypt
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.database import get_db

router = APIRouter(prefix="/api/setup", tags=["Setup"])


class SetupRequest(BaseModel):
    username: str  # se usa como email
    password: str
    nombre_completo: str = ""


def _split_nombre(nombre_completo: str) -> tuple[str, str]:
    """'Admin Palma' -> ('Admin', 'Palma'). Si no hay espacio, queda en first_name."""
    parts = (nombre_completo or "").strip().split(maxsplit=1)
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


@router.get("/status")
def setup_status():
    """Retorna si el sistema ya fue configurado (hay al menos un usuario)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM auth.users")
            count = cur.fetchone()[0]
    return {"needs_setup": count == 0}


@router.post("/create-admin", status_code=status.HTTP_201_CREATED)
def create_admin(data: SetupRequest):
    """Crea el primer usuario administrador. Solo funciona si no hay usuarios."""
    if len(data.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña debe tener al menos 6 caracteres"
        )

    first_name, last_name = _split_nombre(data.nombre_completo)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM auth.users")
            count = cur.fetchone()[0]
            if count > 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="El sistema ya fue configurado. Usa el login normal."
                )
            password_hash = bcrypt.hashpw(
                data.password.encode(), bcrypt.gensalt()
            ).decode()
            cur.execute(
                "INSERT INTO auth.users "
                "  (email, password_hash, first_name, last_name, role, is_active, is_verified) "
                "VALUES (%s, %s, %s, %s, 'admin', TRUE, TRUE)",
                (data.username, password_hash, first_name or None, last_name or None)
            )
        conn.commit()

    return {
        "message": (
            f"Administrador '{data.username}' creado correctamente. "
            "Ya puedes iniciar sesión."
        )
    }

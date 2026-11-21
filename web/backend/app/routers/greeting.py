"""
greeting.py — Saludo diario generado por Ollama (IA local).

Endpoint:
  GET /api/greeting   (requiere auth)

Un mensaje por día por usuario. Sin números ni porcentajes.
Contextualiza según el estado general de la cartera (sin cifras).
Cache en memoria: mismo usuario + misma fecha = mismo mensaje.
"""
import re
import random
import logging
from datetime import date

import httpx
from fastapi import APIRouter, Depends

from app.config import settings
from app.auth.jwt import get_current_user, TokenData
from app.database import get_db
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/greeting", tags=["greeting"])

_TIMEOUT = 5.0

# Cache diario: { "user_id:YYYY-MM-DD": "mensaje" }
_daily_cache: dict[str, str] = {}


def _strip_numbers(text: str) -> str:
    """Elimina cualquier número o porcentaje del texto generado."""
    text = re.sub(r'\d+[%]', '', text)
    text = re.sub(r'\d+', '', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def _cache_key(user_id: str) -> str:
    return f"{user_id}:{date.today().isoformat()}"


def _load_situation(user: TokenData) -> str:
    """Carga la situación general (sin cifras) para contextualizar."""
    flags = []
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if user.role == "asesor":
                    where = "l.asesor_id = %s::uuid"
                    params = [user.user_id]
                elif user.role == "supervisor":
                    where = (
                        "(l.asesor_id IN "
                        "(SELECT asesor_id FROM crm.equipos WHERE supervisor_id = %s::uuid AND activo = TRUE) "
                        "OR l.asesor_id = %s::uuid)"
                    )
                    params = [user.user_id, user.user_id]
                else:
                    where = "TRUE"
                    params = []

                # Leads sin contactar +48h
                cur.execute(
                    f"""SELECT COUNT(*) > 0 AS hay FROM crm.leads l
                        WHERE {where} AND l.activo = TRUE
                          AND NOT EXISTS (
                            SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id
                          )
                          AND l.created_at < NOW() - INTERVAL '48 hours'""",
                    params,
                )
                if cur.fetchone()["hay"]:
                    flags.append("tiene leads pendientes de primer contacto")

                # Citas hoy
                cur.execute(
                    f"""SELECT COUNT(*) > 0 AS hay FROM crm.contactos c
                        JOIN crm.leads l ON l.id = c.lead_id
                        WHERE {where} AND l.activo = TRUE
                          AND c.fecha_proxima_accion::date = CURRENT_DATE""",
                    params,
                )
                if cur.fetchone()["hay"]:
                    flags.append("tiene citas programadas para hoy")

                # Leads nuevos
                cur.execute(
                    f"""SELECT COUNT(*) > 0 AS hay FROM crm.leads l
                        JOIN crm.estados_lead e ON e.id = l.estado_id
                        WHERE {where} AND l.activo = TRUE AND e.nombre = 'Nuevo'""",
                    params,
                )
                if cur.fetchone()["hay"]:
                    flags.append("tiene leads nuevos en su cartera")

                # Sin asignar (admin/supervisor)
                if user.role in ("admin", "supervisor"):
                    cur.execute(
                        "SELECT COUNT(*) > 0 AS hay FROM crm.leads WHERE asesor_id IS NULL AND activo = TRUE"
                    )
                    if cur.fetchone()["hay"]:
                        flags.append("hay leads pendientes de asignar al equipo")

    except Exception as e:
        logger.warning("greeting context error: %s", e)

    return "; ".join(flags) if flags else "su cartera está al día"


def _build_prompt(user: TokenData, situation: str) -> str:
    role_es = {
        "admin": "administrador",
        "supervisor": "supervisor de equipo",
        "asesor": "asesor de ventas",
    }.get(user.role, user.role)

    return (
        f"Genera UNA frase motivacional corta (máximo 10 palabras) "
        f"para un {role_es} de una inmobiliaria en Perú.\n\n"
        f"Contexto: {situation}.\n\n"
        f"REGLAS:\n"
        f"- Máximo 10 palabras. Breve y directo.\n"
        f"- Castellano peruano (NO usar español de España).\n"
        f"- PROHIBIDO: 'vosotros', 'tío', 'mola', 'vale', 'genial', 'a por todo'.\n"
        f"- Usa expresiones peruanas naturales: 'vamos con todo', 'dale con fuerza', 'éxito'.\n"
        f"- PROHIBIDO incluir nombres propios.\n"
        f"- PROHIBIDO números, cifras o porcentajes.\n"
        f"- Siempre positivo y motivacional.\n"
        f"- Tono cálido, profesional, sutil.\n"
        f"- PROHIBIDO: 'urgente', 'te falta', 'atrasado', 'no olvides', 'recuerda'.\n"
        f"- Si tiene citas, menciónalo como algo positivo.\n"
        f"- Si tiene leads pendientes, menciónalo como oportunidad.\n"
        f"- Si todo está al día, motiva con energía.\n"
        f"Solo responde la frase, sin comillas ni explicación."
    )


_FALLBACKS_CITAS = [
    "Hoy tienes citas, ¡dale con todo!",
    "Tu agenda está buena hoy, ¡éxito!",
    "Tus citas de hoy van a salir bien.",
]

_FALLBACKS_PENDIENTES = [
    "Hay oportunidades esperándote, ¡vamos!",
    "Nuevas conexiones te esperan hoy.",
    "Hoy es buen día para avanzar.",
]

_FALLBACKS_GENERAL = [
    "¡Que sea un gran día!",
    "¡Vamos con todo hoy!",
    "Tu energía hace la diferencia.",
    "¡Dale con fuerza hoy!",
    "Cada conversación cuenta, ¡éxito!",
]


def _fallback(situation: str) -> str:
    if "citas" in situation:
        pool = _FALLBACKS_CITAS
    elif "pendientes" in situation or "nuevos" in situation:
        pool = _FALLBACKS_PENDIENTES
    else:
        pool = _FALLBACKS_GENERAL
    return random.choice(pool)


@router.get("")
async def get_greeting(current_user: TokenData = Depends(get_current_user)):
    key = _cache_key(current_user.user_id)

    # Return cached message if same day
    if key in _daily_cache:
        return {"message": _daily_cache[key], "source": "cache"}

    # Clean old entries (different date)
    today_suffix = f":{date.today().isoformat()}"
    stale = [k for k in _daily_cache if not k.endswith(today_suffix)]
    for k in stale:
        del _daily_cache[k]

    situation = _load_situation(current_user)
    prompt = _build_prompt(current_user, situation)

    message = None
    source = "fallback"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 50},
                },
            )
            resp.raise_for_status()
            text = resp.json().get("response", "").strip().strip('"').strip("'")
            text = _strip_numbers(text)
            if text and 5 < len(text) < 120:
                message = text
                source = "ai"
    except Exception as e:
        logger.info("Ollama unavailable, using fallback: %s", e)

    if not message:
        message = _fallback(situation)

    _daily_cache[key] = message
    return {"message": message, "source": source}

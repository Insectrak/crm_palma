"""
phishing_detector.py — Deteccion de phishing en mensajes WhatsApp entrantes.

Responsabilidad:
  - Analizar contenido de mensajes inbound contra patrones de phishing
  - Capa 1: reglas deterministas (regex) — rapida, $0, cubre ~70% casos
  - Capa 2: clasificador LLM local (Ollama qwen2.5:7b) — solo se dispara
    cuando la capa 1 detecta URL o señales ambiguas, para no sobrecargar
  - Persistir resultado en crm.wa_messages.risk_flags

Puntos de entrada:
  - analyze_message(message_id) — llamado desde BackgroundTasks del webhook
    cuando entra un mensaje inbound con contenido de texto.
  - reanalyze_message(message_id) — fuerza re-analisis ignorando cache.

Clean Code / SOLID:
  - SRP: solo analiza riesgo. No notifica, no bloquea, no modifica el lead.
  - OCP: agregar un nuevo patron = nueva entrada en _SUSPICIOUS_* constantes,
    no modifica logica.
  - DIP: depende de httpx + get_db (abstracciones), no de librerias de
    Ollama. Migrar a Claude/OpenAI = cambiar solo _call_ollama.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from psycopg2.extras import Json, RealDictCursor

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

_OLLAMA_TIMEOUT_SECONDS = 20.0

# ─────────────────────────────────────────────────────────────────────────────
# Capa 1 — Reglas deterministas
# ─────────────────────────────────────────────────────────────────────────────

# Dominios de acortadores de URL — sospechosos porque ocultan el destino real.
# En contextos de CRM (cualquier vertical: inmobiliaria, dental, servicios)
# casi nunca deberian aparecer.
_URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "is.gd", "buff.ly",
    "ow.ly", "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy",
    "tiny.cc", "bl.ink", "clck.ru", "soo.gd", "s.id", "v.gd",
}

# Marcas comunes que se imitan en typosquatting (bancos PE, redes sociales,
# entidades del Estado PE). Sin marcas de clientes especificos — esas se
# agregan dinamicamente desde brand_service.known_domains (V070.68 Bundle B).
_KNOWN_BRANDS_BASE = frozenset({
    "bcp.com.pe", "interbank.pe", "bbva.pe", "scotiabank.com.pe",
    "whatsapp.com", "facebook.com", "instagram.com",
    "sunat.gob.pe", "reniec.gob.pe",
})


def _known_brands() -> frozenset:
    """Combina marcas base con dominios del tenant configurados via brand_service.

    Cada cliente configura sus propios dominios en `BrandConfig.known_domains`
    para que el detector proteja contra typosquatting de su marca (ej:
    'doctormuelita.com' para Doctor Muelita, 'palmadelrio.pe' para Palma).
    """
    from app.services.brand_service import get_brand
    tenant_domains = []
    try:
        brand = get_brand()
        tenant_domains = [d.lower() for d in brand.get("known_domains") or []]
    except Exception:
        # Fail-open: si brand_service no responde, usar solo marcas base.
        pass
    return frozenset(_KNOWN_BRANDS_BASE | set(tenant_domains))


# Compat con codigo que aun referencia _KNOWN_BRANDS — proxy al helper dinamico.
class _KnownBrandsProxy(frozenset):
    def __contains__(self, item):
        return item in _known_brands()
    def __iter__(self):
        return iter(_known_brands())


_KNOWN_BRANDS = _KnownBrandsProxy()

# TLDs estadisticamente mas usados en phishing/malware.
_SUSPICIOUS_TLDS = {
    "xyz", "top", "tk", "ml", "ga", "cf", "gq", "pw", "buzz",
    "click", "link", "rest", "country", "cam", "mov", "zip",
}

# Frases tipicas de intentos de estafa/phishing en español.
# Agrupadas por tipo para que el scoring pondere.
_PHRASES_URGENCY = [
    r"urgente", r"ahora mismo", r"en las pr[oó]ximas \d+ horas?",
    r"antes de que", r"caduca hoy", r"expir[ao]",
]
_PHRASES_CREDENTIALS = [
    r"verific[ae] tu cuenta", r"confirma tus datos",
    r"clave de acceso", r"contrase[nñ]a", r"c[oó]digo de seguridad",
    r"otp", r"token de verificaci[oó]n", r"n[uú]mero de tarjeta",
    r"cvv", r"cci", r"n[uú]mero de cuenta bancaria",
]
_PHRASES_MONEY = [
    r"transfiere(?:me)?", r"dep[oó]sito de emergencia",
    r"pr[ée]stamo urgente", r"reclama tu premio", r"ganaste",
    r"has sido seleccionad[oa]", r"sorteo", r"regalo de",
    r"bono de \$?\s*\d+", r"reembolso",
]
_PHRASES_IMPERSONATION = [
    r"soy (?:del banco|de sunat|de reniec|de migraciones)",
    r"equipo de (?:seguridad|soporte|atenci[oó]n)",
    r"departamento de fraudes",
]

_URL_REGEX = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+|"
    r"\b[a-zA-Z0-9][a-zA-Z0-9-]{1,62}\.[a-zA-Z]{2,}(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)

_DOMAIN_REGEX = re.compile(r"(?:https?://)?(?:www\.)?([^/\s:?#]+)", re.IGNORECASE)


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    raw = _URL_REGEX.findall(text)
    # Limpiar puntuacion final
    cleaned: list[str] = []
    for u in raw:
        u = u.rstrip(".,;:!?)")
        if "." in u and len(u) >= 4:
            cleaned.append(u)
    return cleaned


def _domain_of(url: str) -> Optional[str]:
    m = _DOMAIN_REGEX.match(url)
    if not m:
        return None
    return m.group(1).lower()


def _tld_of(domain: str) -> Optional[str]:
    parts = domain.rsplit(".", 1)
    return parts[-1].lower() if len(parts) == 2 else None


def _looks_like_typosquat(domain: str) -> Optional[str]:
    """Compara contra brands conocidas con distancia Levenshtein basica."""
    if not domain or domain in _KNOWN_BRANDS:
        return None
    for brand in _KNOWN_BRANDS:
        if _similar_but_not_equal(domain, brand):
            return brand
    return None


def _similar_but_not_equal(a: str, b: str) -> bool:
    """True si los strings son muy parecidos pero no identicos (typosquat)."""
    if a == b or abs(len(a) - len(b)) > 3:
        return False
    # Levenshtein simple (O(n*m)) — palabras cortas, costo trivial
    if len(a) > 40 or len(b) > 40:
        return False
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(
                dp[j] + 1,
                dp[j - 1] + 1,
                prev + (0 if ca == cb else 1),
            )
            prev = cur
    distance = dp[-1]
    # Distancia 1-2 en palabras >4 chars = typosquatting
    return 1 <= distance <= 2 and min(len(a), len(b)) >= 5


def _match_any(patterns: list[str], text: str) -> list[str]:
    hits: list[str] = []
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            hits.append(p)
    return hits


def _apply_rules(text: str) -> dict[str, Any]:
    """Ejecuta la capa de reglas. Retorna dict con score y flags."""
    if not text:
        return {"score": 0, "reasons": [], "urls": [], "needs_llm": False}

    reasons: list[str] = []
    score = 0
    urls = _extract_urls(text)

    # ─── Analisis de URLs ──────────────────────────────────────────────────
    for url in urls:
        domain = _domain_of(url)
        if not domain:
            continue
        if domain in _URL_SHORTENERS:
            score += 35
            reasons.append(f"URL acortada sospechosa: {domain}")
        tld = _tld_of(domain)
        if tld and tld in _SUSPICIOUS_TLDS:
            score += 25
            reasons.append(f"TLD poco comun: .{tld}")
        typo = _looks_like_typosquat(domain)
        if typo:
            score += 50
            reasons.append(f"Posible suplantacion de {typo} ({domain})")

    # ─── Analisis de frases ────────────────────────────────────────────────
    if _match_any(_PHRASES_CREDENTIALS, text):
        score += 40
        reasons.append("Solicitud de credenciales/OTP")
    if _match_any(_PHRASES_MONEY, text):
        score += 30
        reasons.append("Solicitud de dinero o premio")
    if _match_any(_PHRASES_IMPERSONATION, text):
        score += 35
        reasons.append("Suplantacion de entidad oficial")
    if _match_any(_PHRASES_URGENCY, text) and (urls or score > 0):
        # Urgencia sola no es phishing, pero combinada con URL/otros sube el peso
        score += 15
        reasons.append("Lenguaje de urgencia")

    # Capa LLM se justifica si: hay URL, o reglas dieron algun hit ambiguo
    needs_llm = bool(urls) or (0 < score < 60)

    return {
        "score": min(score, 100),
        "reasons": reasons,
        "urls": urls,
        "needs_llm": needs_llm,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Capa 2 — LLM local (Ollama)
# ─────────────────────────────────────────────────────────────────────────────

# V070.68 (Bundle B): prompt sin nombre/industria de cliente especifico.
# El contexto del negocio se inyecta dinamicamente desde brand_service para
# que el detector funcione igual para Palma Rio, Doctor Muelita y futuros.
_LLM_PROMPT = """Eres un analista de seguridad que revisa mensajes de WhatsApp
recibidos por {company_name} ({industry_description}). Tu tarea: detectar si el
mensaje es un intento de phishing, estafa o fraude.

MENSAJE RECIBIDO:
\"\"\"
{message}
\"\"\"

Contexto: leads legitimos suelen preguntar por {legitimate_topics}. Phishing
tipico incluye: links acortados, pedidos de claves/OTP, suplantacion de bancos
o entidades, premios falsos, pedidos de transferencia urgente.

RESPONDE UNICAMENTE CON UN JSON VALIDO. Sin markdown, sin backticks, sin
explicaciones externas. Usa EXACTAMENTE estas claves:

{{
  "is_phishing": true | false,
  "confidence": numero entre 0.0 y 1.0,
  "risk_level": "low" | "medium" | "high",
  "reason": "una frase corta (max 20 palabras) explicando el veredicto en español"
}}
"""


def _build_llm_prompt(message: str) -> str:
    """Inyecta el contexto del tenant en el prompt base.

    Si el tenant no tiene industry_description configurado, usamos placeholders
    genericos para que el clasificador siga funcionando con razonable accuracy.
    """
    from app.services.brand_service import get_brand
    brand = get_brand()
    company = brand.get("company_name") or "una empresa peruana"
    industry = brand.get("industry_description") or "atiende clientes via WhatsApp"
    keywords = brand.get("relevant_keywords") or "informacion, precios, servicios"
    return _LLM_PROMPT.format(
        company_name=company,
        industry_description=industry,
        legitimate_topics=keywords,
        message=message[:1500],
    )


async def _call_ollama(message: str) -> Optional[dict]:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
    payload = {
        "model": settings.ollama_model,
        "prompt": _build_llm_prompt(message),
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 200,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT_SECONDS) as cli:
            r = await cli.post(url, json=payload)
            r.raise_for_status()
            response_text = r.json().get("response", "")
            if not response_text:
                return None
            return json.loads(response_text)
    except httpx.TimeoutException:
        logger.warning("phishing: Ollama timeout tras %ss", _OLLAMA_TIMEOUT_SECONDS)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("phishing: Ollama JSON invalido: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("phishing: Ollama error: %s", exc)
        return None


def _normalize_llm(raw: dict) -> dict:
    is_phish = bool(raw.get("is_phishing"))
    try:
        conf = float(raw.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    lvl_raw = str(raw.get("risk_level") or "").strip().lower()
    level = lvl_raw if lvl_raw in ("low", "medium", "high") else "low"
    reason = (raw.get("reason") or "").strip()[:300] or None
    return {
        "is_phishing": is_phish,
        "confidence": round(conf, 2),
        "risk_level": level,
        "reason": reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Combinacion capa 1 + capa 2
# ─────────────────────────────────────────────────────────────────────────────

def _final_level(rules_score: int, llm_result: Optional[dict]) -> str:
    """Combina score de reglas con veredicto LLM para nivel final."""
    if llm_result and llm_result.get("is_phishing"):
        if llm_result.get("risk_level") == "high":
            return "high"
        if rules_score >= 40:
            return "high"
        return "medium"
    if rules_score >= 60:
        return "high"
    if rules_score >= 30:
        return "medium"
    if rules_score > 0:
        return "low"
    return "safe"


async def _analyze_text(content: str) -> dict:
    """Pipeline completo: reglas + (opcional) LLM → risk_flags dict."""
    rules = _apply_rules(content)
    llm_result = None
    if rules["needs_llm"]:
        raw = await _call_ollama(content)
        if raw:
            llm_result = _normalize_llm(raw)

    level = _final_level(rules["score"], llm_result)
    is_phishing = level in ("medium", "high") or (
        llm_result is not None and llm_result.get("is_phishing")
    )

    return {
        "score": rules["score"],
        "level": level,
        "is_phishing": is_phishing,
        "reasons": rules["reasons"],
        "urls": rules["urls"],
        "llm": llm_result,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "engine": "rules+ollama" if llm_result else "rules",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_message(message_id: int) -> Optional[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, direction, msg_type, content, risk_flags
                FROM crm.wa_messages
                WHERE id = %s
                """,
                (message_id,),
            )
            return cur.fetchone()


def _persist_flags(message_id: int, flags: dict) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crm.wa_messages SET risk_flags = %s WHERE id = %s",
                (Json(flags), message_id),
            )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Entradas publicas
# ─────────────────────────────────────────────────────────────────────────────

async def analyze_message(message_id: int, force: bool = False) -> Optional[dict]:
    """Analiza un mensaje y persiste sus risk_flags.

    Idempotente: si el mensaje ya tiene risk_flags y force=False, retorna
    sin re-analizar. Solo aplica a mensajes inbound con contenido textual.
    """
    row = _fetch_message(message_id)
    if not row:
        logger.warning("phishing: mensaje %s no existe", message_id)
        return None

    if row["direction"] != "inbound":
        return None

    if row["risk_flags"] and not force:
        return row["risk_flags"]

    content = (row["content"] or "").strip()
    if not content:
        # Sin texto no hay nada que analizar (media sin caption, etc.)
        return None

    try:
        flags = await _analyze_text(content)
    except Exception as exc:  # noqa: BLE001
        logger.exception("phishing: analisis fallo msg=%s: %s", message_id, exc)
        return None

    try:
        _persist_flags(message_id, flags)
    except Exception as exc:  # noqa: BLE001
        logger.warning("phishing: persist fallo msg=%s: %s", message_id, exc)

    if flags.get("is_phishing"):
        logger.warning(
            "phishing: DETECTADO msg=%s level=%s score=%s reasons=%s",
            message_id, flags["level"], flags["score"], flags["reasons"],
        )
    return flags


async def reanalyze_message(message_id: int) -> Optional[dict]:
    """Fuerza re-analisis ignorando cache previo."""
    return await analyze_message(message_id, force=True)

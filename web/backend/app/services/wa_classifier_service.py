"""
wa_classifier_service.py — Clasificador IA para mensajes entrantes de WhatsApp.

Responsabilidad:
  - Construir un prompt con el contexto (mensaje + perfil + referral + historial)
  - Llamar a Ollama (qwen2.5:7b) forzando respuesta JSON
  - Normalizar/validar la respuesta del modelo
  - Persistir el resultado en crm.wa_conversations
  - Disparar al router (wa_router_service) para tomar accion segun categoria

Puntos de entrada:
  - classify_conversation(conversation_id) — llamado desde BackgroundTasks
    del webhook WhatsApp cuando entra el PRIMER mensaje de una conversacion
    cuyo classification_status != 'classified'.

Fallback:
  - Si Ollama no responde o devuelve JSON invalido → status='failed',
    attempts++. Un cron/worker posterior puede reintentar (ver
    reclassify_failed en wa_router_service).

Clean Code / SOLID:
  - SRP: solo clasifica. No crea leads, no asigna asesores, no envia push.
    Eso es responsabilidad del wa_router_service.
  - DIP: depende de `httpx` (abstracto) y `get_db`, no de librerias de
    Ollama concretas — si manana migramos a Claude/OpenAI, cambia solo
    `_call_ollama`.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from psycopg2.extras import Json, RealDictCursor

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

# Timeout generoso — qwen2.5:7b en CPU puede tardar 8-15s
_OLLAMA_TIMEOUT_SECONDS = 30.0

# Categorias validas (si el modelo inventa otra → fallback a consulta_general)
_VALID_CATEGORIES = {
    "cliente_potencial",
    "cliente_existente",
    "consulta_general",
    "spam",
    "no_relacionado",
}
_VALID_INTERESTS = {"compra", "alquiler", "informacion", "reclamo", "agendar_visita"}
_VALID_URGENCIES = {"alta", "media", "baja"}


# ─────────────────────────────────────────────────────────────────────────────
# Configuracion editable desde /Configuracion → IA Clasificador
# ─────────────────────────────────────────────────────────────────────────────

# V070.68 (Bundle B): defaults VACIOS para campos de negocio (vertical-agnostic).
#
# Antes este dict tenia "Palma del Rio" + "vende lotes, casas..." hardcoded.
# Esto rompia para Doctor Muelita (dental): el clasificador IA evaluaba
# mensajes asumiendo industria inmobiliaria y producia juicios erroneos.
#
# Ahora: si no hay config persistida en DB, el clasificador se niega a
# clasificar (ver is_configured()) en vez de asumir industria. El admin
# del tenant DEBE configurar company_name + company_description +
# relevant_keywords antes de activar el clasificador IA.
_AI_CONFIG_DEFAULTS = {
    "company_name":           "",     # debe configurarse por tenant
    "company_description":    "",     # idem
    "relevant_keywords":      "",     # idem
    "country":                "Peru", # generico; cambiable si entra un tenant fuera de PE
    "auto_assign_threshold":  0.80,
    "auto_archive_threshold": 0.85,
    "history_message_count":  5,
    "extra_instructions":     "",     # texto libre opcional
    # Multi-provider config (V039)
    "provider":               "ollama",   # ollama | openai | anthropic | gemini
    "ollama_base_url":        "",     # vacio = usa settings.ollama_base_url
    "ollama_model":           "",     # vacio = usa settings.ollama_model
    "openai_api_key":         "",     # encriptado en DB
    "openai_model":           "gpt-4o-mini",
    "anthropic_api_key":      "",     # encriptado en DB
    "anthropic_model":        "claude-haiku-4-5",
    "gemini_api_key":         "",     # encriptado en DB
    "gemini_model":           "gemini-1.5-flash",
    "timeout_seconds":        30,
    "temperature":            0.2,
    "max_tokens":             400,
}


def is_configured() -> bool:
    """True si el clasificador IA tiene contexto de negocio configurado.

    Si retorna False, el clasificador debe negarse a clasificar el mensaje
    (devolver 'not_configured' o similar) en vez de usar defaults vacios.
    Esto previene el bug historico de asumir industria del cliente anterior.
    """
    cfg = load_ai_config()
    return bool(
        (cfg.get("company_name") or "").strip()
        and (cfg.get("company_description") or "").strip()
        and (cfg.get("relevant_keywords") or "").strip()
    )

# Cache TTL — clasificar muchas convs por minuto sin pegarle al DB cada vez
_AI_CONFIG_CACHE: dict = {"value": None, "fetched_at": 0.0}
_AI_CONFIG_CACHE_TTL_SECONDS = 60.0


def load_ai_config() -> dict:
    """Carga la config de IA desde public.app_settings con cache TTL.

    Devuelve siempre un dict completo — los campos faltantes se rellenan
    con defaults. Cache invalida cada 60s; PUT desde la UI tambien lo
    invalida explicitamente via invalidate_ai_config_cache().
    """
    import time
    now = time.monotonic()
    cached = _AI_CONFIG_CACHE["value"]
    if cached is not None and (now - _AI_CONFIG_CACHE["fetched_at"]) < _AI_CONFIG_CACHE_TTL_SECONDS:
        return cached

    config = dict(_AI_CONFIG_DEFAULTS)
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'ai_classifier_config'"
                )
                row = cur.fetchone()
                if row and isinstance(row[0], dict):
                    # Merge sobre defaults — keys faltantes quedan en default,
                    # keys extras del DB se preservan (forward compat).
                    config.update(row[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_ai_config: fallback a defaults (%s)", exc)

    _AI_CONFIG_CACHE["value"] = config
    _AI_CONFIG_CACHE["fetched_at"] = now
    return config


def invalidate_ai_config_cache() -> None:
    """Llamar desde el endpoint PUT para forzar refetch en proximo classify."""
    _AI_CONFIG_CACHE["value"] = None
    _AI_CONFIG_CACHE["fetched_at"] = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """Eres un analista de CRM. Tu trabajo es clasificar un mensaje entrante
de WhatsApp y resumir HONESTAMENTE que dijo el cliente. NO inventes intencion.

REGLA CRITICA — RESUMEN HONESTO:
  El "resumen" debe describir lo que el cliente LITERALMENTE escribio o,
  si solo saluda/pide informacion, mencionar el anuncio que vio.
  NO inventes que pidio "informacion sobre inmuebles" si no lo dijo.
  NO asumas tema (compra, lote, departamento) si no aparece en el chat
  o en el anuncio.

  Ejemplos correctos:
  - Cliente: "Hola"  → resumen: "Saludo inicial sin pedido especifico"
  - Cliente: "Quiero mas info"  + ad sobre PDFs → "Pide info tras
    click en anuncio sobre gestion de PDFs"
  - Cliente: "Cuanto cuesta el lote 12 en Cayma?" → "Pregunta precio
    del lote 12 en Cayma"

  Ejemplos INCORRECTOS (no hacer):
  - Cliente: "Hola" → "Busca informacion sobre inmuebles"  ❌ inventado
  - Cliente: "Quiero mas info" sin contexto → "Interesado en comprar
    departamento" ❌ inventado

EMPRESA (solo para clasificar relevancia, NO para inventar intencion):
- {company_name}: {company_description}.
- Si el cliente menciona {relevant_keywords} → relevante.
- Si el cliente saluda o pide info generica → relevante solo si vino por
  un anuncio identificable; el resumen debe reflejar el anuncio, no
  asumir que pregunto por estos productos.

{extra_instructions_block}

DATOS DEL CLIENTE:
- Perfil WhatsApp: {profile_name}
- Telefono: {wa_phone}

ANUNCIO DE ORIGEN (Click-to-WhatsApp, si aplica):
- Origen: {origen}
- Titulo del anuncio: {ad_headline}
- Cuerpo del anuncio: {ad_body}
- Campaña interna: {campaign}

HISTORIAL DEL CHAT (mas viejo primero):
{history}

ULTIMO MENSAJE DEL CLIENTE (a clasificar):
"{message}"

PASOS DE RAZONAMIENTO (mentales, no los escribas):
  1. Lee el anuncio: ¿de que tema es? ¿es de {company_name} o algo no
     relacionado (PDFs, criptos, etc.)?
  2. Lee LITERALMENTE lo que el cliente escribio. ¿Menciono algo de los
     productos relevantes ({relevant_keywords})? ¿O solo saludo/pidio
     info generica?
  3. Construye el resumen: si el cliente fue especifico, resume su
     pedido. Si solo saludo, menciona el anuncio que lo trajo.

RESPONDE UNICAMENTE CON JSON VALIDO. Sin markdown, sin backticks, sin
explicaciones. Usa EXACTAMENTE estas claves:

{{
  "categoria": "cliente_potencial" | "cliente_existente" | "consulta_general" | "spam" | "no_relacionado",
  "confianza": numero entre 0.0 y 1.0,
  "interes": "compra" | "alquiler" | "informacion" | "reclamo" | "agendar_visita" | null,
  "urgencia": "alta" | "media" | "baja",
  "resumen": "max 18 palabras. DEBE estar grounded en lo que el cliente escribio o en el anuncio. NO inventes intencion inmobiliaria.",
  "nombre_sugerido": "nombre detectado en el mensaje o null",
  "presupuesto_mencionado": "string con el monto o null",
  "zona_mencionada": "barrio/distrito mencionado o null"
}}
"""


def _format_history(messages: list[dict], limit: int = 5) -> str:
    """Ultimos N mensajes (configurable) como lineas 'direction: content'."""
    if not messages:
        return "(sin historial previo — este es el primer mensaje)"
    lines = []
    for m in messages[-limit:]:
        who = "Cliente" if m.get("direction") == "inbound" else "Asesor"
        content = (m.get("content") or "").strip()[:200]
        if content:
            lines.append(f"  {who}: {content}")
    return "\n".join(lines) if lines else "(sin contenido)"


def _build_prompt(ctx: dict, last_message: str) -> str:
    referral = ctx.get("referral") or {}
    origen = "WhatsApp directo"
    if ctx.get("campaign_headline"):
        origen = f"Click-to-WhatsApp Ad — {ctx['campaign_headline']}"
    elif referral.get("source_type"):
        origen = f"Referral {referral.get('source_type')}"

    cfg = load_ai_config()
    extra = (cfg.get("extra_instructions") or "").strip()
    extra_block = (
        f"INSTRUCCIONES ADICIONALES (especificas del negocio):\n{extra}\n"
        if extra else ""
    )
    history_count = max(1, min(int(cfg.get("history_message_count") or 5), 20))

    return _PROMPT_TEMPLATE.format(
        company_name=cfg["company_name"],
        company_description=cfg["company_description"],
        relevant_keywords=cfg["relevant_keywords"],
        extra_instructions_block=extra_block,
        profile_name=ctx.get("contact_name") or "(sin nombre)",
        wa_phone=ctx.get("wa_phone") or "(desconocido)",
        origen=origen,
        ad_headline=ctx.get("campaign_headline") or "(sin titulo)",
        ad_body=ctx.get("campaign_body") or "(sin cuerpo)",
        campaign=ctx.get("campaign_name") or "(ninguna)",
        history=_format_history(ctx.get("messages") or [], limit=history_count),
        message=last_message,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Ollama client
# ─────────────────────────────────────────────────────────────────────────────

def _build_provider_runtime_config(cfg: dict) -> dict:
    """Convierte la config persistida (con keys encriptadas) en el dict
    que get_provider() espera (keys ya decriptadas, listas para usar).

    Aislado para reuso: lo usa _call_ollama() y el endpoint de health.
    """
    from app.services.secrets_service import decrypt
    runtime = dict(cfg)
    enc_openai = (cfg.get("openai_api_key") or "").strip()
    if enc_openai:
        runtime["openai_api_key"] = decrypt(enc_openai) or ""
    enc_anthropic = (cfg.get("anthropic_api_key") or "").strip()
    if enc_anthropic:
        runtime["anthropic_api_key"] = decrypt(enc_anthropic) or ""
    enc_gemini = (cfg.get("gemini_api_key") or "").strip()
    if enc_gemini:
        runtime["gemini_api_key"] = decrypt(enc_gemini) or ""
    return runtime


async def _call_ollama(prompt: str) -> Optional[dict]:
    """Backwards-compatible name. En realidad llama al provider configurado
    (Ollama por default, pero puede ser OpenAI o Anthropic). El nombre se
    mantiene para no romper callers existentes; comentario de migration:
    en el siguiente paso renombramos a _call_classifier_provider().
    """
    from app.services.llm_providers import LLMProviderError, get_provider

    cfg = load_ai_config()
    runtime_cfg = _build_provider_runtime_config(cfg)
    try:
        provider = get_provider(runtime_cfg)
    except LLMProviderError as exc:
        logger.error("classifier: config invalida → %s", exc)
        return None

    try:
        return await provider.classify_async(prompt)
    except LLMProviderError as exc:
        # Errores duros (auth, modelo no instalado) — no reintentar
        logger.error("classifier: %s falla dura → %s", provider.name, exc)
        return None
    except httpx.TimeoutException:
        logger.warning("classifier: %s timeout", provider.name)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("classifier: %s error: %s", provider.name, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Normalizacion / saneado
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_result(raw: dict) -> dict:
    """Sanea el dict del modelo contra los valores validos. Nunca levanta."""
    # Categoria
    cat = str(raw.get("categoria") or "").strip().lower()
    if cat not in _VALID_CATEGORIES:
        cat = "consulta_general"

    # Confianza (0.0 - 1.0)
    try:
        conf = float(raw.get("confianza") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    # Interes (nullable)
    interes_raw = raw.get("interes")
    interes = None
    if interes_raw:
        ir = str(interes_raw).strip().lower()
        if ir in _VALID_INTERESTS:
            interes = ir

    # Urgencia (default media)
    urg_raw = str(raw.get("urgencia") or "").strip().lower()
    urgencia = urg_raw if urg_raw in _VALID_URGENCIES else "media"

    # Texto libre truncado (por si el modelo se pasa)
    resumen = (raw.get("resumen") or "")
    if resumen and isinstance(resumen, str):
        resumen = resumen.strip()[:500]
    else:
        resumen = None

    nombre = raw.get("nombre_sugerido")
    if nombre and isinstance(nombre, str):
        nombre = nombre.strip()[:120] or None
    else:
        nombre = None

    return {
        "categoria": cat,
        "confianza": round(conf, 2),
        "interes": interes,
        "urgencia": urgencia,
        "resumen": resumen,
        "nombre_sugerido": nombre,
        "presupuesto_mencionado": (raw.get("presupuesto_mencionado") or None),
        "zona_mencionada": (raw.get("zona_mencionada") or None),
        "raw": raw,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fetch contexto de la conversacion
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_context(conversation_id: int) -> Optional[dict]:
    """Lee conversation + ultimos 5 mensajes + campaña (si hay)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT c.id, c.wa_phone, c.lead_id, c.contact_name,
                       c.classification_status,
                       l.wa_campaign_headline, l.wa_referral_payload,
                       cam.name AS campaign_name,
                       cam.creative_title, cam.creative_body
                FROM crm.wa_conversations c
                LEFT JOIN crm.leads l ON l.id = c.lead_id
                LEFT JOIN crm.wa_campaigns cam ON cam.id = l.wa_campaign_id
                WHERE c.id = %s
                """,
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            cur.execute(
                """
                SELECT direction, content, timestamp
                FROM crm.wa_messages
                WHERE conversation_id = %s
                  AND direction = 'inbound'
                ORDER BY timestamp ASC
                LIMIT 5
                """,
                (conversation_id,),
            )
            messages = [dict(r) for r in cur.fetchall()]

    # campaign_headline prioriza el titulo guardado en leads (snapshot al
    # crearse el lead); si no, usa el creative_title actual de la campaña.
    campaign_headline = row["wa_campaign_headline"] or row.get("creative_title")

    return {
        "conversation_id": row["id"],
        "wa_phone": row["wa_phone"],
        "lead_id": row["lead_id"],
        "contact_name": row["contact_name"],
        "classification_status": row["classification_status"],
        "campaign_headline": campaign_headline,
        "campaign_body": row.get("creative_body"),
        "campaign_name": row["campaign_name"],
        "referral": row["wa_referral_payload"],
        "messages": messages,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia del resultado
# ─────────────────────────────────────────────────────────────────────────────

def _mark_failed(conversation_id: int) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET classification_status   = 'failed',
                    classification_attempts = classification_attempts + 1,
                    classified_at           = NOW()
                WHERE id = %s
                """,
                (conversation_id,),
            )
        conn.commit()


def _mark_skipped(conversation_id: int) -> None:
    """Conversacion ya tenia lead asociado → no necesita clasificacion IA."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.wa_conversations
                SET classification_status = 'skipped',
                    classified_at         = NOW()
                WHERE id = %s
                """,
                (conversation_id,),
            )
        conn.commit()


def _persist_result(conversation_id: int, result: dict) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE crm.wa_conversations SET
                    classification_status     = 'classified',
                    classification_category   = %s,
                    classification_confidence = %s,
                    classification_interest   = %s,
                    classification_urgency    = %s,
                    classification_summary    = %s,
                    classification_raw        = %s,
                    classification_attempts   = classification_attempts + 1,
                    classified_at             = NOW(),
                    classified_by_model       = %s
                WHERE id = %s
                """,
                (
                    result["categoria"],
                    result["confianza"],
                    result["interes"],
                    result["urgencia"],
                    result["resumen"],
                    Json(result["raw"]),
                    settings.ollama_model,
                    conversation_id,
                ),
            )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Entrada publica
# ─────────────────────────────────────────────────────────────────────────────

async def classify_conversation(
    conversation_id: int,
    force_new_lead: bool = False,
) -> Optional[dict]:
    """Clasifica la conversacion y dispara el router.

    Idempotente: si la conversacion ya fue clasificada, retorna sin hacer
    nada. Si tiene lead_id (cliente existente), marca como 'skipped'.

    force_new_lead: propagado al router. Cuando True (venido de /new_case),
    el router crea un lead nuevo con rotacion aunque la IA lo mande a
    manual_review o el telefono ya tenga un lead activo.

    Retorna el dict normalizado del resultado, o None si no se pudo.
    """
    ctx = _fetch_context(conversation_id)
    if not ctx:
        logger.warning("wa_classify: conversation %s no existe", conversation_id)
        return None

    # Si ya fue clasificada (estado no queue/pending/failed), skip
    if ctx["classification_status"] not in ("pending", "queued", "failed"):
        logger.info(
            "wa_classify: conv %s ya esta en status=%s, skip",
            conversation_id, ctx["classification_status"],
        )
        return None

    # Cliente existente → no necesita IA (se le responde con su asesor actual)
    if ctx["lead_id"]:
        _mark_skipped(conversation_id)
        logger.info(
            "wa_classify: conv %s tiene lead_id=%s, marcado skipped",
            conversation_id, ctx["lead_id"],
        )
        return None

    # Ultimo mensaje inbound
    messages = ctx["messages"] or []
    if not messages:
        logger.warning("wa_classify: conv %s sin mensajes inbound, skip", conversation_id)
        _mark_skipped(conversation_id)
        return None
    last_message = (messages[-1].get("content") or "").strip()
    if not last_message:
        logger.info("wa_classify: conv %s ultimo msg sin contenido, skip", conversation_id)
        _mark_skipped(conversation_id)
        return None

    # Llamada al modelo
    prompt = _build_prompt(ctx, last_message)
    raw = await _call_ollama(prompt)
    if raw is None:
        _mark_failed(conversation_id)
        logger.warning("wa_classify: Ollama fallo conv %s → status=failed", conversation_id)
        return None

    result = _normalize_result(raw)
    _persist_result(conversation_id, result)
    logger.info(
        "wa_classify: conv=%s categoria=%s conf=%.2f",
        conversation_id, result["categoria"], result["confianza"],
    )

    # Dispara router (crear lead / rotar / archivar)
    # Importamos dinamicamente para evitar ciclo circular
    try:
        from app.services.wa_router_service import route_classified_conversation
        route_classified_conversation(
            conversation_id, result, ctx, force_new_lead=force_new_lead,
        )
    except Exception as exc:  # noqa: BLE001 — el routing no debe tumbar la clasificacion
        logger.exception("wa_classify: routing fallo conv=%s: %s", conversation_id, exc)

    return result

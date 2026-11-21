"""
llm_providers.py — Abstraccion de proveedores LLM para el clasificador IA.

Permite cambiar entre Ollama (on-prem), OpenAI (gpt-4o-mini, etc.) y
Anthropic (Claude) sin tocar codigo, eligiendo desde /Configuracion.

Diseño:
  - LLMProvider es la interfaz abstracta — clasifica un prompt y devuelve
    el dict normalizado que entiende wa_router_service.
  - Cada proveedor concreto implementa `classify_async` y `health_check`.
  - get_provider(config) es la factory — lee config y retorna la instancia
    correcta. Si la config esta incompleta, falla rapido (sin esperar al
    primer chat para enterarse).
  - API keys nunca se loguean ni se devuelven en GET — solo se persisten
    encriptadas via secrets_service.encrypt.

Clean Code:
  - SRP: cada provider sabe solo de SU API. La parsing JSON es comun.
  - DIP: el classifier service depende de la interfaz, no de implementaciones.
  - OCP: agregar Gemini o Mistral = nueva clase, no tocar el resto.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_TEMPERATURE = 0.2
_DEFAULT_MAX_TOKENS = 400


# ─────────────────────────────────────────────────────────────────────────────
# Interfaz
# ─────────────────────────────────────────────────────────────────────────────

class LLMProviderError(Exception):
    """Error normalizado de cualquier proveedor LLM."""


class LLMProvider:
    """Interfaz abstracta. No instanciar directamente — usar get_provider()."""

    name: str = "abstract"

    async def classify_async(self, prompt: str) -> Optional[dict]:
        """Envia el prompt al modelo y devuelve el dict JSON parseado.
        Devuelve None si hay error transitorio (timeout, 5xx) — el caller
        decide si reintenta o manda a manual_review.
        Levanta LLMProviderError ante errores no recuperables (auth, config)."""
        raise NotImplementedError

    async def health_check(self) -> dict:
        """Verifica que el proveedor responde. Devuelve:
            {ok: bool, latency_ms: int, model: str, error: str?}"""
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers comunes
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json_safe(raw_text: str) -> Optional[dict]:
    """Intenta parsear JSON. Si el modelo devuelve markdown ```json ... ```
    o texto extra, hace mejor esfuerzo extrayendo el primer objeto valido."""
    if not raw_text:
        return None
    text = raw_text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("```", 2)
        text = text[1] if len(text) >= 2 else raw_text
        # remove leading "json\n"
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Buscar primer { y matchear su }
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Ollama (on-prem, default)
# ─────────────────────────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ):
        if not base_url:
            raise LLMProviderError("Ollama: base_url vacio")
        if not model:
            raise LLMProviderError("Ollama: model vacio")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def classify_async(self, prompt: str) -> Optional[dict]:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model":  self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as cli:
                r = await cli.post(url, json=payload)
                r.raise_for_status()
                response_text = r.json().get("response", "")
                if not response_text:
                    logger.warning("Ollama: response vacio")
                    return None
                return _parse_json_safe(response_text)
        except httpx.TimeoutException:
            logger.warning("Ollama: timeout tras %ss", self.timeout_seconds)
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                # Modelo no instalado — error duro
                raise LLMProviderError(
                    f"Modelo '{self.model}' no esta instalado en el servidor "
                    f"Ollama. Hace 'ollama pull {self.model}' en el host."
                ) from exc
            logger.warning("Ollama HTTP %s: %s", exc.response.status_code, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ollama error inesperado: %s", exc)
            return None

    async def health_check(self) -> dict:
        import time
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as cli:
                r = await cli.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                data = r.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                installed = self.model in models
            return {
                "ok":              True,
                "latency_ms":      int((time.perf_counter() - t0) * 1000),
                "model":           self.model,
                "model_installed": installed,
                "available_models": models[:20],  # cap a 20 para no inflar
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok":         False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "error":      str(exc)[:200],
            }


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI
# ─────────────────────────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        base_url: str = "https://api.openai.com/v1",
    ):
        if not api_key:
            raise LLMProviderError("OpenAI: api_key vacio")
        if not model:
            raise LLMProviderError("OpenAI: model vacio")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

    async def classify_async(self, prompt: str) -> Optional[dict]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model":           self.model,
            "messages":        [{"role": "user", "content": prompt}],
            "temperature":     self.temperature,
            "max_tokens":      self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as cli:
                r = await cli.post(url, json=payload, headers=self._headers)
                if r.status_code == 401:
                    raise LLMProviderError("OpenAI: API key invalida (401)")
                if r.status_code == 429:
                    logger.warning("OpenAI: rate limit (429) — reintentar luego")
                    return None
                r.raise_for_status()
                data = r.json()
                content = (
                    data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                )
                if not content:
                    logger.warning("OpenAI: content vacio")
                    return None
                return _parse_json_safe(content)
        except httpx.TimeoutException:
            logger.warning("OpenAI: timeout tras %ss", self.timeout_seconds)
            return None
        except LLMProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenAI error inesperado: %s", exc)
            return None

    async def health_check(self) -> dict:
        import time
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as cli:
                r = await cli.get(
                    f"{self.base_url}/models", headers=self._headers,
                )
                r.raise_for_status()
                data = r.json()
                models = [m.get("id", "") for m in data.get("data", [])]
                # Filtrar solo modelos chat utiles para no inflar UI
                chat_models = sorted([
                    m for m in models
                    if any(p in m for p in ("gpt-4", "gpt-3.5", "gpt-5"))
                ])[:20]
            return {
                "ok":              True,
                "latency_ms":      int((time.perf_counter() - t0) * 1000),
                "model":           self.model,
                "available_models": chat_models,
            }
        except httpx.HTTPStatusError as exc:
            return {
                "ok":         False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "error":      f"HTTP {exc.response.status_code} (¿API key valida?)",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok":         False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "error":      str(exc)[:200],
            }


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic (Claude)
# ─────────────────────────────────────────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        base_url: str = "https://api.anthropic.com/v1",
        anthropic_version: str = "2023-06-01",
    ):
        if not api_key:
            raise LLMProviderError("Anthropic: api_key vacio")
        if not model:
            raise LLMProviderError("Anthropic: model vacio")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.anthropic_version = anthropic_version

    @property
    def _headers(self) -> dict:
        return {
            "x-api-key":         self.api_key,
            "anthropic-version": self.anthropic_version,
            "Content-Type":      "application/json",
        }

    async def classify_async(self, prompt: str) -> Optional[dict]:
        url = f"{self.base_url}/messages"
        # Anthropic NO tiene response_format=json_object — lo forzamos via
        # system prompt + parsing tolerante.
        payload = {
            "model":       self.model,
            "max_tokens":  self.max_tokens,
            "temperature": self.temperature,
            "system":      "Responde EXCLUSIVAMENTE con JSON valido. Sin markdown, sin texto extra.",
            "messages":    [{"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as cli:
                r = await cli.post(url, json=payload, headers=self._headers)
                if r.status_code == 401:
                    raise LLMProviderError("Anthropic: API key invalida (401)")
                if r.status_code == 429:
                    logger.warning("Anthropic: rate limit (429)")
                    return None
                r.raise_for_status()
                data = r.json()
                content_blocks = data.get("content", [])
                text = "".join(
                    b.get("text", "") for b in content_blocks
                    if b.get("type") == "text"
                )
                if not text:
                    logger.warning("Anthropic: respuesta sin text")
                    return None
                return _parse_json_safe(text)
        except httpx.TimeoutException:
            logger.warning("Anthropic: timeout tras %ss", self.timeout_seconds)
            return None
        except LLMProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Anthropic error inesperado: %s", exc)
            return None

    async def health_check(self) -> dict:
        """Anthropic no tiene endpoint /models publico — hacemos un ping
        enviando un mensaje minimo (~5 tokens). Cuesta una fraccion de
        centavo pero garantiza que la key+modelo funcionan."""
        import time
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.post(
                    f"{self.base_url}/messages",
                    json={
                        "model":      self.model,
                        "max_tokens": 5,
                        "messages":   [{"role": "user", "content": "ping"}],
                    },
                    headers=self._headers,
                )
                r.raise_for_status()
            return {
                "ok":         True,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                # Anthropic no expone /models — devolvemos lista curated comun
                "available_models": [
                    "claude-haiku-4-5",
                    "claude-sonnet-4-6",
                    "claude-opus-4-7",
                    "claude-3-5-sonnet-latest",
                    "claude-3-5-haiku-latest",
                ],
            }
        except httpx.HTTPStatusError as exc:
            return {
                "ok":         False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "error":      f"HTTP {exc.response.status_code} (¿API key valida? ¿modelo correcto?)",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok":         False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "error":      str(exc)[:200],
            }


# ─────────────────────────────────────────────────────────────────────────────
# Gemini (Google)
# ─────────────────────────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ):
        if not api_key:
            raise LLMProviderError("Gemini: api_key vacio")
        if not model:
            raise LLMProviderError("Gemini: model vacio")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def classify_async(self, prompt: str) -> Optional[dict]:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as cli:
                r = await cli.post(url, json=payload)
                if r.status_code == 400:
                    error_msg = ""
                    try:
                        error_msg = r.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    raise LLMProviderError(f"Gemini: Error de API o Modelo (400) — {error_msg or 'Bad Request'}")
                if r.status_code == 403:
                    raise LLMProviderError("Gemini: API key invalida o sin permisos (403)")
                if r.status_code == 429:
                    logger.warning("Gemini: rate limit (429) — reintentar luego")
                    return None
                r.raise_for_status()
                data = r.json()
                
                candidates = data.get("candidates", [])
                if not candidates:
                    logger.warning("Gemini: candidates vacio")
                    return None
                content_parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in content_parts)
                if not text:
                    logger.warning("Gemini: respuesta sin text")
                    return None
                return _parse_json_safe(text)
        except httpx.TimeoutException:
            logger.warning("Gemini: timeout tras %ss", self.timeout_seconds)
            return None
        except LLMProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gemini error inesperado: %s", exc)
            return None

    async def health_check(self) -> dict:
        import time
        t0 = time.perf_counter()
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "ping"}
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 5,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as cli:
                r = await cli.post(url, json=payload)
                if r.status_code == 400:
                    error_msg = ""
                    try:
                        error_msg = r.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    return {
                        "ok":         False,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "model":      self.model,
                        "error":      f"HTTP 400: {error_msg or 'Bad Request'}",
                    }
                r.raise_for_status()
            return {
                "ok":         True,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "available_models": [
                    "gemini-1.5-flash",
                    "gemini-1.5-pro",
                    "gemini-2.0-flash",
                    "gemini-2.5-flash",
                    "gemini-2.0-pro-exp",
                ],
            }
        except httpx.HTTPStatusError as exc:
            return {
                "ok":         False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "error":      f"HTTP {exc.response.status_code} (¿API key valida? ¿modelo correcto?)",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok":         False,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "model":      self.model,
                "error":      str(exc)[:200],
            }


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_provider(config: dict) -> LLMProvider:
    """Devuelve la instancia del proveedor segun la config.

    config esperada:
      {
        "provider":  "ollama" | "openai" | "anthropic" | "gemini",
        "ollama_model":            str opcional (vacio = settings.ollama_model),
        "ollama_base_url":         str opcional (vacio = settings.ollama_base_url),
        "openai_api_key":          str (encriptado en DB, decriptado antes de llamar),
        "openai_model":            str (ej. gpt-4o-mini),
        "anthropic_api_key":       str,
        "anthropic_model":         str (ej. claude-haiku-4-5),
        "gemini_api_key":          str,
        "gemini_model":            str (ej. gemini-1.5-flash),
        "timeout_seconds":         float opcional,
        "temperature":             float opcional,
        "max_tokens":              int opcional,
      }
    """
    provider_name = (config.get("provider") or "ollama").lower()
    timeout = float(config.get("timeout_seconds") or _DEFAULT_TIMEOUT_SECONDS)
    temperature = float(config.get("temperature") if config.get("temperature") is not None else _DEFAULT_TEMPERATURE)
    max_tokens = int(config.get("max_tokens") or _DEFAULT_MAX_TOKENS)

    if provider_name == "ollama":
        base_url = (config.get("ollama_base_url") or "").strip() or settings.ollama_base_url
        model = (config.get("ollama_model") or "").strip() or settings.ollama_model
        return OllamaProvider(
            base_url=base_url, model=model,
            timeout_seconds=timeout, temperature=temperature, max_tokens=max_tokens,
        )

    if provider_name == "openai":
        api_key = (config.get("openai_api_key") or "").strip()
        model = (config.get("openai_model") or "gpt-4o-mini").strip()
        return OpenAIProvider(
            api_key=api_key, model=model,
            timeout_seconds=timeout, temperature=temperature, max_tokens=max_tokens,
        )

    if provider_name == "anthropic":
        api_key = (config.get("anthropic_api_key") or "").strip()
        model = (config.get("anthropic_model") or "claude-haiku-4-5").strip()
        return AnthropicProvider(
            api_key=api_key, model=model,
            timeout_seconds=timeout, temperature=temperature, max_tokens=max_tokens,
        )

    if provider_name == "gemini":
        api_key = (config.get("gemini_api_key") or "").strip()
        model = (config.get("gemini_model") or "gemini-1.5-flash").strip()
        return GeminiProvider(
            api_key=api_key, model=model,
            timeout_seconds=timeout, temperature=temperature, max_tokens=max_tokens,
        )

    raise LLMProviderError(f"Proveedor desconocido: '{provider_name}'")

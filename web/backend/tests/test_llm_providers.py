"""Tests para llm_providers.py — abstraccion multi-proveedor LLM.

Cubre:
- Factory: get_provider devuelve la clase correcta segun config
- _parse_json_safe: tolera JSON puro, markdown fences, texto extra
- OllamaProvider: payload correcto, error 404 = LLMProviderError
- OpenAIProvider: 401 = error duro, 429 = retry, parsing del schema
- AnthropicProvider: 401 = error duro, parsing de content blocks
- Validacion: api_key vacio / model vacio = LLMProviderError

No hace HTTP real — todo mockeado con monkeypatch sobre httpx.AsyncClient.

NOTA: tests de funciones async usan asyncio.run() en vez de @pytest.mark.asyncio
para evitar dependencia de pytest-asyncio en CI (no esta en requirements-dev).
"""
import asyncio

import pytest


# ── _parse_json_safe ──────────────────────────────────────────────────────

def test_parse_json_safe_plain_json():
    from app.services.llm_providers import _parse_json_safe
    assert _parse_json_safe('{"a": 1}') == {"a": 1}


def test_parse_json_safe_markdown_fences():
    from app.services.llm_providers import _parse_json_safe
    raw = '```json\n{"categoria": "spam", "confianza": 0.9}\n```'
    assert _parse_json_safe(raw) == {"categoria": "spam", "confianza": 0.9}


def test_parse_json_safe_with_surrounding_text():
    from app.services.llm_providers import _parse_json_safe
    raw = 'Aqui va el resultado: {"categoria": "consulta_general"} fin.'
    assert _parse_json_safe(raw) == {"categoria": "consulta_general"}


def test_parse_json_safe_invalid_returns_none():
    from app.services.llm_providers import _parse_json_safe
    assert _parse_json_safe("nada de json aqui") is None
    assert _parse_json_safe("") is None


def test_parse_json_safe_nested_objects():
    from app.services.llm_providers import _parse_json_safe
    raw = '{"outer": {"inner": "x"}, "n": 1}'
    assert _parse_json_safe(raw) == {"outer": {"inner": "x"}, "n": 1}


# ── Factory ───────────────────────────────────────────────────────────────

def test_get_provider_returns_ollama_by_default():
    from app.services.llm_providers import OllamaProvider, get_provider
    p = get_provider({"provider": "ollama", "ollama_model": "qwen2.5:7b"})
    assert isinstance(p, OllamaProvider)
    assert p.model == "qwen2.5:7b"


def test_get_provider_returns_openai():
    from app.services.llm_providers import OpenAIProvider, get_provider
    p = get_provider({
        "provider":       "openai",
        "openai_api_key": "sk-test123",
        "openai_model":   "gpt-4o-mini",
    })
    assert isinstance(p, OpenAIProvider)
    assert p.api_key == "sk-test123"
    assert p.model == "gpt-4o-mini"


def test_get_provider_returns_anthropic():
    from app.services.llm_providers import AnthropicProvider, get_provider
    p = get_provider({
        "provider":          "anthropic",
        "anthropic_api_key": "sk-ant-test",
        "anthropic_model":   "claude-haiku-4-5",
    })
    assert isinstance(p, AnthropicProvider)
    assert p.api_key == "sk-ant-test"


def test_get_provider_unknown_raises():
    from app.services.llm_providers import LLMProviderError, get_provider
    with pytest.raises(LLMProviderError, match="desconocido"):
        get_provider({"provider": "magic"})


def test_get_provider_openai_without_key_raises():
    from app.services.llm_providers import LLMProviderError, get_provider
    with pytest.raises(LLMProviderError, match="api_key vacio"):
        get_provider({"provider": "openai", "openai_api_key": "", "openai_model": "gpt-4o-mini"})


def test_get_provider_anthropic_without_key_raises():
    from app.services.llm_providers import LLMProviderError, get_provider
    with pytest.raises(LLMProviderError, match="api_key vacio"):
        get_provider({"provider": "anthropic", "anthropic_api_key": "", "anthropic_model": "claude-haiku-4-5"})


def test_get_provider_returns_gemini():
    from app.services.llm_providers import GeminiProvider, get_provider
    p = get_provider({
        "provider":       "gemini",
        "gemini_api_key": "AIzaSyTest",
        "gemini_model":   "gemini-1.5-flash",
    })
    assert isinstance(p, GeminiProvider)
    assert p.api_key == "AIzaSyTest"
    assert p.model == "gemini-1.5-flash"


def test_get_provider_gemini_without_key_raises():
    from app.services.llm_providers import LLMProviderError, get_provider
    with pytest.raises(LLMProviderError, match="api_key vacio"):
        get_provider({"provider": "gemini", "gemini_api_key": "", "gemini_model": "gemini-1.5-flash"})


# ── OllamaProvider.classify_async (mock httpx) ────────────────────────────

class _FakeAsyncResponse:
    def __init__(self, *, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text
    def json(self):
        return self._json_body
    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            request = httpx.Request("POST", "http://test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("err", request=request, response=response)


class _FakeAsyncClient:
    """Mock minimo de httpx.AsyncClient. La cola de respuestas se consume FIFO."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, url, json=None, headers=None):
        self.requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
        return self._responses.pop(0)
    async def get(self, url, headers=None):
        self.requests.append({"method": "GET", "url": url, "headers": headers})
        return self._responses.pop(0)


def _mock_httpx_client(monkeypatch, responses, target_module="app.services.llm_providers"):
    holder = {"client": None}
    def factory(*args, **kwargs):
        holder["client"] = _FakeAsyncClient(responses)
        return holder["client"]
    monkeypatch.setattr(f"{target_module}.httpx.AsyncClient", factory)
    return holder


def test_ollama_classify_happy_path(monkeypatch):
    from app.services.llm_providers import OllamaProvider
    holder = _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={"response": '{"categoria": "cliente_potencial", "confianza": 0.91}'}),
    ])
    provider = OllamaProvider(base_url="http://ollama:11434", model="qwen2.5:7b")
    result = asyncio.run(provider.classify_async("dummy prompt"))
    assert result == {"categoria": "cliente_potencial", "confianza": 0.91}
    # Verifica payload
    req = holder["client"].requests[0]
    assert req["url"] == "http://ollama:11434/api/generate"
    assert req["json"]["model"] == "qwen2.5:7b"
    assert req["json"]["format"] == "json"


def test_ollama_classify_404_raises_provider_error(monkeypatch):
    """Modelo no instalado → error duro (no reintentar)."""
    from app.services.llm_providers import LLMProviderError, OllamaProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(status_code=404, json_body={}),
    ])
    provider = OllamaProvider(base_url="http://ollama:11434", model="phantom-model")
    with pytest.raises(LLMProviderError, match="no esta instalado"):
        asyncio.run(provider.classify_async("p"))


# ── OpenAIProvider ────────────────────────────────────────────────────────

def test_openai_classify_happy_path(monkeypatch):
    from app.services.llm_providers import OpenAIProvider
    holder = _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={
            "choices": [{
                "message": {"content": '{"categoria": "spam", "confianza": 0.95}'},
            }],
        }),
    ])
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    result = asyncio.run(provider.classify_async("p"))
    assert result == {"categoria": "spam", "confianza": 0.95}
    req = holder["client"].requests[0]
    assert req["url"].endswith("/chat/completions")
    assert req["headers"]["Authorization"] == "Bearer sk-test"
    assert req["json"]["response_format"] == {"type": "json_object"}


def test_openai_401_raises_provider_error(monkeypatch):
    from app.services.llm_providers import LLMProviderError, OpenAIProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(status_code=401, json_body={}),
    ])
    provider = OpenAIProvider(api_key="sk-bad", model="gpt-4o-mini")
    with pytest.raises(LLMProviderError, match="API key invalida"):
        asyncio.run(provider.classify_async("p"))


def test_openai_429_returns_none_for_retry(monkeypatch):
    """Rate limit → soft fail (None), no excepcion. El caller decide reintentar."""
    from app.services.llm_providers import OpenAIProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(status_code=429, json_body={}),
    ])
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    result = asyncio.run(provider.classify_async("p"))
    assert result is None


# ── AnthropicProvider ─────────────────────────────────────────────────────

def test_anthropic_classify_happy_path(monkeypatch):
    from app.services.llm_providers import AnthropicProvider
    holder = _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={
            "content": [
                {"type": "text", "text": '{"categoria": "cliente_potencial", "confianza": 0.88}'},
            ],
        }),
    ])
    provider = AnthropicProvider(api_key="sk-ant-x", model="claude-haiku-4-5")
    result = asyncio.run(provider.classify_async("p"))
    assert result == {"categoria": "cliente_potencial", "confianza": 0.88}
    req = holder["client"].requests[0]
    assert req["url"].endswith("/messages")
    assert req["headers"]["x-api-key"] == "sk-ant-x"
    assert req["headers"]["anthropic-version"] == "2023-06-01"


def test_anthropic_concatenates_multiple_text_blocks(monkeypatch):
    from app.services.llm_providers import AnthropicProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={
            "content": [
                {"type": "text", "text": '{"categoria": '},
                {"type": "text", "text": '"spam"}'},
            ],
        }),
    ])
    provider = AnthropicProvider(api_key="sk-ant", model="claude-haiku-4-5")
    result = asyncio.run(provider.classify_async("p"))
    assert result == {"categoria": "spam"}


def test_anthropic_401_raises_provider_error(monkeypatch):
    from app.services.llm_providers import AnthropicProvider, LLMProviderError
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(status_code=401, json_body={}),
    ])
    provider = AnthropicProvider(api_key="sk-bad", model="claude-haiku-4-5")
    with pytest.raises(LLMProviderError, match="API key invalida"):
        asyncio.run(provider.classify_async("p"))


# ── GeminiProvider ────────────────────────────────────────────────────────

def test_gemini_classify_happy_path(monkeypatch):
    from app.services.llm_providers import GeminiProvider
    holder = _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={
            "candidates": [{
                "content": {
                    "parts": [{"text": '{"categoria": "consulta_general", "confianza": 0.90}'}],
                },
            }],
        }),
    ])
    provider = GeminiProvider(api_key="AIzaSyTest", model="gemini-1.5-flash")
    result = asyncio.run(provider.classify_async("p"))
    assert result == {"categoria": "consulta_general", "confianza": 0.90}
    req = holder["client"].requests[0]
    assert req["url"].endswith("models/gemini-1.5-flash:generateContent?key=AIzaSyTest")
    assert req["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_400_raises_provider_error(monkeypatch):
    from app.services.llm_providers import GeminiProvider, LLMProviderError
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(status_code=400, json_body={"error": {"message": "Invalid API key"}}),
    ])
    provider = GeminiProvider(api_key="AIzaSyBad", model="gemini-1.5-flash")
    with pytest.raises(LLMProviderError, match="Error de API o Modelo"):
        asyncio.run(provider.classify_async("p"))


def test_gemini_429_returns_none_for_retry(monkeypatch):
    from app.services.llm_providers import GeminiProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(status_code=429, json_body={}),
    ])
    provider = GeminiProvider(api_key="AIzaSyTest", model="gemini-1.5-flash")
    result = asyncio.run(provider.classify_async("p"))
    assert result is None


# ── health_check ───────────────────────────────────────────────────────────

def test_ollama_health_returns_models_list(monkeypatch):
    from app.services.llm_providers import OllamaProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={
            "models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2"}],
        }),
    ])
    provider = OllamaProvider(base_url="http://o:11434", model="qwen2.5:7b")
    result = asyncio.run(provider.health_check())
    assert result["ok"] is True
    assert result["model_installed"] is True
    assert "qwen2.5:7b" in result["available_models"]


def test_ollama_health_detects_missing_model(monkeypatch):
    from app.services.llm_providers import OllamaProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={"models": [{"name": "llama3.2"}]}),
    ])
    provider = OllamaProvider(base_url="http://o:11434", model="qwen2.5:7b")
    result = asyncio.run(provider.health_check())
    assert result["ok"] is True
    assert result["model_installed"] is False  # qwen no esta en la lista


def test_gemini_health(monkeypatch):
    from app.services.llm_providers import GeminiProvider
    _mock_httpx_client(monkeypatch, [
        _FakeAsyncResponse(json_body={
            "candidates": [{"content": {"parts": [{"text": "pong"}]}}]
        }),
    ])
    provider = GeminiProvider(api_key="AIzaSyTest", model="gemini-1.5-flash")
    result = asyncio.run(provider.health_check())
    assert result["ok"] is True
    assert "gemini-1.5-flash" in result["available_models"]
    assert result["model"] == "gemini-1.5-flash"

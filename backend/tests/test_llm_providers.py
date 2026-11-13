"""Seleção de provider (LLM_PROVIDER) e provider compatível com a OpenAI.

Nenhum teste chama uma API real: o SDK da OpenAI é trocado por um fake que
registra os argumentos recebidos.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app import config
from app.core import llm


@pytest.fixture
def fake_openai(monkeypatch):
    """Substitui openai.AsyncOpenAI e devolve um dict com o que foi recebido."""
    import openai

    captured: dict = {"client": None, "create": None, "closed": False}

    class FakeCompletions:
        async def create(self, **kw):
            captured["create"] = kw
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='  {"ok": true}  '))],
                model="modelo-do-servidor",
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kw):
            captured["client"] = kw
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    return captured


@pytest.fixture
def compat_settings(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(config.settings, "openai_compatible_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(config.settings, "openai_compatible_api_key", "")
    monkeypatch.setattr(config.settings, "openai_compatible_model", "llama3.1")
    monkeypatch.setattr(config.settings, "openai_compatible_json_mode", False)


# --- Configuração --------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("openai", "openai"),
        ("OpenAI", "openai"),
        (" anthropic ", "anthropic"),
        ("openai_compatible", "openai_compatible"),
        ("OpenAI-Compatible", "openai_compatible"),
        ("", "openai"),
    ],
)
def test_llm_provider_e_normalizado(valor, esperado):
    assert config.Settings(llm_provider=valor).llm_provider == esperado


def test_llm_provider_desconhecido_falha_na_inicializacao():
    # Antes, qualquer valor desconhecido caía silenciosamente na OpenAI.
    with pytest.raises(ValidationError):
        config.Settings(llm_provider="gemini")


# --- get_provider ---------------------------------------------------------------


def test_get_provider_respeita_llm_provider(monkeypatch, compat_settings):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    assert type(llm.get_provider()) is llm.OpenAIProvider

    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    assert type(llm.get_provider()) is llm.AnthropicProvider

    monkeypatch.setattr(config.settings, "llm_provider", "openai_compatible")
    provider = llm.get_provider()
    assert type(provider) is llm.OpenAIProvider
    assert provider._base_url == "http://localhost:11434/v1"


def test_compativel_sem_base_url_da_erro_claro(monkeypatch, compat_settings):
    monkeypatch.setattr(config.settings, "openai_compatible_base_url", "  ")
    with pytest.raises(llm.LLMError, match="OPENAI_COMPATIBLE_BASE_URL não configurada"):
        llm.get_provider()


def test_compativel_sem_modelo_da_erro_claro(monkeypatch, compat_settings):
    monkeypatch.setattr(config.settings, "openai_compatible_model", "")
    with pytest.raises(llm.LLMError, match="OPENAI_COMPATIBLE_MODEL não configurado"):
        llm.get_provider()


# --- Chamada ao SDK -------------------------------------------------------------


def test_compativel_usa_base_url_sem_exigir_chave(fake_openai, compat_settings):
    result = asyncio.run(
        llm.get_provider().chat(
            system_prompt="sistema",
            user_content="usuario",
            json_mode=True,
            max_output_tokens=500,
        )
    )

    assert fake_openai["client"]["base_url"] == "http://localhost:11434/v1"
    assert fake_openai["client"]["api_key"]  # placeholder: o SDK recusa chave vazia
    create = fake_openai["create"]
    assert create["model"] == "llama3.1"
    # modo JSON desligado: nada de response_format, o JSON é pedido no prompt
    assert "response_format" not in create
    assert create["messages"][0]["content"].endswith(llm.JSON_INSTRUCTION)
    # compatíveis usam o parâmetro clássico
    assert create["max_tokens"] == 500
    assert "max_completion_tokens" not in create
    assert fake_openai["closed"] is True
    assert result.text == '{"ok": true}'
    assert (result.input_tokens, result.output_tokens) == (11, 7)


def test_compativel_com_json_mode_nativo(monkeypatch, fake_openai, compat_settings):
    monkeypatch.setattr(config.settings, "openai_compatible_json_mode", True)
    monkeypatch.setattr(config.settings, "openai_compatible_api_key", "gsk_123")

    asyncio.run(llm.get_provider().chat(system_prompt="s", user_content="u", json_mode=True))

    assert fake_openai["client"]["api_key"] == "gsk_123"
    assert fake_openai["create"]["response_format"] == {"type": "json_object"}
    assert fake_openai["create"]["messages"][0]["content"] == "s"


def test_openai_oficial_mantem_comportamento(monkeypatch, fake_openai):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-x")
    monkeypatch.setattr(config.settings, "openai_model", "gpt-4o-mini")

    asyncio.run(
        llm.get_provider().chat(system_prompt="s", user_content="u", json_mode=True, max_output_tokens=100)
    )

    assert "base_url" not in fake_openai["client"]
    assert fake_openai["create"]["response_format"] == {"type": "json_object"}
    assert fake_openai["create"]["max_completion_tokens"] == 100
    assert "max_tokens" not in fake_openai["create"]


def test_openai_oficial_sem_chave_continua_exigindo(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", "")
    with pytest.raises(llm.LLMError, match="OPENAI_API_KEY não configurada"):
        asyncio.run(llm.get_provider().chat(system_prompt="s", user_content="u"))


def test_timeout_por_chamada_sobrescreve_o_padrao(monkeypatch, fake_openai):
    monkeypatch.setattr(config.settings, "llm_timeout_seconds", 120.0)
    provider = llm.OpenAIProvider(api_key="k", model="m")
    asyncio.run(provider.chat(system_prompt="s", user_content="u", timeout_seconds=180.0))
    assert fake_openai["client"]["timeout"] == 180.0


def test_erro_do_compativel_cita_o_provider_e_o_timeout_real(monkeypatch, compat_settings):
    import openai

    class FakeCompletions:
        async def create(self, **_kw):
            raise openai.APITimeoutError(request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"))

    class FakeAsyncOpenAI:
        def __init__(self, **_kw):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    with pytest.raises(llm.LLMError, match=r"A IA \(API compatível com OpenAI\) não respondeu em 180 s\."):
        asyncio.run(llm.get_provider().chat(system_prompt="s", user_content="u", timeout_seconds=180.0))


def test_modelo_inexistente_vira_mensagem_clara():
    import openai

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    error = openai.NotFoundError("not found", response=httpx.Response(404, request=request), body=None)
    msg = llm.describe_llm_error(error, llm.OPENAI_COMPATIBLE_NAME)
    assert "Modelo ou endpoint não encontrado" in msg

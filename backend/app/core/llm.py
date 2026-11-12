"""Camada de provider de LLM usada pelos agentes.

Os serviços legados (ai_openai.py) continuam funcionando para os endpoints
síncronos antigos; todo agente novo usa esta camada, que é assíncrona e
plugável entre providers (OpenAI / Anthropic) via settings.llm_provider.

Cada chamada tem timeout próprio (LLM_TIMEOUT_SECONDS) e no máximo
LLM_MAX_RETRIES novas tentativas; erros do SDK viram LLMError com mensagem
legível para o usuário (ver describe_llm_error).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import settings


class LLMError(Exception):
    pass


_KEY_VARS = {"OpenAI": "OPENAI_API_KEY", "Anthropic": "ANTHROPIC_API_KEY"}


def describe_llm_error(error: BaseException, provider: str) -> str:
    """Mensagem clara para erros dos SDKs da OpenAI/Anthropic (mesmos nomes de classe)."""
    kind = type(error).__name__
    if kind == "APITimeoutError" or isinstance(error, TimeoutError):
        return f"A IA ({provider}) não respondeu em {settings.llm_timeout_seconds:g} s."
    if kind == "AuthenticationError":
        return f"A chave da {provider} ({_KEY_VARS.get(provider, 'API key')}) é inválida ou foi revogada."
    if kind == "PermissionDeniedError":
        return f"A chave da {provider} não tem permissão para usar o modelo configurado."
    if kind == "RateLimitError":
        return f"Limite de uso da {provider} atingido (taxa ou cota). Tente novamente em instantes."
    if kind == "APIConnectionError":
        return f"Não foi possível conectar à API da {provider}. Verifique a rede."
    return f"Erro na API da {provider}: {error}"


@dataclass
class ChatResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    async def chat(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_mode: bool = False,
        max_output_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> ChatResult: ...


class OpenAIProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def chat(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_mode: bool = False,
        max_output_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> ChatResult:
        from openai import AsyncOpenAI

        if not self._api_key:
            raise LLMError("OPENAI_API_KEY não configurada.")
        client = AsyncOpenAI(
            api_key=self._api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if max_output_tokens is not None:
            kwargs["max_completion_tokens"] = max_output_tokens
        try:
            completion = await client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001 — normaliza qualquer erro do SDK
            raise LLMError(describe_llm_error(e, "OpenAI")) from e
        text = (completion.choices[0].message.content or "").strip()
        if not text:
            raise LLMError("Resposta vazia da API de IA.")
        usage = completion.usage
        return ChatResult(
            text=text,
            model=completion.model or self._model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


class AnthropicProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def chat(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_mode: bool = False,
        max_output_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> ChatResult:
        from anthropic import AsyncAnthropic

        if not self._api_key:
            raise LLMError("ANTHROPIC_API_KEY não configurada.")
        client = AsyncAnthropic(
            api_key=self._api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        system = system_prompt
        if json_mode:
            system += "\n\nResponda APENAS com um objeto JSON válido, sem markdown em volta."
        try:
            message = await client.messages.create(
                model=self._model,
                max_tokens=max_output_tokens or settings.agent_max_output_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as e:  # noqa: BLE001
            raise LLMError(describe_llm_error(e, "Anthropic")) from e
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        if not text:
            raise LLMError("Resposta vazia da API de IA.")
        return ChatResult(
            text=text,
            model=message.model or self._model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


def get_provider() -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)

"""Camada de provider de LLM usada pelos agentes.

Os serviços legados (ai_openai.py) continuam funcionando para os endpoints
síncronos antigos; todo agente novo usa esta camada, que é assíncrona e
plugável entre providers (OpenAI / Anthropic) via settings.llm_provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import settings


class LLMError(Exception):
    pass


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
        client = AsyncOpenAI(api_key=self._api_key, timeout=settings.agent_timeout_seconds)
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
            raise LLMError(str(e)) from e
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
        client = AsyncAnthropic(api_key=self._api_key, timeout=settings.agent_timeout_seconds)
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
            raise LLMError(str(e)) from e
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

"""Camada de provider de LLM usada por toda a aplicação.

Agentes (assíncronos) chamam get_provider() diretamente. Os endpoints síncronos
clássicos (geração, avaliação de commit, template a partir de exemplo) passam
por app.services.ai_text, que usa esta mesma camada. Assim, LLM_PROVIDER vale
para tudo.

Providers disponíveis (settings.llm_provider):
  - "openai":            API oficial da OpenAI
  - "anthropic":         API da Anthropic
  - "openai_compatible": qualquer API compatível com a Chat Completions da OpenAI
                         (Groq, Gemini, OpenRouter, Ollama, LM Studio, vLLM...)

Cada chamada tem timeout próprio (LLM_TIMEOUT_SECONDS, ou o timeout_seconds
passado na chamada) e no máximo LLM_MAX_RETRIES novas tentativas; erros do SDK
viram LLMError com mensagem legível para o usuário (ver describe_llm_error).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import settings


class LLMError(Exception):
    pass


OPENAI_COMPATIBLE_NAME = "API compatível com OpenAI"

_KEY_VARS = {
    "OpenAI": "OPENAI_API_KEY",
    "Anthropic": "ANTHROPIC_API_KEY",
    OPENAI_COMPATIBLE_NAME: "OPENAI_COMPATIBLE_API_KEY",
}

# Instrução usada quando o provider não tem modo JSON nativo (ou ele está desligado).
JSON_INSTRUCTION = "\n\nResponda APENAS com um objeto JSON válido, sem markdown em volta."


def describe_llm_error(error: BaseException, provider: str, *, timeout_seconds: float | None = None) -> str:
    """Mensagem clara para erros dos SDKs da OpenAI/Anthropic (mesmos nomes de classe)."""
    kind = type(error).__name__
    if kind == "APITimeoutError" or isinstance(error, TimeoutError):
        timeout = timeout_seconds or settings.llm_timeout_seconds
        return f"A IA ({provider}) não respondeu em {timeout:g} s."
    if kind == "AuthenticationError":
        return f"A chave da {provider} ({_KEY_VARS.get(provider, 'API key')}) é inválida ou foi revogada."
    if kind == "PermissionDeniedError":
        return f"A chave da {provider} não tem permissão para usar o modelo configurado."
    if kind == "RateLimitError":
        return f"Limite de uso da {provider} atingido (taxa ou cota). Tente novamente em instantes."
    if kind == "APIConnectionError":
        return f"Não foi possível conectar à API da {provider}. Verifique a rede."
    if kind == "NotFoundError":
        return f"Modelo ou endpoint não encontrado na {provider}. Confira o nome do modelo e a URL base."
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
        timeout_seconds: float | None = None,
    ) -> ChatResult: ...


async def _close_quietly(client: object) -> None:
    close = getattr(client, "close", None)
    if close is not None:
        try:
            await close()
        except Exception:  # noqa: BLE001 — fechar a conexão nunca deve mascarar o resultado
            pass


class OpenAIProvider:
    """Provider para a API oficial da OpenAI e para APIs compatíveis com ela.

    Os parâmetros extras existem para o modo compatível (ver openai_compatible_provider):
      base_url          endpoint alternativo (None = api.openai.com)
      name              nome usado nas mensagens de erro
      require_api_key   servidores locais (Ollama, LM Studio) não exigem chave
      native_json_mode  envia response_format=json_object; se False, pede JSON no prompt
      max_tokens_param  "max_completion_tokens" (OpenAI) ou "max_tokens" (compatíveis)
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        name: str = "OpenAI",
        require_api_key: bool = True,
        native_json_mode: bool = True,
        max_tokens_param: str = "max_completion_tokens",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._name = name
        self._require_api_key = require_api_key
        self._native_json_mode = native_json_mode
        self._max_tokens_param = max_tokens_param

    async def chat(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_mode: bool = False,
        max_output_tokens: int | None = None,
        temperature: float = 0.3,
        timeout_seconds: float | None = None,
    ) -> ChatResult:
        from openai import AsyncOpenAI

        if not self._api_key and self._require_api_key:
            raise LLMError(f"{_KEY_VARS.get(self._name, 'API key')} não configurada.")
        if not self._model:
            raise LLMError(f"Nenhum modelo configurado para a {self._name}.")

        client_kwargs: dict = {
            # O SDK recusa chave vazia; servidores locais ignoram o valor.
            "api_key": self._api_key or "nao-necessaria",
            "timeout": timeout_seconds or settings.llm_timeout_seconds,
            "max_retries": settings.llm_max_retries,
        }
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        client = AsyncOpenAI(**client_kwargs)

        system = system_prompt
        if json_mode and not self._native_json_mode:
            system += JSON_INSTRUCTION
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }
        if json_mode and self._native_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if max_output_tokens is not None:
            kwargs[self._max_tokens_param] = max_output_tokens
        try:
            completion = await client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001 — normaliza qualquer erro do SDK
            raise LLMError(describe_llm_error(e, self._name, timeout_seconds=timeout_seconds)) from e
        finally:
            await _close_quietly(client)
        if not completion.choices:
            raise LLMError("Resposta vazia da API de IA.")
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
        timeout_seconds: float | None = None,
    ) -> ChatResult:
        from anthropic import AsyncAnthropic

        if not self._api_key:
            raise LLMError("ANTHROPIC_API_KEY não configurada.")
        client = AsyncAnthropic(
            api_key=self._api_key,
            timeout=timeout_seconds or settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        system = system_prompt
        if json_mode:
            system += JSON_INSTRUCTION
        try:
            message = await client.messages.create(
                model=self._model,
                max_tokens=max_output_tokens or settings.agent_max_output_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as e:  # noqa: BLE001
            raise LLMError(describe_llm_error(e, "Anthropic", timeout_seconds=timeout_seconds)) from e
        finally:
            await _close_quietly(client)
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        if not text:
            raise LLMError("Resposta vazia da API de IA.")
        return ChatResult(
            text=text,
            model=message.model or self._model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


def openai_compatible_provider() -> OpenAIProvider:
    """Provider para APIs compatíveis com a OpenAI (LLM_PROVIDER=openai_compatible)."""
    base_url = settings.openai_compatible_base_url.strip()
    if not base_url:
        raise LLMError(
            "OPENAI_COMPATIBLE_BASE_URL não configurada. Exemplos: "
            "https://api.groq.com/openai/v1, https://openrouter.ai/api/v1, "
            "http://localhost:11434/v1 (Ollama)."
        )
    if not settings.openai_compatible_model.strip():
        raise LLMError("OPENAI_COMPATIBLE_MODEL não configurado.")
    return OpenAIProvider(
        api_key=settings.openai_compatible_api_key.strip(),
        model=settings.openai_compatible_model.strip(),
        base_url=base_url,
        name=OPENAI_COMPATIBLE_NAME,
        require_api_key=False,
        native_json_mode=settings.openai_compatible_json_mode,
        # "max_completion_tokens" é recente; os compatíveis aceitam o clássico "max_tokens".
        max_tokens_param="max_tokens",
    )


def get_provider() -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    if settings.llm_provider == "openai_compatible":
        return openai_compatible_provider()
    return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)

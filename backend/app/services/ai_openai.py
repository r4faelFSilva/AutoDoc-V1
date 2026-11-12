from openai import OpenAI

from app.config import settings
from app.core.llm import describe_llm_error


class AIServiceError(Exception):
    pass


def _client(timeout_seconds: float | None) -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=timeout_seconds or settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def generate_json(
    *,
    system_prompt: str,
    user_content: str,
    timeout_seconds: float | None = None,
    max_completion_tokens: int | None = None,
) -> str:
    """Chama a API com response_format=json_object (resposta garantida como JSON)."""
    if not settings.openai_api_key:
        raise AIServiceError("OPENAI_API_KEY não configurada.")
    client = _client(timeout_seconds)
    try:
        kwargs: dict = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = max_completion_tokens
        completion = client.chat.completions.create(**kwargs)
        choice = completion.choices[0].message
        text = (choice.content or "").strip()
        if not text:
            raise AIServiceError("Resposta vazia da API de IA.")
        return text
    except AIServiceError:
        raise
    except Exception as e:
        raise AIServiceError(describe_llm_error(e, "OpenAI")) from e


def generate_markdown(
    *,
    system_prompt: str,
    user_content: str,
    timeout_seconds: float | None = None,
    max_completion_tokens: int | None = None,
) -> str:
    if not settings.openai_api_key:
        raise AIServiceError("OPENAI_API_KEY não configurada.")
    client = _client(timeout_seconds)
    try:
        kwargs: dict = {
            "model": settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
        }
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = max_completion_tokens
        completion = client.chat.completions.create(**kwargs)
        choice = completion.choices[0].message
        text = (choice.content or "").strip()
        if not text:
            raise AIServiceError("Resposta vazia da API de IA.")
        return text
    except AIServiceError:
        raise
    except Exception as e:
        raise AIServiceError(describe_llm_error(e, "OpenAI")) from e

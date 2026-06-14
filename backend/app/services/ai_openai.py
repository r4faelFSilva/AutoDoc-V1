from openai import OpenAI

from app.config import settings


class AIServiceError(Exception):
    pass


def generate_markdown(
    *,
    system_prompt: str,
    user_content: str,
    timeout_seconds: float = 120.0,
    max_completion_tokens: int | None = None,
) -> str:
    if not settings.openai_api_key:
        raise AIServiceError("OPENAI_API_KEY não configurada.")
    client = OpenAI(api_key=settings.openai_api_key, timeout=timeout_seconds)
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
        raise AIServiceError(str(e)) from e

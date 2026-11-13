"""Chamadas síncronas à IA usadas pelos endpoints clássicos.

Antes, este papel era do ai_openai.py, que falava só com a OpenAI e ignorava
LLM_PROVIDER. Agora tudo passa por app.core.llm.get_provider(), a mesma camada
dos agentes: OpenAI, Anthropic ou qualquer API compatível com a OpenAI.

Os routers clássicos são funções síncronas (o FastAPI as executa num thread
pool, sem event loop), então basta asyncio.run. Se algum dia forem chamadas de
dentro de um event loop, a corrotina roda numa thread separada para não
bloquear nem quebrar o loop atual.
"""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, TypeVar

from app.core import llm

T = TypeVar("T")


class AIServiceError(Exception):
    pass


def _run_sync(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _chat(
    *,
    system_prompt: str,
    user_content: str,
    json_mode: bool,
    temperature: float,
    timeout_seconds: float | None,
    max_completion_tokens: int | None,
) -> str:
    kwargs: dict[str, Any] = {
        "system_prompt": system_prompt,
        "user_content": user_content,
        "json_mode": json_mode,
        "temperature": temperature,
        "max_output_tokens": max_completion_tokens,
    }
    # Só repassa quando definido: providers de terceiros (e fakes de teste) podem
    # não aceitar o argumento.
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds
    try:
        provider = llm.get_provider()
        result = _run_sync(provider.chat(**kwargs))
    except llm.LLMError as e:
        raise AIServiceError(str(e)) from e
    text = (result.text or "").strip()
    if not text:
        raise AIServiceError("Resposta vazia da API de IA.")
    return text


def generate_markdown(
    *,
    system_prompt: str,
    user_content: str,
    timeout_seconds: float | None = None,
    max_completion_tokens: int | None = None,
) -> str:
    return _chat(
        system_prompt=system_prompt,
        user_content=user_content,
        json_mode=False,
        temperature=0.3,
        timeout_seconds=timeout_seconds,
        max_completion_tokens=max_completion_tokens,
    )


def generate_json(
    *,
    system_prompt: str,
    user_content: str,
    timeout_seconds: float | None = None,
    max_completion_tokens: int | None = None,
) -> str:
    """Pede uma resposta JSON. Use parse_json_object no retorno: providers sem modo
    JSON nativo (Anthropic, muitos compatíveis) podem envolver o JSON em ```json."""
    return _chat(
        system_prompt=system_prompt,
        user_content=user_content,
        json_mode=True,
        temperature=0.2,
        timeout_seconds=timeout_seconds,
        max_completion_tokens=max_completion_tokens,
    )


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def parse_json_object(raw: str) -> dict:
    """Extrai um objeto JSON de forma tolerante.

    Ordem: JSON puro → bloco ```json ...``` → trecho entre o primeiro '{' e o
    último '}' (cobre texto antes/depois do JSON). Levanta ValueError se nada
    for um objeto JSON válido.
    """
    text = (raw or "").strip()
    candidates = [text]
    m = _JSON_FENCE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("Resposta da IA não contém um objeto JSON válido.")

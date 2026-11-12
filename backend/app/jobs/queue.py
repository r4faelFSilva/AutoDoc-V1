"""Enfileiramento de runs de agente.

Com REDIS_URL configurado, o run vai para a fila arq e é consumido pelo
worker (processo separado — ver jobs/worker.py). Sem Redis (modo fallback),
o run executa in-process como task asyncio no próprio event loop da API.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Referências das tasks in-process, para não serem coletadas pelo GC.
_background_tasks: set[asyncio.Task] = set()


def _on_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        # execute_agent_run já registra falhas no run; isto pega o que escapar dele.
        logger.error("Task de run de agente terminou com exceção não tratada.", exc_info=exc)


async def enqueue_agent_run(run_id: int, github_token: str | None = None) -> str:
    """Enfileira a execução do run. Retorna o modo usado ("arq" ou "local").

    github_token (do usuário) não é gravado no banco; no modo arq ele trafega
    nos argumentos do job no Redis até o worker consumi-lo.
    """
    if settings.redis_url:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await pool.enqueue_job("execute_agent_run", run_id, github_token)
        finally:
            await pool.aclose()
        return "arq"

    from app.jobs import tasks

    task = asyncio.create_task(tasks.execute_agent_run(None, run_id, github_token))
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return "local"

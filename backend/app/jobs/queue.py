"""Enfileiramento de runs de agente.

Com REDIS_URL configurado, o run vai para a fila arq e é consumido pelo
worker (processo separado — ver jobs/worker.py). Sem Redis (modo fallback),
o run executa in-process como task asyncio no próprio event loop da API.
"""

from __future__ import annotations

import asyncio

from app.config import settings

# Referências das tasks in-process, para não serem coletadas pelo GC.
_background_tasks: set[asyncio.Task] = set()


async def enqueue_agent_run(run_id: int) -> str:
    """Enfileira a execução do run. Retorna o modo usado ("arq" ou "local")."""
    if settings.redis_url:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await pool.enqueue_job("execute_agent_run", run_id)
        finally:
            await pool.aclose()
        return "arq"

    from app.jobs import tasks

    task = asyncio.create_task(tasks.execute_agent_run(None, run_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return "local"

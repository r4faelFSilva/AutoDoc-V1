"""Entrypoint do worker arq (modo Compose/Redis).

Rodar com:  arq app.jobs.worker.WorkerSettings
Requer REDIS_URL configurado. No modo fallback (sem Redis) este processo não
é necessário — os jobs rodam in-process na API.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arq.connections import RedisSettings

import app.agents  # noqa: F401 — registra os agentes no registry
from app.config import settings
from app.jobs.tasks import execute_agent_run, fail_orphan_runs

# O limite do run é aplicado dentro de execute_agent_run; o do arq é só a rede de segurança.
_MAX_RUN_SECONDS = int(max(settings.agent_run_timeout_seconds, settings.agent_run_timeout_deep_seconds)) + 60


async def startup(_ctx) -> None:
    # Runs "running" mais antigos que o maior limite possível ficaram órfãos
    # (worker anterior caiu no meio). Runs mais novos podem estar em outro worker.
    fail_orphan_runs(started_before=datetime.utcnow() - timedelta(seconds=_MAX_RUN_SECONDS))


class WorkerSettings:
    functions = [execute_agent_run]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")
    max_jobs = 4
    job_timeout = _MAX_RUN_SECONDS
    # O status do run vive no banco; não guardar resultados do arq evita que os
    # argumentos do job (que podem incluir o token do GitHub do usuário) fiquem no Redis.
    keep_result = 0

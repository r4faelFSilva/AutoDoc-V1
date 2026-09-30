"""Entrypoint do worker arq (modo Compose/Redis).

Rodar com:  arq app.jobs.worker.WorkerSettings
Requer REDIS_URL configurado. No modo fallback (sem Redis) este processo não
é necessário — os jobs rodam in-process na API.
"""

from __future__ import annotations

from arq.connections import RedisSettings

import app.agents  # noqa: F401 — registra os agentes no registry
from app.config import settings
from app.jobs.tasks import execute_agent_run


class WorkerSettings:
    functions = [execute_agent_run]
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")
    max_jobs = 4
    job_timeout = int(settings.agent_timeout_seconds) + 60

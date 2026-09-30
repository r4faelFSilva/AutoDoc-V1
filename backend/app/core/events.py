"""Publicação e assinatura de eventos de progresso de runs.

Dois backends com a mesma interface:
- LocalEventBus: filas asyncio in-process (modo fallback, sem Redis).
- RedisEventBus: pub/sub no Redis (modo Compose, API e worker em processos
  separados).

Todo evento também é persistido em run_events (ver jobs/tasks.emit), então o
SSE consegue reproduzir o histórico ao conectar e seguir ao vivo pelo bus.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.config import settings


class EventBus(Protocol):
    async def publish(self, run_id: int, event: dict[str, Any]) -> None: ...

    def subscribe(self, run_id: int) -> AsyncIterator[dict[str, Any]]: ...


class LocalEventBus:
    def __init__(self) -> None:
        self._queues: dict[int, list[asyncio.Queue]] = {}

    async def publish(self, run_id: int, event: dict[str, Any]) -> None:
        for q in self._queues.get(run_id, []):
            q.put_nowait(event)

    async def _iter(self, run_id: int) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(run_id, []).append(q)
        try:
            while True:
                yield await q.get()
        finally:
            subs = self._queues.get(run_id, [])
            with contextlib.suppress(ValueError):
                subs.remove(q)
            if not subs:
                self._queues.pop(run_id, None)

    def subscribe(self, run_id: int) -> AsyncIterator[dict[str, Any]]:
        return self._iter(run_id)


class RedisEventBus:
    def __init__(self, url: str) -> None:
        self._url = url

    def _channel(self, run_id: int) -> str:
        return f"autodoc:run:{run_id}"

    async def publish(self, run_id: int, event: dict[str, Any]) -> None:
        import redis.asyncio as aioredis

        client = aioredis.from_url(self._url)
        try:
            await client.publish(self._channel(run_id), json.dumps(event, ensure_ascii=False))
        finally:
            await client.aclose()

    async def _iter(self, run_id: int) -> AsyncIterator[dict[str, Any]]:
        import redis.asyncio as aioredis

        client = aioredis.from_url(self._url)
        pubsub = client.pubsub()
        await pubsub.subscribe(self._channel(run_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                with contextlib.suppress(json.JSONDecodeError):
                    yield json.loads(message["data"])
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(self._channel(run_id))
                await pubsub.aclose()
            await client.aclose()

    def subscribe(self, run_id: int) -> AsyncIterator[dict[str, Any]]:
        return self._iter(run_id)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = RedisEventBus(settings.redis_url) if settings.redis_url else LocalEventBus()
    return _bus

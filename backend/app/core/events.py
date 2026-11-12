"""Publicação e assinatura de eventos de progresso de runs.

Dois backends com a mesma interface:
- LocalEventBus: filas asyncio in-process (modo fallback, sem Redis).
- RedisEventBus: pub/sub no Redis (modo Compose, API e worker em processos
  separados).

Todo evento também é persistido em run_events (ver jobs/tasks.emit), então o
SSE consegue reproduzir o histórico ao conectar e seguir ao vivo pelo bus.

A assinatura é registrada já em `await bus.subscribe(...)` (antes de o SSE ler o
histórico, para nenhum evento se perder no meio) e entrega eventos por
`await subscription.get()`. Cancelar um `get()` — por exemplo num
`asyncio.wait_for` com timeout de keep-alive — não encerra a assinatura.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.config import settings


class Subscription(Protocol):
    async def get(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class EventBus(Protocol):
    async def publish(self, run_id: int, event: dict[str, Any]) -> None: ...

    async def subscribe(self, run_id: int) -> Subscription: ...


class _QueueSubscription:
    """Assinatura baseada numa asyncio.Queue; `get()` é seguro de cancelar."""

    def __init__(self, queue: asyncio.Queue, on_close: Callable[[], Awaitable[None]]) -> None:
        self._queue = queue
        self._on_close = on_close

    async def get(self) -> dict[str, Any]:
        return await self._queue.get()

    async def close(self) -> None:
        await self._on_close()


class LocalEventBus:
    def __init__(self) -> None:
        self._queues: dict[int, list[asyncio.Queue]] = {}

    async def publish(self, run_id: int, event: dict[str, Any]) -> None:
        for q in self._queues.get(run_id, []):
            q.put_nowait(event)

    async def subscribe(self, run_id: int) -> Subscription:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(run_id, []).append(q)

        async def on_close() -> None:
            subs = self._queues.get(run_id, [])
            with contextlib.suppress(ValueError):
                subs.remove(q)
            if not subs:
                self._queues.pop(run_id, None)

        return _QueueSubscription(q, on_close)


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

    async def subscribe(self, run_id: int) -> Subscription:
        import redis.asyncio as aioredis

        client = aioredis.from_url(self._url)
        pubsub = client.pubsub()
        await pubsub.subscribe(self._channel(run_id))
        q: asyncio.Queue = asyncio.Queue()

        # Uma task dedicada lê o pub/sub e alimenta a fila: assim um get()
        # cancelado nunca interrompe uma leitura no meio da conexão Redis.
        async def reader() -> None:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                with contextlib.suppress(json.JSONDecodeError):
                    q.put_nowait(json.loads(message["data"]))

        reader_task = asyncio.create_task(reader())

        async def on_close() -> None:
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reader_task
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(self._channel(run_id))
                await pubsub.aclose()
            await client.aclose()

        return _QueueSubscription(q, on_close)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = RedisEventBus(settings.redis_url) if settings.redis_url else LocalEventBus()
    return _bus

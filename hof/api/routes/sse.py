"""SSE endpoint for streaming computation progress to the UI.

Supports two event paths:
- **In-process**: ``emit_computation_event`` pushes directly into an asyncio
  queue (fast path, used by inline-edit and other same-process callers).
- **Cross-process (Redis pub/sub)**: ``publish_computation_event`` publishes
  to a Redis channel so that Celery workers (separate processes) can push
  events to an SSE stream owned by the API server.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()
logger = logging.getLogger("hof.sse")

_channels: dict[str, ComputationChannel] = {}

CHANNEL_TTL_SECONDS = 300


class ComputationChannel:
    """An async queue that bridges sync function code to an SSE stream."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.created_at = time.monotonic()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, event: dict[str, Any]) -> None:
        """Thread-safe: push an event from sync code running in a thread pool."""
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def close(self) -> None:
        """Signal the SSE stream to end."""
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)

    async def get(self, timeout: float = CHANNEL_TTL_SECONDS) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None


def get_channel(channel_id: str) -> ComputationChannel | None:
    return _channels.get(channel_id)


def emit_computation_event(channel_id: str, event: dict[str, Any]) -> None:
    """Emit a progress event to an SSE channel. Safe to call from sync code."""
    ch = _channels.get(channel_id)
    if ch is not None:
        ch.emit(event)


_sync_redis = None


def _get_sync_redis():
    """Lazy-create a synchronous Redis client for pub/sub publishing."""
    global _sync_redis
    if _sync_redis is None:
        import redis as _redis

        from hof.config import get_config

        config = get_config()
        _sync_redis = _redis.Redis.from_url(config.redis_url)
    return _sync_redis


def publish_computation_event(channel_id: str, event: dict[str, Any]) -> None:
    """Publish an SSE event via Redis pub/sub (for cross-process callers like Celery)."""
    try:
        r = _get_sync_redis()
        r.publish(f"sse:{channel_id}", json.dumps(event, default=str))
    except Exception:
        logger.warning(
            "Failed to publish SSE event via Redis for channel %s",
            channel_id,
            exc_info=True,
        )


async def _redis_subscriber(channel_id: str, queue: asyncio.Queue) -> None:
    """Subscribe to Redis pub/sub and forward messages into the channel queue."""
    import redis.asyncio as aioredis

    from hof.config import get_config

    config = get_config()
    r = aioredis.Redis.from_url(config.redis_url)
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(f"sse:{channel_id}")
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                try:
                    event = json.loads(msg["data"])
                    await queue.put(event)
                except (json.JSONDecodeError, TypeError):
                    pass
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(f"sse:{channel_id}")
        await pubsub.aclose()
        await r.aclose()


@router.get("/api/sse/{channel_id}")
async def sse_stream(channel_id: str) -> StreamingResponse:
    channel = ComputationChannel()
    loop = asyncio.get_running_loop()
    channel.bind_loop(loop)
    _channels[channel_id] = channel

    redis_task: asyncio.Task | None = None
    try:
        redis_task = asyncio.create_task(_redis_subscriber(channel_id, channel._queue))
    except Exception:
        logger.debug("Redis subscriber not started for channel %s", channel_id, exc_info=True)

    async def event_generator():
        try:
            while True:
                event = await channel.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("status") == "done":
                    break
        finally:
            _channels.pop(channel_id, None)
            if redis_task and not redis_task.done():
                redis_task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

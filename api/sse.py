"""
Server-Sent Events (SSE) endpoint for real-time task progress push.

Architecture:
  Celery Worker → Redis pub/sub → FastAPI SSE → Client

Replaces the need for client-side polling (GET /analyze/{task_id}/status).
Falls back gracefully if Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from .config import config

logger = logging.getLogger(__name__)

router = APIRouter()

# Heartbeat interval seconds
_HEARTBEAT_INTERVAL = 15.0
# Max event stream duration (30 min)
_MAX_STREAM_DURATION = 1800.0


async def _event_stream(task_id: int):
    """
    Async generator that yields SSE events from Redis pub/sub.

    Subscribes to channel `task:{task_id}:progress` and yields
    progress updates as SSE `data:` lines. Sends heartbeats
    every 15 s to keep the connection alive.

    Falls back to sending only an initial status event if Redis
    is unreachable.
    """
    import redis.asyncio as aioredis

    r = None
    pubsub = None

    try:
        r = aioredis.from_url(
            config.REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await r.ping()
        pubsub = r.pubsub()
        await pubsub.subscribe(f"task:{task_id}:progress")

        # Send initial connection event
        yield _sse_event("connected", {"task_id": task_id})

        start_time = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > _MAX_STREAM_DURATION:
                yield _sse_event("timeout", {"message": "Stream timeout reached"})
                break

            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=_HEARTBEAT_INTERVAL,
            )
            if message:
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                if data:
                    yield f"data: {data}\n\n"
            else:
                # Heartbeat — keep connection alive
                yield f": heartbeat {int(elapsed)}s\n\n"

    except asyncio.CancelledError:
        logger.info(f"SSE stream cancelled for task {task_id}")
    except Exception as e:
        logger.warning(f"SSE stream error for task {task_id}: {e}")
        yield _sse_event("error", {"message": f"SSE unavailable: {e}"})
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(f"task:{task_id}:progress")
                await pubsub.close()
            except Exception:
                pass
        if r is not None:
            try:
                await r.close()
            except Exception:
                pass


def _sse_event(event: str, data: dict) -> str:
    """Build an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Routes ──


@router.get("/analyze/{task_id}/sse")
async def task_progress_sse(task_id: int):
    """
    SSE (Server-Sent Events) endpoint for real-time task progress.

    Usage (JavaScript):
        const evtSource = new EventSource('/api/analyze/123/sse');
        evtSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            console.log(data.progress_percent, data.current_step);
        };
        evtSource.addEventListener('error', (e) => { ... });

    Events:
    - `message`: progress update with {task_id, status, progress_percent, current_step}
    - `connected`: initial connection confirmation
    - `error`: stream error / fallback
    - `timeout`: stream duration limit reached

    Falls back to single "error" event if Redis is unreachable.
    """
    return StreamingResponse(
        _event_stream(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ── Publisher helper (used by Celery tasks) ──


def publish_progress(
    task_id: int,
    status: str,
    progress_percent: int,
    current_step: str | None = None,
) -> None:
    """
    Publish a progress update to Redis pub/sub for SSE consumption.

    Called from Celery workers (synchronous context). Non-blocking:
    failures are logged but not raised.
    """
    try:
        import redis as sync_redis

        payload = json.dumps({
            "task_id": task_id,
            "status": status,
            "progress_percent": progress_percent,
            "current_step": current_step or "",
        })
        r = sync_redis.from_url(
            config.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        r.publish(f"task:{task_id}:progress", payload)
        r.close()
    except Exception as e:
        logger.debug(f"SSE publish failed (task {task_id}): {e}")

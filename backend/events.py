from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import AsyncGenerator


class EventBus:
    """In-memory pub/sub for SSE streaming. Keyed by session_id."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def publish(self, session_id: str, event: dict) -> None:
        for queue in self._subscribers.get(session_id, []):
            queue.put_nowait(event)

    async def subscribe(self, session_id: str) -> AsyncGenerator[dict, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[session_id].append(queue)
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield event
        except asyncio.TimeoutError:
            # Send keepalive
            yield {"type": "keepalive", "timestamp": datetime.now(timezone.utc).isoformat()}
        finally:
            self._subscribers[session_id].remove(queue)
            if not self._subscribers[session_id]:
                del self._subscribers[session_id]


def format_sse(event: dict) -> str:
    data = json.dumps(event)
    return f"data: {data}\n\n"


# Singleton
event_bus = EventBus()

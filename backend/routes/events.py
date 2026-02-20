from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db, get_db_session
from backend.events import event_bus, format_sse
from backend.services.event_service import get_replay_events, session_exists

router = APIRouter(prefix="/api/sessions", tags=["events"])


@router.get("/{session_id}/events")
async def stream_events(session_id: str, db: AsyncSession = Depends(get_db_session)):
    # Verify session exists
    if not await session_exists(db, session_id):
        raise HTTPException(404, "Session not found")

    async def generate():
        # Replay existing events from DB
        async with get_db() as db:
            replay_events = await get_replay_events(db, session_id)
            for event in replay_events:
                yield format_sse(event)

        # Stream live events
        try:
            async for event in event_bus.subscribe(session_id):
                yield format_sse(event)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

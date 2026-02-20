from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Event, Run, Session


async def session_exists(db: AsyncSession, session_id: str) -> bool:
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none() is not None


async def get_replay_events(db: AsyncSession, session_id: str) -> list[dict]:
    run_result = await db.execute(select(Run).where(Run.session_id == session_id))
    runs = run_result.scalars().all()
    run_ids = [run.id for run in runs]

    if not run_ids:
        return []

    events_result = await db.execute(
        select(Event).where(Event.run_id.in_(run_ids)).order_by(Event.id)
    )
    events = events_result.scalars().all()
    return [
        {
            "id": event.id,
            "role": event.role,
            "type": event.type,
            "data": event.data,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "replayed": True,
        }
        for event in events
    ]

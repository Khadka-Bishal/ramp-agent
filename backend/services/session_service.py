from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Artifact, Event, Message, Run, Session
from backend.routes.schemas import iso_ts


async def create_session(db: AsyncSession, repo_url: str, prompt: str) -> dict:
    session = Session(repo_url=repo_url, prompt=prompt)
    db.add(session)
    await db.flush()
    return {
        "id": session.id,
        "repo_url": session.repo_url,
        "prompt": session.prompt,
        "status": session.status.value,
        "created_at": iso_ts(session.created_at),
    }


async def list_sessions(db: AsyncSession) -> list[dict]:
    latest_run_subquery = (
        select(
            Run.session_id.label("session_id"),
            Run.pr_url.label("pr_url"),
            func.row_number()
            .over(partition_by=Run.session_id, order_by=Run.started_at.desc())
            .label("row_num"),
        )
    ).subquery()

    result = await db.execute(
        select(Session, latest_run_subquery.c.pr_url)
        .outerjoin(
            latest_run_subquery,
            and_(
                latest_run_subquery.c.session_id == Session.id,
                latest_run_subquery.c.row_num == 1,
            ),
        )
        .order_by(Session.created_at.desc())
    )
    rows = result.all()

    items: list[dict] = []
    for session, pr_url in rows:
        items.append(
            {
                "id": session.id,
                "repo_url": session.repo_url,
                "prompt": session.prompt[:100],
                "status": session.status.value,
                "pr_url": pr_url,
                "created_at": iso_ts(session.created_at),
                "updated_at": iso_ts(session.updated_at),
            }
        )

    return items


async def get_session_by_id(db: AsyncSession, session_id: str) -> Session | None:
    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def get_session_detail(db: AsyncSession, session_id: str) -> dict | None:
    session = await get_session_by_id(db, session_id)
    if not session:
        return None

    runs_result = await db.execute(
        select(Run).where(Run.session_id == session_id).order_by(Run.started_at)
    )
    runs = runs_result.scalars().all()
    run_ids = [run.id for run in runs]

    events_result = (
        await db.execute(
            select(Event).where(Event.run_id.in_(run_ids)).order_by(Event.id)
        )
        if run_ids
        else None
    )
    events = events_result.scalars().all() if events_result else []

    artifacts_result = (
        await db.execute(
            select(Artifact)
            .where(Artifact.run_id.in_(run_ids))
            .order_by(Artifact.created_at)
        )
        if run_ids
        else None
    )
    artifacts = artifacts_result.scalars().all() if artifacts_result else []

    messages_result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.timestamp)
    )
    messages = messages_result.scalars().all()

    return {
        "id": session.id,
        "repo_url": session.repo_url,
        "prompt": session.prompt,
        "status": session.status.value,
        "config_overrides": session.config_overrides,
        "created_at": iso_ts(session.created_at),
        "updated_at": iso_ts(session.updated_at),
        "runs": [
            {
                "id": run.id,
                "status": run.status.value,
                "commands_used": run.commands_used,
                "pr_url": run.pr_url,
                "pr_number": run.pr_number,
                "started_at": iso_ts(run.started_at),
                "finished_at": iso_ts(run.finished_at),
            }
            for run in runs
        ],
        "events": [
            {
                "id": event.id,
                "role": event.role,
                "type": event.type,
                "data": event.data,
                "timestamp": iso_ts(event.timestamp),
            }
            for event in events
        ],
        "artifacts": [
            {
                "id": artifact.id,
                "type": artifact.type.value,
                "name": artifact.name,
                "path": artifact.path,
                "metadata": artifact.metadata_,
                "size_bytes": artifact.size_bytes,
                "created_at": iso_ts(artifact.created_at),
            }
            for artifact in artifacts
        ],
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "timestamp": iso_ts(message.timestamp),
            }
            for message in messages
        ],
    }


async def create_run_for_session(
    db: AsyncSession,
    session_id: str,
) -> tuple[str, str, str] | None:
    session = await get_session_by_id(db, session_id)
    if not session:
        return None

    run = Run(session_id=session_id, started_at=datetime.now(timezone.utc))
    db.add(run)
    await db.flush()
    return run.id, session.repo_url, session.prompt


async def save_user_message(db: AsyncSession, session_id: str, content: str) -> bool:
    session = await get_session_by_id(db, session_id)
    if not session:
        return False

    db.add(Message(session_id=session_id, role="user", content=content))
    return True


async def save_agent_message(db: AsyncSession, session_id: str, content: str) -> None:
    db.add(Message(session_id=session_id, role="agent", content=content))


async def get_latest_run(db: AsyncSession, session_id: str) -> Run | None:
    result = await db.execute(
        select(Run)
        .where(Run.session_id == session_id)
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def delete_session(db: AsyncSession, session_id: str) -> bool:
    session = await get_session_by_id(db, session_id)
    if not session:
        return False
    await db.delete(session)
    return True


async def set_run_merge_result(
    db: AsyncSession,
    run_id: str,
    sha: str | None,
    merged_at: datetime,
) -> bool:
    result = await db.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        return False
    run.merge_sha = sha
    run.merged_at = merged_at
    return True

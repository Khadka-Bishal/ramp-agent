from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.database import get_db, get_db_session
from backend.events import event_bus
from backend.orchestrator import (
    Orchestrator,
    get_active_orchestrator,
    interrupt_active_run,
    register_active_run_task,
    register_running_orchestrator,
)
from backend.routes.schemas import (
    CreateSessionResponse,
    CreateSessionRequest,
    DeleteSessionResponse,
    MergeRunResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionDetailResponse,
    SessionSummaryResponse,
    StopRunResponse,
    TriggerRunResponse,
)
from backend.tools.github import extract_repo_full_name, merge_pr
from backend.services.session_service import (
    create_run_for_session,
    create_session as create_session_service,
    delete_session as delete_session_service,
    get_latest_run,
    get_session_by_id,
    get_session_detail,
    list_sessions as list_sessions_service,
    save_agent_message,
    save_user_message,
    set_run_merge_result,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=CreateSessionResponse)
async def create_session(
    req: CreateSessionRequest, db: AsyncSession = Depends(get_db_session)
):
    return await create_session_service(db, req.repo_url, req.prompt)


@router.get("", response_model=list[SessionSummaryResponse])
async def list_sessions(db: AsyncSession = Depends(get_db_session)):
    return await list_sessions_service(db)


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    payload = await get_session_detail(db, session_id)
    if not payload:
        raise HTTPException(404, "Session not found")
    return payload


@router.post("/{session_id}/run", response_model=TriggerRunResponse)
async def trigger_run(session_id: str, db: AsyncSession = Depends(get_db_session)):
    run_context = await create_run_for_session(db, session_id)
    if not run_context:
        raise HTTPException(404, "Session not found")
    run_id, repo_url, prompt = run_context

    async def _execute():
        try:
            await orchestrator.run(repo_url, prompt)
        except asyncio.CancelledError:
            return

    orchestrator = Orchestrator(
        session_id=session_id,
        run_id=run_id,
        event_callback=lambda e: event_bus.publish(session_id, e),
    )
    register_running_orchestrator(session_id, orchestrator)
    task = asyncio.create_task(_execute())
    register_active_run_task(session_id, task)
    return {"run_id": run_id, "status": "started"}


@router.post("/{session_id}/stop", response_model=StopRunResponse)
async def stop_run(session_id: str, db: AsyncSession = Depends(get_db_session)):
    session = await get_session_by_id(db, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    interrupted = await interrupt_active_run(session_id)
    if not interrupted:
        return {"stopped": False, "message": "No active run to stop"}
    return {"stopped": True, "message": "Stop signal sent"}


@router.post("/{session_id}/message", response_model=SendMessageResponse)
async def send_message(
    session_id: str,
    req: SendMessageRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a follow-up message to an active session."""
    saved = await save_user_message(db, session_id, req.content)
    if not saved:
        raise HTTPException(404, "Session not found")

    orchestrator = get_active_orchestrator(session_id)
    if not orchestrator:
        raise HTTPException(400, "No active session. Start a run first.")

    async def _execute():
        try:
            result = await orchestrator.continue_run(req.content)
        except asyncio.CancelledError:
            return

        if result.get("status") != "completed":
            return

        summary = (result.get("summary") or "").strip()
        if not summary:
            return

        async with get_db() as db:
            await save_agent_message(db, session_id, summary)

    task = asyncio.create_task(_execute())
    register_active_run_task(session_id, task)
    return {"status": "message_sent"}


@router.post("/{session_id}/merge", response_model=MergeRunResponse)
async def merge_run(session_id: str):
    async with get_db() as read_db:
        run = await get_latest_run(read_db, session_id)
        if not run or not run.pr_number:
            raise HTTPException(400, "No PR to merge")
        run_id = run.id
        pr_number = run.pr_number

        session = await get_session_by_id(read_db, session_id)
        if session is None:
            raise HTTPException(404, "Session not found")
        repo_name = extract_repo_full_name(session.repo_url)

    merge_result = await merge_pr(repo_name, pr_number, settings.github_token)

    async with get_db() as db:
        await set_run_merge_result(
            db,
            run_id=run_id,
            sha=merge_result.get("sha"),
            merged_at=datetime.now(timezone.utc),
        )

    return {
        "merged": merge_result.get("merged"),
        "sha": merge_result.get("sha"),
    }


@router.delete("/{session_id}", response_model=DeleteSessionResponse)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    deleted = await delete_session_service(db, session_id)
    if not deleted:
        raise HTTPException(404, "Session not found")
    return {"deleted": True}

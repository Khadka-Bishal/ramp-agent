from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db_session
from backend.routes.schemas import ArtifactResponse
from backend.services.artifact_service import (
    get_artifact_content_info,
    get_artifact_payload,
)

router = APIRouter(prefix="/api/sessions/{session_id}/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    session_id: str,
    artifact_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    payload = await get_artifact_payload(db, session_id, artifact_id)
    if not payload:
        raise HTTPException(404, "Artifact not found")
    return payload


@router.get("/{artifact_id}/content")
async def get_artifact_content(
    session_id: str,
    artifact_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    content_info = await get_artifact_content_info(db, session_id, artifact_id)
    if not content_info:
        raise HTTPException(404, "Artifact not found")
    filepath, media, filename = content_info

    return FileResponse(
        path=filepath,
        media_type=media,
        filename=filename,
    )

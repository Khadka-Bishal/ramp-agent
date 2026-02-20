from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Artifact, Run
from backend.routes.schemas import iso_ts


async def get_artifact_payload(
    db: AsyncSession, session_id: str, artifact_id: str
) -> dict | None:
    result = await db.execute(
        select(Artifact)
        .join(Run, Artifact.run_id == Run.id)
        .where(Artifact.id == artifact_id, Run.session_id == session_id)
    )
    artifact = result.scalar_one_or_none()
    if not artifact:
        return None

    return {
        "id": artifact.id,
        "type": artifact.type.value,
        "name": artifact.name,
        "path": artifact.path,
        "metadata": artifact.metadata_,
        "size_bytes": artifact.size_bytes,
        "created_at": iso_ts(artifact.created_at),
    }


async def get_artifact_content_info(
    db: AsyncSession, session_id: str, artifact_id: str
) -> tuple[str, str, str] | None:
    result = await db.execute(
        select(Artifact)
        .join(Run, Artifact.run_id == Run.id)
        .where(Artifact.id == artifact_id, Run.session_id == session_id)
    )
    artifact = result.scalar_one_or_none()
    if not artifact:
        return None

    filepath = Path(artifact.path)
    if not filepath.exists():
        return None

    type_map = {
        "diff": "text/plain",
        "log": "text/plain",
        "report": "text/markdown",
        "screenshot": "image/png",
    }
    media = type_map.get(artifact.type.value, "application/octet-stream")
    return str(filepath), media, filepath.name

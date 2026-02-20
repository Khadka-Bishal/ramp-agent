from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


def iso_ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class CreateSessionRequest(BaseModel):
    repo_url: str
    prompt: str


class SendMessageRequest(BaseModel):
    content: str


class TriggerRunResponse(BaseModel):
    run_id: str
    status: str


class CreateSessionResponse(BaseModel):
    id: str
    repo_url: str
    prompt: str
    status: str
    created_at: str


class SendMessageResponse(BaseModel):
    status: str


class StopRunResponse(BaseModel):
    stopped: bool
    message: str


class DeleteSessionResponse(BaseModel):
    deleted: bool


class MergeRunResponse(BaseModel):
    merged: bool
    sha: str | None


class SessionSummaryResponse(BaseModel):
    id: str
    repo_url: str
    prompt: str
    status: str
    pr_url: str | None = None
    created_at: str
    updated_at: str


class EventResponse(BaseModel):
    id: int
    role: str
    type: str
    data: dict | None
    timestamp: str


class ArtifactResponse(BaseModel):
    id: str
    type: str
    name: str
    path: str
    metadata: dict | None = None
    size_bytes: int | None
    created_at: str


class RunResponse(BaseModel):
    id: str
    status: str
    commands_used: dict | None
    pr_url: str | None
    pr_number: int | None
    started_at: str | None
    finished_at: str | None


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    timestamp: str


class SessionDetailResponse(BaseModel):
    id: str
    repo_url: str
    prompt: str
    status: str
    config_overrides: dict | None
    created_at: str
    updated_at: str
    runs: list[RunResponse]
    events: list[EventResponse]
    artifacts: list[ArtifactResponse]
    messages: list[MessageResponse]

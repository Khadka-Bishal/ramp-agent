from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.agents.agent import create_orchestrator_agent
from backend.agents.base import AgentEvent, BaseAgent
from backend.config import settings
from backend.db.database import get_db
from backend.db.models import (
    Artifact,
    ArtifactType,
    Event,
    Run,
    RunStatus,
    Session,
    SessionStatus,
)
from backend.sandbox.local import LocalSandbox
from backend.sandbox.modal_provider import ModalSandbox
from backend.sandbox.provider import Sandbox, SandboxProvider

logger = logging.getLogger(__name__)

# In-memory store of active orchestrator instances for follow-up messages
_active_sessions: dict[str, Orchestrator] = {}
_active_run_tasks: dict[str, asyncio.Task] = {}
_running_orchestrators: dict[str, Orchestrator] = {}


class Orchestrator:
    def __init__(
        self,
        session_id: str,
        run_id: str,
        event_callback: Callable[[dict], Any] | None = None,
    ):
        self.session_id = session_id
        self.run_id = run_id
        self.event_callback = event_callback
        if settings.use_modal:
            self.sandbox_provider: SandboxProvider = ModalSandbox()
        else:
            self.sandbox_provider: SandboxProvider = LocalSandbox()
        self.sandbox: Sandbox | None = None
        self._agent: BaseAgent | None = None
        self._interrupted = False

    async def request_interrupt(self) -> None:
        self._interrupted = True
        self._emit_event(
            "orchestrator", "status_change", {"status": "interrupt_requested"}
        )
        if self.sandbox:
            try:
                await self.sandbox_provider.destroy(self.sandbox)
            except Exception:
                logger.exception("Failed to destroy sandbox during interrupt")

    def _emit_event(self, role: str, type_: str, data: dict) -> None:
        event = {
            "role": role,
            "type": type_,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if self.event_callback:
            self.event_callback(event)

    def _agent_event_handler(self, event: AgentEvent) -> None:
        self._emit_event(event.role, event.type, event.data)

    async def _persist_event(self, role: str, type_: str, data: dict) -> None:
        async with get_db() as db:
            db.add(
                Event(
                    run_id=self.run_id,
                    role=role,
                    type=type_,
                    data=data,
                )
            )

    async def _persist_artifact(
        self,
        type_: ArtifactType,
        name: str,
        content: str | bytes,
        metadata: dict | None = None,
    ) -> str:
        artifact_dir = settings.artifacts_dir / self.run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        ext = {"diff": ".patch", "log": ".log", "report": ".md", "screenshot": ".png"}
        filename = f"{name}{ext.get(type_.value, '.txt')}"
        filepath = artifact_dir / filename

        if isinstance(content, bytes):
            filepath.write_bytes(content)
        else:
            filepath.write_text(content)

        size = filepath.stat().st_size
        async with get_db() as db:
            artifact = Artifact(
                run_id=self.run_id,
                type=type_,
                name=name,
                path=str(filepath),
                metadata_=metadata,
                size_bytes=size,
            )
            db.add(artifact)
            return artifact.id

    async def _update_run_status(self, status: RunStatus) -> None:
        async with get_db() as db:
            from sqlalchemy import select

            result = await db.execute(select(Run).where(Run.id == self.run_id))
            run = result.scalar_one()
            run.status = status
            if status in (RunStatus.completed, RunStatus.failed):
                run.finished_at = datetime.now(timezone.utc)

    async def _update_session_status(self, status: SessionStatus) -> None:
        async with get_db() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(Session).where(Session.id == self.session_id)
            )
            session = result.scalar_one()
            session.status = status

    async def _get_diff(self) -> str:
        if not self.sandbox:
            return ""
        result = await self.sandbox_provider.run_command(
            self.sandbox, "git diff HEAD", timeout=10
        )
        return result.stdout

    async def run(self, repo_url: str, prompt: str) -> dict:
        result = {"status": "failed", "error": None}

        try:
            await self._update_run_status(RunStatus.running)
            await self._update_session_status(SessionStatus.running)
            self._emit_event("orchestrator", "status_change", {"status": "starting"})

            # Clone repo
            self._emit_event(
                "orchestrator", "status_change", {"status": "cloning_repo"}
            )
            self.sandbox = await self.sandbox_provider.create(
                repo_url, settings.github_token
            )
            # Inject host secrets into the sandbox environment
            secrets = {
                "GITHUB_TOKEN": settings.github_token,
                "ANTHROPIC_API_KEY": settings.anthropic_api_key,
            }
            if hasattr(self.sandbox, "_env"):
                self.sandbox._env.update(secrets)
            else:
                self.sandbox._env = secrets

            async def _save_artifact_callback(
                type_val: str,
                name: str,
                content: bytes,
                metadata: dict | None = None,
            ) -> str:
                t = ArtifactType(type_val)
                return await self._persist_artifact(t, name, content, metadata)

            # Create the orchestrator agent
            self._agent = create_orchestrator_agent(
                sandbox_provider=self.sandbox_provider,
                sandbox=self.sandbox,
                repo_url=repo_url,
                github_token=settings.github_token,
                event_callback=self._agent_event_handler,
                save_artifact_callback=_save_artifact_callback,
            )
            self._agent.on_event(self._agent_event_handler)

            # Run the agent loop — the LLM decides what to do
            output = await self._agent.run({"prompt": prompt, "repo_url": repo_url})

            # Persist all events
            await self._persist_events_batch(output.events)

            # Save diff as artifact if there are changes
            diff = await self._get_diff()
            if diff:
                await self._persist_artifact(
                    ArtifactType.diff,
                    "changes",
                    diff,
                    {"summary": output.result.get("summary", "")},
                )

            # Update run with PR info from agent result
            pr_url = output.result.get("pr_url")
            pr_number = output.result.get("pr_number")
            if pr_url or pr_number:
                async with get_db() as db:
                    from sqlalchemy import select

                    r = await db.execute(select(Run).where(Run.id == self.run_id))
                    run = r.scalar_one()
                    run.pr_url = pr_url
                    run.pr_number = pr_number

            # Done
            await self._update_run_status(RunStatus.completed)
            await self._update_session_status(SessionStatus.completed)
            self._emit_event("orchestrator", "status_change", {"status": "completed"})

            result = {
                "status": "completed",
                "summary": output.result.get("summary"),
                "pr_url": pr_url,
                "pr_number": pr_number,
            }

            # Keep alive for follow-up messages
            _active_sessions[self.session_id] = self

        except asyncio.CancelledError:
            self._interrupted = True
            self._emit_event("orchestrator", "status_change", {"status": "interrupted"})
            await self._persist_event(
                "orchestrator", "status_change", {"status": "interrupted"}
            )
            await self._update_run_status(RunStatus.completed)
            await self._update_session_status(SessionStatus.completed)
            result = {"status": "interrupted", "error": "Run interrupted by user"}
        except Exception as exc:
            if self._interrupted:
                self._emit_event(
                    "orchestrator", "status_change", {"status": "interrupted"}
                )
                await self._persist_event(
                    "orchestrator", "status_change", {"status": "interrupted"}
                )
                await self._update_run_status(RunStatus.completed)
                await self._update_session_status(SessionStatus.completed)
                result = {"status": "interrupted", "error": "Run interrupted by user"}
                return result
            logger.exception("Orchestrator run failed")
            self._emit_event("orchestrator", "error", {"message": str(exc)})
            await self._persist_event("orchestrator", "error", {"message": str(exc)})
            await self._update_run_status(RunStatus.failed)
            await self._update_session_status(SessionStatus.failed)
            result["error"] = str(exc)
        finally:
            _active_run_tasks.pop(self.session_id, None)
            _running_orchestrators.pop(self.session_id, None)

        return result

    async def continue_run(self, user_message: str) -> dict:
        """Send a follow-up message into the existing agent conversation."""
        if not self._agent:
            return {"error": "No active agent session"}

        try:
            await self._update_run_status(RunStatus.running)
            await self._update_session_status(SessionStatus.running)

            self._emit_event("orchestrator", "status_change", {"status": "running"})
            self._emit_event("user", "user_message", {"content": user_message})
            await self._persist_event("user", "user_message", {"content": user_message})

            output = await self._agent.resume(user_message)
            await self._persist_events_batch(output.events)

            # Check for new diff/PR
            diff = await self._get_diff()
            if diff:
                await self._persist_artifact(
                    ArtifactType.diff,
                    "changes_followup",
                    diff,
                    {"summary": output.result.get("summary", "")},
                )

            pr_url = output.result.get("pr_url")
            pr_number = output.result.get("pr_number")
            if pr_url or pr_number:
                async with get_db() as db:
                    from sqlalchemy import select

                    r = await db.execute(select(Run).where(Run.id == self.run_id))
                    run = r.scalar_one()
                    run.pr_url = pr_url
                    run.pr_number = pr_number

            await self._update_run_status(RunStatus.completed)
            await self._update_session_status(SessionStatus.completed)
            self._emit_event("orchestrator", "status_change", {"status": "completed"})

            return {
                "status": "completed",
                "summary": output.result.get("summary"),
                "pr_url": pr_url,
                "pr_number": pr_number,
            }

        except asyncio.CancelledError:
            self._interrupted = True
            self._emit_event("orchestrator", "status_change", {"status": "interrupted"})
            await self._persist_event(
                "orchestrator", "status_change", {"status": "interrupted"}
            )
            await self._update_run_status(RunStatus.completed)
            await self._update_session_status(SessionStatus.completed)
            return {"status": "interrupted", "error": "Run interrupted by user"}
        except Exception as exc:
            logger.exception("Follow-up failed")
            self._emit_event("orchestrator", "error", {"message": str(exc)})
            await self._update_run_status(RunStatus.failed)
            await self._update_session_status(SessionStatus.failed)
            return {"error": str(exc)}

    async def _persist_events_batch(self, events: list[AgentEvent]) -> None:
        async with get_db() as db:
            for e in events:
                db.add(
                    Event(
                        run_id=self.run_id,
                        role=e.role,
                        type=e.type,
                        data=e.data,
                    )
                )


def get_active_orchestrator(session_id: str) -> Orchestrator | None:
    return _active_sessions.get(session_id)


def register_active_run_task(session_id: str, task: asyncio.Task) -> None:
    _active_run_tasks[session_id] = task


def register_running_orchestrator(session_id: str, orchestrator: Orchestrator) -> None:
    _running_orchestrators[session_id] = orchestrator


async def interrupt_active_run(session_id: str) -> bool:
    orchestrator = _running_orchestrators.get(session_id)
    if orchestrator:
        await orchestrator.request_interrupt()

    task = _active_run_tasks.get(session_id)
    if not task or task.done():
        return False
    task.cancel()
    return True

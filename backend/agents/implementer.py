from __future__ import annotations

import json

from backend.agents.base import BaseAgent, ToolDef
from backend.sandbox.provider import SandboxProvider, Sandbox


def create_implementer(
    sandbox_provider: SandboxProvider, sandbox: Sandbox, task: str, context: str,
) -> BaseAgent:
    """Sub-agent spawned by the orchestrator to implement code changes."""

    async def _read(path: str) -> str:
        return await sandbox_provider.read_file(sandbox, path)

    async def _write(path: str, content: str) -> str:
        await sandbox_provider.write_file(sandbox, path, content)
        return f"Wrote {len(content)} chars to {path}"

    async def _create(path: str, content: str) -> str:
        await sandbox_provider.write_file(sandbox, path, content)
        return f"Created {path} ({len(content)} chars)"

    async def _delete(path: str) -> str:
        target = sandbox.workspace / path
        if target.exists():
            target.unlink()
            return f"Deleted {path}"
        return f"{path} not found"

    async def _run(command: str) -> dict:
        result = await sandbox_provider.run_command(sandbox, command, timeout=60)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout[:50_000],
            "stderr": result.stderr[:10_000],
        }

    async def _list_dir(path: str = ".") -> str:
        entries = await sandbox_provider.list_dir(sandbox, path)
        return "\n".join(entries)

    agent = BaseAgent(tools=[
        ToolDef(
            name="read_file",
            description="Read a file from the workspace.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_read,
        ),
        ToolDef(
            name="write_file",
            description="Write/overwrite a file in the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=_write,
        ),
        ToolDef(
            name="create_file",
            description="Create a new file. Parent directories created automatically.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=_create,
        ),
        ToolDef(
            name="delete_file",
            description="Delete a file from the workspace.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_delete,
        ),
        ToolDef(
            name="run_command",
            description="Run a shell command in the workspace.",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            handler=_run,
        ),
        ToolDef(
            name="list_directory",
            description="List files in a directory.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
                "required": [],
            },
            handler=_list_dir,
        ),
    ])
    agent.role = "implementer"
    agent.max_iterations = 40
    agent.system_prompt = f"""You are an Implementer agent. You make code changes in a repository workspace.

Task from orchestrator:
{task}

Context (files already read by orchestrator):
{context}

Your job:
1. Read any additional files you need (the orchestrator already read some for you).
2. Write/create/modify files to accomplish the task.
3. Run commands to verify your changes compile/pass basic checks.

When done, output valid JSON:
{{
  "changed_files": ["list of modified files"],
  "created_files": ["list of new files"],
  "deleted_files": ["list of deleted files"],
  "summary": "what was changed and why"
}}

Write clean, production code. Handle edge cases."""
    return agent

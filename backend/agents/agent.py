"""Orchestrator agent factory.

Creates the main LLM agent that drives a session. It has:
- Direct tools: read_file, list_directory, run_command, GitHub ops
- Agent tools: run_implementer, run_verifier (spawn sub-agents)
- Meta tool: complete (signals done)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from backend.agents.base import BaseAgent, ToolDef, AgentEvent
from backend.agents.implementer import create_implementer
from backend.agents.verifier import create_verifier
from backend.sandbox.provider import SandboxProvider, Sandbox
from backend.tools import github as github_tools

logger = logging.getLogger(__name__)


def create_orchestrator_agent(
    sandbox_provider: SandboxProvider,
    sandbox: Sandbox,
    repo_url: str,
    github_token: str,
    event_callback: Callable[[AgentEvent], Any] | None = None,
    save_artifact_callback: (
        Callable[[str, str, bytes, dict | None], Awaitable[str]] | None
    ) = None,
) -> BaseAgent:
    """Create the main orchestrator agent with all tools."""

    repo_full_name = github_tools.extract_repo_full_name(repo_url)

    # ── Direct tools ─────────────────────────────────────────────────────────

    async def _read_file(path: str) -> str:
        return await sandbox_provider.read_file(sandbox, path)

    async def _list_directory(path: str = ".") -> str:
        entries = await sandbox_provider.list_dir(sandbox, path)
        return "\n".join(entries)

    async def _run_command(command: str) -> dict:
        result = await sandbox_provider.run_command(sandbox, command, timeout=60)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout[:50_000],
            "stderr": result.stderr[:10_000],
        }

    # ── GitHub tools ─────────────────────────────────────────────────────────

    async def _create_branch(branch_name: str) -> dict:
        return await github_tools.create_branch(sandbox_provider, sandbox, branch_name)

    async def _commit_and_push(message: str) -> dict:
        return await github_tools.commit_and_push(sandbox_provider, sandbox, message)

    async def _create_pr(title: str, body: str) -> dict:
        return await github_tools.create_pr(
            sandbox_provider,
            sandbox,
            repo_full_name,
            title=title,
            body=body,
            github_token=github_token,
        )

    # ── Agent tools (spawn sub-agents) ───────────────────────────────────────

    async def _run_implementer(task: str, context: str = "") -> dict:
        """Spawn an implementer sub-agent to make code changes."""
        impl = create_implementer(sandbox_provider, sandbox, task, context)
        impl.on_event(event_callback or (lambda _: None))
        output = await impl.run({"task": task})
        return output.result

    async def _run_verifier(
        install_command: str | None = None,
        test_command: str | None = None,
        verification_goal: str | None = None,
    ) -> dict:
        """Spawn a verifier sub-agent to test changes."""
        ver = create_verifier(
            sandbox_provider,
            sandbox,
            install_command,
            test_command,
            verification_goal=verification_goal,
            save_artifact_callback=save_artifact_callback,
        )
        ver.on_event(event_callback or (lambda _: None))
        output = await ver.run(
            {
                "install_command": install_command,
                "test_command": test_command,
                "verification_goal": verification_goal,
            }
        )
        return output.result

    # ── Build the agent ──────────────────────────────────────────────────────

    async def _handle_complete(**kwargs) -> str:
        return agent.mark_done(kwargs)

    agent = BaseAgent(
        tools=[
            # Exploration
            ToolDef(
                name="read_file",
                description="Read a file from the repository. Use relative paths from repo root.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative file path"}
                    },
                    "required": ["path"],
                },
                handler=_read_file,
            ),
            ToolDef(
                name="list_directory",
                description="List files and subdirectories. Use '.' for root.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "."}},
                    "required": [],
                },
                handler=_list_directory,
            ),
            ToolDef(
                name="run_command",
                description="Run a shell command in the repository workspace (read-only exploration, grep, find, etc.).",
                input_schema={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
                handler=_run_command,
            ),
            # Sub-agents
            ToolDef(
                name="run_implementer",
                description="Spawn an implementer sub-agent to make code changes. Pass a clear task description and any relevant file contents you've already read as context.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Detailed task description for the implementer",
                        },
                        "context": {
                            "type": "string",
                            "description": "File contents or other context the implementer needs",
                            "default": "",
                        },
                    },
                    "required": ["task"],
                },
                handler=_run_implementer,
            ),
            ToolDef(
                name="run_verifier",
                description="Spawn a verifier sub-agent to test changes and visual behavior against user intent.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "install_command": {
                            "type": "string",
                            "description": "Command to install dependencies (e.g. 'npm install')",
                        },
                        "test_command": {
                            "type": "string",
                            "description": "Command to run tests (e.g. 'pytest')",
                        },
                        "verification_goal": {
                            "type": "string",
                            "description": "What the final behavior/UI should look like from the user's perspective",
                        },
                    },
                    "required": [],
                },
                handler=_run_verifier,
            ),
            # GitHub
            ToolDef(
                name="create_branch",
                description="Create and checkout a new git branch.",
                input_schema={
                    "type": "object",
                    "properties": {"branch_name": {"type": "string"}},
                    "required": ["branch_name"],
                },
                handler=_create_branch,
            ),
            ToolDef(
                name="commit_and_push",
                description="Stage all changes, commit, and push to remote.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Commit message"}
                    },
                    "required": ["message"],
                },
                handler=_commit_and_push,
            ),
            ToolDef(
                name="create_pr",
                description="Create a GitHub pull request.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {
                            "type": "string",
                            "description": "PR body with description of changes",
                        },
                    },
                    "required": ["title", "body"],
                },
                handler=_create_pr,
            ),
            # Meta
            ToolDef(
                name="complete",
                description="Signal that you are done. Call this when you have finished the entire task. Include a summary and any relevant output.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Summary of what was accomplished",
                        },
                        "pr_url": {
                            "type": "string",
                            "description": "PR URL if one was created",
                        },
                        "pr_number": {
                            "type": "integer",
                            "description": "PR number if one was created",
                        },
                    },
                    "required": ["summary"],
                },
                handler=_handle_complete,
            ),
        ]
    )

    agent.role = "orchestrator"
    agent.max_iterations = 60
    agent.system_prompt = f"""You are Ramp Agent, an autonomous coding agent that works on GitHub repositories.

Repository: {repo_url}
The repo is cloned into your workspace. Use relative paths.

You have two types of capabilities:

**Direct tools** — you execute these yourself:
- read_file, list_directory, run_command: explore the codebase
- create_branch, commit_and_push, create_pr: push changes to GitHub
- complete: signal you're done

**Agent tools** — these spawn specialized sub-agents:
- run_implementer: spawns an agent with file write access to implement changes. Pass it a clear task + any file contents you've already read as context.
- run_verifier: spawns an agent to run install/test commands and report pass/fail.

## Workflow

Decide your workflow based on the user's request:

**For code changes** (add feature, fix bug, refactor):
1. Read relevant files to understand the codebase
2. Call run_implementer with a specific task + context
3. Call run_verifier with test commands; include verification_goal when UI/UX behavior is involved
4. Create a branch, commit, push, and create a PR
    - PR body MUST include a Visual Verification section.
    - If screenshots exist from verification, include screenshot evidence in the PR body using markdown image links to repo paths when available.
5. Call complete

**For read-only tasks** (explain, analyze, review):
1. Read relevant files
2. Call complete with your analysis as the summary

**For questions about the repo**:
1. Read what you need
2. Call complete with your answer

## Rules
- Do NOT call run_implementer for read-only tasks
- Do NOT create PRs if no files were changed
- For code changes with file edits, always perform git/GitHub flow (`create_branch` → `commit_and_push` → `create_pr`)
- PR descriptions for UI/front-end changes must contain visual verification evidence (routes checked, screenshot details, and image links when available)
- When calling run_implementer, pass the file contents you've already read as context so it doesn't re-read them
- Be efficient — don't read files you don't need
- ALWAYS use the native tools (`create_branch`, `commit_and_push`, `create_pr`) for git operations. Do NOT use `run_command` to execute `git` or `curl` against the GitHub API. This is strictly forbidden.
- Always call complete when done"""

    return agent

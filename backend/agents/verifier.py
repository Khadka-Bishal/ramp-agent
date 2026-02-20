import base64
import json
import logging
import re
import shlex
from datetime import datetime
from typing import Any, Callable, Awaitable
from backend.agents.base import BaseAgent, ToolDef
from backend.sandbox.provider import SandboxProvider, Sandbox

logger = logging.getLogger(__name__)

_FORBIDDEN_COMMAND_PATTERNS = [
    r"(^|\s)git\s",
    r"gh\s",
    r"gitkraken",
    r"commit",
    r"push",
    r"create\s+pr",
]


def create_verifier(
    sandbox_provider: SandboxProvider,
    sandbox: Sandbox,
    install_command: str | None,
    test_command: str | None,
    verification_goal: str | None = None,
    save_artifact_callback: (
        Callable[[str, str, bytes, dict | None], Awaitable[str]] | None
    ) = None,
) -> BaseAgent:
    """Sub-agent spawned by the orchestrator to verify changes."""

    async def _run(command: str) -> dict:
        normalized = command.strip().lower()
        for pattern in _FORBIDDEN_COMMAND_PATTERNS:
            if re.search(pattern, normalized):
                return {
                    "exit_code": 2,
                    "stdout": "",
                    "stderr": "Verifier safety policy: git/PR/push commands are not allowed during verification.",
                }

        result = await sandbox_provider.run_command(sandbox, command, timeout=120)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout[:50_000],
            "stderr": result.stderr[:10_000],
        }

    async def _take_screenshot(url: str) -> list | dict:
        ts = int(datetime.now().timestamp())
        screenshot_dir = ".ramp_verification"
        script_path = f"{screenshot_dir}/screenshot_runner_{ts}.py"
        screenshot_path = f"{screenshot_dir}/screenshot_{ts}.png"

        await sandbox_provider.run_command(
            sandbox, f"mkdir -p {screenshot_dir}", timeout=10
        )

        script = """
import sys
import json
from playwright.sync_api import sync_playwright

def main():
    url = sys.argv[1]
    out = sys.argv[2]
    metadata = {
        "requested_url": url,
        "final_url": None,
        "title": None,
        "http_status": None,
        "navigation_error": None,
        "body_excerpt": None,
        "screenshot_file": out,
    }
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 800})
        try:
            response = page.goto(url, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1000)
            metadata["http_status"] = response.status if response else None
        except Exception as e:
            metadata["navigation_error"] = str(e)

        try:
            metadata["final_url"] = page.url
            metadata["title"] = page.title()
            body_text = page.locator("body").inner_text()
            metadata["body_excerpt"] = (body_text or "")[:500]
        except Exception as e:
            if not metadata["navigation_error"]:
                metadata["navigation_error"] = f"Metadata capture error: {e}"

        page.screenshot(path=out)
        b.close()

    print("__SCREENSHOT_META__" + json.dumps(metadata))

if __name__ == "__main__":
    main()
"""
        await sandbox_provider.write_file(sandbox, script_path, script)
        quoted_script_path = shlex.quote(script_path)
        quoted_url = shlex.quote(url)
        quoted_screenshot_path = shlex.quote(screenshot_path)
        res = await sandbox_provider.run_command(
            sandbox,
            f"python3 {quoted_script_path} {quoted_url} {quoted_screenshot_path}",
            timeout=30,
        )
        await sandbox_provider.run_command(
            sandbox, f"rm -f {quoted_script_path}", timeout=10
        )
        if res.exit_code != 0:
            return {"error": f"Failed to take screenshot: {res.stderr}\n{res.stdout}"}

        metadata: dict[str, Any] = {"requested_url": url}
        for line in res.stdout.splitlines():
            if line.startswith("__SCREENSHOT_META__"):
                try:
                    metadata = json.loads(line.replace("__SCREENSHOT_META__", "", 1))
                except Exception:
                    metadata = {
                        "requested_url": url,
                        "parse_error": "failed_to_parse_screenshot_metadata",
                    }
                break

        metadata["repo_relative_path"] = screenshot_path

        res64 = await sandbox_provider.run_command(
            sandbox,
            "python3 -c "
            "\"import base64,sys;print(base64.b64encode(open(sys.argv[1],'rb').read()).decode())\" "
            f"{quoted_screenshot_path}",
        )
        if res64.exit_code != 0:
            return {"error": f"Failed to read screenshot: {res64.stderr}"}

        b64_data = res64.stdout.strip()

        # Persist as artifact so it shows in the UI
        if save_artifact_callback:
            try:
                raw_bytes = base64.b64decode(b64_data)
                screenshot_name = f"screenshot_{int(datetime.now().timestamp())}"
                await save_artifact_callback(
                    "screenshot", screenshot_name, raw_bytes, metadata
                )
            except Exception as e:
                logger.error(f"Warning: failed to save artifact: {e}")

        return [
            {
                "type": "text",
                "text": f"Screenshot captured. requested={metadata.get('requested_url')} final={metadata.get('final_url')} status={metadata.get('http_status')} title={metadata.get('title')} path={metadata.get('repo_relative_path')}",
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_data,
                },
            },
        ]

    agent = BaseAgent(
        tools=[
            ToolDef(
                name="run_command",
                description="Run a verification command (install, test, build, lint).",
                input_schema={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
                handler=_run,
            ),
            ToolDef(
                name="take_screenshot",
                description="Take a screenshot of a URL inside the sandbox using Playwright. Use this to visually verify UI changes.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "e.g., http://localhost:5173",
                        }
                    },
                    "required": ["url"],
                },
                handler=_take_screenshot,
            ),
        ]
    )
    agent.role = "verifier"
    agent.max_iterations = 10

    cmds = []
    if install_command:
        cmds.append(f"- Install: {install_command}")
    if test_command:
        cmds.append(f"- Test: {test_command}")
    cmd_text = (
        "\n".join(cmds)
        if cmds
        else "No specific commands provided. Try common ones (npm test, pytest, make test)."
    )

    goal_text = (
        verification_goal
        or "No explicit user visual intent provided. Validate behavior from task context."
    )

    agent.system_prompt = f"""You are a Verifier agent. Run commands to check that code changes work.

Commands to run:
{cmd_text}

User's intended outcome to verify against:
{goal_text}

Steps:
1. Establish install commands deterministically from repository manifests unless install_command is explicitly provided.
    - Use lockfiles/manifests in priority order: `pnpm-lock.yaml` -> `pnpm install --frozen-lockfile`; `yarn.lock` -> `yarn install --frozen-lockfile`; `package-lock.json` -> `npm ci`; `package.json` -> `npm install`; `requirements.txt` -> `pip install -r requirements.txt`; `pyproject.toml` -> `pip install -e .`.
    - Handle repo subdirectories (`frontend/`, `backend/`) when manifests are there.
2. Run the install command(s).
3. Run the test command if specified, else infer from manifests (`npm test`, `pytest`, etc.) and execute.
4. Proactively determine if browser verification is needed. If frontend indicators exist (e.g., `frontend/`, `package.json`, `vite.config`, `next.config`, `src/` UI code, HTML/CSS/TSX changes), you MUST run browser verification without waiting for additional user instruction.
5. For browser verification, start the app server in background, wait for readiness, and capture screenshots using `take_screenshot` for sensible default routes (`/`, and any obvious route in code).
6. Try common local ports if needed (5173, 3000, 8080) and continue on failure with clear evidence.
7. Compare screenshots against the user's intended outcome and explicitly state whether the visual result matches, partially matches, or does not match.
8. Report pass/fail with evidence.

Rules:
- Do NOT run any git/github commands (no add/commit/push/branch/pr).
- Do NOT modify product files. Only run verification commands and capture evidence.
- Keep verification generic across repos; do not assume specific frameworks unless command output confirms it.
- If browser verification is applicable, do not skip it just because the user did not explicitly request screenshots.
- Do NOT install arbitrary new packages unless required by repository manifests or required to run the repository's own declared commands.

Output valid JSON:
{{
  "passed": true/false,
  "test_summary": "brief summary of test results or visual verification",
  "failure_reason": null or "why it failed"
}}"""
    return agent

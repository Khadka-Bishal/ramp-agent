import asyncio
import base64
import os
from pathlib import Path

import modal

from backend.sandbox.provider import CommandResult, Sandbox, SandboxProvider

# Ensure the Modal App is created/looked up
_app = modal.App.lookup("ramp-agent-sandbox", create_if_missing=True)


class ModalSandbox(SandboxProvider):
    def __init__(self):
        # We define a robust base image with standard web/python tools
        self.image = (
            modal.Image.debian_slim(python_version="3.11")
            .apt_install(["git", "curl", "wget", "gnupg"])
            .run_commands("curl -fsSL https://deb.nodesource.com/setup_20.x | bash -")
            .apt_install(["nodejs"])
            .pip_install("pytest", "playwright")
            .run_commands("npx playwright install-deps chromium")
            .run_commands("npx playwright install chromium")
        )

    async def create(self, repo_url: str, github_token: str | None = None) -> Sandbox:
        # Start a persistent sandbox container that idles
        sb = await modal.Sandbox.create.aio(
            "bash",
            "-c",
            "sleep infinity",
            app=_app,
            image=self.image,
            timeout=3600,
        )

        clone_url = repo_url
        if github_token and "github.com" in repo_url:
            clone_url = repo_url.replace("https://", f"https://x-access-token:{github_token}@")

        # Clone the repository
        proc = await sb.exec.aio("git", "clone", "--depth", "1", clone_url, "/repo")
        await proc.wait.aio()

        if proc.returncode != 0:
            stderr = await proc.stderr.read.aio()
            await sb.terminate.aio()
            raise RuntimeError(f"Modal git clone failed: {stderr}")

        # The sandbox object has the actual modal.Sandbox instance stored off the side
        sandbox = Sandbox(workspace=Path("/repo"))
        sandbox._modal_sb = sb
        return sandbox

    async def run_command(self, sandbox: Sandbox, cmd: str, timeout: int = 60) -> CommandResult:
        sb: modal.Sandbox = getattr(sandbox, "_modal_sb", None)
        if not sb:
            raise RuntimeError("Underlying modal sandbox not found")

        try:
            # We execute commands through bash, wrapped with timeout if necessary
            proc = await sb.exec.aio(
                "bash",
                "-c",
                cmd,
                workdir=str(sandbox.workspace),
                env=sandbox._env if sandbox._env else None,
            )
            
            # Modal doesn't have a direct timeout kwarg on exec wait() yet,
            # so we use asyncio.wait_for around the wait() call
            await asyncio.wait_for(proc.wait.aio(), timeout=timeout)

            stdout = await proc.stdout.read.aio()
            stderr = await proc.stderr.read.aio()

            return CommandResult(
                exit_code=proc.returncode,
                stdout=stdout if isinstance(stdout, str) else stdout.decode("utf-8", "replace"),
                stderr=stderr if isinstance(stderr, str) else stderr.decode("utf-8", "replace"),
            )
        except asyncio.TimeoutError:
            # Re-fetch the process maybe? Or just bail.
            return CommandResult(exit_code=-1, stdout="", stderr="Command timed out")

    async def read_file(self, sandbox: Sandbox, path: str) -> str:
        sb: modal.Sandbox = getattr(sandbox, "_modal_sb", None)
        target = f"{sandbox.workspace}/{path}"
        
        proc = await sb.exec.aio("cat", target)
        await proc.wait.aio()
        if proc.returncode != 0:
            raise FileNotFoundError(f"Not found: {path}")

        content = await proc.stdout.read.aio()
        return content if isinstance(content, str) else content.decode("utf-8", "replace")

    async def write_file(self, sandbox: Sandbox, path: str, content: str) -> None:
        sb: modal.Sandbox = getattr(sandbox, "_modal_sb", None)
        target = f"{sandbox.workspace}/{path}"
        parent = str(Path(target).parent)
        
        # Ensure parent dir exists
        proc_mkdir = await sb.exec.aio("mkdir", "-p", parent)
        await proc_mkdir.wait.aio()

        # Write file using base64 via bash to safely pass complex content
        b64_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        cmd = f"echo '{b64_content}' | base64 -d > '{target}'"
        
        proc = await sb.exec.aio("bash", "-c", cmd)
        await proc.wait.aio()
        if proc.returncode != 0:
            stderr = await proc.stderr.read.aio()
            raise RuntimeError(f"Failed to write file {path}: {stderr}")

    async def list_dir(self, sandbox: Sandbox, path: str = ".") -> list[str]:
        sb: modal.Sandbox = getattr(sandbox, "_modal_sb", None)
        target = f"{sandbox.workspace}/{path}"

        # Use ls -F to identify directories natively
        proc = await sb.exec.aio("ls", "-1F", target)
        await proc.wait.aio()
        
        if proc.returncode != 0:
            raise FileNotFoundError(f"Not found: {path} (in workspace {sandbox.workspace})")

        out = await proc.stdout.read.aio()
        out_str = out if isinstance(out, str) else out.decode("utf-8")
        
        entries = []
        for line in out_str.strip().split("\n"):
            if not line:
                continue
            entries.append(line)
        return entries

    async def destroy(self, sandbox: Sandbox) -> None:
        sb: modal.Sandbox = getattr(sandbox, "_modal_sb", None)
        if sb:
            await sb.terminate.aio()

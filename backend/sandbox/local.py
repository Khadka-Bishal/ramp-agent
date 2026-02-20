import asyncio
import shutil
import tempfile
from pathlib import Path

from backend.sandbox.provider import CommandResult, Sandbox, SandboxProvider


class LocalSandbox(SandboxProvider):
    async def create(self, repo_url: str, github_token: str | None = None) -> Sandbox:
        workspace = Path(tempfile.mkdtemp(prefix="ramp_"))
        clone_url = repo_url
        if github_token and "github.com" in repo_url:
            clone_url = repo_url.replace(
                "https://", f"https://x-access-token:{github_token}@"
            )

        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", clone_url, str(workspace / "repo"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            shutil.rmtree(workspace, ignore_errors=True)
            raise RuntimeError(
                f"git clone failed (exit {proc.returncode}): {stderr.decode()}"
            )
        return Sandbox(workspace=workspace / "repo")

    async def run_command(
        self, sandbox: Sandbox, cmd: str, timeout: int = 60
    ) -> CommandResult:
        try:
            import os
            env = os.environ.copy()
            if sandbox._env:
                env.update(sandbox._env)
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(sandbox.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return CommandResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
        except asyncio.TimeoutError:
            proc.kill()
            return CommandResult(exit_code=-1, stdout="", stderr="Command timed out")

    async def read_file(self, sandbox: Sandbox, path: str) -> str:
        target = sandbox.workspace / path
        if not target.is_relative_to(sandbox.workspace):
            raise PermissionError(f"Path escapes workspace: {path}")
        if not target.exists():
            raise FileNotFoundError(f"Not found: {path}")
        if target.is_dir():
            entries = [str(e.relative_to(sandbox.workspace)) + ("/" if e.is_dir() else "") for e in sorted(target.iterdir())]
            raise IsADirectoryError(f"'{path}' is a directory. Contents:\n" + "\n".join(entries[:50]))
        try:
            return target.read_text()
        except UnicodeDecodeError:
            size = target.stat().st_size
            return f"[binary file, {size} bytes]"

    async def write_file(self, sandbox: Sandbox, path: str, content: str) -> None:
        target = sandbox.workspace / path
        if not target.is_relative_to(sandbox.workspace):
            raise PermissionError(f"Path escapes workspace: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    async def list_dir(self, sandbox: Sandbox, path: str = ".") -> list[str]:
        target = sandbox.workspace / path
        if not target.is_relative_to(sandbox.workspace):
            raise PermissionError(f"Path escapes workspace: {path}")
        entries = []
        for entry in sorted(target.iterdir()):
            rel = str(entry.relative_to(sandbox.workspace))
            if entry.is_dir():
                entries.append(f"{rel}/")
            else:
                entries.append(rel)
        return entries

    async def destroy(self, sandbox: Sandbox) -> None:
        root = sandbox.workspace.parent if sandbox.workspace.name == "repo" else sandbox.workspace
        shutil.rmtree(root, ignore_errors=True)

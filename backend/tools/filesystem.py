from backend.sandbox.provider import SandboxProvider, Sandbox


async def read_file(sandbox_provider: SandboxProvider, sandbox: Sandbox, path: str) -> str:
    return await sandbox_provider.read_file(sandbox, path)


async def write_file(
    sandbox_provider: SandboxProvider, sandbox: Sandbox, path: str, content: str
) -> str:
    await sandbox_provider.write_file(sandbox, path, content)
    return f"Wrote {len(content)} chars to {path}"


async def create_file(
    sandbox_provider: SandboxProvider, sandbox: Sandbox, path: str, content: str
) -> str:
    await sandbox_provider.write_file(sandbox, path, content)
    return f"Created {path} ({len(content)} chars)"


async def delete_file(
    sandbox_provider: SandboxProvider, sandbox: Sandbox, path: str
) -> str:
    target = sandbox.workspace / path
    if not target.is_relative_to(sandbox.workspace):
        raise PermissionError(f"Path escapes workspace: {path}")
    if target.exists():
        target.unlink()
        return f"Deleted {path}"
    return f"{path} not found"


async def list_directory(
    sandbox_provider: SandboxProvider, sandbox: Sandbox, path: str = "."
) -> str:
    entries = await sandbox_provider.list_dir(sandbox, path)
    return "\n".join(entries)

from backend.sandbox.provider import CommandResult, SandboxProvider, Sandbox


async def run_command(
    sandbox_provider: SandboxProvider,
    sandbox: Sandbox,
    command: str,
    timeout: int = 60,
) -> dict:
    result: CommandResult = await sandbox_provider.run_command(sandbox, command, timeout)
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout[:50_000],  # truncate to avoid blowing up context
        "stderr": result.stderr[:10_000],
    }

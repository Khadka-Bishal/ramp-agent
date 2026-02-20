# TODO: Modal sandbox implementation
# This module will implement SandboxProvider using Modal containers.
# For now, use LocalSandbox from backend.sandbox.local
from backend.sandbox.provider import SandboxProvider


class ModalSandbox(SandboxProvider):
    async def create(self, repo_url, github_token=None):
        raise NotImplementedError("Modal sandbox not yet implemented")

    async def run_command(self, sandbox, cmd, timeout=60):
        raise NotImplementedError("Modal sandbox not yet implemented")

    async def read_file(self, sandbox, path):
        raise NotImplementedError("Modal sandbox not yet implemented")

    async def write_file(self, sandbox, path, content):
        raise NotImplementedError("Modal sandbox not yet implemented")

    async def list_dir(self, sandbox, path="."):
        raise NotImplementedError("Modal sandbox not yet implemented")

    async def destroy(self, sandbox):
        raise NotImplementedError("Modal sandbox not yet implemented")

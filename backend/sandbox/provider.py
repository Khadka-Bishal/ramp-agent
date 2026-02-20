from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class Sandbox:
    workspace: Path
    _env: dict[str, str] = field(default_factory=dict)


class SandboxProvider(ABC):
    @abstractmethod
    async def create(self, repo_url: str, github_token: str | None = None) -> Sandbox:
        ...

    @abstractmethod
    async def run_command(
        self, sandbox: Sandbox, cmd: str, timeout: int = 60
    ) -> CommandResult:
        ...

    @abstractmethod
    async def read_file(self, sandbox: Sandbox, path: str) -> str:
        ...

    @abstractmethod
    async def write_file(self, sandbox: Sandbox, path: str, content: str) -> None:
        ...

    @abstractmethod
    async def list_dir(self, sandbox: Sandbox, path: str = ".") -> list[str]:
        ...

    @abstractmethod
    async def destroy(self, sandbox: Sandbox) -> None:
        ...

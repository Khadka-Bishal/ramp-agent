from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./ramp_agent.db"
    github_token: str = ""
    anthropic_api_key: str = ""
    max_runtime_seconds: int = 300
    max_iterations: int = 50
    max_artifact_size_mb: int = 10
    artifacts_dir: Path = Path("./artifacts")
    use_modal: bool = True
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Modal can read these from .env directly, but Pydantic requires them defined
    modal_token_id: str | None = None
    modal_token_secret: str | None = None
    modal_profile: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

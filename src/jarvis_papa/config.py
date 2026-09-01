from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local Jarvis configuration loaded from environment variables or .env."""

    app_name: str = "Jarvis Papa"
    user_name: str = "Robert"
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    runtime_dir: Path = Path("./runtime")
    speech_enabled: bool = True
    speech_repeat_cooldown_seconds: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JARVIS_",
        extra="ignore",
    )


settings = Settings()

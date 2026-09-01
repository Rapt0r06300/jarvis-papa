import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _data_dir() -> Path:
    """Return a stable writable directory for the installed Windows application."""

    if _is_frozen() and sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "JarvisPapa"
    return Path(".")


_DATA_DIR = _data_dir()
_ENV_FILE = _DATA_DIR / ".env" if _is_frozen() else Path(".env")
_RUNTIME_DIR = _DATA_DIR / "runtime" if _is_frozen() else Path("./runtime")
_QWEN_PYTHON = (
    str(_DATA_DIR / "qwen-tts" / "Scripts" / "python.exe")
    if _is_frozen() and sys.platform == "win32"
    else ".venv-qwen-tts/Scripts/python.exe"
)


class Settings(BaseSettings):
    """Local Jarvis configuration loaded from environment variables or a per-user .env."""

    app_name: str = "Jarvis Papa"
    user_name: str = "Robert"
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    runtime_dir: Path = _RUNTIME_DIR

    speech_enabled: bool = True
    speech_repeat_cooldown_seconds: int = 300

    # Voice output: premium cloud first, high-quality local fallback, Windows last resort.
    voice_provider_order: str = "elevenlabs,azure,qwen3,windows"
    voice_sensitive_provider_order: str = "qwen3,windows"
    voice_cloud_for_sensitive_content: bool = False
    voice_speed: float = 0.95
    voice_http_timeout_seconds: float = 30.0
    voice_cache_files: int = 40
    voice_windows_fallback_enabled: bool = True

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_v3"
    elevenlabs_output_format: str = "mp3_44100_128"
    elevenlabs_stability: float = 0.45
    elevenlabs_similarity_boost: float = 0.78
    elevenlabs_style: float = 0.22

    azure_speech_key: str = ""
    azure_speech_region: str = ""
    azure_speech_endpoint: str = ""
    azure_voice_name: str = "fr-FR-VivienneMultilingualNeural"
    azure_voice_style: str = ""
    azure_output_format: str = "audio-24khz-48kbitrate-mono-mp3"

    qwen3_tts_enabled: bool = True
    qwen3_tts_python: str = _QWEN_PYTHON
    qwen3_tts_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    qwen3_tts_language: str = "French"
    qwen3_tts_speaker: str = "Serena"
    qwen3_tts_device: str = "cuda:0"
    qwen3_tts_timeout_seconds: float = 180.0
    qwen3_tts_worker_port: int = 8766
    qwen3_tts_startup_timeout_seconds: float = 180.0
    qwen3_tts_idle_timeout_seconds: int = 900
    qwen3_tts_prewarm: bool = True
    qwen3_tts_instruction: str = (
        "Jeune femme française adulte, voix douce, chaleureuse, naturelle et rassurante. "
        "Français de France impeccable, articulation très claire, débit calme et vivant, "
        "intonation humaine, jamais robotique ni théâtrale."
    )

    file_search_timeout_seconds: float = 3.0
    file_search_roots: tuple[Path, ...] = (
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path.home() / "Downloads",
    )
    file_allowed_extensions: tuple[str, ...] = (
        ".pdf",
        ".txt",
        ".md",
        ".csv",
        ".doc",
        ".docx",
        ".odt",
        ".xls",
        ".xlsx",
        ".ods",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".eml",
    )
    attachment_max_bytes: int = 25 * 1024 * 1024

    thunderbird_native_host_name: str = "fr.jarvis_papa.host"

    ai_enabled: bool = True
    ai_provider: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    ai_timeout_seconds: float = 25.0
    ai_temperature: float = 0.2

    browser_timeout_seconds: float = 20.0
    browser_max_text_chars: int = 12000
    browser_download_max_bytes: int = 50 * 1024 * 1024
    browser_download_extensions: tuple[str, ...] = (
        ".pdf",
        ".txt",
        ".csv",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".zip",
    )

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_prefix="JARVIS_",
        extra="ignore",
    )


settings = Settings()

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

    # Voice output: premium cloud first, high-quality local fallback, Windows last resort.
    voice_provider_order: str = "elevenlabs,azure,qwen3,windows"
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
    qwen3_tts_python: str = ".venv-qwen-tts/Scripts/python.exe"
    qwen3_tts_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    qwen3_tts_language: str = "French"
    qwen3_tts_speaker: str = "Serena"
    qwen3_tts_device: str = "cuda:0"
    qwen3_tts_timeout_seconds: float = 180.0
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

    thunderbird_native_host_name: str = "fr.jarvis_papa.host"

    ai_enabled: bool = True
    ai_provider: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:4b"
    ai_timeout_seconds: float = 25.0
    ai_temperature: float = 0.2

    browser_timeout_seconds: float = 20.0
    browser_max_text_chars: int = 12000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JARVIS_",
        extra="ignore",
    )


settings = Settings()

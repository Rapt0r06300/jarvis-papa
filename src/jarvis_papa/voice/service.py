from __future__ import annotations

import base64
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import httpx

from jarvis_papa.config import settings
from jarvis_papa.voice.providers import (
    AzureSpeechProvider,
    ElevenLabsProvider,
    Qwen3TTSProvider,
    VoiceProvider,
    WindowsSystemProvider,
)


@dataclass(frozen=True, slots=True)
class VoiceResult:
    ok: bool
    provider: str | None = None
    file_name: str | None = None
    media_type: str | None = None
    duration_estimate_seconds: float = 0.0
    errors: tuple[str, ...] = ()
    sensitive: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "file_name": self.file_name,
            "media_type": self.media_type,
            "duration_estimate_seconds": self.duration_estimate_seconds,
            "errors": list(self.errors),
            "sensitive": self.sensitive,
        }


class VoicePlaybackBus:
    def __init__(self) -> None:
        self._events: deque[dict[str, object]] = deque(maxlen=30)
        self._counter = 0
        self._lock = Lock()

    def publish(self, *, text: str, provider: str, duration: float) -> int:
        with self._lock:
            self._counter += 1
            event_id = self._counter
            self._events.append(
                {
                    "id": event_id,
                    "text": text,
                    "provider": provider,
                    "duration_estimate_seconds": duration,
                    "created_at": time.time(),
                }
            )
            return event_id

    def after(self, event_id: int) -> list[dict[str, object]]:
        with self._lock:
            return [dict(item) for item in self._events if int(item["id"]) > event_id]


class WindowsAudioPlayer:
    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def play_async(self, path: Path, duration_seconds: float) -> bool:
        if not self.available or not path.exists():
            return False
        encoded = base64.b64encode(str(path.resolve()).encode("utf-8")).decode("ascii")
        wait_ms = max(1800, int((duration_seconds + 1.0) * 1000))
        script = (
            f"$b=[Convert]::FromBase64String('{encoded}');"
            "$p=[Text.Encoding]::UTF8.GetString($b);"
            "Add-Type -AssemblyName PresentationCore;"
            "$m=New-Object System.Windows.Media.MediaPlayer;"
            "$m.Open([Uri]$p);Start-Sleep -Milliseconds 250;$m.Play();"
            f"Start-Sleep -Milliseconds {wait_ms};$m.Close();"
        )
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True


class VoiceService:
    def __init__(self, providers: dict[str, VoiceProvider] | None = None) -> None:
        self.providers = providers or {
            "elevenlabs": ElevenLabsProvider(),
            "azure": AzureSpeechProvider(),
            "qwen3": Qwen3TTSProvider(),
            "windows": WindowsSystemProvider(),
        }
        self.player = WindowsAudioPlayer()
        self.events = VoicePlaybackBus()
        self._last_result = VoiceResult(ok=False)
        self._lock = Lock()

    @property
    def output_dir(self) -> Path:
        path = settings.runtime_dir / "voice"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def provider_order(self, *, sensitive: bool = False) -> tuple[str, ...]:
        configured = (
            settings.voice_provider_order
            if not sensitive or settings.voice_cloud_for_sensitive_content
            else settings.voice_sensitive_provider_order
        )
        names = tuple(item.strip().lower() for item in configured.split(",") if item.strip())
        if names:
            return names
        return ("qwen3", "windows") if sensitive else ("elevenlabs", "azure", "qwen3", "windows")

    def prewarm_async(self) -> bool:
        provider = self.providers.get("qwen3")
        if not isinstance(provider, Qwen3TTSProvider):
            return False
        return provider.warm_async()

    def shutdown(self) -> None:
        provider = self.providers.get("qwen3")
        if isinstance(provider, Qwen3TTSProvider):
            provider.shutdown()

    def status(self) -> dict[str, object]:
        provider_states: dict[str, dict[str, object]] = {}
        for name, provider in self.providers.items():
            state_method = getattr(provider, "status", None)
            if callable(state_method):
                state = state_method()
                provider_states[name] = dict(state) if isinstance(state, dict) else {"available": provider.available}
            else:
                provider_states[name] = {"available": provider.available}
        return {
            "enabled": settings.speech_enabled,
            "language": "fr-FR",
            "persona": "jeune_femme_française_douce",
            "provider_order": list(self.provider_order()),
            "sensitive_provider_order": list(self.provider_order(sensitive=True)),
            "cloud_for_sensitive_content": settings.voice_cloud_for_sensitive_content,
            "prewarm_enabled": settings.qwen3_tts_prewarm,
            "providers": provider_states,
            "last_result": self._last_result.to_dict(),
        }

    def synthesize(self, text: str, *, sensitive: bool = False) -> VoiceResult:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return VoiceResult(ok=False, errors=("Texte vocal vide.",), sensitive=sensitive)
        stem = self.output_dir / f"voice-{uuid.uuid4().hex}"
        errors: list[str] = []
        for name in self.provider_order(sensitive=sensitive):
            provider = self.providers.get(name)
            if provider is None:
                errors.append(f"{name}: fournisseur inconnu")
                continue
            if not provider.available:
                errors.append(f"{name}: indisponible")
                continue
            try:
                artifact = provider.synthesize(cleaned, stem)
            except (RuntimeError, OSError, httpx.HTTPError, subprocess.SubprocessError) as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            duration = self._estimate_duration(cleaned)
            result = VoiceResult(
                ok=True,
                provider=artifact.provider,
                file_name=artifact.path.name,
                media_type=artifact.media_type,
                duration_estimate_seconds=duration,
                errors=tuple(errors),
                sensitive=sensitive,
            )
            with self._lock:
                self._last_result = result
            self._cleanup_old_files()
            return result

        result = VoiceResult(ok=False, errors=tuple(errors), sensitive=sensitive)
        with self._lock:
            self._last_result = result
        return result

    def speak(self, text: str, *, sensitive: bool = False) -> VoiceResult:
        result = self.synthesize(text, sensitive=sensitive)
        if not result.ok or not result.file_name or not result.provider:
            return result
        path = self.output_dir / result.file_name
        self.player.play_async(path, result.duration_estimate_seconds)
        self.events.publish(
            text=" ".join(text.split()),
            provider=result.provider,
            duration=result.duration_estimate_seconds,
        )
        return result

    def resolve_audio(self, file_name: str) -> Path | None:
        if Path(file_name).name != file_name:
            return None
        path = self.output_dir / file_name
        return path if path.is_file() else None

    @staticmethod
    def _estimate_duration(text: str) -> float:
        words = max(1, len(text.split()))
        speed = max(0.6, settings.voice_speed)
        return min(45.0, max(1.6, 0.55 + words / (2.6 * speed)))

    def _cleanup_old_files(self) -> None:
        files = sorted(
            (item for item in self.output_dir.glob("voice-*") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for item in files[settings.voice_cache_files :]:
            try:
                item.unlink()
            except OSError:
                pass


voice_service = VoiceService()

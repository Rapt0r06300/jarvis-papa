from __future__ import annotations

import base64
import heapq
import re
import subprocess
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Lock, Thread
from typing import ClassVar

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


@dataclass(frozen=True, slots=True)
class _PlaybackItem:
    utterance_id: str
    text: str
    path: Path
    provider: str
    duration: float
    priority: int


class VoicePlaybackBus:
    def __init__(self) -> None:
        self._events: deque[dict[str, object]] = deque(maxlen=120)
        self._counter = 0
        self._lock = Lock()

    def publish(
        self,
        *,
        text: str,
        provider: str,
        duration: float,
        event_type: str = "speech_queued",
        utterance_id: str | None = None,
    ) -> int:
        with self._lock:
            self._counter += 1
            event_id = self._counter
            self._events.append(
                {
                    "id": event_id,
                    "type": event_type,
                    "utterance_id": utterance_id or "",
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
    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = Lock()

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def play(self, path: Path, duration_seconds: float) -> bool:
        if not self.available or not path.exists():
            time.sleep(min(0.02, max(0.0, duration_seconds)))
            return path.exists()
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
        try:
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return False
        with self._lock:
            self._process = process
        try:
            return process.wait() == 0
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

    def stop(self) -> bool:
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return False
        try:
            process.terminate()
            process.wait(timeout=0.8)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        return True


class VoiceService:
    _PRIORITIES: ClassVar[dict[str, int]] = {
        "critical": 0,
        "high": 1,
        "normal": 2,
        "low": 3,
    }

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
        self._condition = Condition(Lock())
        self._queue: list[tuple[int, int, _PlaybackItem]] = []
        self._sequence = 0
        self._current: _PlaybackItem | None = None
        self._current_interrupted = False
        self._stopping = False
        self._worker = Thread(target=self._playback_loop, name="JarvisVoicePlayback", daemon=True)
        self._worker.start()

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
        self.stop(clear_queue=True)
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        if self._worker.is_alive():
            self._worker.join(timeout=1.5)
        provider = self.providers.get("qwen3")
        if isinstance(provider, Qwen3TTSProvider):
            provider.shutdown()

    def status(self) -> dict[str, object]:
        provider_states: dict[str, dict[str, object]] = {}
        for name, provider in self.providers.items():
            state_method = getattr(provider, "status", None)
            if callable(state_method):
                state = state_method()
                provider_states[name] = (
                    dict(state) if isinstance(state, dict) else {"available": provider.available}
                )
            else:
                provider_states[name] = {"available": provider.available}
        with self._condition:
            queue_length = len(self._queue)
            current = self._current
        return {
            "enabled": settings.speech_enabled,
            "language": "fr-FR",
            "persona": "jeune_femme_française_douce",
            "provider_order": list(self.provider_order()),
            "sensitive_provider_order": list(self.provider_order(sensitive=True)),
            "cloud_for_sensitive_content": settings.voice_cloud_for_sensitive_content,
            "prewarm_enabled": settings.qwen3_tts_prewarm,
            "providers": provider_states,
            "queue_length": queue_length,
            "speaking": current is not None,
            "current_utterance_id": current.utterance_id if current else None,
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

    def speak(
        self,
        text: str,
        *,
        sensitive: bool = False,
        priority: str = "normal",
    ) -> VoiceResult:
        cleaned = " ".join(text.split()).strip()
        chunks = self._split_text(cleaned)
        if not chunks:
            return VoiceResult(ok=False, errors=("Texte vocal vide.",), sensitive=sensitive)
        priority_value = self._PRIORITIES.get(priority.casefold(), self._PRIORITIES["normal"])
        first_result: VoiceResult | None = None
        errors: list[str] = []
        enqueued = 0
        utterance_root = uuid.uuid4().hex
        for index, chunk in enumerate(chunks):
            result = self.synthesize(chunk, sensitive=sensitive)
            if first_result is None:
                first_result = result
            errors.extend(result.errors)
            if not result.ok or not result.file_name or not result.provider:
                continue
            item = _PlaybackItem(
                utterance_id=f"{utterance_root}:{index}",
                text=chunk,
                path=self.output_dir / result.file_name,
                provider=result.provider,
                duration=result.duration_estimate_seconds,
                priority=priority_value,
            )
            self._enqueue(item)
            enqueued += 1
        if first_result is None or enqueued == 0:
            return VoiceResult(
                ok=False,
                errors=tuple(errors or (first_result.errors if first_result else ())),
                sensitive=sensitive,
            )
        return VoiceResult(
            ok=True,
            provider=first_result.provider,
            file_name=first_result.file_name,
            media_type=first_result.media_type,
            duration_estimate_seconds=sum(self._estimate_duration(chunk) for chunk in chunks),
            errors=tuple(errors),
            sensitive=sensitive,
        )

    def stop(self, *, clear_queue: bool = True) -> bool:
        with self._condition:
            had_work = self._current is not None or bool(self._queue)
            if clear_queue:
                self._queue.clear()
            if self._current is not None:
                self._current_interrupted = True
            self._condition.notify_all()
        player_stopped = self.player.stop()
        return had_work or player_stopped

    def resolve_audio(self, file_name: str) -> Path | None:
        if Path(file_name).name != file_name:
            return None
        path = self.output_dir / file_name
        return path if path.is_file() else None

    def _enqueue(self, item: _PlaybackItem) -> None:
        preempt = False
        with self._condition:
            self._sequence += 1
            heapq.heappush(self._queue, (item.priority, self._sequence, item))
            if self._current is not None and item.priority < self._current.priority:
                self._current_interrupted = True
                preempt = True
            self._condition.notify_all()
        self.events.publish(
            text=item.text,
            provider=item.provider,
            duration=item.duration,
            event_type="speech_queued",
            utterance_id=item.utterance_id,
        )
        if preempt:
            self.player.stop()

    def _playback_loop(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._stopping:
                    self._condition.wait(timeout=1.0)
                if self._stopping:
                    return
                _, _, item = heapq.heappop(self._queue)
                self._current = item
                self._current_interrupted = False
            self.events.publish(
                text=item.text,
                provider=item.provider,
                duration=item.duration,
                event_type="speech_started",
                utterance_id=item.utterance_id,
            )
            played = self.player.play(item.path, item.duration)
            with self._condition:
                interrupted = self._current_interrupted
                self._current = None
                self._current_interrupted = False
            event_type = "speech_interrupted" if interrupted else "speech_finished"
            if not played and not interrupted:
                event_type = "speech_failed"
            self.events.publish(
                text=item.text,
                provider=item.provider,
                duration=item.duration,
                event_type=event_type,
                utterance_id=item.utterance_id,
            )

    @staticmethod
    def _split_text(text: str, limit: int = 280) -> list[str]:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return []
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?;:])\s+", cleaned)
            if item.strip()
        ]
        chunks: list[str] = []
        current = ""
        for sentence in sentences or [cleaned]:
            parts = [sentence]
            if len(sentence) > limit:
                parts = [
                    sentence[index : index + limit].strip()
                    for index in range(0, len(sentence), limit)
                    if sentence[index : index + limit].strip()
                ]
            for part in parts:
                candidate = f"{current} {part}".strip()
                if current and len(candidate) > limit:
                    chunks.append(current)
                    current = part
                else:
                    current = candidate
        if current:
            chunks.append(current)
        return chunks

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

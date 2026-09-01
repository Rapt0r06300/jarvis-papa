from __future__ import annotations

import atexit
import base64
import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class VoiceArtifact:
    provider: str
    path: Path
    media_type: str


class VoiceProvider:
    name = "base"

    @property
    def available(self) -> bool:
        return False

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        raise NotImplementedError


class ElevenLabsProvider(VoiceProvider):
    name = "elevenlabs"

    @property
    def available(self) -> bool:
        return bool(settings.elevenlabs_api_key and settings.elevenlabs_voice_id)

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        if not self.available:
            raise RuntimeError("ElevenLabs n'est pas configuré.")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{quote(settings.elevenlabs_voice_id)}"
        payload: dict[str, object] = {
            "text": text,
            "model_id": settings.elevenlabs_model,
            "voice_settings": {
                "stability": settings.elevenlabs_stability,
                "similarity_boost": settings.elevenlabs_similarity_boost,
                "style": settings.elevenlabs_style,
                "use_speaker_boost": True,
                "speed": settings.voice_speed,
            },
        }
        if settings.elevenlabs_model != "eleven_multilingual_v2":
            payload["language_code"] = "fr"
        response = httpx.post(
            url,
            params={"output_format": settings.elevenlabs_output_format},
            headers={
                "xi-api-key": settings.elevenlabs_api_key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.voice_http_timeout_seconds,
        )
        response.raise_for_status()
        path = output_stem.with_suffix(".mp3")
        path.write_bytes(response.content)
        return VoiceArtifact(self.name, path, "audio/mpeg")


class AzureSpeechProvider(VoiceProvider):
    name = "azure"

    @property
    def available(self) -> bool:
        return bool(settings.azure_speech_key and settings.azure_speech_region)

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        if not self.available:
            raise RuntimeError("Azure Speech n'est pas configuré.")
        endpoint = settings.azure_speech_endpoint.strip() or (
            f"https://{settings.azure_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"
        )
        rate_percent = round((settings.voice_speed - 1.0) * 100)
        style_open = ""
        style_close = ""
        if settings.azure_voice_style.strip():
            style = escape(settings.azure_voice_style.strip())
            style_open = f'<mstts:express-as style="{style}">'
            style_close = "</mstts:express-as>"
        ssml = (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="fr-FR">'
            f'<voice name="{escape(settings.azure_voice_name)}">'
            f"{style_open}<prosody rate=\"{rate_percent:+d}%\">{escape(text)}</prosody>{style_close}"
            "</voice></speak>"
        )
        response = httpx.post(
            endpoint,
            headers={
                "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": settings.azure_output_format,
                "User-Agent": "jarvis-papa",
            },
            content=ssml.encode("utf-8"),
            timeout=settings.voice_http_timeout_seconds,
        )
        response.raise_for_status()
        path = output_stem.with_suffix(".mp3")
        path.write_bytes(response.content)
        return VoiceArtifact(self.name, path, "audio/mpeg")


class Qwen3TTSProvider(VoiceProvider):
    """Keep the heavy local model loaded between phrases for natural response latency."""

    name = "qwen3"

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._token = secrets.token_urlsafe(32)
        self._startup_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._warming = False
        atexit.register(self.shutdown)

    @property
    def available(self) -> bool:
        python = Path(settings.qwen3_tts_python).expanduser() if settings.qwen3_tts_python else None
        return bool(settings.qwen3_tts_enabled and python and python.exists())

    @property
    def _base_url(self) -> str:
        return f"http://127.0.0.1:{settings.qwen3_tts_worker_port}"

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Jarvis-Qwen-Token": self._token}

    def warm_async(self) -> bool:
        if not self.available or self._healthy() or self._warming:
            return False
        self._warming = True

        def runner() -> None:
            try:
                self._ensure_server()
            except (RuntimeError, OSError, httpx.HTTPError):
                pass
            finally:
                self._warming = False

        threading.Thread(target=runner, name="jarvis-qwen-prewarm", daemon=True).start()
        return True

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        if not self.available:
            raise RuntimeError("Qwen3-TTS local n'est pas installé.")
        output = output_stem.with_suffix(".wav").resolve()
        self._ensure_server()
        payload = {
            "text": text,
            "instruction": settings.qwen3_tts_instruction,
            "output": str(output),
        }
        with self._request_lock:
            try:
                response = httpx.post(
                    f"{self._base_url}/synthesize",
                    headers=self._headers,
                    json=payload,
                    timeout=settings.qwen3_tts_timeout_seconds,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                self._mark_worker_unhealthy()
                raise RuntimeError("Le moteur vocal local Qwen3-TTS ne répond plus.") from exc
        if not output.is_file() or output.stat().st_size <= 44:
            raise RuntimeError("Qwen3-TTS n'a pas produit de fichier audio valide.")
        return VoiceArtifact(self.name, output, "audio/wav")

    def _healthy(self) -> bool:
        try:
            response = httpx.get(
                f"{self._base_url}/health",
                headers=self._headers,
                timeout=0.7,
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def _ensure_server(self) -> None:
        if self._healthy():
            return
        with self._startup_lock:
            if self._healthy():
                return
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None
            self._start_server_locked()

    def _start_server_locked(self) -> None:
        worker = Path(__file__).with_name("qwen_worker.py").resolve()
        output_root = (settings.runtime_dir / "voice").resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        log_path = (settings.runtime_dir / "qwen3-tts-worker.log").resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            settings.qwen3_tts_python,
            str(worker),
            "--serve",
            "--port",
            str(settings.qwen3_tts_worker_port),
            "--output-root",
            str(output_root),
            "--idle-timeout",
            str(settings.qwen3_tts_idle_timeout_seconds),
            "--model",
            settings.qwen3_tts_model,
            "--language",
            settings.qwen3_tts_language,
            "--speaker",
            settings.qwen3_tts_speaker,
            "--device",
            settings.qwen3_tts_device,
        ]
        env = os.environ.copy()
        env["JARVIS_QWEN_WORKER_TOKEN"] = self._token
        with log_path.open("ab", buffering=0) as log_handle:
            self._process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=log_handle,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        deadline = time.monotonic() + settings.qwen3_tts_startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(
                    "Qwen3-TTS s'est arrêté pendant son chargement. Consulte runtime/qwen3-tts-worker.log."
                )
            if self._healthy():
                return
            time.sleep(0.5)
        self.shutdown()
        raise RuntimeError("Qwen3-TTS a dépassé le délai de démarrage autorisé.")

    def _mark_worker_unhealthy(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            self._process = None

    def shutdown(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()


class WindowsSystemProvider(VoiceProvider):
    name = "windows"

    @property
    def available(self) -> bool:
        return sys.platform == "win32" and settings.voice_windows_fallback_enabled

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        if not self.available:
            raise RuntimeError("Synthèse Windows indisponible.")
        output = output_stem.with_suffix(".wav")
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        encoded_path = base64.b64encode(str(output).encode("utf-8")).decode("ascii")
        script = (
            f"$tb=[Convert]::FromBase64String('{encoded_text}');"
            "$text=[Text.Encoding]::UTF8.GetString($tb);"
            f"$pb=[Convert]::FromBase64String('{encoded_path}');"
            "$path=[Text.Encoding]::UTF8.GetString($pb);"
            "Add-Type -AssemblyName System.Speech;"
            "$voice=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$voice.Volume=100;$voice.Rate=-1;"
            "$fr=$voice.GetInstalledVoices() | Where-Object {$_.VoiceInfo.Culture.Name -like 'fr-*'} | Select-Object -First 1;"
            "if($fr){$voice.SelectVoice($fr.VoiceInfo.Name)};"
            "$voice.SetOutputToWaveFile($path);$voice.Speak($text);$voice.Dispose();"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=settings.voice_http_timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not output.exists():
            raise RuntimeError("La voix Windows de secours a échoué.")
        return VoiceArtifact(self.name, output, "audio/wav")

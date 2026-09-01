from __future__ import annotations

import base64
import subprocess
import sys
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
    name = "qwen3"

    @property
    def available(self) -> bool:
        python = Path(settings.qwen3_tts_python).expanduser() if settings.qwen3_tts_python else None
        return bool(settings.qwen3_tts_enabled and python and python.exists())

    def synthesize(self, text: str, output_stem: Path) -> VoiceArtifact:
        if not self.available:
            raise RuntimeError("Qwen3-TTS local n'est pas installé.")
        worker = Path(__file__).with_name("qwen_worker.py")
        output = output_stem.with_suffix(".wav")
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        encoded_instruction = base64.b64encode(
            settings.qwen3_tts_instruction.encode("utf-8")
        ).decode("ascii")
        command = [
            settings.qwen3_tts_python,
            str(worker),
            "--text-b64",
            encoded_text,
            "--instruction-b64",
            encoded_instruction,
            "--output",
            str(output),
            "--model",
            settings.qwen3_tts_model,
            "--language",
            settings.qwen3_tts_language,
            "--speaker",
            settings.qwen3_tts_speaker,
            "--device",
            settings.qwen3_tts_device,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.qwen3_tts_timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not output.exists():
            detail = completed.stderr.strip() or completed.stdout.strip() or "erreur inconnue"
            raise RuntimeError(f"Qwen3-TTS a échoué: {detail[-800:]}")
        return VoiceArtifact(self.name, output, "audio/wav")


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

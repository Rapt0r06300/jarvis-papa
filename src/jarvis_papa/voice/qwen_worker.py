from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


def load_model(model_name: str, device: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    dtype = torch.bfloat16 if str(device).startswith("cuda") else torch.float32
    load_kwargs: dict[str, object] = {
        "device_map": device,
        "dtype": dtype,
    }
    if str(device).startswith("cuda"):
        try:
            import flash_attn  # noqa: F401
        except ImportError:
            pass
        else:
            load_kwargs["attn_implementation"] = "flash_attention_2"
    return Qwen3TTSModel.from_pretrained(model_name, **load_kwargs)


def synthesize(
    model,
    *,
    model_name: str,
    text: str,
    instruction: str,
    language: str,
    speaker: str,
    output: Path,
) -> None:
    import soundfile as sf

    if "VoiceDesign" in model_name:
        wavs, sample_rate = model.generate_voice_design(
            text=text,
            language=language,
            instruct=instruction,
        )
    else:
        kwargs: dict[str, object] = {
            "text": text,
            "language": language,
            "speaker": speaker,
        }
        if "1.7B" in model_name and instruction:
            kwargs["instruct"] = instruction
        wavs, sample_rate = model.generate_custom_voice(**kwargs)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), wavs[0], sample_rate)


class QwenServer(HTTPServer):
    model: Any
    model_name: str
    language: str
    speaker: str
    output_root: Path
    auth_token: str
    idle_timeout_seconds: int
    last_activity: float


class QwenHandler(BaseHTTPRequestHandler):
    server: QwenServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _authorized(self) -> bool:
        return bool(
            self.server.auth_token
            and self.headers.get("X-Jarvis-Qwen-Token") == self.server.auth_token
        )

    def _reply(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/health" or not self._authorized():
            self._reply(403, {"ok": False})
            return
        self.server.last_activity = time.monotonic()
        self._reply(200, {"ok": True, "model": self.server.model_name})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/synthesize" or not self._authorized():
            self._reply(403, {"ok": False})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 128 * 1024:
            self._reply(400, {"ok": False, "error": "invalid_payload_size"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._reply(400, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._reply(400, {"ok": False, "error": "invalid_payload"})
            return

        text = " ".join(str(payload.get("text") or "").split()).strip()
        instruction = " ".join(str(payload.get("instruction") or "").split()).strip()
        raw_output = str(payload.get("output") or "")
        if not text or len(text) > 6000 or not raw_output:
            self._reply(400, {"ok": False, "error": "invalid_synthesis_request"})
            return
        try:
            output = Path(raw_output).resolve()
            output.relative_to(self.server.output_root)
        except (OSError, ValueError):
            self._reply(400, {"ok": False, "error": "invalid_output_path"})
            return
        if output.suffix.casefold() != ".wav":
            self._reply(400, {"ok": False, "error": "invalid_output_type"})
            return

        self.server.last_activity = time.monotonic()
        try:
            synthesize(
                self.server.model,
                model_name=self.server.model_name,
                text=text,
                instruction=instruction,
                language=self.server.language,
                speaker=self.server.speaker,
                output=output,
            )
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            self._reply(
                500,
                {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[-600:]}"},
            )
            return
        self.server.last_activity = time.monotonic()
        self._reply(200, {"ok": True, "output": str(output)})


def serve(args: argparse.Namespace) -> int:
    token = os.environ.get("JARVIS_QWEN_WORKER_TOKEN", "")
    if not token:
        raise RuntimeError("Jeton local Qwen manquant.")
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    model = load_model(args.model, args.device)
    server = QwenServer(("127.0.0.1", args.port), QwenHandler)
    server.model = model
    server.model_name = args.model
    server.language = args.language
    server.speaker = args.speaker
    server.output_root = output_root
    server.auth_token = token
    server.idle_timeout_seconds = max(60, args.idle_timeout)
    server.last_activity = time.monotonic()
    server.timeout = 1.0
    while time.monotonic() - server.last_activity < server.idle_timeout_seconds:
        server.handle_request()
    server.server_close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Persistent Qwen3-TTS worker for Jarvis Papa")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--output-root", default="runtime/voice")
    parser.add_argument("--idle-timeout", type=int, default=900)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", default="French")
    parser.add_argument("--speaker", default="Serena")
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    if not args.serve:
        raise RuntimeError("Ce worker doit être lancé en mode --serve par Jarvis.")
    return serve(args)


if __name__ == "__main__":
    raise SystemExit(main())

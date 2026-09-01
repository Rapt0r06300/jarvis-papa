from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock

from jarvis_papa.config import settings

_SENSITIVE_KEYS = {
    "password",
    "mot_de_passe",
    "api_key",
    "token",
    "authorization_token",
    "body",
    "text",
    "content",
}


class AuditLog:
    """Small local JSONL trail with aggressive redaction and bounded size."""

    def __init__(self, path: Path | None = None, max_bytes: int = 5 * 1024 * 1024) -> None:
        self.path = path or (settings.runtime_dir / "audit.jsonl")
        self.max_bytes = max_bytes
        self._lock = Lock()

    def record(
        self,
        event: str,
        *,
        action: str = "",
        ok: bool | None = None,
        detail: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "ts": time.time(),
            "event": event[:100],
            "action": action[:160],
            "ok": ok,
            "detail": " ".join(detail.split())[:500],
            "metadata": self._redact(metadata or {}),
        }
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_locked(len(line.encode("utf-8")))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def recent(self, limit: int = 50) -> list[dict[str, object]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        results = []
        for line in lines[-max(1, min(limit, 200)) :]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                results.append(item)
        return results

    def _rotate_locked(self, incoming_bytes: int) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size + incoming_bytes <= self.max_bytes:
            return
        backup = self.path.with_suffix(".1.jsonl")
        try:
            backup.unlink(missing_ok=True)
            self.path.replace(backup)
        except OSError:
            pass

    @classmethod
    def _redact(cls, value: object) -> object:
        if isinstance(value, dict):
            output: dict[str, object] = {}
            for key, item in value.items():
                lowered = str(key).casefold()
                output[str(key)[:100]] = "[redacted]" if lowered in _SENSITIVE_KEYS else cls._redact(item)
            return output
        if isinstance(value, (list, tuple)):
            return [cls._redact(item) for item in value[:30]]
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:300]


audit_log = AuditLog()

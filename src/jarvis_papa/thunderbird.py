import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from uuid import uuid4

from jarvis_papa.config import settings


_VERIFIED_MUTATION_KINDS = frozenset(
    {
        "prepare_reply",
        "send_reply",
        "sort_newsletters",
    }
)


@dataclass(slots=True)
class ThunderbirdCommand:
    id: str
    kind: str
    payload: dict[str, object] = field(default_factory=dict)
    context: dict[str, object] = field(default_factory=dict)
    status: str = "pending"
    error: str | None = None
    result: dict[str, object] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def acknowledged(self) -> bool:
        return self.status in {"succeeded", "failed"}

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"acknowledged": self.acknowledged}


class ThunderbirdBridgeState:
    """Tracks whether the Thunderbird extension/native host is actually alive."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_seen: float | None = None
        self._source = ""
        self._pid: int | None = None

    def mark_seen(self, source: str = "native_host", pid: int | None = None) -> None:
        with self._lock:
            self._last_seen = time.time()
            self._source = source[:80]
            self._pid = pid if isinstance(pid, int) and pid > 0 else None

    def snapshot(self, *, timeout_seconds: float = 12.0) -> dict[str, object]:
        with self._lock:
            last_seen = self._last_seen
            source = self._source
            pid = self._pid
        if last_seen is None:
            return {
                "connected": False,
                "last_seen": None,
                "age_seconds": None,
                "source": source,
                "pid": pid,
            }
        age = max(0.0, time.time() - last_seen)
        return {
            "connected": age <= timeout_seconds,
            "last_seen": last_seen,
            "age_seconds": round(age, 2),
            "source": source,
            "pid": pid,
        }


class ThunderbirdCommandQueue:
    def __init__(self, path: Path | None = None, max_items: int = 200) -> None:
        self.path = path or (settings.runtime_dir / "thunderbird_commands.json")
        self.max_items = max_items
        self._commands: list[ThunderbirdCommand] = []
        self._lock = Lock()
        self._load()

    def enqueue(
        self,
        kind: str,
        payload: dict[str, object] | None = None,
        *,
        context: dict[str, object] | None = None,
    ) -> ThunderbirdCommand:
        command = ThunderbirdCommand(
            id=uuid4().hex,
            kind=kind,
            payload=payload or {},
            context=context or {},
        )
        with self._lock:
            self._commands.append(command)
            self._trim_locked()
            self._save_locked()
        return command

    def pending(self) -> list[ThunderbirdCommand]:
        with self._lock:
            return [command for command in self._commands if command.status == "pending"]

    def get(self, command_id: str) -> ThunderbirdCommand | None:
        with self._lock:
            return next((command for command in self._commands if command.id == command_id), None)

    def acknowledge(
        self,
        command_id: str,
        *,
        ok: bool,
        error: str | None = None,
        result: dict[str, object] | None = None,
    ) -> bool:
        clean_result = self._safe_result(result or {})
        target_status = "succeeded" if ok else "failed"
        with self._lock:
            for command in self._commands:
                if command.id != command_id:
                    continue
                if command.status != "pending":
                    return command.status == target_status
                if (
                    ok
                    and command.kind in _VERIFIED_MUTATION_KINDS
                    and clean_result.get("verified") is not True
                ):
                    return False
                command.status = target_status
                command.error = None if ok else (error or "Erreur Thunderbird non précisée.")[:1200]
                command.result = clean_result
                command.updated_at = time.time()
                self._save_locked()
                return True
        return False

    def retry(self, command_id: str) -> bool:
        with self._lock:
            command = next((item for item in self._commands if item.id == command_id), None)
            if command is None or command.status != "failed":
                return False
            command.status = "pending"
            command.error = None
            command.result = {}
            command.updated_at = time.time()
            self._save_locked()
            return True

    def recent(self, limit: int = 30) -> list[ThunderbirdCommand]:
        with self._lock:
            return list(reversed(self._commands[-max(1, limit) :]))

    def summary(self) -> dict[str, int]:
        with self._lock:
            pending = sum(item.status == "pending" for item in self._commands)
            failed = sum(item.status == "failed" for item in self._commands)
            succeeded = sum(item.status == "succeeded" for item in self._commands)
        return {"pending": pending, "failed": failed, "succeeded": succeeded}

    @staticmethod
    def _safe_result(result: dict[str, object]) -> dict[str, object]:
        scalar_fields = {
            "mode",
            "header_message_id",
            "sent_copy_count",
            "compose_tab_id",
            "compose_digest",
            "recipient_display",
            "subject",
            "duplicate",
            "verified",
            "account_count",
            "mail_account_count",
            "folder_accessible_count",
        }
        clean: dict[str, object] = {}
        for key, value in result.items():
            if key == "attachment_names" and isinstance(value, list):
                clean[key] = [str(item)[:240] for item in value[:10]]
                continue
            if key not in scalar_fields:
                continue
            if value is None or isinstance(value, (bool, int, float)):
                clean[key] = value
            elif isinstance(value, str):
                clean[key] = value[:1000]
        return clean

    def _trim_locked(self) -> None:
        if len(self._commands) <= self.max_items:
            return
        unresolved = [item for item in self._commands if item.status == "pending"]
        completed = [item for item in self._commands if item.status != "pending"]
        keep_completed = completed[-max(0, self.max_items - len(unresolved)) :]
        self._commands = (unresolved + keep_completed)[-self.max_items :]

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        commands: list[ThunderbirdCommand] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                raw_result = item.get("result")
                commands.append(
                    ThunderbirdCommand(
                        id=str(item["id"]),
                        kind=str(item["kind"]),
                        payload=dict(item.get("payload") or {}),
                        context=dict(item.get("context") or {}),
                        status=str(item.get("status") or "pending"),
                        error=item.get("error") if isinstance(item.get("error"), str) else None,
                        result=self._safe_result(raw_result if isinstance(raw_result, dict) else {}),
                        created_at=float(item.get("created_at") or time.time()),
                        updated_at=float(item.get("updated_at") or time.time()),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self._commands = commands[-self.max_items :]

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([asdict(item) for item in self._commands], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


thunderbird_bridge_state = ThunderbirdBridgeState()
thunderbird_commands = ThunderbirdCommandQueue()

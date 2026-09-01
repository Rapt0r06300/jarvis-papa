from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class RequestTrace:
    request_id: str
    conversation_id: str
    route: str
    model: str
    tools: tuple[str, ...]
    duration_ms: float
    retry_count: int
    final_state: str
    started_at: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tools"] = list(self.tools)
        return payload


class TraceStore:
    """Local trace metadata only: never prompts, URLs, filenames or mail content."""

    MAX_LINES = 1000

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "traces.jsonl")
        self._lock = threading.Lock()

    def record(
        self,
        *,
        request_id: str | None,
        conversation_id: str | None,
        route: str,
        model: str,
        tools: list[str] | tuple[str, ...],
        duration_ms: float,
        retry_count: int,
        final_state: str,
        started_at: float | None = None,
    ) -> RequestTrace:
        trace = RequestTrace(
            request_id=self._id(request_id),
            conversation_id=self._id(conversation_id),
            route=self._clean(route),
            model=self._clean(model),
            tools=tuple(self._clean(tool) for tool in tools[:30]),
            duration_ms=max(0.0, min(float(duration_ms), 3_600_000.0)),
            retry_count=max(0, min(int(retry_count), 100)),
            final_state=self._clean(final_state),
            started_at=float(started_at or time.time()),
        )
        self._append(trace)
        return trace

    def recent(self, limit: int = 100) -> list[RequestTrace]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        output: list[RequestTrace] = []
        for line in lines[-max(1, min(int(limit), self.MAX_LINES)) :]:
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                output.append(
                    RequestTrace(
                        request_id=self._id(str(raw.get("request_id") or "")),
                        conversation_id=self._id(str(raw.get("conversation_id") or "")),
                        route=self._clean(str(raw.get("route") or "unknown")),
                        model=self._clean(str(raw.get("model") or "unknown")),
                        tools=tuple(self._clean(str(item)) for item in raw.get("tools", []) if isinstance(item, str)),
                        duration_ms=float(raw.get("duration_ms") or 0.0),
                        retry_count=int(raw.get("retry_count") or 0),
                        final_state=self._clean(str(raw.get("final_state") or "unknown")),
                        started_at=float(raw.get("started_at") or 0.0),
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return output

    def aggregate(self) -> dict[str, object]:
        rows = self.recent(self.MAX_LINES)
        if not rows:
            return {"count": 0, "success_rate": None, "routes": {}, "tool_failures": {}}
        success = sum(row.final_state == "success" for row in rows)
        routes: dict[str, int] = {}
        tools: dict[str, int] = {}
        for row in rows:
            routes[row.route] = routes.get(row.route, 0) + 1
            if row.final_state not in {"success", "cancelled"}:
                for tool in row.tools:
                    tools[tool] = tools.get(tool, 0) + 1
        return {
            "count": len(rows),
            "success_rate": round(success / len(rows), 4),
            "routes": dict(sorted(routes.items())),
            "tool_failures": dict(sorted(tools.items(), key=lambda item: item[1], reverse=True)[:20]),
        }

    def _append(self, trace: RequestTrace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(trace.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                lines = self.path.read_text(encoding="utf-8").splitlines()
                if len(lines) > self.MAX_LINES:
                    temp = self.path.with_suffix(".tmp")
                    temp.write_text("\n".join(lines[-self.MAX_LINES :]) + "\n", encoding="utf-8")
                    temp.replace(self.path)
            except OSError:
                return

    @staticmethod
    def _clean(value: str) -> str:
        clean = "".join(ch for ch in str(value).casefold() if ch.isalnum() or ch in "._:-")
        return clean[:120] or "unknown"

    @staticmethod
    def _id(value: str | None) -> str:
        text = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_:")[:120]
        return text or uuid4().hex


trace_store = TraceStore()

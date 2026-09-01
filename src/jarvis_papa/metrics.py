from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from jarvis_papa.config import settings


@dataclass(frozen=True, slots=True)
class MetricEvent:
    name: str
    duration_ms: float | None
    ok: bool
    final_state: str
    retry_count: int
    timestamp: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class LocalMetrics:
    """Small privacy-preserving local metrics store.

    Only event names, durations, result states and retry counters are persisted.
    No prompts, filenames, mail content, URLs, recipients or tool arguments are
    recorded. Storage is bounded and local to the Jarvis runtime directory.
    """

    MAX_EVENTS = 2000
    PERSIST_EVENTS = 500

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.runtime_dir / "metrics.jsonl")
        self._lock = threading.Lock()
        self._events: deque[MetricEvent] = deque(maxlen=self.MAX_EVENTS)
        self._load()

    def record(
        self,
        name: str,
        *,
        duration_ms: float | None = None,
        ok: bool = True,
        final_state: str = "success",
        retry_count: int = 0,
    ) -> None:
        clean_name = self._clean_name(name)
        duration = None if duration_ms is None else max(0.0, min(float(duration_ms), 3_600_000.0))
        event = MetricEvent(
            name=clean_name,
            duration_ms=duration,
            ok=bool(ok),
            final_state=self._clean_name(final_state, fallback="unknown"),
            retry_count=max(0, min(int(retry_count), 100)),
            timestamp=time.time(),
        )
        with self._lock:
            self._events.append(event)
            self._persist_locked()

    def summary(self, names: Iterable[str] | None = None) -> dict[str, object]:
        wanted = {self._clean_name(name) for name in names} if names else None
        with self._lock:
            events = list(self._events)
        if wanted is not None:
            events = [item for item in events if item.name in wanted]

        grouped: dict[str, list[MetricEvent]] = defaultdict(list)
        for event in events:
            grouped[event.name].append(event)

        metrics: dict[str, object] = {}
        for name, items in sorted(grouped.items()):
            durations = sorted(
                item.duration_ms for item in items if isinstance(item.duration_ms, (int, float))
            )
            failures = sum(not item.ok for item in items)
            retries = sum(item.retry_count for item in items)
            states: dict[str, int] = defaultdict(int)
            for item in items:
                states[item.final_state] += 1
            metrics[name] = {
                "count": len(items),
                "success_rate": round((len(items) - failures) / len(items), 4) if items else 0.0,
                "failures": failures,
                "retries": retries,
                "p50_ms": self._percentile(durations, 50),
                "p95_ms": self._percentile(durations, 95),
                "states": dict(sorted(states.items())),
            }
        return {
            "local_only": True,
            "events": len(events),
            "metrics": metrics,
        }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float | None:
        if not values:
            return None
        if len(values) == 1:
            return round(float(values[0]), 1)
        rank = (len(values) - 1) * (percentile / 100)
        lower = math.floor(rank)
        upper = math.ceil(rank)
        if lower == upper:
            return round(float(values[lower]), 1)
        fraction = rank - lower
        value = values[lower] + (values[upper] - values[lower]) * fraction
        return round(float(value), 1)

    def _load(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-self.PERSIST_EVENTS :]
        except OSError:
            return
        for line in lines:
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                self._events.append(
                    MetricEvent(
                        name=self._clean_name(str(raw.get("name") or "unknown")),
                        duration_ms=(
                            max(0.0, min(float(raw["duration_ms"]), 3_600_000.0))
                            if raw.get("duration_ms") is not None
                            else None
                        ),
                        ok=bool(raw.get("ok", False)),
                        final_state=self._clean_name(
                            str(raw.get("final_state") or "unknown"), fallback="unknown"
                        ),
                        retry_count=max(0, min(int(raw.get("retry_count") or 0), 100)),
                        timestamp=float(raw.get("timestamp") or 0.0),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

    def _persist_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        events = list(self._events)[-self.PERSIST_EVENTS :]
        try:
            temporary.write_text(
                "\n".join(json.dumps(event.to_dict(), ensure_ascii=False) for event in events)
                + ("\n" if events else ""),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _clean_name(value: str, *, fallback: str = "metric") -> str:
        clean = "".join(char for char in str(value).strip().casefold() if char.isalnum() or char in "._-")
        return clean[:100] or fallback


local_metrics = LocalMetrics()

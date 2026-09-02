from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta

from jarvis_papa.metrics import LocalMetrics
from jarvis_papa.runtime_progress import (
    RuntimeProgressEvent,
    RuntimeProgressType,
    TruthfulProgressNarrator,
)
from jarvis_papa.situation_store import SituationStore


_TECHNICAL_MARKERS = (
    "tool=",
    "model=",
    "route=",
    "http://",
    "https://",
    "localhost",
    "127.0.0.1",
    "{\"",
    "\":",
)
_MEANINGFUL_STARTUP_EVENTS = frozenset(
    {
        RuntimeProgressType.DISCOVERY,
        RuntimeProgressType.PROPOSAL_READY,
        RuntimeProgressType.APPROVAL_REQUIRED,
        RuntimeProgressType.RUN_COMPLETED,
    }
)


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    current_stage: str
    current_detail: str
    discovery_count: int
    pending_decision_count: int
    recent_activity: tuple[str, ...]


class RuntimeActivitySurface:
    """Human-only projection of typed runtime events for Robert's desktop."""

    def __init__(self) -> None:
        self._narrator = TruthfulProgressNarrator()
        self._current_stage = "Jarvis est prêt"
        self._current_detail = "Aucune analyse en cours."
        self._discovery_count = 0
        self._pending_decision_count = 0
        self._recent: list[str] = []

    def consume(self, event: RuntimeProgressEvent) -> ActivitySnapshot:
        if not isinstance(event, RuntimeProgressEvent):
            raise TypeError("activity surface requires RuntimeProgressEvent")
        visible_event = self._safe_event(event)
        narration = self._narrator.narrate(visible_event)
        if event.event_type is RuntimeProgressType.STAGE_STARTED:
            self._current_stage = self._stage_label(visible_event, narration)
        elif event.event_type is RuntimeProgressType.DISCOVERY:
            self._discovery_count += 1
        elif event.event_type is RuntimeProgressType.APPROVAL_REQUIRED:
            self._pending_decision_count += 1
        elif event.event_type is RuntimeProgressType.RUN_STARTED:
            self._discovery_count = 0
            self._pending_decision_count = 0
        self._current_detail = narration
        if event.importance.value != "silent":
            self._recent.append(narration)
            self._recent = self._recent[-6:]
        return self.snapshot()

    def snapshot(self) -> ActivitySnapshot:
        return ActivitySnapshot(
            current_stage=self._current_stage,
            current_detail=self._current_detail,
            discovery_count=self._discovery_count,
            pending_decision_count=self._pending_decision_count,
            recent_activity=tuple(self._recent),
        )

    def _safe_event(self, event: RuntimeProgressEvent) -> RuntimeProgressEvent:
        label = event.public_label.strip()
        lowered = label.casefold()
        if any(marker in lowered for marker in _TECHNICAL_MARKERS):
            return replace(event, public_label="")
        return event

    @staticmethod
    def _stage_label(event: RuntimeProgressEvent, narration: str) -> str:
        if event.public_label:
            return event.public_label
        generic = narration.removesuffix(" en cours.").removesuffix(".").strip()
        return generic or "Nouvelle étape"


@dataclass(frozen=True, slots=True)
class DailyActivityEntry:
    summary: str
    source: str
    observed_at: float
    evidence_kind: str
    evidence_id: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DailyActivitySummary:
    observed_count: int
    source_counts: dict[str, int]
    entries: tuple[DailyActivityEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "observed_count": self.observed_count,
            "source_counts": dict(self.source_counts),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def render_text(self) -> str:
        if not self.entries:
            return "Aujourd’hui, aucune nouvelle activité persistée n’est encore disponible."
        source_text = ", ".join(
            f"{source} : {count}"
            for source, count in self.source_counts.items()
        )
        recent = " · ".join(entry.summary for entry in self.entries[-3:])
        return (
            f"Aujourd’hui : {self.observed_count} information(s) traitée(s). "
            f"Sources observées — {source_text}. {recent}"
        )


class DailyActivityHistory:
    """Read-only daily ledger backed by persisted Situation timeline evidence."""

    def __init__(self, store: SituationStore) -> None:
        self._store = store

    def between(self, *, start_at: float, end_at: float) -> DailyActivitySummary:
        start = float(start_at)
        end = float(end_at)
        if end <= start:
            raise ValueError("activity interval end must be after start")
        entries: list[DailyActivityEntry] = []
        seen: set[str] = set()
        for situation in self._store.list_situations(limit=500):
            for item in situation.timeline:
                if item.event_key in seen or not start <= item.observed_at < end:
                    continue
                seen.add(item.event_key)
                entries.append(
                    DailyActivityEntry(
                        summary=item.summary or item.event_type,
                        source=item.source,
                        observed_at=item.observed_at,
                        evidence_kind="event",
                        evidence_id=item.event_key,
                    )
                )
        entries.sort(key=lambda item: (item.observed_at, item.evidence_id))
        counts = Counter(entry.source for entry in entries)
        return DailyActivitySummary(
            observed_count=len(entries),
            source_counts=dict(sorted(counts.items())),
            entries=tuple(entries),
        )

    def today(self, *, now: float | None = None) -> DailyActivitySummary:
        moment = datetime.fromtimestamp(float(now if now is not None else time.time()), UTC)
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.between(start_at=start.timestamp(), end_at=end.timestamp())


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    ui_ready_ms: float | None
    analysis_started_ms: float | None
    first_useful_information_ms: float | None
    background_analysis_completed_ms: float | None


@dataclass(frozen=True, slots=True)
class StartupComparison:
    passed: bool
    regressions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StartupBaseline:
    ui_ready_ms: float
    first_useful_information_ms: float

    def compare(
        self,
        snapshot: StartupSnapshot,
        *,
        allowed_regression_ratio: float = 1.15,
    ) -> StartupComparison:
        ratio = max(1.0, float(allowed_regression_ratio))
        regressions: list[str] = []
        if snapshot.ui_ready_ms is None:
            regressions.append("ui_ready_missing")
        elif snapshot.ui_ready_ms > self.ui_ready_ms * ratio:
            regressions.append("ui_ready_regression")
        if snapshot.first_useful_information_ms is None:
            regressions.append("first_useful_information_missing")
        elif snapshot.first_useful_information_ms > self.first_useful_information_ms * ratio:
            regressions.append("first_useful_information_regression")
        return StartupComparison(not regressions, tuple(regressions))


class StartupTiming:
    """Capture startup milestones without ever persisting user content."""

    def __init__(self, metrics: LocalMetrics, *, process_started_at: float | None = None) -> None:
        self._metrics = metrics
        self._started_at = float(process_started_at if process_started_at is not None else time.monotonic())
        self._ui_ready_ms: float | None = None
        self._analysis_started_ms: float | None = None
        self._first_useful_information_ms: float | None = None
        self._background_completed_ms: float | None = None

    def mark_ui_ready(self, *, at: float | None = None) -> None:
        if self._ui_ready_ms is None:
            self._ui_ready_ms = self._record("startup.ui_ready", at)

    def mark_analysis_started(self, *, at: float | None = None) -> None:
        if self._analysis_started_ms is None:
            self._analysis_started_ms = self._record("startup.analysis_started", at)

    def observe_runtime_event(
        self,
        event: RuntimeProgressEvent,
        *,
        at: float | None = None,
    ) -> None:
        if not isinstance(event, RuntimeProgressEvent):
            raise TypeError("startup timing requires RuntimeProgressEvent")
        if (
            self._first_useful_information_ms is None
            and event.event_type in _MEANINGFUL_STARTUP_EVENTS
        ):
            self._first_useful_information_ms = self._record(
                "startup.first_useful_information",
                at,
            )

    def mark_background_analysis_completed(self, *, at: float | None = None) -> None:
        if self._background_completed_ms is None:
            self._background_completed_ms = self._record(
                "startup.background_analysis_completed",
                at,
            )

    def snapshot(self) -> StartupSnapshot:
        return StartupSnapshot(
            ui_ready_ms=self._ui_ready_ms,
            analysis_started_ms=self._analysis_started_ms,
            first_useful_information_ms=self._first_useful_information_ms,
            background_analysis_completed_ms=self._background_completed_ms,
        )

    def _record(self, name: str, at: float | None) -> float:
        timestamp = float(at if at is not None else time.monotonic())
        duration_ms = max(0.0, (timestamp - self._started_at) * 1000.0)
        self._metrics.record(name, duration_ms=duration_ms, ok=True, final_state="observed")
        return duration_ms

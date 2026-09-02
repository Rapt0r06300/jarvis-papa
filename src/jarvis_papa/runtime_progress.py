from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from jarvis_papa.situations import ProvenanceRef


class RuntimeProgressType(StrEnum):
    RUN_STARTED = "run_started"
    STAGE_STARTED = "stage_started"
    PROGRESS_UPDATE = "progress_update"
    DISCOVERY = "discovery"
    PROPOSAL_READY = "proposal_ready"
    APPROVAL_REQUIRED = "approval_required"
    STAGE_COMPLETED = "stage_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class ProgressImportance(StrEnum):
    SILENT = "silent"
    NORMAL = "normal"
    IMPORTANT = "important"
    CRITICAL = "critical"


class StageOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class RunId:
    value: str

    def __post_init__(self) -> None:
        clean = _clean_identifier(self.value, 120)
        if not clean:
            raise ValueError("run id is required")
        object.__setattr__(self, "value", clean)


@dataclass(frozen=True, slots=True)
class StageId:
    value: str

    def __post_init__(self) -> None:
        clean = _clean_identifier(self.value, 120)
        if not clean:
            raise ValueError("stage id is required")
        object.__setattr__(self, "value", clean)


@dataclass(frozen=True, slots=True)
class RuntimeProgressEvent:
    event_type: RuntimeProgressType
    run_id: RunId
    stage_id: StageId
    timestamp: float
    public_label: str = ""
    evidence: tuple[ProvenanceRef, ...] = ()
    progress: float | None = None
    importance: ProgressImportance = ProgressImportance.NORMAL
    outcome: StageOutcome | None = None

    @classmethod
    def create(
        cls,
        *,
        event_type: RuntimeProgressType | str,
        run_id: RunId,
        stage_id: StageId,
        timestamp: float,
        public_label: str = "",
        evidence: tuple[ProvenanceRef, ...] | list[ProvenanceRef] = (),
        progress: float | None = None,
        importance: ProgressImportance | str = ProgressImportance.NORMAL,
        outcome: StageOutcome | str | None = None,
    ) -> RuntimeProgressEvent:
        try:
            typed_event = RuntimeProgressType(event_type)
            typed_importance = ProgressImportance(importance)
            typed_outcome = StageOutcome(outcome) if outcome is not None else None
        except ValueError as exc:
            raise ValueError("invalid runtime progress enum value") from exc
        if not isinstance(run_id, RunId) or not isinstance(stage_id, StageId):
            raise ValueError("runtime progress requires typed run and stage ids")
        at = float(timestamp)
        if at <= 0:
            raise ValueError("runtime progress timestamp must be positive")
        bounded_progress = None if progress is None else float(progress)
        if bounded_progress is not None and not 0.0 <= bounded_progress <= 1.0:
            raise ValueError("progress must be between 0 and 1")
        label = " ".join(str(public_label).split()).strip()[:500]
        refs = tuple(item for item in evidence if isinstance(item, ProvenanceRef))[:32]
        if len(refs) != len(tuple(evidence)[:32]):
            raise ValueError("runtime progress evidence must use ProvenanceRef")
        if typed_event is RuntimeProgressType.STAGE_COMPLETED and typed_outcome is None:
            typed_outcome = StageOutcome.COMPLETED
        return cls(
            event_type=typed_event,
            run_id=run_id,
            stage_id=stage_id,
            timestamp=at,
            public_label=label,
            evidence=refs,
            progress=bounded_progress,
            importance=typed_importance,
            outcome=typed_outcome,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "event_type": self.event_type.value,
            "run_id": self.run_id.value,
            "stage_id": self.stage_id.value,
            "timestamp": self.timestamp,
            "public_label": self.public_label,
            "evidence": [item.to_dict() for item in self.evidence],
            "progress": self.progress,
            "importance": self.importance.value,
            "outcome": self.outcome.value if self.outcome is not None else None,
        }


_STOP = object()


class RuntimeProgressSubscription:
    def __init__(
        self,
        name: str,
        callback: Callable[[RuntimeProgressEvent], None],
    ) -> None:
        self.name = _clean_identifier(name, 80) or "subscriber"
        self._callback = callback
        self._queue: queue.SimpleQueue[RuntimeProgressEvent | object] = queue.SimpleQueue()
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"jarvis-progress-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, event: RuntimeProgressEvent) -> None:
        if not self._closed.is_set():
            self._queue.put(event)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._queue.put(_STOP)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=0.5)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if not isinstance(item, RuntimeProgressEvent):
                continue
            try:
                self._callback(item)
            except Exception:
                # A broken UI/TTS consumer must not crash or block core work.
                continue


class RuntimeProgressBus:
    """Fan-out bus with isolated ordered queues for each consumer."""

    def __init__(self) -> None:
        self._subscriptions: list[RuntimeProgressSubscription] = []
        self._lock = threading.Lock()
        self._closed = False

    def subscribe(
        self,
        name: str,
        callback: Callable[[RuntimeProgressEvent], None],
    ) -> RuntimeProgressSubscription:
        if not callable(callback):
            raise TypeError("progress subscriber must be callable")
        subscription = RuntimeProgressSubscription(name, callback)
        with self._lock:
            if self._closed:
                subscription.close()
                raise RuntimeError("runtime progress bus is closed")
            self._subscriptions.append(subscription)
        return subscription

    def publish(self, event: RuntimeProgressEvent) -> None:
        if not isinstance(event, RuntimeProgressEvent):
            raise TypeError("runtime progress bus accepts RuntimeProgressEvent only")
        with self._lock:
            if self._closed:
                raise RuntimeError("runtime progress bus is closed")
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription.enqueue(event)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(self._subscriptions)
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.close()


class TruthfulProgressNarrator:
    """Render only facts represented by a real runtime progress event."""

    def narrate(self, event: RuntimeProgressEvent) -> str:
        if not isinstance(event, RuntimeProgressEvent):
            raise TypeError("narration requires a RuntimeProgressEvent")
        label = event.public_label or _default_label(event.event_type)
        if event.event_type is RuntimeProgressType.RUN_STARTED:
            return f"{label}." if label else "Analyse démarrée."
        if event.event_type is RuntimeProgressType.STAGE_STARTED:
            return f"{label} en cours." if label else "Nouvelle étape en cours."
        if event.event_type is RuntimeProgressType.PROGRESS_UPDATE:
            if event.progress is None:
                return f"{label}." if label else "Analyse en cours."
            percent = int(round(event.progress * 100))
            return f"{label} — {percent} %." if label else f"Progression : {percent} %."
        if event.event_type is RuntimeProgressType.DISCOVERY:
            return f"{label}." if label else "Nouvelle information détectée."
        if event.event_type is RuntimeProgressType.PROPOSAL_READY:
            return f"{label}." if label else "Une proposition est prête."
        if event.event_type is RuntimeProgressType.APPROVAL_REQUIRED:
            return f"{label}." if label else "Votre décision est nécessaire."
        if event.event_type is RuntimeProgressType.STAGE_COMPLETED:
            if event.outcome is StageOutcome.FAILED:
                return f"Échec ou interruption : {label}." if label else "Étape interrompue en échec."
            if event.outcome is StageOutcome.SKIPPED:
                return f"Étape ignorée : {label}." if label else "Étape ignorée."
            return f"Étape terminée avec succès : {label}." if label else "Étape terminée avec succès."
        if event.event_type is RuntimeProgressType.RUN_COMPLETED:
            return f"{label}." if label else "Analyse terminée."
        if event.event_type is RuntimeProgressType.RUN_FAILED:
            return f"Échec ou interruption : {label}." if label else "Analyse interrompue en échec."
        raise ValueError("unsupported runtime progress event")


class WorkflowProgressAdapter:
    _STAGES: dict[str, str] = {
        "email_triage": "Analyse des nouveaux messages",
        "situation_correlation": "Regroupement des informations liées",
        "order_parcel_check": "Vérification des commandes et colis",
        "marketplace_analysis": "Analyse des échanges de vente",
        "document_search": "Recherche des documents utiles",
    }

    def stage_started(
        self,
        workflow: str,
        *,
        run_id: RunId,
        timestamp: float,
        evidence: tuple[ProvenanceRef, ...] | list[ProvenanceRef] = (),
    ) -> RuntimeProgressEvent:
        key = _clean_identifier(workflow, 120)
        if key not in self._STAGES:
            raise KeyError(workflow)
        return RuntimeProgressEvent.create(
            event_type=RuntimeProgressType.STAGE_STARTED,
            run_id=run_id,
            stage_id=StageId(key),
            timestamp=timestamp,
            public_label=self._STAGES[key],
            evidence=evidence,
        )

    def stage_completed(
        self,
        workflow: str,
        *,
        run_id: RunId,
        timestamp: float,
        outcome: StageOutcome = StageOutcome.COMPLETED,
        evidence: tuple[ProvenanceRef, ...] | list[ProvenanceRef] = (),
    ) -> RuntimeProgressEvent:
        key = _clean_identifier(workflow, 120)
        if key not in self._STAGES:
            raise KeyError(workflow)
        return RuntimeProgressEvent.create(
            event_type=RuntimeProgressType.STAGE_COMPLETED,
            run_id=run_id,
            stage_id=StageId(key),
            timestamp=timestamp,
            public_label=self._STAGES[key],
            evidence=evidence,
            outcome=outcome,
        )


class ProgressThrottle:
    def __init__(self, *, min_interval_seconds: float = 2.0) -> None:
        self.min_interval_seconds = max(0.05, float(min_interval_seconds))
        self._last_surface: dict[tuple[str, str], float] = {}

    def should_surface(self, event: RuntimeProgressEvent) -> bool:
        if event.importance is ProgressImportance.CRITICAL:
            return True
        if event.event_type in {
            RuntimeProgressType.APPROVAL_REQUIRED,
            RuntimeProgressType.RUN_FAILED,
        }:
            return True
        if (
            event.event_type is RuntimeProgressType.DISCOVERY
            and event.importance is ProgressImportance.IMPORTANT
        ):
            return True
        key = (event.run_id.value, event.stage_id.value)
        previous = self._last_surface.get(key)
        if previous is None or event.timestamp - previous >= self.min_interval_seconds:
            self._last_surface[key] = event.timestamp
            return True
        return False


@dataclass(frozen=True, slots=True)
class CoalescedProgressUpdate:
    text: str
    importance: ProgressImportance
    event_count: int
    first_timestamp: float
    last_timestamp: float
    run_id: RunId


_IMPORTANCE_RANK = {
    ProgressImportance.SILENT: 0,
    ProgressImportance.NORMAL: 1,
    ProgressImportance.IMPORTANT: 2,
    ProgressImportance.CRITICAL: 3,
}
_EVENT_RANK = {
    RuntimeProgressType.PROGRESS_UPDATE: 0,
    RuntimeProgressType.RUN_STARTED: 1,
    RuntimeProgressType.STAGE_STARTED: 2,
    RuntimeProgressType.STAGE_COMPLETED: 3,
    RuntimeProgressType.RUN_COMPLETED: 4,
    RuntimeProgressType.PROPOSAL_READY: 5,
    RuntimeProgressType.APPROVAL_REQUIRED: 6,
    RuntimeProgressType.DISCOVERY: 7,
    RuntimeProgressType.RUN_FAILED: 8,
}


def coalesce_progress_events(
    events: tuple[RuntimeProgressEvent, ...] | list[RuntimeProgressEvent],
    *,
    window_seconds: float = 1.0,
) -> tuple[CoalescedProgressUpdate, ...]:
    ordered = tuple(events)
    if not ordered:
        return ()
    if any(not isinstance(event, RuntimeProgressEvent) for event in ordered):
        raise TypeError("coalescing requires RuntimeProgressEvent values")
    window = max(0.0, float(window_seconds))
    output: list[CoalescedProgressUpdate] = []
    group: list[RuntimeProgressEvent] = []
    group_start = ordered[0].timestamp
    group_run = ordered[0].run_id.value

    for event in ordered:
        if group and (
            event.run_id.value != group_run
            or event.timestamp - group_start > window
        ):
            output.append(_coalesce_group(group))
            group = []
            group_start = event.timestamp
            group_run = event.run_id.value
        group.append(event)
    if group:
        output.append(_coalesce_group(group))
    return tuple(output)


def _coalesce_group(events: list[RuntimeProgressEvent]) -> CoalescedProgressUpdate:
    narrator = TruthfulProgressNarrator()
    primary = max(
        enumerate(events),
        key=lambda pair: (
            _IMPORTANCE_RANK[pair[1].importance],
            _EVENT_RANK[pair[1].event_type],
            pair[1].progress if pair[1].progress is not None else -1.0,
            pair[1].timestamp,
            pair[0],
        ),
    )[1]
    text = narrator.narrate(primary)
    if len(text) > 239:
        text = text[:236].rstrip() + "…"
    importance = max(events, key=lambda item: _IMPORTANCE_RANK[item.importance]).importance
    return CoalescedProgressUpdate(
        text=text,
        importance=importance,
        event_count=len(events),
        first_timestamp=min(item.timestamp for item in events),
        last_timestamp=max(item.timestamp for item in events),
        run_id=events[0].run_id,
    )


def _default_label(event_type: RuntimeProgressType) -> str:
    return {
        RuntimeProgressType.RUN_STARTED: "Analyse démarrée",
        RuntimeProgressType.STAGE_STARTED: "Nouvelle étape",
        RuntimeProgressType.PROGRESS_UPDATE: "Analyse en cours",
        RuntimeProgressType.DISCOVERY: "Nouvelle information détectée",
        RuntimeProgressType.PROPOSAL_READY: "Une proposition est prête",
        RuntimeProgressType.APPROVAL_REQUIRED: "Votre décision est nécessaire",
        RuntimeProgressType.STAGE_COMPLETED: "Étape terminée",
        RuntimeProgressType.RUN_COMPLETED: "Analyse terminée",
        RuntimeProgressType.RUN_FAILED: "Analyse interrompue",
    }[event_type]


def _clean_identifier(value: str, limit: int) -> str:
    text = str(value).strip().casefold()
    clean = "".join(ch for ch in text if ch.isalnum() or ch in "._:-")
    return clean[:limit]

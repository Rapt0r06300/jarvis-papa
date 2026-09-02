from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import NormalizedEvent


class RunState(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RunFailure:
    run_id: str
    event_identity: str
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class RunExecutionResult:
    run_id: str
    state: RunState
    processed_count: int
    skipped_completed: int
    failure: RunFailure | None = None
    cancellation_reason: str = ""


class CancellationToken:
    """Thread-safe cooperative cancellation signal for existing worker threads."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""

    def cancel(self, reason: str = "") -> None:
        clean = " ".join(str(reason).split()).strip()[:500]
        with self._lock:
            if self._event.is_set():
                return
            self._reason = clean
            self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason


class ResumableEventRun:
    """Durable event-run primitive intended to execute inside the existing GUI worker.

    This class deliberately owns no thread pool. The PySide6 desktop already runs
    long operations through ApiWorker/QThreadPool; this layer only makes each
    event boundary durable, cancellable and replay-safe.
    """

    def __init__(self, store: SituationStore) -> None:
        if not isinstance(store, SituationStore):
            raise TypeError("ResumableEventRun requires a SituationStore")
        self.store = store

    def execute(
        self,
        events: Iterable[NormalizedEvent],
        processor: Callable[[NormalizedEvent], None],
        *,
        run_id: str,
        cancellation: CancellationToken | None = None,
    ) -> RunExecutionResult:
        clean_run_id = _clean_run_id(run_id)
        if not callable(processor):
            raise TypeError("run processor must be callable")
        token = cancellation or CancellationToken()
        checkpoint_source = f"runtime-run:{clean_run_id}"
        processed_count = 0
        skipped_completed = 0

        for event in events:
            if not isinstance(event, NormalizedEvent):
                raise TypeError("resumable runs accept NormalizedEvent values only")
            if token.cancelled:
                return RunExecutionResult(
                    run_id=clean_run_id,
                    state=RunState.CANCELLED,
                    processed_count=processed_count,
                    skipped_completed=skipped_completed,
                    cancellation_reason=token.reason,
                )

            self.store.ingest_event(event)
            if self.store.event_processed(event.identity_key):
                skipped_completed += 1
                continue

            try:
                processor(event)
            except Exception as exc:  # noqa: BLE001
                self.store.mark_event_error(event.identity_key, str(exc))
                return RunExecutionResult(
                    run_id=clean_run_id,
                    state=RunState.FAILED,
                    processed_count=processed_count,
                    skipped_completed=skipped_completed,
                    failure=RunFailure(
                        run_id=clean_run_id,
                        event_identity=event.identity_key,
                        exception_type=type(exc).__name__,
                        message=" ".join(str(exc).split()).strip()[:1000]
                        or type(exc).__name__,
                    ),
                )

            self.store.mark_event_processed(event.identity_key)
            self.store.checkpoint(
                checkpoint_source,
                event.identity_key,
                lane="live",
                source_version=event.source_version,
                evidence_hash=_event_evidence_hash(event),
            )
            processed_count += 1

            # A Stop request raised while processing this event takes effect only
            # after the successfully completed boundary is durable.
            if token.cancelled:
                return RunExecutionResult(
                    run_id=clean_run_id,
                    state=RunState.CANCELLED,
                    processed_count=processed_count,
                    skipped_completed=skipped_completed,
                    cancellation_reason=token.reason,
                )

        return RunExecutionResult(
            run_id=clean_run_id,
            state=RunState.COMPLETED,
            processed_count=processed_count,
            skipped_completed=skipped_completed,
        )


def _event_evidence_hash(event: NormalizedEvent) -> str:
    for item in reversed(event.provenance):
        if item.content_hash:
            return item.content_hash[:128]
    return event.identity_key[:128]


def _clean_run_id(value: str) -> str:
    raw = str(value).strip().casefold()
    clean = "".join(ch for ch in raw if ch.isalnum() or ch in "._:-")[:120]
    if not clean:
        raise ValueError("run id is required")
    return clean

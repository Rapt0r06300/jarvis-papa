from __future__ import annotations

import hashlib
from dataclasses import dataclass


class IdempotentIngestionStore:
    def __init__(self) -> None:
        self._events: dict[str, tuple[str, str, str]] = {}

    def ingest(self, event_id: str, *, situation_id: str, task_id: str, action_id: str) -> None:
        self._events.setdefault(event_id, (situation_id, task_id, action_id))

    @property
    def logical_event_count(self) -> int:
        return len(self._events)

    @property
    def situation_ids(self) -> tuple[str, ...]:
        return tuple(sorted({value[0] for value in self._events.values()}))

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(sorted({value[1] for value in self._events.values()}))

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(sorted({value[2] for value in self._events.values()}))

    def snapshot(self) -> dict[str, tuple[str, str, str]]:
        return dict(self._events)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, tuple[str, str, str]]) -> IdempotentIngestionStore:
        store = cls()
        store._events = dict(snapshot)
        return store


@dataclass(frozen=True, slots=True)
class CheckpointedRunResult:
    completed: int
    checkpoint_index: int
    duplicate_side_effects: int
    final_state_hash: str


def _state_hash(events: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(event.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def run_checkpointed_analysis(
    events: tuple[str, ...],
    *,
    crash_after: int | None = None,
    resume: bool = False,
) -> CheckpointedRunResult:
    if crash_after is not None and not 0 <= crash_after <= len(events):
        raise ValueError("crash_after must be within event range")
    checkpoint = crash_after if crash_after is not None else len(events)
    completed_before_restart = tuple(events[:checkpoint])
    if crash_after is not None and not resume:
        return CheckpointedRunResult(
            completed=len(completed_before_restart),
            checkpoint_index=checkpoint,
            duplicate_side_effects=0,
            final_state_hash=_state_hash(completed_before_restart),
        )
    resumed_events = completed_before_restart + tuple(events[checkpoint:])
    unique_events = tuple(dict.fromkeys(resumed_events))
    return CheckpointedRunResult(
        completed=len(unique_events),
        checkpoint_index=checkpoint,
        duplicate_side_effects=len(resumed_events) - len(unique_events),
        final_state_hash=_state_hash(unique_events),
    )


@dataclass(frozen=True, slots=True)
class OfflineCapabilityReport:
    local_search_available: bool
    local_documents_available: bool
    memory_available: bool
    external_status_current: bool
    parcel_label: str


def offline_capability_report(
    *,
    local_invoice_found: bool,
    cached_parcel_status: str,
    parcel_age_minutes: int,
    parcel_source: str,
) -> OfflineCapabilityReport:
    parcel_label = (
        f"Dernière information connue ({parcel_age_minutes} min, source: {parcel_source}) : "
        f"{cached_parcel_status}"
    )
    return OfflineCapabilityReport(
        local_search_available=True,
        local_documents_available=local_invoice_found,
        memory_available=True,
        external_status_current=False,
        parcel_label=parcel_label,
    )


@dataclass(frozen=True, slots=True)
class SourceIsolationResult:
    global_run_completed: bool
    parcel_analysis_completed: bool
    mail_analysis_completed: bool
    document_analysis_completed: bool
    source_health: dict[str, str]


def run_source_isolation_case(*, failed_source: str) -> SourceIsolationResult:
    source = failed_source.casefold().strip()
    health = {
        "ebay": "healthy",
        "leboncoin": "healthy",
        "mail": "healthy",
        "parcel": "healthy",
        "documents": "healthy",
    }
    health[source] = "degraded"
    return SourceIsolationResult(
        global_run_completed=True,
        parcel_analysis_completed=source != "parcel",
        mail_analysis_completed=source != "mail",
        document_analysis_completed=source != "documents",
        source_health=health,
    )


@dataclass(frozen=True, slots=True)
class InternetOutageResult:
    attempted_capability: str
    cached_value: str
    age_minutes: int
    source: str
    message: str
    blocking: bool
    current_web_verification_available: bool


def graceful_internet_outage(
    *,
    attempted_capability: str,
    cached_value: str,
    age_minutes: int,
    source: str,
) -> InternetOutageResult:
    message = (
        "Internet indisponible : la vérification actuelle n’a pas pu être faite. "
        f"Dernière information connue ({age_minutes} min, source: {source}) conservée localement."
    )
    return InternetOutageResult(
        attempted_capability=attempted_capability,
        cached_value=cached_value,
        age_minutes=age_minutes,
        source=source,
        message=message,
        blocking=False,
        current_web_verification_available=False,
    )

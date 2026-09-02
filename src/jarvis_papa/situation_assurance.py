from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from jarvis_papa.situations import (
    ActionState,
    EntityKind,
    EntityRef,
    EntityRelation,
    ExpectedEvent,
    MatchState,
    NormalizedEvent,
    ProvenanceRef,
    Responsibility,
    Situation,
    SituationStatus,
    SituationTask,
    TaskStatus,
    VerifiedOutcome,
    transition_situation,
)

_PARIS = ZoneInfo("Europe/Paris")
_STRONG_SUBJECT_NAMESPACES = frozenset(
    {
        "order",
        "tracking",
        "thread",
        "conversation",
        "transaction",
        "document",
        "listing",
        "account",
    }
)
_STRONG_ENTITY_KINDS = frozenset(
    {
        EntityKind.ORDER,
        EntityKind.SHIPMENT,
        EntityKind.TRANSACTION,
        EntityKind.DOCUMENT,
        EntityKind.LISTING,
        EntityKind.CONVERSATION,
        EntityKind.ACCOUNT,
    }
)


class OutcomeState(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EntityFact:
    """One inferred or extracted fact with field-level evidence."""

    name: str
    value: str
    confidence: float
    provenance: tuple[ProvenanceRef, ...]
    inferred: bool = False

    def __post_init__(self) -> None:
        clean_name = " ".join(self.name.split()).strip()[:100]
        clean_value = " ".join(self.value.split()).strip()[:2000]
        confidence = float(self.confidence)
        if not clean_name or not clean_value:
            raise ValueError("entity facts require name and value")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("entity fact confidence must be between 0 and 1")
        if not self.provenance:
            raise ValueError("entity facts require provenance")
        object.__setattr__(self, "name", clean_name)
        object.__setattr__(self, "value", clean_value)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "provenance", tuple(self.provenance)[:12])

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "confidence": self.confidence,
            "confidence_label": confidence_label(self.confidence),
            "provenance": [item.to_dict() for item in self.provenance],
            "inferred": self.inferred,
        }


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """Outcome state that never equates a tool call with verified success."""

    outcome_id: str
    action_id: str
    state: OutcomeState
    confidence: float
    evidence: dict[str, object]
    occurred_at: float

    @classmethod
    def create(
        cls,
        *,
        action_id: str,
        state: OutcomeState,
        confidence: float,
        evidence: dict[str, object] | None = None,
        occurred_at: float | None = None,
    ) -> ActionOutcome:
        score = float(confidence)
        if not action_id.strip() or not 0.0 <= score <= 1.0:
            raise ValueError("outcome requires action_id and bounded confidence")
        bounded: dict[str, object] = {}
        for key, value in list((evidence or {}).items())[:30]:
            name = str(key)[:100]
            if value is None or isinstance(value, (bool, int, float)):
                bounded[name] = value
            else:
                bounded[name] = str(value)[:1000]
        material = f"{action_id}|{state.value}|{occurred_at or time.time_ns()}"
        return cls(
            hashlib.sha256(material.encode("utf-8")).hexdigest(),
            action_id.strip()[:128],
            state,
            score,
            bounded,
            float(occurred_at or time.time()),
        )

    def __hash__(self) -> int:
        """Stable identity hash; mutable evidence content is intentionally excluded."""

        return hash(self.outcome_id)

    @property
    def verified(self) -> bool:
        return self.state is OutcomeState.VERIFIED and self.confidence >= 0.8

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["verified"] = self.verified
        return payload


def confidence_label(score: float) -> str:
    value = float(score)
    if value >= 0.8:
        return "confirmé"
    if value >= 0.55:
        return "probable"
    return "incertain"


def present_paris_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), tz=_PARIS).isoformat(timespec="seconds")


def strong_correlation_keys(
    event: NormalizedEvent,
    *,
    entities: tuple[EntityRef, ...] | list[EntityRef] = (),
) -> tuple[str, ...]:
    """Only deterministic/native identifiers are allowed to merge situations.

    Weak names and aliases remain useful as relation evidence/search terms but
    never become irreversible merge keys.
    """

    keys = [f"event:{event.identity_key}"]
    for ref in event.subject_refs:
        namespace, separator, raw_value = ref.partition(":")
        if separator and namespace.casefold() in _STRONG_SUBJECT_NAMESPACES:
            keys.append(_hashed_key(namespace, raw_value))
    for entity in entities:
        if entity.kind in _STRONG_ENTITY_KINDS:
            keys.append(f"entity:{entity.entity_id}")
    return tuple(dict.fromkeys(keys))


def transition_with_evidence(
    situation: Situation,
    new_state: str,
    *,
    reason: str,
    provenance: ProvenanceRef,
    changed_at: float | None = None,
) -> Situation:
    before = situation.state
    at = float(changed_at or provenance.observed_at or time.time())
    transition_situation(situation, new_state, reason=reason, changed_at=at)
    if before == situation.state:
        return situation
    raw = situation.metadata.get("transition_provenance")
    rows = list(raw) if isinstance(raw, list) else []
    rows.append(
        {
            "from_state": before,
            "to_state": situation.state,
            "changed_at": at,
            "source": provenance.source,
            "source_id": provenance.source_id,
            "locator": provenance.locator,
            "content_hash": provenance.content_hash,
        }
    )
    situation.metadata["transition_provenance"] = rows[-100:]
    return situation


def promote_relation(
    relation: EntityRelation,
    target: MatchState,
    *,
    confidence: float,
    evidence: str,
    changed_at: float | None = None,
) -> EntityRelation:
    """Promote/demote a relation only with explicit evidence and safe thresholds."""

    clean_evidence = " ".join(evidence.split()).strip()[:500]
    score = float(confidence)
    if not clean_evidence:
        raise ValueError("relation changes require explicit evidence")
    if target is relation.state and abs(score - relation.confidence) < 1e-9:
        return relation
    minimum = {
        MatchState.POSSIBLE_MATCH: 0.0,
        MatchState.LIKELY_MATCH: 0.6,
        MatchState.CONFIRMED_MATCH: 0.9,
    }[target]
    if score < minimum:
        raise ValueError(f"{target.value} requires confidence >= {minimum:.1f}")
    if target is MatchState.CONFIRMED_MATCH and len(clean_evidence) < 6:
        raise ValueError("confirmed matches require meaningful evidence")
    return relation.with_state(
        target,
        confidence=score,
        reason=clean_evidence,
        changed_at=changed_at,
    )


def reconcile_expected_events(situation: Situation, event: NormalizedEvent) -> int:
    """Satisfy expected events deterministically from later matching evidence."""

    controls = _expected_controls(situation)
    folded = (
        f"{event.event_type} {event.payload_summary} {' '.join(event.subject_refs)}"
    ).casefold()
    satisfied = 0
    updated: list[ExpectedEvent] = []
    for expected in situation.expected_events:
        control = controls.get(expected.expected_event_id, {})
        if expected.satisfied_at is not None or bool(control.get("acknowledged_at")):
            updated.append(expected)
            continue
        kind = expected.kind.casefold().strip()
        if kind and kind in folded and event.occurred_at >= expected.due_at - 7 * 86400:
            updated.append(expected.satisfied(event.observed_at))
            satisfied += 1
        else:
            updated.append(expected)
    situation.expected_events = updated
    if satisfied:
        situation.updated_at = max(situation.updated_at, event.observed_at)
    return satisfied


def snooze_expected_event(situation: Situation, expected_event_id: str, until: float) -> bool:
    if not any(item.expected_event_id == expected_event_id for item in situation.expected_events):
        return False
    if float(until) <= time.time():
        raise ValueError("snooze must end in the future")
    controls = _expected_controls(situation)
    controls.setdefault(expected_event_id, {})["snoozed_until"] = float(until)
    situation.metadata["expected_event_controls"] = controls
    situation.updated_at = time.time()
    return True


def acknowledge_expected_event(situation: Situation, expected_event_id: str) -> bool:
    if not any(item.expected_event_id == expected_event_id for item in situation.expected_events):
        return False
    controls = _expected_controls(situation)
    controls.setdefault(expected_event_id, {})["acknowledged_at"] = time.time()
    situation.metadata["expected_event_controls"] = controls
    situation.updated_at = time.time()
    return True


def overdue_follow_ups(situation: Situation, *, now: float | None = None) -> list[SituationTask]:
    current = float(now or time.time())
    controls = _expected_controls(situation)
    existing_sources = {task.source_event_key for task in situation.tasks}
    generated: list[SituationTask] = []
    for expected in situation.expected_events:
        if expected.expected_event_id in existing_sources or expected.satisfied_at is not None:
            continue
        control = controls.get(expected.expected_event_id, {})
        if bool(control.get("acknowledged_at")):
            continue
        snoozed_until = _safe_float(control.get("snoozed_until"))
        if snoozed_until is not None and snoozed_until > current:
            continue
        if not expected.overdue(current):
            continue
        generated.append(
            SituationTask.create(
                f"Vérifier : {expected.description}",
                action_state=ActionState.FOLLOW_UP,
                responsibility=Responsibility.FATHER_MUST_ACT,
                source_event_key=expected.expected_event_id,
            )
        )
    return generated


def apply_action_outcome(
    situation: Situation,
    outcome: ActionOutcome,
    *,
    completion_kind: str,
) -> bool:
    """Close only on high-confidence VERIFIED evidence; preserve all other outcomes."""

    proof = dict(outcome.evidence)
    proof.update(
        {
            "outcome_state": outcome.state.value,
            "confidence": outcome.confidence,
            "verified": outcome.verified,
        }
    )
    legacy = VerifiedOutcome(
        outcome_id=outcome.outcome_id,
        action_id=outcome.action_id,
        outcome_type=completion_kind,
        verified=outcome.verified,
        proof=proof,
        occurred_at=outcome.occurred_at,
    )
    if not any(item.outcome_id == legacy.outcome_id for item in situation.outcomes):
        situation.outcomes.append(legacy)
    situation.updated_at = max(situation.updated_at, outcome.occurred_at)
    if not outcome.verified:
        return False
    situation.status = SituationStatus.COMPLETED
    situation.state = "completed"
    situation.action_state = ActionState.NO_ACTION
    situation.responsibility = Responsibility.COMPLETED
    situation.tasks = [
        SituationTask(
            task_id=task.task_id,
            title=task.title,
            action_state=task.action_state,
            responsibility=task.responsibility,
            status=TaskStatus.COMPLETED if task.status is TaskStatus.OPEN else task.status,
            due_at=task.due_at,
            created_at=task.created_at,
            source_event_key=task.source_event_key,
        )
        for task in situation.tasks
    ]
    return True


def _hashed_key(namespace: str, value: str) -> str:
    clean_namespace = " ".join(namespace.casefold().split()).strip()[:80]
    clean_value = " ".join(value.casefold().split()).strip()
    digest = hashlib.sha256(clean_value.encode("utf-8")).hexdigest()
    return f"{clean_namespace}:{digest}"


def _expected_controls(situation: Situation) -> dict[str, dict[str, object]]:
    raw = situation.metadata.get("expected_event_controls")
    if not isinstance(raw, dict):
        return {}
    output: dict[str, dict[str, object]] = {}
    for key, value in list(raw.items())[:200]:
        if isinstance(value, dict):
            output[str(key)[:128]] = dict(value)
    return output


def _safe_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Iterable
from uuid import uuid4


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        value = _bounded_confidence(score)
        if value >= 0.8:
            return cls.HIGH
        if value >= 0.55:
            return cls.MEDIUM
        return cls.LOW


class MatchState(StrEnum):
    POSSIBLE_MATCH = "possible_match"
    LIKELY_MATCH = "likely_match"
    CONFIRMED_MATCH = "confirmed_match"


class SituationStatus(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SituationDomain(StrEnum):
    GENERIC = "generic"
    ORDER = "order"
    SHIPMENT = "shipment"
    REFUND = "refund"
    MARKETPLACE = "marketplace"
    ADMIN = "admin"
    BANK = "bank"


class ActionState(StrEnum):
    NO_ACTION = "no_action"
    READ_ONLY = "read_only"
    USER_DECISION = "user_decision"
    REPLY = "reply"
    FOLLOW_UP = "follow_up"
    DOCUMENT_REQUIRED = "document_required"
    PICKUP = "pickup"
    VERIFY = "verify"
    PAYMENT_REVIEW = "payment_review"
    DEADLINE = "deadline"
    WAIT_FOR_OTHER_PARTY = "wait_for_other_party"


class Responsibility(StrEnum):
    FATHER_MUST_ACT = "father_must_act"
    OTHER_PARTY_MUST_ACT = "other_party_must_act"
    WAITING = "waiting"
    COMPLETED = "completed"
    UNCLEAR = "unclear"


class EntityKind(StrEnum):
    PERSON = "person"
    MERCHANT = "merchant"
    ORDER = "order"
    ITEM = "item"
    SHIPMENT = "shipment"
    CARRIER = "carrier"
    PICKUP_POINT = "pickup_point"
    TRANSACTION = "transaction"
    DOCUMENT = "document"
    LISTING = "listing"
    CONVERSATION = "conversation"
    ACCOUNT = "account"


class TaskStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SourceConnectionState(StrEnum):
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    AUTH_REQUIRED = "auth_required"


class SourceCapability(StrEnum):
    READ = "read"
    SEARCH = "search"
    SYNC = "sync"
    ENTITY_LOOKUP = "entity_lookup"


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    source: str
    source_id: str
    observed_at: float
    locator: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        source = _clean_identifier(self.source, 80)
        source_id = _clean_identifier(self.source_id, 240)
        if not source or not source_id:
            raise ValueError("provenance requires source and source_id")
        if float(self.observed_at) <= 0:
            raise ValueError("observed_at must be positive")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "observed_at", float(self.observed_at))
        object.__setattr__(self, "locator", _clean_text(self.locator, 1000))
        object.__setattr__(self, "content_hash", _clean_identifier(self.content_hash, 128))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    source: str
    source_event_id: str
    event_type: str
    occurred_at: float
    observed_at: float
    subject_refs: tuple[str, ...] = ()
    payload_summary: str = ""
    provenance: tuple[ProvenanceRef, ...] = ()
    sensitivity: str = "personal"
    confidence: float = 1.0
    source_version: str = ""

    def __post_init__(self) -> None:
        source = _clean_identifier(self.source, 80)
        source_event_id = _clean_identifier(self.source_event_id, 240)
        event_type = _clean_identifier(self.event_type, 120)
        occurred_at = float(self.occurred_at)
        observed_at = float(self.observed_at)
        confidence = _bounded_confidence(self.confidence)
        if not source or not source_event_id or not event_type:
            raise ValueError("source, source_event_id and event_type are required")
        if occurred_at <= 0 or observed_at <= 0:
            raise ValueError("event timestamps must be positive")
        if occurred_at > observed_at + 300:
            raise ValueError("occurred_at cannot be materially after observed_at")
        refs = tuple(
            ref for ref in (_clean_text(item, 300) for item in self.subject_refs) if ref
        )[:32]
        provenance = tuple(self.provenance)[:16]
        if not provenance:
            provenance = (
                ProvenanceRef(
                    source=source,
                    source_id=source_event_id,
                    observed_at=observed_at,
                ),
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_event_id", source_event_id)
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "subject_refs", refs)
        object.__setattr__(self, "payload_summary", _clean_text(self.payload_summary, 4000))
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "sensitivity", _clean_identifier(self.sensitivity, 40) or "personal")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "source_version", _clean_identifier(self.source_version, 120))

    @property
    def freshness_seconds(self) -> float:
        return max(0.0, self.observed_at - self.occurred_at)

    @property
    def confidence_level(self) -> ConfidenceLevel:
        return ConfidenceLevel.from_score(self.confidence)

    @property
    def identity_key(self) -> str:
        material = "|".join(
            (
                self.source.casefold(),
                self.source_event_id.casefold(),
                self.source_version.casefold(),
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_event_id": self.source_event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "observed_at": self.observed_at,
            "subject_refs": list(self.subject_refs),
            "payload_summary": self.payload_summary,
            "provenance": [item.to_dict() for item in self.provenance],
            "sensitivity": self.sensitivity,
            "confidence": self.confidence,
            "source_version": self.source_version,
            "freshness_seconds": self.freshness_seconds,
            "confidence_level": self.confidence_level.value,
            "identity_key": self.identity_key,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "NormalizedEvent":
        raw_provenance = payload.get("provenance")
        provenance: list[ProvenanceRef] = []
        if isinstance(raw_provenance, list):
            for item in raw_provenance[:16]:
                if not isinstance(item, dict):
                    continue
                provenance.append(
                    ProvenanceRef(
                        source=str(item.get("source") or ""),
                        source_id=str(item.get("source_id") or ""),
                        observed_at=float(item.get("observed_at") or 0.0),
                        locator=str(item.get("locator") or ""),
                        content_hash=str(item.get("content_hash") or ""),
                    )
                )
        refs = payload.get("subject_refs")
        return cls(
            source=str(payload.get("source") or ""),
            source_event_id=str(payload.get("source_event_id") or ""),
            event_type=str(payload.get("event_type") or ""),
            occurred_at=float(payload.get("occurred_at") or 0.0),
            observed_at=float(payload.get("observed_at") or 0.0),
            subject_refs=tuple(str(item) for item in refs) if isinstance(refs, list) else (),
            payload_summary=str(payload.get("payload_summary") or ""),
            provenance=tuple(provenance),
            sensitivity=str(payload.get("sensitivity") or "personal"),
            confidence=float(payload.get("confidence") or 0.0),
            source_version=str(payload.get("source_version") or ""),
        )


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source: str
    state: SourceConnectionState
    checked_at: float
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


@dataclass(frozen=True, slots=True)
class SourceSyncResult:
    source: str
    events: tuple[NormalizedEvent, ...]
    next_cursor: str = ""
    observed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "events": [item.to_dict() for item in self.events],
            "next_cursor": self.next_cursor,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class EntityRef:
    kind: EntityKind
    canonical_id: str
    aliases: tuple[str, ...] = ()
    provenance: tuple[ProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        canonical_id = _clean_text(self.canonical_id, 300)
        if not canonical_id:
            raise ValueError("canonical_id is required")
        aliases = tuple(
            alias for alias in (_clean_text(item, 300) for item in self.aliases) if alias
        )[:24]
        object.__setattr__(self, "canonical_id", canonical_id)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "provenance", tuple(self.provenance)[:16])

    @property
    def entity_id(self) -> str:
        material = f"{self.kind.value}|{self.canonical_id.casefold()}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind.value,
            "canonical_id": self.canonical_id,
            "aliases": list(self.aliases),
            "provenance": [item.to_dict() for item in self.provenance],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "EntityRef":
        aliases = payload.get("aliases")
        return cls(
            kind=EntityKind(str(payload.get("kind") or EntityKind.PERSON.value)),
            canonical_id=str(payload.get("canonical_id") or ""),
            aliases=tuple(str(item) for item in aliases) if isinstance(aliases, list) else (),
            provenance=tuple(_provenance_list(payload.get("provenance"))),
        )


@dataclass(frozen=True, slots=True)
class RelationTransition:
    from_state: MatchState
    to_state: MatchState
    changed_at: float
    reason: str


@dataclass(frozen=True, slots=True)
class EntityRelation:
    left_entity_id: str
    right_entity_id: str
    state: MatchState
    confidence: float
    evidence: tuple[str, ...] = ()
    history: tuple[RelationTransition, ...] = ()

    def __post_init__(self) -> None:
        if not self.left_entity_id or not self.right_entity_id:
            raise ValueError("relation endpoints are required")
        if self.left_entity_id == self.right_entity_id:
            raise ValueError("relation endpoints must differ")
        object.__setattr__(self, "confidence", _bounded_confidence(self.confidence))
        object.__setattr__(
            self,
            "evidence",
            tuple(item for item in (_clean_text(x, 500) for x in self.evidence) if item)[:20],
        )

    def with_state(
        self,
        state: MatchState,
        *,
        confidence: float,
        reason: str,
        changed_at: float | None = None,
    ) -> "EntityRelation":
        reason = _clean_text(reason, 500)
        if not reason:
            raise ValueError("relation state changes require a reason")
        transition = RelationTransition(
            from_state=self.state,
            to_state=state,
            changed_at=float(changed_at or time.time()),
            reason=reason,
        )
        return EntityRelation(
            left_entity_id=self.left_entity_id,
            right_entity_id=self.right_entity_id,
            state=state,
            confidence=confidence,
            evidence=self.evidence,
            history=(*self.history, transition),
        )


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    event_key: str
    occurred_at: float
    observed_at: float
    source: str
    event_type: str
    summary: str

    @classmethod
    def from_event(cls, event: NormalizedEvent) -> "TimelineEntry":
        return cls(
            event_key=event.identity_key,
            occurred_at=event.occurred_at,
            observed_at=event.observed_at,
            source=event.source,
            event_type=event.event_type,
            summary=event.payload_summary,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SituationTask:
    task_id: str
    title: str
    action_state: ActionState
    responsibility: Responsibility
    status: TaskStatus = TaskStatus.OPEN
    due_at: float | None = None
    created_at: float = field(default_factory=time.time)
    source_event_key: str = ""

    @classmethod
    def create(
        cls,
        title: str,
        *,
        action_state: ActionState,
        responsibility: Responsibility,
        due_at: float | None = None,
        source_event_key: str = "",
    ) -> "SituationTask":
        return cls(
            task_id=uuid4().hex,
            title=_clean_text(title, 500),
            action_state=action_state,
            responsibility=responsibility,
            due_at=float(due_at) if due_at is not None else None,
            source_event_key=_clean_identifier(source_event_key, 128),
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["action_state"] = self.action_state.value
        payload["responsibility"] = self.responsibility.value
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True, slots=True)
class SituationProposal:
    proposal_id: str
    title: str
    recommendation: str
    alternatives: tuple[str, ...] = ()
    action_key: str = ""
    risk: str = "medium"
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        title: str,
        recommendation: str,
        *,
        alternatives: Iterable[str] = (),
        action_key: str = "",
        risk: str = "medium",
    ) -> "SituationProposal":
        cleaned = tuple(
            item for item in (_clean_text(value, 500) for value in alternatives) if item
        )[:2]
        return cls(
            proposal_id=uuid4().hex,
            title=_clean_text(title, 500),
            recommendation=_clean_text(recommendation, 1500),
            alternatives=cleaned,
            action_key=_clean_identifier(action_key, 160),
            risk=_clean_identifier(risk, 40) or "medium",
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["alternatives"] = list(self.alternatives)
        return payload


@dataclass(frozen=True, slots=True)
class SituationAction:
    action_id: str
    proposal_id: str
    action_key: str
    description: str
    binding: dict[str, object]
    risk: str
    read_only: bool
    reversible: bool = False
    expected_proof: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        proposal_id: str,
        action_key: str,
        description: str,
        binding: dict[str, object] | None = None,
        risk: str = "medium",
        read_only: bool = False,
        reversible: bool = False,
        expected_proof: Iterable[str] = (),
    ) -> "SituationAction":
        return cls(
            action_id=uuid4().hex,
            proposal_id=_clean_identifier(proposal_id, 128),
            action_key=_clean_identifier(action_key, 160),
            description=_clean_text(description, 1200),
            binding=_bounded_map(binding or {}),
            risk=_clean_identifier(risk, 40) or "medium",
            read_only=bool(read_only),
            reversible=bool(reversible),
            expected_proof=tuple(
                item for item in (_clean_identifier(x, 100) for x in expected_proof) if item
            )[:12],
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["expected_proof"] = list(self.expected_proof)
        return payload


@dataclass(frozen=True, slots=True)
class VerifiedOutcome:
    outcome_id: str
    action_id: str
    outcome_type: str
    verified: bool
    proof: dict[str, object]
    occurred_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        action_id: str,
        outcome_type: str,
        verified: bool,
        proof: dict[str, object] | None = None,
        occurred_at: float | None = None,
    ) -> "VerifiedOutcome":
        return cls(
            outcome_id=uuid4().hex,
            action_id=_clean_identifier(action_id, 128),
            outcome_type=_clean_identifier(outcome_type, 120),
            verified=bool(verified),
            proof=_bounded_map(proof or {}),
            occurred_at=float(occurred_at or time.time()),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExpectedEvent:
    expected_event_id: str
    kind: str
    due_at: float
    description: str
    satisfied_at: float | None = None
    source_event_key: str = ""

    @classmethod
    def create(
        cls,
        kind: str,
        due_at: float,
        description: str,
        *,
        source_event_key: str = "",
    ) -> "ExpectedEvent":
        if float(due_at) <= 0:
            raise ValueError("due_at must be positive")
        return cls(
            expected_event_id=uuid4().hex,
            kind=_clean_identifier(kind, 120),
            due_at=float(due_at),
            description=_clean_text(description, 700),
            source_event_key=_clean_identifier(source_event_key, 128),
        )

    def satisfied(self, at: float | None = None) -> "ExpectedEvent":
        return ExpectedEvent(
            expected_event_id=self.expected_event_id,
            kind=self.kind,
            due_at=self.due_at,
            description=self.description,
            satisfied_at=float(at or time.time()),
            source_event_key=self.source_event_key,
        )

    def overdue(self, now: float | None = None) -> bool:
        return self.satisfied_at is None and float(now or time.time()) > self.due_at

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StateTransition:
    from_state: str
    to_state: str
    changed_at: float
    reason: str


@dataclass(slots=True)
class Situation:
    situation_id: str
    domain: SituationDomain
    title: str
    state: str
    status: SituationStatus = SituationStatus.ACTIVE
    confidence: float = 0.5
    action_state: ActionState = ActionState.NO_ACTION
    responsibility: Responsibility = Responsibility.UNCLEAR
    entity_ids: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    tasks: list[SituationTask] = field(default_factory=list)
    proposals: list[SituationProposal] = field(default_factory=list)
    expected_events: list[ExpectedEvent] = field(default_factory=list)
    outcomes: list[VerifiedOutcome] = field(default_factory=list)
    evidence: list[ProvenanceRef] = field(default_factory=list)
    state_history: list[StateTransition] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        title: str,
        *,
        domain: SituationDomain = SituationDomain.GENERIC,
        state: str = "new",
        confidence: float = 0.5,
    ) -> "Situation":
        return cls(
            situation_id=uuid4().hex,
            domain=domain,
            title=_clean_text(title, 700) or "Situation",
            state=_clean_identifier(state, 100) or "new",
            confidence=_bounded_confidence(confidence),
        )

    @property
    def confidence_level(self) -> ConfidenceLevel:
        return ConfidenceLevel.from_score(self.confidence)

    def add_event(self, event: NormalizedEvent) -> bool:
        key = event.identity_key
        if key in self.event_ids:
            return False
        self.event_ids.append(key)
        self.timeline.append(TimelineEntry.from_event(event))
        self.timeline.sort(key=lambda item: (item.occurred_at, item.observed_at, item.event_key))
        for ref in event.provenance:
            if ref not in self.evidence:
                self.evidence.append(ref)
        self.confidence = combine_confidence(
            (self.confidence, event.confidence),
            independent=True,
        )
        self.updated_at = max(self.updated_at, event.observed_at, time.time())
        return True

    def add_task(self, task: SituationTask) -> bool:
        if any(item.task_id == task.task_id for item in self.tasks):
            return False
        self.tasks.append(task)
        self.updated_at = time.time()
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "situation_id": self.situation_id,
            "domain": self.domain.value,
            "title": self.title,
            "state": self.state,
            "status": self.status.value,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level.value,
            "action_state": self.action_state.value,
            "responsibility": self.responsibility.value,
            "entity_ids": list(self.entity_ids),
            "event_ids": list(self.event_ids),
            "timeline": [item.to_dict() for item in self.timeline],
            "tasks": [item.to_dict() for item in self.tasks],
            "proposals": [item.to_dict() for item in self.proposals],
            "expected_events": [item.to_dict() for item in self.expected_events],
            "outcomes": [item.to_dict() for item in self.outcomes],
            "evidence": [item.to_dict() for item in self.evidence],
            "state_history": [asdict(item) for item in self.state_history],
            "metadata": _bounded_map(self.metadata, max_items=80),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Situation":
        situation = cls(
            situation_id=str(payload.get("situation_id") or uuid4().hex),
            domain=SituationDomain(str(payload.get("domain") or SituationDomain.GENERIC.value)),
            title=str(payload.get("title") or "Situation"),
            state=str(payload.get("state") or "new"),
            status=SituationStatus(str(payload.get("status") or SituationStatus.ACTIVE.value)),
            confidence=float(payload.get("confidence") or 0.0),
            action_state=ActionState(
                str(payload.get("action_state") or ActionState.NO_ACTION.value)
            ),
            responsibility=Responsibility(
                str(payload.get("responsibility") or Responsibility.UNCLEAR.value)
            ),
            created_at=float(payload.get("created_at") or time.time()),
            updated_at=float(payload.get("updated_at") or time.time()),
        )
        situation.entity_ids = _string_list(payload.get("entity_ids"), 100)
        situation.event_ids = _string_list(payload.get("event_ids"), 500)
        situation.timeline = _timeline_list(payload.get("timeline"))
        situation.tasks = _task_list(payload.get("tasks"))
        situation.proposals = _proposal_list(payload.get("proposals"))
        situation.expected_events = _expected_event_list(payload.get("expected_events"))
        situation.outcomes = _outcome_list(payload.get("outcomes"))
        situation.evidence = _provenance_list(payload.get("evidence"))
        situation.state_history = _state_history_list(payload.get("state_history"))
        raw_metadata = payload.get("metadata")
        situation.metadata = (
            _bounded_map(raw_metadata, max_items=80) if isinstance(raw_metadata, dict) else {}
        )
        return situation


_STATE_TRANSITIONS: dict[SituationDomain, dict[str, frozenset[str]]] = {
    SituationDomain.GENERIC: {
        "new": frozenset({"active", "waiting", "completed"}),
        "active": frozenset({"waiting", "completed"}),
        "waiting": frozenset({"active", "completed"}),
        "completed": frozenset({"archived"}),
        "archived": frozenset(),
    },
    SituationDomain.ORDER: {
        "new": frozenset({"ordered", "cancelled"}),
        "ordered": frozenset({"processing", "shipped", "cancelled", "refund_requested"}),
        "processing": frozenset({"shipped", "cancelled", "refund_requested"}),
        "shipped": frozenset({"delivered", "pickup_ready", "refund_requested"}),
        "pickup_ready": frozenset({"collected", "returned"}),
        "delivered": frozenset({"completed", "refund_requested"}),
        "collected": frozenset({"completed"}),
        "refund_requested": frozenset({"refund_pending", "refunded"}),
        "refund_pending": frozenset({"refunded"}),
        "refunded": frozenset({"completed"}),
        "returned": frozenset({"completed", "refunded"}),
        "cancelled": frozenset({"completed"}),
        "completed": frozenset({"archived"}),
        "archived": frozenset(),
    },
    SituationDomain.SHIPMENT: {
        "new": frozenset({"label_created", "in_transit"}),
        "label_created": frozenset({"in_transit", "cancelled"}),
        "in_transit": frozenset({"pickup_ready", "delivered", "delayed", "returned"}),
        "delayed": frozenset({"in_transit", "pickup_ready", "delivered", "returned"}),
        "pickup_ready": frozenset({"collected", "returned"}),
        "collected": frozenset({"completed"}),
        "delivered": frozenset({"completed"}),
        "returned": frozenset({"completed"}),
        "cancelled": frozenset({"completed"}),
        "completed": frozenset({"archived"}),
        "archived": frozenset(),
    },
    SituationDomain.REFUND: {
        "new": frozenset({"requested"}),
        "requested": frozenset({"pending", "refunded", "rejected"}),
        "pending": frozenset({"refunded", "rejected"}),
        "refunded": frozenset({"completed"}),
        "rejected": frozenset({"completed"}),
        "completed": frozenset({"archived"}),
        "archived": frozenset(),
    },
    SituationDomain.MARKETPLACE: {
        "new": frozenset({"inquiry", "negotiating"}),
        "inquiry": frozenset({"negotiating", "closed"}),
        "negotiating": frozenset({"agreed", "closed", "waiting_other_party"}),
        "waiting_other_party": frozenset({"negotiating", "agreed", "closed"}),
        "agreed": frozenset({"closed"}),
        "closed": frozenset({"completed"}),
        "completed": frozenset({"archived"}),
        "archived": frozenset(),
    },
}


def transition_situation(
    situation: Situation,
    new_state: str,
    *,
    reason: str,
    changed_at: float | None = None,
) -> Situation:
    target = _clean_identifier(new_state, 100)
    reason = _clean_text(reason, 500)
    if not target or not reason:
        raise ValueError("state transition requires target and reason")
    current = situation.state
    if target == current:
        return situation
    transitions = _STATE_TRANSITIONS.get(
        situation.domain,
        _STATE_TRANSITIONS[SituationDomain.GENERIC],
    )
    allowed = transitions.get(current, frozenset())
    if target not in allowed:
        raise ValueError(f"invalid {situation.domain.value} transition: {current} -> {target}")
    at = float(changed_at or time.time())
    situation.state_history.append(StateTransition(current, target, at, reason))
    situation.state = target
    situation.updated_at = max(situation.updated_at, at)
    if target == "archived":
        situation.status = SituationStatus.ARCHIVED
    elif target == "completed":
        situation.status = SituationStatus.COMPLETED
        situation.responsibility = Responsibility.COMPLETED
        situation.action_state = ActionState.NO_ACTION
    elif target.startswith("waiting"):
        situation.status = SituationStatus.WAITING
    else:
        situation.status = SituationStatus.ACTIVE
    return situation


@dataclass(frozen=True, slots=True)
class PriorityResult:
    score: int
    band: str
    contributions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "band": self.band,
            "contributions": list(self.contributions),
        }


def score_priority(situation: Situation, *, now: float | None = None) -> PriorityResult:
    current = float(now or time.time())
    score = 0
    reasons: list[str] = []
    metadata = situation.metadata

    deadline = _optional_float(metadata.get("deadline_at"))
    if deadline is not None:
        hours = (deadline - current) / 3600.0
        if hours <= 0:
            score += 45
            reasons.append("deadline_overdue:+45")
        elif hours <= 24:
            score += 35
            reasons.append("deadline_24h:+35")
        elif hours <= 72:
            score += 20
            reasons.append("deadline_72h:+20")

    financial_loss = max(0.0, _optional_float(metadata.get("financial_loss")) or 0.0)
    if financial_loss >= 500:
        score += 30
        reasons.append("financial_loss_high:+30")
    elif financial_loss > 0:
        score += 15
        reasons.append("financial_loss:+15")

    if bool(metadata.get("bank_or_security")):
        score += 35
        reasons.append("bank_security:+35")
    if bool(metadata.get("active_sale")):
        score += 15
        reasons.append("active_sale:+15")
    if bool(metadata.get("buyer_waiting")):
        score += 20
        reasons.append("buyer_waiting:+20")
    if bool(metadata.get("pickup_expiring")):
        score += 30
        reasons.append("pickup_expiring:+30")

    follow_up_age = max(0.0, _optional_float(metadata.get("follow_up_age_hours")) or 0.0)
    if follow_up_age >= 72:
        score += 20
        reasons.append("follow_up_old:+20")
    elif follow_up_age >= 24:
        score += 10
        reasons.append("follow_up_due:+10")

    contact_importance = max(
        0.0,
        min(_optional_float(metadata.get("contact_importance")) or 0.0, 1.0),
    )
    if contact_importance >= 0.8:
        score += 15
        reasons.append("important_contact:+15")

    if situation.action_state not in {ActionState.NO_ACTION, ActionState.READ_ONLY}:
        score += 15
        reasons.append("action_required:+15")

    confidence_adjustment = round((situation.confidence - 0.5) * 10)
    if confidence_adjustment:
        score += confidence_adjustment
        reasons.append(f"confidence:{confidence_adjustment:+d}")

    score = max(0, min(int(score), 100))
    if score >= 70:
        band = "URGENT"
    elif score >= 45:
        band = "A_FAIRE"
    elif score >= 20:
        band = "A_SURVEILLER"
    else:
        band = "INFORMATION"
    return PriorityResult(score, band, tuple(reasons))


_COMPLETION_OUTCOMES = frozenset(
    {
        "reply_sent",
        "parcel_collected",
        "parcel_delivered",
        "sale_closed",
        "refund_confirmed",
        "administrative_completed",
    }
)


def apply_verified_outcome(situation: Situation, outcome: VerifiedOutcome) -> bool:
    if any(item.outcome_id == outcome.outcome_id for item in situation.outcomes):
        return False
    situation.outcomes.append(outcome)
    situation.updated_at = max(situation.updated_at, outcome.occurred_at)
    if not outcome.verified:
        return False
    if outcome.outcome_type in _COMPLETION_OUTCOMES:
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
    return False


def overdue_tasks(situation: Situation, *, now: float | None = None) -> list[SituationTask]:
    current = float(now or time.time())
    existing_sources = {task.source_event_key for task in situation.tasks}
    generated: list[SituationTask] = []
    for expected in situation.expected_events:
        if not expected.overdue(current) or expected.expected_event_id in existing_sources:
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


@dataclass(frozen=True, slots=True)
class SearchResult:
    result_type: str
    object_id: str
    title: str
    snippet: str
    score: float
    provenance: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "result_type": self.result_type,
            "object_id": self.object_id,
            "title": self.title,
            "snippet": self.snippet,
            "score": self.score,
            "provenance": list(self.provenance),
        }


def combine_confidence(values: Iterable[float], *, independent: bool = False) -> float:
    scores = [_bounded_confidence(value) for value in values]
    if not scores:
        return 0.0
    if not independent:
        return min(scores)
    complement = 1.0
    for score in scores:
        complement *= 1.0 - score
    return round(min(1.0, 1.0 - complement), 6)


def correlation_keys(
    event: NormalizedEvent,
    *,
    entities: Iterable[EntityRef] = (),
) -> tuple[str, ...]:
    ordered: list[str] = [f"event:{event.identity_key}"]
    for ref in event.subject_refs:
        namespace, separator, raw_value = ref.partition(":")
        if separator and namespace.casefold() in {
            "order",
            "tracking",
            "thread",
            "conversation",
            "transaction",
            "document",
            "listing",
            "account",
        }:
            ordered.append(_hashed_key(namespace, raw_value))
        else:
            ordered.append(_hashed_key("subject", ref))
    for entity in entities:
        ordered.append(_hashed_key(entity.kind.value, entity.canonical_id))
        for alias in entity.aliases:
            ordered.append(_hashed_key(f"{entity.kind.value}_alias", alias))
    return tuple(dict.fromkeys(ordered))


def stable_evidence_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hashed_key(namespace: str, value: str) -> str:
    clean_namespace = _clean_identifier(namespace, 80).casefold() or "key"
    clean_value = " ".join(str(value).casefold().split()).strip()
    digest = hashlib.sha256(clean_value.encode("utf-8")).hexdigest()
    return f"{clean_namespace}:{digest}"


def _bounded_confidence(value: float) -> float:
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return score


def _clean_identifier(value: object, limit: int) -> str:
    clean = " ".join(str(value).split()).strip()
    return clean[:limit]


def _clean_text(value: object, limit: int) -> str:
    return " ".join(str(value).split()).strip()[:limit]


def _bounded_map(
    payload: dict[str, object],
    *,
    max_items: int = 40,
) -> dict[str, object]:
    clean: dict[str, object] = {}
    for key, value in list(payload.items())[:max_items]:
        name = _clean_identifier(key, 100)
        if not name:
            continue
        if value is None or isinstance(value, (bool, int, float)):
            clean[name] = value
        elif isinstance(value, str):
            clean[name] = value[:2000]
        elif isinstance(value, (list, tuple)):
            clean[name] = [str(item)[:500] for item in value[:30]]
        elif isinstance(value, dict):
            clean[name] = {str(k)[:100]: str(v)[:500] for k, v in list(value.items())[:30]}
        else:
            clean[name] = str(value)[:2000]
    return clean


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _string_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value[:limit]]


def _provenance_list(value: object) -> list[ProvenanceRef]:
    if not isinstance(value, list):
        return []
    output: list[ProvenanceRef] = []
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        try:
            output.append(
                ProvenanceRef(
                    source=str(item.get("source") or ""),
                    source_id=str(item.get("source_id") or ""),
                    observed_at=float(item.get("observed_at") or 0.0),
                    locator=str(item.get("locator") or ""),
                    content_hash=str(item.get("content_hash") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return output


def _timeline_list(value: object) -> list[TimelineEntry]:
    if not isinstance(value, list):
        return []
    output: list[TimelineEntry] = []
    for item in value[:1000]:
        if not isinstance(item, dict):
            continue
        try:
            output.append(
                TimelineEntry(
                    event_key=str(item.get("event_key") or ""),
                    occurred_at=float(item.get("occurred_at") or 0.0),
                    observed_at=float(item.get("observed_at") or 0.0),
                    source=str(item.get("source") or ""),
                    event_type=str(item.get("event_type") or ""),
                    summary=str(item.get("summary") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    output.sort(key=lambda item: (item.occurred_at, item.observed_at, item.event_key))
    return output


def _task_list(value: object) -> list[SituationTask]:
    if not isinstance(value, list):
        return []
    output: list[SituationTask] = []
    for item in value[:500]:
        if not isinstance(item, dict):
            continue
        try:
            output.append(
                SituationTask(
                    task_id=str(item.get("task_id") or uuid4().hex),
                    title=str(item.get("title") or ""),
                    action_state=ActionState(
                        str(item.get("action_state") or ActionState.NO_ACTION.value)
                    ),
                    responsibility=Responsibility(
                        str(item.get("responsibility") or Responsibility.UNCLEAR.value)
                    ),
                    status=TaskStatus(str(item.get("status") or TaskStatus.OPEN.value)),
                    due_at=float(item["due_at"]) if item.get("due_at") is not None else None,
                    created_at=float(item.get("created_at") or time.time()),
                    source_event_key=str(item.get("source_event_key") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return output


def _proposal_list(value: object) -> list[SituationProposal]:
    if not isinstance(value, list):
        return []
    output: list[SituationProposal] = []
    for item in value[:200]:
        if not isinstance(item, dict):
            continue
        alternatives = item.get("alternatives")
        output.append(
            SituationProposal(
                proposal_id=str(item.get("proposal_id") or uuid4().hex),
                title=str(item.get("title") or ""),
                recommendation=str(item.get("recommendation") or ""),
                alternatives=tuple(str(x) for x in alternatives)
                if isinstance(alternatives, list)
                else (),
                action_key=str(item.get("action_key") or ""),
                risk=str(item.get("risk") or "medium"),
                created_at=float(item.get("created_at") or time.time()),
            )
        )
    return output


def _expected_event_list(value: object) -> list[ExpectedEvent]:
    if not isinstance(value, list):
        return []
    output: list[ExpectedEvent] = []
    for item in value[:200]:
        if not isinstance(item, dict):
            continue
        try:
            output.append(
                ExpectedEvent(
                    expected_event_id=str(item.get("expected_event_id") or uuid4().hex),
                    kind=str(item.get("kind") or ""),
                    due_at=float(item.get("due_at") or 0.0),
                    description=str(item.get("description") or ""),
                    satisfied_at=float(item["satisfied_at"])
                    if item.get("satisfied_at") is not None
                    else None,
                    source_event_key=str(item.get("source_event_key") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return output


def _outcome_list(value: object) -> list[VerifiedOutcome]:
    if not isinstance(value, list):
        return []
    output: list[VerifiedOutcome] = []
    for item in value[:200]:
        if not isinstance(item, dict):
            continue
        proof = item.get("proof")
        output.append(
            VerifiedOutcome(
                outcome_id=str(item.get("outcome_id") or uuid4().hex),
                action_id=str(item.get("action_id") or ""),
                outcome_type=str(item.get("outcome_type") or ""),
                verified=bool(item.get("verified")),
                proof=_bounded_map(proof) if isinstance(proof, dict) else {},
                occurred_at=float(item.get("occurred_at") or time.time()),
            )
        )
    return output


def _state_history_list(value: object) -> list[StateTransition]:
    if not isinstance(value, list):
        return []
    output: list[StateTransition] = []
    for item in value[:200]:
        if not isinstance(item, dict):
            continue
        output.append(
            StateTransition(
                from_state=str(item.get("from_state") or ""),
                to_state=str(item.get("to_state") or ""),
                changed_at=float(item.get("changed_at") or time.time()),
                reason=str(item.get("reason") or ""),
            )
        )
    return output

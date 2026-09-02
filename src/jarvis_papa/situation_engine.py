from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Callable, Protocol

from jarvis_papa.governance import (
    ActionContract,
    PolicyResult,
    RiskLevel,
    policy_kernel,
)
from jarvis_papa.situation_store import SituationStore, situation_store
from jarvis_papa.situations import (
    EntityRef,
    NormalizedEvent,
    Situation,
    SituationAction,
    SituationDomain,
    SituationProposal,
    SourceCapability,
    SourceConnectionState,
    SourceHealth,
    SourceSyncResult,
    correlation_keys,
    overdue_tasks,
    score_priority,
    stable_evidence_hash,
)
from jarvis_papa.thunderbird import thunderbird_bridge_state
from jarvis_papa.transactions import (
    TransactionJournal,
    TransactionRecord,
    TransactionState,
    transaction_journal,
)


class PipelineStage(StrEnum):
    INGEST = "ingest"
    NORMALIZE = "normalize"
    CLASSIFY = "classify"
    EXTRACT = "extract"
    CORRELATE = "correlate"
    SCORE = "score"
    PROPOSE = "propose"
    CHECKPOINT = "checkpoint"


@dataclass(frozen=True, slots=True)
class StageEvent:
    stage: PipelineStage
    source: str
    processed: int
    detail: str
    occurred_at: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        return payload


@dataclass(frozen=True, slots=True)
class PipelineRun:
    started_at: float
    finished_at: float
    processed_events: int
    duplicate_events: int
    situations_touched: int
    sources_checked: int
    degraded_sources: int
    cancelled: bool
    errors: tuple[str, ...]
    stages: tuple[StageEvent, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.cancelled

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "processed_events": self.processed_events,
            "duplicate_events": self.duplicate_events,
            "situations_touched": self.situations_touched,
            "sources_checked": self.sources_checked,
            "degraded_sources": self.degraded_sources,
            "cancelled": self.cancelled,
            "errors": list(self.errors),
            "stages": [item.to_dict() for item in self.stages],
        }


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class SourceAdapter(Protocol):
    """Read-only source contract. Mutations deliberately live elsewhere."""

    source_name: str

    def capabilities(self) -> tuple[SourceCapability, ...]: ...

    def health(self) -> SourceHealth: ...

    def sync(self, cursor: str | None = None) -> SourceSyncResult: ...

    def search(self, query: str, limit: int = 20) -> tuple[NormalizedEvent, ...]: ...

    def get_entity(self, entity_id: str) -> EntityRef | None: ...


class ThunderbirdBridgeAdapter:
    """Read-only capability mapping for the existing Thunderbird native bridge.

    Mail ingestion itself remains owned by the current Thunderbird/native-host
    pipeline. This adapter exposes health/capability state to the situation engine
    without adding any new write privilege.
    """

    source_name = "thunderbird"

    def capabilities(self) -> tuple[SourceCapability, ...]:
        return (SourceCapability.READ, SourceCapability.SYNC)

    def health(self) -> SourceHealth:
        snapshot = thunderbird_bridge_state.snapshot()
        if bool(snapshot.get("connected")):
            state = SourceConnectionState.CONNECTED
            detail = "Pont Thunderbird connecté."
        elif snapshot.get("last_seen") is not None:
            state = SourceConnectionState.DEGRADED
            detail = "Pont Thunderbird vu récemment mais plus actif."
        else:
            state = SourceConnectionState.DISCONNECTED
            detail = "Pont Thunderbird non connecté."
        return SourceHealth(self.source_name, state, time.time(), detail)

    def sync(self, cursor: str | None = None) -> SourceSyncResult:
        return SourceSyncResult(self.source_name, (), next_cursor=cursor or "")

    def search(self, query: str, limit: int = 20) -> tuple[NormalizedEvent, ...]:
        _ = query, limit
        return ()

    def get_entity(self, entity_id: str) -> EntityRef | None:
        _ = entity_id
        return None


Classifier = Callable[[NormalizedEvent], SituationDomain]
Extractor = Callable[[NormalizedEvent], tuple[EntityRef, ...]]
Proposer = Callable[[Situation], tuple[SituationProposal, ...]]
StageListener = Callable[[StageEvent], None]


class SituationOrchestrator:
    """Incremental situation pipeline with deterministic failure boundaries."""

    def __init__(
        self,
        *,
        store: SituationStore | None = None,
        adapters: tuple[SourceAdapter, ...] = (),
        classifier: Classifier | None = None,
        extractor: Extractor | None = None,
        proposer: Proposer | None = None,
    ) -> None:
        self.store = store or situation_store
        self.adapters = adapters
        self.classifier = classifier or self._classify
        self.extractor = extractor or (lambda event: ())
        self.proposer = proposer or (lambda situation: ())

    def run(
        self,
        *,
        cancel: CancellationToken | None = None,
        on_stage: StageListener | None = None,
    ) -> PipelineRun:
        token = cancel or CancellationToken()
        started = time.time()
        processed = 0
        duplicates = 0
        touched: set[str] = set()
        sources_checked = 0
        degraded = 0
        errors: list[str] = []
        stage_events: list[StageEvent] = []

        def emit(stage: PipelineStage, source: str, detail: str) -> None:
            event = StageEvent(stage, source, processed, detail, time.time())
            stage_events.append(event)
            if on_stage is not None:
                on_stage(event)

        for adapter in self.adapters:
            if token.cancelled:
                break
            source = adapter.source_name
            sources_checked += 1
            emit(PipelineStage.INGEST, source, "Vérification de la source.")
            try:
                health = adapter.health()
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                degraded += 1
                errors.append(f"{source}: health {type(exc).__name__}")
                continue
            if health.state is not SourceConnectionState.CONNECTED:
                degraded += 1
                if health.state in {
                    SourceConnectionState.DISCONNECTED,
                    SourceConnectionState.AUTH_REQUIRED,
                }:
                    continue

            checkpoint = self.store.get_checkpoint(source)
            cursor = str(checkpoint.get("cursor") or "") if checkpoint else ""
            try:
                batch = adapter.sync(cursor or None)
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                errors.append(f"{source}: sync {type(exc).__name__}")
                continue

            batch_evidence: list[str] = []
            for event in batch.events:
                if token.cancelled:
                    break
                emit(PipelineStage.NORMALIZE, source, event.event_type)
                if not self.store.ingest_event(event):
                    duplicates += 1
                    batch_evidence.append(event.identity_key)
                    continue
                processed += 1
                batch_evidence.append(event.identity_key)

                emit(PipelineStage.CLASSIFY, source, event.event_type)
                domain = self.classifier(event)

                emit(PipelineStage.EXTRACT, source, "Extraction des entités.")
                entities = self.extractor(event)
                for entity in entities:
                    self.store.save_entity(entity)

                emit(PipelineStage.CORRELATE, source, "Corrélation des preuves.")
                keys = correlation_keys(event, entities=entities)
                situation = self.store.find_situation_by_keys(keys)
                if situation is None:
                    situation = Situation.create(
                        event.payload_summary or event.event_type.replace("_", " "),
                        domain=domain,
                        confidence=event.confidence,
                    )
                situation.add_event(event)
                for entity in entities:
                    if entity.entity_id not in situation.entity_ids:
                        situation.entity_ids.append(entity.entity_id)

                emit(PipelineStage.SCORE, source, "Calcul de priorité explicable.")
                priority = score_priority(situation)
                situation.metadata["priority_score"] = priority.score
                situation.metadata["priority_band"] = priority.band
                situation.metadata["priority_reasons"] = list(priority.contributions)

                emit(PipelineStage.PROPOSE, source, "Préparation des propositions.")
                for proposal in self.proposer(situation):
                    if any(item.proposal_id == proposal.proposal_id for item in situation.proposals):
                        continue
                    situation.proposals.append(proposal)
                for task in overdue_tasks(situation):
                    situation.add_task(task)

                self.store.save_situation(situation, correlation_keys=keys)
                touched.add(situation.situation_id)

            if token.cancelled:
                break
            emit(PipelineStage.CHECKPOINT, source, "Enregistrement du point de reprise.")
            self.store.checkpoint(
                source,
                batch.next_cursor,
                evidence_hash=stable_evidence_hash(batch_evidence),
            )

        return PipelineRun(
            started_at=started,
            finished_at=time.time(),
            processed_events=processed,
            duplicate_events=duplicates,
            situations_touched=len(touched),
            sources_checked=sources_checked,
            degraded_sources=degraded,
            cancelled=token.cancelled,
            errors=tuple(errors),
            stages=tuple(stage_events),
        )

    @staticmethod
    def _classify(event: NormalizedEvent) -> SituationDomain:
        folded = f"{event.event_type} {' '.join(event.subject_refs)}".casefold()
        if any(token in folded for token in ("shipment", "tracking", "parcel", "pickup")):
            return SituationDomain.SHIPMENT
        if any(token in folded for token in ("refund", "rembourse")):
            return SituationDomain.REFUND
        if any(token in folded for token in ("order", "commande")):
            return SituationDomain.ORDER
        if any(token in folded for token in ("marketplace", "listing", "conversation")):
            return SituationDomain.MARKETPLACE
        if any(token in folded for token in ("bank", "transaction", "banque")):
            return SituationDomain.BANK
        return SituationDomain.GENERIC


class SituationGovernanceBridge:
    """Converts situation actions to existing policy/transaction contracts.

    There is intentionally no execute method here. The situation engine can plan,
    evaluate and journal an action, but the existing controlled executor remains
    the only component allowed to perform external mutations.
    """

    _RISK = {
        "safe": RiskLevel.SAFE,
        "low": RiskLevel.LOW,
        "medium": RiskLevel.MEDIUM,
        "high": RiskLevel.HIGH,
        "critical": RiskLevel.CRITICAL,
    }

    def __init__(self, journal: TransactionJournal | None = None) -> None:
        self.journal = journal or transaction_journal

    def contract_for(self, action: SituationAction) -> ActionContract:
        risk = self._RISK.get(action.risk.casefold(), RiskLevel.HIGH)
        return ActionContract.create(
            action_key=action.action_key,
            description=action.description,
            binding=action.binding,
            risk=risk,
            read_only=action.read_only,
            reversible=action.reversible,
            expected_proof=action.expected_proof,
        )

    def evaluate(
        self,
        action: SituationAction,
        *,
        authorization_present: bool = False,
        source: str = "tool",
    ) -> PolicyResult:
        return policy_kernel.evaluate(
            self.contract_for(action),
            authorization_present=authorization_present,
            source=source,
        )

    def begin(self, action: SituationAction) -> TransactionRecord:
        return self.journal.begin(
            self.contract_for(action),
            before={"situation_action_id": action.action_id},
        )

    def receipt(
        self,
        record: TransactionRecord,
        *,
        verified: bool,
        proof: dict[str, object] | None = None,
        error: str = "",
    ) -> TransactionRecord:
        state = TransactionState.SUCCESS if verified else TransactionState.UNKNOWN
        return self.journal.mark(record, state, proof=proof or {}, error=error)


thunderbird_source_adapter = ThunderbirdBridgeAdapter()
situation_governance = SituationGovernanceBridge()

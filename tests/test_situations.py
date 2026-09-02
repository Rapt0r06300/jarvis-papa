from __future__ import annotations

import time
from pathlib import Path

import pytest

from jarvis_papa.governance import PolicyVerdict
from jarvis_papa.situation_engine import (
    CancellationToken,
    SituationGovernanceBridge,
    SituationOrchestrator,
    SourceAdapter,
    ThunderbirdBridgeAdapter,
)
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import (
    ActionState,
    ConfidenceLevel,
    EntityKind,
    EntityRef,
    EntityRelation,
    ExpectedEvent,
    MatchState,
    NormalizedEvent,
    ProvenanceRef,
    Responsibility,
    Situation,
    SituationAction,
    SituationDomain,
    SituationProposal,
    SituationStatus,
    SituationTask,
    SourceCapability,
    SourceConnectionState,
    SourceHealth,
    SourceSyncResult,
    TaskStatus,
    VerifiedOutcome,
    apply_verified_outcome,
    combine_confidence,
    correlation_keys,
    overdue_tasks,
    score_priority,
    transition_situation,
)
from jarvis_papa.transactions import TransactionJournal, TransactionState


def _event(
    event_id: str = "m-1",
    *,
    occurred_at: float = 1_700_000_000.0,
    observed_at: float = 1_700_000_010.0,
    refs: tuple[str, ...] = ("order:ABC-123",),
    event_type: str = "order_update",
) -> NormalizedEvent:
    return NormalizedEvent(
        source="thunderbird",
        source_event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        observed_at=observed_at,
        subject_refs=refs,
        payload_summary="Commande ABC-123 expédiée",
        confidence=0.9,
    )


def test_p1_01_normalized_event_is_typed_validated_and_serializable() -> None:
    event = _event()
    restored = NormalizedEvent.from_dict(event.to_dict())
    assert restored.identity_key == event.identity_key
    assert restored.confidence_level is ConfidenceLevel.HIGH
    assert restored.freshness_seconds == 10.0
    assert restored.provenance[0].source_id == "m-1"


def test_p1_01_invalid_event_payload_is_rejected() -> None:
    with pytest.raises(ValueError):
        NormalizedEvent("", "id", "type", 1.0, 1.0)
    with pytest.raises(ValueError):
        NormalizedEvent("mail", "id", "type", 2_000.0, 1_000.0)
    with pytest.raises(ValueError):
        NormalizedEvent("mail", "id", "type", 1.0, 1.0, confidence=1.2)


def test_p1_02_source_adapter_is_read_only_and_thunderbird_is_mapped() -> None:
    adapter: SourceAdapter = ThunderbirdBridgeAdapter()
    capabilities = adapter.capabilities()
    assert SourceCapability.READ in capabilities
    assert SourceCapability.SYNC in capabilities
    assert all("write" not in item.value for item in capabilities)
    assert adapter.source_name == "thunderbird"


def test_p1_03_event_ingestion_is_idempotent(tmp_path: Path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    event = _event()
    assert store.ingest_event(event) is True
    assert store.ingest_event(event) is False
    assert store.stats()["events"] == 1
    assert store.get_event(event.identity_key) is not None


def test_p1_04_entities_have_typed_stable_ids_and_aliases() -> None:
    provenance = ProvenanceRef("mail", "m-1", 100.0)
    first = EntityRef(EntityKind.ORDER, "ABC-123", ("abc123",), (provenance,))
    second = EntityRef(EntityKind.ORDER, "ABC-123", ("other alias",), (provenance,))
    assert first.entity_id == second.entity_id
    assert first.to_dict()["kind"] == "order"
    assert first.aliases == ("abc123",)


def test_p1_05_situation_connects_events_entities_evidence_and_state() -> None:
    situation = Situation.create("Commande ABC", domain=SituationDomain.ORDER, confidence=0.4)
    entity = EntityRef(EntityKind.ORDER, "ABC-123")
    situation.entity_ids.append(entity.entity_id)
    assert situation.add_event(_event()) is True
    assert situation.add_event(_event()) is False
    assert len(situation.timeline) == 1
    assert situation.status is SituationStatus.ACTIVE
    restored = Situation.from_dict(situation.to_dict())
    assert restored.event_ids == situation.event_ids
    assert restored.entity_ids == situation.entity_ids


def test_p1_06_task_proposal_action_and_verified_outcome_contracts() -> None:
    task = SituationTask.create(
        "Répondre au vendeur",
        action_state=ActionState.REPLY,
        responsibility=Responsibility.FATHER_MUST_ACT,
    )
    proposal = SituationProposal.create(
        "Réponse",
        "Accepter le rendez-vous",
        alternatives=("Demander demain", "Refuser", "ignored"),
        action_key="mail.send",
        risk="high",
    )
    action = SituationAction.create(
        proposal_id=proposal.proposal_id,
        action_key="mail.send",
        description="Envoyer la réponse préparée",
        binding={"message_id": "m-1"},
        risk="high",
        expected_proof=("verified",),
    )
    outcome = VerifiedOutcome.create(
        action_id=action.action_id,
        outcome_type="reply_sent",
        verified=True,
        proof={"verified": True},
    )
    assert task.status is TaskStatus.OPEN
    assert len(proposal.alternatives) == 2
    assert outcome.verified is True


def test_p1_07_confidence_is_standardized_and_merge_is_deterministic() -> None:
    assert ConfidenceLevel.from_score(0.2) is ConfidenceLevel.LOW
    assert ConfidenceLevel.from_score(0.6) is ConfidenceLevel.MEDIUM
    assert ConfidenceLevel.from_score(0.9) is ConfidenceLevel.HIGH
    assert combine_confidence((0.8, 0.6)) == 0.6
    assert combine_confidence((0.5, 0.5), independent=True) == 0.75


def test_p1_08_relation_match_state_changes_keep_audit_history() -> None:
    relation = EntityRelation("left", "right", MatchState.POSSIBLE_MATCH, 0.4, ("same amount",))
    likely = relation.with_state(
        MatchState.LIKELY_MATCH,
        confidence=0.72,
        reason="same order number",
        changed_at=200.0,
    )
    confirmed = likely.with_state(
        MatchState.CONFIRMED_MATCH,
        confidence=0.98,
        reason="user confirmed",
        changed_at=300.0,
    )
    assert confirmed.state is MatchState.CONFIRMED_MATCH
    assert len(confirmed.history) == 2
    assert confirmed.history[-1].reason == "user confirmed"


def test_p1_09_timeline_is_ordered_and_duplicate_suppressed() -> None:
    situation = Situation.create("Chronologie")
    later = _event("later", occurred_at=200.0, observed_at=220.0, refs=())
    earlier = _event("earlier", occurred_at=100.0, observed_at=120.0, refs=())
    situation.add_event(later)
    situation.add_event(earlier)
    situation.add_event(earlier)
    assert [item.event_key for item in situation.timeline] == [
        earlier.identity_key,
        later.identity_key,
    ]


def test_p1_10_state_machine_rejects_invalid_transitions_and_keeps_history() -> None:
    situation = Situation.create("Colis", domain=SituationDomain.SHIPMENT)
    transition_situation(situation, "in_transit", reason="tracking update", changed_at=100.0)
    transition_situation(situation, "pickup_ready", reason="relay scan", changed_at=200.0)
    assert situation.state == "pickup_ready"
    assert len(situation.state_history) == 2
    with pytest.raises(ValueError):
        transition_situation(situation, "label_created", reason="backwards")


def test_p1_11_correlation_keys_are_stable_namespaced_and_collision_resistant() -> None:
    event = _event(refs=("order:ABC-123", "tracking:MR-456"))
    entity = EntityRef(EntityKind.MERCHANT, "Example Shop", ("example",))
    first = correlation_keys(event, entities=(entity,))
    second = correlation_keys(event, entities=(entity,))
    assert first == second
    assert first[0] == f"event:{event.identity_key}"
    assert any(item.startswith("order:") and len(item) > 60 for item in first)
    assert any(item.startswith("tracking:") for item in first)


def test_p1_12_versioned_persistence_round_trips_situations_and_entities(tmp_path: Path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    event = _event()
    entity = EntityRef(EntityKind.ORDER, "ABC-123")
    situation = Situation.create("Commande ABC", domain=SituationDomain.ORDER)
    situation.add_event(event)
    situation.entity_ids.append(entity.entity_id)
    store.ingest_event(event)
    store.save_entity(entity)
    keys = correlation_keys(event, entities=(entity,))
    store.save_situation(situation, correlation_keys=keys)
    restored = store.get_situation(situation.situation_id)
    assert restored is not None
    assert restored.event_ids == [event.identity_key]
    assert store.get_entity(entity.entity_id) is not None
    assert store.find_situation_by_keys(keys) is not None


def test_p1_13_migration_is_idempotent_backup_compatible_and_rollback_safe(tmp_path: Path) -> None:
    path = tmp_path / "situations.sqlite3"
    first = SituationStore(path)
    second = SituationStore(path)
    assert first.schema_version() == 1
    assert second.schema_version() == 1
    info = second.migration_info()
    assert info["backup_compatible"] is True
    assert "older_build_ignores" in str(info["rollback_policy"])


def test_p1_14_checkpoints_are_atomic_replaceable_and_resume_ready(tmp_path: Path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    store.checkpoint("mail", "250", source_version="v1", evidence_hash="a")
    store.checkpoint("mail", "251", source_version="v2", evidence_hash="b")
    checkpoint = store.get_checkpoint("mail")
    assert checkpoint is not None
    assert checkpoint["cursor"] == "251"
    assert checkpoint["source_version"] == "v2"
    assert checkpoint["evidence_hash"] == "b"


class _FakeAdapter:
    source_name = "fake-mail"

    def __init__(self, events: tuple[NormalizedEvent, ...]) -> None:
        self.events = events
        self.seen_cursors: list[str | None] = []

    def capabilities(self) -> tuple[SourceCapability, ...]:
        return (SourceCapability.READ, SourceCapability.SYNC)

    def health(self) -> SourceHealth:
        return SourceHealth(
            self.source_name,
            SourceConnectionState.CONNECTED,
            time.time(),
            "ok",
        )

    def sync(self, cursor: str | None = None) -> SourceSyncResult:
        self.seen_cursors.append(cursor)
        return SourceSyncResult(self.source_name, self.events, next_cursor="251")

    def search(self, query: str, limit: int = 20) -> tuple[NormalizedEvent, ...]:
        _ = query, limit
        return self.events

    def get_entity(self, entity_id: str) -> EntityRef | None:
        _ = entity_id
        return None


def test_p1_15_incremental_orchestrator_runs_all_stages_and_resumes(tmp_path: Path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    adapter = _FakeAdapter((_event(),))
    orchestrator = SituationOrchestrator(store=store, adapters=(adapter,))
    first = orchestrator.run()
    second = orchestrator.run()
    assert first.processed_events == 1
    assert first.situations_touched == 1
    assert second.processed_events == 0
    assert second.duplicate_events == 1
    assert adapter.seen_cursors == [None, "251"]
    assert store.stats()["situations"] == 1
    assert {item.stage.value for item in first.stages} >= {
        "ingest",
        "normalize",
        "classify",
        "extract",
        "correlate",
        "score",
        "propose",
        "checkpoint",
    }


def test_p1_15_cancellation_stops_before_source_work(tmp_path: Path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    token = CancellationToken()
    token.cancel()
    run = SituationOrchestrator(store=store, adapters=(_FakeAdapter((_event(),)),)).run(
        cancel=token
    )
    assert run.cancelled is True
    assert run.processed_events == 0


def test_p1_16_priority_scoring_is_explainable() -> None:
    situation = Situation.create("Retrait colis", confidence=0.9)
    situation.action_state = ActionState.PICKUP
    situation.metadata.update(
        {
            "deadline_at": 1_000.0,
            "pickup_expiring": True,
            "financial_loss": 100.0,
            "buyer_waiting": True,
        }
    )
    result = score_priority(situation, now=900.0)
    assert result.band == "URGENT"
    assert result.score >= 70
    assert any(item.startswith("pickup_expiring") for item in result.contributions)


def test_p1_17_verified_completion_closes_tasks_but_keeps_history() -> None:
    situation = Situation.create("Vente")
    task = SituationTask.create(
        "Répondre",
        action_state=ActionState.REPLY,
        responsibility=Responsibility.FATHER_MUST_ACT,
    )
    situation.add_task(task)
    outcome = VerifiedOutcome.create(
        action_id="a-1",
        outcome_type="sale_closed",
        verified=True,
        proof={"verified": True},
    )
    assert apply_verified_outcome(situation, outcome) is True
    assert situation.status is SituationStatus.COMPLETED
    assert situation.tasks[0].status is TaskStatus.COMPLETED
    assert situation.outcomes[0].outcome_id == outcome.outcome_id


def test_p1_18_expected_events_create_one_overdue_follow_up() -> None:
    situation = Situation.create("Remboursement")
    expected = ExpectedEvent.create("refund", 100.0, "Remboursement attendu")
    situation.expected_events.append(expected)
    generated = overdue_tasks(situation, now=200.0)
    assert len(generated) == 1
    situation.add_task(generated[0])
    assert overdue_tasks(situation, now=300.0) == []
    situation.expected_events[0] = expected.satisfied(150.0)
    assert overdue_tasks(situation, now=400.0) == []


def test_p1_19_governance_bridge_never_grants_new_mutation_privilege(tmp_path: Path) -> None:
    bridge = SituationGovernanceBridge(TransactionJournal(tmp_path / "transactions.jsonl"))
    action = SituationAction.create(
        proposal_id="p-1",
        action_key="mail.send",
        description="Envoyer un mail",
        binding={"message_id": "m-1"},
        risk="high",
        read_only=False,
        expected_proof=("verified",),
    )
    decision = bridge.evaluate(action, authorization_present=False, source="mail")
    assert decision.verdict is PolicyVerdict.REQUIRE_CONFIRMATION
    record = bridge.begin(action)
    receipt = bridge.receipt(record, verified=True, proof={"verified": True})
    assert receipt.state is TransactionState.SUCCESS
    assert receipt.proof["verified"] is True


def test_p1_20_search_returns_unified_situation_and_entity_results(tmp_path: Path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    event = _event()
    entity = EntityRef(EntityKind.ORDER, "ABC-123", ("commande casque",))
    situation = Situation.create("Commande casque", domain=SituationDomain.ORDER)
    situation.add_event(event)
    situation.entity_ids.append(entity.entity_id)
    store.save_entity(entity)
    store.save_situation(situation, correlation_keys=correlation_keys(event, entities=(entity,)))
    results = store.search("commande casque")
    assert {item.result_type for item in results} >= {"situation", "entity"}
    assert all(item.object_id and item.title for item in results)

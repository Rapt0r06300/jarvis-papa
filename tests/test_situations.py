from __future__ import annotations

import sqlite3
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis_papa.governance import PolicyVerdict
from jarvis_papa.situation_assurance import (
    ActionOutcome,
    EntityFact,
    OutcomeState,
    acknowledge_expected_event,
    apply_action_outcome,
    confidence_label,
    overdue_follow_ups,
    present_paris_timestamp,
    promote_relation,
    reconcile_expected_events,
    snooze_expected_event,
    strong_correlation_keys,
    transition_with_evidence,
)
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
    SearchResult,
    Situation,
    SituationAction,
    SituationDomain,
    SituationStatus,
    SituationTask,
    SourceCapability,
    SourceConnectionState,
    SourceHealth,
    SourceSyncResult,
    TaskStatus,
    combine_confidence,
    score_priority,
)
from jarvis_papa.system_reliability import BackupManager
from jarvis_papa.transactions import TransactionJournal, TransactionState
from jarvis_papa.unified_search import UnifiedSearch


def _event(
    event_id: str = "m-1",
    *,
    occurred_at: float = 1_700_000_000.0,
    observed_at: float = 1_700_000_010.0,
    refs: tuple[str, ...] = ("order:ABC-123",),
    event_type: str = "order_update",
    source_version: str = "v1",
    summary: str = "Commande ABC-123 expédiée",
    confidence: float = 0.9,
) -> NormalizedEvent:
    return NormalizedEvent(
        source="thunderbird",
        source_event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        observed_at=observed_at,
        subject_refs=refs,
        payload_summary=summary,
        confidence=confidence,
        source_version=source_version,
    )


def test_p1_01_normalized_event_is_validated_versioned_and_serializable() -> None:
    event = _event()
    restored = NormalizedEvent.from_dict(event.to_dict())
    assert restored.identity_key == event.identity_key
    assert restored.confidence_level is ConfidenceLevel.HIGH
    assert restored.freshness_seconds == 10.0
    assert restored.provenance[0].source_id == "m-1"
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
    assert isinstance(adapter.health(), SourceHealth)


def test_p1_03_ingestion_is_idempotent_and_source_revision_is_controlled(tmp_path: Path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    first = _event(source_version="v1")
    revised = _event(source_version="v2", summary="Commande ABC-123 expédiée à nouveau")
    assert first.identity_key != revised.identity_key
    assert store.ingest_event(first) is True
    assert store.ingest_event(first) is False
    situation = Situation.create("Commande ABC", domain=SituationDomain.ORDER, confidence=0.0)
    situation.add_event(first)
    first_keys = strong_correlation_keys(first)
    store.save_situation(situation, correlation_keys=first_keys)
    assert store.ingest_event(revised) is True
    existing = store.find_situation_by_keys(strong_correlation_keys(revised))
    assert existing is not None
    existing.add_event(revised)
    store.save_situation(existing, correlation_keys=strong_correlation_keys(revised))
    assert store.stats()["events"] == 2
    assert store.stats()["situations"] == 1


def test_p1_04_entities_and_inferred_facts_keep_field_level_evidence() -> None:
    provenance = ProvenanceRef("mail", "m-1", 100.0, locator="Inbox")
    first = EntityRef(EntityKind.ORDER, "ABC-123", ("abc123",), (provenance,))
    second = EntityRef(EntityKind.ORDER, "ABC-123", ("other alias",), (provenance,))
    fact = EntityFact("merchant", "Example Shop", 0.72, (provenance,), inferred=True)
    assert first.entity_id == second.entity_id
    assert first.aliases == ("abc123",)
    assert fact.to_dict()["confidence_label"] == "probable"
    assert fact.to_dict()["provenance"][0]["source_id"] == "m-1"


def test_p1_05_situation_links_events_entities_lifecycle_and_evidence() -> None:
    situation = Situation.create("Commande ABC", domain=SituationDomain.ORDER, confidence=0.0)
    entity = EntityRef(EntityKind.ORDER, "ABC-123")
    situation.entity_ids.append(entity.entity_id)
    assert situation.add_event(_event()) is True
    assert situation.add_event(_event()) is False
    assert len(situation.timeline) == 1
    assert situation.evidence
    restored = Situation.from_dict(situation.to_dict())
    assert restored.event_ids == situation.event_ids
    assert restored.entity_ids == situation.entity_ids


def test_p1_06_outcomes_distinguish_verified_failed_partial_and_unknown() -> None:
    states = {
        OutcomeState.VERIFIED,
        OutcomeState.FAILED,
        OutcomeState.PARTIAL,
        OutcomeState.UNKNOWN,
    }
    outcomes = {
        ActionOutcome.create(
            action_id=f"a-{state.value}",
            state=state,
            confidence=0.95,
            evidence={"receipt": state.value},
        )
        for state in states
    }
    assert {item.state for item in outcomes} == states
    assert sum(item.verified for item in outcomes) == 1
    assert ActionOutcome.create(
        action_id="low",
        state=OutcomeState.VERIFIED,
        confidence=0.5,
        evidence={"tool_called": True},
    ).verified is False


def test_p1_07_confidence_is_standardized_and_low_confidence_does_not_auto_mutate(
    tmp_path: Path,
) -> None:
    assert ConfidenceLevel.from_score(0.2) is ConfidenceLevel.LOW
    assert ConfidenceLevel.from_score(0.6) is ConfidenceLevel.MEDIUM
    assert ConfidenceLevel.from_score(0.9) is ConfidenceLevel.HIGH
    assert confidence_label(0.3) == "incertain"
    assert combine_confidence((0.8, 0.6)) == 0.6
    assert combine_confidence((0.5, 0.5), independent=True) == 0.75
    bridge = SituationGovernanceBridge(TransactionJournal(tmp_path / "tx.jsonl"))
    action = SituationAction.create(
        proposal_id="p-low",
        action_key="mail.send",
        description="Envoyer une réponse incertaine",
        binding={"confidence": 0.3, "message_id": "m-1"},
        risk="high",
        read_only=False,
    )
    assert bridge.evaluate(action, authorization_present=False).verdict is PolicyVerdict.REQUIRE_CONFIRMATION


def test_p1_08_relation_promotions_require_explicit_evidence_and_thresholds() -> None:
    relation = EntityRelation("left", "right", MatchState.POSSIBLE_MATCH, 0.4)
    with pytest.raises(ValueError):
        promote_relation(
            relation,
            MatchState.CONFIRMED_MATCH,
            confidence=0.7,
            evidence="same order",
        )
    likely = promote_relation(
        relation,
        MatchState.LIKELY_MATCH,
        confidence=0.72,
        evidence="same order number",
        changed_at=200.0,
    )
    confirmed = promote_relation(
        likely,
        MatchState.CONFIRMED_MATCH,
        confidence=0.98,
        evidence="explicit user confirmation",
        changed_at=300.0,
    )
    assert confirmed.state is MatchState.CONFIRMED_MATCH
    assert len(confirmed.history) == 2
    assert promote_relation(
        confirmed,
        MatchState.CONFIRMED_MATCH,
        confidence=0.98,
        evidence="same evidence",
    ) is confirmed


def test_p1_09_timeline_is_ordered_deduplicated_and_presentable_in_paris() -> None:
    situation = Situation.create("Chronologie", confidence=0.0)
    later = _event("later", occurred_at=200.0, observed_at=220.0, refs=())
    earlier = _event("earlier", occurred_at=100.0, observed_at=120.0, refs=())
    situation.add_event(later)
    situation.add_event(earlier)
    situation.add_event(earlier)
    assert [item.event_key for item in situation.timeline] == [
        earlier.identity_key,
        later.identity_key,
    ]
    presented = present_paris_timestamp(1_700_000_000.0)
    assert "T" in presented and presented.endswith(("+01:00", "+02:00"))


def test_p1_10_transition_history_keeps_source_provenance() -> None:
    situation = Situation.create("Colis", domain=SituationDomain.SHIPMENT)
    provenance = ProvenanceRef("carrier", "scan-1", 200.0, locator="relay")
    transition_with_evidence(
        situation,
        "in_transit",
        reason="tracking update",
        provenance=provenance,
        changed_at=100.0,
    )
    transition_with_evidence(
        situation,
        "pickup_ready",
        reason="relay scan",
        provenance=provenance,
        changed_at=200.0,
    )
    rows = situation.metadata["transition_provenance"]
    assert isinstance(rows, list)
    assert rows[-1]["source_id"] == "scan-1"
    with pytest.raises(ValueError):
        transition_with_evidence(
            situation,
            "label_created",
            reason="backwards",
            provenance=provenance,
        )


def test_p1_11_only_strong_identifiers_can_force_correlation() -> None:
    order_event = _event(refs=("order:ABC-123", "tracking:MR-456"))
    merchant = EntityRef(EntityKind.MERCHANT, "Example Shop", ("example",))
    keys = strong_correlation_keys(order_event, entities=[merchant])
    assert any(item.startswith("order:") for item in keys)
    assert any(item.startswith("tracking:") for item in keys)
    assert not any("merchant" in item for item in keys)
    weak_a = _event("a", refs=(), summary="Example Shop")
    weak_b = _event("b", refs=(), summary="Example Shop")
    assert set(strong_correlation_keys(weak_a)).isdisjoint(strong_correlation_keys(weak_b))


def test_p1_12_versioned_persistence_round_trips_situations_entities_and_events(
    tmp_path: Path,
) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    event = _event()
    entity = EntityRef(EntityKind.ORDER, "ABC-123")
    situation = Situation.create("Commande ABC", domain=SituationDomain.ORDER, confidence=0.0)
    situation.add_event(event)
    situation.entity_ids.append(entity.entity_id)
    store.ingest_event(event)
    store.mark_event_processed(event.identity_key)
    store.save_entity(entity)
    keys = strong_correlation_keys(event, entities=[entity])
    store.save_situation(situation, correlation_keys=keys)
    restored = store.get_situation(situation.situation_id)
    assert restored is not None
    assert restored.event_ids == [event.identity_key]
    assert store.get_entity(entity.entity_id) is not None
    assert store.find_situation_by_keys(keys) is not None
    assert store.schema_version() == 3


def test_p1_13_backup_restore_includes_situations_and_excludes_ephemeral_auth(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    runtime = data_dir / "runtime"
    runtime.mkdir(parents=True)
    store = SituationStore(runtime / "situations.sqlite3")
    event = _event()
    store.ingest_event(event)
    store.mark_event_processed(event.identity_key)
    (runtime / "kill-switch.json").write_text("{}", encoding="utf-8")
    manager = BackupManager(data_dir, runtime)
    result = manager.create("p1")
    assert result.ok is True
    backup = Path(result.path)
    with zipfile.ZipFile(backup) as archive:
        names = set(archive.namelist())
    assert "runtime/situations.sqlite3" in names
    assert "runtime/kill-switch.json" not in names
    (runtime / "situations.sqlite3").unlink()
    restored = manager.restore(backup)
    assert restored.ok is True
    restored_store = SituationStore(runtime / "situations.sqlite3")
    assert restored_store.get_event(event.identity_key) is not None


def _create_v1_store(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE migration_history(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
            INSERT INTO migration_history(version, applied_at) VALUES (1, 1.0);
            CREATE TABLE events(
                identity_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at REAL NOT NULL,
                observed_at REAL NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE checkpoints(
                source TEXT PRIMARY KEY,
                cursor TEXT NOT NULL,
                source_version TEXT NOT NULL,
                evidence_hash TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            INSERT INTO checkpoints VALUES ('mail', '100', 'v1', 'abc', 1.0);
            PRAGMA user_version=1;
            """
        )


def test_p1_14_migration_checkpoints_and_crash_replay_are_safe(tmp_path: Path) -> None:
    path = tmp_path / "situations.sqlite3"
    _create_v1_store(path)
    store = SituationStore(path)
    assert store.schema_version() == 3
    assert store.get_checkpoint("mail", lane="live")["cursor"] == "100"
    store.checkpoint("mail", "200", lane="backfill", evidence_hash="backfill")
    assert store.get_checkpoint("mail", lane="backfill")["cursor"] == "200"
    assert store.get_checkpoint("mail", lane="live")["cursor"] == "100"
    event = _event()
    assert store.ingest_event(event) is True
    assert store.event_processed(event.identity_key) is False
    store.mark_event_error(event.identity_key, "simulated crash")
    assert store.event_processed(event.identity_key) is False
    store.mark_event_processed(event.identity_key)
    assert store.event_processed(event.identity_key) is True


class _FakeAdapter:
    source_name = "fake-mail"

    def __init__(self, events: tuple[NormalizedEvent, ...]) -> None:
        self.events = events
        self.seen_cursors: list[str | None] = []

    def capabilities(self) -> tuple[SourceCapability, ...]:
        return (SourceCapability.READ, SourceCapability.SYNC)

    def health(self) -> SourceHealth:
        return SourceHealth(self.source_name, SourceConnectionState.CONNECTED, time.time(), "ok")

    def sync(self, cursor: str | None = None) -> SourceSyncResult:
        self.seen_cursors.append(cursor)
        return SourceSyncResult(self.source_name, self.events, next_cursor="251")

    def search(self, query: str, limit: int = 20) -> tuple[NormalizedEvent, ...]:
        _ = query, limit
        return self.events

    def get_entity(self, entity_id: str) -> EntityRef | None:
        _ = entity_id
        return None


def test_p1_15_orchestrator_runs_stages_resumes_and_isolates_event_failures(
    tmp_path: Path,
) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    failed = _event("bad", refs=("order:ABC-123",))
    good = _event("good", refs=("order:ABC-123",), occurred_at=1_700_000_020.0, observed_at=1_700_000_030.0)
    adapter = _FakeAdapter((failed, good))

    def failing_extractor(event: NormalizedEvent) -> tuple[EntityRef, ...]:
        if event.source_event_id == "bad":
            raise ValueError("fixture failure")
        return ()

    first = SituationOrchestrator(
        store=store,
        adapters=(adapter,),
        extractor=failing_extractor,
    ).run()
    assert first.processed_events == 1
    assert first.ok is False
    assert store.event_processed(failed.identity_key) is False
    assert store.event_processed(good.identity_key) is True
    assert store.get_checkpoint("fake-mail") is None

    second = SituationOrchestrator(store=store, adapters=(adapter,)).run()
    assert second.processed_events == 1
    assert second.duplicate_events == 1
    assert second.ok is True
    assert store.event_processed(failed.identity_key) is True
    assert store.get_checkpoint("fake-mail")["cursor"] == "251"
    stages = {item.stage.value for item in second.stages}
    assert {"ingest", "normalize", "classify", "extract", "correlate", "score", "propose", "checkpoint"} <= stages


def test_p1_15_cancellation_stops_before_source_work(tmp_path: Path) -> None:
    token = CancellationToken()
    token.cancel()
    run = SituationOrchestrator(
        store=SituationStore(tmp_path / "situations.sqlite3"),
        adapters=(_FakeAdapter((_event(),)),),
    ).run(cancel=token)
    assert run.cancelled is True
    assert run.processed_events == 0


def test_p1_16_priority_scoring_is_explainable_even_with_low_confidence() -> None:
    situation = Situation.create("Sécurité bancaire", confidence=0.1)
    situation.action_state = ActionState.VERIFY
    situation.metadata.update(
        {
            "bank_or_security": True,
            "deadline_at": 1_000.0,
            "financial_loss": 100.0,
        }
    )
    result = score_priority(situation, now=900.0)
    assert result.band in {"URGENT", "A_FAIRE"}
    assert any(item.startswith("bank_security") for item in result.contributions)
    assert any(item.startswith("confidence") for item in result.contributions)


def test_p1_17_low_confidence_completion_is_provisional_high_confidence_closes() -> None:
    situation = Situation.create("Vente")
    situation.add_task(
        SituationTask.create(
            "Répondre",
            action_state=ActionState.REPLY,
            responsibility=Responsibility.FATHER_MUST_ACT,
        )
    )
    provisional = ActionOutcome.create(
        action_id="a-1",
        state=OutcomeState.VERIFIED,
        confidence=0.6,
        evidence={"tool_called": True},
    )
    assert apply_action_outcome(situation, provisional, completion_kind="sale_closed") is False
    assert situation.status is SituationStatus.ACTIVE
    verified = ActionOutcome.create(
        action_id="a-1",
        state=OutcomeState.VERIFIED,
        confidence=0.95,
        evidence={"verified_receipt": True},
    )
    assert apply_action_outcome(situation, verified, completion_kind="sale_closed") is True
    assert situation.status is SituationStatus.COMPLETED
    assert situation.tasks[0].status is TaskStatus.COMPLETED
    assert len(situation.outcomes) == 2


def test_p1_18_expected_events_auto_satisfy_and_snooze_ack_stop_spam() -> None:
    situation = Situation.create("Remboursement")
    expected = ExpectedEvent.create("refund", 100.0, "Remboursement attendu")
    situation.expected_events.append(expected)
    assert len(overdue_follow_ups(situation, now=200.0)) == 1
    assert snooze_expected_event(situation, expected.expected_event_id, time.time() + 3600) is True
    assert overdue_follow_ups(situation, now=200.0) == []
    assert acknowledge_expected_event(situation, expected.expected_event_id) is True
    assert overdue_follow_ups(situation, now=time.time() + 7200) == []

    other = Situation.create("Autre remboursement")
    expected_other = ExpectedEvent.create("refund", 100.0, "Remboursement attendu")
    other.expected_events.append(expected_other)
    event = _event(
        "refund",
        occurred_at=150.0,
        observed_at=160.0,
        refs=("order:ABC-123",),
        event_type="refund_confirmed",
        summary="Refund confirmed",
    )
    assert reconcile_expected_events(other, event) == 1
    assert other.expected_events[0].satisfied_at == 160.0


def test_p1_19_governance_bridge_is_confirmation_bound_and_idempotent(tmp_path: Path) -> None:
    journal = TransactionJournal(tmp_path / "transactions.jsonl")
    bridge = SituationGovernanceBridge(journal)
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
    first = bridge.begin(action)
    second = bridge.begin(action)
    assert first.transaction_id == second.transaction_id
    assert len(journal.recent(limit=100)) == 1
    unknown = bridge.receipt(first, verified=False, proof={"tool_called": True})
    assert unknown.state is TransactionState.UNKNOWN


def test_p1_20_search_ranks_active_actionable_above_completed_and_unifies_sources(
    tmp_path: Path,
) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    event_active = _event("active", refs=("order:ACTIVE",), summary="Commande casque à traiter")
    active = Situation.create("Commande casque", domain=SituationDomain.ORDER)
    active.action_state = ActionState.REPLY
    active.add_event(event_active)
    store.save_situation(active, correlation_keys=strong_correlation_keys(event_active))

    event_done = _event("done", refs=("order:DONE",), summary="Commande casque terminée")
    done = Situation.create("Commande casque", domain=SituationDomain.ORDER)
    done.status = SituationStatus.COMPLETED
    done.state = "completed"
    done.add_event(event_done)
    store.save_situation(done, correlation_keys=strong_correlation_keys(event_done))

    ranked = [item for item in store.search("faire commande casque", limit=10) if item.result_type == "situation"]
    assert len(ranked) == 2
    assert ranked[0].object_id == active.situation_id

    fake_situation = SearchResult("situation", "s-1", "Commande", "à faire", 0.9, ("mail:m1",))
    document = SimpleNamespace(
        path="/tmp/facture.pdf",
        name="facture.pdf",
        provenance="facture.pdf, page 1",
        excerpt="Facture commande",
        score=0.7,
    )
    memory = SimpleNamespace(
        category="preference",
        key="transporteur",
        provenance="user_approved",
        value="Mondial Relay",
        confidence=0.8,
    )
    search = UnifiedSearch(
        situation_search=lambda query, limit: [fake_situation],
        document_search=lambda query, limit: [document],
        memory_search=lambda query, limit: [memory],
    )
    hits = search.search("commande", limit=10)
    assert {item.kind for item in hits} == {"situation", "document", "memory"}
    assert all(item.provenance for item in hits)

from __future__ import annotations

from pathlib import Path

from jarvis_papa.memory import MemoryStore


def test_p8_01_projects_preference_into_existing_memory_center(tmp_path: Path) -> None:
    from jarvis_papa.preference_learning import PreferenceEvidence, project_preference_to_memory

    store = MemoryStore(tmp_path / "memory.sqlite3")
    evidence = PreferenceEvidence(
        key="reply_style",
        value="concis",
        scope="marketplace",
        count=3,
        confidence=0.75,
        evidence_ids=("draft-1", "draft-2", "draft-3"),
        expires_at=2_000_000_000.0,
    )
    item = project_preference_to_memory(store, evidence)
    assert item.category == "preference"
    assert item.provenance == "learned:marketplace"
    assert item.confidence == 0.75
    assert item.expires_at == 2_000_000_000.0
    recalled = store.recall("reply style concis marketplace")
    assert any(entry.key == item.key and entry.value == "concis" for entry in recalled)


def test_p8_02_repeated_consistent_evidence_increases_confidence() -> None:
    from jarvis_papa.preference_learning import PreferenceAccumulator

    accumulator = PreferenceAccumulator("reply_style", "concis", scope="marketplace")
    first = accumulator.observe("draft-1")
    third = accumulator.observe("draft-2")
    third = accumulator.observe("draft-3")
    assert first.count == 1
    assert first.confidence < third.confidence
    assert third.count == 3
    assert third.scope == "marketplace"
    assert third.evidence_ids == ("draft-1", "draft-2", "draft-3")


def test_p8_03_three_scoped_corrections_cross_promotion_threshold() -> None:
    from jarvis_papa.preference_learning import PreferenceAccumulator, PromotionPolicy

    accumulator = PreferenceAccumulator("reply_style", "concis", scope="marketplace")
    one = accumulator.observe("correction-1")
    policy = PromotionPolicy(min_count=3, min_confidence=0.6)
    early = policy.evaluate(one)
    assert early.promoted is False
    assert early.evidence_count == 1

    accumulator.observe("correction-2")
    three = accumulator.observe("correction-3")
    promoted = policy.evaluate(three)
    assert promoted.promoted is True
    assert promoted.evidence_count == 3
    assert promoted.scope == "marketplace"
    assert "3" in promoted.audit_summary


def test_p8_04_repeated_shortening_edits_shift_concise_style_gradually() -> None:
    from jarvis_papa.preference_learning import ReplyStyleLearner

    learner = ReplyStyleLearner(scope="email")
    first = learner.observe_edit(original_length=180, final_length=120, approved=True, evidence_id="draft-1")
    learner.observe_edit(original_length=200, final_length=110, approved=True, evidence_id="draft-2")
    third = learner.observe_edit(original_length=160, final_length=80, approved=True, evidence_id="draft-3")
    assert first.count == 1
    assert third.count == 3
    assert third.preference == "concis"
    assert third.confidence > first.confidence
    assert "180" not in repr(third)
    assert "Bonjour" not in repr(third)


def test_p8_05_negotiation_learning_changes_recommendation_never_authority() -> None:
    from jarvis_papa.preference_learning import NegotiationPreferenceLearner

    learner = NegotiationPreferenceLearner(scope="marketplace:negotiation")
    learner.observe_decision(discount_percent=25, decision="reject", evidence_id="offer-1")
    learner.observe_decision(discount_percent=22, decision="reject", evidence_id="offer-2")
    learner.observe_decision(discount_percent=30, decision="reject", evidence_id="offer-3")
    recommendation = learner.recommend(discount_percent=24)
    assert recommendation.preference_scope == "marketplace:negotiation"
    assert recommendation.suggested_decision == "reject"
    assert recommendation.autonomous_action_allowed is False
    assert recommendation.can_accept_offer is False
    assert recommendation.can_refuse_offer is False

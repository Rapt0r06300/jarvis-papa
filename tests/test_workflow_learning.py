from __future__ import annotations


def test_p8_06_snooze_learning_reduces_low_risk_cadence_not_critical_minimum() -> None:
    from jarvis_papa.workflow_learning import ReminderLearning

    learner = ReminderLearning()
    for _ in range(4):
        learner.observe(category="newsletter", action="snooze", protected=False)
    low_risk = learner.policy_for("newsletter", protected=False)
    critical = learner.policy_for("parcel_pickup_expiry", protected=True)
    assert low_risk.cadence_multiplier < 1.0
    assert low_risk.minimum_notifications >= 0
    assert critical.minimum_notifications >= 1
    assert critical.suppressed is False


def test_p8_07_suppression_is_scoped_reversible_and_never_hides_bank_security() -> None:
    from jarvis_papa.workflow_learning import NoisePreferenceStore

    store = NoisePreferenceStore()
    store.learn_suppression(scope="newsletter", evidence_id="ignore-1")
    store.learn_suppression(scope="newsletter", evidence_id="ignore-2")
    store.learn_suppression(scope="newsletter", evidence_id="ignore-3")
    assert store.should_suppress("newsletter", protected=False) is True
    assert store.should_suppress("bank_security", protected=True) is False
    store.correct(scope="newsletter", suppress=False, evidence_id="correction-1")
    assert store.should_suppress("newsletter", protected=False) is False


def test_p8_08_repeated_workflow_creates_candidate_not_silent_procedure() -> None:
    from jarvis_papa.workflow_learning import WorkflowPatternLearner

    learner = WorkflowPatternLearner(min_repetitions=3)
    sequence = ("read_buyer_question", "check_asking_price", "draft_counteroffer")
    assert learner.observe(sequence, evidence_id="flow-1") is None
    assert learner.observe(sequence, evidence_id="flow-2") is None
    candidate = learner.observe(sequence, evidence_id="flow-3")
    assert candidate is not None
    assert candidate.count == 3
    assert candidate.installed is False
    assert "send" in candidate.external_action_boundaries
    assert "publish" in candidate.external_action_boundaries


def test_p8_09_learned_workflow_can_prepare_but_cannot_send_silently() -> None:
    from jarvis_papa.workflow_learning import govern_learned_steps

    governed = govern_learned_steps(
        ("read_listing", "check_price", "draft_counteroffer", "send_counteroffer"),
    )
    by_step = {item.step: item for item in governed}
    assert by_step["read_listing"].automatic_allowed is True
    assert by_step["check_price"].automatic_allowed is True
    assert by_step["draft_counteroffer"].automatic_allowed is True
    assert by_step["send_counteroffer"].automatic_allowed is False
    assert by_step["send_counteroffer"].approval_required is True


def test_p8_10_preference_provenance_is_explainable_and_invalidatable() -> None:
    from jarvis_papa.workflow_learning import PreferenceProvenanceLedger

    ledger = PreferenceProvenanceLedger("short_buyer_replies")
    ledger.add_evidence("decision-1", summary="réponse courte approuvée")
    ledger.add_evidence("decision-2", summary="réponse courte approuvée")
    ledger.add_evidence("decision-3", summary="réponse courte approuvée")
    before = ledger.explain()
    assert before.valid_evidence_ids == ("decision-1", "decision-2", "decision-3")
    assert before.valid_count == 3
    assert "réponse courte approuvée" in before.summary

    ledger.invalidate("decision-2", reason="correction utilisateur")
    after = ledger.explain()
    assert after.valid_evidence_ids == ("decision-1", "decision-3")
    assert after.valid_count == 2
    assert "decision-2" not in after.valid_evidence_ids

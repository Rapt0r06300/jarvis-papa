from __future__ import annotations


def test_p8_16_explicit_correction_wins_and_conflict_is_auditable() -> None:
    from jarvis_papa.memory_evaluation import PreferenceObservation, resolve_preference_conflict

    inferred = PreferenceObservation(
        value="concis",
        scope="marketplace",
        confidence=0.90,
        source="inferred",
        observed_at=100.0,
        evidence_ids=("edit-old",),
    )
    explicit = PreferenceObservation(
        value="détaillé",
        scope="marketplace",
        confidence=1.0,
        source="explicit_user_correction",
        observed_at=200.0,
        evidence_ids=("user-correction",),
    )

    result = resolve_preference_conflict((inferred, explicit))

    assert result.winner.value == "détaillé"
    assert result.winner.source == "explicit_user_correction"
    assert "edit-old" in result.audit_summary
    assert "user-correction" in result.audit_summary
    assert "explicit" in result.reason.casefold()


def test_p8_17_inferred_preferences_decay_but_explicit_corrections_do_not() -> None:
    from jarvis_papa.memory_evaluation import PreferenceObservation, decay_preference

    stale = PreferenceObservation(
        value="concis",
        scope="marketplace",
        confidence=0.80,
        source="inferred",
        observed_at=0.0,
        evidence_ids=("edit-1",),
    )
    explicit = PreferenceObservation(
        value="détaillé",
        scope="marketplace",
        confidence=1.0,
        source="explicit_user_correction",
        observed_at=0.0,
        evidence_ids=("user-1",),
    )
    now = 90 * 24 * 3600.0

    first = decay_preference(stale, now=now, half_life_days=30)
    second = decay_preference(stale, now=now, half_life_days=30)
    preserved = decay_preference(explicit, now=now, half_life_days=30)

    assert first == second
    assert first.confidence < 0.20
    assert preserved.confidence == 1.0
    assert preserved.source == "explicit_user_correction"


def test_p8_18_edited_draft_is_distinct_from_accepted_and_rejected() -> None:
    from jarvis_papa.memory_evaluation import DraftOutcomeTracker

    tracker = DraftOutcomeTracker()
    tracker.record("draft-1", "edited")
    tracker.record("draft-2", "accepted")
    tracker.record("draft-3", "rejected")
    metrics = tracker.snapshot()

    assert metrics.accepted == 1
    assert metrics.edited == 1
    assert metrics.rejected == 1
    assert metrics.total == 3
    assert tracker.stored_fields == ("draft_id", "outcome")


def test_p8_19_scoped_retrieval_excludes_unrelated_sensitive_memory() -> None:
    from jarvis_papa.memory_evaluation import ScopedMemoryFact, retrieve_scoped_memory

    facts = (
        ScopedMemoryFact(
            key="reply_style",
            value="concis",
            scope="marketplace",
            entity="ebay",
            sensitivity="personal",
        ),
        ScopedMemoryFact(
            key="refund_note",
            value="virement bancaire en attente",
            scope="banking",
            entity="bank",
            sensitivity="sensitive",
        ),
    )

    selected = retrieve_scoped_memory(facts, situation_scope="marketplace", entity="ebay")

    assert [fact.key for fact in selected] == ["reply_style"]
    assert all(fact.scope == "marketplace" for fact in selected)
    assert all(fact.entity in {"", "ebay"} for fact in selected)


def test_p8_20_learning_safety_benchmark_keeps_zero_tolerance_invariants() -> None:
    from jarvis_papa.memory_evaluation import run_learning_safety_benchmark

    result = run_learning_safety_benchmark()

    assert result.passed is True
    assert result.single_example_promoted is False
    assert result.secret_leak_count == 0
    assert result.financial_mutation_allowed_count == 0
    assert {
        "promotion",
        "conflict",
        "forget",
        "decay",
        "secret_denial",
        "pickup_expiry",
        "procedure_governance",
    }.issubset(result.scenarios)

from __future__ import annotations

from jarvis_papa.situations import ProvenanceRef


def _prov(source: str, source_id: str, observed_at: float) -> ProvenanceRef:
    return ProvenanceRef(source, source_id, observed_at)


def test_p7_16_second_visible_item_resolves_from_bounded_context() -> None:
    from jarvis_papa.fusion_context import ReferentContext

    context = ReferentContext(("order-1", "order-2", "order-3"))
    resolved = context.resolve("le deuxième")
    assert resolved.entity_id == "order-2"
    assert resolved.confident is True
    assert resolved.source == "visible_context"

    ambiguous = ReferentContext(()).resolve("celui-là")
    assert ambiguous.entity_id == ""
    assert ambiguous.confident is False
    assert "précis" in ambiguous.message.casefold() or "ambigu" in ambiguous.message.casefold()


def test_p7_17_buyer_context_excludes_unrelated_banking_and_sensitive_fields() -> None:
    from jarvis_papa.fusion_context import SituationContextItem, build_situation_context

    items = (
        SituationContextItem("market-1", "marketplace", {"buyer": "Alice", "item": "Casque"}, ("Bonjour",), ("listing-1",)),
        SituationContextItem("bank-1", "banking", {"merchant": "Amazon", "otp_code": "123456"}, ("Code 123456",), ("bank-mail-1",)),
    )
    context = build_situation_context("market-1", items)
    assert context.situation_id == "market-1"
    assert context.domain == "marketplace"
    assert context.structured_summary == {"buyer": "Alice", "item": "Casque"}
    assert "123456" not in repr(context)
    assert "bank-1" not in repr(context)


def test_p7_18_stale_correlated_fact_is_last_known_with_evidence_ages() -> None:
    from jarvis_papa.fusion_context import assess_fact_freshness

    freshness = assess_fact_freshness(
        (_prov("mail", "m1", 100.0), _prov("web", "relay", 200.0)),
        now=1_000.0,
        max_age_seconds=300.0,
    )
    assert freshness.oldest_age_seconds == 900.0
    assert freshness.newest_age_seconds == 800.0
    assert freshness.current is False
    assert freshness.label == "dernière information connue"


def test_p7_19_source_action_uses_real_reference_or_is_unavailable() -> None:
    from jarvis_papa.fusion_context import build_source_action

    available = build_source_action(_prov("mail", "mail-42", 500.0))
    assert available.enabled is True
    assert available.source == "mail"
    assert available.source_id == "mail-42"

    missing = build_source_action(None)
    assert missing.enabled is False
    assert missing.source_id == ""
    assert "indisponible" in missing.label.casefold()


def test_p7_20_synthetic_fusion_metrics_separate_false_and_missed_merges() -> None:
    from jarvis_papa.fusion_context import FusionCase, evaluate_fusion_cases

    cases = (
        FusionCase("amazon-mondial", should_merge=True, predicted_merge=True, confidence=0.96),
        FusionCase("amazon-bank", should_merge=True, predicted_merge=False, confidence=0.35),
        FusionCase("unrelated", should_merge=False, predicted_merge=True, confidence=0.82),
        FusionCase("separate", should_merge=False, predicted_merge=False, confidence=0.12),
    )
    metrics = evaluate_fusion_cases(cases)
    assert metrics.correct_merges == 1
    assert metrics.missed_merges == 1
    assert metrics.false_merges == 1
    assert metrics.correct_non_merges == 1
    assert metrics.total == 4
    assert 0.0 <= metrics.mean_calibration_error <= 1.0

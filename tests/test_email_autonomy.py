from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from jarvis_papa import email_runtime
from jarvis_papa.email_intelligence import (
    EmailIntent,
    EmailMessage,
    EmailThreadState,
    email_intelligence,
)
from jarvis_papa.situation_assurance import EntityFact
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import ActionState, ProvenanceRef, Responsibility

_PARIS = ZoneInfo("Europe/Paris")


def _mail(
    message_id: str,
    *,
    sender: str = "Service <service@example.test>",
    subject: str = "Information",
    body: str = "Bonjour, voici une information.",
    received_at: float = 1_780_000_000.0,
    sender_is_father: bool = False,
    list_unsubscribe: bool = False,
) -> EmailMessage:
    return EmailMessage(
        source_id="thunderbird",
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        received_at=received_at,
        sender_is_father=sender_is_father,
        list_unsubscribe=list_unsubscribe,
    )


def test_p2_15_scoped_feedback_never_disables_bank_security(tmp_path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    feedback = email_runtime.EmailAutonomyStore(store)
    newsletter = _mail(
        "<newsletter@example.test>",
        sender="Boutique <news@shop.example.test>",
        subject="Offres de la semaine",
        body="Nouveautés et promotions. Unsubscribe.",
        list_unsubscribe=True,
    )
    original = email_intelligence.triage(newsletter)
    correction = feedback.record_correction(
        message=newsletter,
        original_prediction=original.intent.value,
        corrected_label="irrelevant",
        scope="sender:shop.example.test",
        created_at=1_780_000_100.0,
    )
    assert correction.original_prediction == original.intent.value
    assert correction.corrected_label == "irrelevant"
    assert correction.scope == "sender:shop.example.test"
    assert correction.created_at == 1_780_000_100.0
    assert correction.provenance.source_id == newsletter.message_id
    rows = feedback.list_corrections(scope="sender:shop.example.test")
    assert rows == (correction,)

    adjusted = feedback.adjusted_confidence(
        base_confidence=0.70,
        intent=EmailIntent.NEWSLETTER,
        scope="sender:shop.example.test",
    )
    unrelated = feedback.adjusted_confidence(
        base_confidence=0.70,
        intent=EmailIntent.NEWSLETTER,
        scope="sender:another.example.test",
    )
    protected = feedback.adjusted_confidence(
        base_confidence=0.91,
        intent=EmailIntent.BANK_SECURITY,
        scope="sender:shop.example.test",
    )
    assert adjusted != 0.70
    assert 0.50 <= adjusted <= 0.90
    assert unrelated == 0.70
    assert protected >= 0.91


def test_p2_16_draft_first_mode_cannot_send_without_existing_authorization_gate() -> None:
    policy = email_runtime.EmailAutonomyPolicy()
    assert policy.allowed_without_authorization(email_runtime.EmailCapability.READ)
    assert policy.allowed_without_authorization(email_runtime.EmailCapability.UNDERSTAND)
    assert policy.allowed_without_authorization(email_runtime.EmailCapability.DRAFT)
    assert not policy.allowed_without_authorization(email_runtime.EmailCapability.SEND)
    assert not policy.allowed_without_authorization(email_runtime.EmailCapability.DELETE)

    draft = email_runtime.PreparedEmailDraft(
        draft_id="draft-p2c",
        situation_id="situation-marketplace-1",
        recipient="buyer@example.test",
        subject="Re: annonce",
        body="Bonjour, l'article est toujours disponible.",
    )
    assert draft.editable is True
    assert draft.state is email_runtime.DraftState.PREPARED
    assert draft.ui_status == "prepared"

    decision = policy.authorize_mutation(
        capability=email_runtime.EmailCapability.SEND,
        token="",
        binding={"draft_id": draft.draft_id, "recipient": draft.recipient},
    )
    assert decision.ok is False
    with pytest.raises(PermissionError):
        draft.mark_sent(decision)
    assert draft.state is email_runtime.DraftState.PREPARED
    assert draft.ui_status == "prepared"


def test_p2_17_situation_draft_uses_verified_listing_price_and_omits_uncertain_fact() -> None:
    evidence = ProvenanceRef(
        source="marketplace",
        source_id="listing-42",
        observed_at=1_780_000_000.0,
        locator="listing:42",
        content_hash="a" * 64,
    )
    facts = (
        EntityFact("listing_price", "150 €", 0.97, (evidence,)),
        EntityFact("pickup_address", "Adresse peut-être obsolète", 0.40, (evidence,), inferred=True),
    )
    context = email_runtime.SituationDraftContext(
        situation_id="situation-marketplace-42",
        recipient="buyer@example.test",
        subject="Re: prix de l'annonce",
        request="Quel est votre prix ?",
        facts=facts,
    )
    draft = email_runtime.build_situation_draft(context)
    assert "150 €" in draft.body
    assert "Adresse peut-être obsolète" not in draft.body
    assert draft.state is email_runtime.DraftState.PREPARED
    assert draft.editable is True
    assert draft.situation_id == context.situation_id
    assert draft.evidence
    assert draft.evidence[0].source_id == "listing-42"


def test_p2_18_stale_unanswered_conversation_surfaces_once_and_obeys_snooze_ack() -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=_PARIS).timestamp()
    state = EmailThreadState("thread:buyer-1")
    state.responsibility = Responsibility.FATHER_MUST_ACT
    state.action_state = ActionState.REPLY
    state.open_question = "Le produit est-il toujours disponible ?"
    state.last_message_at = now - timedelta(days=5).total_seconds()

    tracker = email_runtime.StaleConversationTracker(stale_after=timedelta(days=3))
    first = tracker.evaluate(state, now=now, low_value=False)
    second = tracker.evaluate(state, now=now, low_value=False)
    assert first is not None
    assert first.thread_key == state.thread_key
    assert first.secondary is False
    assert second is None

    snoozed = EmailThreadState("thread:buyer-snoozed")
    snoozed.responsibility = Responsibility.FATHER_MUST_ACT
    snoozed.action_state = ActionState.REPLY
    snoozed.last_message_at = now - timedelta(days=5).total_seconds()
    tracker.snooze(snoozed.thread_key, until=now + 3600)
    assert tracker.evaluate(snoozed, now=now, low_value=False) is None

    acknowledged = EmailThreadState("thread:buyer-ack")
    acknowledged.responsibility = Responsibility.FATHER_MUST_ACT
    acknowledged.action_state = ActionState.REPLY
    acknowledged.last_message_at = now - timedelta(days=5).total_seconds()
    tracker.acknowledge(acknowledged.thread_key)
    assert tracker.evaluate(acknowledged, now=now, low_value=False) is None

    answered = EmailThreadState("thread:answered")
    answered.responsibility = Responsibility.OTHER_PARTY_MUST_ACT
    answered.action_state = ActionState.WAIT_FOR_OTHER_PARTY
    answered.last_message_at = now - timedelta(days=5).total_seconds()
    assert tracker.evaluate(answered, now=now, low_value=False) is None

    low_value = EmailThreadState("thread:low-value")
    low_value.responsibility = Responsibility.FATHER_MUST_ACT
    low_value.action_state = ActionState.REPLY
    low_value.last_message_at = now - timedelta(days=5).total_seconds()
    low_value_reminder = tracker.evaluate(low_value, now=now, low_value=True)
    assert low_value_reminder is not None
    assert low_value_reminder.secondary is True


def test_p2_19_briefing_counts_persist_and_deduplicate_by_situation(tmp_path) -> None:
    store = SituationStore(tmp_path / "situations.sqlite3")
    autonomy = email_runtime.EmailAutonomyStore(store)
    for index in range(10):
        disposition = (
            email_runtime.BriefingDisposition.IGNORE_FOR_BRIEFING
            if index < 3
            else email_runtime.BriefingDisposition.ACTION_REQUIRED
        )
        autonomy.record_briefing(
            message_id=f"message-{index}",
            disposition=disposition,
            situation_id="situation-order-42",
            actionable=index >= 3,
            observed_at=1_780_000_000.0 + index,
        )
    summary = autonomy.briefing_summary()
    assert summary.message_count == 10
    assert summary.ignored_count == 3
    assert summary.actionable_situation_count == 1
    assert not hasattr(summary, "time_saved")
    assert autonomy.briefing_summary() == summary


def test_p2_20_email_benchmark_is_reproducible_anonymized_and_reports_safety_metrics() -> None:
    cases = email_runtime.synthetic_email_benchmark_cases()
    categories = {case.category for case in cases}
    assert {
        "newsletter",
        "order",
        "carrier",
        "marketplace",
        "bank_admin",
        "malformed_html",
        "unicode",
        "phishing",
        "prompt_injection",
    } <= categories
    assert all(case.thread_group for case in cases)
    assert all(isinstance(case.expected_intent, EmailIntent) for case in cases)
    assert all(isinstance(case.expected_action_state, ActionState) for case in cases)
    serialized = "\n".join(
        f"{case.message.sender}\n{case.message.subject}\n{case.message.body}" for case in cases
    ).casefold()
    assert "sk-" not in serialized
    assert "password=" not in serialized
    assert "bermond" not in serialized

    first = email_runtime.run_email_benchmark(
        cases,
        model_version="rules-v1",
        config_version="p2c-v1",
    )
    second = email_runtime.run_email_benchmark(
        cases,
        model_version="rules-v1",
        config_version="p2c-v1",
    )
    assert first == second
    assert first["model_version"] == "rules-v1"
    assert first["config_version"] == "p2c-v1"
    assert first["total_cases"] == len(cases)
    assert "CRITICAL_MISS_RATE" in first
    assert "NOISE_FALSE_POSITIVES" in first
    assert 0.0 <= first["CRITICAL_MISS_RATE"] <= 1.0
    assert first["NOISE_FALSE_POSITIVES"] >= 0
    assert 0.0 <= first["classification_accuracy"] <= 1.0

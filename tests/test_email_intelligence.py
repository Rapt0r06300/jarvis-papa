from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from jarvis_papa import email_runtime
from jarvis_papa.email_intelligence import (
    EMAIL_MEANING_SCHEMA_VERSION,
    EMAIL_TAXONOMY_VERSION,
    EmailIntent,
    EmailMessage,
    EmailThreadState,
    ModelStage,
    StructuredEmailMeaning,
    derive_thread_identity,
    email_intelligence,
)
from jarvis_papa.situation_store import SituationStore
from jarvis_papa.situations import ActionState, Responsibility


def _mail(
    message_id: str,
    *,
    sender: str = "Service <service@example.com>",
    subject: str = "Information",
    body: str = "Bonjour, voici une information.",
    references: tuple[str, ...] = (),
    in_reply_to: str = "",
    sender_is_father: bool = False,
    list_unsubscribe: bool = False,
    received_at: float = 1_780_000_000.0,
) -> EmailMessage:
    return EmailMessage(
        source_id="thunderbird",
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        received_at=received_at,
        references=references,
        in_reply_to=in_reply_to,
        sender_is_father=sender_is_father,
        list_unsubscribe=list_unsubscribe,
    )


def test_p2_01_cheap_first_triage_avoids_one_llm_call_per_mail() -> None:
    messages = [
        _mail(
            f"<newsletter-{index}@example.com>",
            subject="Newsletter et offres de la semaine",
            body="Découvrez nos offres. Unsubscribe.",
            list_unsubscribe=True,
        )
        for index in range(250)
    ]
    messages.extend(
        _mail(
            f"<normal-{index}@example.com>",
            subject="Petit point",
            body="Bonjour, je voulais vous tenir au courant.",
        )
        for index in range(50)
    )
    decisions = [email_intelligence.triage(message) for message in messages]
    model_calls = sum(item.escalation is not ModelStage.NONE for item in decisions)
    assert model_calls == 50
    assert model_calls < len(messages)
    assert all(item.destructive_action_allowed is False for item in decisions)
    assert all(len(str(item.bounded_context)) < 9000 for item in decisions)


def test_p2_01_uncertain_fast_result_can_escalate_to_strong_model() -> None:
    message = _mail("<uncertain@example.com>")
    provisional = StructuredEmailMeaning(
        summary="Message ambigu",
        intent=EmailIntent.UNKNOWN_IMPORTANT,
        action_state=ActionState.USER_DECISION,
        importance=55,
        deadline=None,
        requested_action="",
        references=(),
        confidence=0.51,
        provenance=(message.provenance,),
    )
    decision = email_intelligence.triage(message, fast_result=provisional)
    assert decision.escalation is ModelStage.STRONG
    assert len(str(decision.bounded_context)) < 9000


def test_p2_02_taxonomy_is_typed_versioned_and_contains_critical_classes() -> None:
    assert EMAIL_TAXONOMY_VERSION == 1
    required = {
        EmailIntent.NEWSLETTER,
        EmailIntent.ORDER,
        EmailIntent.SHIPPING,
        EmailIntent.DELAY,
        EmailIntent.PICKUP,
        EmailIntent.REFUND,
        EmailIntent.BANK_SECURITY,
        EmailIntent.ADMIN,
        EmailIntent.MARKETPLACE,
        EmailIntent.NEGOTIATION,
        EmailIntent.ACTION,
        EmailIntent.REPLY,
        EmailIntent.DEADLINE,
        EmailIntent.UNKNOWN_IMPORTANT,
    }
    assert required <= set(EmailIntent)
    uncertain = email_intelligence.triage(
        _mail(
            "<important@example.com>",
            subject="Contrat important",
            body="Information importante concernant votre contrat.",
        )
    )
    assert isinstance(uncertain.intent, EmailIntent)
    assert uncertain.intent is EmailIntent.UNKNOWN_IMPORTANT


def test_p2_03_structured_meaning_rejects_malformed_model_output_and_keeps_provenance() -> None:
    message = _mail("<model@example.com>")
    valid = StructuredEmailMeaning.from_model_payload(
        {
            "summary": "Document à transmettre",
            "intent": "admin",
            "action_state": "document_required",
            "importance": 78,
            "deadline": "2026-09-04",
            "requested_action": "Transmettre l'attestation",
            "references": ["dossier:42"],
            "confidence": 0.91,
            "entities": ["document:attestation"],
            "related_situation": "situation-42",
            "schema_version": EMAIL_MEANING_SCHEMA_VERSION,
        },
        provenance=message.provenance,
    )
    assert valid.deadline == "2026-09-04"
    assert valid.provenance[0].source_id == "<model@example.com>"
    assert valid.action_state is ActionState.DOCUMENT_REQUIRED
    with pytest.raises(ValueError):
        StructuredEmailMeaning.from_model_payload(
            {
                "summary": "malformé",
                "intent": "admin",
                "action_state": "document_required",
                "importance": 50,
                "deadline": "vendredi peut-être",
                "requested_action": "",
                "references": [],
                "confidence": 0.8,
            },
            provenance=message.provenance,
        )
    with pytest.raises(ValueError):
        StructuredEmailMeaning.from_model_payload(
            {"summary": "incomplet"},
            provenance=message.provenance,
        )


def test_p2_04_action_state_is_independent_and_father_reply_waits_for_other_party() -> None:
    pickup = email_intelligence.triage(
        _mail(
            "<pickup@example.com>",
            subject="Votre colis est disponible au point relais",
            body="Merci de retirer votre colis avant le 04/09/2026.",
        )
    )
    assert pickup.intent is EmailIntent.PICKUP
    assert pickup.action_state is ActionState.PICKUP
    father = email_intelligence.triage(
        _mail(
            "<father@example.com>",
            sender="Robert <robert@example.com>",
            subject="Re: Dossier",
            body="Bonjour, je vous ai transmis le document demandé.",
            sender_is_father=True,
        )
    )
    assert father.action_state is ActionState.WAIT_FOR_OTHER_PARTY


def test_p2_05_reply_chain_and_duplicate_resend_share_one_durable_thread() -> None:
    root = _mail(
        "<root@example.com>",
        subject="Dossier assurance",
        body="Pouvez-vous transmettre l'attestation ?",
    )
    duplicate = _mail(
        "<root@example.com>",
        subject="Dossier assurance",
        body="Pouvez-vous transmettre l'attestation ?",
    )
    reply = _mail(
        "<reply@example.com>",
        subject="Re: Dossier assurance",
        body="Je relance ma demande.",
        references=("<root@example.com>",),
        in_reply_to="<root@example.com>",
    )
    root_id = derive_thread_identity(root)
    duplicate_id = derive_thread_identity(duplicate)
    reply_id = derive_thread_identity(reply)
    assert root_id.key == duplicate_id.key == reply_id.key
    assert reply_id.confidence >= 0.9


def test_p2_05_subject_fallback_is_explicitly_low_confidence() -> None:
    first = _mail("generated-a", subject="Même sujet", sender="A <a@example.com>")
    second = _mail("generated-b", subject="Re: Même sujet", sender="A <a@example.com>")
    first_id = derive_thread_identity(first)
    second_id = derive_thread_identity(second)
    assert first_id.key == second_id.key
    assert first_id.confidence == second_id.confidence == 0.45
    assert first_id.method == "conservative_subject_domain_fallback"


def test_p2_06_thread_state_question_reply_thanks_has_no_open_reply_obligation() -> None:
    root = _mail(
        "<q@example.com>",
        sender="Assurance <agent@example.com>",
        subject="Attestation demandée",
        body="Pouvez-vous nous transmettre votre attestation ?",
        received_at=1_780_000_000.0,
    )
    father = _mail(
        "<father-reply@example.com>",
        sender="Robert <robert@example.com>",
        subject="Re: Attestation demandée",
        body="Bonjour, je vous transmets l'attestation demandée.",
        references=("<q@example.com>",),
        sender_is_father=True,
        received_at=1_780_000_100.0,
    )
    thanks = _mail(
        "<thanks@example.com>",
        sender="Assurance <agent@example.com>",
        subject="Re: Attestation demandée",
        body="Merci beaucoup, bien reçu.",
        references=("<q@example.com>", "<father-reply@example.com>"),
        received_at=1_780_000_200.0,
    )
    state = EmailThreadState(derive_thread_identity(root).key)
    for message in (root, father, thanks):
        meaning = email_intelligence.meaning_from_rules(message)
        state.update(message, meaning)
    assert state.open_question == ""
    assert state.action_state is ActionState.NO_ACTION
    assert state.responsibility is Responsibility.COMPLETED
    assert state.latest_state == "completed"
    assert len(state.message_ids) == 3
    assert len(state.evidence) == 3


def test_email_message_requires_stable_identity_and_positive_time() -> None:
    with pytest.raises(ValueError):
        EmailMessage("", "", "", "", "", time.time())


def test_p2_07_commitment_reuses_engine_and_normalizes_relative_deadline() -> None:
    observed = datetime(2026, 9, 2, 10, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
    message = _mail(
        "<deadline@example.com>",
        sender="Assurance <agent@example.com>",
        subject="Réponse requise",
        body="Merci de répondre avant vendredi avec votre attestation.",
        received_at=observed,
    )
    state = email_runtime.RuntimeEmailThreadState(derive_thread_identity(message).key)
    state.update(message, email_intelligence.meaning_from_rules(message))
    assert state.commitments
    commitment = state.commitments[-1]
    assert commitment.actor == "father"
    assert "répondre" in commitment.obligation.casefold()
    assert commitment.due_date == "2026-09-04"
    assert commitment.source_wording.casefold() == "avant vendredi"
    assert commitment.confidence >= 0.75
    assert commitment.provenance.source_id == "<deadline@example.com>"
    assert state.to_situation_payload()["commitments"]


def test_p2_08_future_father_promise_keeps_responsibility_on_father() -> None:
    root = _mail(
        "<ask@example.com>",
        body="Pouvez-vous envoyer le justificatif ?",
    )
    promise = _mail(
        "<promise@example.com>",
        sender="Robert <robert@example.com>",
        subject="Re: justificatif",
        body="Je vous l'enverrai demain.",
        references=("<ask@example.com>",),
        sender_is_father=True,
        received_at=root.received_at + 60,
    )
    state = email_runtime.RuntimeEmailThreadState(derive_thread_identity(root).key)
    state.update(root, email_intelligence.meaning_from_rules(root))
    state.update(promise, email_intelligence.meaning_from_rules(promise))
    assert state.responsibility is Responsibility.FATHER_MUST_ACT
    assert state.latest_state == "father_committed"
    assert state.commitments[-1].actor == "father"


def test_p2_09_newsletters_are_silent_but_bank_alert_stays_visible() -> None:
    newsletters = [
        _mail(
            f"<nl-{index}@example.com>",
            subject="Newsletter offres",
            body="Découvrez les nouveautés. Unsubscribe.",
            list_unsubscribe=True,
        )
        for index in range(27)
    ]
    bank = _mail(
        "<bank@example.com>",
        sender="Banque <security@bank.example>",
        subject="Alerte sécurité carte bancaire",
        body="Une opération inhabituelle nécessite une vérification.",
    )
    newsletter_decisions = [
        email_runtime.briefing_decision(message, email_intelligence.triage(message))
        for message in newsletters
    ]
    bank_decision = email_runtime.briefing_decision(bank, email_intelligence.triage(bank))
    assert all(
        item.disposition is email_runtime.BriefingDisposition.IGNORE_FOR_BRIEFING
        for item in newsletter_decisions
    )
    assert bank_decision.disposition is email_runtime.BriefingDisposition.ACTION_REQUIRED
    assert all(item.mailbox_mutation_allowed is False for item in newsletter_decisions)
    assert bank_decision.mailbox_mutation_allowed is False


def test_p2_10_lookalike_bank_domain_is_evidence_not_fraud_verdict() -> None:
    message = _mail(
        "<spoof@example.com>",
        sender="Crédit Agricole <alerte@credit-agric0le.example>",
        subject="URGENT sécurité compte",
        body="Vérifiez immédiatement: http://credit-agricole-secure.example/login",
    )
    assessment = email_runtime.assess_email_trust(message)
    kinds = {item.kind for item in assessment.signals}
    assert "brand_domain_mismatch" in kinds
    assert "suspicious_link" in kinds
    assert "urgency_cue" in kinds
    assert assessment.requires_verification is True
    assert assessment.certainty < 1.0
    assert email_runtime.domain_matches_official(
        "credit-agricole.fr", ("credit-agricole.fr", "www.credit-agricole.fr")
    )


def test_p2_11_html_sanitizer_blocks_active_and_remote_content() -> None:
    message = _mail("<html@example.com>")
    html = (
        "<html><body>Bonjour<script>steal()</script>"
        "<img src='https://tracker.example/pixel.gif'>"
        "<a href='http://example.net/dossier'>Voir le dossier</a></body></html>"
    )
    sanitized = email_runtime.sanitize_email_html(html, provenance=message.provenance)
    assert "steal" not in sanitized.text
    assert "Bonjour" in sanitized.text
    assert sanitized.blocked_active_count >= 1
    assert sanitized.blocked_remote_count >= 1
    assert sanitized.links[0].url == "http://example.net/dossier"
    assert sanitized.links[0].trusted is False
    assert sanitized.links[0].provenance.source_id == "<html@example.com>"


def test_p2_12_backfill_is_bounded_read_only_and_checkpointed(tmp_path) -> None:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
    policy = email_runtime.EmailBackfillPolicy()
    plan = policy.plan(now)
    assert plan.window_days <= 14
    assert plan.max_messages <= 500
    assert plan.read_only is True
    assert plan.lane == "backfill"
    assert policy.next_window_days(plan.window_days) > plan.window_days
    store = SituationStore(tmp_path / "situations.sqlite3")
    email_runtime.save_email_backfill_checkpoint(
        store,
        "cursor-42",
        source_version="p2b",
        evidence_hash="abc123",
    )
    checkpoint = store.get_checkpoint("email", lane="backfill")
    assert checkpoint is not None
    assert checkpoint["cursor"] == "cursor-42"
    assert checkpoint["source_version"] == "p2b"


def test_p2_13_fresh_evidence_backed_bank_mail_preempts_backfill_without_drops() -> None:
    newsletter = _mail(
        "<old-newsletter@example.com>",
        subject="Newsletter",
        body="Offres de la semaine. Unsubscribe.",
        list_unsubscribe=True,
        received_at=1_779_000_000.0,
    )
    bank = _mail(
        "<fresh-bank@example.com>",
        sender="Banque <security@bank.example>",
        subject="Alerte sécurité carte bancaire",
        body="Vérification requise pour une opération inhabituelle.",
        received_at=1_780_000_500.0,
    )
    items = [
        email_runtime.EmailWorkItem(
            newsletter,
            email_intelligence.triage(newsletter),
            lane="backfill",
            sequence=1,
        ),
        email_runtime.EmailWorkItem(
            bank,
            email_intelligence.triage(bank),
            lane="live",
            sequence=2,
        ),
    ]
    ordered = email_runtime.prioritize_email_work(items)
    assert [item.message.message_id for item in ordered] == [
        "<fresh-bank@example.com>",
        "<old-newsletter@example.com>",
    ]
    assert len(ordered) == len(items)


def test_p2_14_compaction_retains_old_unresolved_invoice_and_deadline() -> None:
    first = _mail(
        "<invoice-0@example.com>",
        subject="Facture manquante",
        body="Merci de transmettre la facture avant le 04/09/2026.",
    )
    first_meaning = StructuredEmailMeaning(
        summary="Facture demandée",
        intent=EmailIntent.ADMIN,
        action_state=ActionState.DOCUMENT_REQUIRED,
        importance=80,
        deadline="2026-09-04",
        requested_action="Transmettre la facture",
        references=("document:facture",),
        confidence=0.95,
        provenance=(first.provenance,),
        entities=("document:facture",),
    )
    messages = [first]
    meanings = [first_meaning]
    state = email_runtime.RuntimeEmailThreadState(derive_thread_identity(first).key)
    state.update(first, first_meaning)
    for index in range(1, 50):
        message = _mail(
            f"<invoice-{index}@example.com>",
            subject="Re: Facture manquante",
            body=f"Information intermédiaire {index}.",
            references=("<invoice-0@example.com>",),
            received_at=first.received_at + index,
        )
        meaning = email_intelligence.meaning_from_rules(message)
        messages.append(message)
        meanings.append(meaning)
        state.update(message, meaning)
    compact = email_runtime.compact_email_thread(state, messages, meanings, max_messages=5)
    assert compact.message_count == 50
    assert compact.commitment == "Transmettre la facture"
    assert compact.deadline == "2026-09-04"
    assert "document:facture" in compact.entities
    assert compact.provenance
    assert len(compact.recent_messages) <= 5
    assert compact.recent_messages[-1]["message_id"] == "<invoice-49@example.com>"

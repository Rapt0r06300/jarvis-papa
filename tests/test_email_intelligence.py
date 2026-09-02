from __future__ import annotations

import time

import pytest

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
            body="Merci de regarder ce point.",
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

from jarvis_papa.mail import IncomingMail, mail_assistant
from jarvis_papa.speech import SpeechImportance


def test_document_request_becomes_high_priority_action() -> None:
    mail = IncomingMail(
        message_id=42,
        header_message_id="abc@example.test",
        author="Assurance Exemple <contact@example.test>",
        subject="Justificatif demandé",
        body="Bonjour, merci de transmettre votre facture avant le 5 septembre.",
    )

    assessment = mail_assistant.assess(mail)

    assert assessment.importance is SpeechImportance.HIGH
    assert assessment.action_required is True
    assert assessment.category == "important"
    assert "facture" in assessment.search_terms


def test_newsletter_is_silent_and_kept_for_sorting() -> None:
    mail = IncomingMail(
        message_id=43,
        header_message_id="newsletter@example.test",
        author="Boutique Exemple",
        subject="Newsletter de la semaine",
        body="Promotion spéciale. Cliquez ici pour vous désabonner.",
    )

    assessment = mail_assistant.assess(mail)
    card = mail_assistant.create_action_card(mail, assessment)

    assert assessment.is_noise is True
    assert assessment.category == "newsletter"
    assert assessment.importance is SpeechImportance.LOW
    assert card is not None
    assert card.speech_text is None
    assert card.options == []
    assert card.metadata["category"] == "newsletter"

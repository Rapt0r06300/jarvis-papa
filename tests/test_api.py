from fastapi.testclient import TestClient

from jarvis_papa.app import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_is_available() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Jarvis est prêt" in response.text
    assert "Bonjour Robert" in response.text
    assert "Ce qui demande ton attention" in response.text
    assert "Fais-moi le point" in response.text
    assert "Autorisation 1 sur 2" in response.text
    assert "Autorisation 2 sur 2" in response.text


def test_status_reports_double_confirmation_security() -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["security"] == "two_explicit_confirmations_for_changes"
    assert payload["modules"]["mail"] == "important_summaries_and_newsletter_sorting"
    assert payload["modules"]["voice_output"] == "important_mail_summaries_ready"


def test_write_permission_requires_two_confirmations() -> None:
    none = client.post("/api/security/check", json={"risk": "write", "confirmations": 0})
    one = client.post("/api/security/check", json={"risk": "write", "confirmations": 1})
    two = client.post("/api/security/check", json={"risk": "write", "confirmations": 2})

    assert none.status_code == 200
    assert none.json()["allowed"] is False
    assert none.json()["confirmations_remaining"] == 2
    assert one.json()["allowed"] is False
    assert one.json()["confirmations_remaining"] == 1
    assert two.json()["allowed"] is True
    assert two.json()["confirmations_remaining"] == 0


def test_legacy_boolean_confirmation_is_only_one_confirmation() -> None:
    response = client.post(
        "/api/security/check",
        json={"risk": "write", "confirmed": True},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert response.json()["confirmations_received"] == 1


def test_background_information_stays_silent() -> None:
    response = client.post(
        "/api/speech/event",
        json={
            "text": "La synchronisation est terminée.",
            "importance": "normal",
            "dedupe_key": "sync-finished",
        },
    )
    assert response.status_code == 200
    assert response.json()["should_speak"] is False


def test_direct_response_to_robert_should_be_spoken() -> None:
    response = client.post(
        "/api/speech/event",
        json={
            "text": "Robert, tu as deux messages importants.",
            "importance": "normal",
            "user_initiated": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["should_speak"] is True
    assert response.json()["reason"] == "direct_response_to_robert"


def test_important_mail_gets_short_spoken_summary() -> None:
    response = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 123,
            "header_message_id": "mail-123@example.test",
            "author": "Assurance Exemple <contact@example.test>",
            "subject": "Facture demandée",
            "body": (
                "Bonjour, merci de transmettre la facture avant le 5 septembre. "
                "Vous pouvez également nous contacter si vous avez une question supplémentaire."
            ),
            "folder": "Inbox",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["category"] == "important"
    assert payload["action_required"] is True
    assert payload["card"] is not None
    assert len(payload["spoken_summary"]) <= 150
    assert payload["card"]["speech_text"].startswith("Robert, mail important de Assurance Exemple.")
    option_map = {item["id"]: item for item in payload["card"]["options"]}
    assert "find-files" in option_map
    assert option_map["prepare-reply"]["requires_confirmation"] is True


def test_newsletter_is_silent_and_kept_out_of_main_attention_list() -> None:
    before = client.get("/api/newsletters").json()["count"]
    response = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 777,
            "header_message_id": "newsletter-777@example.test",
            "author": "Boutique Exemple",
            "subject": "Newsletter - nos offres du mois",
            "body": "Découvrez nos promotions. Se désabonner ici.",
        },
    )
    payload = response.json()
    assert payload["category"] == "newsletter"
    assert payload["speech"]["spoken"] is False
    after = client.get("/api/newsletters").json()["count"]
    assert after == before + 1
    main_cards = client.get("/api/actions").json()
    assert all(card["metadata"].get("category") != "newsletter" for card in main_cards)


def test_newsletter_sort_requires_two_confirmations() -> None:
    one = client.post("/api/newsletters/sort", json={"confirmations": 1})
    assert one.status_code == 200
    if client.get("/api/newsletters").json()["count"]:
        assert one.json()["ok"] is False
        assert one.json()["confirmations_remaining"] == 1


def test_open_email_action_is_read_only() -> None:
    created = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 321,
            "header_message_id": "mail-321@example.test",
            "author": "Service Exemple",
            "subject": "Information importante",
            "body": "Merci de répondre à ce message.",
        },
    ).json()
    card_id = created["card"]["id"]
    executed = client.post(
        f"/api/actions/{card_id}/execute",
        json={"option_id": "open-email", "confirmations": 0},
    )
    assert executed.status_code == 200
    assert executed.json()["ok"] is True
    commands = client.get("/api/thunderbird/commands").json()
    assert any(command["kind"] == "open_message" for command in commands)


def test_prepare_reply_requires_two_confirmations() -> None:
    created = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 654,
            "author": "Administration Exemple",
            "subject": "Réponse demandée",
            "body": "Merci de répondre à ce message.",
        },
    ).json()
    card_id = created["card"]["id"]
    one = client.post(
        f"/api/actions/{card_id}/execute",
        json={"option_id": "prepare-reply", "confirmations": 1},
    )
    assert one.status_code == 200
    assert one.json()["ok"] is False
    assert one.json()["confirmations_remaining"] == 1


def test_attachment_draft_requires_two_confirmations() -> None:
    created = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 444,
            "author": "Assurance Exemple",
            "subject": "Justificatif demandé",
            "body": "Merci de transmettre le justificatif.",
        },
    ).json()
    card_id = created["card"]["id"]
    response = client.post(
        f"/api/actions/{card_id}/attach",
        json={"paths": ["document.pdf"], "confirmations": 1},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["confirmations_remaining"] == 1


def test_browser_agent_blocks_loopback_urls() -> None:
    response = client.post(
        "/api/browser/read",
        json={"url": "http://127.0.0.1:9999/private"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_local_memory_write_requires_two_confirmations() -> None:
    blocked = client.post(
        "/api/memory/remember",
        json={
            "category": "preference-test",
            "key": "courriers assurance",
            "value": "réponses courtes",
            "confirmations": 1,
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["ok"] is False

    saved = client.post(
        "/api/memory/remember",
        json={
            "category": "preference-test",
            "key": "courriers assurance",
            "value": "réponses courtes",
            "confirmations": 2,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    recalled = client.get("/api/memory/recall", params={"q": "assurance"})
    assert any(item["value"] == "réponses courtes" for item in recalled.json()["results"])

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


def test_status_reports_active_foundation_modules() -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    modules = response.json()["modules"]
    assert modules["mail"] == "bridge_ready"
    assert modules["voice_output"] == "intelligent_policy_ready"


def test_write_permission_requires_confirmation() -> None:
    response = client.post(
        "/api/security/check",
        json={"risk": "write", "confirmed": False},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False


def test_write_permission_can_be_confirmed() -> None:
    response = client.post(
        "/api/security/check",
        json={"risk": "write", "confirmed": True},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True


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


def test_action_required_should_be_spoken() -> None:
    response = client.post(
        "/api/speech/event",
        json={
            "text": "Robert, veux-tu envoyer cette réponse ?",
            "importance": "normal",
            "action_required": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["should_speak"] is True


def test_incoming_mail_creates_contextual_action_card() -> None:
    response = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 123,
            "header_message_id": "mail-123@example.test",
            "author": "Assurance Exemple <contact@example.test>",
            "subject": "Facture demandée",
            "body": "Bonjour, merci de transmettre la facture avant le 5 septembre.",
            "folder": "Inbox",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["action_required"] is True
    assert payload["card"] is not None
    option_ids = {item["id"] for item in payload["card"]["options"]}
    assert "find-files" in option_ids
    assert "prepare-reply" in option_ids


def test_open_email_action_is_forwarded_to_thunderbird() -> None:
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
        json={"option_id": "open-email", "confirmed": False},
    )

    assert executed.status_code == 200
    assert executed.json()["ok"] is True
    commands = client.get("/api/thunderbird/commands").json()
    assert any(command["kind"] == "open_message" for command in commands)

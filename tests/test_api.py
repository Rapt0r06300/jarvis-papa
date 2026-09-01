from uuid import uuid4

from fastapi.testclient import TestClient

from jarvis_papa.app import app

client = TestClient(app)


def authorization_token(action_key: str, description: str = "Action de test") -> str:
    started = client.post(
        "/api/confirmations/start",
        json={"action_key": action_key, "description": description},
    )
    assert started.status_code == 200
    challenge_id = started.json()["challenge_id"]
    first = client.post(f"/api/confirmations/{challenge_id}/confirm", json={})
    assert first.status_code == 200
    assert first.json()["step"] == 1
    assert first.json()["completed"] is False
    second = client.post(f"/api/confirmations/{challenge_id}/confirm", json={})
    assert second.status_code == 200
    assert second.json()["step"] == 2
    assert second.json()["completed"] is True
    token = second.json()["authorization_token"]
    assert isinstance(token, str) and token
    return token


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dashboard_is_available_and_accessible() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Jarvis est prêt" in response.text
    assert "Bonjour Robert" in response.text
    assert "À faire maintenant" in response.text
    assert "Fais-moi le point" in response.text
    assert "Autorisation 1 sur 2" in response.text
    assert "Autorisation ${step} sur 2" in response.text
    assert "Dernière vérification" in response.text
    assert "Oui, je confirme" in response.text
    assert 'class="avatar"' in response.text
    assert "assistant-pane.speaking" in response.text
    assert "prefers-reduced-motion" in response.text
    assert 'aria-live="polite"' in response.text


def test_status_reports_hardened_secretary_modules() -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["security"] == "server_enforced_two_step_one_time_grants"
    assert payload["modules"]["mail"] == "professional_triage_deadlines_and_newsletters"
    assert payload["modules"]["voice_output"] == "privacy_aware_french_voice"
    assert payload["modules"]["tasks"] == "persistent_prioritized_snooze_ready"


def test_http_security_headers_are_present() -> None:
    response = client.get("/health")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_foreign_web_origin_cannot_call_jarvis() -> None:
    response = client.post(
        "/api/assistant/ask",
        headers={"Origin": "https://evil.example"},
        json={"text": "Bonjour", "speak": False},
    )
    assert response.status_code == 403


def test_voice_status_exposes_french_female_persona_and_private_sensitive_chain() -> None:
    response = client.get("/api/voice/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "fr-FR"
    assert payload["persona"] == "jeune_femme_française_douce"
    assert payload["provider_order"][:3] == ["elevenlabs", "azure", "qwen3"]
    assert payload["sensitive_provider_order"] == ["qwen3", "windows"]
    assert payload["cloud_for_sensitive_content"] is False


def test_voice_event_endpoint_starts_empty_or_returns_events() -> None:
    response = client.get("/api/voice/events", params={"after": 0})
    assert response.status_code == 200
    assert isinstance(response.json()["events"], list)


def test_write_security_check_never_trusts_client_confirmation_counter() -> None:
    for confirmations in (0, 1, 2):
        response = client.post(
            "/api/security/check",
            json={"risk": "write", "confirmations": confirmations},
        )
        assert response.status_code == 200
        assert response.json()["allowed"] is False
        assert response.json()["confirmations_remaining"] == 2


def test_read_security_check_remains_automatic() -> None:
    response = client.post("/api/security/check", json={"risk": "read"})
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_two_distinct_server_confirmation_steps_are_required() -> None:
    started = client.post(
        "/api/confirmations/start",
        json={"action_key": "memory.remember", "description": "mémoriser une préférence"},
    ).json()
    challenge_id = started["challenge_id"]

    first = client.post(f"/api/confirmations/{challenge_id}/confirm", json={}).json()
    assert first["completed"] is False
    assert first["authorization_token"] is None

    second = client.post(f"/api/confirmations/{challenge_id}/confirm", json={}).json()
    assert second["completed"] is True
    assert second["authorization_token"]

    third = client.post(f"/api/confirmations/{challenge_id}/confirm", json={}).json()
    assert third["ok"] is False


def test_authorization_token_is_bound_to_action_and_one_use_only() -> None:
    token = authorization_token("memory.remember")
    key = f"test-{uuid4().hex}"
    saved = client.post(
        "/api/memory/remember",
        json={
            "category": "test",
            "key": key,
            "value": "réponses courtes",
            "authorization_token": token,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True

    reused = client.post(
        "/api/memory/remember",
        json={
            "category": "test",
            "key": key + "-2",
            "value": "autre valeur",
            "authorization_token": token,
        },
    )
    assert reused.status_code == 200
    assert reused.json()["ok"] is False


def test_wrong_action_cannot_consume_authorization_token() -> None:
    token = authorization_token("memory.remember")
    response = client.post(
        "/api/browser/download",
        json={
            "url": "https://example.com",
            "link_text": "Document",
            "authorization_token": token,
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_background_information_stays_silent() -> None:
    response = client.post(
        "/api/speech/event",
        json={
            "text": "La synchronisation est terminée.",
            "importance": "normal",
            "dedupe_key": f"sync-{uuid4().hex}",
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


def test_important_mail_gets_priority_deadline_and_short_summary() -> None:
    unique = uuid4().hex
    response = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 123,
            "header_message_id": f"mail-{unique}@example.test",
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
    assert payload["priority_score"] >= 60
    assert payload["deadline_text"] == "5 septembre"
    assert payload["recommended_action"]
    assert len(payload["spoken_summary"]) <= 175
    option_map = {item["id"]: item for item in payload["card"]["options"]}
    assert "find-files" in option_map
    assert option_map["prepare-reply"]["requires_confirmation"] is True


def test_suspicious_mail_is_never_silently_sorted_as_newsletter() -> None:
    response = client.post(
        "/api/mail/incoming",
        json={
            "header_message_id": f"suspicious-{uuid4().hex}@example.test",
            "author": "Service sécurité",
            "subject": "Compte bloqué - action urgente",
            "body": "Votre compte est bloqué. Veuillez fournir votre code de sécurité immédiatement.",
            "list_unsubscribe": True,
        },
    )
    payload = response.json()
    assert payload["category"] == "suspicious"
    assert payload["noise"] is False
    assert payload["priority_score"] >= 80
    assert payload["card"] is not None


def test_newsletter_is_silent_and_kept_out_of_main_attention_list() -> None:
    unique = uuid4().hex
    before = client.get("/api/newsletters").json()["count"]
    response = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 777,
            "header_message_id": f"newsletter-{unique}@example.test",
            "author": "Boutique Exemple",
            "subject": "Newsletter - nos offres du mois",
            "body": "Découvrez nos promotions. Se désabonner ici.",
            "list_unsubscribe": True,
        },
    )
    payload = response.json()
    assert payload["category"] == "newsletter"
    assert payload["speech"]["spoken"] is False
    assert client.get("/api/newsletters").json()["count"] == before + 1
    main_cards = client.get("/api/actions").json()
    assert all(card["metadata"].get("category") != "newsletter" for card in main_cards)


def test_old_confirmations_field_cannot_sort_newsletters() -> None:
    response = client.post("/api/newsletters/sort", json={"confirmations": 2})
    assert response.status_code == 200
    if client.get("/api/newsletters").json()["count"]:
        assert response.json()["ok"] is False
        assert response.json()["confirmations_remaining"] == 2


def test_open_email_action_is_read_only() -> None:
    unique = uuid4().hex
    created = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 321,
            "header_message_id": f"mail-{unique}@example.test",
            "author": "Service Exemple",
            "subject": "Information importante",
            "body": "Merci de répondre à ce message.",
        },
    ).json()
    card_id = created["card"]["id"]
    executed = client.post(
        f"/api/actions/{card_id}/execute",
        json={"option_id": "open-email"},
    )
    assert executed.status_code == 200
    assert executed.json()["ok"] is True
    commands = client.get("/api/thunderbird/commands").json()
    assert any(command["kind"] == "open_message" for command in commands)


def test_prepare_reply_cannot_be_bypassed_with_confirmations_two() -> None:
    created = client.post(
        "/api/mail/incoming",
        json={
            "message_id": 654,
            "header_message_id": f"reply-{uuid4().hex}@example.test",
            "author": "Administration Exemple",
            "subject": "Réponse demandée",
            "body": "Merci de répondre à ce message.",
        },
    ).json()
    card_id = created["card"]["id"]
    blocked = client.post(
        f"/api/actions/{card_id}/execute",
        json={"option_id": "prepare-reply", "confirmations": 2},
    )
    assert blocked.status_code == 200
    assert blocked.json()["ok"] is False
    assert blocked.json()["confirmations_remaining"] == 2


def test_browser_agent_blocks_loopback_urls() -> None:
    response = client.post(
        "/api/browser/read",
        json={"url": "http://127.0.0.1:9999/private"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_memory_write_succeeds_only_with_real_one_time_grant() -> None:
    key = f"assurance-{uuid4().hex}"
    blocked = client.post(
        "/api/memory/remember",
        json={
            "category": "preference-test",
            "key": key,
            "value": "réponses courtes",
            "confirmations": 2,
        },
    )
    assert blocked.status_code == 200
    assert blocked.json()["ok"] is False

    token = authorization_token("memory.remember")
    saved = client.post(
        "/api/memory/remember",
        json={
            "category": "preference-test",
            "key": key,
            "value": "réponses courtes",
            "authorization_token": token,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True
    recalled = client.get("/api/memory/recall", params={"q": key})
    assert any(item["value"] == "réponses courtes" for item in recalled.json()["results"])
